"""Phase 1.12 multi_remote — subprocess-mocked unit tests (T6.5-followup).

Bumps coverage of `collectors.multi_remote` from 33% → ≥70% by mocking `_run`
across `_remote_parity_local_refs`, `_remote_parity_ls_remote`, `_scan_repo`,
and full `collect_multi_remote` flows including submodule iteration.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from _helpers import tmp_project, tmp_repo, write_file
from collectors.multi_remote import (
    _aggregate_flags,
    _gitdir_for,
    _head_commit,
    _list_remotes,
    _remote_parity_local_refs,
    _remote_parity_ls_remote,
    _scan_repo,
    collect_multi_remote,
)


def _make_run(table):
    def fake(cmd, cwd, timeout=5):
        key = tuple(cmd)
        if key in table:
            return table[key]
        return (1, "", f"unmocked: {' '.join(cmd)}")
    return fake


def _write_fresh_remote_refresh_cache(
    repo: Path, leg_keys: list[str], scan_generation: int = 1
) -> None:
    """Write a `.aria/cache/remote-refresh.json` (F3′ cache) with a JUST-NOW
    `fetched_at` for each `"<repo_path>::<remote>"` key in `leg_keys` — gives
    the F1′/F4′ join in `collect_multi_remote` a `证据资格`-satisfying (evidence
    window default 3600s) leg, since Phase 1's `_overall_parity` now requires
    `evidence_grade=="fresh"` (not just `parity=="equal"`) for positive
    evidence (see multi_remote.py `_apply_freshness_downgrade` docstring)."""
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_file(
        repo / ".aria" / "cache" / "remote-refresh.json",
        json.dumps(
            {
                "scan_generation": scan_generation,
                "legs": {
                    key: {
                        "fetched_at": now_iso,
                        "fetch_ok": "true",
                        "error_kind": None,
                        "generation_fetched": scan_generation,
                        "consecutive_unverified": 0,
                        "coordination_ref_present": None,
                    }
                    for key in leg_keys
                },
            }
        ),
    )


class TestPureHelpers(unittest.TestCase):
    def test_head_commit_success(self):
        run_table = {("git", "rev-parse", "--short=7", "HEAD"): (0, "abc1234\n", "")}
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            self.assertEqual(_head_commit(Path("/x"), 5), "abc1234")

    def test_head_commit_failure_returns_none(self):
        run_table = {("git", "rev-parse", "--short=7", "HEAD"): (1, "", "boom")}
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            self.assertIsNone(_head_commit(Path("/x"), 5))

    def test_head_commit_empty_output(self):
        run_table = {("git", "rev-parse", "--short=7", "HEAD"): (0, "  \n", "")}
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            self.assertIsNone(_head_commit(Path("/x"), 5))

    def test_list_remotes(self):
        run_table = {("git", "remote"): (0, "origin\ngithub\n", "")}
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            self.assertEqual(_list_remotes(Path("/x"), 5), ["origin", "github"])

    def test_list_remotes_failure(self):
        run_table = {("git", "remote"): (1, "", "boom")}
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            self.assertEqual(_list_remotes(Path("/x"), 5), [])

    def test_gitdir_relative(self):
        run_table = {("git", "rev-parse", "--git-dir"): (0, ".git\n", "")}
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            p = _gitdir_for(Path("/tmp/repo"), 5)
            self.assertTrue(str(p).endswith(".git"))

    def test_gitdir_absolute(self):
        run_table = {("git", "rev-parse", "--git-dir"): (0, "/abs/path/.git\n", "")}
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            p = _gitdir_for(Path("/tmp/repo"), 5)
            self.assertEqual(str(p), "/abs/path/.git")

    def test_gitdir_failure(self):
        run_table = {("git", "rev-parse", "--git-dir"): (1, "", "no")}
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            self.assertIsNone(_gitdir_for(Path("/x"), 5))


# F2′ retirement note (main spec stale-refs-false-parity, Phase 1):
# `TestFetchHeadAgeHours` used to live here, exercising `_fetch_head_age_hours`
# (repo-global FETCH_HEAD-mtime staleness). The function is deleted wholesale
# (see collectors/multi_remote.py module docstring) — freshness is now a
# per-remote F1′/F4′ join against the F3′ remote_refresh cache, not a
# repo-global mtime read. `_gitdir_for` (tested in `TestPureHelpers` above) is
# unaffected — it is a generic git-dir resolver retained independently.


class TestParityLocalRefs(unittest.TestCase):
    def test_detached_head(self):
        out = _remote_parity_local_refs(
            Path("/x"), "origin", branch=None, local_head="abc", shallow=False, timeout=5
        )
        self.assertEqual(out["parity"], "unknown")
        self.assertEqual(out["reason"], "detached_head")

    def test_shallow_clone(self):
        out = _remote_parity_local_refs(
            Path("/x"), "origin", branch="master", local_head="abc", shallow=True, timeout=5
        )
        self.assertEqual(out["reason"], "shallow_clone")

    def test_no_local_tracking_ref(self):
        run_table = {
            ("git", "rev-parse", "--short=7", "refs/remotes/origin/master"): (
                1, "", "no ref"
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_local_refs(
                Path("/x"), "origin", "master", "abc1234", False, 5
            )
        self.assertEqual(out["reason"], "no_local_tracking_ref")
        self.assertTrue(out["reachable"])  # local op succeeded-to-run

    def test_equal_parity(self):
        run_table = {
            ("git", "rev-parse", "--short=7", "refs/remotes/origin/master"): (
                0, "abc1234\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", "HEAD...refs/remotes/origin/master"): (
                0, "0\t0\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_local_refs(
                Path("/x"), "origin", "master", "abc1234", False, 5
            )
        self.assertEqual(out["parity"], "equal")
        self.assertEqual(out["ahead_count"], 0)
        self.assertEqual(out["behind_count"], 0)

    def test_ahead_parity(self):
        run_table = {
            ("git", "rev-parse", "--short=7", "refs/remotes/origin/master"): (
                0, "def4567\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", "HEAD...refs/remotes/origin/master"): (
                0, "3\t0\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_local_refs(
                Path("/x"), "origin", "master", "abc1234", False, 5
            )
        self.assertEqual(out["parity"], "ahead")

    def test_behind_parity(self):
        run_table = {
            ("git", "rev-parse", "--short=7", "refs/remotes/origin/master"): (
                0, "def4567\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", "HEAD...refs/remotes/origin/master"): (
                0, "0\t5\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_local_refs(
                Path("/x"), "origin", "master", "abc1234", False, 5
            )
        self.assertEqual(out["parity"], "behind")

    def test_diverged_parity(self):
        run_table = {
            ("git", "rev-parse", "--short=7", "refs/remotes/origin/master"): (
                0, "def4567\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", "HEAD...refs/remotes/origin/master"): (
                0, "2\t3\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_local_refs(
                Path("/x"), "origin", "master", "abc1234", False, 5
            )
        self.assertEqual(out["parity"], "diverged")

    def test_local_head_none_after_remote_resolved(self):
        run_table = {
            ("git", "rev-parse", "--short=7", "refs/remotes/origin/master"): (
                0, "def4567\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_local_refs(
                Path("/x"), "origin", "master", local_head=None, shallow=False, timeout=5
            )
        self.assertEqual(out["reason"], "detached_head")

    def test_rev_list_failed(self):
        run_table = {
            ("git", "rev-parse", "--short=7", "refs/remotes/origin/master"): (
                0, "def4567\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", "HEAD...refs/remotes/origin/master"): (
                128, "", "fatal"
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_local_refs(
                Path("/x"), "origin", "master", "abc1234", False, 5
            )
        self.assertEqual(out["reason"], "rev_list_failed")

    def test_rev_list_parse_failed(self):
        run_table = {
            ("git", "rev-parse", "--short=7", "refs/remotes/origin/master"): (
                0, "def4567\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", "HEAD...refs/remotes/origin/master"): (
                0, "garbage\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_local_refs(
                Path("/x"), "origin", "master", "abc1234", False, 5
            )
        self.assertEqual(out["reason"], "rev_list_parse_failed")

    def test_rev_list_value_error(self):
        run_table = {
            ("git", "rev-parse", "--short=7", "refs/remotes/origin/master"): (
                0, "def4567\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", "HEAD...refs/remotes/origin/master"): (
                0, "x\ty\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_local_refs(
                Path("/x"), "origin", "master", "abc1234", False, 5
            )
        self.assertEqual(out["reason"], "rev_list_parse_failed")


class TestParityLsRemote(unittest.TestCase):
    def test_detached_head_short_circuits(self):
        out = _remote_parity_ls_remote(
            Path("/x"), "origin", None, "abc", False, 5
        )
        self.assertEqual(out["reason"], "detached_head")
        self.assertEqual(out["method"], "ls_remote")

    def test_network_timeout_classification(self):
        run_table = {
            ("git", "ls-remote", "--heads", "origin", "master"): (
                128, "", "fatal: could not resolve host"
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_ls_remote(
                Path("/x"), "origin", "master", "abc", False, 5
            )
        self.assertFalse(out["reachable"])
        self.assertEqual(out["reason"], "network_timeout")

    def test_auth_failed_classification(self):
        run_table = {
            ("git", "ls-remote", "--heads", "origin", "master"): (
                128, "", "fatal: Authentication failed"
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_ls_remote(
                Path("/x"), "origin", "master", "abc", False, 5
            )
        self.assertEqual(out["reason"], "auth_failed")
        self.assertFalse(out["reachable"])

    def test_not_found_classification(self):
        run_table = {
            ("git", "ls-remote", "--heads", "origin", "master"): (
                128, "", "fatal: repository does not exist"
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_ls_remote(
                Path("/x"), "origin", "master", "abc", False, 5
            )
        self.assertEqual(out["reason"], "not_found")

    def test_unclassified_error_falls_back_to_timeout(self):
        run_table = {
            ("git", "ls-remote", "--heads", "origin", "master"): (
                128, "", "fatal: weird error"
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_ls_remote(
                Path("/x"), "origin", "master", "abc", False, 5
            )
        self.assertEqual(out["reason"], "network_timeout")

    def test_remote_branch_missing(self):
        """QA-I1: empty stdout but rc=0 → branch doesn't exist on remote."""
        run_table = {
            ("git", "ls-remote", "--heads", "origin", "feat-x"): (0, "\n", ""),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_ls_remote(
                Path("/x"), "origin", "feat-x", "abc", False, 5
            )
        self.assertEqual(out["reason"], "remote_branch_missing")
        self.assertTrue(out["reachable"])

    def test_malformed_response(self):
        run_table = {
            ("git", "ls-remote", "--heads", "origin", "master"): (
                0, "no-tab-here\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_ls_remote(
                Path("/x"), "origin", "master", "abc", False, 5
            )
        self.assertEqual(out["reason"], "parse_error")
        self.assertTrue(out["reachable"])

    def test_shallow_after_remote_resolved(self):
        run_table = {
            ("git", "ls-remote", "--heads", "origin", "master"): (
                0, "abc1234567890abc1234567890abc1234567890ab\trefs/heads/master\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_ls_remote(
                Path("/x"), "origin", "master", "abc1234", shallow=True, timeout=5
            )
        self.assertEqual(out["reason"], "shallow_clone")
        self.assertEqual(out["remote_head"], "abc1234")

    def test_local_head_none_after_remote(self):
        run_table = {
            ("git", "ls-remote", "--heads", "origin", "master"): (
                0, "abc1234567890abc1234567890abc1234567890ab\trefs/heads/master\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_ls_remote(
                Path("/x"), "origin", "master", local_head=None, shallow=False, timeout=5
            )
        self.assertEqual(out["reason"], "detached_head")

    def test_equal_via_ls_remote(self):
        sha = "abc1234567890abc1234567890abc1234567890ab"
        run_table = {
            ("git", "ls-remote", "--heads", "origin", "master"): (
                0, f"{sha}\trefs/heads/master\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", f"HEAD...{sha}"): (
                0, "0\t0\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_ls_remote(
                Path("/x"), "origin", "master", "abc1234", False, 5
            )
        self.assertEqual(out["parity"], "equal")
        self.assertEqual(out["remote_head"], "abc1234")

    def test_unknown_sha_degrades_to_equal_when_heads_match(self):
        """rc != 0 from rev-list but local_head startswith remote sha → 'equal'."""
        sha = "abc1234567890abc1234567890abc1234567890ab"
        run_table = {
            ("git", "ls-remote", "--heads", "origin", "master"): (
                0, f"{sha}\trefs/heads/master\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", f"HEAD...{sha}"): (
                128, "", "unknown sha"
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_ls_remote(
                Path("/x"), "origin", "master", "abc1234", False, 5
            )
        # local_head=abc1234 is the prefix of remote sha
        self.assertEqual(out["parity"], "equal")
        self.assertEqual(out["ahead_count"], 0)
        self.assertEqual(out["behind_count"], 0)

    def test_unknown_sha_no_match_stays_unknown(self):
        sha = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        run_table = {
            ("git", "ls-remote", "--heads", "origin", "master"): (
                0, f"{sha}\trefs/heads/master\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", f"HEAD...{sha}"): (
                128, "", "unknown sha"
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_ls_remote(
                Path("/x"), "origin", "master", "abc1234", False, 5
            )
        self.assertEqual(out["parity"], "unknown")

    def test_rev_list_parse_failure_in_ls_remote(self):
        sha = "abc1234567890abc1234567890abc1234567890ab"
        run_table = {
            ("git", "ls-remote", "--heads", "origin", "master"): (
                0, f"{sha}\trefs/heads/master\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", f"HEAD...{sha}"): (
                0, "weird\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_ls_remote(
                Path("/x"), "origin", "master", "deadbe", False, 5
            )
        self.assertEqual(out["parity"], "unknown")

    def test_ls_remote_ahead_classification(self):
        sha = "abc1234567890abc1234567890abc1234567890ab"
        run_table = {
            ("git", "ls-remote", "--heads", "origin", "master"): (
                0, f"{sha}\trefs/heads/master\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", f"HEAD...{sha}"): (
                0, "3\t0\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_ls_remote(
                Path("/x"), "origin", "master", "deadbe", False, 5
            )
        self.assertEqual(out["parity"], "ahead")
        self.assertEqual(out["ahead_count"], 3)

    def test_ls_remote_behind_classification(self):
        sha = "abc1234567890abc1234567890abc1234567890ab"
        run_table = {
            ("git", "ls-remote", "--heads", "origin", "master"): (
                0, f"{sha}\trefs/heads/master\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", f"HEAD...{sha}"): (
                0, "0\t4\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_ls_remote(
                Path("/x"), "origin", "master", "deadbe", False, 5
            )
        self.assertEqual(out["parity"], "behind")
        self.assertEqual(out["behind_count"], 4)

    def test_ls_remote_diverged_classification(self):
        sha = "abc1234567890abc1234567890abc1234567890ab"
        run_table = {
            ("git", "ls-remote", "--heads", "origin", "master"): (
                0, f"{sha}\trefs/heads/master\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", f"HEAD...{sha}"): (
                0, "2\t1\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_ls_remote(
                Path("/x"), "origin", "master", "deadbe", False, 5
            )
        self.assertEqual(out["parity"], "diverged")

    def test_rev_list_value_error_in_ls_remote(self):
        sha = "abc1234567890abc1234567890abc1234567890ab"
        run_table = {
            ("git", "ls-remote", "--heads", "origin", "master"): (
                0, f"{sha}\trefs/heads/master\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", f"HEAD...{sha}"): (
                0, "x\ty\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            out = _remote_parity_ls_remote(
                Path("/x"), "origin", "master", "deadbe", False, 5
            )
        self.assertEqual(out["parity"], "unknown")


class TestScanRepo(unittest.TestCase):
    def test_scan_with_two_remotes_local_refs(self):
        run_table = {
            ("git", "rev-parse", "--short=7", "HEAD"): (0, "abc1234\n", ""),
            ("git", "remote"): (0, "origin\ngithub\n", ""),
            ("git", "rev-parse", "--short=7", "refs/remotes/origin/master"): (
                0, "abc1234\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", "HEAD...refs/remotes/origin/master"): (
                0, "0\t0\n", ""
            ),
            ("git", "rev-parse", "--short=7", "refs/remotes/github/master"): (
                0, "def5678\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", "HEAD...refs/remotes/github/master"): (
                0, "1\t0\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            with mock.patch(
                "collectors.multi_remote._is_shallow", return_value=False
            ), mock.patch(
                "collectors.multi_remote._current_branch", return_value="master"
            ):
                # F2′ retirement: _scan_repo now returns the block alone (the
                # `stale` tuple element was a dead `False` constant — see
                # collectors/multi_remote.py `_scan_repo` docstring).
                block = _scan_repo(
                    Path("/x"), ".", verify_mode="local_refs", timeout=5
                )
        self.assertEqual(block["branch"], "master")
        self.assertEqual(len(block["remotes"]), 2)
        parities = [r["parity"] for r in block["remotes"]]
        self.assertEqual(set(parities), {"equal", "ahead"})

    def test_scan_with_ls_remote_mode(self):
        sha = "abc1234567890abc1234567890abc1234567890ab"
        run_table = {
            ("git", "rev-parse", "--short=7", "HEAD"): (0, "abc1234\n", ""),
            ("git", "remote"): (0, "origin\n", ""),
            ("git", "ls-remote", "--heads", "origin", "master"): (
                0, f"{sha}\trefs/heads/master\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count", f"HEAD...{sha}"): (
                0, "0\t0\n", ""
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            with mock.patch(
                "collectors.multi_remote._is_shallow", return_value=False
            ), mock.patch(
                "collectors.multi_remote._current_branch", return_value="master"
            ):
                block = _scan_repo(
                    Path("/x"), ".", verify_mode="ls_remote", timeout=5
                )
        self.assertEqual(block["remotes"][0]["method"], "ls_remote")
        self.assertEqual(block["remotes"][0]["parity"], "equal")


class TestCollectorFullFlow(unittest.TestCase):
    def test_full_main_repo_flow_with_config_overrides(self):
        with tmp_repo() as repo:
            write_file(
                repo / ".aria" / "config.json",
                json.dumps({
                    "state_scanner": {
                        "multi_remote": {
                            "enabled": True,
                            "verify_mode": "local_refs",
                            "timeout_seconds": 3,
                        }
                    }
                }),
            )
            # F1′/F4′ (Phase 1): the ∃-evidence clause now requires
            # evidence_grade=="fresh", not just parity=="equal" — inject a
            # just-fetched remote_refresh leg for (".", "origin") so this
            # fixture's `equal` remains positive evidence.
            _write_fresh_remote_refresh_cache(repo, [".::origin"])
            run_table = {
                ("git", "rev-parse", "--is-inside-work-tree"): (0, "true\n", ""),
                ("git", "rev-parse", "--short=7", "HEAD"): (0, "abc1234\n", ""),
                ("git", "remote"): (0, "origin\n", ""),
                ("git", "rev-parse", "--short=7", "refs/remotes/origin/master"): (
                    0, "abc1234\n", ""
                ),
                ("git", "rev-list", "--left-right", "--count", "HEAD...refs/remotes/origin/master"): (
                    0, "0\t0\n", ""
                ),
            }
            with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
                with mock.patch(
                    "collectors.multi_remote._is_shallow", return_value=False
                ), mock.patch(
                    "collectors.multi_remote._current_branch", return_value="master"
                ), mock.patch(
                    "collectors.multi_remote._enumerate_submodule_paths", return_value=[]
                ):
                    r = collect_multi_remote(repo)
        self.assertTrue(r.data["enabled"])
        self.assertTrue(r.data["overall_parity"])
        self.assertFalse(r.data["has_pending_push"])
        self.assertEqual(r.data["main_repo"]["remotes"][0]["parity"], "equal")

    def test_invalid_verify_mode_falls_back(self):
        with tmp_repo() as repo:
            write_file(
                repo / ".aria" / "config.json",
                json.dumps({
                    "state_scanner": {
                        "multi_remote": {"enabled": True, "verify_mode": "BOGUS"}
                    }
                }),
            )
            run_table = {
                ("git", "rev-parse", "--is-inside-work-tree"): (0, "true\n", ""),
                ("git", "rev-parse", "--short=7", "HEAD"): (0, "abc1234\n", ""),
                ("git", "remote"): (0, "origin\n", ""),
                ("git", "rev-parse", "--short=7", "refs/remotes/origin/master"): (
                    0, "def5678\n", ""
                ),
                ("git", "rev-list", "--left-right", "--count", "HEAD...refs/remotes/origin/master"): (
                    0, "0\t3\n", ""
                ),
            }
            with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
                with mock.patch(
                    "collectors.multi_remote._is_shallow", return_value=False
                ), mock.patch(
                    "collectors.multi_remote._current_branch", return_value="master"
                ), mock.patch(
                    "collectors.multi_remote._enumerate_submodule_paths", return_value=[]
                ):
                    r = collect_multi_remote(repo)
        self.assertEqual(r.data["main_repo"]["remotes"][0]["method"], "local_refs")
        self.assertEqual(r.data["main_repo"]["remotes"][0]["parity"], "behind")
        self.assertFalse(r.data["overall_parity"])

    def test_with_submodule_enumeration(self):
        with tmp_repo() as repo:
            (repo / "sub").mkdir()
            (repo / "sub" / ".git").write_text("gitdir: ../.git/modules/sub\n")
            run_table = {
                ("git", "rev-parse", "--is-inside-work-tree"): (0, "true\n", ""),
                ("git", "rev-parse", "--short=7", "HEAD"): (0, "abc1234\n", ""),
                ("git", "remote"): (0, "origin\n", ""),
                ("git", "rev-parse", "--short=7", "refs/remotes/origin/master"): (
                    0, "abc1234\n", ""
                ),
                ("git", "rev-list", "--left-right", "--count", "HEAD...refs/remotes/origin/master"): (
                    0, "0\t0\n", ""
                ),
            }
            with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
                with mock.patch(
                    "collectors.multi_remote._is_shallow", return_value=False
                ), mock.patch(
                    "collectors.multi_remote._current_branch", return_value="master"
                ), mock.patch(
                    "collectors.multi_remote._enumerate_submodule_paths",
                    return_value=["sub"],
                ):
                    r = collect_multi_remote(repo)
        self.assertEqual(len(r.data["submodules"]), 1)
        self.assertEqual(r.data["submodules"][0]["path"], "sub")

    def test_uninitialized_submodule_skipped(self):
        with tmp_repo() as repo:
            # `sub` exists but no .git inside → skipped per fail-soft
            (repo / "sub").mkdir()
            run_table = {
                ("git", "rev-parse", "--is-inside-work-tree"): (0, "true\n", ""),
                ("git", "rev-parse", "--short=7", "HEAD"): (0, "abc1234\n", ""),
                ("git", "remote"): (0, "", ""),
            }
            with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
                with mock.patch(
                    "collectors.multi_remote._is_shallow", return_value=False
                ), mock.patch(
                    "collectors.multi_remote._current_branch", return_value="master"
                ), mock.patch(
                    "collectors.multi_remote._enumerate_submodule_paths",
                    return_value=["sub"],
                ):
                    r = collect_multi_remote(repo)
        self.assertEqual(r.data["submodules"], [])

    # F2′ retirement note (main spec stale-refs-false-parity, Phase 1, task
    # 12.3): `test_local_refs_stale_flag` and
    # `test_warn_after_hours_inherits_from_sync_check` used to live here,
    # asserting the now-deleted `local_refs_stale` output field and
    # `warn_after_hours` sync_check-inheritance behavior. Both are DELETED
    # (not rewritten — the feature they pinned is retired wholesale, nothing
    # meaningful to reassert). See collectors/multi_remote.py module docstring
    # + `_load_config` docstring for the replacement (per-remote
    # `evidence_grade`, F1′/F4′ join against the F3′ remote_refresh cache).

    def test_malformed_config_falls_back(self):
        from collectors.multi_remote import _load_config

        with tmp_repo() as repo:
            write_file(repo / ".aria" / "config.json", "not json {")
            cfg = _load_config(repo)
            self.assertEqual(cfg, {})

    def test_missing_config_returns_empty(self):
        from collectors.multi_remote import _load_config

        with tmp_project() as root:
            self.assertEqual(_load_config(root), {})

    def test_aggregate_all_unknown_yields_false(self):
        """Multiple unknown remotes (no equal evidence) → overall_parity=False."""
        flags = _aggregate_flags([
            {"parity": "unknown", "reachable": True, "reason": "no_local_tracking_ref"},
            {"parity": "unknown", "reachable": True, "reason": "shallow_clone"},
        ])
        self.assertFalse(flags["overall_parity"])
        self.assertFalse(flags["has_unreachable_remote"])

    def test_aggregate_unreachable_via_unknown_with_network_reason(self):
        flags = _aggregate_flags([
            {"parity": "unknown", "reachable": True, "reason": "auth_failed"},
        ])
        self.assertTrue(flags["has_unreachable_remote"])

    def test_aggregate_reachable_false_marks_unreachable(self):
        flags = _aggregate_flags([
            {"parity": "unknown", "reachable": False, "reason": "network_timeout"},
            {"parity": "equal", "reachable": True},
        ])
        self.assertTrue(flags["has_unreachable_remote"])
        self.assertTrue(flags["overall_parity"])  # equal evidence + no blockers


class TestRemotePolicyNamespace(unittest.TestCase):
    """Task 1.6 — `_resolve_remote_policy` pure inheritance matrix.

    Contract under test is phase-c-integrator/SKILL.md §C.2.5 step 3: skill-level
    null inherits top-level; skill-level non-null wins outright.
    """

    def test_skill_null_inherits_top_level(self):
        from collectors.multi_remote import _resolve_remote_policy

        out = _resolve_remote_policy(
            {"enabled": True, "enforced_remotes": None, "read_only_remotes": None},
            {"enforced_remotes": ["origin"], "read_only_remotes": ["mirror"]},
        )
        self.assertEqual(out["enforced_remotes"], ["origin"])
        self.assertEqual(out["read_only_remotes"], ["mirror"])

    def test_absent_skill_key_inherits_top_level(self):
        from collectors.multi_remote import _resolve_remote_policy

        out = _resolve_remote_policy({"enabled": True}, {"enforced_remotes": ["origin"]})
        self.assertEqual(out["enforced_remotes"], ["origin"])

    def test_skill_value_wins_over_top_level(self):
        from collectors.multi_remote import _resolve_remote_policy

        out = _resolve_remote_policy(
            {"enforced_remotes": ["github"]}, {"enforced_remotes": ["origin"]}
        )
        self.assertEqual(out["enforced_remotes"], ["github"])

    def test_explicit_empty_list_wins_and_is_not_treated_as_null(self):
        """`[]` at skill level is a PRESENT value → it wins, and it must NOT be
        re-read as "inherit". (Its own meaning — auto-discover-all — belongs to
        `resolve_enforced_remotes`, not to this resolver.)"""
        from collectors.multi_remote import _resolve_remote_policy

        out = _resolve_remote_policy(
            {"enforced_remotes": []}, {"enforced_remotes": ["origin"]}
        )
        self.assertEqual(out["enforced_remotes"], [])

    def test_unrelated_keys_untouched(self):
        from collectors.multi_remote import _resolve_remote_policy

        out = _resolve_remote_policy(
            {"enabled": False, "timeout_seconds": 3}, {"enforced_remotes": ["origin"]}
        )
        self.assertFalse(out["enabled"])
        self.assertEqual(out["timeout_seconds"], 3)


class TestEnforcedPolicyGovernsVerdict(unittest.TestCase):
    """Tasks 6.1/6.2 — F5′ enforced/read-only filtering reaches the CORE verdict.

    Falsifiability note (this is the point of the class): every test here is
    written so it FAILS against the pre-task-6 code, where `_overall_parity` was
    handed `all_remote_entries` unfiltered. A green run on the Aria repo's own
    config proves nothing — that config sets neither policy key, so the filter is
    a no-op there (memory: `noop_in_test_env_hardening_needs_mechanism_assertion`).
    """

    def _two_remote_repo(self, repo: Path, policy: dict, mirror_counts: str = "0\t3\n"):
        """origin: equal+fresh. mirror: `mirror_counts` (default = behind by 3)."""
        write_file(
            repo / ".aria" / "config.json",
            json.dumps({"state_scanner": {"multi_remote": dict(policy)}}),
        )
        _write_fresh_remote_refresh_cache(repo, [".::origin", ".::mirror"])
        return {
            ("git", "rev-parse", "--is-inside-work-tree"): (0, "true\n", ""),
            ("git", "rev-parse", "--short=7", "HEAD"): (0, "abc1234\n", ""),
            ("git", "remote"): (0, "origin\nmirror\n", ""),
            ("git", "rev-parse", "--short=7", "refs/remotes/origin/master"): (
                0, "abc1234\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count",
             "HEAD...refs/remotes/origin/master"): (0, "0\t0\n", ""),
            ("git", "rev-parse", "--short=7", "refs/remotes/mirror/master"): (
                0, "def5678\n", ""
            ),
            ("git", "rev-list", "--left-right", "--count",
             "HEAD...refs/remotes/mirror/master"): (0, mirror_counts, ""),
        }

    def _collect(self, repo, run_table):
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)):
            with mock.patch(
                "collectors.multi_remote._is_shallow", return_value=False
            ), mock.patch(
                "collectors.multi_remote._current_branch", return_value="master"
            ), mock.patch(
                "collectors.multi_remote._enumerate_submodule_paths", return_value=[]
            ):
                return collect_multi_remote(repo)

    def test_read_only_remote_excluded_from_overall_parity(self):
        """A behind read-only mirror must NOT drag the verdict false.

        Pre-fix behavior: mirror is in `all_remote_entries` → clause 4 sees
        parity=="behind" → False. That is the "read_only_remotes is a dead key"
        defect this task closes.
        """
        with tmp_repo() as repo:
            table = self._two_remote_repo(repo, {"read_only_remotes": ["mirror"]})
            r = self._collect(repo, table)
        self.assertTrue(r.data["overall_parity"])
        # The excluded remote is still REPORTED verbatim — filtering governs the
        # verdict, it does not hide data from the operator.
        names = [e["name"] for e in r.data["main_repo"]["remotes"]]
        self.assertIn("mirror", names)
        self.assertEqual(
            next(e for e in r.data["main_repo"]["remotes"] if e["name"] == "mirror")["parity"],
            "behind",
        )

    def test_without_policy_the_behind_mirror_still_blocks(self):
        """Control: same fixture, no policy → verdict false. Guards against the
        filter silently swallowing everything regardless of config."""
        with tmp_repo() as repo:
            table = self._two_remote_repo(repo, {})
            r = self._collect(repo, table)
        self.assertFalse(r.data["overall_parity"])

    def test_enforced_allowlist_narrows_the_verdict(self):
        with tmp_repo() as repo:
            table = self._two_remote_repo(repo, {"enforced_remotes": ["origin"]})
            r = self._collect(repo, table)
        self.assertTrue(r.data["overall_parity"])

    def test_policy_inherited_from_top_level_block(self):
        """Task 1.6 end-to-end: the policy lives at TOP level, skill block present
        but leaves it null → same verdict as if it were skill-local."""
        with tmp_repo() as repo:
            write_file(
                repo / ".aria" / "config.json",
                json.dumps({
                    "multi_remote": {"read_only_remotes": ["mirror"]},
                    "state_scanner": {
                        "multi_remote": {"enabled": True, "read_only_remotes": None}
                    },
                }),
            )
            _write_fresh_remote_refresh_cache(repo, [".::origin", ".::mirror"])
            table = {
                ("git", "rev-parse", "--is-inside-work-tree"): (0, "true\n", ""),
                ("git", "rev-parse", "--short=7", "HEAD"): (0, "abc1234\n", ""),
                ("git", "remote"): (0, "origin\nmirror\n", ""),
                ("git", "rev-parse", "--short=7", "refs/remotes/origin/master"): (
                    0, "abc1234\n", ""
                ),
                ("git", "rev-list", "--left-right", "--count",
                 "HEAD...refs/remotes/origin/master"): (0, "0\t0\n", ""),
                ("git", "rev-parse", "--short=7", "refs/remotes/mirror/master"): (
                    0, "def5678\n", ""
                ),
                ("git", "rev-list", "--left-right", "--count",
                 "HEAD...refs/remotes/mirror/master"): (0, "0\t3\n", ""),
            }
            r = self._collect(repo, table)
        self.assertTrue(r.data["overall_parity"])

    def test_policy_excluding_every_remote_is_fail_closed(self):
        """R3/R4 audit hazard: read-only covering ALL remotes empties the
        participating set. `all([]) == True` would report "in sync" on ZERO
        evidence — clause 1 must return False instead."""
        with tmp_repo() as repo:
            table = self._two_remote_repo(
                repo, {"read_only_remotes": ["origin", "mirror"]}, mirror_counts="0\t0\n"
            )
            r = self._collect(repo, table)
        self.assertFalse(r.data["overall_parity"])

    def test_has_pending_push_stays_unfiltered(self):
        """6.2 scope boundary (task 5.3 preserved decision): ahead-detection is NOT
        narrowed by the policy — an unpushed commit is worth surfacing even on a
        remote whose parity you opted out of."""
        with tmp_repo() as repo:
            table = self._two_remote_repo(
                repo, {"read_only_remotes": ["mirror"]}, mirror_counts="2\t0\n"
            )
            r = self._collect(repo, table)
        self.assertTrue(r.data["has_pending_push"])
        self.assertTrue(r.data["overall_parity"])

    def test_has_unreachable_remote_respects_policy(self):
        """6.2: the read-only exclusion applies to `has_unreachable_remote` too —
        otherwise a mirror that merely blips the network still lights up the
        global warning (and, through it, the `multi_remote_drift` rule)."""
        with tmp_repo() as repo:
            write_file(
                repo / ".aria" / "config.json",
                json.dumps({
                    "state_scanner": {"multi_remote": {"read_only_remotes": ["mirror"]}}
                }),
            )
            now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
            write_file(
                repo / ".aria" / "cache" / "remote-refresh.json",
                json.dumps({
                    "scan_generation": 1,
                    "legs": {
                        ".::origin": {
                            "fetched_at": now_iso, "fetch_ok": "true",
                            "error_kind": None, "generation_fetched": 1,
                            "consecutive_unverified": 0,
                            "coordination_ref_present": None,
                        },
                        ".::mirror": {
                            "fetched_at": now_iso, "fetch_ok": "false",
                            "error_kind": "network", "generation_fetched": 1,
                            "consecutive_unverified": 1,
                            "coordination_ref_present": None,
                        },
                    },
                }),
            )
            table = {
                ("git", "rev-parse", "--is-inside-work-tree"): (0, "true\n", ""),
                ("git", "rev-parse", "--short=7", "HEAD"): (0, "abc1234\n", ""),
                ("git", "remote"): (0, "origin\nmirror\n", ""),
                ("git", "rev-parse", "--short=7", "refs/remotes/origin/master"): (
                    0, "abc1234\n", ""
                ),
                ("git", "rev-list", "--left-right", "--count",
                 "HEAD...refs/remotes/origin/master"): (0, "0\t0\n", ""),
                ("git", "rev-parse", "--short=7", "refs/remotes/mirror/master"): (
                    0, "abc1234\n", ""
                ),
                ("git", "rev-list", "--left-right", "--count",
                 "HEAD...refs/remotes/mirror/master"): (0, "0\t0\n", ""),
            }
            r = self._collect(repo, table)
        self.assertFalse(r.data["has_unreachable_remote"])


if __name__ == "__main__":
    unittest.main()
