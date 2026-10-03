# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
import re
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"


def read(name: str) -> str:
    return (DEPLOY / name).read_text(encoding="utf-8")


class CaddyfileTest(unittest.TestCase):
    def setUp(self):
        self.text = read("Caddyfile")
        self.lines = [line.strip() for line in self.text.splitlines()
                      if line.strip() and not line.strip().startswith("#")]

    def test_no_access_log(self):
        # The only `log` is the global default logger; a site-level `log` is an access log.
        self.assertEqual([line for line in self.lines if re.match(r"^log\b", line)],
                         ["log default {"])

    def test_server_logs_carry_no_request_fields(self):
        self.assertIn("exclude http.log.access http.log.error http.handlers.reverse_proxy "
                      "http.stdlib", self.lines)

    def test_the_proxy_passes_no_client_address(self):
        for header in ("X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host"):
            self.assertIn(f"header_up -{header}", self.lines)
        self.assertIn("reverse_proxy 127.0.0.1:8484 {", self.lines)

    def test_only_packages_are_served(self):
        self.assertIn(r"@package path_regexp ^/[A-Za-z0-9._-]+\.crx3$", self.lines)
        self.assertIn("file_server @package {", self.lines)

    def test_tls_and_admin(self):
        for line in ("admin off", "skip_install_trust", "tls internal", "https://@ADDRESS@ {"):
            self.assertIn(line, self.lines)


class UnitTest(unittest.TestCase):
    def test_hardening(self):
        lines = set(read("ghost-update.service").splitlines())
        for line in ("DynamicUser=yes", "ProtectSystem=strict", "ProtectHome=yes",
                     "PrivateTmp=yes", "PrivateDevices=yes", "NoNewPrivileges=yes",
                     "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX",
                     "SystemCallFilter=@system-service", "CapabilityBoundingSet=",
                     "ReadOnlyPaths=/srv/releases",
                     "LoadCredential=cup_key:/etc/ghost-update/cup_key.json",
                     "ExecStart=/usr/bin/python3 -m ghost_update.service "
                     "--config /etc/ghost-update/server.json"):
            self.assertIn(line, lines)


class FirewallTest(unittest.TestCase):
    def test_rules(self):
        text = read("nftables.conf")
        self.assertIn("policy drop;", text)
        self.assertIn("tcp dport 22 ct state new accept", text)
        self.assertIn("tcp dport { 80, 443 } ct state new accept", text)
        self.assertEqual(text.count("timeout 60s"), 2)  # both meters forget after a minute
        rules = [line for line in text.splitlines() if not line.strip().startswith("#")]
        self.assertEqual([line for line in rules if re.search(r"\blog\b", line)], [])


class ConfigTest(unittest.TestCase):
    def test_server_json(self):
        config = json.loads(read("server.json"))
        self.assertEqual(config, {"port": 8484, "public_url": "https://@ADDRESS@",
                                  "releases_dir": "/srv/releases"})

    def test_ssh(self):
        lines = set(read("sshd.conf").splitlines())
        for line in ("PermitRootLogin no", "PasswordAuthentication no",
                     "KbdInteractiveAuthentication no", "AllowUsers ghost"):
            self.assertIn(line, lines)


if __name__ == "__main__":
    unittest.main()
