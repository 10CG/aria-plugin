"""Phase 1.13 issue_scan — pagination and truncation visibility (10CG/aria-plugin#182).

Before this change `issue_scan` issued ONE request per repo with `limit=20` and
reported `len(items)` as `open_count`, so a repo with more than 20 open issues
was silently cut off. Forgejo lists newest first, so the issues that vanished
were always the oldest ones.

Contract pinned here:
- `limit` is the PAGE SIZE (clamped to the server default maximum of 50), never
  a total cap. Listing continues until the server returns an empty page.
- The first request keeps the exact pre-pagination URL (no `page=` parameter);
  later pages append `&page=N`.
- Anything that ends the listing early is visible: `truncated: true` with a
  `truncated_reason` (`max_items` / `pagination_stalled`).
- A failed later page fails the whole repo loudly (`fetch_error`) instead of
  returning a silently partial list.
- Cache entries written before this change may be truncated, so they are cold.

The Forgejo double models the real server (honours `limit` / `page`, can clamp
the page size, can ignore `page`, can fail one page) so the tests do not depend
on how many requests the implementation happens to make.
"""

from __future__ import annotations

import json
import time
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

from _helpers import tmp_repo, write_file  # first import: puts scripts/ on sys.path
import collectors.issue_scan as issue_scan_mod
from collectors.issue_scan import (
    ERR_TIMEOUT,
    SCHEMA_VERSION,
    _build_empty_repo_entry,
    _fetch_repo,
    _now_iso,
    collect_issue_scan,
)

_REMOTE = "https://forgejo.10cg.pub/foo/bar.git\n"
_ISSUES_URL = "/repos/foo/bar/issues?state=open&type=issues&limit=20"


def _issue(n: int, labels: list[dict] | None = None) -> dict:
    return {
        "number": n,
        "title": f"issue {n}",
        "labels": labels or [],
        "html_url": f"/foo/bar/issues/{n}",
        "pull_request": None,
    }


class FakeForgejo:
    """Callable stand-in for `collectors._common._run`.

    Serves `total` open issues newest first (numbers total..1) the way the real
    API does. Knobs: `max_per_page` (server-side clamp), `honours_page` (False =
    the server ignores `page`), `overlap` (page N>1 repeats the tail of page
    N-1, as when an issue is opened between two requests), `fail_page`.
    """

    def __init__(self, total, *, max_per_page=50, honours_page=True, overlap=0,
                 fail_page=None, label_every=None):
        self.total = total
        self.max_per_page = max_per_page
        self.honours_page = honours_page
        self.overlap = overlap
        self.fail_page = fail_page
        self.label_every = label_every
        self.calls: list[int] = []        # page number of each issues-list request
        self.endpoints: list[str] = []    # raw endpoint of each issues-list request

    def __call__(self, cmd, cwd, timeout=5):
        if tuple(cmd[:4]) == ("git", "remote", "get-url", "origin"):
            return (0, _REMOTE, "")
        if tuple(cmd[:2]) == ("forgejo", "GET") and "/issues?" in cmd[2]:
            query = parse_qs(urlparse(cmd[2]).query)
            limit = min(int(query["limit"][0]), self.max_per_page)
            page = int(query.get("page", ["1"])[0]) if self.honours_page else 1
            self.calls.append(page)
            self.endpoints.append(cmd[2])
            if self.fail_page == page:
                return (124, "", "timed out")
            hi = self.total - (page - 1) * limit + (self.overlap if page > 1 else 0)
            lo = max(self.total - page * limit, 0)
            rows = []
            for n in range(hi, lo, -1):
                tagged = self.label_every and n % self.label_every == 0
                rows.append(_issue(n, [{"name": "bug"}] if tagged else None))
            return (0, json.dumps(rows), "")
        return (1, "", f"unmocked: {' '.join(cmd)}")


class FakeGh:
    """`gh issue list` double: honours --limit, has no page parameter."""

    def __init__(self, total):
        self.total = total
        self.limits: list[int] = []

    def __call__(self, cmd, cwd, timeout=5):
        if tuple(cmd[:3]) == ("gh", "issue", "list"):
            limit = int(cmd[cmd.index("--limit") + 1])
            self.limits.append(limit)
            rows = [
                {"number": n, "title": f"issue {n}", "labels": [],
                 "url": f"https://github.com/foo/bar/issues/{n}"}
                for n in range(self.total, max(self.total - limit, 0), -1)
            ]
            return (0, json.dumps(rows), "")
        return (1, "", f"unmocked: {' '.join(cmd)}")


def _fetch(platform, fake, limit=20, labels=(), **kwargs):
    with mock.patch("collectors.issue_scan._run", side_effect=fake):
        return _fetch_repo(platform, "foo/bar", limit, list(labels), 5, **kwargs)


class TestForgejoPagination(unittest.TestCase):
    def test_every_page_is_collected(self):
        # Baseline collected only the first page: 20 of 46.
        res = _fetch("forgejo", FakeForgejo(46))
        self.assertEqual(sorted(i["number"] for i in res[0]), list(range(1, 47)))

    def test_first_request_url_is_unchanged_and_later_pages_add_page_param(self):
        srv = FakeForgejo(46)
        _fetch("forgejo", srv)
        self.assertEqual(srv.endpoints[0], _ISSUES_URL)  # no `page=` on page 1
        self.assertEqual(srv.endpoints[1], _ISSUES_URL + "&page=2")
        # 20 + 20 + 6, then the empty page is what ends the listing
        self.assertEqual(srv.calls, [1, 2, 3, 4])

    def test_complete_listing_is_not_flagged_truncated(self):
        res = _fetch("forgejo", FakeForgejo(46))
        self.assertFalse(res.truncated)
        self.assertIsNone(res.truncated_reason)

    def test_repo_without_issues_costs_one_request_and_is_complete(self):
        srv = FakeForgejo(0)
        res = _fetch("forgejo", srv)
        self.assertEqual(res[0], [])
        self.assertIsNone(res[1])
        self.assertEqual(res[2], "live")
        self.assertFalse(res.truncated)
        self.assertEqual(srv.calls, [1])

    def test_server_clamping_page_size_below_the_request_does_not_end_listing_early(self):
        # Server max page size 30 < the 50 we ask for: page 1 is "short" but not
        # last. Stopping on a short page would silently end the listing at 30.
        res = _fetch("forgejo", FakeForgejo(130, max_per_page=30), limit=50)
        self.assertEqual(len(res[0]), 130)
        self.assertFalse(res.truncated)

    def test_page_size_is_clamped_to_the_server_default_maximum(self):
        srv = FakeForgejo(10)
        _fetch("forgejo", srv, limit=100)
        self.assertEqual(srv.endpoints[0], "/repos/foo/bar/issues?state=open&type=issues&limit=50")

    def test_label_filter_applies_across_pages(self):
        # bug-labelled issues are 40, 30 (page 1) and 20, 10 (page 2)
        res = _fetch("forgejo", FakeForgejo(46, label_every=10), labels=["bug"])
        self.assertEqual(sorted(i["number"] for i in res[0]), [10, 20, 30, 40])

    def test_overlapping_pages_do_not_duplicate_items(self):
        res = _fetch("forgejo", FakeForgejo(46, overlap=3))
        numbers = [i["number"] for i in res[0]]
        self.assertEqual(len(numbers), len(set(numbers)))
        self.assertEqual(sorted(numbers), list(range(1, 47)))


class TestForgejoTruncationIsVisible(unittest.TestCase):
    def test_ceiling_reached_is_flagged(self):
        srv = FakeForgejo(200)
        with mock.patch.object(issue_scan_mod, "_MAX_ITEMS", 60):
            res = _fetch("forgejo", srv)
        self.assertEqual(len(res[0]), 60)
        self.assertTrue(res.truncated)
        self.assertEqual(res.truncated_reason, "max_items")

    def test_exactly_at_the_ceiling_is_complete(self):
        # The pair of the test above: without this one a "always truncated"
        # implementation would pass.
        with mock.patch.object(issue_scan_mod, "_MAX_ITEMS", 60):
            res = _fetch("forgejo", FakeForgejo(60))
        self.assertEqual(len(res[0]), 60)
        self.assertFalse(res.truncated)

    def test_one_past_the_ceiling_is_flagged_and_not_kept(self):
        with mock.patch.object(issue_scan_mod, "_MAX_ITEMS", 60):
            res = _fetch("forgejo", FakeForgejo(61))
        self.assertEqual(len(res[0]), 60)
        self.assertTrue(res.truncated)

    def test_server_ignoring_page_is_flagged_and_not_doubled(self):
        srv = FakeForgejo(46, honours_page=False)  # same first page for ever
        res = _fetch("forgejo", srv)
        self.assertEqual(len(res[0]), 20)
        self.assertTrue(res.truncated)
        self.assertEqual(res.truncated_reason, "pagination_stalled")
        self.assertEqual(srv.calls, [1, 1])  # page 1, then the repeat that proves the stall

    def test_failure_on_a_later_page_fails_the_repo_loudly(self):
        res = _fetch("forgejo", FakeForgejo(100, fail_page=3))
        self.assertEqual(res[1], ERR_TIMEOUT)
        self.assertEqual(res[0], [])
        self.assertEqual(res[2], "unavailable")

    def test_expired_deadline_is_a_timeout_and_makes_no_request(self):
        srv = FakeForgejo(46)
        res = _fetch("forgejo", srv, deadline=time.monotonic() - 1)
        self.assertEqual(res[1], ERR_TIMEOUT)
        self.assertEqual(srv.calls, [])


class TestGithubCeiling(unittest.TestCase):
    def test_asks_for_the_ceiling_not_the_page_size(self):
        gh = FakeGh(5)
        res = _fetch("github", gh, limit=20)
        # ceiling + 1: the extra row is the probe that tells "exactly full" from "overflowed"
        self.assertEqual(gh.limits, [issue_scan_mod._MAX_ITEMS + 1])
        self.assertEqual(len(res[0]), 5)
        self.assertFalse(res.truncated)

    def test_overflow_is_trimmed_and_flagged(self):
        with mock.patch.object(issue_scan_mod, "_MAX_ITEMS", 30):
            res = _fetch("github", FakeGh(45))
        self.assertEqual(len(res[0]), 30)
        self.assertTrue(res.truncated)
        self.assertEqual(res.truncated_reason, "max_items")

    def test_exactly_at_the_ceiling_is_complete(self):
        with mock.patch.object(issue_scan_mod, "_MAX_ITEMS", 30):
            res = _fetch("github", FakeGh(30))
        self.assertEqual(len(res[0]), 30)
        self.assertFalse(res.truncated)


def _enable_config(root, **overrides):
    cfg = {"state_scanner": {"issue_scan": {
        "enabled": True, "platform": "forgejo", "scan_submodules": False, **overrides}}}
    write_file(root / ".aria" / "config.json", json.dumps(cfg))


class TestCollectorPagination(unittest.TestCase):
    def _scan(self, repo, fake):
        with mock.patch("collectors.issue_scan._run", side_effect=fake):
            with mock.patch("collectors.issue_scan.shutil.which", return_value="/usr/bin/forgejo"):
                return collect_issue_scan(repo)

    def test_open_count_counts_every_page(self):
        with tmp_repo() as repo:
            _enable_config(repo)
            st = self._scan(repo, FakeForgejo(46)).data["issue_status"]
        self.assertEqual(st["open_count"], 46)  # baseline: 20
        self.assertEqual(len(st["items"]), 46)
        self.assertEqual(st["repos"]["foo/bar"]["open_count"], 46)
        self.assertFalse(st["truncated"])
        self.assertFalse(st["repos"]["foo/bar"]["truncated"])

    def test_truncation_reaches_the_repo_entry_and_the_top_level(self):
        with tmp_repo() as repo:
            _enable_config(repo)
            with mock.patch.object(issue_scan_mod, "_MAX_ITEMS", 40):
                st = self._scan(repo, FakeForgejo(100)).data["issue_status"]
        entry = st["repos"]["foo/bar"]
        self.assertEqual(st["open_count"], 40)
        self.assertTrue(st["truncated"])
        self.assertTrue(entry["truncated"])
        self.assertEqual(entry["truncated_reason"], "max_items")

    def test_cache_written_before_pagination_is_not_served(self):
        # Those caches hold at most `limit` rows per repo and cannot say whether
        # they were cut off, so serving one would report a truncated list as full.
        with tmp_repo() as repo:
            _enable_config(repo)
            stale = {"number": 99, "title": "cached", "labels": [], "url": "x"}
            write_file(repo / ".aria" / "cache" / "issues.json", json.dumps({
                "schema_version": "1.1",
                "fetched_at": _now_iso(),
                "ttl_seconds": 900,
                "scan_submodules": False,
                "platform": "forgejo",
                "open_count": 1,
                "items": [stale],
                "open_issues": [],
                "label_summary": {},
                "repos": {"foo/bar": {
                    "platform": "forgejo", "source": "live", "fetch_error": None,
                    "fetched_at": _now_iso(), "open_count": 1, "items": [stale]}},
            }))
            st = self._scan(repo, FakeForgejo(46)).data["issue_status"]
        self.assertEqual(st["source"], "live")
        self.assertEqual(st["open_count"], 46)

    def test_truncation_flag_survives_a_cache_round_trip(self):
        with tmp_repo() as repo:
            _enable_config(repo)
            with mock.patch.object(issue_scan_mod, "_MAX_ITEMS", 40):
                self._scan(repo, FakeForgejo(100))  # populates the cache
            # any live request would fail here, so a passing source=="cache" proves the hit
            second = self._scan(repo, FakeForgejo(100, fail_page=1))
        entry = second.data["issue_status"]["repos"]["foo/bar"]
        self.assertEqual(entry["source"], "cache")
        self.assertTrue(entry["truncated"])
        self.assertEqual(entry["truncated_reason"], "max_items")

    def test_written_schema_version_is_the_one_readers_accept(self):
        with tmp_repo() as repo:
            _enable_config(repo)
            st = self._scan(repo, FakeForgejo(3)).data["issue_status"]
            self.assertEqual(st["schema_version"], SCHEMA_VERSION)
            self.assertIn(SCHEMA_VERSION, issue_scan_mod.SCHEMA_COMPAT)


class TestEmptyEntryShape(unittest.TestCase):
    def test_failed_entry_carries_the_truncation_fields(self):
        entry = _build_empty_repo_entry("forgejo", ERR_TIMEOUT)
        self.assertIs(entry["truncated"], False)
        self.assertIsNone(entry["truncated_reason"])


if __name__ == "__main__":
    unittest.main()
