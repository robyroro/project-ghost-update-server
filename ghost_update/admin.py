# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Administers the server's releases; /usr/local/sbin/ghost-update-admin.

  init                       create releases.json with Ghost's app IDs, if missing
  activate --staged F --appid A --version V [--installer I] [--arguments ARGS]
                             make a staged package the app's active release
  stage --staged F --appid A --version V --fraction P [--installer I] [--arguments ARGS]
                             make a staged package the app's candidate, offered to
                             fraction P of update checks
  set-fraction --appid A --fraction P
                             the candidate's fraction
  halt --appid A             fraction 0: the candidate goes to no new client
  promote --appid A          the candidate becomes the active release
  drop --appid A             forget the candidate and delete its package
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


def _load(releases_dir: Path) -> manifest.Manifest:
    return manifest.parse((releases_dir / manifest.FILE_NAME).read_bytes(), releases_dir)


def _save(releases_dir: Path, updated: manifest.Manifest) -> None:
    manifest.parse(manifest.serialize(updated), releases_dir)  # validate before writing
    manifest.write(updated, releases_dir)


def _place(releases_dir: Path, staged: Path, appid: str, version: str, installer: str,
           arguments: str) -> Release:
    name = f"{appid.strip('{}')}-{version}.crx3"
    release = Release(version, name, staged.stat().st_size, _sha256(staged), installer,
                      arguments)
    os.replace(staged, releases_dir / name)
    return release


def _newer(version: str, entry: manifest.AppEntry) -> str | None:
    """Why the version can't follow the entry's active release, or None."""
    try:
        new = parse_version(version)
    except InvalidRequest:
        return "the version is not four dotted integers"
    if entry.active and new <= parse_version(entry.active.version):
        return f"{version} is not newer than the active {entry.active.version}"
    return None


def _without_candidate(current: manifest.Manifest, appid: str) -> manifest.AppEntry | int:
    """The app's entry, or the exit code of the refusal."""
    entry = current.apps.get(appid)
    if entry is None:
        return _error(f"unknown app {appid}")
    if entry.candidate:
        return _error(f"a candidate exists ({entry.candidate.release.version}): promote or "
                      "drop it first")
    return entry


def _with_candidate(current: manifest.Manifest, appid: str) -> manifest.AppEntry | int:
    entry = current.apps.get(appid)
    if entry is None or entry.candidate is None:
        return _error(f"{appid} has no candidate")
    return entry


def activate(releases_dir: Path, staged: Path, appid: str, version: str, installer: str,
             arguments: str) -> int:
    appid = appid.lower()
    current = _load(releases_dir)
    entry = _without_candidate(current, appid)
    if isinstance(entry, int):
        return entry
    problem = _newer(version, entry)
    if problem:
        return _error(problem)
    release = _place(releases_dir, staged, appid, version, installer, arguments)
    kept = ((entry.active,) if entry.active else ()) + entry.previous
    _save(releases_dir, manifest.Manifest({**current.apps, appid: manifest.AppEntry(
        release, kept[:manifest.KEPT - 1])}))
    for old in kept[manifest.KEPT - 1:]:
        (releases_dir / old.file).unlink(missing_ok=True)
    print(f"{appid} {version} active")
    return 0


def stage(releases_dir: Path, staged: Path, appid: str, version: str, installer: str,
          arguments: str, fraction: float) -> int:
    appid = appid.lower()
    current = _load(releases_dir)
    entry = _without_candidate(current, appid)
    if isinstance(entry, int):
        return entry
    problem = _newer(version, entry)
    if problem:
        return _error(problem)
    release = _place(releases_dir, staged, appid, version, installer, arguments)
    _save(releases_dir, manifest.Manifest({**current.apps, appid: manifest.AppEntry(
        entry.active, entry.previous, manifest.Candidate(release, fraction))}))
    print(f"{appid} {version} staged for {fraction:.0%} of update checks")
    return 0


def set_fraction(releases_dir: Path, appid: str, fraction: float, word: str = "set") -> int:
    appid = appid.lower()
    current = _load(releases_dir)
    entry = _with_candidate(current, appid)
    if isinstance(entry, int):
        return entry
    _save(releases_dir, manifest.Manifest({**current.apps, appid: manifest.AppEntry(
        entry.active, entry.previous, manifest.Candidate(entry.candidate.release, fraction))}))
    print(f"{appid} {entry.candidate.release.version} {word}: {fraction:.0%} of update checks")
    return 0


def promote(releases_dir: Path, appid: str) -> int:
    appid = appid.lower()
    current = _load(releases_dir)
    entry = _with_candidate(current, appid)
    if isinstance(entry, int):
        return entry
    kept = ((entry.active,) if entry.active else ()) + entry.previous
    _save(releases_dir, manifest.Manifest({**current.apps, appid: manifest.AppEntry(
        entry.candidate.release, kept[:manifest.KEPT - 1])}))
    for old in kept[manifest.KEPT - 1:]:
        (releases_dir / old.file).unlink(missing_ok=True)
    print(f"{appid} {entry.candidate.release.version} active")
    return 0


def drop(releases_dir: Path, appid: str) -> int:
    appid = appid.lower()
    current = _load(releases_dir)
    entry = _with_candidate(current, appid)
    if isinstance(entry, int):
        return entry
    _save(releases_dir, manifest.Manifest({**current.apps, appid: manifest.AppEntry(
        entry.active, entry.previous)}))
    (releases_dir / entry.candidate.release.file).unlink(missing_ok=True)
    print(f"{appid} {entry.candidate.release.version} dropped")
    return 0


def list_releases(releases_dir: Path) -> int:
    current = _load(releases_dir)
    for appid, entry in sorted(current.apps.items()):
        active = entry.active.version if entry.active else "none"
        kept = ", ".join(p.version for p in entry.previous) or "none"
        candidate = (f"  candidate {entry.candidate.release.version} at "
                     f"{entry.candidate.fraction:.0%}" if entry.candidate else "")
        print(f"{appid}  active {active}  kept {kept}{candidate}")
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


def _fraction(text: str) -> float:
    value = float(text)
    if not 0 <= value <= 1:
        raise argparse.ArgumentTypeError("a fraction is from 0 to 1")
    return value


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
    s = sub.add_parser("stage")
    s.add_argument("--staged", type=Path, required=True)
    s.add_argument("--appid", required=True)
    s.add_argument("--version", required=True)
    s.add_argument("--fraction", type=_fraction, required=True)
    s.add_argument("--installer", default=DEFAULT_INSTALLER)
    s.add_argument("--arguments", default=DEFAULT_ARGUMENTS)
    f = sub.add_parser("set-fraction")
    f.add_argument("--appid", required=True)
    f.add_argument("--fraction", type=_fraction, required=True)
    for name in ("halt", "promote", "drop"):
        sub.add_parser(name).add_argument("--appid", required=True)
    sub.add_parser("list")
    fa = sub.add_parser("find-address")
    fa.add_argument("address")
    args = parser.parse_args(argv)
    if args.command == "init":
        return init(args.releases_dir)
    if args.command == "activate":
        return activate(args.releases_dir, args.staged, args.appid, args.version,
                        args.installer, args.arguments)
    if args.command == "stage":
        return stage(args.releases_dir, args.staged, args.appid, args.version, args.installer,
                     args.arguments, args.fraction)
    if args.command == "set-fraction":
        return set_fraction(args.releases_dir, args.appid, args.fraction)
    if args.command == "halt":
        return set_fraction(args.releases_dir, args.appid, 0.0, word="halted")
    if args.command == "promote":
        return promote(args.releases_dir, args.appid)
    if args.command == "drop":
        return drop(args.releases_dir, args.appid)
    if args.command == "list":
        return list_releases(args.releases_dir)
    return report(find_address(args.address))


if __name__ == "__main__":
    sys.exit(main())
