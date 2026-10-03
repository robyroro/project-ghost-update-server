#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""ECDSA over NIST P-256 with SHA-256, in pure Python.

For the updater's test identity only: the test server signs CUP responses
and CRX3 packages with it (Phase 2, sub-project B). Nonces follow RFC 6979,
so signatures are deterministic and testable. It is not constant-time, and
no production key ever goes through it.

Copied from the browser's tools/ at 8e5ba4f; keep the two in step.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
     0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)

# DER SubjectPublicKeyInfo of a P-256 key, up to the uncompressed point.
_SPKI_PREFIX = bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d030107034200")

Point = tuple[int, int]


def _add(p: Point | None, q: Point | None) -> Point | None:
    if p is None:
        return q
    if q is None:
        return p
    (x1, y1), (x2, y2) = p, q
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p == q:
        lam = (3 * x1 * x1 + A) * pow(2 * y1, -1, P) % P
    else:
        lam = (y2 - y1) * pow(x2 - x1, -1, P) % P
    x3 = (lam * lam - x1 - x2) % P
    return x3, (lam * (x1 - x3) - y1) % P


def _mul(k: int, p: Point) -> Point | None:
    result = None
    while k:
        if k & 1:
            result = _add(result, p)
        p = _add(p, p)
        k >>= 1
    return result


def on_curve(p: Point) -> bool:
    x, y = p
    return 0 <= x < P and 0 <= y < P and (y * y - (x * x * x + A * x + B)) % P == 0


def generate_private_key() -> int:
    return secrets.randbelow(N - 1) + 1


def public_key(d: int) -> Point:
    return _mul(d, G)


def _rfc6979_nonce(d: int, digest: bytes) -> int:
    x = d.to_bytes(32, "big")
    h = (int.from_bytes(digest, "big") % N).to_bytes(32, "big")
    v, k = b"\x01" * 32, b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        candidate = int.from_bytes(v, "big")
        if 1 <= candidate < N:
            return candidate
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def sign(d: int, message: bytes) -> tuple[int, int]:
    """ECDSA-SHA256 of `message`, as (r, s)."""
    digest = hashlib.sha256(message).digest()
    e = int.from_bytes(digest, "big") % N
    k = _rfc6979_nonce(d, digest)
    r = _mul(k, G)[0] % N
    s = pow(k, -1, N) * (e + r * d) % N
    if not r or not s:
        raise ValueError("degenerate signature; RFC 6979 makes this unreachable")
    return r, s


def verify(q: Point, message: bytes, r: int, s: int) -> bool:
    if not (1 <= r < N and 1 <= s < N):
        return False
    e = int.from_bytes(hashlib.sha256(message).digest(), "big") % N
    w = pow(s, -1, N)
    point = _add(_mul(e * w % N, G), _mul(r * w % N, q))
    return point is not None and point[0] % N == r


def _der_length(n: int) -> bytes:
    return bytes([n]) if n < 0x80 else bytes([0x81, n])


def _der_integer(v: int) -> bytes:
    body = v.to_bytes((v.bit_length() + 8) // 8 or 1, "big")
    return b"\x02" + _der_length(len(body)) + body


def der_signature(r: int, s: int) -> bytes:
    body = _der_integer(r) + _der_integer(s)
    return b"\x30" + _der_length(len(body)) + body


def parse_der_signature(der: bytes) -> tuple[int, int]:
    if der[0] != 0x30 or der[1] != len(der) - 2:
        raise ValueError("not a DER ECDSA signature")
    values, i = [], 2
    for _ in range(2):
        if der[i] != 0x02:
            raise ValueError("not a DER integer")
        length = der[i + 1]
        values.append(int.from_bytes(der[i + 2:i + 2 + length], "big"))
        i += 2 + length
    return values[0], values[1]


def spki(q: Point) -> bytes:
    return _SPKI_PREFIX + b"\x04" + q[0].to_bytes(32, "big") + q[1].to_bytes(32, "big")


def parse_spki(der: bytes) -> Point:
    if not der.startswith(_SPKI_PREFIX + b"\x04") or len(der) != len(_SPKI_PREFIX) + 65:
        raise ValueError("not a P-256 SubjectPublicKeyInfo")
    point = der[len(_SPKI_PREFIX) + 1:]
    return int.from_bytes(point[:32], "big"), int.from_bytes(point[32:], "big")
