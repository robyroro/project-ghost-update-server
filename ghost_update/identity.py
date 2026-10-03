# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""The test identity (Phase 2). Sub-project D replaces the keys; the final
product name replaces the app IDs. Each value matches the browser's
branding/ files, which tests/test_fixtures.py checks through the copied keys."""

# The CUP key version the updater announces in cup2key (branding/cup_key.h).
CUP_KEY_VERSION = 1

# SHA-256 of the DER SubjectPublicKeyInfo of the key whose proof Ghost's
# updater requires on packages (branding/crx_publisher_key.h).
PUBLISHER_KEY_SHA256 = "c3fc14d7c68bc76a213a242a9a7395aa94f033a044ead5e3e54a0e0629330968"

# branding/updater.gni: browser_appid and updater_appid, lowercase.
BROWSER_APPID = "{c0ff4371-d9ab-461e-bffd-6b0dc2430b02}"
UPDATER_APPID = "{4b5a3a08-578b-4b1f-8b2b-26cb99b30c4f}"
