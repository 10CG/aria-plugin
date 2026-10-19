"""issue-groomer corpus loader (TASK-009, spec issue-groomer-p1-mvp).

Loads the three 2026-10-18 snapshot files that back the issue-groomer test
corpus. The corpus lives in the main repo's scratchpad and is deliberately
NOT copied into the plugin repo (spec: "不复制入库; scratchpad 单点落点风险
显式接受, 靠再生成恢复" — regenerate with scripts/regen_corpus.py). This
module therefore only ever *references* paths; every path is parameterizable
and defaults point at the canonical scratchpad trio.

Corpus shapes (as emitted by the 2026-10-18 snapshot run):

- full 18-repo file (378 rows): list of
    {"repo": str, "number": int, "title": str, "labels": [name, ...],
     "created": "YYYY-MM-DD", "updated": "YYYY-MM-DD"}
  Row order: fixed repo block order, then `number` descending within a repo.
  NOTE: `created`/`updated` are DATE-ONLY (API `created_at`/`updated_at`
  truncated to the first 10 chars) — deliberate snapshot convention.
- curated 4-repo file (150 rows): same shape + `"comments": int` (the issue
  list endpoint's comment-count field, NOT a fetched comment list).
- sample body+comments file: dict
    {"sampled_at": str, "purpose": str, "items": [item, ...]}  (5 items)
  item = {"repo", "number", "body_len", "body_head" (first 200 chars of body),
          "comments_count_field" (int, from the issue object),
          "comments_endpoint_shape": [
              {"id", "created_at", "updated_at", "body_len"}]}   (6 comments total)
  Comment timestamps here are the RAW API form (full ISO, "Z" suffix).

comment-edit synthesis (spec SC-1 component-level mandate, state-10 of the
fingerprint matrix): `with_synthetic_edit` / `synth_comment_set` produce
comment lists where one comment has updated_at > created_at, with the edit
placed so that `max(updated_at)` diverges from `max(created_at)` and from
`count` — the wrong proxies a fingerprint implementation must not fall back
to. Used by fingerprint/diff fixtures to discriminate max(updated_at) from
max(created_at)/count-based stand-ins.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ── Canonical corpus location (single point; see module docstring) ───────────

DEFAULT_CORPUS_DIR = Path("/home/dev/Aria/scratchpad")
FULL_FILENAME = "issues-open-full-18repos-2026-10-18.json"
CURATED_FILENAME = "issues-open-2026-10-18.json"
SAMPLE_FILENAME = "issues-sample-body-comments-2026-10-18.json"

# Row-order contract shared with scripts/regen_corpus.py ("同结构" 再生成):
# repo blocks appear in this fixed order, `number` descending inside a block.
FULL_REPO_ORDER = (
    "Aria", "aria-plugin", "aria-standards", "aria-orchestrator", "Aether",
    "aether-plugin", "Kairos", "SilkNode", "ShenQuant", "shenquant-data",
    "Kino", "nexus", "truffle-hound", "truffle-hound-v2", "TurfSync",
    "todo-app", "todo-web", "10cg.local",
)
CURATED_REPO_ORDER = FULL_REPO_ORDER[:4]  # Aria 系 4 卫星仓

BODY_HEAD_LEN = 200  # sample item body_head truncation length


class CorpusError(RuntimeError):
    """Corpus file missing or structurally not what this loader expects."""


# ── Loading ──────────────────────────────────────────────────────────────────

def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise CorpusError(
            f"corpus file not found: {path} — corpus is NOT copied into the "
            f"plugin repo; regenerate it with "
            f"scripts/regen_corpus.py (live API re-fetch), or pass explicit paths"
        )
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise CorpusError(f"corpus file {path} is not valid JSON: {exc}") from exc


def load_full(path: str | Path | None = None) -> list[dict[str, Any]]:
    """378-row 18-repo open-issue snapshot (see module docstring for shape)."""
    p = Path(path) if path is not None else DEFAULT_CORPUS_DIR / FULL_FILENAME
    data = _read_json(p)
    if not isinstance(data, list):
        raise CorpusError(f"{p}: expected a top-level JSON list, got {type(data).__name__}")
    return data


def load_curated(path: str | Path | None = None) -> list[dict[str, Any]]:
    """150-row 4-repo snapshot with per-issue comment counts."""
    p = Path(path) if path is not None else DEFAULT_CORPUS_DIR / CURATED_FILENAME
    data = _read_json(p)
    if not isinstance(data, list):
        raise CorpusError(f"{p}: expected a top-level JSON list, got {type(data).__name__}")
    return data


def load_sample(path: str | Path | None = None) -> dict[str, Any]:
    """Whole sample document: {"sampled_at", "purpose", "items": [5 items]}."""
    p = Path(path) if path is not None else DEFAULT_CORPUS_DIR / SAMPLE_FILENAME
    data = _read_json(p)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise CorpusError(f"{p}: expected {{..., 'items': [..]}}")
    return data


# ── Filtering / lookup helpers ───────────────────────────────────────────────

def by_repo(rows: list[dict[str, Any]], repo: str) -> list[dict[str, Any]]:
    """Exact-name repo filter, preserving corpus row order."""
    return [row for row in rows if row.get("repo") == repo]


def sample_item(doc: dict[str, Any], repo: str, number: int) -> dict[str, Any]:
    """One sample item by (repo, number); KeyError with context when absent."""
    for item in doc.get("items", []):
        if item.get("repo") == repo and item.get("number") == number:
            return item
    raise KeyError(f"sample item {repo}#{number} not in corpus sample")


def sample_comments(doc: dict[str, Any], repo: str, number: int) -> list[dict[str, Any]]:
    """`comments_endpoint_shape` of one sample item (raw API comment shape)."""
    return list(sample_item(doc, repo, number).get("comments_endpoint_shape") or [])


def sample_comments_total(doc: dict[str, Any]) -> int:
    """Total comments across all sample items (6 in the canonical snapshot)."""
    return sum(len(item.get("comments_endpoint_shape") or []) for item in doc.get("items", []))


# ── comment-edit synthesis (SC-1 state-10 判别原料) ─────────────────────────

def _parse_ts(ts: str) -> datetime:
    """Parse an API-form timestamp ("2026-10-15T16:58:30Z"); naive → UTC."""
    text = str(ts).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def comment_is_edited(comment: dict[str, Any]) -> bool:
    """True iff updated_at > created_at (an edited comment)."""
    return _parse_ts(comment["updated_at"]) > _parse_ts(comment["created_at"])


def with_synthetic_edit(
    comments: list[dict[str, Any]],
    index: int = 0,
    edit_delay_s: int = 3600,
) -> list[dict[str, Any]]:
    """Return a copy of `comments` with ONE comment's updated_at bumped.

    The synthetic updated_at is placed strictly after EVERY created_at and
    updated_at in the input (base timestamp = max over both fields, plus
    `edit_delay_s`). Default `index=0` puts the edit on the OLDEST comment,
    which is the discriminating case for the fingerprint contract: the row
    carrying `max(updated_at)` is not the newest comment by creation, so
    implementations that proxy "latest comment state" via `max(created_at)`,
    via comment `count`, or via the newest comment's row all miss the edit;
    only `max(updated_at)` over the full set sees it.

    Input is never mutated; non-edited rows are shallow-copied verbatim
    (key set preserved, so real corpus shapes round-trip unchanged).
    """
    if not comments:
        raise ValueError("cannot synthesize an edit on an empty comment list")
    if not 0 <= index < len(comments):
        raise IndexError(f"edit index {index} out of range for {len(comments)} comments")

    base = max(
        max(_parse_ts(c["created_at"]) for c in comments),
        max(_parse_ts(c["updated_at"]) for c in comments),
    )
    edited_ts = _fmt_ts(base + timedelta(seconds=edit_delay_s))

    out: list[dict[str, Any]] = []
    for i, comment in enumerate(comments):
        if i == index:
            row = dict(comment)
            row["updated_at"] = edited_ts
            out.append(row)
        else:
            out.append(dict(comment))
    return out


def synth_comment_set(
    n: int = 3,
    start: str = "2026-10-15T10:00:00Z",
    step_s: int = 3600,
    edit_index: int | None = None,
    edit_delay_s: int = 3600,
) -> list[dict[str, Any]]:
    """Deterministic API-shape comment set, optionally with one synthetic edit.

    Comments are created in ascending time order (id 1..n, one per `step_s`),
    each with updated_at == created_at (unedited). With `edit_index` set,
    `with_synthetic_edit` is applied to that index — by default place the edit
    on index 0 yourself (`edit_index=0`) to get the oldest-comment-edited
    discriminating case described in `with_synthetic_edit`.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    t0 = _parse_ts(start)
    rows = []
    for i in range(n):
        created = _fmt_ts(t0 + timedelta(seconds=step_s * i))
        rows.append({
            "id": i + 1,
            "created_at": created,
            "updated_at": created,
            "body_len": 100 + i,
        })
    if edit_index is None:
        return rows
    return with_synthetic_edit(rows, index=edit_index, edit_delay_s=edit_delay_s)
