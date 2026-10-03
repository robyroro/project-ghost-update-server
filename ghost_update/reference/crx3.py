#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""CRX3 packages, as components/crx_file/crx3.proto describes them.

    "Cr24" | version 3 (LE32) | header size (LE32) | CrxFileHeader | zip

Each proof signs "CRX3 SignedData\\x00" | LE32 size | signed header data | zip.
Packages built here carry one ECDSA proof, whose key is both the developer
key (it names the CRX) and the publisher key Ghost's updater requires.

Copied from the browser's tools/ at 8e5ba4f; keep the two in step.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass

from ghost_update.reference import ecdsa_p256

MAGIC = b"Cr24"
_SIGNATURE_CONTEXT = b"CRX3 SignedData\x00"
_SHA256_WITH_ECDSA = 3
_SIGNED_HEADER_DATA = 10000


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte, n = n & 0x7F, n >> 7
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(number: int, payload: bytes) -> bytes:
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def _read_varint(data: bytes, i: int) -> tuple[int, int]:
    value, shift = 0, 0
    while True:
        byte = data[i]
        value |= (byte & 0x7F) << shift
        i, shift = i + 1, shift + 7
        if not byte & 0x80:
            return value, i


def _fields(data: bytes) -> list[tuple[int, bytes]]:
    out, i = [], 0
    while i < len(data):
        tag, i = _read_varint(data, i)
        if tag & 7 != 2:
            raise ValueError("unexpected protobuf wire type")
        length, i = _read_varint(data, i)
        out.append((tag >> 3, data[i:i + length]))
        i += length
    return out


def crx_id(public_key_der: bytes) -> bytes:
    return hashlib.sha256(public_key_der).digest()[:16]


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, files[name])
    return buffer.getvalue()


def _signed_message(signed_data: bytes, archive: bytes) -> bytes:
    return _SIGNATURE_CONTEXT + len(signed_data).to_bytes(4, "little") + signed_data + archive


def build(files: dict[str, bytes], private_key: int) -> bytes:
    public_der = ecdsa_p256.spki(ecdsa_p256.public_key(private_key))
    signed_data = _field(1, crx_id(public_der))
    archive = _zip(files)
    signature = ecdsa_p256.der_signature(
        *ecdsa_p256.sign(private_key, _signed_message(signed_data, archive)))
    header = (_field(_SHA256_WITH_ECDSA, _field(1, public_der) + _field(2, signature))
              + _field(_SIGNED_HEADER_DATA, signed_data))
    return (MAGIC + (3).to_bytes(4, "little") + len(header).to_bytes(4, "little")
            + header + archive)


@dataclass(frozen=True)
class Package:
    proofs: list[tuple[bytes, bytes]]  # (public key DER, signature DER)
    signed_data: bytes
    crx_id: bytes
    archive: bytes


def parse(data: bytes) -> Package:
    if data[:4] != MAGIC or int.from_bytes(data[4:8], "little") != 3:
        raise ValueError("not a CRX3 package")
    size = int.from_bytes(data[8:12], "little")
    header, archive = data[12:12 + size], data[12 + size:]
    proofs, signed_data = [], b""
    for number, payload in _fields(header):
        if number == _SHA256_WITH_ECDSA:
            proof = dict(_fields(payload))
            proofs.append((proof.get(1, b""), proof.get(2, b"")))
        elif number == _SIGNED_HEADER_DATA:
            signed_data = payload
    return Package(proofs, signed_data, dict(_fields(signed_data)).get(1, b""), archive)


def verified_keys(data: bytes) -> list[bytes]:
    """The public keys whose proofs verify, as the updater would check them."""
    package = parse(data)
    message = _signed_message(package.signed_data, package.archive)
    keys = []
    for public_der, signature in package.proofs:
        try:
            ok = ecdsa_p256.verify(ecdsa_p256.parse_spki(public_der), message,
                                   *ecdsa_p256.parse_der_signature(signature))
        except (ValueError, IndexError):
            ok = False
        if ok:
            keys.append(public_der)
    return keys
