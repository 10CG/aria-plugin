"""Phase 1.14 forgejo_config 4-state detection tests.

Covers QA-I3 fix: fenced `forgejo:` code blocks must not count as configured.
"""

from __future__ import annotations

import unittest

from _helpers import run_git, tmp_repo, write_file
from collectors.forgejo_config import (
    _detect_forgejo_host,
    _has_forgejo_block,
    collect_forgejo_config,
)


class TestHostDetection(unittest.TestCase):
    def test_forgejo_https(self):
        self.assertEqual(
            _detect_forgejo_host("https://forgejo.10cg.pub/10CG/Aria.git"),
            "forgejo.10cg.pub",
        )

    def test_forgejo_ssh(self):
        self.assertEqual(
            _detect_forgejo_host("ssh://git@forgejo.10cg.pub/10CG/Aria.git"),
            "forgejo.10cg.pub",
        )

    def test_github_not_detected(self):
        self.assertIsNone(_detect_forgejo_host("https://github.com/10CG/Aria.git"))

    def test_empty(self):
        self.assertIsNone(_detect_forgejo_host(""))


class TestForgejoBlockDetection(unittest.TestCase):
    def test_yaml_key(self):
        self.assertTrue(_has_forgejo_block("forgejo:\n  url: ...\n"))

    def test_heading(self):
        self.assertTrue(_has_forgejo_block("# Forgejo\n\nsome text\n"))

    def test_no_forgejo_anywhere(self):
        self.assertFalse(_has_forgejo_block("unrelated content\n"))

    def test_qa_i3_fenced_block_not_configured(self):
        """QA-I3: sample code in fenced block doesn't count as real config."""
        text = """
# Docs

Below is what the real config should look like:

```yaml
forgejo:
  url: https://example.com
```

"""
        self.assertFalse(_has_forgejo_block(text))

    def test_yaml_outside_fence_counts(self):
        text = """
```yaml
# example
```

forgejo:
  url: real-value
"""
        self.assertTrue(_has_forgejo_block(text))


class TestCollectorStates(unittest.TestCase):
    def test_state1_no_remote(self):
        with tmp_repo() as repo:
            r = collect_forgejo_config(repo)
            self.assertFalse(r.data["forgejo_remote_detected"])

    def test_state1_non_forgejo_remote(self):
        with tmp_repo() as repo:
            run_git(repo, "remote", "add", "origin", "https://github.com/x/y.git")
            r = collect_forgejo_config(repo)
            self.assertFalse(r.data["forgejo_remote_detected"])

    def test_state2_forgejo_no_claude_local_md(self):
        with tmp_repo() as repo:
            run_git(
                repo, "remote", "add", "origin",
                "https://forgejo.10cg.pub/10CG/X.git",
            )
            r = collect_forgejo_config(repo)
            self.assertTrue(r.data["forgejo_remote_detected"])
            self.assertEqual(r.data["config_status"], "missing")

    def test_state3_forgejo_incomplete(self):
        with tmp_repo() as repo:
            run_git(
                repo, "remote", "add", "origin",
                "https://forgejo.10cg.pub/10CG/X.git",
            )
            write_file(repo / "CLAUDE.local.md", "# no forgejo block\n")
            r = collect_forgejo_config(repo)
            self.assertEqual(r.data["config_status"], "incomplete")

    def test_state4_forgejo_configured(self):
        with tmp_repo() as repo:
            run_git(
                repo, "remote", "add", "origin",
                "git@forgejo.10cg.pub:10CG/X.git",
            )
            write_file(repo / "CLAUDE.local.md", "forgejo:\n  url: real\n")
            r = collect_forgejo_config(repo)
            self.assertEqual(r.data["config_status"], "configured")


class TestRegexHardening(unittest.TestCase):
    """Spec `state-scanner-collector-regex-hardening` (2026-04-25): blockquote
    prefix + fullwidth colon support for forgejo_config field detector."""

    def test_fullwidth_colon_yaml_key(self):
        """i18n: Chinese IME default `forgejo：` (fullwidth) must count as configured."""
        self.assertTrue(_has_forgejo_block("forgejo：\n  url: real\n"))

    def test_blockquote_prefix_yaml_key(self):
        """`> forgejo:` (Chinese-author docs habit) must work."""
        self.assertTrue(_has_forgejo_block("> forgejo:\n>   url: real\n"))


if __name__ == "__main__":
    unittest.main()
