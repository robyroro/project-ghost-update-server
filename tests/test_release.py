# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import unittest
from pathlib import Path

from ghost_update import release
from ghost_update.identity import BROWSER_APPID
from ghost_update.reference import crx3
from tests.helpers import CRX_KEY_FILE, OTHER_KEY, private_key


class CheckPackageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = {"mini_installer.exe": b"MZ installer"}
        cls.good = crx3.build(cls.files, private_key(CRX_KEY_FILE))

    def test_a_package_by_ghosts_publisher_key_passes(self):
        release.check_package(self.good, "mini_installer.exe", "dev")

    def test_refusals(self):
        cases = {
            "another key": (crx3.build(self.files, OTHER_KEY), "mini_installer.exe"),
            "no installer": (self.good, "setup.exe"),
            "not a CRX3": (b"PK\x03\x04", "mini_installer.exe"),
            "truncated": (self.good[:40], "mini_installer.exe"),
            "a changed archive": (self.good[:-1] + bytes([self.good[-1] ^ 1]),
                                  "mini_installer.exe"),
        }
        for name, (data, installer) in cases.items():
            with self.subTest(name):
                with self.assertRaises(release.ReleaseError):
                    release.check_package(data, installer, "dev")

    def test_a_development_package_is_refused_for_the_test_identity(self):
        with self.assertRaises(release.ReleaseError):
            release.check_package(self.good, "mini_installer.exe", "test")


class CommandsTest(unittest.TestCase):
    def test_upload_then_activate(self):
        staged = "/srv/releases/staging/c0ff4371-d9ab-461e-bffd-6b0dc2430b02-152.0.7977.14902.crx3"
        self.assertEqual(
            release.commands(Path("update.crx3"), BROWSER_APPID, "152.0.7977.14902",
                             "ghost@203.0.113.5", "mini_installer.exe",
                             "--verbose-logging --do-not-launch-chrome"),
            [["scp", "-q", "update.crx3", f"ghost@203.0.113.5:{staged}"],
             ["ssh", "ghost@203.0.113.5",
              f"sudo ghost-update-admin activate --staged {staged} --appid "
              "'{c0ff4371-d9ab-461e-bffd-6b0dc2430b02}' --version 152.0.7977.14902 "
              "--installer mini_installer.exe "
              "--arguments '--verbose-logging --do-not-launch-chrome'"]])

    def test_a_bad_version_or_app_id_is_refused(self):
        for appid, version in ((BROWSER_APPID, "1.2.3"), ("{x}", "1.2.3.4"),
                               (BROWSER_APPID + ";rm", "1.2.3.4")):
            with self.subTest((appid, version)):
                with self.assertRaises(release.ReleaseError):
                    release.commands(Path("u.crx3"), appid, version, "ghost@h",
                                     "mini_installer.exe", "")


if __name__ == "__main__":
    unittest.main()
