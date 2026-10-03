# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Publishes a release: checks a CRX3 here, uploads it, activates it.

    python -m ghost_update.release --crx F --appid A --version V --host USER@HOST
           [--installer mini_installer.exe] [--arguments ARGS]

Runs on the build machine with the system's ssh and scp. The package must
carry a valid proof by Ghost's publisher key and contain its installer; the
server's ghost-update-admin then refuses a version that isn't newer.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import shlex
import subprocess
import sys
import zipfile
from pathlib import Path

from ghost_update import admin, identity
from ghost_update.protocol import InvalidRequest, parse_version
from ghost_update.reference import crx3

STAGING = "/srv/releases/staging"
_APPID = re.compile(r"^\{[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                    r"[0-9a-fA-F]{12}\}$")


class ReleaseError(ValueError):
    pass


def check_package(data: bytes, installer: str,
                  publisher_key_sha256: str = identity.PUBLISHER_KEY_SHA256) -> None:
    try:
        keys = crx3.verified_keys(data)
        archive = crx3.parse(data).archive
    except (ValueError, IndexError):
        raise ReleaseError("not a CRX3 package") from None
    if not any(hashlib.sha256(key).hexdigest() == publisher_key_sha256 for key in keys):
        raise ReleaseError("no valid proof by Ghost's publisher key")
    try:
        names = zipfile.ZipFile(io.BytesIO(archive)).namelist()
    except zipfile.BadZipFile:
        raise ReleaseError("the package holds no zip archive") from None
    if installer not in names:
        raise ReleaseError(f"the package doesn't contain {installer}")


def commands(crx: Path, appid: str, version: str, host: str, installer: str,
             arguments: str) -> list[list[str]]:
    if not _APPID.match(appid):
        raise ReleaseError("the app ID is not a GUID in braces")
    try:
        parse_version(version)
    except InvalidRequest:
        raise ReleaseError("the version is not four dotted integers") from None
    staged = f"{STAGING}/{appid.strip('{}').lower()}-{version}.crx3"
    activate = ["sudo", "ghost-update-admin", "activate", "--staged", staged, "--appid", appid,
                "--version", version, "--installer", installer, "--arguments", arguments]
    return [["scp", "-q", str(crx), f"{host}:{staged}"], ["ssh", host, shlex.join(activate)]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--crx", type=Path, required=True)
    parser.add_argument("--appid", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--host", required=True, help="USER@HOST of the server")
    parser.add_argument("--installer", default=admin.DEFAULT_INSTALLER)
    parser.add_argument("--arguments", default=admin.DEFAULT_ARGUMENTS)
    args = parser.parse_args(argv)
    try:
        steps = commands(args.crx, args.appid, args.version, args.host, args.installer,
                         args.arguments)
        check_package(args.crx.read_bytes(), args.installer)
    except (OSError, ReleaseError) as e:
        print(f"release: {e}", file=sys.stderr)
        return 1
    for step in steps:
        if subprocess.run(step).returncode:
            print(f"release: failed: {step[0]}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
