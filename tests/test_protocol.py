# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import json
import unittest

from ghost_update import protocol
from ghost_update.identity import BROWSER_APPID, UPDATER_APPID
from tests.helpers import FIXTURES

TODAY = datetime.date(2026, 10, 3)
BASE = "https://203.0.113.5/releases"
RELEASE = protocol.Release("152.0.7977.14902", "browser-152.0.7977.14902.crx3", 1000, "ab" * 32,
                           "mini_installer.exe", "--verbose-logging --do-not-launch-chrome")
RELEASES = {BROWSER_APPID: protocol.Offer(RELEASE), UPDATER_APPID: protocol.Offer(None)}
CANDIDATE = protocol.Release("152.0.7977.14903", "browser-152.0.7977.14903.crx3", 2000,
                             "cd" * 32, "mini_installer.exe", "")


def answers(apps: list[dict]) -> list[dict]:
    body = json.dumps({"request": {"protocol": "4.0", "apps": apps}}).encode()
    payload = protocol.respond(body, RELEASES, BASE, TODAY)
    assert payload.startswith(b")]}'\n")
    return json.loads(payload[5:])["response"]["apps"]


class DecisionTest(unittest.TestCase):
    def test_an_older_version_gets_the_release(self):
        [app] = answers([{"appid": BROWSER_APPID, "version": "152.0.7977.14901",
                          "updatecheck": {}}])
        check = app["updatecheck"]
        self.assertEqual((app["status"], check["status"], check["nextversion"]),
                         ("ok", "ok", "152.0.7977.14902"))
        download, crx3 = check["pipelines"][0]["operations"]
        self.assertEqual(download, {
            "type": "download", "size": 1000, "out": {"sha256": "ab" * 32},
            "urls": [{"url": f"{BASE}/browser-152.0.7977.14902.crx3"}]})
        self.assertEqual(crx3, {"type": "crx3", "in": {"sha256": "ab" * 32},
                                "path": "mini_installer.exe",
                                "arguments": "--verbose-logging --do-not-launch-chrome"})

    def test_an_install_gets_the_release(self):
        for app in ({"appid": BROWSER_APPID, "version": "0.0.0.0", "updatecheck": {}},
                    {"appid": BROWSER_APPID, "version": "", "updatecheck": {}},
                    {"appid": BROWSER_APPID, "updatecheck": {}}):
            with self.subTest(app):
                self.assertEqual(answers([app])[0]["updatecheck"]["nextversion"],
                                 "152.0.7977.14902")

    def test_the_same_or_a_newer_version_gets_noupdate(self):
        for version in ("152.0.7977.14902", "152.0.7977.14903", "153.0.0.0"):
            with self.subTest(version):
                [app] = answers([{"appid": BROWSER_APPID, "version": version,
                                  "updatecheck": {}}])
                self.assertEqual(app["updatecheck"], {"status": "noupdate"})

    def test_an_app_without_a_release_gets_noupdate(self):
        [app] = answers([{"appid": UPDATER_APPID, "version": "152.0.7977.149",
                          "updatecheck": {}}])
        self.assertEqual(app, {"appid": UPDATER_APPID, "status": "ok",
                               "updatecheck": {"status": "noupdate"}})

    def test_an_unknown_app(self):
        appid = "{00000000-0000-0000-0000-000000000000}"
        self.assertEqual(answers([{"appid": appid, "version": "1.0.0.0", "updatecheck": {}}]),
                         [{"appid": appid, "status": "error-unknownApplication"}])

    def test_app_ids_match_without_case_and_are_echoed(self):
        [app] = answers([{"appid": BROWSER_APPID.upper(), "version": "1.0.0.0",
                          "updatecheck": {}}])
        self.assertEqual((app["appid"], app["updatecheck"]["status"]),
                         (BROWSER_APPID.upper(), "ok"))

    def test_an_event_is_acknowledged_with_nothing_else(self):
        self.assertEqual(answers([{"appid": BROWSER_APPID, "version": "152.0.7977.14901",
                                   "event": [{"eventtype": 3}]}]),
                         [{"appid": BROWSER_APPID, "status": "ok"}])

    def test_the_request_captured_from_the_browser(self):
        request = json.loads((FIXTURES / "captured_request.json").read_text())["request"]
        payload = protocol.respond(json.dumps(request).encode(), RELEASES, BASE, TODAY)
        [app] = json.loads(payload[5:])["response"]["apps"]
        self.assertEqual(app["updatecheck"]["nextversion"], "152.0.7977.14902")

    def test_the_response_envelope(self):
        payload = protocol.respond(b'{"request":{"protocol":"4.0","apps":[]}}', RELEASES, BASE,
                                   TODAY)
        response = json.loads(payload[5:])["response"]
        self.assertEqual(response["protocol"], "4.0")
        self.assertEqual(response["daystart"]["elapsed_days"],
                         (TODAY - datetime.date(2007, 1, 1)).days)


class InvalidRequestTest(unittest.TestCase):
    def test_invalid_requests_are_refused(self):
        def app(version):
            return json.dumps({"request": {"protocol": "4.0", "apps": [
                {"appid": BROWSER_APPID, "version": version, "updatecheck": {}}]}}).encode()
        for body in (b"not json", b"\xff", b"[]", b'{"request": []}',
                     b'{"request": {"protocol": "3.0", "apps": []}}',
                     b'{"request": {"protocol": "4.0"}}',
                     b'{"request": {"protocol": "4.0", "apps": [{"version": "1.0.0.0"}]}}',
                     app("1.2.3"), app("a.b.c.d"), app(5), app("1.2.3.4.5"), app("1.2.3.-4")):
            with self.subTest(body):
                with self.assertRaises(protocol.InvalidRequest):
                    protocol.respond(body, RELEASES, BASE, TODAY)

    def test_messages_quote_nothing_from_the_request(self):
        body = json.dumps({"request": {"protocol": "4.0", "apps": [
            {"appid": BROWSER_APPID, "version": "9.9.9.MARKER", "updatecheck": {}}]}}).encode()
        with self.assertRaises(protocol.InvalidRequest) as caught:
            protocol.respond(body, RELEASES, BASE, TODAY)
        self.assertNotIn("MARKER", str(caught.exception))


def offered(offer: protocol.Offer, version: str, draw: float) -> str:
    body = json.dumps({"request": {"protocol": "4.0", "apps": [
        {"appid": BROWSER_APPID, "version": version, "updatecheck": {}}]}}).encode()
    payload = protocol.respond(body, {BROWSER_APPID: offer}, BASE, TODAY, draw=lambda: draw)
    check = json.loads(payload[5:])["response"]["apps"][0]["updatecheck"]
    return check.get("nextversion", check["status"])


class CandidateTest(unittest.TestCase):
    def test_a_check_under_the_fraction_gets_the_candidate(self):
        offer = protocol.Offer(RELEASE, CANDIDATE, 0.05)
        self.assertEqual(offered(offer, "152.0.7977.14901", 0.04), "152.0.7977.14903")
        self.assertEqual(offered(offer, "152.0.7977.14901", 0.05), "152.0.7977.14902")

    def test_fraction_zero_offers_the_candidate_to_no_one(self):
        offer = protocol.Offer(RELEASE, CANDIDATE, 0.0)
        self.assertEqual(offered(offer, "152.0.7977.14901", 0.0), "152.0.7977.14902")

    def test_fraction_one_offers_it_to_every_check(self):
        offer = protocol.Offer(RELEASE, CANDIDATE, 1.0)
        self.assertEqual(offered(offer, "152.0.7977.14901", 0.999999), "152.0.7977.14903")

    def test_a_client_on_the_candidate_is_never_sent_back(self):
        offer = protocol.Offer(RELEASE, CANDIDATE, 0.0)
        self.assertEqual(offered(offer, "152.0.7977.14903", 0.5), "noupdate")

    def test_a_candidate_without_an_active_release(self):
        offer = protocol.Offer(None, CANDIDATE, 0.0)
        self.assertEqual(offered(offer, "152.0.7977.14901", 0.5), "noupdate")

    def test_events_draw_nothing(self):
        draws = []
        body = json.dumps({"request": {"protocol": "4.0", "apps": [
            {"appid": BROWSER_APPID, "version": "1.0.0.0", "event": []}]}}).encode()
        protocol.respond(body, RELEASES, BASE, TODAY, draw=lambda: draws.append(1) or 0.0)
        self.assertEqual(draws, [])


if __name__ == "__main__":
    unittest.main()
