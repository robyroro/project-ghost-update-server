# Project Ghost update server

The update server of [Project Ghost](https://github.com/robyroro/project-ghost), a privacy-first browser built on Chromium. It answers the browser updater's Omaha 4 checks with CUP-signed responses, serves the release packages, and keeps no record of who asked.

- **Design:** [the update server's design](https://github.com/robyroro/project-ghost/blob/main/docs/superpowers/specs/2026-10-03-update-server-design.md), in the browser's repository.
- **What the browser sends:** [the update request](https://github.com/robyroro/project-ghost/blob/main/docs/privacy-model.md#the-update-request).

## Layout

| Path | What it is |
|---|---|
| `ghost_update/` | The service, `ghost-update-admin`, and the release CLI |
| `deploy/` | Provisioning of a Debian 12 server: Caddy, nftables, systemd |
| `tools/deploy.py` | Deploys to a server from the build machine |
| `tests/` | Tests; `tests/fixtures/` holds files copied from the browser's repository |

## Tests

    python -m pip install cryptography
    python -m unittest discover -s tests -t . -v
    python tools/lint.py

## Deploying

    python tools/deploy.py --host root@<address> --address <address> --cup-key <version>=<key file>

The first run, as root on a fresh Debian 12 server, creates the administrator `ghost` and turns off root's SSH login; later runs use `--host ghost@<address>`. Each run changes only what differs.

Each `--cup-key` is one CUP key and the version clients announce for it in `cup2key`. During a rotation the server holds both versions and signs each response with the one asked for; a later deployment without the old version removes it.

## Publishing a release

    python -m ghost_update.release --crx <package.crx3> --appid <app ID> --version <version> --identity test --host ghost@<address>

The package must carry a proof by one of the identity's publisher keys, the primary or the backup.

## Rolling a release out

With `--fraction F`, the release CLI uploads the package as the app's **candidate**, beside the active release. The server offers it to fraction F of update checks: requests carry no identifier, so each check draws on its own, and at about five checks a day F = 0.01 reaches about 5 % of clients a day. Then, on the server:

    sudo ghost-update-admin set-fraction --appid <app ID> --fraction 0.1
    sudo ghost-update-admin halt --appid <app ID>       # fraction 0: no new client gets it
    sudo ghost-update-admin promote --appid <app ID>    # it becomes the active release
    sudo ghost-update-admin drop --appid <app ID>       # forget it and delete its package

The browser's `tools/release.py rollout|halt|promote|drop --host <host>` runs these over SSH. A client is never offered a version older than its own, so a halted release stays on the clients that took it.

## Test identity

Until the final product name and production keys exist, the server runs the browser's test identity: CUP key version 2 and the publisher keys from its key ceremony (the browser's `docs/signing/`). The development identity's keys, whose private halves are public in the browser's repository, serve the tests. Only test machines trust either.

## License

MPL-2.0. Contributions are accepted under the [Developer Certificate of Origin](https://developercertificate.org/) (`git commit -s`).
