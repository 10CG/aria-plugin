"""Phase 1.14 forgejo_config 4-state detection tests.

Covers QA-I3 fix: fenced `forgejo:` code blocks must not count as configured.
"""

from __future__ import annotations

import unittest

from _helpers import run_git, tmp_repo, write_file
from collectors._common import (
    _LEGACY_FORGEJO_FALLBACK,
    _parse_env_forgejo_hosts,
    _read_config_forgejo_hosts,
    resolve_forgejo_hosts,
)
from collectors.forgejo_config import (
    _detect_forgejo_host,
    _has_forgejo_block,
    collect_forgejo_config,
)

LEGACY = _LEGACY_FORGEJO_FALLBACK  # ("forgejo.10cg.pub",)


class TestHostDetection(unittest.TestCase):
    def test_forgejo_https(self):
        self.assertEqual(
            _detect_forgejo_host("https://forgejo.10cg.pub/10CG/Aria.git", LEGACY),
            "forgejo.10cg.pub",
        )

    def test_forgejo_ssh(self):
        self.assertEqual(
            _detect_forgejo_host("ssh://git@forgejo.10cg.pub/10CG/Aria.git", LEGACY),
            "forgejo.10cg.pub",
        )

    def test_github_not_detected(self):
        self.assertIsNone(_detect_forgejo_host("https://github.com/10CG/Aria.git", LEGACY))

    def test_empty(self):
        self.assertIsNone(_detect_forgejo_host("", LEGACY))

    def test_custom_host_via_known_hosts(self):
        """OpenSpec v1.30.0 §E: custom host injected via known_hosts param works."""
        custom = ("forge.example.com",)
        self.assertEqual(
            _detect_forgejo_host("https://forge.example.com/org/repo.git", custom),
            "forge.example.com",
        )
        # Legacy host no longer detected when custom-only known_hosts
        self.assertIsNone(
            _detect_forgejo_host("https://forgejo.10cg.pub/10CG/X.git", custom)
        )


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


class TestForgejoHostsResolver(unittest.TestCase):
    """OpenSpec aria-forgejo-hosts-parameterization (v1.30.0) — env/config/default
    precedence chain in `_common.resolve_forgejo_hosts()`. Per AC §1-§12."""

    def _isolate_env(self):
        """Helper: remove ARIA_FORGEJO_HOSTS from env for the duration of one test."""
        import os
        return os.environ.pop("ARIA_FORGEJO_HOSTS", None)

    def _restore_env(self, prev):
        import os
        if prev is not None:
            os.environ["ARIA_FORGEJO_HOSTS"] = prev
        else:
            os.environ.pop("ARIA_FORGEJO_HOSTS", None)

    def setUp(self):
        self._saved_env = self._isolate_env()

    def tearDown(self):
        self._restore_env(self._saved_env)

    # ----- AC §1 env precedence -----
    def test_env_override_single_host(self):
        import os
        os.environ["ARIA_FORGEJO_HOSTS"] = "alt.example.com"
        with tmp_repo() as repo:
            self.assertEqual(resolve_forgejo_hosts(repo), ("alt.example.com",))

    def test_env_override_multi_host(self):
        import os
        os.environ["ARIA_FORGEJO_HOSTS"] = "h1.com,h2.com,h3.com"
        with tmp_repo() as repo:
            self.assertEqual(resolve_forgejo_hosts(repo), ("h1.com", "h2.com", "h3.com"))

    # ----- AC §6 empty env fall-through -----
    def test_empty_env_falls_through_to_default(self):
        import os
        os.environ["ARIA_FORGEJO_HOSTS"] = ""
        with tmp_repo() as repo:
            self.assertEqual(resolve_forgejo_hosts(repo), LEGACY)

    def test_whitespace_env_falls_through_to_default(self):
        import os
        os.environ["ARIA_FORGEJO_HOSTS"] = "   "
        with tmp_repo() as repo:
            self.assertEqual(resolve_forgejo_hosts(repo), LEGACY)

    # ----- AC §2 config.json precedence -----
    def test_config_json_precedence(self):
        with tmp_repo() as repo:
            (repo / ".aria").mkdir()
            (repo / ".aria" / "config.json").write_text(
                '{"state_scanner":{"issue_scan":{"platform_hostnames":{"forgejo":["custom.example.com"]}}}}'
            )
            self.assertEqual(resolve_forgejo_hosts(repo), ("custom.example.com",))

    # ----- AC env-beats-config -----
    def test_env_beats_config(self):
        import os
        os.environ["ARIA_FORGEJO_HOSTS"] = "env-wins.com"
        with tmp_repo() as repo:
            (repo / ".aria").mkdir()
            (repo / ".aria" / "config.json").write_text(
                '{"state_scanner":{"issue_scan":{"platform_hostnames":{"forgejo":["config-loses.com"]}}}}'
            )
            self.assertEqual(resolve_forgejo_hosts(repo), ("env-wins.com",))

    # ----- AC §3 default fallback -----
    def test_default_fallback_no_env_no_config(self):
        with tmp_repo() as repo:
            self.assertEqual(resolve_forgejo_hosts(repo), LEGACY)

    # ----- AC §7 empty config list fall-through -----
    def test_empty_config_list_falls_through_to_default(self):
        with tmp_repo() as repo:
            (repo / ".aria").mkdir()
            (repo / ".aria" / "config.json").write_text(
                '{"state_scanner":{"issue_scan":{"platform_hostnames":{"forgejo":[]}}}}'
            )
            self.assertEqual(resolve_forgejo_hosts(repo), LEGACY)

    # ----- AC §8 duplicate hosts tolerated -----
    def test_duplicate_hosts_preserved(self):
        import os
        os.environ["ARIA_FORGEJO_HOSTS"] = "h1.com,h1.com,h2.com"
        with tmp_repo() as repo:
            self.assertEqual(resolve_forgejo_hosts(repo), ("h1.com", "h1.com", "h2.com"))

    # ----- Fail-soft config: malformed JSON → fall through -----
    def test_malformed_config_falls_through(self):
        with tmp_repo() as repo:
            (repo / ".aria").mkdir()
            (repo / ".aria" / "config.json").write_text('not valid json {{{')
            self.assertEqual(resolve_forgejo_hosts(repo), LEGACY)

    # ----- AC §12 monkeypatch isolation (architectural — module-level constant removed) -----
    def test_no_module_level_forgejo_hosts_constant(self):
        """Architectural: forgejo_config.py must NOT have module-level _KNOWN_FORGEJO_HOSTS
        constant (Rev1 removal of import-time binding risk)."""
        from collectors import forgejo_config
        self.assertFalse(
            hasattr(forgejo_config, "_KNOWN_FORGEJO_HOSTS"),
            "_KNOWN_FORGEJO_HOSTS should be removed (Rev1 fix R1 ba M-2 / qa M1 #4)",
        )


class TestCustomHostCollectorE2E(unittest.TestCase):
    """OpenSpec v1.30.0 AC §10 — custom host via env actually detected by collector."""

    def setUp(self):
        import os
        self._saved_env = os.environ.pop("ARIA_FORGEJO_HOSTS", None)

    def tearDown(self):
        import os
        if self._saved_env is not None:
            os.environ["ARIA_FORGEJO_HOSTS"] = self._saved_env
        else:
            os.environ.pop("ARIA_FORGEJO_HOSTS", None)

    def test_custom_host_detected_via_env(self):
        """AC §10: ARIA_FORGEJO_HOSTS=forge.example.com + matching git remote → detected."""
        import os
        os.environ["ARIA_FORGEJO_HOSTS"] = "forge.example.com"
        with tmp_repo() as repo:
            run_git(
                repo, "remote", "add", "origin",
                "https://forge.example.com/org/repo.git",
            )
            r = collect_forgejo_config(repo)
            self.assertTrue(r.data["forgejo_remote_detected"])
            self.assertEqual(r.data["instance"], "forge.example.com")

    def test_legacy_host_NOT_detected_when_env_overrides(self):
        """AC §1: env override displaces legacy fallback entirely."""
        import os
        os.environ["ARIA_FORGEJO_HOSTS"] = "forge.example.com"
        with tmp_repo() as repo:
            run_git(
                repo, "remote", "add", "origin",
                "https://forgejo.10cg.pub/10CG/X.git",
            )
            r = collect_forgejo_config(repo)
            self.assertFalse(r.data["forgejo_remote_detected"])


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
