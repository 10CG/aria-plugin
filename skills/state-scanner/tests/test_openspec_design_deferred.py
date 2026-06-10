"""#134 archive-completeness-gate consumption-side tests (A2.4 + A4.1/A4.2).

Covers (Spec `aria-archive-completeness-gate`, DEC-20260609-001):
- A4.1 archive_type round-trip: real marker / garbage fail-soft / missing
  proposal.md / normal archive without frontmatter.
- A4.2 design_deferred predicate fixtures: block-flip-like unknown /
  fresh-approved (<30d) excluded / stale-approved (>=30d) included /
  implemented∩¬complete included (and NOT in pending_archive).
- A2.4 complement-invariant (4 legal buckets): every active spec satisfies
  `is_complete ∨ in design_deferred ∨ normalized∈{in_progress,ready,pending}
  ∨ (approved ∧ staleness<30d)` — no third state.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _helpers import tmp_project, write_file
from collectors.openspec import (
    _DESIGN_DEFERRED_STALENESS_DAYS,
    collect_openspec,
)
from spec_complete import is_spec_complete


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _proposal(status: str, updated_days_ago: int | None = None) -> str:
    """Build a proposal.md; optional frontmatter updated-at controls staleness."""
    body = f"# spec\n\n> **Status**: {status}\n\n## Why\ntest\n"
    if updated_days_ago is None:
        return body
    return f"---\nupdated-at: {_iso_days_ago(updated_days_ago)}\n---\n{body}"


def _archived(root: Path, name: str, frontmatter: str | None) -> None:
    head = f"---\n{frontmatter}\n---\n" if frontmatter is not None else ""
    write_file(
        root / "openspec" / "archive" / name / "proposal.md",
        f"{head}# archived\n\n> **Status**: Complete\n",
    )


class TestArchiveTypeRoundTrip(unittest.TestCase):
    """A4.1 — archive_items[].archive_type additive field (契约 B 消费侧)."""

    def test_real_marker_positive_sample(self) -> None:
        with tmp_project() as root:
            (root / "openspec" / "changes").mkdir(parents=True)
            _archived(
                root,
                "2026-06-01-deferred-spec",
                "archive_type: implementation-deferred\narchived_reason: 商业拍板前不实施",
            )
            r = collect_openspec(root)
            items = r.data["archive"]["items"]
            self.assertEqual(items[0]["archive_type"], "implementation-deferred")
            self.assertFalse(
                any(e["error"] == "archive_type_unreadable" for e in r.errors)
            )

    def test_garbage_value_fail_soft(self) -> None:
        with tmp_project() as root:
            (root / "openspec" / "changes").mkdir(parents=True)
            _archived(root, "2026-06-01-bad-spec", "archive_type: garbage")
            r = collect_openspec(root)
            self.assertIsNone(r.data["archive"]["items"][0]["archive_type"])
            self.assertTrue(
                any(e["error"] == "archive_type_unreadable" for e in r.errors)
            )

    def test_missing_proposal_fail_soft(self) -> None:
        with tmp_project() as root:
            (root / "openspec" / "changes").mkdir(parents=True)
            (root / "openspec" / "archive" / "2026-06-01-empty-spec").mkdir(
                parents=True
            )
            r = collect_openspec(root)
            self.assertIsNone(r.data["archive"]["items"][0]["archive_type"])
            self.assertTrue(
                any(e["error"] == "archive_type_unreadable" for e in r.errors)
            )

    def test_normal_archive_without_frontmatter_is_silent_null(self) -> None:
        with tmp_project() as root:
            (root / "openspec" / "changes").mkdir(parents=True)
            _archived(root, "2026-06-01-normal-spec", None)
            r = collect_openspec(root)
            self.assertIsNone(r.data["archive"]["items"][0]["archive_type"])
            self.assertFalse(
                any(e["error"] == "archive_type_unreadable" for e in r.errors)
            )


class TestDesignDeferredPredicate(unittest.TestCase):
    """A4.2 — design_deferred 派生信号边界 fixtures."""

    @staticmethod
    def _deferred_ids(r) -> set[str]:
        return {d["id"] for d in r.data["design_deferred"]}

    def test_blockflip_unknown_no_tasks_lands(self) -> None:
        """(i) 活体 block-flip 形状: Status=DEFERRED→unknown, 无 tasks.md → 落."""
        with tmp_project() as root:
            write_file(
                root / "openspec" / "changes" / "block-flip-like" / "proposal.md",
                _proposal("⏸️ **DEFERRED (D+14, NOT flipped)** — defer"),
            )
            r = collect_openspec(root)
            self.assertIn("block-flip-like", self._deferred_ids(r))
            entry = r.data["design_deferred"][0]
            self.assertEqual(entry["status"], "unknown")
            self.assertIn("staleness_days", entry)
            self.assertIn("reason", entry)

    def test_fresh_approved_excluded(self) -> None:
        """(ii) Approved + <30d + open [ ] tasks → 合法在飞, 不落."""
        with tmp_project() as root:
            spec = root / "openspec" / "changes" / "fresh-approved"
            write_file(spec / "proposal.md", _proposal("**Approved**", updated_days_ago=5))
            write_file(spec / "tasks.md", "- [ ] T1\n- [ ] T2\n")
            r = collect_openspec(root)
            self.assertNotIn("fresh-approved", self._deferred_ids(r))

    def test_stale_approved_lands(self) -> None:
        """(iii) Approved + >=30d → 落."""
        with tmp_project() as root:
            spec = root / "openspec" / "changes" / "stale-approved"
            write_file(
                spec / "proposal.md",
                _proposal(
                    "**Approved**",
                    updated_days_ago=_DESIGN_DEFERRED_STALENESS_DAYS + 5,
                ),
            )
            write_file(spec / "tasks.md", "- [ ] T1\n")
            r = collect_openspec(root)
            self.assertIn("stale-approved", self._deferred_ids(r))

    def test_implemented_incomplete_lands_not_pending_archive(self) -> None:
        """(iv) implemented∩¬complete → 落 design_deferred, 不落 pending_archive."""
        with tmp_project() as root:
            spec = root / "openspec" / "changes" / "impl-await-verify"
            write_file(spec / "proposal.md", _proposal("Implemented", updated_days_ago=1))
            write_file(spec / "tasks.md", "- [x] T1\n- [ ] T2\n")
            r = collect_openspec(root)
            self.assertIn("impl-await-verify", self._deferred_ids(r))
            self.assertEqual(r.data["pending_archive"], [])

    def test_reviewed_incomplete_lands(self) -> None:
        with tmp_project() as root:
            write_file(
                root / "openspec" / "changes" / "reviewed-spec" / "proposal.md",
                _proposal("Reviewed", updated_days_ago=1),
            )
            r = collect_openspec(root)
            self.assertIn("reviewed-spec", self._deferred_ids(r))

    def test_in_progress_excluded_surfaced_elsewhere(self) -> None:
        """in_progress 由 priority_items 别处 surface, 不入 design_deferred."""
        with tmp_project() as root:
            write_file(
                root / "openspec" / "changes" / "wip-spec" / "proposal.md",
                _proposal("In Progress", updated_days_ago=90),
            )
            r = collect_openspec(root)
            self.assertNotIn("wip-spec", self._deferred_ids(r))

    def test_done_complete_goes_pending_archive_not_deferred(self) -> None:
        """A2.5 — done 落 pending_archive (archive-ready={done} only), 不落 deferred."""
        with tmp_project() as root:
            write_file(
                root / "openspec" / "changes" / "done-spec" / "proposal.md",
                _proposal("Done"),
            )
            r = collect_openspec(root)
            self.assertEqual(r.data["pending_archive"][0]["id"], "done-spec")
            self.assertNotIn("done-spec", self._deferred_ids(r))


class TestComplementInvariant(unittest.TestCase):
    """A2.4 — gate↔surface 互补 4 合法桶, 无第三态 (可机械验证形式).

    对每个 active spec 断言:
      is_complete ∨ in design_deferred ∨ normalized∈{in_progress,ready,pending}
      ∨ (normalized=='approved' ∧ staleness<30d)
    前置: changes/ 不含 terminal 态 (archived/deprecated)。
    """

    # raw Status × tasks.md 内容 (None=absent) — 覆盖全 non-terminal normalized
    # 桶 × complete 真假; 含 fresh/stale approved 两侧。
    _MATRIX: list[tuple[str, str, str | None, int]] = [
        # (spec_id, raw_status, tasks_md, updated_days_ago)
        ("m-pending", "Draft", None, 1),
        ("m-ready", "Ready", "- [ ] T\n", 1),
        ("m-inprogress", "In Progress", "- [ ] T\n", 90),
        ("m-fresh-approved", "Approved", "- [ ] T\n", 5),
        ("m-stale-approved", "Approved", "- [ ] T\n", 45),
        ("m-reviewed", "Reviewed", None, 1),
        ("m-active", "Active", "- [ ] T\n", 1),
        ("m-implemented", "Implemented", "- [x] T\n- [ ] U\n", 1),
        ("m-done", "Done", "- [x] T\n", 1),
        ("m-done-by-tasks", "Approved", "- [x] T\n- [x] U\n", 5),
        ("m-unknown", "DEFERRED weird custom state", None, 1),
        ("m-carry-forward", "Approved", "- [x] T [deferred to next cycle]\n", 45),
    ]

    def test_every_active_spec_lands_in_a_legal_bucket(self) -> None:
        with tmp_project() as root:
            for spec_id, raw, tasks, age in self._MATRIX:
                spec = root / "openspec" / "changes" / spec_id
                write_file(spec / "proposal.md", _proposal(raw, updated_days_ago=age))
                if tasks is not None:
                    write_file(spec / "tasks.md", tasks)
            r = collect_openspec(root)

            deferred = {d["id"] for d in r.data["design_deferred"]}
            by_id = {it["id"]: it for it in r.data["changes"]["items"]}
            self.assertEqual(len(by_id), len(self._MATRIX))

            for spec_id, _raw, _tasks, age in self._MATRIX:
                st = by_id[spec_id]["status"]
                spec_dir = root / "openspec" / "changes" / spec_id
                complete = is_spec_complete(spec_dir)["complete"]
                in_deferred = spec_id in deferred
                elsewhere = st in {"in_progress", "ready", "pending"}
                fresh_approved = st == "approved" and age < _DESIGN_DEFERRED_STALENESS_DAYS
                self.assertTrue(
                    complete or in_deferred or elsewhere or fresh_approved,
                    f"third-state black hole: {spec_id} (normalized={st}, "
                    f"complete={complete}, deferred={in_deferred})",
                )

    def test_buckets_are_exclusive_where_required(self) -> None:
        """design_deferred 与 {in_progress,ready,pending}/fresh-approved 不重叠."""
        with tmp_project() as root:
            for spec_id, raw, tasks, age in self._MATRIX:
                spec = root / "openspec" / "changes" / spec_id
                write_file(spec / "proposal.md", _proposal(raw, updated_days_ago=age))
                if tasks is not None:
                    write_file(spec / "tasks.md", tasks)
            r = collect_openspec(root)
            deferred = {d["id"] for d in r.data["design_deferred"]}
            self.assertNotIn("m-inprogress", deferred)
            self.assertNotIn("m-ready", deferred)
            self.assertNotIn("m-pending", deferred)
            self.assertNotIn("m-fresh-approved", deferred)
            # carry-forward annotation defeats all-[x] completeness → stale 落
            self.assertIn("m-carry-forward", deferred)
            # 全勾且无注释但 Status=Approved+fresh → complete 桶 (右析取无关)
            self.assertNotIn("m-done-by-tasks", deferred)


if __name__ == "__main__":
    unittest.main()
