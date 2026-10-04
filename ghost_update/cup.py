# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""CUP: signing update responses so the updater can trust them.

The updater (components/client_update_protocol/cup.cc) checks
    ECDSA-SHA256 over SHA-256(SHA-256(request) | SHA-256(response) | cup2key)
sent as X-Cup-Server-Proof: "<DER signature, hex>:<SHA-256(request), hex>".
OpenSSL signs, through `cryptography`: the browser's pure-Python signer isn't
constant-time, and a network-facing server must not leak its key in timing.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

_CUP2KEY = re.compile(r"^([1-9][0-9]{0,3}):[A-Za-z0-9_=-]{1,128}$")


def load_key(path: Path) -> ec.EllipticCurvePrivateKey:
    """A key file as the browser's tools/update_server.py writes it."""
    value = int(json.loads(Path(path).read_text(encoding="utf-8"))["private_key"], 16)
    return ec.derive_private_key(value, ec.SECP256R1())


def cup2key_version(cup2key: str, versions) -> int | None:
    """The key version `<version>:<nonce>` names, if this server has that key.

    Each client announces the key it holds; during a rotation the server has
    both, and signs each response with the one asked for."""
    match = _CUP2KEY.match(cup2key)
    if not match:
        return None
    version = int(match.group(1))
    return version if version in versions else None


def proof(key: ec.EllipticCurvePrivateKey, cup2key: str, request_body: bytes,
          response_body: bytes) -> str:
    request_hash = hashlib.sha256(request_body).digest()
    inner = hashlib.sha256(request_hash + hashlib.sha256(response_body).digest()
                           + cup2key.encode()).digest()
    signature = key.sign(inner, ec.ECDSA(hashes.SHA256()))
    return f"{signature.hex()}:{request_hash.hex()}"
