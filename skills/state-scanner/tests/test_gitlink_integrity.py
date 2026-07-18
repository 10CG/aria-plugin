"""Phase 2A F10″ — orphaned-gitlink cross-repo reachability (R5-C-A accident
remedy). Tests the five new predicate functions (`_resolve_published_gitlink_sha`
/ `_gitlink_unreachable` / `_looks_like_no_such_commit` /
`_gitlink_reachability_verdict` / `_classify_gitlink_pair`), the gitlink-layer
D18 counter cache (`_gitlink_pair_key` / `_read_gitlink_cache` /
`_write_gitlink_cache_atomic`), the `_gitlink_blocking`/`_overall_parity`
signature change, and the `collect_multi_remote` R×S double-loop wiring.

Blueprint refs (scratchpad p2_f10.md / p2_qa.md, this session):
  - `eight_branch_domain`: the fixed nine-branch (eight non-ok + implicit ok)
    control-flow order `_classify_gitlink_pair` must follow.
  - `ac16_orphaned` / `ac17_four_branches`: AC-16 (2026-07-12 accident replay)
    + AC-17 (a/b/c1/c2/d/e/f) test matrix.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from _helpers import run_git, tmp_project, tmp_repo, write_file  # noqa: E402
from collectors import multi_remote as mr  # type: ignore  # noqa: E402

NOW = datetime(2026, 7, 17, 15, 0, 0, tzinfo=timezone.utc)
WIN = 3600
HARD = 7 * 86400
K_EFF = 4

C_SHA = "c" * 40
G_SHA = "g" * 40


def _make_run(table):
    def fake(cmd, cwd, timeout=5):
        key = tuple(cmd)
        if key in table:
            return table[key]
        return (1, "", f"unmocked: {' '.join(cmd)}")

    return fake


def _exempt_leg(scan_generation=5, consecutive_unverified=0):
    return {
        "fetched_at": NOW.isoformat(timespec="seconds"),
        "fetch_ok": "true",
        "generation_fetched": scan_generation,
        "consecutive_unverified": consecutive_unverified,
    }


def _stale_leg():
    """Never-fetched leg — exemption-INELIGIBLE (fetched_at is None)."""
    return None


class TestParseLsTreeGitlinkEntry(unittest.TestCase):
    def test_valid_gitlink_line(self):
        out = f"160000 commit {G_SHA}\tstandards\n"
        self.assertEqual(mr._parse_ls_tree_gitlink_entry(out), G_SHA)

    def test_empty_output_gap_fill(self):
        # path does not exist in C's tree at all — rc=0, EMPTY stdout (not a
        # non-zero rc — R7 backend M-1). Byte-indistinguishable from a
        # mode-mismatch case; both collapse to None (not_a_gitlink upstream).
        self.assertIsNone(mr._parse_ls_tree_gitlink_entry(""))

    def test_mode_mismatch_ordinary_directory(self):
        out = "040000 tree ttttttttttttttttttttttttttttttttttttttttt\tstandards\n"
        self.assertIsNone(mr._parse_ls_tree_gitlink_entry(out))

    def test_path_with_spaces_tab_anchored(self):
        out = f"160000 commit {G_SHA}\tvendor/my submodule\n"
        self.assertEqual(mr._parse_ls_tree_gitlink_entry(out), G_SHA)

    def test_malformed_no_tab(self):
        self.assertIsNone(mr._parse_ls_tree_gitlink_entry("garbage no tab here"))

    def test_malformed_too_few_fields(self):
        self.assertIsNone(mr._parse_ls_tree_gitlink_entry("160000 commit\tstandards\n"))


class TestLooksLikeNoSuchCommit(unittest.TestCase):
    def test_no_such_commit(self):
        self.assertTrue(mr._looks_like_no_such_commit("error: no such commit 79b7cd6"))

    def test_bad_object(self):
        self.assertTrue(mr._looks_like_no_such_commit("fatal: bad object 79b7cd6"))

    def test_not_a_valid_object_name(self):
        self.assertTrue(
            mr._looks_like_no_such_commit("fatal: not a valid object name 79b7cd6")
        )

    def test_unrelated_stderr_false(self):
        self.assertFalse(mr._looks_like_no_such_commit("fatal: repository not found"))

    def test_case_insensitive(self):
        self.assertTrue(mr._looks_like_no_such_commit("FATAL: BAD OBJECT abc123"))


class TestResolvePublishedGitlinkSha(unittest.TestCase):
    def test_main_branch_none_short_circuits(self):
        c, g = mr._resolve_published_gitlink_sha(Path("/x"), None, "github", "standards", 5)
        self.assertIsNone(c)
        self.assertIsNone(g)

    def test_rev_parse_failure_yields_none_none(self):
        table = {("git", "rev-parse", "refs/remotes/github/master"): (1, "", "unknown ref")}
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(table)):
            c, g = mr._resolve_published_gitlink_sha(
                Path("/x"), "master", "github", "standards", 5
            )
        self.assertIsNone(c)
        self.assertIsNone(g)

    def test_rev_parse_empty_stdout_yields_none_none(self):
        table = {("git", "rev-parse", "refs/remotes/github/master"): (0, "\n", "")}
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(table)):
            c, g = mr._resolve_published_gitlink_sha(
                Path("/x"), "master", "github", "standards", 5
            )
        self.assertIsNone(c)
        self.assertIsNone(g)

    def test_success_resolves_both(self):
        table = {
            ("git", "rev-parse", "refs/remotes/github/master"): (0, f"{C_SHA}\n", ""),
            ("git", "ls-tree", C_SHA, "--", "standards"): (
                0,
                f"160000 commit {G_SHA}\tstandards\n",
                "",
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(table)):
            c, g = mr._resolve_published_gitlink_sha(
                Path("/x"), "master", "github", "standards", 5
            )
        self.assertEqual(c, C_SHA)
        self.assertEqual(g, G_SHA)

    def test_ls_tree_failure_yields_c_but_none_g(self):
        table = {
            ("git", "rev-parse", "refs/remotes/github/master"): (0, f"{C_SHA}\n", ""),
            ("git", "ls-tree", C_SHA, "--", "standards"): (128, "", "fatal: bad tree"),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(table)):
            c, g = mr._resolve_published_gitlink_sha(
                Path("/x"), "master", "github", "standards", 5
            )
        self.assertEqual(c, C_SHA)
        self.assertIsNone(g)

    def test_mode_mismatch_yields_c_but_none_g(self):
        table = {
            ("git", "rev-parse", "refs/remotes/github/master"): (0, f"{C_SHA}\n", ""),
            ("git", "ls-tree", C_SHA, "--", "standards"): (
                0,
                "040000 tree ttttttttttttttttttttttttttttttttttttttttt\tstandards\n",
                "",
            ),
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(table)):
            c, g = mr._resolve_published_gitlink_sha(
                Path("/x"), "master", "github", "standards", 5
            )
        self.assertEqual(c, C_SHA)
        self.assertIsNone(g)


class TestGitlinkUnreachable(unittest.TestCase):
    def _run_check(self, table):
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(table)):
            return mr._gitlink_unreachable(Path("/sub"), "github", G_SHA, 5)

    def test_reachable(self):
        table = {
            (
                "git", "-C", "/sub", "branch", "-r", "--contains", G_SHA, "--list", "github/*",
            ): (0, "github/master\n", "")
        }
        unreachable, is_soft_error = self._run_check(table)
        self.assertFalse(unreachable)
        self.assertFalse(is_soft_error)

    def test_unreachable_empty_output_mirror_lag(self):
        table = {
            (
                "git", "-C", "/sub", "branch", "-r", "--contains", G_SHA, "--list", "github/*",
            ): (0, "", "")
        }
        unreachable, is_soft_error = self._run_check(table)
        self.assertTrue(unreachable)
        self.assertFalse(is_soft_error)

    def test_rc129_no_such_commit_is_unreachable_not_soft_error(self):
        # R7 backend C-4 severity-inversion guard: the MORE severe case (G
        # nowhere to be found) must NOT be downgraded to soft_error.
        table = {
            (
                "git", "-C", "/sub", "branch", "-r", "--contains", G_SHA, "--list", "github/*",
            ): (129, "", f"fatal: bad object {G_SHA}")
        }
        unreachable, is_soft_error = self._run_check(table)
        self.assertTrue(unreachable)
        self.assertFalse(is_soft_error)

    def test_rc129_unrecognized_stderr_falls_to_soft_error(self):
        table = {
            (
                "git", "-C", "/sub", "branch", "-r", "--contains", G_SHA, "--list", "github/*",
            ): (129, "", "fatal: something else entirely")
        }
        unreachable, is_soft_error = self._run_check(table)
        self.assertFalse(unreachable)
        self.assertTrue(is_soft_error)

    def test_other_nonzero_rc_is_soft_error(self):
        table = {
            (
                "git", "-C", "/sub", "branch", "-r", "--contains", G_SHA, "--list", "github/*",
            ): (128, "", "fatal: repository corrupted")
        }
        unreachable, is_soft_error = self._run_check(table)
        self.assertFalse(unreachable)
        self.assertTrue(is_soft_error)


class TestGitlinkReachabilityVerdict(unittest.TestCase):
    def test_both_exempt_and_gen_ok_is_orphaned(self):
        main_leg = _exempt_leg(scan_generation=5)
        sub_leg = _exempt_leg(scan_generation=5)
        status = mr._gitlink_reachability_verdict(
            main_leg, sub_leg, NOW, 6, WIN, HARD, K_EFF
        )
        self.assertEqual(status, "orphaned")

    def test_main_not_exempt_is_orphan_unverified(self):
        status = mr._gitlink_reachability_verdict(
            _stale_leg(), _exempt_leg(scan_generation=5), NOW, 6, WIN, HARD, K_EFF
        )
        self.assertEqual(status, "orphan_unverified")

    def test_sub_not_exempt_is_orphan_unverified(self):
        status = mr._gitlink_reachability_verdict(
            _exempt_leg(scan_generation=5), _stale_leg(), NOW, 6, WIN, HARD, K_EFF
        )
        self.assertEqual(status, "orphan_unverified")

    def test_neither_exempt_is_orphan_unverified(self):
        status = mr._gitlink_reachability_verdict(
            _stale_leg(), _stale_leg(), NOW, 6, WIN, HARD, K_EFF
        )
        self.assertEqual(status, "orphan_unverified")

    def test_cross_leg_generation_skew_blocks_orphaned_even_if_both_exempt(self):
        # RM-2: sub leg is genuinely older (stale) than the main leg — both
        # individually exempt, but gen(S,R) < gen(main,R) ⇒ time-order
        # ambiguity ⇒ orphan_unverified, NOT orphaned (防假红).
        main_leg = _exempt_leg(scan_generation=6)
        sub_leg = _exempt_leg(scan_generation=5)
        status = mr._gitlink_reachability_verdict(
            main_leg, sub_leg, NOW, 7, WIN, HARD, K_EFF
        )
        self.assertEqual(status, "orphan_unverified")

    def test_sub_ahead_of_main_generation_is_orphaned(self):
        # sub leg caught up / is newer — gen_ok holds (sub_gen >= main_gen).
        main_leg = _exempt_leg(scan_generation=5)
        sub_leg = _exempt_leg(scan_generation=6)
        status = mr._gitlink_reachability_verdict(
            main_leg, sub_leg, NOW, 6, WIN, HARD, K_EFF
        )
        self.assertEqual(status, "orphaned")


class TestGitlinkBlockingThreshold(unittest.TestCase):
    def test_orphaned_always_blocks_regardless_of_k_eff(self):
        self.assertTrue(mr._gitlink_blocking({"status": "orphaned"}, 1))
        self.assertTrue(mr._gitlink_blocking({"status": "orphaned"}, 999))

    def test_orphan_unverified_below_threshold_does_not_block(self):
        g = {"status": "orphan_unverified", "consecutive_unverified": 2}
        self.assertFalse(mr._gitlink_blocking(g, 4))

    def test_orphan_unverified_at_threshold_blocks(self):
        g = {"status": "orphan_unverified", "consecutive_unverified": 4}
        self.assertTrue(mr._gitlink_blocking(g, 4))

    def test_orphan_unverified_non_int_counter_treated_as_zero(self):
        g = {"status": "orphan_unverified", "consecutive_unverified": "bogus"}
        self.assertFalse(mr._gitlink_blocking(g, 1))

    def test_benign_statuses_never_block(self):
        for status in (
            "ok", "no_published_ref", "not_a_gitlink", "uninitialized",
            "no_matching_remote", "shallow_unverifiable", "soft_error",
        ):
            self.assertFalse(mr._gitlink_blocking({"status": status}, 0), status)


class TestClassifyGitlinkPairDomains(unittest.TestCase):
    """Nine-branch domain (eight-non-ok + implicit ok), one fixture each,
    following the fixed order the blueprint derives."""

    def _base_kwargs(self, sub_dir, main_leg=None, sub_leg=None):
        return dict(
            main_repo_dir=Path("/main"),
            main_branch="master",
            sub_dir=sub_dir,
            sub_path="standards",
            remote="github",
            main_leg=main_leg,
            sub_leg=sub_leg,
            timeout=5,
            now=NOW,
            scan_generation=6,
            evidence_window_seconds=WIN,
            hard_cap_seconds=HARD,
            k_eff=K_EFF,
            c=C_SHA,
            main_leg_ok=True,
        )

    def test_branch1_no_published_ref_short_circuits_before_any_git_call(self):
        kwargs = self._base_kwargs(Path("/does/not/matter"))
        kwargs["main_leg_ok"] = False
        kwargs["c"] = None
        # No _run mock at all — must not touch git.
        status = mr._classify_gitlink_pair(**kwargs)
        self.assertEqual(status, "no_published_ref")

    def test_branch2_not_a_gitlink_gap_fill_empty_ls_tree(self):
        table = {("git", "ls-tree", C_SHA, "--", "standards"): (0, "", "")}
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(table)):
            status = mr._classify_gitlink_pair(**self._base_kwargs(Path("/nonexistent")))
        self.assertEqual(status, "not_a_gitlink")

    def test_branch2_not_a_gitlink_mode_mismatch(self):
        table = {
            ("git", "ls-tree", C_SHA, "--", "standards"): (
                0, "040000 tree ttttttttttttttttttttttttttttttttttttttttt\tstandards\n", ""
            )
        }
        with mock.patch("collectors.multi_remote._run", side_effect=_make_run(table)):
            status = mr._classify_gitlink_pair(**self._base_kwargs(Path("/nonexistent")))
        self.assertEqual(status, "not_a_gitlink")

    def test_branch3_uninitialized_submodule(self):
        with tmp_project() as root:
            sub_dir = root / "standards"  # never created
            table = {
                ("git", "ls-tree", C_SHA, "--", "standards"): (
                    0, f"160000 commit {G_SHA}\tstandards\n", ""
                )
            }
            with mock.patch("collectors.multi_remote._run", side_effect=_make_run(table)):
                status = mr._classify_gitlink_pair(**self._base_kwargs(sub_dir))
        self.assertEqual(status, "uninitialized")

    def test_branch4_no_matching_remote(self):
        with tmp_project() as root:
            sub_dir = root / "standards"
            (sub_dir / ".git").mkdir(parents=True)
            table = {
                ("git", "ls-tree", C_SHA, "--", "standards"): (
                    0, f"160000 commit {G_SHA}\tstandards\n", ""
                ),
                ("git", "remote"): (0, "origin\n", ""),  # no "github" here
            }
            with mock.patch("collectors.multi_remote._run", side_effect=_make_run(table)):
                status = mr._classify_gitlink_pair(**self._base_kwargs(sub_dir))
        self.assertEqual(status, "no_matching_remote")

    def test_branch5_shallow_unverifiable(self):
        with tmp_project() as root:
            sub_dir = root / "standards"
            (sub_dir / ".git").mkdir(parents=True)
            table = {
                ("git", "ls-tree", C_SHA, "--", "standards"): (
                    0, f"160000 commit {G_SHA}\tstandards\n", ""
                ),
                ("git", "remote"): (0, "github\n", ""),
            }
            with mock.patch(
                "collectors.multi_remote._run", side_effect=_make_run(table)
            ), mock.patch("collectors.multi_remote._is_shallow", return_value=True):
                status = mr._classify_gitlink_pair(**self._base_kwargs(sub_dir))
        self.assertEqual(status, "shallow_unverifiable")

    def _contains_cmd(self, sub_dir):
        return (
            "git", "-C", str(sub_dir), "branch", "-r", "--contains", G_SHA, "--list", "github/*",
        )

    def test_branch6_ok(self):
        with tmp_project() as root:
            sub_dir = root / "standards"
            (sub_dir / ".git").mkdir(parents=True)
            table = {
                ("git", "ls-tree", C_SHA, "--", "standards"): (
                    0, f"160000 commit {G_SHA}\tstandards\n", ""
                ),
                ("git", "remote"): (0, "github\n", ""),
                self._contains_cmd(sub_dir): (0, "github/master\n", ""),
            }
            with mock.patch(
                "collectors.multi_remote._run", side_effect=_make_run(table)
            ), mock.patch("collectors.multi_remote._is_shallow", return_value=False):
                status = mr._classify_gitlink_pair(**self._base_kwargs(sub_dir))
        self.assertEqual(status, "ok")

    def test_branch6_orphaned_via_exempt_legs(self):
        with tmp_project() as root:
            sub_dir = root / "standards"
            (sub_dir / ".git").mkdir(parents=True)
            table = {
                ("git", "ls-tree", C_SHA, "--", "standards"): (
                    0, f"160000 commit {G_SHA}\tstandards\n", ""
                ),
                ("git", "remote"): (0, "github\n", ""),
                self._contains_cmd(sub_dir): (0, "", ""),  # empty ⇒ unreachable
            }
            kwargs = self._base_kwargs(
                sub_dir,
                main_leg=_exempt_leg(scan_generation=6),
                sub_leg=_exempt_leg(scan_generation=6),
            )
            with mock.patch(
                "collectors.multi_remote._run", side_effect=_make_run(table)
            ), mock.patch("collectors.multi_remote._is_shallow", return_value=False):
                status = mr._classify_gitlink_pair(**kwargs)
        self.assertEqual(status, "orphaned")

    def test_branch6_orphan_unverified_via_non_exempt_legs(self):
        with tmp_project() as root:
            sub_dir = root / "standards"
            (sub_dir / ".git").mkdir(parents=True)
            table = {
                ("git", "ls-tree", C_SHA, "--", "standards"): (
                    0, f"160000 commit {G_SHA}\tstandards\n", ""
                ),
                ("git", "remote"): (0, "github\n", ""),
                self._contains_cmd(sub_dir): (0, "", ""),
            }
            kwargs = self._base_kwargs(sub_dir, main_leg=None, sub_leg=None)
            with mock.patch(
                "collectors.multi_remote._run", side_effect=_make_run(table)
            ), mock.patch("collectors.multi_remote._is_shallow", return_value=False):
                status = mr._classify_gitlink_pair(**kwargs)
        self.assertEqual(status, "orphan_unverified")

    def test_branch6_rc129_orphaned_when_exempt(self):
        with tmp_project() as root:
            sub_dir = root / "standards"
            (sub_dir / ".git").mkdir(parents=True)
            table = {
                ("git", "ls-tree", C_SHA, "--", "standards"): (
                    0, f"160000 commit {G_SHA}\tstandards\n", ""
                ),
                ("git", "remote"): (0, "github\n", ""),
                self._contains_cmd(sub_dir): (129, "", f"fatal: bad object {G_SHA}"),
            }
            kwargs = self._base_kwargs(
                sub_dir,
                main_leg=_exempt_leg(scan_generation=6),
                sub_leg=_exempt_leg(scan_generation=6),
            )
            with mock.patch(
                "collectors.multi_remote._run", side_effect=_make_run(table)
            ), mock.patch("collectors.multi_remote._is_shallow", return_value=False):
                status = mr._classify_gitlink_pair(**kwargs)
        self.assertEqual(status, "orphaned")

    def test_branch7_soft_error(self):
        with tmp_project() as root:
            sub_dir = root / "standards"
            (sub_dir / ".git").mkdir(parents=True)
            table = {
                ("git", "ls-tree", C_SHA, "--", "standards"): (
                    0, f"160000 commit {G_SHA}\tstandards\n", ""
                ),
                ("git", "remote"): (0, "github\n", ""),
                self._contains_cmd(sub_dir): (128, "", "fatal: repository corrupted"),
            }
            with mock.patch(
                "collectors.multi_remote._run", side_effect=_make_run(table)
            ), mock.patch("collectors.multi_remote._is_shallow", return_value=False):
                status = mr._classify_gitlink_pair(**self._base_kwargs(sub_dir))
        self.assertEqual(status, "soft_error")


class TestGitlinkCache(unittest.TestCase):
    def test_pair_key_format(self):
        self.assertEqual(mr._gitlink_pair_key("github", "standards"), "github::standards")

    def test_read_missing_file_returns_empty(self):
        with tmp_project() as root:
            self.assertEqual(mr._read_gitlink_cache(root), {})

    def test_read_malformed_json_returns_empty(self):
        with tmp_project() as root:
            write_file(root / ".aria" / "cache" / "gitlink-integrity.json", "not json {")
            self.assertEqual(mr._read_gitlink_cache(root), {})

    def test_write_then_read_round_trip(self):
        with tmp_project() as root:
            mr._write_gitlink_cache_atomic(root, {"github::standards": {"consecutive_unverified": 3}})
            data = mr._read_gitlink_cache(root)
            self.assertEqual(data["pairs"]["github::standards"]["consecutive_unverified"], 3)

    def test_write_merges_with_existing_pairs_not_overwriting(self):
        with tmp_project() as root:
            mr._write_gitlink_cache_atomic(root, {"github::standards": {"consecutive_unverified": 1}})
            mr._write_gitlink_cache_atomic(
                root, {"github::aria-orchestrator": {"consecutive_unverified": 2}}
            )
            data = mr._read_gitlink_cache(root)
            self.assertEqual(data["pairs"]["github::standards"]["consecutive_unverified"], 1)
            self.assertEqual(
                data["pairs"]["github::aria-orchestrator"]["consecutive_unverified"], 2
            )

    def test_counter_reset_statuses_are_exactly_ok_and_orphaned(self):
        # Lock test per blueprint's explicit request: the "freeze the other six
        # statuses" reading is the blueprint's OWN inference, not spec-verbatim
        # text — pin it down so a future edit cannot silently widen/narrow it.
        self.assertEqual(mr._GITLINK_COUNTER_RESET_STATUSES, frozenset({"ok", "orphaned"}))

    def test_gitlink_cache_file_is_physically_separate_from_remote_refresh_cache(self):
        self.assertNotEqual(mr._GITLINK_CACHE_RELATIVE, mr._REMOTE_REFRESH_CACHE_RELATIVE)


class TestGitlinkUnreachableRealGit(unittest.TestCase):
    """Real-git integration test (not `_run`-mocked) for AC-17(e) tag-only pin
    — mock-only coverage cannot prove the implementation never additionally
    consults `git tag --contains`, since the mock table itself dictates the
    `contains` return value. This spies on the REAL `_run` (via `side_effect`
    wrapping the genuine function) to assert the exact command set invoked."""

    def test_tag_only_pin_still_reports_unreachable_and_never_calls_tag(self):
        with tmp_repo() as sub:
            # Second commit G — will be tag-only reachable.
            write_file(sub / "file.txt", "v2")
            run_git(sub, "add", "file.txt")
            run_git(sub, "commit", "-q", "-m", "second")
            g = run_git(sub, "rev-parse", "HEAD").stdout.strip()
            run_git(sub, "tag", "pin-t", g)

            first_commit = run_git(sub, "rev-list", "--max-parents=0", "HEAD").stdout.strip()
            # Simulate a remote-tracking branch that does NOT contain G — only
            # the first commit is "mirrored".
            run_git(sub, "update-ref", "refs/remotes/origin/master", first_commit)

            original_run = mr._run
            with mock.patch(
                "collectors.multi_remote._run", side_effect=original_run
            ) as spy:
                unreachable, is_soft_error = mr._gitlink_unreachable(sub, "origin", g, 5)

        self.assertTrue(unreachable)
        self.assertFalse(is_soft_error)
        for call in spy.call_args_list:
            cmd = call.args[0]
            self.assertNotIn("tag", cmd, f"unexpected git-tag call: {cmd!r}")


def _write_remote_refresh_cache(repo: Path, legs: dict, scan_generation: int = 1) -> None:
    write_file(
        repo / ".aria" / "cache" / "remote-refresh.json",
        json.dumps({"scan_generation": scan_generation, "legs": legs}),
    )


class TestCollectMultiRemoteGitlinkWiring(unittest.TestCase):
    """Full `collect_multi_remote` integration — AC-16 (2026-07-12 accident
    replay) + a subset of AC-17. `overall_parity` is asserted end-to-end (not
    just the gitlink status), proving F4′ clause 3 actually consumes
    `gitlink_integrity` through the real collector wiring, not just the pure
    `_overall_parity` unit tests."""

    def _patch_common(self, run_table, submodule_paths, branch_by_dir):
        def branch_side_effect(repo_dir, timeout=5):
            return branch_by_dir.get(str(repo_dir))

        return (
            mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)),
            mock.patch("collectors.multi_remote._is_shallow", return_value=False),
            mock.patch(
                "collectors.multi_remote._current_branch", side_effect=branch_side_effect
            ),
            mock.patch(
                "collectors.multi_remote._enumerate_submodule_paths",
                return_value=submodule_paths,
            ),
        )

    def test_ac16_accident_replay_orphaned_blocks_overall_parity(self):
        """2026-07-12 accident, replayed: main repo's github/master publishes a
        gitlink to `standards@G`, which is unreachable on standards' github
        remote, with BOTH legs exemption-eligible (fresh fetch, matching
        generation) ⇒ status=orphaned ⇒ overall_parity MUST be False — even
        though the main repo's own github leg independently supplies fresh
        positive `equal` evidence (clause 2 alone would say True; clause 3
        must override it)."""
        with tmp_repo() as repo:
            sub_dir = repo / "standards"
            sub_dir.mkdir()
            (sub_dir / ".git").write_text("gitdir: ../.git/modules/standards\n")
            _write_remote_refresh_cache(
                repo,
                {
                    ".::github": {
                        "fetched_at": NOW.isoformat(timespec="seconds"),
                        "fetch_ok": "true",
                        "generation_fetched": 6,
                        "consecutive_unverified": 0,
                    },
                    "standards::github": {
                        "fetched_at": NOW.isoformat(timespec="seconds"),
                        "fetch_ok": "true",
                        "generation_fetched": 6,
                        "consecutive_unverified": 0,
                    },
                },
                scan_generation=6,
            )
            run_table = {
                ("git", "rev-parse", "--is-inside-work-tree"): (0, "true\n", ""),
                ("git", "rev-parse", "--short=7", "HEAD"): (0, "dfb3118\n", ""),
                ("git", "remote"): (0, "github\n", ""),
                ("git", "rev-parse", "--short=7", "refs/remotes/github/master"): (
                    0, "dfb3118\n", ""
                ),
                (
                    "git", "rev-list", "--left-right", "--count",
                    "HEAD...refs/remotes/github/master",
                ): (0, "0\t0\n", ""),
                # gitlink loop:
                ("git", "rev-parse", "refs/remotes/github/master"): (0, f"{C_SHA}\n", ""),
                ("git", "ls-tree", C_SHA, "--", "standards"): (
                    0, f"160000 commit {G_SHA}\tstandards\n", ""
                ),
                (
                    "git", "-C", str(sub_dir), "branch", "-r", "--contains", G_SHA,
                    "--list", "github/*",
                ): (0, "", ""),  # empty ⇒ unreachable (mirror lag)
            }
            branch_by_dir = {str(repo): "master", str(sub_dir): None}
            with mock.patch(
                "collectors.multi_remote.scan_now", return_value=NOW
            ), self._patch_common(run_table, ["standards"], branch_by_dir)[0], self._patch_common(
                run_table, ["standards"], branch_by_dir
            )[1], self._patch_common(
                run_table, ["standards"], branch_by_dir
            )[2], self._patch_common(
                run_table, ["standards"], branch_by_dir
            )[3]:
                result = mr.collect_multi_remote(repo)

        self.assertEqual(
            result.data["gitlink_integrity"],
            [
                {
                    "remote": "github",
                    "submodule": "standards",
                    "status": "orphaned",
                    "consecutive_unverified": 0,
                }
            ],
        )
        self.assertFalse(result.data["overall_parity"])

    def test_ac17a_healthy_all_reachable_does_not_block(self):
        with tmp_repo() as repo:
            sub_dir = repo / "standards"
            sub_dir.mkdir()
            (sub_dir / ".git").write_text("gitdir: ../.git/modules/standards\n")
            _write_remote_refresh_cache(
                repo,
                {
                    ".::github": {
                        "fetched_at": NOW.isoformat(timespec="seconds"),
                        "fetch_ok": "true",
                        "generation_fetched": 6,
                        "consecutive_unverified": 0,
                    },
                },
                scan_generation=6,
            )
            run_table = {
                ("git", "rev-parse", "--is-inside-work-tree"): (0, "true\n", ""),
                ("git", "rev-parse", "--short=7", "HEAD"): (0, "dfb3118\n", ""),
                ("git", "remote"): (0, "github\n", ""),
                ("git", "rev-parse", "--short=7", "refs/remotes/github/master"): (
                    0, "dfb3118\n", ""
                ),
                (
                    "git", "rev-list", "--left-right", "--count",
                    "HEAD...refs/remotes/github/master",
                ): (0, "0\t0\n", ""),
                ("git", "rev-parse", "refs/remotes/github/master"): (0, f"{C_SHA}\n", ""),
                ("git", "ls-tree", C_SHA, "--", "standards"): (
                    0, f"160000 commit {G_SHA}\tstandards\n", ""
                ),
                (
                    "git", "-C", str(sub_dir), "branch", "-r", "--contains", G_SHA,
                    "--list", "github/*",
                ): (0, "github/master\n", ""),  # reachable
            }
            branch_by_dir = {str(repo): "master", str(sub_dir): None}
            patches = self._patch_common(run_table, ["standards"], branch_by_dir)
            with mock.patch(
                "collectors.multi_remote.scan_now", return_value=NOW
            ), patches[0], patches[1], patches[2], patches[3]:
                result = mr.collect_multi_remote(repo)

        self.assertEqual(result.data["gitlink_integrity"][0]["status"], "ok")
        self.assertTrue(result.data["overall_parity"])

    def test_ac17b_local_head_ahead_never_enters_judgment_zero_false_positive(self):
        """F10″ only looks at the PUBLISHED C (`refs/remotes/R/<branch>`), never
        local HEAD — a locally-advanced, unpushed gitlink must never surface in
        `gitlink_integrity` at all for this pair's published-C world."""
        with tmp_repo() as repo:
            sub_dir = repo / "standards"
            sub_dir.mkdir()
            (sub_dir / ".git").write_text("gitdir: ../.git/modules/standards\n")
            _write_remote_refresh_cache(
                repo,
                {
                    ".::github": {
                        "fetched_at": NOW.isoformat(timespec="seconds"),
                        "fetch_ok": "true",
                        "generation_fetched": 6,
                        "consecutive_unverified": 0,
                    },
                },
                scan_generation=6,
            )
            # Published C references G_OLD, which IS reachable — the fact that
            # a newer (unpublished) gitlink might exist in the local tree never
            # enters this pair's judgment because ls-tree reads the PUBLISHED C.
            run_table = {
                ("git", "rev-parse", "--is-inside-work-tree"): (0, "true\n", ""),
                ("git", "rev-parse", "--short=7", "HEAD"): (0, "dfb3118\n", ""),
                ("git", "remote"): (0, "github\n", ""),
                ("git", "rev-parse", "--short=7", "refs/remotes/github/master"): (
                    0, "dfb3118\n", ""
                ),
                (
                    "git", "rev-list", "--left-right", "--count",
                    "HEAD...refs/remotes/github/master",
                ): (0, "0\t0\n", ""),
                ("git", "rev-parse", "refs/remotes/github/master"): (0, f"{C_SHA}\n", ""),
                ("git", "ls-tree", C_SHA, "--", "standards"): (
                    0, "160000 commit gold_old_sha_gold_old_sha_gold_old_sha1\tstandards\n", ""
                ),
                (
                    "git", "-C", str(sub_dir), "branch", "-r", "--contains",
                    "gold_old_sha_gold_old_sha_gold_old_sha1", "--list", "github/*",
                ): (0, "github/master\n", ""),
            }
            branch_by_dir = {str(repo): "master", str(sub_dir): None}
            patches = self._patch_common(run_table, ["standards"], branch_by_dir)
            with mock.patch(
                "collectors.multi_remote.scan_now", return_value=NOW
            ), patches[0], patches[1], patches[2], patches[3]:
                result = mr.collect_multi_remote(repo)

        self.assertEqual(result.data["gitlink_integrity"][0]["status"], "ok")
        self.assertTrue(result.data["overall_parity"])

    def test_ac17c_nonconventional_branch_name_trunk_orphaned_and_ok_pair(self):
        """(c1)/(c2) paired — same non-conventional branch name (`trunk`), only
        the `contains` outcome differs, proving no hidden branch-name
        allow-list short-circuit."""
        for contains_output, expected_status, expected_overall in (
            ("", "orphaned", False),
            ("github/trunk\n", "ok", True),
        ):
            with self.subTest(expected_status=expected_status):
                with tmp_repo(branch="trunk") as repo:
                    sub_dir = repo / "standards"
                    sub_dir.mkdir()
                    (sub_dir / ".git").write_text("gitdir: ../.git/modules/standards\n")
                    _write_remote_refresh_cache(
                        repo,
                        {
                            ".::github": {
                                "fetched_at": NOW.isoformat(timespec="seconds"),
                                "fetch_ok": "true",
                                "generation_fetched": 6,
                                "consecutive_unverified": 0,
                            },
                            "standards::github": {
                                "fetched_at": NOW.isoformat(timespec="seconds"),
                                "fetch_ok": "true",
                                "generation_fetched": 6,
                                "consecutive_unverified": 0,
                            },
                        },
                        scan_generation=6,
                    )
                    run_table = {
                        ("git", "rev-parse", "--is-inside-work-tree"): (0, "true\n", ""),
                        ("git", "rev-parse", "--short=7", "HEAD"): (0, "dfb3118\n", ""),
                        ("git", "remote"): (0, "github\n", ""),
                        (
                            "git", "rev-parse", "--short=7", "refs/remotes/github/trunk",
                        ): (0, "dfb3118\n", ""),
                        (
                            "git", "rev-list", "--left-right", "--count",
                            "HEAD...refs/remotes/github/trunk",
                        ): (0, "0\t0\n", ""),
                        ("git", "rev-parse", "refs/remotes/github/trunk"): (
                            0, f"{C_SHA}\n", ""
                        ),
                        ("git", "ls-tree", C_SHA, "--", "standards"): (
                            0, f"160000 commit {G_SHA}\tstandards\n", ""
                        ),
                        (
                            "git", "-C", str(sub_dir), "branch", "-r", "--contains", G_SHA,
                            "--list", "github/*",
                        ): (0, contains_output, ""),
                    }
                    branch_by_dir = {str(repo): "trunk", str(sub_dir): None}
                    patches = self._patch_common(run_table, ["standards"], branch_by_dir)
                    with mock.patch(
                        "collectors.multi_remote.scan_now", return_value=NOW
                    ), patches[0], patches[1], patches[2], patches[3]:
                        result = mr.collect_multi_remote(repo)

                self.assertEqual(
                    result.data["gitlink_integrity"][0]["status"], expected_status
                )
                self.assertEqual(result.data["overall_parity"], expected_overall)

    def test_ac17f_cross_leg_generation_skew_is_orphan_unverified_not_orphaned(self):
        with tmp_repo() as repo:
            sub_dir = repo / "standards"
            sub_dir.mkdir()
            (sub_dir / ".git").write_text("gitdir: ../.git/modules/standards\n")
            _write_remote_refresh_cache(
                repo,
                {
                    ".::github": {
                        "fetched_at": NOW.isoformat(timespec="seconds"),
                        "fetch_ok": "true",
                        "generation_fetched": 6,
                        "consecutive_unverified": 0,
                    },
                    # sub leg is ONE generation behind — exempt (gen_age=1 ≤
                    # k_eff) but gen_ok fails (sub_gen < main_gen).
                    "standards::github": {
                        "fetched_at": NOW.isoformat(timespec="seconds"),
                        "fetch_ok": "true",
                        "generation_fetched": 5,
                        "consecutive_unverified": 0,
                    },
                },
                scan_generation=6,
            )
            run_table = {
                ("git", "rev-parse", "--is-inside-work-tree"): (0, "true\n", ""),
                ("git", "rev-parse", "--short=7", "HEAD"): (0, "dfb3118\n", ""),
                ("git", "remote"): (0, "github\n", ""),
                ("git", "rev-parse", "--short=7", "refs/remotes/github/master"): (
                    0, "dfb3118\n", ""
                ),
                (
                    "git", "rev-list", "--left-right", "--count",
                    "HEAD...refs/remotes/github/master",
                ): (0, "0\t0\n", ""),
                ("git", "rev-parse", "refs/remotes/github/master"): (0, f"{C_SHA}\n", ""),
                ("git", "ls-tree", C_SHA, "--", "standards"): (
                    0, f"160000 commit {G_SHA}\tstandards\n", ""
                ),
                (
                    "git", "-C", str(sub_dir), "branch", "-r", "--contains", G_SHA,
                    "--list", "github/*",
                ): (0, "", ""),
            }
            branch_by_dir = {str(repo): "master", str(sub_dir): None}
            patches = self._patch_common(run_table, ["standards"], branch_by_dir)
            with mock.patch(
                "collectors.multi_remote.scan_now", return_value=NOW
            ), patches[0], patches[1], patches[2], patches[3]:
                result = mr.collect_multi_remote(repo)

        self.assertEqual(result.data["gitlink_integrity"][0]["status"], "orphan_unverified")
        # k_eff default (k_min=3) with consecutive_unverified starting at 0→1
        # this scan does NOT yet reach the D18 threshold, so overall_parity
        # is unaffected by the gitlink clause on this single scan.
        self.assertTrue(result.data["overall_parity"])
        self.assertEqual(result.data["gitlink_integrity"][0]["consecutive_unverified"], 1)


class TestGitlinkCounterIsolation(unittest.TestCase):
    """Proves the gitlink-layer (R,S) D18 counter never reads or writes the
    parity-layer per-(repo,remote) leg counter — two scans of
    `collect_multi_remote` with a fixed, never-touched remote_refresh leg
    counter must show ONLY the gitlink cache's counter advancing."""

    def test_two_scans_advance_gitlink_counter_independently_of_leg_counter(self):
        with tmp_repo() as repo:
            sub_dir = repo / "standards"
            sub_dir.mkdir()
            (sub_dir / ".git").write_text("gitdir: ../.git/modules/standards\n")
            _write_remote_refresh_cache(
                repo,
                {
                    ".::github": {
                        "fetched_at": NOW.isoformat(timespec="seconds"),
                        "fetch_ok": "true",
                        "generation_fetched": 6,
                        "consecutive_unverified": 0,
                    },
                    # deliberately NEVER exempt (no fetched_at) — main leg
                    # for the SUBMODULE side stays unfetched throughout, so
                    # gitlink status stays orphan_unverified every scan.
                },
                scan_generation=6,
            )
            run_table = {
                ("git", "rev-parse", "--is-inside-work-tree"): (0, "true\n", ""),
                ("git", "rev-parse", "--short=7", "HEAD"): (0, "dfb3118\n", ""),
                ("git", "remote"): (0, "github\n", ""),
                ("git", "rev-parse", "--short=7", "refs/remotes/github/master"): (
                    0, "dfb3118\n", ""
                ),
                (
                    "git", "rev-list", "--left-right", "--count",
                    "HEAD...refs/remotes/github/master",
                ): (0, "0\t0\n", ""),
                ("git", "rev-parse", "refs/remotes/github/master"): (0, f"{C_SHA}\n", ""),
                ("git", "ls-tree", C_SHA, "--", "standards"): (
                    0, f"160000 commit {G_SHA}\tstandards\n", ""
                ),
                (
                    "git", "-C", str(sub_dir), "branch", "-r", "--contains", G_SHA,
                    "--list", "github/*",
                ): (0, "", ""),
            }
            branch_by_dir = {str(repo): "master", str(sub_dir): None}
            patches = self._make_patches(run_table, ["standards"], branch_by_dir)
            with mock.patch(
                "collectors.multi_remote.scan_now", return_value=NOW
            ), patches[0], patches[1], patches[2], patches[3]:
                r1 = mr.collect_multi_remote(repo)
                r2 = mr.collect_multi_remote(repo)

            leg_cache_after = json.loads(
                (repo / ".aria" / "cache" / "remote-refresh.json").read_text()
            )
            gitlink_cache_after = json.loads(
                (repo / ".aria" / "cache" / "gitlink-integrity.json").read_text()
            )

        self.assertEqual(r1.data["gitlink_integrity"][0]["consecutive_unverified"], 1)
        self.assertEqual(r2.data["gitlink_integrity"][0]["consecutive_unverified"], 2)
        # the never-touched parity-layer leg counter (this test never runs the
        # real remote_refresh collector) stays exactly as pre-seeded — proving
        # multi_remote.py's gitlink loop never writes into it.
        self.assertEqual(
            leg_cache_after["legs"][".::github"]["consecutive_unverified"], 0
        )
        self.assertEqual(
            gitlink_cache_after["pairs"]["github::standards"]["consecutive_unverified"], 2
        )

    @staticmethod
    def _make_patches(run_table, submodule_paths, branch_by_dir):
        def branch_side_effect(repo_dir, timeout=5):
            return branch_by_dir.get(str(repo_dir))

        return (
            mock.patch("collectors.multi_remote._run", side_effect=_make_run(run_table)),
            mock.patch("collectors.multi_remote._is_shallow", return_value=False),
            mock.patch(
                "collectors.multi_remote._current_branch", side_effect=branch_side_effect
            ),
            mock.patch(
                "collectors.multi_remote._enumerate_submodule_paths",
                return_value=submodule_paths,
            ),
        )


if __name__ == "__main__":
    unittest.main()
