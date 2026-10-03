# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import hashlib
import os
import unittest
from pathlib import Path

from ghost_update import identity
from ghost_update.reference import ecdsa_p256
from tests.helpers import CRX_KEY_FILE, FIXTURES, private_key

# Each fixture, its path in the browser's repository, and its SHA-256 there.
SOURCES = {
    "cup_test_key.json": ("test/updater/cup_test_key.json",
                          "0a9d129f7d4d6780fa2bbbf544d2c5e4dc04490b4a060a8b6f7a4ee3cc60cc0d"),
    "cup_vector.json": ("test/updater/cup_vector.json",
                        "c77fe2cb86ff269fecb1af3b2db99b6987e55fb12b24748546b783fefacc8a8e"),
    "captured_request.json": ("test/updater/captured_request.json",
                              "20deb525f5329d02d60cd490c44399cfa9e40857153d8d61d5f23035c4d97dd4"),
    "crx_test_key.json": ("test/updater/crx_test_key.json",
                          "f918a7e5f05b0c0b1a96acdb6d632bbbd9ab3db34099407e28403877a5a26052"),
}


class FixturesTest(unittest.TestCase):
    def test_fixtures_are_the_pinned_copies(self):
        for name, (_, digest) in SOURCES.items():
            with self.subTest(name):
                self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(),
                                 digest)

    def test_fixtures_match_the_browser(self):
        """Set GHOST_WEBOPS to a checkout of the browser's repository to compare."""
        webops = os.environ.get("GHOST_WEBOPS")
        if not webops:
            self.skipTest("GHOST_WEBOPS is not set")
        for name, (source, _) in SOURCES.items():
            with self.subTest(name):
                self.assertEqual((FIXTURES / name).read_bytes(),
                                 (Path(webops) / source).read_bytes())

    def test_the_publisher_key_hash_is_the_test_key(self):
        public = ecdsa_p256.spki(ecdsa_p256.public_key(private_key(CRX_KEY_FILE)))
        self.assertEqual(hashlib.sha256(public).hexdigest(), identity.PUBLISHER_KEY_SHA256)


if __name__ == "__main__":
    unittest.main()
