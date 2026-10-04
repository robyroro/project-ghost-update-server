# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import contextlib
import hashlib
import http.client
import io
import json
import logging
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives.asymmetric import ec

from ghost_update import cup, manifest, service
from ghost_update.identity import BROWSER_APPID, UPDATER_APPID
from ghost_update.protocol import Release
from tests.helpers import CUP_KEY_FILE, reference_verify

SESSION_MARKER = "{5e55104e-0000-4000-8000-00000000f00d}"
REQUEST_MARKER = "{12e90e57-0000-4000-8000-00000000beef}"


def request_body(version: str) -> bytes:
    return json.dumps({"request": {
        "protocol": "4.0", "sessionid": SESSION_MARKER, "requestid": REQUEST_MARKER,
        "apps": [{"appid": BROWSER_APPID, "version": version, "updatecheck": {}}]}}).encode()


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.publish("152.0.7977.14902")
        self.key = cup.load_key(CUP_KEY_FILE)
        numbers = self.key.public_key().public_numbers()
        self.public = (numbers.x, numbers.y)
        # The fixtures hold one CUP key; a second version is made here.
        self.other = ec.generate_private_key(ec.SECP256R1())
        self.service = service.Service(0, manifest.Store(self.dir),
                                       {1: self.key, 2: self.other}, "https://203.0.113.5")
        threading.Thread(target=self.service.serve_forever, daemon=True).start()
        self.addCleanup(self.service.server_close)
        self.addCleanup(self.service.shutdown)

    def publish(self, version: str) -> None:
        name = f"browser-{version}.crx3"
        (self.dir / name).write_bytes(b"x" * 100)
        release = Release(version, name, 100, hashlib.sha256(b"x" * 100).hexdigest(),
                          "mini_installer.exe", "--do-not-launch-chrome")
        manifest.write(manifest.Manifest({BROWSER_APPID: manifest.AppEntry(release, ()),
                                          UPDATER_APPID: manifest.AppEntry(None, ())}),
                       self.dir)

    def post(self, body: bytes, query: str = "cup2key=1:12345", path: str = "/update"):
        conn = http.client.HTTPConnection("127.0.0.1", self.service.server_address[1],
                                          timeout=10)
        conn.request("POST", f"{path}?{query}" if query else path, body=body)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, response.getheader("X-Cup-Server-Proof"), data

    def test_an_update_is_offered_and_signed(self):
        body = request_body("152.0.7977.14901")
        status, proof, data = self.post(body)
        self.assertEqual(status, 200)
        self.assertTrue(reference_verify(self.public, "1:12345", body, data, proof))
        [app] = json.loads(data[5:])["response"]["apps"]
        self.assertEqual(app["updatecheck"]["pipelines"][0]["operations"][0]["urls"],
                         [{"url": "https://203.0.113.5/releases/browser-152.0.7977.14902.crx3"}])

    def test_refusals(self):
        cases = {
            "no cup2key": (request_body("1.0.0.0"), "", "/update", 400),
            "a key version the server lacks": (request_body("1.0.0.0"), "cup2key=3:12345",
                                               "/update", 400),
            "invalid request": (b"{", "cup2key=1:12345", "/update", 400),
            "another path": (request_body("1.0.0.0"), "cup2key=1:12345", "/other", 404),
        }
        for name, (body, query, path, expected) in cases.items():
            with self.subTest(name):
                status, proof, data = self.post(body, query, path)
                self.assertEqual((status, proof, data), (expected, None, b""))

    def test_an_oversized_body_is_refused_unread(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.service.server_address[1],
                                          timeout=10)
        conn.putrequest("POST", "/update?cup2key=1:12345")
        conn.putheader("Content-Length", str(service.MAX_BODY + 1))
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 413)
        conn.close()

    def test_get_is_not_served(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.service.server_address[1],
                                          timeout=10)
        conn.request("GET", "/update")
        self.assertEqual(conn.getresponse().status, 404)
        conn.close()

    def test_a_new_release_is_picked_up(self):
        self.publish("152.0.7977.14903")
        path = self.dir / manifest.FILE_NAME
        mtime = path.stat().st_mtime_ns + 5_000_000_000
        os.utime(path, ns=(mtime, mtime))
        _, _, data = self.post(request_body("152.0.7977.14901"))
        [app] = json.loads(data[5:])["response"]["apps"]
        self.assertEqual(app["updatecheck"]["nextversion"], "152.0.7977.14903")

    def test_nothing_from_a_request_is_written(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger("ghost-update")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        self.addCleanup(logger.setLevel, logging.NOTSET)
        self.addCleanup(logger.removeHandler, handler)
        with contextlib.redirect_stderr(stream):
            self.post(request_body("152.0.7977.14901"))
            self.post(request_body("9.9.9"))                     # an invalid version
            self.post(request_body("152.0.7977.14901"), query="")  # no cup2key
        written = stream.getvalue()
        self.assertIn("refused", written)  # the capture works
        self.assertNotIn(SESSION_MARKER, written)
        self.assertNotIn(REQUEST_MARKER, written)
        self.assertNotIn("127.0.0.1", written)

    def test_each_key_version_signs_its_own_requests(self):
        numbers = self.other.public_key().public_numbers()
        body = request_body("152.0.7977.14901")
        status, proof, data = self.post(body, "cup2key=2:777")
        self.assertEqual(status, 200)
        self.assertTrue(reference_verify((numbers.x, numbers.y), "2:777", body, data, proof))
        self.assertFalse(reference_verify(self.public, "2:777", body, data, proof))

    def test_an_unknown_key_version_is_refused(self):
        with self.assertLogs("ghost-update", "WARNING"):
            status, _, _ = self.post(request_body("152.0.7977.14901"), "cup2key=3:777")
        self.assertEqual(status, 400)


class MainTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.config = self.dir / "server.json"
        self.config.write_text(json.dumps({"port": 0, "public_url": "https://203.0.113.5",
                                           "releases_dir": str(self.dir)}))

    def test_no_key_no_start(self):
        manifest.write(manifest.Manifest({UPDATER_APPID: manifest.AppEntry(None, ())}),
                       self.dir)
        with mock.patch.dict(os.environ):
            os.environ.pop("CREDENTIALS_DIRECTORY", None)
            with self.assertLogs("ghost-update", "ERROR"):
                self.assertEqual(service.main(["--config", str(self.config)]), 1)

    def test_no_valid_manifest_no_start(self):
        (self.dir / manifest.FILE_NAME).write_text("{")
        with self.assertLogs("ghost-update", "ERROR"):
            self.assertEqual(service.main(["--config", str(self.config),
                                           "--key", f"1={CUP_KEY_FILE}"]), 1)

    def test_keys_from_systemd_credentials(self):
        creds = self.dir / "creds"
        creds.mkdir()
        shutil.copy(CUP_KEY_FILE, creds / "cup_keys_1.json")
        (creds / "unrelated").write_text("x")
        self.assertEqual(service.credential_keys(creds), {1: creds / "cup_keys_1.json"})

    def test_a_key_argument_names_its_version(self):
        self.assertEqual(service.parse_key("2=k.json"), (2, Path("k.json")))
        for bad in ("k.json", "x=k.json", "2="):
            with self.assertRaises(ValueError):
                service.parse_key(bad)


if __name__ == "__main__":
    unittest.main()
