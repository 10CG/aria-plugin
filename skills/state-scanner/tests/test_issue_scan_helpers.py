"""Phase 1.13 issue_scan pure-function tests.

Focuses on pure helpers (no network I/O). Full collector tests would require
mocking the forgejo/gh CLI subprocess, which is out of T6 scope.
"""

from __future__ import annotations

import unittest

from _helpers import tmp_project, write_file
from collectors.issue_scan import (
    ERR_AUTH_FAILED,
    ERR_CLI_MISSING,
    ERR_NETWORK_UNAVAILABLE,
    ERR_NOT_FOUND,
    ERR_RATE_LIMITED,
    ERR_TIMEOUT,
    ERR_UNKNOWN,
    _apply_heuristics,
    _classify_error,
    _detect_platform,
    _extract_hostname,
    _extract_owner_repo,
    _list_openspec_changes,
    _load_config,
    _match_openspec,
    _match_us,
    _normalize_items,
)


class TestHostname(unittest.TestCase):
    def test_https_url(self):
        self.assertEqual(
            _extract_hostname("https://github.com/10CG/Aria"), "github.com"
        )

    def test_scp_form(self):
        self.assertEqual(
            _extract_hostname("git@forgejo.10cg.pub:10CG/Aria.git"),
            "forgejo.10cg.pub",
        )

    def test_ssh_url(self):
        self.assertEqual(
            _extract_hostname("ssh://git@host.com:22/owner/repo"), "host.com"
        )

    def test_empty(self):
        self.assertIsNone(_extract_hostname(""))


class TestOwnerRepo(unittest.TestCase):
    def test_https(self):
        self.assertEqual(
            _extract_owner_repo("https://github.com/10CG/Aria.git"), "10CG/Aria"
        )

    def test_scp(self):
        self.assertEqual(
            _extract_owner_repo("git@forgejo.10cg.pub:10CG/Aria.git"), "10CG/Aria"
        )

    def test_strips_dotgit(self):
        self.assertEqual(
            _extract_owner_repo("https://github.com/foo/bar.git"), "foo/bar"
        )

    def test_rejects_too_deep(self):
        self.assertIsNone(
            _extract_owner_repo("https://github.com/org/team/repo")
        )


class TestPlatformDetection(unittest.TestCase):
    BASE_CFG = {
        "platform": None,
        "platform_hostnames": {
            "forgejo": ["forgejo.10cg.pub"],
            "github": ["github.com"],
        },
    }

    def test_explicit_overrides(self):
        cfg = dict(self.BASE_CFG, platform="github")
        self.assertEqual(_detect_platform(cfg, "any://whatever"), "github")

    def test_forgejo_via_hostmap(self):
        self.assertEqual(
            _detect_platform(self.BASE_CFG, "git@forgejo.10cg.pub:10CG/Aria.git"),
            "forgejo",
        )

    def test_github_via_hostmap(self):
        self.assertEqual(
            _detect_platform(self.BASE_CFG, "https://github.com/foo/bar"), "github"
        )

    def test_no_remote_returns_none(self):
        self.assertIsNone(_detect_platform(self.BASE_CFG, None))

    def test_unknown_hostname_returns_none(self):
        # Unknown hostname without github.com / forgejo fallback substring
        self.assertIsNone(
            _detect_platform(self.BASE_CFG, "https://gitlab.example.com/foo/bar")
        )


class TestErrorClassification(unittest.TestCase):
    def test_rc127_is_cli_missing(self):
        self.assertEqual(_classify_error(127, ""), ERR_CLI_MISSING)

    def test_rc124_is_timeout(self):
        self.assertEqual(_classify_error(124, ""), ERR_TIMEOUT)

    def test_network_stderr(self):
        self.assertEqual(
            _classify_error(1, "connection refused"), ERR_NETWORK_UNAVAILABLE
        )

    def test_auth_stderr(self):
        self.assertEqual(_classify_error(1, "401 Unauthorized"), ERR_AUTH_FAILED)

    def test_rate_limit_stderr(self):
        self.assertEqual(
            _classify_error(1, "rate limit exceeded"), ERR_RATE_LIMITED
        )

    def test_not_found_stderr(self):
        self.assertEqual(_classify_error(1, "HTTP 404 Not Found"), ERR_NOT_FOUND)

    def test_unknown_fallback(self):
        self.assertEqual(_classify_error(1, "unparseable nonsense"), ERR_UNKNOWN)


class TestNormalizeItems(unittest.TestCase):
    def test_qa_c2_pull_request_filter(self):
        """QA-C2: Forgejo /issues returns PRs. Filter out items whose
        pull_request field is a non-null object or whose URL contains `/pulls/`."""
        raw = [
            {"number": 1, "title": "real issue", "html_url": "/issues/1"},
            {"number": 2, "title": "pr disguised", "pull_request": {}, "html_url": "/issues/2"},
            {"number": 3, "title": "pr via url", "html_url": "/pulls/3"},
        ]
        items = _normalize_items(raw, platform="forgejo")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["number"], 1)

    def test_modern_forgejo_pull_request_null_on_issues(self):
        """Regression: modern Forgejo (≥1.21) attaches `pull_request: null` to
        every issue payload. Presence-only check rejected all real issues →
        open_count=0 silent failure. Fix: only reject when value is a dict."""
        raw = [
            {"number": 67, "title": "real issue with null pull_request",
             "pull_request": None, "html_url": "/issues/67"},
            {"number": 68, "title": "another real issue",
             "pull_request": None, "html_url": "/issues/68"},
            {"number": 69, "title": "actual PR has dict",
             "pull_request": {"merged": False}, "html_url": "/issues/69"},
        ]
        items = _normalize_items(raw, platform="forgejo")
        self.assertEqual(len(items), 2)
        self.assertEqual([i["number"] for i in items], [67, 68])

    def test_label_extraction(self):
        raw = [{"number": 1, "labels": [{"name": "bug"}, "plain-string"]}]
        items = _normalize_items(raw, platform="github")
        self.assertEqual(items[0]["labels"], ["bug", "plain-string"])

    def test_defaults(self):
        raw = [{"number": 1}]
        items = _normalize_items(raw, platform="forgejo")
        self.assertEqual(items[0]["title"], "")
        self.assertEqual(items[0]["labels"], [])


class TestHeuristicLinking(unittest.TestCase):
    def test_us_match(self):
        self.assertEqual(_match_us("related to US-021 work"), "US-021")
        self.assertEqual(_match_us("see (US-100)"), "US-100")
        self.assertIsNone(_match_us("no story here"))

    def test_openspec_match(self):
        changes = ["add-auth", "refactor-api"]
        self.assertEqual(_match_openspec("Implements add-auth.", changes), "add-auth")
        self.assertIsNone(_match_openspec("vaguely related", changes))

    def test_openspec_word_boundary(self):
        # Should NOT match inside longer word
        changes = ["auth"]
        self.assertIsNone(_match_openspec("distinguish", changes))

    def test_apply_heuristics_drops_body(self):
        items = [{"title": "x", "body": "US-021", "labels": []}]
        _apply_heuristics(items, ["add-auth"])
        self.assertNotIn("body", items[0])
        self.assertEqual(items[0]["linked_us"], "US-021")
        self.assertTrue(items[0]["heuristic"])


class TestOpenspecListing(unittest.TestCase):
    def test_lists_change_dirs(self):
        with tmp_project() as root:
            write_file(
                root / "openspec" / "changes" / "feat-a" / "proposal.md", "**Status**: Draft\n"
            )
            write_file(
                root / "openspec" / "changes" / "feat-b" / "proposal.md", "**Status**: Done\n"
            )
            (root / "openspec" / "changes" / ".hidden").mkdir(parents=True)
            changes = sorted(_list_openspec_changes(root))
            self.assertEqual(changes, ["feat-a", "feat-b"])

    def test_missing_dir(self):
        with tmp_project() as root:
            self.assertEqual(_list_openspec_changes(root), [])


class TestConfigLoader(unittest.TestCase):
    def test_missing_config_returns_defaults(self):
        with tmp_project() as root:
            cfg = _load_config(root)
            self.assertFalse(cfg["enabled"])
            self.assertEqual(cfg["api_timeout_seconds"], 5)

    def test_partial_config_merges(self):
        import json

        with tmp_project() as root:
            write_file(
                root / ".aria" / "config.json",
                json.dumps(
                    {
                        "state_scanner": {
                            "issue_scan": {
                                "enabled": True,
                                "platform": "forgejo",
                                "limit": 50,
                            }
                        }
                    }
                ),
            )
            cfg = _load_config(root)
            self.assertTrue(cfg["enabled"])
            self.assertEqual(cfg["platform"], "forgejo")
            self.assertEqual(cfg["limit"], 50)
            # Defaults for unspecified keys
            self.assertEqual(cfg["api_timeout_seconds"], 5)


if __name__ == "__main__":
    unittest.main()
