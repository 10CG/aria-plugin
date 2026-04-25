"""Phase 1.13 issue_scan — subprocess-mocked unit tests (T6.5-followup).

Bumps coverage of `collectors.issue_scan` from 44% → ≥70% by mocking
`_run` (forgejo/gh CLI), `shutil.which` (CLI presence), and exercising the
full collector flow including cache hit/miss, submodule scan, error
classification, and aggregation.
"""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from unittest import mock

from _helpers import tmp_project, tmp_repo, write_file
from collectors.issue_scan import (
    DEFAULT_CONFIG,
    ERR_AUTH_FAILED,
    ERR_CLI_MISSING,
    ERR_NETWORK_UNAVAILABLE,
    ERR_NOT_FOUND,
    ERR_PARSE_ERROR,
    ERR_PLATFORM_UNKNOWN,
    ERR_RATE_LIMITED,
    ERR_TIMEOUT,
    SCHEMA_COMPAT,
    SCHEMA_VERSION,
    _build_empty_repo_entry,
    _cache_path,
    _classify_error,
    _cli_available,
    _fetch_repo,
    _lookup_cached_repo,
    _now_iso,
    _parse_iso8601,
    _read_cache,
    _stage_budget,
    _write_cache_atomic,
    collect_issue_scan,
)


def _make_run(table):
    def fake(cmd, cwd, timeout=5):
        key = tuple(cmd)
        if key in table:
            return table[key]
        for k, v in table.items():
            if len(k) <= len(key) and tuple(key[: len(k)]) == k:
                return v
        return (1, "", f"unmocked: {' '.join(cmd)}")
    return fake


class TestStageBudget(unittest.TestCase):
    def test_explicit_user_value_honoured(self):
        cfg = dict(DEFAULT_CONFIG, stage_timeout_seconds=42, scan_submodules=True)
        self.assertEqual(_stage_budget(cfg, 5), 42)

    def test_no_submodules_returns_12(self):
        cfg = dict(DEFAULT_CONFIG, scan_submodules=False)
        self.assertEqual(_stage_budget(cfg, 0), 12)

    def test_with_submodules_scales_with_n(self):
        cfg = dict(DEFAULT_CONFIG, scan_submodules=True, api_timeout_seconds=5)
        self.assertEqual(_stage_budget(cfg, 3), 20)  # max(20, 4*5=20)
        self.assertEqual(_stage_budget(cfg, 5), 30)  # max(20, 6*5=30)

    def test_with_submodules_minimum_20(self):
        cfg = dict(DEFAULT_CONFIG, scan_submodules=True, api_timeout_seconds=2)
        self.assertEqual(_stage_budget(cfg, 1), 20)  # max(20, 2*2=4)


class TestCliAvailable(unittest.TestCase):
    def test_forgejo_present(self):
        with mock.patch("collectors.issue_scan.shutil.which", return_value="/usr/bin/forgejo"):
            self.assertTrue(_cli_available("forgejo"))

    def test_forgejo_missing(self):
        with mock.patch("collectors.issue_scan.shutil.which", return_value=None):
            self.assertFalse(_cli_available("forgejo"))

    def test_github_present(self):
        with mock.patch("collectors.issue_scan.shutil.which", return_value="/usr/local/bin/gh"):
            self.assertTrue(_cli_available("github"))

    def test_unknown_platform(self):
        self.assertFalse(_cli_available("gitlab"))


class TestClassifyErrorEnums(unittest.TestCase):
    """Cover the three fetch_error enums not exercised by full-flow tests."""

    def test_rc124_is_timeout(self):
        self.assertEqual(_classify_error(124, ""), ERR_TIMEOUT)

    def test_rc127_is_cli_missing(self):
        self.assertEqual(_classify_error(127, ""), ERR_CLI_MISSING)

    def test_rate_limit_keyword(self):
        self.assertEqual(_classify_error(1, "rate limit exceeded"), ERR_RATE_LIMITED)

    def test_too_many_requests_keyword(self):
        self.assertEqual(_classify_error(1, "HTTP 429 Too Many Requests"), ERR_RATE_LIMITED)


class TestCachePath(unittest.TestCase):
    def test_relative_resolves_under_root(self):
        with tmp_project() as root:
            cfg = dict(DEFAULT_CONFIG, cache_path=".aria/cache/x.json")
            p = _cache_path(root, cfg)
            self.assertEqual(p, root / ".aria" / "cache" / "x.json")

    def test_absolute_used_verbatim(self):
        cfg = dict(DEFAULT_CONFIG, cache_path="/tmp/abs.json")
        p = _cache_path(Path("/anywhere"), cfg)
        self.assertEqual(p, Path("/tmp/abs.json"))


class TestParseIso8601(unittest.TestCase):
    def test_zulu_form(self):
        self.assertIsNotNone(_parse_iso8601("2026-04-25T10:00:00Z"))

    def test_offset_form(self):
        self.assertIsNotNone(_parse_iso8601("2026-04-25T10:00:00+00:00"))

    def test_invalid(self):
        self.assertIsNone(_parse_iso8601("not-a-date"))

    def test_empty(self):
        self.assertIsNone(_parse_iso8601(""))


class TestNowIso(unittest.TestCase):
    def test_format(self):
        ts = _now_iso()
        # YYYY-MM-DDTHH:MM:SSZ
        self.assertEqual(len(ts), 20)
        self.assertTrue(ts.endswith("Z"))


class TestReadCache(unittest.TestCase):
    def test_missing_file(self):
        with tmp_project() as root:
            self.assertIsNone(_read_cache(root / "absent.json"))

    def test_malformed_json(self):
        with tmp_project() as root:
            p = root / "c.json"
            p.write_text("not json")
            self.assertIsNone(_read_cache(p))

    def test_unknown_schema_treated_as_cold(self):
        with tmp_project() as root:
            p = root / "c.json"
            p.write_text(json.dumps({"schema_version": "9.9", "items": []}))
            self.assertIsNone(_read_cache(p))

    def test_compatible_schemas(self):
        for v in SCHEMA_COMPAT:
            with tmp_project() as root:
                p = root / "c.json"
                p.write_text(json.dumps({"schema_version": v, "items": []}))
                data = _read_cache(p)
                self.assertIsNotNone(data)


class TestWriteCacheAtomic(unittest.TestCase):
    def test_writes_and_creates_parent(self):
        with tmp_project() as root:
            p = root / "deep" / "nested" / "c.json"
            _write_cache_atomic(p, {"schema_version": "1.1", "items": []})
            self.assertTrue(p.is_file())
            data = json.loads(p.read_text())
            self.assertEqual(data["schema_version"], "1.1")


class TestBuildEmptyEntry(unittest.TestCase):
    def test_shape(self):
        entry = _build_empty_repo_entry("forgejo", ERR_CLI_MISSING)
        self.assertEqual(entry["platform"], "forgejo")
        self.assertEqual(entry["fetch_error"], ERR_CLI_MISSING)
        self.assertEqual(entry["source"], "unavailable")
        self.assertEqual(entry["items"], [])
        self.assertEqual(entry["open_count"], 0)


class TestFetchRepoMocked(unittest.TestCase):
    def test_forgejo_success(self):
        body = json.dumps([
            {"number": 1, "title": "issue 1", "labels": [], "html_url": "/issues/1"},
        ])
        run_table = {
            ("forgejo", "GET", "/repos/foo/bar/issues?state=open&type=issues&limit=20"): (
                0, body, ""
            ),
        }
        with mock.patch("collectors.issue_scan._run", side_effect=_make_run(run_table)):
            items, ferr, source = _fetch_repo("forgejo", "foo/bar", 20, [], 5)
        self.assertEqual(source, "live")
        self.assertIsNone(ferr)
        self.assertEqual(len(items), 1)

    def test_github_success(self):
        body = json.dumps([
            {"number": 5, "title": "x", "labels": [{"name": "bug"}], "url": "/issues/5"},
        ])
        run_table = {
            ("gh", "issue", "list", "--repo", "foo/bar", "--state", "open",
             "--limit", "20", "--json", "number,title,labels,url,body"): (0, body, ""),
        }
        with mock.patch("collectors.issue_scan._run", side_effect=_make_run(run_table)):
            items, ferr, source = _fetch_repo("github", "foo/bar", 20, [], 5)
        self.assertEqual(source, "live")
        self.assertEqual(items[0]["labels"], ["bug"])

    def test_unknown_platform(self):
        items, ferr, source = _fetch_repo("gitlab", "foo/bar", 20, [], 5)
        self.assertEqual(ferr, ERR_PLATFORM_UNKNOWN)
        self.assertEqual(items, [])

    def test_rc_nonzero_classifies_error(self):
        run_table = {
            ("forgejo", "GET", "/repos/foo/bar/issues?state=open&type=issues&limit=20"): (
                1, "", "connection refused"
            ),
        }
        with mock.patch("collectors.issue_scan._run", side_effect=_make_run(run_table)):
            items, ferr, source = _fetch_repo("forgejo", "foo/bar", 20, [], 5)
        self.assertEqual(ferr, ERR_NETWORK_UNAVAILABLE)
        self.assertEqual(source, "unavailable")

    def test_json_parse_error(self):
        run_table = {
            ("forgejo", "GET", "/repos/foo/bar/issues?state=open&type=issues&limit=20"): (
                0, "not json [", ""
            ),
        }
        with mock.patch("collectors.issue_scan._run", side_effect=_make_run(run_table)):
            items, ferr, _src = _fetch_repo("forgejo", "foo/bar", 20, [], 5)
        self.assertEqual(ferr, ERR_PARSE_ERROR)

    def test_dict_response_with_401(self):
        body = json.dumps({"message": "Unauthorized", "status": 401})
        run_table = {
            ("forgejo", "GET", "/repos/foo/bar/issues?state=open&type=issues&limit=20"): (
                0, body, ""
            ),
        }
        with mock.patch("collectors.issue_scan._run", side_effect=_make_run(run_table)):
            items, ferr, _src = _fetch_repo("forgejo", "foo/bar", 20, [], 5)
        self.assertEqual(ferr, ERR_AUTH_FAILED)

    def test_dict_response_with_404(self):
        body = json.dumps({"message": "Not found", "status": 404})
        run_table = {
            ("forgejo", "GET", "/repos/foo/bar/issues?state=open&type=issues&limit=20"): (
                0, body, ""
            ),
        }
        with mock.patch("collectors.issue_scan._run", side_effect=_make_run(run_table)):
            items, ferr, _src = _fetch_repo("forgejo", "foo/bar", 20, [], 5)
        self.assertEqual(ferr, ERR_NOT_FOUND)

    def test_dict_response_unknown(self):
        body = json.dumps({"message": "weird"})
        run_table = {
            ("forgejo", "GET", "/repos/foo/bar/issues?state=open&type=issues&limit=20"): (
                0, body, ""
            ),
        }
        with mock.patch("collectors.issue_scan._run", side_effect=_make_run(run_table)):
            _items, ferr, _src = _fetch_repo("forgejo", "foo/bar", 20, [], 5)
        self.assertEqual(ferr, ERR_PARSE_ERROR)

    def test_non_list_non_dict_response(self):
        body = json.dumps("a string")
        run_table = {
            ("forgejo", "GET", "/repos/foo/bar/issues?state=open&type=issues&limit=20"): (
                0, body, ""
            ),
        }
        with mock.patch("collectors.issue_scan._run", side_effect=_make_run(run_table)):
            _items, ferr, _src = _fetch_repo("forgejo", "foo/bar", 20, [], 5)
        self.assertEqual(ferr, ERR_PARSE_ERROR)

    def test_label_filter_applied(self):
        body = json.dumps([
            {"number": 1, "title": "a", "labels": [{"name": "bug"}], "html_url": "/issues/1"},
            {"number": 2, "title": "b", "labels": [{"name": "doc"}], "html_url": "/issues/2"},
        ])
        run_table = {
            ("forgejo", "GET", "/repos/foo/bar/issues?state=open&type=issues&limit=20"): (
                0, body, ""
            ),
        }
        with mock.patch("collectors.issue_scan._run", side_effect=_make_run(run_table)):
            items, _ferr, _src = _fetch_repo("forgejo", "foo/bar", 20, ["bug"], 5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["number"], 1)

    def test_empty_body(self):
        run_table = {
            ("forgejo", "GET", "/repos/foo/bar/issues?state=open&type=issues&limit=20"): (
                0, "", ""
            ),
        }
        with mock.patch("collectors.issue_scan._run", side_effect=_make_run(run_table)):
            items, ferr, source = _fetch_repo("forgejo", "foo/bar", 20, [], 5)
        self.assertEqual(items, [])
        self.assertIsNone(ferr)


class TestLookupCachedRepo(unittest.TestCase):
    def test_no_cache(self):
        self.assertIsNone(_lookup_cached_repo(None, "foo/bar", 900))

    def test_v11_cache_hit(self):
        cache = {
            "schema_version": "1.1",
            "repos": {
                "foo/bar": {
                    "fetched_at": _now_iso(),
                    "items": [{"number": 1}],
                    "platform": "forgejo",
                }
            },
        }
        out = _lookup_cached_repo(cache, "foo/bar", 900)
        self.assertIsNotNone(out)
        self.assertEqual(len(out["items"]), 1)

    def test_v11_cache_expired(self):
        old_ts = "2020-01-01T00:00:00Z"
        cache = {
            "repos": {
                "foo/bar": {"fetched_at": old_ts, "items": [{"number": 1}]}
            },
        }
        self.assertIsNone(_lookup_cached_repo(cache, "foo/bar", 900))

    def test_v11_cache_miss_unknown_repo(self):
        cache = {
            "repos": {"foo/bar": {"fetched_at": _now_iso(), "items": []}},
        }
        self.assertIsNone(_lookup_cached_repo(cache, "other/repo", 900))

    def test_v10_fallback(self):
        cache = {
            "schema_version": "1.0",
            "fetched_at": _now_iso(),
            "platform": "forgejo",
            "items": [{"number": 1}],
        }
        out = _lookup_cached_repo(cache, "any/repo", 900)
        self.assertIsNotNone(out)
        self.assertEqual(out["platform"], "forgejo")

    def test_v10_fallback_uses_open_issues_when_items_missing(self):
        cache = {
            "fetched_at": _now_iso(),
            "platform": "forgejo",
            "open_issues": [{"number": 1}],
        }
        out = _lookup_cached_repo(cache, "any/repo", 900)
        self.assertIsNotNone(out)
        self.assertEqual(len(out["items"]), 1)

    def test_v10_fallback_expired(self):
        cache = {
            "fetched_at": "2020-01-01T00:00:00Z",
            "platform": "forgejo",
            "items": [],
        }
        self.assertIsNone(_lookup_cached_repo(cache, "any/repo", 900))

    def test_v10_fallback_no_items_no_open_issues(self):
        cache = {"fetched_at": _now_iso(), "platform": "forgejo"}
        self.assertIsNone(_lookup_cached_repo(cache, "any/repo", 900))


class TestCollectorDisabled(unittest.TestCase):
    def test_default_disabled_returns_minimal(self):
        with tmp_project() as root:
            r = collect_issue_scan(root)
            self.assertEqual(r.data, {"enabled": False})


class TestCollectorEndToEnd(unittest.TestCase):
    """Full collector flow via mocked CLI subprocess + shutil.which."""

    def _enable_config(self, root: Path, **overrides) -> None:
        cfg = {
            "state_scanner": {
                "issue_scan": {
                    "enabled": True,
                    "platform": "forgejo",
                    "scan_submodules": False,
                    **overrides,
                }
            }
        }
        write_file(root / ".aria" / "config.json", json.dumps(cfg))

    def test_platform_unknown_when_no_remote(self):
        with tmp_repo() as repo:
            self._enable_config(repo, platform=None)
            run_table = {("git", "remote", "get-url", "origin"): (1, "", "no remote")}
            with mock.patch("collectors.issue_scan._run", side_effect=_make_run(run_table)):
                with mock.patch("collectors.issue_scan.shutil.which", return_value=None):
                    r = collect_issue_scan(repo)
        self.assertTrue(r.data["enabled"])
        self.assertEqual(r.data["issue_status"]["fetch_error"], ERR_PLATFORM_UNKNOWN)

    def test_cli_missing(self):
        with tmp_repo() as repo:
            self._enable_config(repo)
            run_table = {
                ("git", "remote", "get-url", "origin"): (
                    0, "https://forgejo.10cg.pub/foo/bar.git\n", ""
                ),
            }
            with mock.patch("collectors.issue_scan._run", side_effect=_make_run(run_table)):
                with mock.patch("collectors.issue_scan.shutil.which", return_value=None):
                    r = collect_issue_scan(repo)
        self.assertEqual(r.data["issue_status"]["fetch_error"], ERR_CLI_MISSING)

    def test_full_live_fetch_writes_cache(self):
        body = json.dumps([
            {
                "number": 1,
                "title": "test issue US-021",
                "labels": [{"name": "bug"}],
                "html_url": "https://forgejo.example/foo/bar/issues/1",
            }
        ])
        with tmp_repo() as repo:
            self._enable_config(repo)
            run_table = {
                ("git", "remote", "get-url", "origin"): (
                    0, "https://forgejo.10cg.pub/foo/bar.git\n", ""
                ),
                ("forgejo", "GET", "/repos/foo/bar/issues?state=open&type=issues&limit=20"): (
                    0, body, ""
                ),
            }
            with mock.patch("collectors.issue_scan._run", side_effect=_make_run(run_table)):
                with mock.patch(
                    "collectors.issue_scan.shutil.which", return_value="/usr/bin/forgejo"
                ):
                    r = collect_issue_scan(repo)
            st = r.data["issue_status"]
            self.assertEqual(st["open_count"], 1)
            self.assertEqual(st["source"], "live")
            self.assertEqual(st["items"][0]["linked_us"], "US-021")
            self.assertEqual(st["schema_version"], SCHEMA_VERSION)
            # Cache must be persisted (check inside tmp_repo lifetime)
            cache_file = repo / ".aria" / "cache" / "issues.json"
            self.assertTrue(cache_file.is_file())

    def test_cache_hit_short_circuits_fetch(self):
        with tmp_repo() as repo:
            self._enable_config(repo)
            cache_file = repo / ".aria" / "cache" / "issues.json"
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps({
                "schema_version": "1.1",
                "fetched_at": _now_iso(),
                "ttl_seconds": 900,
                "scan_submodules": False,
                "platform": "forgejo",
                "open_count": 1,
                "items": [{"number": 99, "title": "cached", "labels": [], "url": "x"}],
                "open_issues": [],
                "label_summary": {},
                "repos": {
                    "foo/bar": {
                        "platform": "forgejo",
                        "source": "live",
                        "fetch_error": None,
                        "fetched_at": _now_iso(),
                        "open_count": 1,
                        "items": [{"number": 99, "title": "cached", "labels": [], "url": "x"}],
                    }
                },
            }))
            # No fetch should happen if cache hits — but git remote still queried
            run_table = {
                ("git", "remote", "get-url", "origin"): (
                    0, "https://forgejo.10cg.pub/foo/bar.git\n", ""
                ),
            }
            with mock.patch("collectors.issue_scan._run", side_effect=_make_run(run_table)):
                with mock.patch(
                    "collectors.issue_scan.shutil.which", return_value="/usr/bin/forgejo"
                ):
                    r = collect_issue_scan(repo)
        st = r.data["issue_status"]
        self.assertEqual(st["source"], "cache")
        self.assertEqual(st["items"][0]["number"], 99)

    def test_submodule_scan_with_uninitialized_sub(self):
        with tmp_repo() as repo:
            self._enable_config(repo, scan_submodules=True)
            run_table = {
                ("git", "remote", "get-url", "origin"): (
                    0, "https://forgejo.10cg.pub/foo/bar.git\n", ""
                ),
                ("forgejo", "GET", "/repos/foo/bar/issues?state=open&type=issues&limit=20"): (
                    0, "[]", ""
                ),
            }
            with mock.patch("collectors.issue_scan._run", side_effect=_make_run(run_table)):
                with mock.patch(
                    "collectors.issue_scan.shutil.which", return_value="/usr/bin/forgejo"
                ):
                    with mock.patch(
                        "collectors.issue_scan._enumerate_submodule_paths",
                        return_value=["uninit-sub"],
                    ):
                        r = collect_issue_scan(repo)
        repos = r.data["issue_status"]["repos"]
        self.assertIn("uninit-sub", repos)
        self.assertEqual(repos["uninit-sub"]["fetch_error"], "submodule_not_initialized")

    def test_submodule_scan_with_no_origin_remote(self):
        with tmp_repo() as repo:
            (repo / "sub").mkdir()
            (repo / "sub" / ".git").write_text("gitdir: ../.git/modules/sub\n")
            self._enable_config(repo, scan_submodules=True)
            run_table = {
                ("git", "remote", "get-url", "origin"): (
                    0, "https://forgejo.10cg.pub/foo/bar.git\n", ""
                ),
                ("forgejo", "GET", "/repos/foo/bar/issues?state=open&type=issues&limit=20"): (
                    0, "[]", ""
                ),
            }

            real_make_run = _make_run(run_table)

            def fake_run(cmd, cwd, timeout=5):
                if list(cmd) == ["git", "remote", "get-url", "origin"] and str(cwd).endswith("/sub"):
                    return (1, "", "no remote")
                return real_make_run(cmd, cwd, timeout)

            with mock.patch("collectors.issue_scan._run", side_effect=fake_run):
                with mock.patch(
                    "collectors.issue_scan.shutil.which", return_value="/usr/bin/forgejo"
                ):
                    with mock.patch(
                        "collectors.issue_scan._enumerate_submodule_paths",
                        return_value=["sub"],
                    ):
                        r = collect_issue_scan(repo)
        repos = r.data["issue_status"]["repos"]
        self.assertEqual(repos["sub"]["fetch_error"], "no_origin_remote")

    def test_submodule_scan_bad_remote_url(self):
        with tmp_repo() as repo:
            (repo / "sub").mkdir()
            (repo / "sub" / ".git").write_text("gitdir: ../.git/modules/sub\n")
            self._enable_config(repo, scan_submodules=True)
            run_table = {
                ("git", "remote", "get-url", "origin"): (
                    0, "https://forgejo.10cg.pub/foo/bar.git\n", ""
                ),
                ("forgejo", "GET", "/repos/foo/bar/issues?state=open&type=issues&limit=20"): (
                    0, "[]", ""
                ),
            }
            real_make_run = _make_run(run_table)

            def fake_run(cmd, cwd, timeout=5):
                if list(cmd) == ["git", "remote", "get-url", "origin"] and str(cwd).endswith("/sub"):
                    return (0, "totally invalid url\n", "")
                return real_make_run(cmd, cwd, timeout)

            with mock.patch("collectors.issue_scan._run", side_effect=fake_run):
                with mock.patch(
                    "collectors.issue_scan.shutil.which", return_value="/usr/bin/forgejo"
                ):
                    with mock.patch(
                        "collectors.issue_scan._enumerate_submodule_paths",
                        return_value=["sub"],
                    ):
                        r = collect_issue_scan(repo)
        repos = r.data["issue_status"]["repos"]
        self.assertEqual(repos["sub"]["fetch_error"], ERR_PARSE_ERROR)

    def test_submodule_scan_full_flow(self):
        body_main = json.dumps([
            {"number": 1, "title": "main issue", "labels": [], "html_url": "/issues/1"}
        ])
        body_sub = json.dumps([
            {"number": 5, "title": "sub issue", "labels": [{"name": "bug"}], "html_url": "/issues/5"}
        ])
        with tmp_repo() as repo:
            (repo / "sub").mkdir()
            (repo / "sub" / ".git").write_text("gitdir: ../.git/modules/sub\n")
            self._enable_config(repo, scan_submodules=True)

            def fake_run(cmd, cwd, timeout=5):
                cmd_t = tuple(cmd)
                if cmd_t == ("git", "remote", "get-url", "origin"):
                    if str(cwd).endswith("/sub"):
                        return (0, "https://forgejo.10cg.pub/foo/sub.git\n", "")
                    return (0, "https://forgejo.10cg.pub/foo/bar.git\n", "")
                if cmd_t == ("forgejo", "GET", "/repos/foo/bar/issues?state=open&type=issues&limit=20"):
                    return (0, body_main, "")
                if cmd_t == ("forgejo", "GET", "/repos/foo/sub/issues?state=open&type=issues&limit=20"):
                    return (0, body_sub, "")
                return (1, "", f"unmocked: {' '.join(cmd)}")

            with mock.patch("collectors.issue_scan._run", side_effect=fake_run):
                with mock.patch(
                    "collectors.issue_scan.shutil.which", return_value="/usr/bin/forgejo"
                ):
                    with mock.patch(
                        "collectors.issue_scan._enumerate_submodule_paths",
                        return_value=["sub"],
                    ):
                        r = collect_issue_scan(repo)
        st = r.data["issue_status"]
        self.assertEqual(st["open_count"], 2)
        self.assertEqual(set(st["repos"].keys()), {"foo/bar", "foo/sub"})
        self.assertEqual(st["label_summary"].get("bug"), 1)

    def test_submodule_platform_unknown(self):
        with tmp_repo() as repo:
            (repo / "sub").mkdir()
            (repo / "sub" / ".git").write_text("gitdir: ../.git/modules/sub\n")
            # Main config explicit forgejo, but we override sub remote to gitlab
            cfg = {
                "state_scanner": {
                    "issue_scan": {
                        "enabled": True,
                        "platform": None,
                        "scan_submodules": True,
                    }
                }
            }
            write_file(repo / ".aria" / "config.json", json.dumps(cfg))

            def fake_run(cmd, cwd, timeout=5):
                cmd_t = tuple(cmd)
                if cmd_t == ("git", "remote", "get-url", "origin"):
                    if str(cwd).endswith("/sub"):
                        return (0, "https://gitlab.example.com/foo/sub.git\n", "")
                    return (0, "https://forgejo.10cg.pub/foo/bar.git\n", "")
                if cmd_t == ("forgejo", "GET", "/repos/foo/bar/issues?state=open&type=issues&limit=20"):
                    return (0, "[]", "")
                return (1, "", "unmocked")

            with mock.patch("collectors.issue_scan._run", side_effect=fake_run):
                with mock.patch(
                    "collectors.issue_scan.shutil.which", return_value="/usr/bin/forgejo"
                ):
                    with mock.patch(
                        "collectors.issue_scan._enumerate_submodule_paths",
                        return_value=["sub"],
                    ):
                        r = collect_issue_scan(repo)
        repos = r.data["issue_status"]["repos"]
        # Submodule's owner/repo can be extracted but platform unknown
        self.assertIn("foo/sub", repos)
        self.assertEqual(repos["foo/sub"]["fetch_error"], ERR_PLATFORM_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
