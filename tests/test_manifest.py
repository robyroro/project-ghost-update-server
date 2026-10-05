# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from ghost_update import manifest
from ghost_update.identity import BROWSER_APPID, UPDATER_APPID
from ghost_update.protocol import Offer, Release


def release(version: str, directory: Path, size: int = 10) -> Release:
    name = f"browser-{version}.crx3"
    (directory / name).write_bytes(b"x" * size)
    return Release(version, name, size, "ab" * 32, "mini_installer.exe", "--do-not-launch-chrome")


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)

    def test_round_trip(self):
        current = release("152.0.7977.14902", self.dir)
        older = release("152.0.7977.14901", self.dir)
        original = manifest.Manifest({BROWSER_APPID: manifest.AppEntry(current, (older,)),
                                      UPDATER_APPID: manifest.AppEntry(None, ())})
        manifest.write(original, self.dir)
        parsed = manifest.parse((self.dir / manifest.FILE_NAME).read_bytes(), self.dir)
        self.assertEqual(parsed, original)
        self.assertEqual(parsed.releases(), {BROWSER_APPID: current, UPDATER_APPID: None})
        self.assertFalse((self.dir / (manifest.FILE_NAME + ".new")).exists())

    def test_invalid_manifests(self):
        good = {"version": "152.0.7977.14902", "file": "browser-152.0.7977.14902.crx3",
                "size": 10, "sha256": "ab" * 32, "installer": "mini_installer.exe",
                "arguments": ""}
        (self.dir / good["file"]).write_bytes(b"x" * 10)
        cases = {
            "not JSON": b"{",
            "no apps": json.dumps({"apps": {}}).encode(),
            "uppercase app ID": json.dumps({"apps": {BROWSER_APPID.upper(): {
                "active": None, "previous": []}}}).encode(),
            "missing previous": json.dumps({"apps": {BROWSER_APPID: {
                "active": None}}}).encode(),
            "too many kept": json.dumps({"apps": {BROWSER_APPID: {
                "active": good, "previous": [good, good, good]}}}).encode(),
        }
        for field, value in (("version", "1.2.3"), ("file", "../etc/passwd"),
                             ("file", "browser.exe"), ("size", 11), ("size", True),
                             ("sha256", "AB" * 32), ("installer", ""), ("arguments", None)):
            cases[f"{field}={value!r}"] = json.dumps({"apps": {BROWSER_APPID: {
                "active": {**good, field: value}, "previous": []}}}).encode()
        cases["extra field"] = json.dumps({"apps": {BROWSER_APPID: {
            "active": {**good, "url": "x"}, "previous": []}}}).encode()
        for name, data in cases.items():
            with self.subTest(name):
                with self.assertRaises(manifest.ManifestError):
                    manifest.parse(data, self.dir)

    def test_a_missing_package_is_invalid(self):
        current = release("152.0.7977.14902", self.dir)
        manifest.write(manifest.Manifest({BROWSER_APPID: manifest.AppEntry(current, ())}),
                       self.dir)
        (self.dir / current.file).unlink()
        with self.assertRaises(manifest.ManifestError):
            manifest.parse((self.dir / manifest.FILE_NAME).read_bytes(), self.dir)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.first = release("152.0.7977.14901", self.dir)
        manifest.write(manifest.Manifest({BROWSER_APPID: manifest.AppEntry(self.first, ())}),
                       self.dir)
        self.store = manifest.Store(self.dir)

    def touch(self, seconds: int) -> None:
        path = self.dir / manifest.FILE_NAME
        mtime = path.stat().st_mtime_ns + seconds * 1_000_000_000
        os.utime(path, ns=(mtime, mtime))

    def test_reloads_when_the_file_changes(self):
        second = release("152.0.7977.14902", self.dir)
        manifest.write(manifest.Manifest({BROWSER_APPID: manifest.AppEntry(second, ())}),
                       self.dir)
        self.touch(5)
        self.assertEqual(self.store.current().releases()[BROWSER_APPID], second)

    def test_keeps_the_last_good_manifest(self):
        (self.dir / manifest.FILE_NAME).write_text("{")
        self.touch(5)
        with self.assertLogs("ghost-update", "ERROR") as logs:
            self.assertEqual(self.store.current().releases()[BROWSER_APPID], self.first)
        self.assertIn("keeping the last good one", logs.output[0])
        with self.assertNoLogs("ghost-update", "ERROR"):
            self.store.current()  # the same bad file is reported once

    def test_a_missing_manifest_keeps_the_last_good_one(self):
        (self.dir / manifest.FILE_NAME).unlink()
        with self.assertLogs("ghost-update", "ERROR"):
            self.assertEqual(self.store.current().releases()[BROWSER_APPID], self.first)

    def test_the_store_needs_a_valid_manifest_to_start(self):
        (self.dir / manifest.FILE_NAME).write_text("{")
        with self.assertRaises(manifest.ManifestError):
            manifest.Store(self.dir)
        (self.dir / manifest.FILE_NAME).unlink()
        with self.assertRaises(OSError):
            manifest.Store(self.dir)


class CandidateTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.active = release("152.0.7977.14902", self.dir)
        self.next = release("152.0.7977.14903", self.dir)

    def test_round_trip_and_offers(self):
        original = manifest.Manifest({
            BROWSER_APPID: manifest.AppEntry(self.active, (), manifest.Candidate(self.next, 0.05)),
            UPDATER_APPID: manifest.AppEntry(None, ())})
        manifest.write(original, self.dir)
        parsed = manifest.parse((self.dir / manifest.FILE_NAME).read_bytes(), self.dir)
        self.assertEqual(parsed, original)
        self.assertEqual(parsed.offers(), {BROWSER_APPID: Offer(self.active, self.next, 0.05),
                                           UPDATER_APPID: Offer(None)})
        doc = json.loads((self.dir / manifest.FILE_NAME).read_text())
        self.assertEqual(doc["apps"][BROWSER_APPID]["candidate"]["fraction"], 0.05)
        self.assertIsNone(doc["apps"][UPDATER_APPID]["candidate"])

    def test_a_file_without_candidates_still_parses(self):
        data = json.dumps({"apps": {BROWSER_APPID: {"active": None, "previous": []}}}).encode()
        self.assertIsNone(manifest.parse(data, self.dir).apps[BROWSER_APPID].candidate)

    def test_invalid_candidates(self):
        good = {"version": "152.0.7977.14903", "file": self.next.file, "size": 10,
                "sha256": "ab" * 32, "installer": "mini_installer.exe",
                "arguments": "--do-not-launch-chrome"}
        active = {**good, "version": "152.0.7977.14902", "file": self.active.file}
        for name, candidate in (("no fraction", good), ("fraction 2", {**good, "fraction": 2}),
                                ("fraction -0.1", {**good, "fraction": -0.1}),
                                ("fraction true", {**good, "fraction": True}),
                                ("not newer", {**active, "fraction": 0.5})):
            with self.subTest(name):
                data = json.dumps({"apps": {BROWSER_APPID: {
                    "active": active, "previous": [], "candidate": candidate}}}).encode()
                with self.assertRaises(manifest.ManifestError):
                    manifest.parse(data, self.dir)


if __name__ == "__main__":
    unittest.main()
