# Migration Guide: state-scanner v2.9 → v3.0

**Status**: active
**Spec**: [`state-scanner-mechanical-enforcement`](../../../openspec/changes/state-scanner-mechanical-enforcement/)
**Target Release**: aria-plugin v1.17.0
**Opt-out Removal**: aria-plugin v1.18.0 (AD-SSME-5)

---

## TL;DR

v3.0.0 turns Phase 1 data collection from an AI-prose discipline into a mechanical one. The AI must call `scripts/scan.py` as Step 0 and read the resulting `.aria/state-snapshot.json` instead of invoking Bash / Grep to rebuild state manually. For one `aria-plugin` minor cycle (v1.17.0), operators who must stay on the v2.x path can set `state_scanner.mechanical_mode: false` in `.aria/config.json`. Starting v1.18.0 that flag is gone.

---

## Why the change

| Pain point in v2.9 prose path | v3.0 mechanical path |
|---|---|
| Phase 1.13 (issue scan) quietly skipped when AI forgets `forgejo` CLI lookup | scan.py always runs Phase 1.13 when config enables it; snapshot carries explicit `fetched_at` |
| Phase 1.11 (custom checks) inconsistent — AI improvises yaml parsing | `collectors/custom_checks.py` deterministic YAML subset parser |
| Status normalization drift (Approved / Reviewed / Active silently collapsed to ready / pending) | collectors preserve distinct states (D1/D2/D5) — see §D1–D5 below |
| PRD chain validation accepts `TBD` / `pending` as valid link | `collectors/architecture.py` rejects placeholder markers (D3) |
| YAML block scalar marker `key: |` leaks literal `"|"` as value | `collectors/_status.py` returns `None` on block markers (D4) |
| Hard-to-diff session artifacts (rerun produces different AI narration) | Canonical JSON snapshot: schema-versioned, diffable via `json-diff-normalizer.md` (T7.0, forthcoming) |

---

## What changes for AI callers

### Step 0 becomes mandatory

Before v3.0, AI would open `git status`, walk `openspec/changes/`, read `audit-reports/` directly. That path is now the **v2.x opt-out**.

The v3.0 contract:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/state-scanner/scripts/scan.py" \
  --output .aria/state-snapshot.json
```

Then read `.aria/state-snapshot.json` and branch on fields. Do not replace this with `git status` / `ls openspec/changes/` style enumeration.

### Exit codes (new in v3.0)

| Code | Meaning | AI action |
|------|---------|-----------|
| 0 | Clean snapshot | proceed to Phase 2 |
| 10 | Soft errors (snapshot still usable; see `errors[]`) | proceed with warning |
| 20 | Hard precondition failed (not a git repo, output path unwritable) | abort, show stderr |
| 30 | Uncaught exception | abort, collect stderr, file bug |

### Top-level snapshot keys (stable)

`snapshot_schema_version` pins at `"1.0"` for all v3.0.x releases. Any consumer must verify this before consuming fields. Full schema: [`state-snapshot-schema.md`](./state-snapshot-schema.md).

---

## D1–D5: Intentional divergences from v2.9 prose

These are bug fixes in v3.0 but would read like regressions if you diff a v2.9-era handwritten report against a v3.0 `scan.py` snapshot. Covered by regression tests under `tests/test_openspec.py`, `tests/test_architecture.py`, `tests/test_upm.py`.

| # | v2.9 behaviour | v3.0 behaviour | Rationale |
|---|---|---|---|
| D1 | `Status: Approved` collapsed to `ready` | preserved as `approved` | audit / archiving gates need this distinction |
| D2 | `Status: Reviewed` collapsed to `pending` | preserved as `reviewed` | Spec pipeline state is a superset of 3-state ready/pending/done |
| D3 | `Parent PRD: TBD` returned `chain_valid: true` | placeholders rejected | architecture linting must fail, not silently pass |
| D4 | YAML `key: \|` returned the literal `"|"` string | returns `None` | block scalar bodies span multiple lines — cannot be inlined |
| D5 | `Active / Deprecated / Archived` all mapped to `unknown` | preserved as distinct states | long-lived Specs need a lifecycle beyond done |

When running `T7` dogfooding diff, whitelist these 5 fields in the canonical normalizer so the fix is not flagged as regression.

---

## Opt-out path (`mechanical_mode: false`)

Available for exactly one minor release — aria-plugin v1.17.0 — then removed in v1.18.0.

### Who needs it

- Users on a deploy target where Python 3.8+ is unavailable
- Users whose shell cannot resolve `${CLAUDE_PLUGIN_ROOT}` correctly (rare)
- Users hitting an acute bug in `scan.py` that requires a rollback while a fix ships

### How to enable

Edit `.aria/config.json`:

```json
{
  "state_scanner": {
    "mechanical_mode": false
  }
}
```

The flag is an **AI-prose contract**, not a `scan.py` switch. When `mechanical_mode` is `false`, SKILL.md §Step 0 permits the AI to rebuild Phase 1 state via Bash / Grep as it did in v2.x. The snapshot file is not written.

### Why this design

`scan.py` itself does not branch on `mechanical_mode` because the script is the mechanical path — if you are running `scan.py`, you are already opting in. The flag exists so that:

1. The SKILL.md prose can distinguish the two paths without a runtime dependency
2. Downstream skills (phase-a-planner, workflow-runner) can inspect the flag via config-loader to decide whether to expect `.aria/state-snapshot.json`
3. Audit tooling can flag `mechanical_mode: false` deployments in telemetry (future)

### Removal timeline

- **v1.17.0** (this release): flag present, defaults to `true`, CHANGELOG entry "state-scanner v3.0.0 mechanical mode, opt-out available"
- **v1.17.x patches**: observe telemetry; if any project sets `mechanical_mode: false`, reach out before v1.18.0
- **v1.18.0**: flag ignored (or warns and proceeds with mechanical path); CHANGELOG entry "state-scanner opt-out removed — prose path deprecated"

Zero opt-out usage over the v1.17.x cycle is the green-light signal for removal.

---

## Downstream callers

### workflow-runner

No behaviour change. It receives `phase_cycle`, `active_module`, and `changed_files` from state-scanner as before. The *source* of those fields shifts from AI recap to snapshot extraction, but the hand-off contract is unchanged.

### phase-a-planner

No behaviour change. Spec draft and task planning still read `openspec_status` from the state-scanner hand-off. The snapshot path produces the same field shape as the prose path (same `openspec.changes.items[*].status` structure), so Phase A logic works unchanged.

### audit-engine

No behaviour change. Audit checkpoints read `audit_status` from state-scanner context, and the snapshot provides it in the same shape. The normalization of `converged` from string → bool (R1-I6 fix) is a quiet correctness improvement.

### Custom integrators (external projects)

Projects that consume state-scanner output via `/aria:state-scanner` and parse the AI's narrative should migrate to reading `.aria/state-snapshot.json` directly. The JSON is stable and versioned; the narrative is not.

---

## Upgrade checklist

For each project that has adopted state-scanner:

- [ ] Confirm Python 3.8+ is available on all dev machines: `python3 --version`
- [ ] Run `python3 aria/skills/state-scanner/scripts/scan.py --output /tmp/test-snapshot.json` — expect exit 0 or 10
- [ ] Validate `snapshot_schema_version == "1.0"`: `python3 -c "import json; print(json.load(open('/tmp/test-snapshot.json'))['snapshot_schema_version'])"`
- [ ] If custom health checks in use: validate `.aria/state-checks.yaml` parses cleanly (see `collectors/custom_checks.py` YAML subset)
- [ ] Verify `.gitignore` includes `.aria/state-snapshot.json` (session artifact, should not be committed)
- [ ] If Phase 1.13 (issue scan) enabled: confirm `forgejo` or `gh` CLI is on PATH and authenticated
- [ ] Cross-reference D1–D5 against any internal tooling that consumed v2.9 Status strings directly — rename `ready → approved`, `pending → reviewed` where semantics matter

---

## Rollback

If v3.0 breaks a project mid-release cycle:

1. Immediate: set `state_scanner.mechanical_mode: false` in `.aria/config.json`
2. Pin aria-plugin to v1.16.x in your plugin manifest (v1.17.0 has mechanical as default but offers opt-out; v1.18.0 has no escape)
3. File an issue at <https://github.com/10CG/aria-plugin/issues> with the `state-snapshot.json` (or failure mode) attached; redact any secrets before posting
4. Re-enable mechanical mode once the upstream fix lands

No downgrade path is provided past v1.18.0 — the prose path is deleted at that point. Users expecting to stay on v2.9 indefinitely should pin their plugin version in a manifest.

---

## References

- Spec: `openspec/changes/state-scanner-mechanical-enforcement/proposal.md`
- Schema SoT: [`state-snapshot-schema.md`](./state-snapshot-schema.md)
- Exit code contract: `state-snapshot-schema.md` §Exit code consumer contract
- SKILL.md §Step 0: `aria/skills/state-scanner/SKILL.md` (v3.0.0+)
- Regression guards: `aria/skills/state-scanner/tests/test_{openspec,architecture,upm}.py`
