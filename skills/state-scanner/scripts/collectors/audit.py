"""Phase 1.10 — latest audit report frontmatter collector.

#149 (round 3, current — supersedes round 2's `-R<N>-`-anchored parsing,
which was rejected by the challenger seat for two gaps found against the
real `.aria/audit-reports/` corpus):

  [M1] The timestamp token is no longer LOCATED via the `-R<N>-` round
  marker. Round 2 found the token by searching for `-R<N>-` (a bare
  integer round) and reading whatever followed — which breaks for every
  round-marker shape that isn't a bare integer: `FINAL` (no digits),
  `R5.5` (decimal round), and `R1-R2` (a merged-round marker that itself
  contains an `-R1-`-shaped substring, but not the real round). Round 3
  finds the timestamp token by scanning the filename directly for the
  first `-<token>-` segment matching an epoch-ms or ISO-ish shape,
  independent of where — or whether — a round marker sits. The round
  number is now extracted completely separately and used only as a
  second-tier sort key (see M2), never to locate the timestamp.

  [M2] A same-spec, same-timestamp tie (the repo's own
  `pre-merge-gate-no-run-for-branch` audit produced seven aggregate
  reports sharing one filename timestamp, R1..R7) now breaks by round
  number BEFORE mtime — not straight to mtime, which only happened to
  land on the right file by write-order accident. `last_audit_selection`
  now carries a `tie_break` field recording which sort-key tier actually
  decided the winner.

See `references/state-snapshot-schema.md` §`audit` for the full
`last_audit_selection` field contract this collector emits, including the
round-2 rule this module still implements at its core (candidate filter =
aggregate-shaped filenames only; never round number itself as an ordering
key; never fall back to a single-seat/stray report).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._common import CollectorResult

_AUDIT_FM = re.compile(r"^---\s*\n([\s\S]+?)\n---", re.MULTILINE)

# #149: a file only counts as an aggregate candidate when its name ends in
# one of these two literal suffixes (WITH the leading dash — `aggregate.md`
# on its own, or `aggregated-summary.md`/`my-aggregate-notes.md`, none of
# which end in `-aggregated.md`/`-aggregate.md`, are never candidates).
# Single-seat reports (agent-name suffix, e.g. `...-tech-lead.md`) and
# unrelated stray files never match either suffix, so they're never
# eligible — no matter their mtime.
_AGGREGATE_SUFFIXES = ("-aggregated.md", "-aggregate.md")

# Isolates the `<checkpoint>-` prefix. Checkpoint values are all
# `underscore_case` with no internal dashes (post_spec, pre_merge,
# post_planning, post_implementation, mid_implementation, post_brainstorm,
# ...), so "up to and including the first dash" unambiguously strips it.
# Timestamp- and round-marker scanning both operate on the remainder (with
# a synthetic leading `-` restored, so both scans' dash-boundary
# requirements still hold at position 0) — round 3 no longer anchors
# either scan on the `-R<N>-` marker's position (see module docstring M1).
_CHECKPOINT_PREFIX = re.compile(r"^[^-]+-")


def _strip_checkpoint_prefix(name: str) -> str:
    m = _CHECKPOINT_PREFIX.match(name)
    if not m:
        return name
    return "-" + name[m.end():]


# Round marker: first `-R<N>-` (integer or decimal, e.g. `R5`, `R5.5`) or
# `-FINAL-`, scanned independently of the timestamp token. A merged marker
# like `-R1-R2-` yields its leftmost half (`R1`) — immaterial, since round
# number is only ever a *second-tier* tiebreak (see M2) and a merge event
# produces exactly one file, so it never needs to out-rank a same-timestamp
# sibling. Not found at all → `-inf` (never a `-1`/`0` stand-in).
_ROUND_MARKER = re.compile(r"-(?:R(?P<num>\d+(?:\.\d+)?)|(?P<final>FINAL))-")


def _parse_round_num(name: str) -> float:
    """Round number for tiebreak purposes: FINAL sorts above every integer
    round (`+inf`); no round marker at all sorts below every real round
    (`-inf`)."""
    m = _ROUND_MARKER.search(_strip_checkpoint_prefix(name))
    if not m:
        return float("-inf")
    if m.group("final"):
        return float("inf")
    return float(m.group("num"))


# Pure-digit epoch-ms token: exactly 13 digits, dash-bounded on both sides.
# `report-storage.md`'s `timestamp_ms` field is UTC-millisecond precision
# when numeric; 13 digits is the exact width of a millisecond epoch in the
# current era. The fixed `{13}` width (not `{12,}`) rejects BOTH a 12-digit
# second-precision epoch (an unrelated convention) AND a 14-digit compact
# `YYYYMMDDHHMMSS` date (which would misparse as the year 2612 if read as
# milliseconds) — a partial match can't sneak through here: with dashes
# required on both sides, a 14-digit run has no OTHER dash inside it for a
# 13-digit sub-match to anchor against, so the whole run simply fails to
# match, same as a 12-digit run one digit short.
_EPOCH_TOKEN = re.compile(r"-(\d{13})-")

# ISO-ish date token: `YYYY-MM-DD`, dash-bounded on the left. What follows
# is inspected separately for an optional compact time part.
_ISO_DATE_TOKEN = re.compile(r"-(\d{4})-(\d{2})-(\d{2})")

# Compact time part immediately after a matched date: `THHMMZ` / `THHMMSSZ`,
# optionally with a `-mmm` millisecond suffix before `Z` (both shapes
# `report-storage.md` documents, e.g. `T1850Z`, `T220340-123Z`). `(?!\d)`
# guards each digit-run alternative so a 6-digit HHMMSS run can never be
# mis-consumed as a 4-digit HHMM run with two stray trailing digits.
_ISO_TIME = re.compile(r"^T(\d{4}(?!\d)|\d{6}(?!\d))(?:-(\d{1,3}))?Z?")


def _is_aggregate_candidate(path: Path) -> bool:
    return path.name.endswith(_AGGREGATE_SUFFIXES)


def _parse_filename_timestamp(name: str) -> datetime | None:
    """Parse the timestamp token in `name` into a UTC datetime for ordering
    purposes — scanning for the first epoch-ms or ISO-ish token, NOT
    anchored to any round marker (#149 round 3, M1).

    Returns None — never a sentinel like epoch-0 — when neither shape is
    found anywhere in the filename. Callers MUST treat None as "sorts
    last, and counts toward `unparsed_timestamp`", not as a comparably-real
    timestamp.

    A `T`-prefixed time part that fails to parse after a VALID date
    degrades to date-only precision (00:00 UTC) rather than failing the
    whole token — a malformed/unrecognized time suffix never turns an
    otherwise-good date into `None`.
    """
    rest = _strip_checkpoint_prefix(name)
    epoch_m = _EPOCH_TOKEN.search(rest)
    iso_m = _ISO_DATE_TOKEN.search(rest)

    # Leftmost match wins regardless of shape — epoch and ISO tokens can
    # never both start at the same position (one is pure digits, the other
    # has dashes at fixed offsets), so this is a strict resolution, not a
    # heuristic.
    if epoch_m and (iso_m is None or epoch_m.start() < iso_m.start()):
        try:
            return datetime.fromtimestamp(int(epoch_m.group(1)) / 1000, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    if iso_m:
        year, month, day = int(iso_m.group(1)), int(iso_m.group(2)), int(iso_m.group(3))
        hour = minute = second = microsecond = 0

        time_rest = rest[iso_m.end():]
        if time_rest.startswith("T"):
            time_m = _ISO_TIME.match(time_rest)
            if time_m:
                hms = time_m.group(1)
                hour, minute = int(hms[0:2]), int(hms[2:4])
                second = int(hms[4:6]) if len(hms) == 6 else 0
                ms_raw = time_m.group(2)
                if ms_raw:
                    microsecond = int(ms_raw.ljust(3, "0")) * 1000
            # else: a `T...` suffix that doesn't match either compact time
            # shape — degrade to date-only precision (see docstring),
            # deliberately NOT `return None` here.

        try:
            return datetime(year, month, day, hour, minute, second, microsecond, tzinfo=timezone.utc)
        except ValueError:
            return None

    return None


def _selection_sort_key(
    item: tuple[Path, "datetime | None", float]
) -> tuple[bool, datetime, float, float]:
    """`max()` key, three real tiers deep (#149 round 3, M2):

    1. a parsed timestamp always outranks an unparsed one (`ts is not None`
       as the leading bool);
    2. among parsed timestamps (or among the tied "all unparsed" group,
       which all share the same leading pair), the later `round_num` wins
       — `-inf` when a candidate has no round marker at all, so it never
       out-ranks one that does;
    3. mtime is the final tiebreak, reached only when BOTH timestamp and
       round number tie.
    """
    path, ts, round_num = item
    return (ts is not None, ts or datetime.min.replace(tzinfo=timezone.utc), round_num, path.stat().st_mtime)


def _compute_tie_break(parsed: list[tuple[Path, "datetime | None", float]]) -> str | None:
    """Which sort-key tier actually discriminated the winner among
    `parsed` (#149 round 3, M2). `None` when the top (has_ts, timestamp)
    pair was already unique — the common case, nothing to break. `"round"`
    when timestamp tied but round number broke it. `"mtime"` when BOTH
    timestamp and round number tied too (this also covers the pre-existing
    "every candidate unparsed" `mtime-fallback` case, where every
    candidate shares the same absent-timestamp bucket)."""

    def ts_key(item: tuple[Path, "datetime | None", float]) -> tuple[bool, datetime]:
        _, ts, _ = item
        return (ts is not None, ts or datetime.min.replace(tzinfo=timezone.utc))

    top_ts_key = max(ts_key(it) for it in parsed)
    ts_group = [it for it in parsed if ts_key(it) == top_ts_key]
    if len(ts_group) == 1:
        return None

    top_round = max(it[2] for it in ts_group)
    round_group = [it for it in ts_group if it[2] == top_round]
    if len(round_group) == 1:
        return "round"

    return "mtime"


def collect_audit(project_root: Path) -> CollectorResult:
    """Parse .aria/audit-reports/ for the latest AGGREGATE report's frontmatter.

    #149: previously picked `max(mtime)` across every `.md` file in the
    directory, which could select a stray non-audit file or a single-seat
    report over the actual aggregate. Round 2 fixed the candidate filter
    but anchored timestamp parsing on `-R<N>-` and broke ties by mtime
    alone. Round 3 (this version) decouples timestamp-token location from
    the round marker entirely and breaks same-timestamp ties by round
    number before mtime (see module docstring). When zero files match the
    aggregate shape, `last_audit` stays None — it never falls back to a
    single-seat or stray report.
    """
    r = CollectorResult()
    audit_dir = project_root / ".aria" / "audit-reports"
    if not audit_dir.is_dir():
        r.data = {
            "enabled": None,
            "last_audit": None,
            "last_audit_selection": _none_selection(
                candidates_scanned=0, reason="audit-reports directory does not exist"
            ),
        }
        return r

    all_reports = list(audit_dir.glob("*.md"))
    if not all_reports:
        r.data = {
            "enabled": True,
            "last_audit": None,
            "last_audit_selection": _none_selection(
                candidates_scanned=0, reason="no markdown reports in .aria/audit-reports/"
            ),
        }
        return r

    candidates = [p for p in all_reports if _is_aggregate_candidate(p)]
    if not candidates:
        r.data = {
            "enabled": True,
            "last_audit": None,
            "last_audit_selection": _none_selection(
                candidates_scanned=len(all_reports),
                reason="no aggregated report in .aria/audit-reports/",
            ),
        }
        return r

    parsed = [(p, _parse_filename_timestamp(p.name), _parse_round_num(p.name)) for p in candidates]
    unparsed_count = sum(1 for _, ts, _ in parsed if ts is None)
    all_unparsed = unparsed_count == len(parsed)

    latest = max(parsed, key=_selection_sort_key)[0]
    tie_break = _compute_tie_break(parsed)
    # Tri-state `ordering` (round 3 [m]): "filename-timestamp" = every candidate
    # parsed; "filename-timestamp-partial" = some did not (they sort LAST and
    # can never win while a parsed candidate exists — but the reader must know
    # the pool was not fully ordered by timestamp); "mtime-fallback" = none did.
    if all_unparsed:
        ordering = "mtime-fallback"
    elif unparsed_count:
        ordering = "filename-timestamp-partial"
    else:
        ordering = "filename-timestamp"
    selection = {
        "method": "aggregated-filename",
        "ordering": ordering,
        "candidates_scanned": len(all_reports),
        "aggregate_candidates": len(candidates),
        "unparsed_timestamp": unparsed_count,
        "selected": latest.name,
        "tie_break": tie_break,
    }

    try:
        text = latest.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        r.soft_error("audit_read_failed", str(e))
        r.data = {"enabled": True, "last_audit": None, "last_audit_selection": selection}
        return r

    fm = _AUDIT_FM.search(text)
    meta: dict[str, Any] = {}
    if fm:
        for line in fm.group(1).splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            raw_v = v.strip().strip("\"'")
            # R1-I6: coerce YAML-like booleans so `converged == True` works.
            if raw_v.lower() in ("true", "yes"):
                meta[k.strip()] = True
            elif raw_v.lower() in ("false", "no"):
                meta[k.strip()] = False
            else:
                meta[k.strip()] = raw_v

    r.data = {
        "enabled": True,
        "last_audit": {
            "path": str(latest.relative_to(project_root)),
            "checkpoint": meta.get("checkpoint"),
            "verdict": meta.get("verdict"),
            "converged": meta.get("converged"),
            "timestamp": meta.get("timestamp"),
        },
        "last_audit_selection": selection,
    }
    return r


def _none_selection(*, candidates_scanned: int, reason: str) -> dict[str, Any]:
    """Build the `last_audit_selection` dict for the three early-return
    "no aggregate could be selected" branches (missing dir / empty dir / no
    aggregate-shaped file). All three share `method: "none"`; `tie_break`
    is always `None` here — there is no selection to break a tie over."""
    return {
        "method": "none",
        "ordering": None,
        "candidates_scanned": candidates_scanned,
        "aggregate_candidates": 0,
        "unparsed_timestamp": 0,
        "selected": None,
        "tie_break": None,
        "reason": reason,
    }
