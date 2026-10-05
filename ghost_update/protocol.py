# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Omaha 4 update checks: parse a request, answer each app, build the response.

No I/O: the service passes in the request body and each app's offer.
"""

from __future__ import annotations

import datetime
import json
import random
import re
from collections.abc import Callable
from dataclasses import dataclass

RESPONSE_PREFIX = ")]}'\n"
NULL_VERSION = "0.0.0.0"  # what the updater sends for an app it is installing
_DAY_ZERO = datetime.date(2007, 1, 1)
_VERSION = re.compile(r"^[0-9]{1,9}(\.[0-9]{1,9}){3}$")


class InvalidRequest(ValueError):
    """A request the server refuses. Messages never quote client data."""


@dataclass(frozen=True)
class Release:
    version: str
    file: str
    size: int
    sha256: str
    installer: str
    arguments: str


@dataclass(frozen=True)
class Offer:
    """An app's releases: the active one, and a candidate offered to a fraction of checks.

    Requests carry no identifier, so the fraction applies to each check, not
    to a stable group of clients: at five checks a day, 0.01 reaches about 5 %
    of clients a day. 0 halts the candidate."""
    active: Release | None
    candidate: Release | None = None
    fraction: float = 0.0

    def choose(self, draw: Callable[[], float]) -> Release | None:
        if self.candidate is not None and draw() < self.fraction:
            return self.candidate
        return self.active


_RANDOM = random.SystemRandom()


def parse_version(text: object) -> tuple[int, ...]:
    if not isinstance(text, str) or not _VERSION.match(text):
        raise InvalidRequest("a version is not four dotted integers")
    return tuple(int(part) for part in text.split("."))


def parse_request(body: bytes) -> list[dict]:
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise InvalidRequest("the body is not JSON") from None
    request = data.get("request") if isinstance(data, dict) else None
    if not isinstance(request, dict):
        raise InvalidRequest("no request object")
    if request.get("protocol") != "4.0":
        raise InvalidRequest("not protocol 4.0")
    apps = request.get("apps")
    if not isinstance(apps, list) or not all(
            isinstance(app, dict) and isinstance(app.get("appid"), str) for app in apps):
        raise InvalidRequest("apps is not a list of apps with IDs")
    return apps


def answer(app: dict, offers: dict[str, Offer], download_base: str,
           draw: Callable[[], float]) -> dict:
    """One app's answer. `offers` maps lowercase app IDs to their releases."""
    appid = app["appid"]
    if appid.lower() not in offers:
        return {"appid": appid, "status": "error-unknownApplication"}
    entry: dict = {"appid": appid, "status": "ok"}
    if "updatecheck" not in app:
        return entry  # an event or a ping: acknowledged, nothing recorded
    release = offers[appid.lower()].choose(draw)
    installed = parse_version(app.get("version") or NULL_VERSION)
    if release is None or installed >= parse_version(release.version):
        entry["updatecheck"] = {"status": "noupdate"}
        return entry
    entry["updatecheck"] = {
        "status": "ok", "nextversion": release.version,
        "pipelines": [{"pipeline_id": "full", "operations": [
            {"type": "download", "size": release.size, "out": {"sha256": release.sha256},
             "urls": [{"url": f"{download_base}/{release.file}"}]},
            {"type": "crx3", "in": {"sha256": release.sha256}, "path": release.installer,
             "arguments": release.arguments}]}]}
    return entry


def respond(body: bytes, offers: dict[str, Offer], download_base: str,
            today: datetime.date, draw: Callable[[], float] = _RANDOM.random) -> bytes:
    """The response body for a request body. Raises InvalidRequest. Nothing about
    the choice is recorded."""
    apps = [answer(app, offers, download_base, draw) for app in parse_request(body)]
    response = {"response": {"protocol": "4.0", "server": "ghost",
                             "daystart": {"elapsed_days": (today - _DAY_ZERO).days},
                             "apps": apps}}
    return (RESPONSE_PREFIX + json.dumps(response, separators=(",", ":"))).encode()
