# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Administers the server's releases; /usr/local/sbin/ghost-update-admin.

  init                       create releases.json with Ghost's app IDs, if missing
  activate --staged F --appid A --version V [--installer I] [--arguments ARGS]
                             make a staged package the app's active release
  list                       each app's active and kept releases
  find-address ADDRESS       search the server's logs and data for an address;
                             exits 1 if found, without printing it
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from ghost_update import identity, manifest
from ghost_update.protocol import InvalidRequest, Release, parse_version

DEFAULT_DIR = Path("/srv/releases")
DEFAULT_INSTALLER = "mini_installer.exe"
DEFAULT_ARGUMENTS = "--verbose-logging --do-not-launch-chrome"
SEARCH_ROOTS = (Path("/var/log"), Path("/var/lib/caddy"), Path("/srv"))
# Records of the administrators' own logins and commands, not of browser users.
ADMIN_PROGRAMS = {"sshd", "sshd-session", "sudo", "systemd-logind"}
ADMIN_FILES = {"wtmp", "btmp", "lastlog"}


def _error(message: str) -> int:
    print(f"ghost-update-admin: {message}", file=sys.stderr)
    return 1


def init(releases_dir: Path) -> int:
    if (releases_dir / manifest.FILE_NAME).exists():
        print("releases.json exists; unchanged")
        return 0
    manifest.write(manifest.Manifest({
        identity.BROWSER_APPID: manifest.AppEntry(None, ()),
        identity.UPDATER_APPID: manifest.AppEntry(None, ())}), releases_dir)
    print("releases.json created")
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def activate(releases_dir: Path, staged: Path, appid: str, version: str, installer: str,
             arguments: str) -> int:
    appid = appid.lower()
    current = manifest.parse((releases_dir / manifest.FILE_NAME).read_bytes(), releases_dir)
    if appid not in current.apps:
        return _error(f"unknown app {appid}")
    try:
        new_version = parse_version(version)
    except InvalidRequest:
        return _error("the version is not four dotted integers")
    entry = current.apps[appid]
    if entry.active and new_version <= parse_version(entry.active.version):
        return _error(f"{version} is not newer than the active {entry.active.version}")
    name = f"{appid.strip('{}')}-{version}.crx3"
    release = Release(version, name, staged.stat().st_size, _sha256(staged), installer,
                      arguments)
    os.replace(staged, releases_dir / name)
    kept = ((entry.active,) if entry.active else ()) + entry.previous
    updated = manifest.Manifest({**current.apps, appid: manifest.AppEntry(
        release, kept[:manifest.KEPT - 1])})
    manifest.parse(manifest.serialize(updated), releases_dir)  # validate before writing
    manifest.write(updated, releases_dir)
    for old in kept[manifest.KEPT - 1:]:
        (releases_dir / old.file).unlink(missing_ok=True)
    print(f"{appid} {version} active")
    return 0


def list_releases(releases_dir: Path) -> int:
    current = manifest.parse((releases_dir / manifest.FILE_NAME).read_bytes(), releases_dir)
    for appid, entry in sorted(current.apps.items()):
        active = entry.active.version if entry.active else "none"
        kept = ", ".join(p.version for p in entry.previous) or "none"
        print(f"{appid}  active {active}  kept {kept}")
    return 0


def journal() -> Iterable[dict]:
    out = subprocess.run(["journalctl", "-o", "json", "--no-pager"], capture_output=True,
                         text=True, check=True).stdout
    for line in out.splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


def find_address(address: str, roots: Iterable[Path] = SEARCH_ROOTS,
                 entries: Iterable[dict] | None = None) -> list[str]:
    """Where the address appears, outside the administrators' own records."""
    found = []
    for entry in journal() if entries is None else entries:
        if {entry.get("_COMM"), entry.get("SYSLOG_IDENTIFIER")} & ADMIN_PROGRAMS:
            continue
        if address in json.dumps(entry):
            found.append("journal: " + str(entry.get("_SYSTEMD_UNIT")
                                           or entry.get("SYSLOG_IDENTIFIER") or "?"))
    needle = address.encode()
    for root in roots:
        for path in sorted(root.rglob("*")) if root.is_dir() else ():
            if (path.name in ADMIN_FILES or "journal" in path.parts or path.is_symlink()
                    or not path.is_file()):
                continue
            try:
                if needle in path.read_bytes():
                    found.append(f"file: {path}")
            except OSError:
                continue
    return sorted(set(found))


def report(found: list[str]) -> int:
    if not found:
        print("no record of the address")
        return 0
    for place in found:
        print(f"found in {place}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ghost-update-admin",
                                     description=__doc__.splitlines()[0])
    parser.add_argument("--releases-dir", type=Path, default=DEFAULT_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    a = sub.add_parser("activate")
    a.add_argument("--staged", type=Path, required=True)
    a.add_argument("--appid", required=True)
    a.add_argument("--version", required=True)
    a.add_argument("--installer", default=DEFAULT_INSTALLER)
    a.add_argument("--arguments", default=DEFAULT_ARGUMENTS)
    sub.add_parser("list")
    f = sub.add_parser("find-address")
    f.add_argument("address")
    args = parser.parse_args(argv)
    if args.command == "init":
        return init(args.releases_dir)
    if args.command == "activate":
        return activate(args.releases_dir, args.staged, args.appid, args.version,
                        args.installer, args.arguments)
    if args.command == "list":
        return list_releases(args.releases_dir)
    return report(find_address(args.address))


if __name__ == "__main__":
    sys.exit(main())
