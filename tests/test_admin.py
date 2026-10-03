# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ghost_update import admin, manifest
from ghost_update.identity import BROWSER_APPID, UPDATER_APPID


class AdminTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        (self.dir / "staging").mkdir()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(admin.main(["--releases-dir", str(self.dir), "init"]), 0)

    def activate(self, version: str, content: bytes = b"package") -> int:
        staged = self.dir / "staging" / f"browser-{version}.crx3"
        staged.write_bytes(content)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return admin.main(["--releases-dir", str(self.dir), "activate", "--staged",
                               str(staged), "--appid", BROWSER_APPID.upper(),
                               "--version", version])

    def current(self) -> manifest.Manifest:
        return manifest.parse((self.dir / manifest.FILE_NAME).read_bytes(), self.dir)

    def test_init_creates_ghost_apps_once(self):
        self.assertEqual(self.current().releases(), {BROWSER_APPID: None, UPDATER_APPID: None})
        before = (self.dir / manifest.FILE_NAME).read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(admin.main(["--releases-dir", str(self.dir), "init"]), 0)
        self.assertEqual((self.dir / manifest.FILE_NAME).read_bytes(), before)

    def test_activate(self):
        self.assertEqual(self.activate("152.0.7977.14902"), 0)
        active = self.current().apps[BROWSER_APPID].active
        self.assertEqual(active, manifest.Release(
            "152.0.7977.14902", "c0ff4371-d9ab-461e-bffd-6b0dc2430b02-152.0.7977.14902.crx3",
            7, hashlib.sha256(b"package").hexdigest(), admin.DEFAULT_INSTALLER,
            admin.DEFAULT_ARGUMENTS))
        self.assertTrue((self.dir / active.file).is_file())
        self.assertFalse(any((self.dir / "staging").iterdir()))

    def test_activate_refuses_a_version_not_newer(self):
        self.assertEqual(self.activate("152.0.7977.14902"), 0)
        for version in ("152.0.7977.14902", "152.0.7977.14901"):
            with self.subTest(version):
                self.assertEqual(self.activate(version), 1)
                self.assertTrue((self.dir / "staging" / f"browser-{version}.crx3").exists())
        self.assertEqual(self.current().apps[BROWSER_APPID].active.version, "152.0.7977.14902")

    def test_activate_refuses_an_unknown_app_and_a_bad_version(self):
        staged = self.dir / "staging" / "x.crx3"
        staged.write_bytes(b"x")
        for appid, version in (("{00000000-0000-0000-0000-000000000000}", "1.0.0.0"),
                               (BROWSER_APPID, "1.0.0")):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(admin.main(["--releases-dir", str(self.dir), "activate",
                                             "--staged", str(staged), "--appid", appid,
                                             "--version", version]), 1)

    def test_three_releases_are_kept(self):
        for respin in range(1, 5):
            self.assertEqual(self.activate(f"152.0.7977.1490{respin}"), 0)
        entry = self.current().apps[BROWSER_APPID]
        self.assertEqual([entry.active.version] + [p.version for p in entry.previous],
                         ["152.0.7977.14904", "152.0.7977.14903", "152.0.7977.14902"])
        self.assertEqual(sorted(p.name for p in self.dir.glob("*.crx3")), sorted(
            f"c0ff4371-d9ab-461e-bffd-6b0dc2430b02-152.0.7977.1490{r}.crx3" for r in (2, 3, 4)))

    def test_list(self):
        self.activate("152.0.7977.14902")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(admin.main(["--releases-dir", str(self.dir), "list"]), 0)
        self.assertIn(f"{BROWSER_APPID}  active 152.0.7977.14902  kept none", out.getvalue())
        self.assertIn(f"{UPDATER_APPID}  active none  kept none", out.getvalue())


class FindAddressTest(unittest.TestCase):
    ADDRESS = "198.51.100.7"

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / "log").mkdir()
        (self.root / "log" / "apt.log").write_text("installed caddy\n")

    def find(self, entries):
        return admin.find_address(self.ADDRESS, roots=(self.root,), entries=entries)

    def test_nothing_found(self):
        self.assertEqual(self.find([{"_COMM": "caddy", "MESSAGE": "serving"}]), [])

    def test_administrators_records_are_skipped(self):
        message = f"Accepted publickey for ghost from {self.ADDRESS} port 51234"
        (self.root / "log" / "wtmp").write_bytes(self.ADDRESS.encode())
        self.assertEqual(self.find([{"_COMM": "sshd", "MESSAGE": message},
                                    {"_COMM": "sudo", "MESSAGE": f"COMMAND=x {self.ADDRESS}"},
                                    {"SYSLOG_IDENTIFIER": "sshd-session", "MESSAGE": message}]),
                         [])

    def test_the_journal_is_searched(self):
        found = self.find([{"_COMM": "caddy", "_SYSTEMD_UNIT": "caddy.service",
                            "MESSAGE": f"TLS handshake error from {self.ADDRESS}:51234"}])
        self.assertEqual(found, ["journal: caddy.service"])

    def test_files_are_searched(self):
        (self.root / "log" / "caddy").mkdir()
        (self.root / "log" / "caddy" / "access.log").write_text(json.dumps(
            {"request": {"remote_ip": self.ADDRESS}}))
        self.assertEqual(self.find([]), [f"file: {self.root / 'log' / 'caddy' / 'access.log'}"])

    def test_the_output_never_names_the_address(self):
        (self.root / "log" / "x.log").write_text(self.ADDRESS)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = admin.report(self.find([]))
        self.assertEqual(code, 1)
        self.assertNotIn(self.ADDRESS, out.getvalue())


if __name__ == "__main__":
    unittest.main()
