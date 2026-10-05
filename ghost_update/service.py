# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""The update service: answers POST /update on loopback, behind Caddy.

    python3 -m ghost_update.service --config /etc/ghost-update/server.json
        [--key VERSION=FILE ...]

The CUP keys default to systemd's credentials cup_keys_<version>.json
($CREDENTIALS_DIRECTORY), one per key version, so a key can be rotated while
clients still ask for the old one.
The service never sees a client's address, since Caddy proxies every request
from loopback, and it writes nothing that comes from a request.
"""

from __future__ import annotations

import argparse
import datetime
import http.server
import json
import logging
import os
import re
import sys
import urllib.parse
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec

from ghost_update import cup, manifest, protocol

MAX_BODY = 64 * 1024
log = logging.getLogger("ghost-update")


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 10
    server: Service

    def do_POST(self) -> None:
        url = urllib.parse.urlsplit(self.path)
        if url.path != "/update":
            self._send(404)
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._refuse(400, "a request without a length")
            return
        if not 0 <= length <= MAX_BODY:
            self._refuse(413, "a request body over 64 KiB")
            return
        body = self.rfile.read(length)
        cup2key = urllib.parse.parse_qs(url.query).get("cup2key", [""])[0]
        version = cup.cup2key_version(cup2key, self.server.keys)
        if version is None:
            self._refuse(400, "a request without a cup2key for a key this server has")
            return
        try:
            payload = protocol.respond(body, self.server.store.current().offers(),
                                       self.server.download_base, datetime.date.today())
        except protocol.InvalidRequest as e:
            self._refuse(400, f"an invalid request: {e}")
            return
        self._send(200, payload, {
            "Content-Type": "application/json",
            "X-Cup-Server-Proof": cup.proof(self.server.keys[version], cup2key, body, payload)})

    def do_GET(self) -> None:
        self._send(404)

    def _refuse(self, status: int, reason: str) -> None:
        log.warning("refused %s", reason)
        self.close_connection = True
        self._send(status)

    def _send(self, status: int, body: bytes = b"", headers: dict | None = None) -> None:
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        pass  # the default writes the client's address and the request line


class Service(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, store: manifest.Store,
                 keys: dict[int, ec.EllipticCurvePrivateKey], public_url: str):
        super().__init__(("127.0.0.1", port), Handler)
        self.store, self.keys = store, keys
        self.download_base = public_url.rstrip("/") + "/releases"


_CREDENTIAL = re.compile(r"^cup_keys_([1-9][0-9]{0,3})\.json$")


def credential_keys(directory: Path) -> dict[int, Path]:
    """systemd's LoadCredential=cup_keys:<dir> names each file cup_keys_<file>."""
    return {int(m.group(1)): directory / name for name in sorted(os.listdir(directory))
            if (m := _CREDENTIAL.match(name))}


def parse_key(text: str) -> tuple[int, Path]:
    version, _, path = text.partition("=")
    if not version.isdigit() or not path:
        raise ValueError(f"--key takes VERSION=FILE, not {text!r}")
    return int(version), Path(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--key", action="append", default=[],
                        help="VERSION=FILE, a CUP key (tests and development)")
    args = parser.parse_args(argv)
    if not log.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    try:
        paths = dict(parse_key(k) for k in args.key)
    except ValueError as e:
        log.error("not starting: %s", e)
        return 1
    if not paths and "CREDENTIALS_DIRECTORY" in os.environ:
        paths = credential_keys(Path(os.environ["CREDENTIALS_DIRECTORY"]))
    if not paths:
        log.error("not starting: no CUP key (--key, or systemd's LoadCredential=cup_keys)")
        return 1
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        keys = {version: cup.load_key(path) for version, path in paths.items()}
        store = manifest.Store(Path(config["releases_dir"]))
        server = Service(int(config["port"]), store, keys, config["public_url"])
    except (OSError, ValueError, KeyError) as e:
        log.error("not starting: %s", e)
        return 1
    log.info("serving on 127.0.0.1:%d", server.server_address[1])
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
