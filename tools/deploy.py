#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Deploys the update server: copies a bundle to the server, runs provision.sh.

    python tools/deploy.py --host root@203.0.113.5 --address 203.0.113.5 --cup-key FILE

The first run is as root on a fresh Debian 12 server. provision.sh creates
the administrator `ghost` and turns off root's SSH login, so later runs use
--host ghost@<address>. Each run changes only what differs.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REMOTE = "/tmp/ghost-update-deploy"
_ADDRESS = re.compile(r"^[A-Za-z0-9.-]+$")


def bundle_files(repo: Path = REPO) -> list[Path]:
    package = [p for p in (repo / "ghost_update").rglob("*.py")]
    deployment = [p for p in (repo / "deploy").iterdir() if p.is_file()]
    return sorted(p.relative_to(repo) for p in package + deployment)


def write_bundle(out: Path, cup_key: Path, repo: Path = REPO) -> Path:
    with tarfile.open(out, "w:gz") as archive:
        for rel in bundle_files(repo):
            archive.add(repo / rel, arcname=rel.as_posix())
        archive.add(cup_key, arcname="cup_key.json")
    return out


def commands(bundle: Path, host: str, address: str) -> list[list[str]]:
    if not _ADDRESS.match(address):
        raise ValueError("the address is an IPv4 address or a host name")
    remote = (f"rm -rf {REMOTE} && mkdir -m 700 {REMOTE} && tar -xzf {REMOTE}.tar.gz -C {REMOTE}"
              f" && rm {REMOTE}.tar.gz && sudo bash {REMOTE}/deploy/provision.sh --address "
              f"{address} --bundle {REMOTE}; status=$?; rm -rf {REMOTE}; exit $status")
    return [["scp", "-q", str(bundle), f"{host}:{REMOTE}.tar.gz"], ["ssh", host, remote]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", required=True, help="USER@HOST to sign in as")
    parser.add_argument("--address", required=True, help="the server's public address")
    parser.add_argument("--cup-key", type=Path, required=True,
                        help="the CUP private key file (the test identity's, for now)")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        bundle = write_bundle(Path(tmp) / "ghost-update-deploy.tar.gz", args.cup_key)
        for step in commands(bundle, args.host, args.address):
            code = subprocess.run(step).returncode
            if code:
                print(f"deploy: {step[0]} exited with {code}", file=sys.stderr)
                return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
