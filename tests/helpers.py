# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Shared by the tests: the fixtures and the reference CUP verifier."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ghost_update.reference import ecdsa_p256

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CUP_KEY_FILE = FIXTURES / "cup_test_key.json"
CRX_KEY_FILE = FIXTURES / "crx_test_key.json"
# RFC 6979's P-256 test key: a key Ghost's updater doesn't trust.
OTHER_KEY = 0xC9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721


def private_key(path: Path) -> int:
    return int(json.loads(path.read_text(encoding="utf-8"))["private_key"], 16)


def reference_verify(public: tuple[int, int], cup2key: str, request_body: bytes,
                     response_body: bytes, proof: str) -> bool:
    """The browser's tools/update_server.py cup_verify, as the updater checks a proof."""
    signature_hex, _, hash_hex = proof.partition(":")
    request_hash = hashlib.sha256(request_body).digest()
    if bytes.fromhex(hash_hex) != request_hash:
        return False
    inner = hashlib.sha256(request_hash + hashlib.sha256(response_body).digest()
                           + cup2key.encode()).digest()
    return ecdsa_p256.verify(public, inner,
                             *ecdsa_p256.parse_der_signature(bytes.fromhex(signature_hex)))
