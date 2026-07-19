"""#166 defect 3 — _normalize_status('Completed') → 'unknown' (should be 'done').

Spec `state-scanner-openspec-collector-false-green`: #101's word-boundary fix
(`\bcomplete\b`, to stop `incomplete` shadowing `complete`) over-tightened and
now drops the natural inflection `Completed` into `unknown` — which further
triggers `design_deferred` noise. Fix: add `completed` to the done-family
tokens (verified `\bcompleted\b` does not match `uncompleted`, so #101 stays
closed).
"""

from __future__ import annotations

import unittest

from _helpers import tmp_project, write_file
from collectors._status import _normalize_status
from collectors.openspec import collect_openspec


class TestCompletedTokenDefect3(unittest.TestCase):
    def test_completed_variants_normalize_done(self):
        # SC-7
        for raw in ("Completed", "COMPLETED", "Status: Completed", "completed"):
            self.assertEqual(_normalize_status(raw), "done", f"{raw!r} should normalize to done")

    def test_uncompleted_incomplete_not_done(self):
        # SC-8 guard: must not reopen #101 (substring shadow).
        self.assertNotEqual(_normalize_status("uncompleted"), "done")
        self.assertNotEqual(_normalize_status("incomplete"), "done")

    def test_completed_spec_pending_archive_not_design_deferred(self):
        # SC-9 cross-field side-effect: a Status=Completed spec normalizes to done,
        #   so it lands in pending_archive[] and NOT design_deferred[] (unknown noise).
        with tmp_project() as root:
            write_file(
                root / "openspec" / "changes" / "done-spec" / "proposal.md",
                "# done-spec\n\n> **Status**: Completed\n\n## Why\ntest\n",
            )
            (root / "openspec" / "archive").mkdir(parents=True, exist_ok=True)
            r = collect_openspec(root)
            deferred_ids = {d["id"] for d in r.data["design_deferred"]}
            pending_ids = {p["id"] for p in r.data["pending_archive"]}
            self.assertNotIn("done-spec", deferred_ids)
            self.assertIn("done-spec", pending_ids)


if __name__ == "__main__":
    unittest.main()
