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

    python tools/deploy.py --host root@<address> --address <address> --cup-key <key file>

The first run, as root on a fresh Debian 12 server, creates the administrator `ghost` and turns off root's SSH login; later runs use `--host ghost@<address>`. Each run changes only what differs.

## Publishing a release

    python -m ghost_update.release --crx <package.crx3> --appid <app ID> --version <version> --host ghost@<address>

## Test identity

Until the final product name and production keys exist (the browser's Phase 2, sub-project D), the server uses the browser's test keys, whose private halves are public in the browser's repository. Only test machines trust them.

## License

MPL-2.0. Contributions are accepted under the [Developer Certificate of Origin](https://developercertificate.org/) (`git commit -s`).
