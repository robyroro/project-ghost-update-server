# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import unittest

from tools import lint


class LintTest(unittest.TestCase):
    def test_notice_found_in_any_comment_style(self):
        notice = ("# This Source Code Form is subject to the terms of the Mozilla Public\n"
                  "# License, v. 2.0. If a copy of the MPL was not distributed with this\n"
                  "# file, You can obtain one at https://mozilla.org/MPL/2.0/.\n")
        self.assertTrue(lint.has_mpl_notice(notice))
        self.assertTrue(lint.has_mpl_notice("#!/bin/bash\n" + notice))
        self.assertFalse(lint.has_mpl_notice("print('hi')\n"))

    def test_the_repository_is_clean(self):
        self.assertEqual(lint.lint(lint.REPO_ROOT), [])


if __name__ == "__main__":
    unittest.main()
