#!/usr/bin/env python3
"""Pre-merge precondition gate helper for phase-c-integrator C.2.4.

Rule #8 (CLAUDE.md) — verify (a) PR CI passing + (b) main branch no in-flight
runs before merge. v1.31.0+ supports pluggable CI backends via the
ci_backends/ package (AetherBackend default, GitHubActionsBackend stub).

Exception contract (v1.31.0+, Hard Constraint #7 — NIE-propagation):
- Backend query_*() may raise NotImplementedError (stub backend). gate_check
  MUST propagate NIE to caller, NOT catch and route through no_ci_fallback.
  Callers MUST handle NIE explicitly. This breaks the old "exceptions are
  always translated to verdict=fail" contract — see Rule #8 wording in
  CLAUDE.md + SKILL.md §C.2.4.X for full rationale.
- AetherQueryError (or other backend transport errors) IS caught and
  translated to verdict=FAIL with raw_message (backward-compatible path).

stdlib + subprocess only (no third-party deps). Cross-platform: assumes
POSIX-like shell for `which`. Windows users go through Git Bash / WSL.

Usage (CLI):
    pre_merge_gate.py --pr-branch <branch> [--main-branch main] [--config-file path]

Output: single JSON line on stdout matching SKILL.md §C.2.4 Output schema.
Exit code: 0 = success (any verdict). Non-zero = helper failure
(distinct from gate verdict=fail which is a successful query).
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from typing import Any

from ci_backends import (
    BACKENDS,
    AetherQueryError,
    CIBackend,
    cached_probe,
)

# Verdict enum values.
VERDICT_GREEN = "green"
VERDICT_WAIT = "wait"
VERDICT_FAIL = "fail"

# v1.31.0+ default config (Hard Constraint #8: ci_backends list order is
# the explicit precedence; absent vs [] disambiguation per AC-4.5).
DEFAULT_CONFIG = {
    "enabled": True,
    "ci_backends": None,  # None/missing = auto-detect; [] = explicit disable
    "no_ci_fallback": "skip_with_warning",
    "wait_timeout_seconds": 1800,
    "wait_check_intervals": [30, 60, 120, 300, 300],
    "primitive_call_timeout_seconds": 30,
    "poll_chunk_seconds": 5,
    "user_escape_hatch": True,
}

# Legacy key alias map for soft-deprecation (Hard Constraint #3).
# Old keys still readable until v2.0; new key wins on conflict (Hard #9).
_OLD_TO_NEW: dict[str, str] = {
    "primitive_preference": "ci_backends",  # value-shape changes — see _translate_value
    "no_aether_fallback": "no_ci_fallback",
}


def _translate_value(old_key: str, old_value: Any) -> Any:
    """Per-key value-shape translation for legacy alias (Rev1 complete table).

    Translation map:
      primitive_preference: ["aether-ci-cli"]  → ci_backends: [{"name": "aether-ci-cli"}]
                            ["foo", "bar"]    → ci_backends: [{"name": "foo"}, {"name": "bar"}]
                            []                → ci_backends: []  (preserves explicit-disable semantic)
      no_aether_fallback:   "skip_with_warning" → no_ci_fallback: "skip_with_warning"  (no shape change)
                            "abort"             → no_ci_fallback: "abort"              (no shape change)
    """
    if old_key == "primitive_preference":
        if not isinstance(old_value, list):
            return old_value  # defensive: malformed config, pass through
        return [{"name": n} for n in old_value]
    if old_key == "no_aether_fallback":
        return old_value  # string enum, no shape change
    return old_value  # defensive: unknown key (shouldn't reach since _OLD_TO_NEW filters)


def _normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    """Translate legacy config keys to v1.31.0 schema with deprecation warnings.

    Operates at the `phase_c_integrator.pre_merge_gate` config sub-dict level
    (caller responsibility to pass the right sub-dict, not top-level config).
    Per Hard Constraint #3 (alias support) + #9 (new key wins on conflict).
    """
    out = dict(config)  # shallow copy
    for old, new in _OLD_TO_NEW.items():
        if old in out:
            if new in out:
                # Conflict: new wins, old discarded (Hard Constraint #9).
                warnings.warn(
                    f"both_keys_present: ignoring `{old}`, using `{new}`",
                    DeprecationWarning,
                    stacklevel=2,
                )
                del out[old]
            else:
                # Soft alias: translate old → new + warn.
                warnings.warn(
                    f"`{old}` is deprecated; use `{new}`; "
                    f"will be removed in v2.0",
                    DeprecationWarning,
                    stacklevel=2,
                )
                out[new] = _translate_value(old, out.pop(old))
    return out


def resolve_ci_backend(config: dict[str, Any]) -> CIBackend | None:
    """Resolve CI backend per [DEC 2026-05-28] §Q3 (b) config-first + probe fallback.

    Semantics (Hard Constraint #8 + AC-4.5):
      - config["ci_backends"] absent OR None  → auto-detect via BACKENDS list order
      - config["ci_backends"] is empty list [] → explicit disable (return None
        immediately, caller routes per no_ci_fallback). This is the canonical
        way for user to bypass CI backend integration in v1.31.0+.
      - config["ci_backends"] non-empty list  → try in user-specified order,
        return first that probes True;exhausted → None

    Returns None signals caller to route through no_ci_fallback path.
    """
    explicit = config.get("ci_backends")
    if explicit is not None:
        # User provided config (including [] = explicit disable per AC-4.5).
        if not explicit:
            return None
        name_map = {b.name: b for b in BACKENDS}
        for entry in explicit:
            backend_cls = name_map.get(
                entry.get("name") if isinstance(entry, dict) else entry
            )
            if backend_cls and cached_probe(backend_cls):
                return _instantiate(backend_cls, config)
        return None
    # Auto-detect (config missing or None).
    for backend_cls in BACKENDS:
        if cached_probe(backend_cls):
            return _instantiate(backend_cls, config)
    return None


def _instantiate(backend_cls: type[CIBackend], config: dict[str, Any]) -> CIBackend:
    """Instantiate backend with config-derived params where applicable.

    Currently only AetherBackend accepts a timeout param; future backends
    may accept different config-derived constructor args via this single
    extension point.
    """
    if backend_cls.name == "aether-ci-cli":
        timeout = int(config.get("primitive_call_timeout_seconds", 30))
        return backend_cls(timeout=timeout)
    return backend_cls()


def compute_verdict(
    main_in_flight_runs: list[dict[str, Any]],
    pr_ci_status: str,
    backend_name: str = "aether-ci-cli",
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute three-state verdict per SKILL.md §C.2.4 step 5.

    Hard Constraint #10 (Rev1) — extended signature accepts backend_name for
    primitive_used output field (replaces hardcoded "aether-ci-cli"). Default
    "aether-ci-cli" preserves backward compat for old test code calling with
    positional args (main_in_flight_runs, pr_ci_status).

    Returns full output dict (was: returns str). Backward-compat note: old
    callers expecting `str` must use new signature explicitly.

    Note: Returns dict for v1.31.0+ to consolidate the verdict + output_build
    code path that gate_check used to do in two steps. Old `compute_verdict`
    that returned str is replaced — Hard Constraint #10 locks new signature.
    """
    # Verdict computation (preserved logic from pre_merge_gate.py L217-228).
    if pr_ci_status in ("failing", "error"):
        verdict = VERDICT_FAIL
    elif pr_ci_status == "pending":
        verdict = VERDICT_WAIT
    elif main_in_flight_runs:
        # pr_ci_status == "passing" + main has in-flight runs → wait
        verdict = VERDICT_WAIT
    else:
        # pr_ci_status == "passing" + main no in-flight → green
        verdict = VERDICT_GREEN

    return _build_output(
        verdict=verdict,
        pr_ci_status=pr_ci_status,
        in_flight_runs=main_in_flight_runs,
        primitive_used=backend_name,
        raw_message="",
    )


def _build_output(
    verdict: str,
    pr_ci_status: str,
    in_flight_runs: list[dict[str, Any]],
    primitive_used: str,
    raw_message: str = "",
    primitive_version_sha: str = "",
) -> dict[str, Any]:
    """Build the canonical output dict per SKILL.md §C.2.4 Output schema."""
    # For Aether backend, populate primitive_version_sha from module constant.
    # For other backends, leave empty (or future: backend-specific version).
    if primitive_used == "aether-ci-cli" and not primitive_version_sha:
        from ci_backends.aether import AETHER_CLI_MIN_SHA
        primitive_version_sha = AETHER_CLI_MIN_SHA
    return {
        "verdict": verdict,
        "pr_ci_status": pr_ci_status,
        "in_flight_runs": in_flight_runs,
        "primitive_used": primitive_used,
        "primitive_version_sha": primitive_version_sha,
        "raw_message": raw_message,
    }


def _no_ci_output(no_ci_fallback: str) -> dict[str, Any]:
    """Build output for the no-backend-available case per fallback config.

    Renamed from _no_aether_output (Rev1 R1 tech F-05 — backend-agnostic
    naming). Message text updated to reference "CI backend" instead of
    "aether" specifically.
    """
    if no_ci_fallback == "abort":
        return _build_output(
            verdict=VERDICT_FAIL,
            pr_ci_status="pending",
            in_flight_runs=[],
            primitive_used="manual",
            raw_message=(
                "no CI backend available and no_ci_fallback=abort: "
                "install a supported CI backend (aether-ci-cli currently) "
                "or set no_ci_fallback=skip_with_warning"
            ),
        )
    # skip_with_warning (default): treat as green so workflow proceeds, but
    # mark the message so callers / reports surface the skip.
    return _build_output(
        verdict=VERDICT_GREEN,
        pr_ci_status="pending",
        in_flight_runs=[],
        primitive_used="manual",
        raw_message=(
            "no CI backend available; gate skipped per no_ci_fallback=skip_with_warning"
        ),
    )


def gate_check(
    pr_branch: str,
    main_branch: str = "main",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the pre-merge gate end-to-end. Return SKILL.md §C.2.4 output dict.

    Exception semantics (v1.31.0+, Hard Constraint #7):
      - NotImplementedError from backend.query_*() PROPAGATES (abort, NOT
        caught and routed to no_ci_fallback). Callers MUST handle NIE
        explicitly. This indicates a stub backend that needs implementation;
        silently skipping defeats Rule #8.
      - AetherQueryError (transport/parse failures) IS caught and translated
        to verdict=FAIL with raw_message (backward-compat path).
      - Other exceptions propagate (unchanged from prior behavior).

    Query order (Hard Constraint #1, ground truth gate_check L309-329):
      main in-flight FIRST → PR CI SECOND (early-fail on main in-flight short-
      circuits PR query, matches current Aether subprocess invocation count).
    """
    # Alias translation BEFORE merge with DEFAULT_CONFIG (Hard Constraint #9).
    # If we merged first, DEFAULT_CONFIG's new keys would always shadow user's
    # old-key values (new-wins rule would discard user intent). So:
    # 1. Normalize user config (translate user's old keys to new keys + warn)
    # 2. THEN merge with default (user's translated new key overrides default)
    user_normalized = _normalize_config(config or {})
    cfg = {**DEFAULT_CONFIG, **user_normalized}

    if not cfg["enabled"]:
        return _build_output(
            verdict=VERDICT_GREEN,
            pr_ci_status="pending",
            in_flight_runs=[],
            primitive_used="manual",
            raw_message="pre_merge_gate.enabled=false; gate skipped",
        )

    backend = resolve_ci_backend(cfg)
    if backend is None:
        return _no_ci_output(cfg["no_ci_fallback"])

    # Backend-specific precheck (e.g. AetherBackend verifies --in-flight flag
    # presence). Default precheck() returns (True, "") for backends with no
    # version constraints.
    ok, precheck_err = backend.precheck()
    if not ok:
        return _build_output(
            verdict=VERDICT_FAIL,
            pr_ci_status="pending",
            in_flight_runs=[],
            primitive_used=backend.name,
            raw_message=precheck_err,
        )

    # Query order: main in-flight FIRST then PR CI SECOND (Rev1.1 corrected,
    # matches ground truth L309-329). Hard Constraint #7: NIE propagates.
    try:
        in_flight = backend.query_branch_in_flight(main_branch)
    except NotImplementedError:
        raise  # Hard Constraint #7: propagate, do NOT route to no_ci_fallback
    except AetherQueryError as exc:
        return _build_output(
            verdict=VERDICT_FAIL,
            pr_ci_status="pending",
            in_flight_runs=[],
            primitive_used=backend.name,
            raw_message=str(exc),
        )

    try:
        pr_status = backend.query_pr_ci(pr_branch)
    except NotImplementedError:
        raise  # Hard Constraint #7
    except AetherQueryError as exc:
        return _build_output(
            verdict=VERDICT_FAIL,
            pr_ci_status="pending",
            in_flight_runs=[],
            primitive_used=backend.name,
            raw_message=str(exc),
        )

    return compute_verdict(
        main_in_flight_runs=in_flight.runs,
        pr_ci_status=pr_status.state,
        backend_name=backend.name,
        cfg=cfg,
    )


def _load_config_from_file(path: str) -> dict[str, Any]:
    """Read .aria/config.json and extract phase_c_integrator.pre_merge_gate block."""
    try:
        with open(path, encoding="utf-8") as fh:
            full = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    pci = full.get("phase_c_integrator") or {}
    if not isinstance(pci, dict):
        return {}
    block = pci.get("pre_merge_gate") or {}
    return block if isinstance(block, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-merge precondition gate (C.2.4)")
    parser.add_argument("--pr-branch", required=True, help="PR feature branch name")
    parser.add_argument("--main-branch", default="main", help="Main branch to check (default: main)")
    parser.add_argument(
        "--config-file",
        default=".aria/config.json",
        help="Path to .aria/config.json (default: .aria/config.json)",
    )
    args = parser.parse_args(argv)
    config = _load_config_from_file(args.config_file)
    output = gate_check(
        pr_branch=args.pr_branch, main_branch=args.main_branch, config=config
    )
    sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
