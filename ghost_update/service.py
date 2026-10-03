# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""The update service: answers POST /update on loopback, behind Caddy.

    python3 -m ghost_update.service --config /etc/ghost-update/server.json [--key FILE]

The CUP key defaults to systemd's credential "cup_key" ($CREDENTIALS_DIRECTORY).
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
        if not cup.valid_cup2key(cup2key):
            self._refuse(400, "a request without a valid cup2key")
            return
        try:
            payload = protocol.respond(body, self.server.store.current().releases(),
                                       self.server.download_base, datetime.date.today())
        except protocol.InvalidRequest as e:
            self._refuse(400, f"an invalid request: {e}")
            return
        self._send(200, payload, {
            "Content-Type": "application/json",
            "X-Cup-Server-Proof": cup.proof(self.server.key, cup2key, body, payload)})

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

    def __init__(self, port: int, store: manifest.Store, key: ec.EllipticCurvePrivateKey,
                 public_url: str):
        super().__init__(("127.0.0.1", port), Handler)
        self.store, self.key = store, key
        self.download_base = public_url.rstrip("/") + "/releases"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--key", type=Path, help="the CUP key file (tests and development)")
    args = parser.parse_args(argv)
    if not log.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    key_path = args.key
    if key_path is None and "CREDENTIALS_DIRECTORY" in os.environ:
        key_path = Path(os.environ["CREDENTIALS_DIRECTORY"]) / "cup_key"
    if key_path is None:
        log.error("not starting: no CUP key (--key, or systemd's LoadCredential=cup_key)")
        return 1
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        key = cup.load_key(key_path)
        store = manifest.Store(Path(config["releases_dir"]))
        server = Service(int(config["port"]), store, key, config["public_url"])
    except (OSError, ValueError, KeyError) as e:
        log.error("not starting: %s", e)
        return 1
    log.info("serving on 127.0.0.1:%d", server.server_address[1])
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
