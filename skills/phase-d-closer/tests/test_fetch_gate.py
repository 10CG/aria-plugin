#!/usr/bin/env python3
"""Tests for phase-d-closer/scripts/fetch_gate.py (切口1, TASK-006, #133).

Deterministic — injects a fake git runner (no real git / network). Covers the
full verdict matrix + the two audit-escalated requirements:
  - R1 I4: upm_source_file == None null-guard
  - R1 I7: credential non-leak (failed stderr with embedded token must NOT appear
           in warning/message) — machine-verifiable, not code-review-only.

Run:
    python3 -m pytest tests/test_fetch_gate.py -v
    python3 tests/test_fetch_gate.py          # fallback: plain asserts
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fetch_gate import run_fetch_gate, _classify_error  # noqa: E402


def _runner(seq):
    """Build a fake git runner returning queued (rc, stdout, stderr) tuples."""
    calls = iter(seq)

    def run(args, cwd, timeout):
        try:
            return next(calls)
        except StopIteration:  # any extra call → benign empty failure
            return 1, "", ""
    return run


_SYMREF_OK = (0, "refs/remotes/origin/master\n", "")


# ── verdict matrix ──────────────────────────────────────────────────────────


def test_strong_when_behind_and_upm_touched():
    run = _runner([
        _SYMREF_OK,
        (0, "", ""),               # fetch ok
        (0, "0\t2\n", ""),         # rev-list: ahead 0, behind 2
        (0, "docs/progress/upm.md\n", ""),  # log: upm touched
    ])
    r = run_fetch_gate(".", collision_kind="none",
                       upm_source_file="docs/progress/upm.md", _runner=run)
    assert r["verdict"] == "strong"
    assert r["upm_touched"] is True
    assert r["behind"] == 2


def test_advisory_when_behind_and_collision_no_touch():
    run = _runner([
        _SYMREF_OK, (0, "", ""), (0, "0\t3\n", ""), (0, "", ""),  # not touched
    ])
    r = run_fetch_gate(".", collision_kind="cross_owner",
                       upm_source_file="docs/progress/upm.md", _runner=run)
    assert r["verdict"] == "advisory"
    assert r["upm_touched"] is False


def test_silent_when_pure_behind_no_collision_no_touch():
    run = _runner([
        _SYMREF_OK, (0, "", ""), (0, "0\t1\n", ""), (0, "", ""),
    ])
    r = run_fetch_gate(".", collision_kind="none",
                       upm_source_file="docs/progress/upm.md", _runner=run)
    assert r["verdict"] == "silent"   # 防 prompt fatigue
    assert r["behind"] == 1


def test_silent_when_synced():
    run = _runner([_SYMREF_OK, (0, "", ""), (0, "0\t0\n", "")])
    r = run_fetch_gate(".", _runner=run)
    assert r["verdict"] == "silent"
    assert r["behind"] == 0


# ── R1 I4: null-guard ────────────────────────────────────────────────────────


def test_null_guard_no_upm_project():
    # behind > 0 but upm_source_file is None (no UPM, e.g. Aria itself) →
    # cannot touch UPM → not strong; no collision → silent.
    run = _runner([_SYMREF_OK, (0, "", ""), (0, "0\t5\n", "")])
    r = run_fetch_gate(".", collision_kind="none", upm_source_file=None, _runner=run)
    assert r["verdict"] == "silent"
    assert r["upm_touched"] is False


def test_null_guard_with_collision_still_advisory():
    # None UPM but collision present + behind → advisory (collision branch).
    run = _runner([_SYMREF_OK, (0, "", ""), (0, "0\t2\n", "")])
    r = run_fetch_gate(".", collision_kind="self_multi_container",
                       upm_source_file=None, _runner=run)
    assert r["verdict"] == "advisory"
    assert r["upm_touched"] is False


# ── R1 I7: credential non-leak + fail-soft ───────────────────────────────────


def test_failsoft_fetch_failure_no_credential_leak():
    secret = "x-access-token-SECRET12345"
    stderr = f"fatal: Authentication failed for 'https://{secret}@host/repo.git/'"
    run = _runner([_SYMREF_OK, (128, "", stderr)])
    r = run_fetch_gate(".", _runner=run)
    # fail-soft: never blocks
    assert r["verdict"] == "silent"
    assert r["fetch_ok"] is False
    assert r["error_kind"] == "auth_403"
    assert r["warning"] is not None
    # CREDENTIAL MUST NOT LEAK into any surfaced string
    assert secret not in r["warning"]
    assert secret not in r["message"]
    assert "SECRET12345" not in (r["warning"] + r["message"])


def test_failsoft_network_error_kind():
    run = _runner([_SYMREF_OK, (128, "", "fatal: unable to access: Could not resolve host: x")])
    r = run_fetch_gate(".", _runner=run)
    assert r["error_kind"] == "network"
    assert r["verdict"] == "silent"


def test_no_default_branch_soft_skip():
    # symbolic-ref fails + all ref probes fail → cannot resolve → soft skip
    run = _runner([(128, "", "")] + [(1, "", "")] * 6)
    r = run_fetch_gate(".", _runner=run)
    assert r["default_branch"] is None
    assert r["verdict"] == "silent"
    assert r["warning"] is not None


def test_never_raises_on_garbage_rev_list():
    run = _runner([_SYMREF_OK, (0, "", ""), (0, "garbage-not-two-ints\n", "")])
    r = run_fetch_gate(".", _runner=run)
    assert r["behind"] is None          # unparseable → None
    assert r["verdict"] == "silent"     # behind None → treated as not-behind


# ── _classify_error enum ──────────────────────────────────────────────────────


def test_classify_error_enum():
    assert _classify_error(128, "Could not resolve host: x") == "network"
    assert _classify_error(128, "remote: HTTP 403") == "auth_403"
    assert _classify_error(1, "! [rejected] non-fast-forward") == "non_ff"
    assert _classify_error(128, "repository not found") == "git_missing"
    assert _classify_error(1, "something weird") == "other"


def run_all() -> int:
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  PASS {fn.__name__}")
        except AssertionError as e:
            print(f"  FAIL {fn.__name__}: {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {fn.__name__}: UNEXPECTED {type(e).__name__}: {e}")
            failed += 1
    if failed:
        print(f"\n{failed} test(s) failed")
        sys.exit(1)
    print(f"\nAll {len(fns)} tests passed!")
    return 0


if __name__ == "__main__":
    run_all()
