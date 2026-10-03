# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
import unittest

from ghost_update import cup
from ghost_update.reference import ecdsa_p256
from tests.helpers import CUP_KEY_FILE, FIXTURES, private_key, reference_verify


class CupTest(unittest.TestCase):
    def setUp(self):
        self.key = cup.load_key(CUP_KEY_FILE)
        numbers = self.key.public_key().public_numbers()
        self.public = (numbers.x, numbers.y)

    def test_the_loaded_key_is_the_test_key(self):
        self.assertEqual(self.public, ecdsa_p256.public_key(private_key(CUP_KEY_FILE)))

    def test_the_browser_vector_verifies_with_the_loaded_key(self):
        vector = json.loads((FIXTURES / "cup_vector.json").read_text())
        self.assertTrue(reference_verify(self.public, vector["cup2key"],
                                         vector["request"].encode(),
                                         vector["response"].encode(), vector["proof"]))

    def test_proofs_verify_as_the_updater_checks_them(self):
        for request, response in ((b"{}", b")]}'\n{}"), (b"x" * 5000, b"y" * 7000)):
            proof = cup.proof(self.key, "1:12345", request, response)
            self.assertTrue(reference_verify(self.public, "1:12345", request, response, proof))
            self.assertFalse(reference_verify(self.public, "1:12345", request, response + b" ",
                                              proof))
            self.assertFalse(reference_verify(self.public, "1:12346", request, response, proof))

    def test_cup2key(self):
        for good in ("1:12345", "1:SUUSbBaXj4Q5AofrKJTxPrbrwU_XSvKjCY1jp_dvqec"):
            self.assertTrue(cup.valid_cup2key(good), good)
        for bad in ("", "1", "1:", "2:12345", "x:1", "1:a b", "1:" + "a" * 129, "01:1"):
            self.assertFalse(cup.valid_cup2key(bad), bad)


if __name__ == "__main__":
    unittest.main()
