# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""The identities whose packages the release CLI accepts (Phase 2). Each
matches the browser's branding/keys/<identity>.h, which tests/test_fixtures.py
checks through the copied fixtures. The final product name replaces the app
IDs."""

# SHA-256 of the DER SubjectPublicKeyInfo of the keys whose proof Ghost's
# updater accepts on packages: the primary, then the backup.
PUBLISHER_KEY_SHA256S = {
    "dev": ("c3fc14d7c68bc76a213a242a9a7395aa94f033a044ead5e3e54a0e0629330968",
            "801ca9186bd26e0c28284b853fb496ff04a869ece0ff1885126a1308e6a749b9"),
    "test": ("06c5ab97148569cf478dd0466313dd34a2d30a6c0f58386fed0992e148a8b841",
             "b88bdfbfeb6b76c6ec080a21b9895aac965114472f163e11f89c8deaf2928698"),
}

# branding/updater.gni: browser_appid and updater_appid, lowercase.
BROWSER_APPID = "{c0ff4371-d9ab-461e-bffd-6b0dc2430b02}"
UPDATER_APPID = "{4b5a3a08-578b-4b1f-8b2b-26cb99b30c4f}"
