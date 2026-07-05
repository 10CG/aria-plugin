"""TASK-010 — back-compat regression for DEC-20260704-002 (carry-id + identity).

Guards the向后兼容 hard constraints that the carry-id + advisory + identity
changes must NOT break:

  (a) adding a §6 carry-id `{id, desc}` prose block does NOT change frontmatter
      parsing — a doc with valid 5-field frontmatter still parses to 5 fields and
      does NOT degrade to legacy (owner=unknown).
  (b) derive_track_id is idempotent on kebab carry-ids; a colon-bearing id is NOT
      translated (documenting WHY the convention forbids `:`).
  (c) an old free-text §6 line (no carry-id) is NOT auto-consumed by any collector
      into gate input — the frontmatter parser only reads the 5 fields, never §6.
  (d) two containers (home_dir injection) yield distinct container_ids.
  (e) when a §6 carry-id reuses the frontmatter track-id, derive_track_id gives a
      consistent normalized value (same work ≠ two tracks).

Spec: openspec/changes/interactive-session-dedup-coordination
Task: TASK-010
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _SKILL_ROOT / "scripts"
# Shadow-proof bootstrap (invocation-mode agnostic): this module needs BOTH the
# `collectors` package (under scripts/) AND Layer L `lib` (state-scanner/lib),
# but scripts/ also contains a DIFFERENT `lib` package (collector helpers) that
# would shadow it.  Force skill root ahead of scripts unconditionally, and purge
# any pre-seeded scripts/lib binding (e.g. `python -m unittest tests.X` may seed
# scripts on the path first).  Repo-wide convention: top-level `lib` == Layer L.
for _p in (str(_SKILL_ROOT), str(_SCRIPTS)):
    while _p in sys.path:
        sys.path.remove(_p)
sys.path.insert(0, str(_SCRIPTS))       # scripts: lower priority (for `collectors`)
sys.path.insert(0, str(_SKILL_ROOT))    # skill root: highest → Layer L `lib` wins
for _k in [k for k in list(sys.modules) if k == "lib" or k.startswith("lib.")]:
    if "state-scanner/lib" not in str(getattr(sys.modules[_k], "__file__", "")):
        del sys.modules[_k]

from lib.track_id import derive_track_id  # noqa: E402
from lib.identity import get_identity  # noqa: E402
from collectors.handoff import parse_handoff_frontmatter  # noqa: E402

_FRONTMATTER = """\
---
track-id: multi-terminal-coordination
owner-container: simonfish/bfe8285d
phase: B
status: in_progress
updated-at: 2026-07-04T12:00:00Z
---

# Handoff

## §6 Next session 优先级

- id: carry-multi-terminal-coordination
  desc: 继续 Layer L advisory 接活
- id: carry-some-other-work
  desc: 另一条 carry-forward
"""

_FRONTMATTER_LEGACY_SIX = """\
---
track-id: some-track
owner-container: simonfish/bfe8285d
phase: B
status: in_progress
updated-at: 2026-07-04T12:00:00Z
---

## §6 Next session 优先级

- ⭐ 继续做那个自由文本没有 carry-id 的事情
"""


class TestFrontmatterUnaffectedByCarryId(unittest.TestCase):
    def test_carry_id_block_does_not_break_frontmatter_parse(self):
        """(a) §6 carry-id prose does not degrade the doc to legacy."""
        fm = parse_handoff_frontmatter(_FRONTMATTER)
        self.assertIsNotNone(fm, "valid frontmatter must parse (not legacy)")
        for key in ("track-id", "owner-container", "phase", "status", "updated-at"):
            self.assertIn(key, fm, f"5-field frontmatter must retain {key}")
        self.assertEqual(fm["track-id"], "multi-terminal-coordination")

    def test_free_text_six_still_parses_five_fields(self):
        """(c) old free-text §6 (no carry-id) — frontmatter still 5 fields, §6 not consumed."""
        fm = parse_handoff_frontmatter(_FRONTMATTER_LEGACY_SIX)
        self.assertIsNotNone(fm)
        self.assertEqual(len(set(fm) & {"track-id", "owner-container", "phase", "status", "updated-at"}), 5)
        # the parser must NOT surface any §6 carry-forward text as a field
        self.assertNotIn("自由文本", str(fm))


class TestCarryIdNormalization(unittest.TestCase):
    def test_kebab_carry_id_is_idempotent(self):
        """(b) a well-formed kebab carry-id normalizes to itself."""
        cid = "carry-m6-blocker3-spec"
        self.assertEqual(derive_track_id(cid), cid)
        self.assertEqual(derive_track_id(derive_track_id(cid)), cid, "idempotent")

    def test_colon_is_not_translated(self):
        """(b) derive_track_id does NOT translate `:` — hence convention forbids it."""
        # If someone violates the convention with `carry:x`, the colon survives
        # normalization (track_id.py replacement table only maps / . _ → -).
        out = derive_track_id("carry:x")
        self.assertIn(":", out, "colon survives → why the convention bans it in carry-ids")

    def test_track_id_reused_as_carry_id_is_consistent(self):
        """(e) reusing the frontmatter track-id as a §6 carry-id normalizes consistently."""
        track_id = "multi-terminal-coordination"
        carry_id = track_id  # reuse per R1-M5 (same work = same id)
        self.assertEqual(derive_track_id(carry_id), derive_track_id(track_id))


class TestIdentityPerContainer(unittest.TestCase):
    def test_two_home_dirs_yield_distinct_container_ids(self):
        """(d) two containers (home_dir injection) get distinct container_ids."""
        with tempfile.TemporaryDirectory() as h1, tempfile.TemporaryDirectory() as h2:
            id1 = get_identity(home_dir=Path(h1))
            id2 = get_identity(home_dir=Path(h2))
            self.assertNotEqual(
                id1.container_id,
                id2.container_id,
                "distinct home dirs must not collide on container_id",
            )
            # owner_container composite is well-formed
            self.assertIn("/", id1.owner_container)


if __name__ == "__main__":
    unittest.main()
