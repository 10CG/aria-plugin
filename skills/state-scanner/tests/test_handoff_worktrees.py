"""Phase 1.15b cross-worktree handoff discovery collector tests (#139).

OpenSpec cross-worktree-handoff-discovery — Rule #6 substitute (deterministic
collector): structural fixture + unit tests (this file, cases ①-⑯/⑱/⑲) +
resolver tests (test_max_worktrees_resolver.py, ⑰) + dogfood (Aria real tree
no-op + sandbox e2e).

Fixtures build a temp git repo plus real `git worktree add` worktrees, all
inside ONE isolated tempdir (NOT repo.parent) per the #135 $TMPDIR-leak lesson.
Handoff files are written to each worktree's working tree (not committed —
collect_handoff scans the filesystem, not git).
"""

from __future__ import annotations

import os
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from _helpers import init_git_repo, run_git, make_config
import collectors.handoff_worktrees as hw
from collectors.handoff import collect_handoff
from collectors.handoff_worktrees import collect_handoff_worktrees

import tempfile


@contextmanager
def multi_worktree_repo():
    """Yield (main_path, add_worktree, root) — temp repo + worktree factory.

    add_worktree(name, branch) creates a sibling worktree inside the SAME
    isolated tempdir (#135: never repo.parent). add_worktree(name, None) makes
    a detached worktree.
    """
    with tempfile.TemporaryDirectory(prefix="wt-coll-") as tmp:
        root = Path(tmp)
        main = root / "main"
        init_git_repo(main, branch="master")

        def add_worktree(name: str, branch: str | None):
            wt = root / name
            if branch is None:
                run_git(main, "worktree", "add", "-q", "--detach", str(wt))
            else:
                run_git(main, "worktree", "add", "-q", "-b", branch, str(wt))
            return wt

        yield main, add_worktree, root


def _write_handoff(
    wt: Path,
    filename: str,
    *,
    status: str | None = None,
    updated_at: str | None = None,
    track_id: str = "track-x",
    frontmatter: bool = True,
    body: str = "# handoff\n",
    mtime_offset: float | None = None,
) -> Path:
    """Write a handoff doc into wt/docs/handoff/. frontmatter=False → legacy doc."""
    handoff = wt / "docs" / "handoff"
    handoff.mkdir(parents=True, exist_ok=True)
    if frontmatter:
        content = (
            f"---\ntrack-id: {track_id}\nowner-container: o/c\nphase: D\n"
            f"status: {status}\nupdated-at: {updated_at}\n---\n{body}"
        )
    else:
        content = body
    path = handoff / filename
    path.write_text(content, encoding="utf-8")
    if mtime_offset is not None:
        t = time.time() + mtime_offset
        os.utime(path, (t, t))
    return path


def _write_pointer(wt: Path, target: str) -> None:
    handoff = wt / "docs" / "handoff"
    handoff.mkdir(parents=True, exist_ok=True)
    (handoff / "latest.md").write_text(
        f"# Latest\n\n**Latest**: [{target}](./{target}) — desc\n", encoding="utf-8"
    )


def _collect(main: Path):
    """Run collector via the real scan.py path (consume Phase 1.15)."""
    ch = collect_handoff(main)
    return collect_handoff_worktrees(main, ch.data)


def _errs(r):
    return {e["error"] for e in r.errors}


class TestNoOp(unittest.TestCase):
    def test_single_worktree_no_op(self):  # ①
        with multi_worktree_repo() as (main, _add, _root):
            _write_handoff(
                main, "2026-06-10-m.md", status="active",
                updated_at="2026-06-10T00:00:00Z",
            )
            r = _collect(main)
            self.assertTrue(r.data["enabled"])
            self.assertTrue(r.data["enumerated"])
            self.assertEqual(r.data["worktree_count"], 1)
            self.assertEqual(r.data["others"], [])
            self.assertIsNone(r.data["global_latest_elsewhere"])


class TestCrossTreeDiscovery(unittest.TestCase):
    def test_other_tree_newer_surfaces(self):  # ②
        with multi_worktree_repo() as (main, add, _root):
            _write_handoff(main, "m.md", status="done",
                           updated_at="2026-06-10T08:00:00Z")
            wt2 = add("wt2", "feat/cut2")
            _write_handoff(wt2, "f.md", status="active",
                           updated_at="2026-06-11T10:00:00Z", track_id="cut2")
            r = _collect(main)
            self.assertEqual(r.data["worktree_count"], 2)
            self.assertEqual(len(r.data["others"]), 1)
            g = r.data["global_latest_elsewhere"]
            self.assertIsNotNone(g)
            self.assertEqual(g["branch"], "feat/cut2")
            self.assertEqual(g["status"], "active")

    def test_current_tree_newest_no_advisory(self):  # ③
        with multi_worktree_repo() as (main, add, _root):
            _write_handoff(main, "m.md", status="active",
                           updated_at="2026-06-12T10:00:00Z")
            wt2 = add("wt2", "feat/x")
            _write_handoff(wt2, "f.md", status="active",
                           updated_at="2026-06-10T10:00:00Z")
            r = _collect(main)
            self.assertIsNone(r.data["global_latest_elsewhere"])
            self.assertEqual(len(r.data["others"]), 1)  # still listed

    def test_other_tree_done_is_global_but_status_done(self):  # ⑦
        with multi_worktree_repo() as (main, add, _root):
            _write_handoff(main, "m.md", status="active",
                           updated_at="2026-06-10T08:00:00Z")
            wt2 = add("wt2", "feat/done")
            _write_handoff(wt2, "f.md", status="done",
                           updated_at="2026-06-12T10:00:00Z")
            r = _collect(main)
            g = r.data["global_latest_elsewhere"]
            self.assertIsNotNone(g)  # field stays arbitration-honest
            self.assertEqual(g["status"], "done")  # Phase 2 gates on this

    def test_current_tree_empty_other_active(self):  # ⑬
        with multi_worktree_repo() as (main, add, _root):
            # main has NO handoff
            wt2 = add("wt2", "feat/active")
            _write_handoff(wt2, "f.md", status="active",
                           updated_at="2026-06-11T10:00:00Z")
            r = _collect(main)
            g = r.data["global_latest_elsewhere"]
            self.assertIsNotNone(g)
            self.assertEqual(g["branch"], "feat/active")
            self.assertEqual(g["status"], "active")


class TestLegacyAndFrontmatter(unittest.TestCase):
    def test_other_tree_legacy_doc_mtime_degrade(self):  # ④
        with multi_worktree_repo() as (main, add, _root):
            _write_handoff(main, "m.md", status="active",
                           updated_at="2026-06-10T08:00:00Z")
            wt2 = add("wt2", "feat/legacy")
            _write_handoff(wt2, "legacy.md", frontmatter=False,
                           body="# no frontmatter\n", mtime_offset=0)
            r = _collect(main)
            o = next(o for o in r.data["others"] if o["branch"] == "feat/legacy")
            self.assertEqual(o["status"], "legacy")
            self.assertEqual(o["cmp_key_source"], "mtime")
            self.assertEqual(o["track_id"], "legacy.md")  # filename-derived
            # negative assertion: other-tree legacy must NOT fire #137 (m-7/N-6)
            self.assertNotIn("handoff_frontmatter_missing", _errs(r))

    def test_other_tree_stale_pointer_prefixed_soft_error(self):  # ⑲
        with multi_worktree_repo() as (main, add, _root):
            _write_handoff(main, "m.md", status="active",
                           updated_at="2026-06-10T08:00:00Z")
            wt2 = add("wt2", "feat/stale")
            _write_handoff(wt2, "real.md", status="active",
                           updated_at="2026-06-11T10:00:00Z")
            _write_pointer(wt2, "2026-99-99-deleted.md")  # target absent
            r = _collect(main)
            self.assertIn("handoff_pointer_target_missing", _errs(r))
            # message carries the worktree path prefix (R2 N-3)
            msg = next(e["detail"] for e in r.errors
                       if e["error"] == "handoff_pointer_target_missing")
            self.assertIn(str(wt2), msg)


class TestPointerResolution(unittest.TestCase):
    def test_other_tree_pointer_wins_over_mtime(self):  # ⑤
        with multi_worktree_repo() as (main, add, _root):
            _write_handoff(main, "m.md", status="done",
                           updated_at="2026-06-10T08:00:00Z")
            wt2 = add("wt2", "feat/ptr")
            # real-latest (pointer target) but OLDER mtime; predecessor newer mtime
            _write_handoff(wt2, "real.md", status="active",
                           updated_at="2026-06-11T10:00:00Z", mtime_offset=-7200)
            _write_handoff(wt2, "pred.md", status="active",
                           updated_at="2026-06-09T10:00:00Z", mtime_offset=0)
            _write_pointer(wt2, "real.md")
            r = _collect(main)
            o = next(o for o in r.data["others"] if o["branch"] == "feat/ptr")
            self.assertEqual(o["doc"], "docs/handoff/real.md")  # pointer wins


class TestArbitrationEdges(unittest.TestCase):
    def test_three_worktrees_deterministic_winner_and_sort(self):  # ⑭
        with multi_worktree_repo() as (main, add, _root):
            _write_handoff(main, "m.md", status="active",
                           updated_at="2026-06-09T00:00:00Z")
            wt_b = add("b-tree", "feat/b")
            wt_a = add("a-tree", "feat/a")
            _write_handoff(wt_b, "b.md", status="active",
                           updated_at="2026-06-11T10:00:00Z")
            _write_handoff(wt_a, "a.md", status="active",
                           updated_at="2026-06-10T10:00:00Z")
            r = _collect(main)
            # winner = wt_b (newest updated-at)
            g = r.data["global_latest_elsewhere"]
            self.assertEqual(g["branch"], "feat/b")
            # others sorted by path lexicographically (a-tree before b-tree)
            paths = [o["path"] for o in r.data["others"]]
            self.assertEqual(paths, sorted(paths))

    def test_mixed_offset_formats_ordered_correctly(self):  # ⑮a
        with multi_worktree_repo() as (main, add, _root):
            # main 09:00Z; A 10:00Z; B 19:00+08:00 (=11:00Z, newest); C 09:30+00:00
            _write_handoff(main, "m.md", status="active",
                           updated_at="2026-06-11T09:00:00Z")
            wt_a = add("wt-a", "feat/a")
            wt_b = add("wt-b", "feat/b")
            wt_c = add("wt-c", "feat/c")
            _write_handoff(wt_a, "a.md", status="active",
                           updated_at="2026-06-11T10:00:00Z")
            _write_handoff(wt_b, "b.md", status="active",
                           updated_at="2026-06-11T19:00:00+08:00")  # = 11:00Z
            _write_handoff(wt_c, "c.md", status="active",
                           updated_at="2026-06-11T09:30:00+00:00")
            r = _collect(main)
            g = r.data["global_latest_elsewhere"]
            self.assertEqual(g["branch"], "feat/b")  # 11:00Z is newest
            # the +08:00 offset tree was arbitrated via frontmatter (not mtime)
            # and carries a finite age_hours (defense vs silent age-basis regression)
            b_entry = next(o for o in r.data["others"] if o["branch"] == "feat/b")
            self.assertEqual(b_entry["cmp_key_source"], "frontmatter")
            self.assertIsInstance(g["age_hours"], float)

    def test_other_vs_other_epoch_tie_path_lex(self):  # ⑮b
        with multi_worktree_repo() as (main, add, _root):
            _write_handoff(main, "m.md", status="active",
                           updated_at="2026-06-09T00:00:00Z")  # older
            wt_z = add("z-tree", "feat/z")
            wt_a = add("a-tree", "feat/a")
            same = "2026-06-11T10:00:00Z"
            _write_handoff(wt_z, "z.md", status="active", updated_at=same)
            _write_handoff(wt_a, "a.md", status="active", updated_at=same)
            r = _collect(main)
            g = r.data["global_latest_elsewhere"]
            # tie → lexicographically smallest path wins (a-tree)
            self.assertTrue(g["path"].endswith("a-tree"), g["path"])

    def test_current_vs_other_tie_current_wins(self):  # ⑮c
        with multi_worktree_repo() as (main, add, _root):
            same = "2026-06-11T10:00:00Z"
            _write_handoff(main, "m.md", status="active", updated_at=same)
            wt2 = add("wt2", "feat/tie")
            _write_handoff(wt2, "f.md", status="active", updated_at=same)
            r = _collect(main)
            # current-tree-wins on tie → no advisory
            self.assertIsNone(r.data["global_latest_elsewhere"])

    def test_malformed_updated_at_degrades_to_mtime(self):  # ⑮d
        with multi_worktree_repo() as (main, add, _root):
            _write_handoff(main, "m.md", status="active",
                           updated_at="2026-06-09T00:00:00Z")
            wt2 = add("wt2", "feat/bad")
            _write_handoff(wt2, "f.md", status="active",
                           updated_at="not-a-real-date", mtime_offset=0)
            r = _collect(main)
            o = next(o for o in r.data["others"] if o["branch"] == "feat/bad")
            self.assertEqual(o["cmp_key_source"], "mtime")  # degraded
            self.assertEqual(o["status"], "active")  # status still from frontmatter

    def test_current_mixed_domain_guard(self):  # ⑱
        with multi_worktree_repo() as (main, add, _root):
            # current updated-at LATER than other, but current doc mtime EARLIER.
            # Correct impl uses updated-at for current → current newest → null.
            # Wrong impl (mtime for current) would point elsewhere.
            _write_handoff(main, "m.md", status="active",
                           updated_at="2026-06-20T10:00:00Z", mtime_offset=-100000)
            wt2 = add("wt2", "feat/x")
            _write_handoff(wt2, "f.md", status="active",
                           updated_at="2026-06-11T10:00:00Z", mtime_offset=0)
            r = _collect(main)
            self.assertIsNone(r.data["global_latest_elsewhere"])


class TestEnumerationAndConfig(unittest.TestCase):
    def test_enumeration_failure(self):  # ⑥
        with multi_worktree_repo() as (main, _add, _root):
            with mock.patch.object(hw, "_run", return_value=(1, "", "boom")):
                r = collect_handoff_worktrees(main, {"exists": False})
            self.assertTrue(r.data["enabled"])
            self.assertFalse(r.data["enumerated"])
            self.assertIn("worktree_enumeration_failed", _errs(r))

    def test_disabled_via_config(self):  # ⑪
        with multi_worktree_repo() as (main, _add, _root):
            make_config(main, {"state_scanner": {"worktree_scan": {"enabled": False}}})
            r = collect_handoff_worktrees(main, {"exists": False})
            self.assertFalse(r.data["enabled"])
            self.assertFalse(r.data["enumerated"])
            # machine-distinguishable from ⑥: NO enumeration soft error (R2 N-1)
            self.assertNotIn("worktree_enumeration_failed", _errs(r))


class TestCapAndUnreachable(unittest.TestCase):
    def test_cap_truncates_with_soft_warn(self):  # ⑧
        os.environ["ARIA_WORKTREE_MAX_SCANNED"] = "1"
        try:
            with multi_worktree_repo() as (main, add, _root):
                _write_handoff(main, "m.md", status="active",
                               updated_at="2026-06-09T00:00:00Z")
                for n in ("wt2", "wt3"):
                    wt = add(n, f"feat/{n}")
                    _write_handoff(wt, "f.md", status="active",
                                   updated_at="2026-06-11T10:00:00Z")
                r = _collect(main)
                self.assertIn("worktree_scan_cap", _errs(r))
                # exactly 1 (cap=1) — NOT <=1, which would pass a baseline-eating
                # bug (len=0) where cap drops the current tree too (R2 N-1: cap
                # must never drop the arbitration baseline).
                self.assertEqual(len(r.data["others"]), 1)
                # cap does not shrink the count: worktree_count is the pre-cap
                # reachable total (3 = main + 2 others).
                self.assertEqual(r.data["worktree_count"], 3)
        finally:
            os.environ.pop("ARIA_WORKTREE_MAX_SCANNED", None)

    def test_worktree_dir_removed_unreachable(self):  # ⑨
        with multi_worktree_repo() as (main, add, _root):
            _write_handoff(main, "m.md", status="active",
                           updated_at="2026-06-10T00:00:00Z")
            wt2 = add("wt2", "feat/gone")
            wt_det = add("wt-det", None)  # detached
            _write_handoff(wt_det, "d.md", status="active",
                           updated_at="2026-06-09T00:00:00Z")
            # remove wt2's directory (git still lists it)
            import shutil
            shutil.rmtree(wt2)
            r = _collect(main)
            self.assertIn("worktree_unreachable", _errs(r))
            msg = next(e["detail"] for e in r.errors
                       if e["error"] == "worktree_unreachable")
            self.assertIn("wt2", msg)
            # detached tree present in others with branch "(detached)"
            det = [o for o in r.data["others"] if o["branch"] == "(detached)"]
            self.assertEqual(len(det), 1)

    def test_per_tree_scan_failure_prefixed(self):  # ⑩
        with multi_worktree_repo() as (main, add, _root):
            _write_handoff(main, "m.md", status="active",
                           updated_at="2026-06-10T00:00:00Z")
            wt2 = add("wt2", "feat/perm")
            handoff = wt2 / "docs" / "handoff"
            _write_handoff(wt2, "f.md", status="active",
                           updated_at="2026-06-11T10:00:00Z")
            os.chmod(handoff, 0o000)
            try:
                r = _collect(main)
                self.assertIn("handoff_canonical_scan_failed", _errs(r))
                msg = next(e["detail"] for e in r.errors
                           if e["error"] == "handoff_canonical_scan_failed")
                self.assertIn(str(wt2), msg)
            finally:
                os.chmod(handoff, 0o755)


class TestSymlink(unittest.TestCase):
    def test_symlinked_cwd_excludes_current_tree(self):  # ⑯
        with multi_worktree_repo() as (main, _add, root):
            _write_handoff(main, "m.md", status="active",
                           updated_at="2026-06-10T00:00:00Z")
            link = root / "main-link"
            link.symlink_to(main)
            ch = collect_handoff(link)
            r = collect_handoff_worktrees(link, ch.data)
            # current tree (reached via symlink) must be excluded → no self-ref
            self.assertEqual(r.data["others"], [])
            self.assertIsNone(r.data["global_latest_elsewhere"])


class TestStatusHonestyAndContract(unittest.TestCase):
    """⑫ + output-key contract: global_latest_elsewhere carries status verbatim
    (arbitration-honest; Phase 2 gates on status=='active'), internal keys stripped."""

    def test_abandoned_global_latest_status_verbatim(self):  # ⑫a
        with multi_worktree_repo() as (main, add, _root):
            _write_handoff(main, "m.md", status="active",
                           updated_at="2026-06-09T00:00:00Z")
            wt2 = add("wt2", "feat/abandoned")
            _write_handoff(wt2, "f.md", status="abandoned",
                           updated_at="2026-06-12T10:00:00Z")
            r = _collect(main)
            g = r.data["global_latest_elsewhere"]
            self.assertIsNotNone(g)  # field stays arbitration-honest
            self.assertEqual(g["status"], "abandoned")  # Phase 2 gate sees non-active

    def test_legacy_global_latest_status_verbatim(self):  # ⑫b
        with multi_worktree_repo() as (main, add, _root):
            _write_handoff(main, "m.md", status="active",
                           updated_at="2026-06-09T00:00:00Z")
            wt2 = add("wt2", "feat/legacy")
            # legacy doc with NOW mtime → wins global by mtime-degraded epoch
            _write_handoff(wt2, "legacy.md", frontmatter=False,
                           body="# no fm\n", mtime_offset=0)
            r = _collect(main)
            g = r.data["global_latest_elsewhere"]
            self.assertIsNotNone(g)
            self.assertEqual(g["status"], "legacy")

    def test_output_keys_exact_no_internal_leak(self):
        with multi_worktree_repo() as (main, add, _root):
            _write_handoff(main, "m.md", status="done",
                           updated_at="2026-06-09T00:00:00Z")
            wt2 = add("wt2", "feat/x")
            _write_handoff(wt2, "f.md", status="active",
                           updated_at="2026-06-11T10:00:00Z")
            r = _collect(main)
            # internal keys (epoch / is_current / age_hours) must NOT leak into
            # others[] — a refactor passing entries through directly would break
            # the json-diff-normalizer contract.
            self.assertEqual(
                set(r.data["others"][0].keys()),
                {"path", "branch", "doc", "updated_at", "status",
                 "track_id", "cmp_key_source"},
            )
            self.assertEqual(
                set(r.data["global_latest_elsewhere"].keys()),
                {"path", "branch", "doc", "status", "age_hours"},
            )


class TestStandaloneFallback(unittest.TestCase):
    """current_handoff=None → fresh-scan fallback (docstring-declared direct-call
    path) must be behaviorally equivalent to the 1.15-consumed path."""

    def test_none_arg_fresh_scan_equivalent(self):
        with multi_worktree_repo() as (main, add, _root):
            _write_handoff(main, "m.md", status="active",
                           updated_at="2026-06-09T00:00:00Z")
            wt2 = add("wt2", "feat/x")
            _write_handoff(wt2, "f.md", status="active",
                           updated_at="2026-06-11T10:00:00Z")
            # omit current_handoff → current tree re-scanned via _resolve_tree_handoff
            r_none = collect_handoff_worktrees(main)
            r_consumed = _collect(main)
            self.assertEqual(r_none.data["others"], r_consumed.data["others"])
            self.assertEqual(
                r_none.data["global_latest_elsewhere"],
                r_consumed.data["global_latest_elsewhere"],
            )
            self.assertEqual(len(r_none.data["others"]), 1)  # current still excluded


class TestBareWorktree(unittest.TestCase):
    """bare worktree (no working tree) is silently skipped, not counted."""

    def test_bare_worktree_skipped(self):
        with multi_worktree_repo() as (main, _add, _root):
            _write_handoff(main, "m.md", status="active",
                           updated_at="2026-06-10T00:00:00Z")
            real = str(main.resolve())
            fake = [
                {"path": real, "branch": "master", "bare": False, "prunable": False},
                {"path": "/some/bare-repo", "branch": "(detached)",
                 "bare": True, "prunable": False},
            ]
            with mock.patch.object(hw, "_list_worktrees", return_value=(fake, None)):
                r = collect_handoff_worktrees(main, collect_handoff(main).data)
            self.assertEqual(r.data["worktree_count"], 1)  # bare not counted
            self.assertEqual(r.data["others"], [])


if __name__ == "__main__":
    unittest.main()
