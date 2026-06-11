# Canonical JSON Diff Normalizer

**Status**: active
**Spec**: [`state-scanner-mechanical-enforcement`](../../../openspec/changes/state-scanner-mechanical-enforcement/) T7.0
**Consumers**: `scripts/normalize_snapshot.py`, `tests/test_snapshot_stability.py`, T7.1 dogfooding diff

---

## Purpose

`state-snapshot.json` is generated fresh on every `scan.py` invocation. Naïve diff
across two runs is dominated by wall-clock noise: timestamps, wall-paths, ephemeral
CLI paths. This normalizer defines a canonical projection so two snapshots of the
**same logical project state** always compare equal.

Two legitimate uses for the normalized form:

1. **Stability regression**: generate a baseline snapshot once, check in a
   normalized copy under `tests/fixtures/`, diff every CI run against it. Any
   unexpected diff = real change (drift, regression, or deliberate addition).
2. **Cross-machine dogfood**: two operators on different machines can confirm
   their scan.py outputs match by comparing normalized snapshots, ignoring
   path and time noise.

---

## Why reframe T7 away from "compare vs v2.9"

Spec T7.1 originally read "compare against v2.9 output fields". v2.9 was a
prose path — the AI narrated project state, never emitting JSON. There is no
v2.9 JSON to diff against. The Spec intent is: *detect unintended drift in the
field contract between releases*. T7 is therefore implemented as **snapshot
stability** (v3.0 vs v3.0 across time) rather than **cross-version diff** (v2.9
vs v3.0). See T7 commit message + `tasks.md` T7.0 entry for the divergence
record.

---

## Normalization rules

### Rule 1 — Sorted keys

Apply `json.dumps(snapshot, sort_keys=True, indent=2)`. All object keys at all
depths must be lexically sorted. This eliminates insertion-order noise.

### Rule 2 — Path normalization

Two path categories:

- **Project-relative paths** (e.g., `docs/architecture/system-architecture.md`):
  keep as-is. These are reproducible.
- **Machine-specific absolute paths** inside the snapshot's own `project_root`
  prefix (e.g., `/home/dev/Aria/...`): replace the prefix with `<project_root>`
  sentinel. The scanner's `project_root` top-level field is whitelisted and
  replaced by this sentinel too.

**Absolute path detection (conservative)**: **only** strings that start with
the detected `project_root` prefix are rewritten. Absolute paths that don't
start with `project_root` (e.g., `/tmp/foo`, `/usr/bin/git`) are left as-is,
as are URL paths (`/api/v1/...`) and any other leading-`/` content.

Rationale for conservative design: the broader regex approach ("any leading-`/`
string with 2+ segments") risks mangling URL paths, content containing
formatted paths, or cross-platform paths that aren't actually machine-specific.
The detected-prefix approach is a zero-false-positive subset — at v3.0
snapshot shape there are no machine-specific absolute paths that escape the
`project_root` prefix (collectors emit project-relative paths everywhere
else).

**Note (v1.45.0, #139)**: `handoff_worktrees.others[].path` (and
`handoff_worktrees.global_latest_elsewhere.path`) are the **first** snapshot
fields holding non-`project_root` absolute paths — they point at *other* git
worktrees, which by definition live outside the current `project_root` prefix.
They are therefore deliberately left as-is by Rule 2's conservative留白 (no
sentinel rewrite). This does not perturb stability testing: the stability
fixture is a single-worktree tree, so `others=[]` and `global_latest_elsewhere`
is `null` — the fields are absent in the normalized form and never reach the
path-rewrite path. `normalize_snapshot.py` requires **zero code change** for
this addition.

### Rule 3 — Timestamp whitelist

Timestamps are always non-deterministic. The following keys are replaced with
the sentinel `<timestamp>` wherever they appear:

- `fetched_at`
- `last_updated`
- `timestamp` (audit report frontmatter)
- `session.last_active_at` (interrupt block)
- `generated_at`

Rule: when a key matches a whitelist entry **exactly** (leaf key, not a
substring), replace the value. Nested matches traverse full dict depth.

**Note (v1.45.0, #139) — `age_hours` is a key-level DROP**: the `age_hours`
leaf key is dropped (not sentinel-replaced) by `normalize_snapshot.py` because
it is derived from `now()` at scan time and varies at sub-second precision
between consecutive runs. The drop is keyed on the **leaf-key name anywhere in
the snapshot**, so it already absorbs `handoff_worktrees.global_latest_elsewhere
.age_hours` with no code change — the drop's semantics are **key-level**, not
"`handoff.age_hours` 专属" (the in-code comment predates #139 and names only
the first consumer; the rule itself is generic by key name). The stability
fixture is single-worktree, so `global_latest_elsewhere` is `null` and this
field is a no-op there.

### Rule 4 — Ephemeral path fields

Some fields hold paths to generated artifacts that vary between runs:

- `project_root` → `<project_root>`
- `cache_path` (issue_scan) → `<cache_path>`

**Note**: `output` is intentionally NOT in this list. `custom_checks.results[*].output`
is a legitimate contract field (check's stdout first-line), not an ephemeral
path. scan.py does not echo CLI args back into the snapshot, so nothing there
requires scrubbing.

### Rule 5 — Commit SHA abbreviation

Values that look like a 40-char hex SHA are abbreviated to 7 chars so cosmetic
commit-churn doesn't blow up diffs. Abbreviated SHAs are kept as-is.

Exception: `snapshot_schema_version` and similar version strings are never
touched.

### Rule 6 — Float precision

Float values rounded to 6 decimal places. Prevents `1.0000000001` vs `1.0`
noise from different numpy-less arithmetic paths.

### Rule 7 — Null/absent equivalence

A key present with value `null` and a missing key are treated as equivalent.
Normalizer form: explicitly strip any key whose value is `None`. This matches
how consumers of JSON dicts typically read values (`obj.get("foo")` returns
`None` either way).

### Rule 8 — Error list ordering

`errors[]` at the top level is sorted by `(error, detail)` tuple. Fail-soft
error ordering is not meaningful; sorting eliminates reordering noise.

### Rule 9 — Sub-dict stability for `sync_status`

`submodules[]` is sorted by `path` (already done by scan.py but asserted here).

`multi_remote.submodules[]` + `multi_remote.main_repo.remotes[]` are sorted by
`(path, name)` and `name` respectively.

### Rule 10 — `recent_commits[]` truncation

`git.recent_commits[]` holds the 5 latest commits, which changes on every
master update. For stability testing, the normalizer drops the entire
`recent_commits` field. (Use the un-normalized snapshot if you need to inspect
commits; the normalized form is for drift detection only.)

---

## Behaviour on edge cases

- Missing field in input: silently skipped (normalizer is non-destructive).
- Non-JSON input: raise `ValueError`, do not corrupt output.
- Infinity / NaN floats: not expected in any snapshot field; if encountered,
  raise `ValueError` (JSON stdlib can't serialize them anyway).

---

## Reference implementation

See `scripts/normalize_snapshot.py` (stdlib-only, ~100 lines).

CLI:

```bash
# normalize and print to stdout
python3 scripts/normalize_snapshot.py .aria/state-snapshot.json

# diff normalized snapshot against baseline
python3 scripts/normalize_snapshot.py .aria/state-snapshot.json > /tmp/now.json
# baseline is already normalized — diff directly
diff tests/fixtures/reference-snapshot-aria.json /tmp/now.json
echo "exit $?"
```

Exit code 0 = identical after normalization = no drift.

---

## Consumers

### `tests/test_normalize_snapshot.py::TestStabilityIntegration`

Runs `scan.py` twice in a tempdir, normalizes both outputs, asserts they are
byte-identical. This is the **automated drift-detection mechanism**.

### `tests/fixtures/reference-snapshot-aria.json`

Manual-compare reference baseline (not wired into automated tests). Operators
who want to confirm "has anything changed vs. the Aria master snapshot from
T7 landing date?" can run the CLI diff snippet above. Future `test_live_scan
_matches_committed_baseline` wiring is deferred (requires periodic baseline
refresh on intentional schema changes).

### Future: T10.2 AB benchmark

When `/skill-creator benchmark` runs, normalized snapshots from the
with-skill-with-deterministic-repo-state run can be diffed to prove the skill
didn't perturb data collection. Out of scope for T7; documented here to pin
the contract for the future consumer.

---

## Not doing

- Not diffing against v2.9 — v2.9 emitted no JSON. See §reframe above.
- Not time-series normalization — this is point-in-time comparison only.
- Not semantic equivalence (e.g., matching `Approved` vs `approved`) — that
  job belongs to `collectors/_status.py::_normalize_status`, not this layer.
