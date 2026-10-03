# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""releases.json: the app IDs the server knows and each one's active release.

    {"apps": {"{app id}": {"active": <release> | null, "previous": [<release>, ...]}}}

A release is {"version", "file", "size", "sha256", "installer", "arguments"},
its file in the releases directory. `previous` lists up to two earlier
releases whose files stay on disk. This file is the server's whole state.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from ghost_update.protocol import InvalidRequest, Release, parse_version

FILE_NAME = "releases.json"
KEPT = 3  # the active release and two previous ones
_APPID = re.compile(r"^\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}$")
_FILE = re.compile(r"^[A-Za-z0-9._-]+\.crx3$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_FIELDS = {"version", "file", "size", "sha256", "installer", "arguments"}
log = logging.getLogger("ghost-update")


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class AppEntry:
    active: Release | None
    previous: tuple[Release, ...]


@dataclass(frozen=True)
class Manifest:
    apps: dict[str, AppEntry]  # lowercase app ID -> entry

    def releases(self) -> dict[str, Release | None]:
        return {appid: entry.active for appid, entry in self.apps.items()}


def _release(value: object, releases_dir: Path) -> Release:
    if not isinstance(value, dict) or set(value) != _RELEASE_FIELDS:
        raise ManifestError("a release has exactly: " + ", ".join(sorted(_RELEASE_FIELDS)))
    try:
        parse_version(value["version"])
    except InvalidRequest:
        raise ManifestError(f"bad version {value['version']!r}") from None
    if not isinstance(value["file"], str) or not _FILE.match(value["file"]):
        raise ManifestError(f"bad file name {value['file']!r}")
    size = value["size"]
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ManifestError(f"bad size {size!r}")
    if not isinstance(value["sha256"], str) or not _SHA256.match(value["sha256"]):
        raise ManifestError("bad sha256")
    if not isinstance(value["installer"], str) or not value["installer"]:
        raise ManifestError("bad installer")
    if not isinstance(value["arguments"], str):
        raise ManifestError("bad arguments")
    path = releases_dir / value["file"]
    if not path.is_file() or path.stat().st_size != size:
        raise ManifestError(f"{value['file']} is missing or not {size} bytes")
    return Release(**value)


def parse(data: bytes, releases_dir: Path) -> Manifest:
    try:
        doc = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise ManifestError("not JSON") from None
    apps = doc.get("apps") if isinstance(doc, dict) else None
    if not isinstance(apps, dict) or not apps:
        raise ManifestError("no apps")
    out = {}
    for appid, entry in apps.items():
        if not _APPID.match(appid):
            raise ManifestError(f"bad app ID {appid!r}: lowercase, in braces")
        if not isinstance(entry, dict) or set(entry) != {"active", "previous"}:
            raise ManifestError(f"{appid}: needs active and previous")
        previous = entry["previous"]
        if not isinstance(previous, list) or len(previous) > KEPT - 1:
            raise ManifestError(f"{appid}: previous is a list of at most {KEPT - 1}")
        active = None if entry["active"] is None else _release(entry["active"], releases_dir)
        out[appid] = AppEntry(active, tuple(_release(p, releases_dir) for p in previous))
    return Manifest(out)


def serialize(manifest: Manifest) -> bytes:
    doc = {"apps": {appid: {"active": asdict(entry.active) if entry.active else None,
                            "previous": [asdict(p) for p in entry.previous]}
                    for appid, entry in sorted(manifest.apps.items())}}
    return (json.dumps(doc, indent=2) + "\n").encode()


def write(manifest: Manifest, releases_dir: Path) -> None:
    """Writes releases.json atomically: a reader sees the old file or the new one."""
    path = releases_dir / FILE_NAME
    temporary = path.with_name(FILE_NAME + ".new")
    with open(temporary, "wb") as f:
        f.write(serialize(manifest))
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


class Store:
    """The active manifest, reloaded when releases.json changes. A new file
    that is missing or invalid is logged once, and the last good one stays."""

    def __init__(self, releases_dir: Path):
        self._dir = releases_dir
        self._path = releases_dir / FILE_NAME
        self._lock = threading.Lock()
        self._seen = self._path.stat().st_mtime_ns  # raises if missing
        self._manifest = parse(self._path.read_bytes(), releases_dir)

    def current(self) -> Manifest:
        with self._lock:
            try:
                mtime = self._path.stat().st_mtime_ns
            except OSError:
                mtime = -1
            if mtime != self._seen:
                self._seen = mtime
                try:
                    self._manifest = parse(self._path.read_bytes(), self._dir)
                    log.info("releases.json reloaded")
                except (OSError, ManifestError) as e:
                    log.error("releases.json not reloaded, keeping the last good one: %s", e)
            return self._manifest
