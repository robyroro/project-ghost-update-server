# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from tests.helpers import CUP_KEY_FILE
from tools import deploy


class BundleTest(unittest.TestCase):
    def test_the_bundle_holds_the_package_the_deployment_and_the_key(self):
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out)
        bundle = deploy.write_bundle(out / "bundle.tar.gz", CUP_KEY_FILE)
        with tarfile.open(bundle) as archive:
            names = set(archive.getnames())
        for name in ("ghost_update/service.py", "ghost_update/reference/crx3.py",
                     "deploy/provision.sh", "deploy/Caddyfile", "cup_key.json"):
            self.assertIn(name, names)
        self.assertFalse([n for n in names if "__pycache__" in n or n.startswith("tests/")])


class CommandsTest(unittest.TestCase):
    def test_copy_then_provision(self):
        remote = deploy.REMOTE
        self.assertEqual(deploy.commands(Path("b.tar.gz"), "root@203.0.113.5", "203.0.113.5"), [
            ["scp", "-q", "b.tar.gz", f"root@203.0.113.5:{remote}.tar.gz"],
            ["ssh", "root@203.0.113.5",
             f"rm -rf {remote} && mkdir -m 700 {remote} && tar -xzf {remote}.tar.gz -C {remote}"
             f" && rm {remote}.tar.gz && sudo bash {remote}/deploy/provision.sh --address "
             f"203.0.113.5 --bundle {remote}; status=$?; rm -rf {remote}; exit $status"]])

    def test_a_bad_address_is_refused(self):
        for address in ("203.0.113.5;rm -rf /", "", "a b"):
            with self.subTest(address):
                with self.assertRaises(ValueError):
                    deploy.commands(Path("b.tar.gz"), "root@h", address)


class ProvisionScriptTest(unittest.TestCase):
    def test_syntax(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("no bash")
        script = Path(deploy.REPO) / "deploy" / "provision.sh"
        result = subprocess.run([bash, "-n", str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
