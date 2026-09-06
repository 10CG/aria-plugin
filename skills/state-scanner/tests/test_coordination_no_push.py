"""Push suppression for the Layer L coordination CLIs —
``--no-push`` / ``ARIA_COORDINATION_NO_PUSH`` (fix/phase1-gate-no-push).

Why
---
``scripts/phase1_gate.py`` pushes ``refs/aria/coordination`` to the project's
REAL remote after writing a claim (Step 9, and the 7a self-resume path), and
``scripts/release_gate.py`` does the same after a release/sweep/gc write
(Step 5).  Neither had a CLI flag, env var, or config knob to suppress that
push.  The Rule #6 AB benchmark harness (/skill-creator) runs eval prompts as
subagents INSIDE the real Aria repo (real origin, no sandbox), so any evaluated
skill that instructs the AI to call these CLIs pushes synthetic claims to the
production coordination ref (a synthetic claim
``postspec-r1-delete-me-a1-entry-claim-audit-test`` landed there 2026-08-02).

What is locked in
-----------------
- Two suppression channels: ``--no-push`` (CLI) and ``ARIA_COORDINATION_NO_PUSH``
  (env; truthy = 1 / true / yes case-insensitive, anything else / unset = off).
- Additive JSON keys ``push_skipped`` / ``push_skipped_reason`` that make a
  deliberate skip distinguishable from a push FAILURE (``push_skipped=false``,
  ``push_success=false``, ``error=<kind>``) and from "push step never reached"
  (``push_success=null``).  ``push_success`` is ``false`` (never ``true``) when
  skipped.
- The local claim write still happens exactly as before.
- Negative control: neither channel → the push IS attempted.

Strategy
--------
Real temp git repos (no mocks on the git layer) so the CLI's argparse wiring and
env resolution in ``_main()`` are on the tested path — a kwarg spelling error in
the wiring cannot hide behind a mocked function.  ``_fresh_repo`` mirrors
``test_release_by_track._fresh_repo`` and is copied rather than imported: bare
cross-test-module imports resolve only under the stdlib ``unittest discover``
runner this suite is built for (pytest's package-mode collection cannot even
import ``_helpers`` here).  Two additional layers:

- ``TestNoPushLibraryPaths`` patches the ``resilient_push`` boundary (as
  test_phase1_gate_advisory does) to assert the DIRECT evidence — the push
  primitive is never called — on both call sites (Step 9 and 7a self-resume).
- ``TestNoPushAgainstBareRemote`` wires a bare remote so the ground truth
  ("remote ref SHA did / did not move") is asserted, not inferred from JSON.
  Its negative control proves the fixture can observe a push at all.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

# Path bootstrap — scripts/ for phase1_gate, skill root for Layer L `lib`.
# Skill root MUST land at sys.path[0] so top-level `lib` resolves to
# state-scanner/lib, not scripts/lib (same rationale as test_phase1_gate_advisory).
_SKILL_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _SKILL_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

import phase1_gate as g  # noqa: E402
from lib.claim_lifecycle import AcquireResult, acquire_claim  # noqa: E402
from lib.claim_schema import ClaimRecord  # noqa: E402
from lib.coordination_ref import ReadClaimsResult, bootstrap, read_claims  # noqa: E402
from lib.failure_handlers import FetchHealth, ResilientPushResult  # noqa: E402
from lib.identity import Identity, get_identity  # noqa: E402
from lib.track_id import derive_track_id  # noqa: E402

_PHASE1_GATE = _SCRIPTS / "phase1_gate.py"
_RELEASE_GATE = _SCRIPTS / "release_gate.py"
_ENV = "ARIA_COORDINATION_NO_PUSH"
_COORD_REF = "refs/aria/coordination"
_SUBPROCESS_TIMEOUT = 120  # push to a missing remote fails fast; generous for slow CI


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _sh(cmd: list[str], cwd: Path | str) -> str:
    return subprocess.run(
        cmd, cwd=str(cwd), check=True, capture_output=True, text=True
    ).stdout.strip()


def _fresh_repo() -> Path:
    """Temp repo: one commit + a bootstrapped (local-only) coordination ref, NO remote."""
    d = tempfile.mkdtemp(prefix="coord-no-push-")
    repo = Path(d)
    _sh(["git", "init", "-q"], d)
    _sh(["git", "config", "user.email", "t@t"], d)
    _sh(["git", "config", "user.name", "t"], d)
    (repo / "x").write_text("x")
    _sh(["git", "add", "-A"], d)
    _sh(["git", "commit", "-qm", "init"], d)
    bootstrap(repo, push=False)
    return repo


def _with_bare_remote(repo: Path) -> Path:
    """Attach a bare ``origin`` already holding the coordination ref; return its path."""
    bare = Path(tempfile.mkdtemp(prefix="coord-bare-"))
    _sh(["git", "init", "-q", "--bare"], bare)
    _sh(["git", "remote", "add", "origin", str(bare)], repo)
    _sh(["git", "push", "-q", "origin", f"{_COORD_REF}:{_COORD_REF}"], repo)
    return bare


def _ref_sha(git_dir: Path) -> str:
    return _sh(["git", "rev-parse", _COORD_REF], git_dir)


def _clean_env(**overrides: str) -> dict[str, str]:
    """Copy of os.environ with ARIA_COORDINATION_NO_PUSH REMOVED, then overrides.

    Removing (not merely not-setting) the variable is what makes the negative
    control a control: a developer shell that exports it must not leak in.
    """
    env = {k: v for k, v in os.environ.items() if k != _ENV}
    env.update(overrides)
    return env


def _run_cli(script: Path, argv: list[str], env: dict[str, str]):
    proc = subprocess.run(
        [sys.executable, str(script), *argv],
        capture_output=True,
        text=True,
        env=env,
        timeout=_SUBPROCESS_TIMEOUT,
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, payload, proc.stderr


def _run_gate_cli(repo: Path, raw_track: str, *extra: str, env: dict[str, str]):
    return _run_cli(
        _PHASE1_GATE,
        [
            "--raw-track-id", raw_track, "--phase", "B", "--mode", "advisory",
            "--repo-path", str(repo), *extra,
        ],
        env,
    )


def _run_release_cli(repo: Path, *args: str, env: dict[str, str]):
    return _run_cli(_RELEASE_GATE, ["--repo-path", str(repo), *args], env)


def _local_track_claims(repo: Path, raw_track: str) -> list[ClaimRecord]:
    tid = derive_track_id(raw_track)
    return [c for c in read_claims(repo).claims if c.track_id == tid]


# ---------------------------------------------------------------------------
# phase1_gate CLI — the four required assertions (a)-(d) + precedence
# ---------------------------------------------------------------------------

class TestPhase1GateNoPushCli(unittest.TestCase):
    """CLI contract for the two suppression channels + negative controls.

    Repos have NO remote: without suppression the push fails fail-soft
    (advisory) — exactly the state a deliberate skip must be told apart from.
    """

    def test_a_cli_flag_skips_push_and_still_writes_local_claim(self):
        """(a) --no-push → exit 0, push_skipped=true, reason=cli_flag,
        push_success=false (not null), claim present in local refs/aria/coordination.

        How this goes red: argparse rejects --no-push (exit 2, no JSON) — or the
        keys are missing (KeyError) — or push_success stays null (assertIs False)
        — or the skip also skipped Step 8 (no local claim)."""
        repo = _fresh_repo()
        rc, out, err = _run_gate_cli(repo, "carry-no-push-a", "--no-push", env=_clean_env())
        self.assertEqual(rc, 0, err[-500:])
        self.assertIs(out["push_skipped"], True)
        self.assertEqual(out["push_skipped_reason"], "cli_flag")
        self.assertIs(out["push_success"], False)
        self.assertTrue(out["proceed"])
        # 主动跳过不得被报成 push 侧错误。
        # 注意别写成 assertIsNone(error): 本类的夹具**刻意没有 remote** (见类
        # docstring), 而 a1-entry TASK-015 起 Step 4 的 fetch 降级也会落进同一个
        # error 字段 —— 那是「读 ref 这一步」的软信号, 与本条要守的「推这一步」无关。
        # 用 error is None 表达「跳过不是错误」会把两条正交路径绑死。
        self.assertNotIn(out["error"], {"push_failed", "auth_failed",
                                        "max_retries_exhausted", "user_aborted"})
        mine = _local_track_claims(repo, "carry-no-push-a")
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0].status, "active")

    def test_b_env_var_skips_push_with_reason_env_var(self):
        """(b) ARIA_COORDINATION_NO_PUSH=1 and NO flag → same as (a), reason=env_var.

        How this goes red: _main() never consults the env (push attempted →
        push_skipped false) — or the reason is mislabelled cli_flag."""
        repo = _fresh_repo()
        rc, out, err = _run_gate_cli(repo, "carry-no-push-b", env=_clean_env(**{_ENV: "1"}))
        self.assertEqual(rc, 0, err[-500:])
        self.assertIs(out["push_skipped"], True)
        self.assertEqual(out["push_skipped_reason"], "env_var")
        self.assertIs(out["push_success"], False)
        self.assertEqual(len(_local_track_claims(repo, "carry-no-push-b")), 1)

    def test_c_negative_control_no_flag_no_env_attempts_push(self):
        """(c) neither flag nor env (var explicitly REMOVED from the subprocess env)
        → push_skipped=false, push_skipped_reason=null.  Only the two new keys are
        asserted: the push itself fails in this remote-less repo (fail-soft
        advisory) — the very state a skip must be distinguishable from.

        How this goes red: push_skipped hard-coded / defaulted to true — or an
        unset env var treated as truthy — or the keys missing (KeyError)."""
        repo = _fresh_repo()
        rc, out, err = _run_gate_cli(repo, "carry-no-push-c", env=_clean_env())
        self.assertIsNotNone(out, err[-500:])
        self.assertIs(out["push_skipped"], False)
        self.assertIsNone(out["push_skipped_reason"])

    def test_d_env_var_zero_is_off(self):
        """(d) ARIA_COORDINATION_NO_PUSH=0 → OFF, identical to (c).

        How this goes red: env resolution uses bare string truthiness ("0" is a
        non-empty string) or `is not None`."""
        repo = _fresh_repo()
        rc, out, err = _run_gate_cli(repo, "carry-no-push-d", env=_clean_env(**{_ENV: "0"}))
        self.assertIsNotNone(out, err[-500:])
        self.assertIs(out["push_skipped"], False)
        self.assertIsNone(out["push_skipped_reason"])

    def test_flag_and_env_both_set_reports_cli_flag(self):
        """Both channels on → reason names the explicit CLI flag (documented
        precedence).  How this goes red: env checked before the flag."""
        repo = _fresh_repo()
        rc, out, err = _run_gate_cli(
            repo, "carry-no-push-e", "--no-push", env=_clean_env(**{_ENV: "yes"})
        )
        self.assertEqual(rc, 0, err[-500:])
        self.assertIs(out["push_skipped"], True)
        self.assertEqual(out["push_skipped_reason"], "cli_flag")


# ---------------------------------------------------------------------------
# Ground truth against a bare remote — the remote ref SHA
# ---------------------------------------------------------------------------

class TestNoPushAgainstBareRemote(unittest.TestCase):
    """The negative control here proves the fixture can observe a push (remote
    moves), so "remote did not move" under suppression is a real measurement,
    not a vacuous one."""

    def test_default_run_moves_remote_ref(self):
        """Negative control with teeth: no suppression → push succeeds against the
        bare origin and the remote coordination ref SHA advances.

        How this goes red: the fixture cannot see pushes (which would make the
        sibling tests vacuous) — or the default flipped to no-push."""
        repo = _fresh_repo()
        bare = _with_bare_remote(repo)
        before = _ref_sha(bare)
        rc, out, err = _run_gate_cli(repo, "carry-remote-ctl", env=_clean_env())
        self.assertEqual(rc, 0, err[-500:])
        self.assertIs(out["push_success"], True)
        self.assertIs(out["push_skipped"], False)
        self.assertNotEqual(_ref_sha(bare), before)
        self.assertEqual(_ref_sha(bare), _ref_sha(repo))

    def test_no_push_leaves_remote_ref_untouched_but_advances_local(self):
        """--no-push against a REAL (bare) origin: local ref advances with the new
        claim, remote ref SHA is byte-identical to before.

        How this goes red: any code path still pushes (remote moves) — or the
        local write was skipped too (local == before)."""
        repo = _fresh_repo()
        bare = _with_bare_remote(repo)
        before = _ref_sha(bare)
        self.assertEqual(_ref_sha(repo), before)
        rc, out, err = _run_gate_cli(repo, "carry-remote-np", "--no-push", env=_clean_env())
        self.assertEqual(rc, 0, err[-500:])
        self.assertIs(out["push_skipped"], True)
        self.assertEqual(_ref_sha(bare), before)  # remote untouched
        self.assertNotEqual(_ref_sha(repo), before)  # local claim written

    def test_env_var_leaves_remote_ref_untouched(self):
        """Same ground truth through the env channel — the channel the AB runbook
        prescribes (subagents inherit the session environment)."""
        repo = _fresh_repo()
        bare = _with_bare_remote(repo)
        before = _ref_sha(bare)
        rc, out, err = _run_gate_cli(
            repo, "carry-remote-env", env=_clean_env(**{_ENV: "true"})
        )
        self.assertEqual(rc, 0, err[-500:])
        self.assertEqual(out["push_skipped_reason"], "env_var")
        self.assertEqual(_ref_sha(bare), before)


# ---------------------------------------------------------------------------
# Library paths — direct evidence at the resilient_push boundary
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
_ME = Identity(owner="me", container_id="cA", session_id="s-me")
_TRACK = "carry-no-push-lib"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _claim(container: str, session: str, claimed_at: datetime) -> ClaimRecord:
    return ClaimRecord(
        schema_version="1",
        track_id=_TRACK,
        owner="me",
        container=container,
        session=session,
        phase="B",
        status="active",
        claimed_at=_iso(claimed_at),
        heartbeat_at=_iso(claimed_at),
        superseded_from=None,
    )


class TestNoPushLibraryPaths(unittest.TestCase):
    """resilient_push is NEVER called under no_push — on BOTH call sites (Step 9
    and the 7a self-resume push).  The push mock would report success=True if
    invoked, so a stray call flips push_success to true and fails assertIs(False)."""

    def _patched(self, claims: list[ClaimRecord]) -> mock.Mock:
        fetch = FetchHealth(
            success=True,
            partial_fetch=False,
            ref_sha_before="a" * 40,
            ref_sha_after="a" * 40,
            error_kind=None,
            error_msg=None,
        )
        rc = ReadClaimsResult(claims=list(claims), errors=[], ref_exists=True)
        acq = AcquireResult(success=True, record=_claim("cA", "s-me", _NOW), error=None)
        push_mock = mock.Mock(
            return_value=ResilientPushResult(
                success=True,
                final_push_result=None,
                attempts=1,
                triggered_fetch_replay=False,
                bootstrap_triggered=False,
                error_kind=None,
                error_msg=None,
                user_aborted=False,
            )
        )
        for p in (
            mock.patch.object(g, "_is_git_repo", return_value=True),
            mock.patch.object(g, "health_check_fetch", return_value=fetch),
            mock.patch.object(g, "read_claims", return_value=rc),
            mock.patch.object(g, "acquire_claim", return_value=acq),
            mock.patch.object(g, "resilient_push", push_mock),
        ):
            p.start()
            self.addCleanup(p.stop)
        return push_mock

    def test_step9_no_push_never_calls_resilient_push(self):
        """Clean path (no competition) with no_push=True → PASSED, own_claim set,
        push_result None, push_skipped True, resilient_push NOT called.

        How this goes red: no_push accepted but ignored (mock called →
        assert_not_called fails and push_success flips to true)."""
        push_mock = self._patched([])
        with tempfile.TemporaryDirectory() as td:
            result = g.run_gate(
                _TRACK, "B", repo_path=Path(td), identity=_ME, now=_NOW, no_push=True
            )
        push_mock.assert_not_called()
        self.assertEqual(result.outcome, g.GateOutcome.PASSED)
        self.assertIsNotNone(result.own_claim)
        self.assertIsNone(result.push_result)
        self.assertIs(result.push_skipped, True)
        self.assertIsNone(result.error)
        self.assertIs(g._gate_result_to_dict(result)["push_success"], False)

    def test_self_resume_no_push_never_calls_resilient_push(self):
        """7a self-resume (own active claim, same container+session) has its OWN
        resilient_push call site — it must honour no_push too (fix the class,
        not the instance).  How this goes red: only Step 9 was gated."""
        push_mock = self._patched([_claim("cA", "s-me", _NOW - timedelta(minutes=5))])
        with tempfile.TemporaryDirectory() as td:
            result = g.run_gate(
                _TRACK, "B", repo_path=Path(td), identity=_ME, now=_NOW, no_push=True
            )
        push_mock.assert_not_called()
        self.assertEqual(result.outcome, g.GateOutcome.PASSED)
        self.assertIsNotNone(result.own_claim)
        self.assertIs(result.push_skipped, True)

    def test_default_still_pushes(self):
        """Back-compat lock-in: run_gate WITHOUT no_push pushes exactly once and
        reports push_skipped False.  How this goes red: the default flipped."""
        push_mock = self._patched([])
        with tempfile.TemporaryDirectory() as td:
            result = g.run_gate(_TRACK, "B", repo_path=Path(td), identity=_ME, now=_NOW)
        push_mock.assert_called_once()
        self.assertIs(result.push_skipped, False)
        self.assertIs(g._gate_result_to_dict(result)["push_success"], True)


# ---------------------------------------------------------------------------
# Env-var semantics (shared parser, both CLIs)
# ---------------------------------------------------------------------------

class TestNoPushEnvSemantics(unittest.TestCase):

    def test_truthy_values_and_everything_else_off(self):
        """Truthy = 1 / true / yes, case-insensitive, whitespace-tolerant; anything
        else — 0 / false / no / empty / 2 / on / unset — is OFF.

        How this goes red: bool(str) / `is not None` / case-sensitive compare."""
        from lib.failure_handlers import COORDINATION_NO_PUSH_ENV, no_push_requested_by_env

        self.assertEqual(COORDINATION_NO_PUSH_ENV, _ENV)
        for v in ("1", "true", "TRUE", "True", "yes", "YES", " yes "):
            with self.subTest(value=v):
                self.assertTrue(no_push_requested_by_env({_ENV: v}))
        for v in ("0", "false", "no", "", " ", "2", "on", "y", "t", "-1"):
            with self.subTest(value=v):
                self.assertFalse(no_push_requested_by_env({_ENV: v}))
        self.assertFalse(no_push_requested_by_env({}))


# ---------------------------------------------------------------------------
# release_gate CLI — same class of leak (Step 5 push after a write)
# ---------------------------------------------------------------------------

class TestReleaseGateNoPushCli(unittest.TestCase):

    @staticmethod
    def _acquire_under_real_identity(repo: Path, raw_track: str) -> None:
        # CLI resolves identity via get_identity(); acquire under the REAL
        # container id so release-by-track can match it (as test_release_by_track).
        acquire_claim(derive_track_id(raw_track), "B", identity=get_identity(), repo_path=repo)

    def test_release_cli_flag_skips_push(self):
        """--no-push → released locally (status done in the local ref), push_skipped
        true / reason cli_flag / push_success false (not null), exit 0.

        How this goes red: argparse rejects --no-push (exit 2) — keys missing —
        push_success stays null — or the release write was skipped too."""
        repo = _fresh_repo()
        self._acquire_under_real_identity(repo, "carry-rel-a")
        rc, out, err = _run_release_cli(
            repo, "--raw-track-id", "carry-rel-a", "--no-push", env=_clean_env()
        )
        self.assertEqual(rc, 0, err[-500:])
        self.assertTrue(out["released"]["success"])
        self.assertIs(out["push_skipped"], True)
        self.assertEqual(out["push_skipped_reason"], "cli_flag")
        self.assertIs(out["push_success"], False)
        self.assertIsNone(out["hard_error"])
        self.assertEqual(
            [c.status for c in _local_track_claims(repo, "carry-rel-a")], ["done"]
        )

    def test_release_env_var_skips_push(self):
        """ARIA_COORDINATION_NO_PUSH=1 → reason env_var.

        How this goes red: release_gate._main() does not consult the env."""
        repo = _fresh_repo()
        self._acquire_under_real_identity(repo, "carry-rel-b")
        rc, out, err = _run_release_cli(
            repo, "--raw-track-id", "carry-rel-b", env=_clean_env(**{_ENV: "1"})
        )
        self.assertEqual(rc, 0, err[-500:])
        self.assertIs(out["push_skipped"], True)
        self.assertEqual(out["push_skipped_reason"], "env_var")
        self.assertIs(out["push_success"], False)

    def test_release_negative_control_attempts_push(self):
        """Neither channel (env removed) → push attempted: push_skipped false,
        reason null (the push itself fails fail-soft — no remote).

        How this goes red: push_skipped hard-coded true / unset env truthy."""
        repo = _fresh_repo()
        self._acquire_under_real_identity(repo, "carry-rel-c")
        rc, out, err = _run_release_cli(repo, "--raw-track-id", "carry-rel-c", env=_clean_env())
        self.assertIsNotNone(out, err[-500:])
        self.assertIs(out["push_skipped"], False)
        self.assertIsNone(out["push_skipped_reason"])

    def test_release_nothing_written_is_not_a_skip(self):
        """--no-push with nothing to release (claim_not_found, benign) → no push
        was due, so push_success stays null and push_skipped is false: "skipped"
        means "a push was due and suppressed", not "the flag was given".

        How this goes red: push_skipped derived from the flag alone."""
        repo = _fresh_repo()
        rc, out, err = _run_release_cli(
            repo, "--raw-track-id", "never-claimed", "--no-push", env=_clean_env()
        )
        self.assertEqual(rc, 0, err[-500:])
        self.assertTrue(out["released"]["benign"])
        self.assertIsNone(out["push_success"])
        self.assertIs(out["push_skipped"], False)
        self.assertIsNone(out["push_skipped_reason"])


if __name__ == "__main__":
    unittest.main()
