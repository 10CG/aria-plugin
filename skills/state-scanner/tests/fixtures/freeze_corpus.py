#!/usr/bin/env python3
"""Trim a state-scanner ``tracks_multibranch`` dump into the frozen test corpus.

owner-container-identity-key-and-collision-parser TASK-006 (SC-6 / SC-11).

Input : a JSON produced from ``collect_handoff_multibranch(...).data`` (either
        the bare ``tracks`` list or a dict carrying a ``tracks`` key).
Output: ``handoff-tracks-frozen-<date>.json`` with EXACTLY the eight fields the
        collision pipeline consumes — track_id / owner_container / status /
        phase / updated_at / filename / branch / legacy — sorted for a stable
        diff.  Nothing else is copied (no bodies, no emails, no tokens, no
        intranet hosts can leak: the eight fields are frontmatter tokens only).

Usage:
    python3 tests/fixtures/freeze_corpus.py <input.json> <output.json>

The committed fixture ``handoff-tracks-frozen-2026-09-05.json`` was produced
from this repository's own handoff history on 2026-09-05 (996 rows).  Re-running
the script on a newer dump is how a future spec refreshes the corpus; the
attribution test only reads the fixture, never live data (frozen snapshot rule:
memory feedback_baseline_corpus_stat_must_run_against_frozen_snapshot).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FIELDS = ("track_id", "owner_container", "status", "phase", "updated_at", "filename", "branch", "legacy")


def trim(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        out.append({k: r.get(k, False if k == "legacy" else "") for k in FIELDS})
    out.sort(key=lambda r: (r["track_id"], r["updated_at"], r["filename"], r["branch"], r["owner_container"]))
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    src, dst = Path(argv[1]), Path(argv[2])
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data["tracks"]
    frozen = trim(rows)
    payload = {
        "schema": "handoff-tracks-frozen/1",
        "fields": list(FIELDS),
        "row_count": len(frozen),
        "tracks": frozen,
    }
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"frozen {len(frozen)} rows -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
