"""Tests for collectors._common subprocess wrapper (_run).

Primary coverage target: #61 fix (Windows CJK locale crash). The `_run` wrapper
must produce UTF-8-decoded stdout regardless of OS locale, never raising
UnicodeDecodeError to the caller.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from collectors._common import _run


class TestRunUtf8Encoding(unittest.TestCase):
    """#61 regression — _run must use UTF-8 + errors='replace'."""

    def test_utf8_cjk_roundtrip(self):
        # CJK characters must survive subprocess roundtrip (the original
        # crash was on git log output containing Chinese commit messages).
        rc, stdout, stderr = _run(
            [sys.executable, "-c", "print('中文测试')"], Path(".")
        )
        self.assertEqual(rc, 0)
        self.assertIn("中文测试", stdout)
        self.assertEqual(stderr, "")

    def test_utf8_emoji_roundtrip(self):
        # Emoji must survive (aria-standards git-commit.md 双语规范 allows
        # emoji in commit subjects).
        rc, stdout, _ = _run(
            [sys.executable, "-c", "print('feat: ship 🚀')"], Path(".")
        )
        self.assertEqual(rc, 0)
        self.assertIn("🚀", stdout)

    def test_utf8_mixed_ascii_cjk_emoji(self):
        # Realistic git log subject form
        rc, stdout, _ = _run(
            [
                sys.executable,
                "-c",
                "print('feat(deploy): 部署 M5 carryover ✅')",
            ],
            Path("."),
        )
        self.assertEqual(rc, 0)
        self.assertIn("部署", stdout)
        self.assertIn("✅", stdout)
        self.assertIn("feat(deploy)", stdout)

    def test_nonzero_exit_still_returns_cleanly(self):
        # Existing contract: non-zero rc must NOT raise
        rc, _, stderr = _run(
            [sys.executable, "-c", "import sys; sys.exit(7)"], Path(".")
        )
        self.assertEqual(rc, 7)

    def test_invalid_bytes_handled_via_errors_replace(self):
        # If a subprocess somehow emits non-UTF-8 bytes (legacy tooling),
        # errors="replace" must soften — no exception escapes _run.
        rc, stdout, _ = _run(
            [
                sys.executable,
                "-c",
                # Write raw bytes that are NOT valid UTF-8 to stdout (0xff is
                # an invalid UTF-8 start byte). With errors='replace' the
                # subprocess wrapper substitutes U+FFFD.
                "import sys; sys.stdout.buffer.write(b'\\xff\\xfeOK\\n')",
            ],
            Path("."),
        )
        self.assertEqual(rc, 0)
        # Both bytes 0xff and 0xfe replaced with U+FFFD (replacement char);
        # "OK" survives as-is
        self.assertIn("OK", stdout)
        # Critical invariant: no UnicodeDecodeError raised — we got here

    def test_command_not_found_returns_127(self):
        # Existing contract preserved
        rc, _, stderr = _run(
            ["this-command-definitely-does-not-exist-xyz123"], Path(".")
        )
        self.assertEqual(rc, 127)
        self.assertIn("command not found", stderr)


class TestRunLocaleHardening(unittest.TestCase):
    """#143 (v1.46.1) — _run forces LC_ALL=C so git emits English diagnostics,
    making collectors' English stderr-substring matching locale-robust."""

    def test_run_injects_lc_all_c_env(self):
        """_run must pass env with LC_ALL=C, preserving os.environ + the 6 kwargs.

        Falsifiable regardless of host locale (mock intercepts before dispatch) —
        closes the 'C-locale CI makes 803-green circular' gap (post_spec qa-major).
        """
        captured: dict = {}

        class _FakeCompleted:
            returncode = 0
            stdout = ""
            stderr = ""

        def _fake_run(*_args, **kwargs):
            captured.update(kwargs)
            return _FakeCompleted()

        with mock.patch("collectors._common.subprocess.run", side_effect=_fake_run):
            _run(["git", "status"], Path("."))

        env = captured.get("env")
        self.assertIsNotNone(env, "_run must pass an env= kwarg")
        assert env is not None  # type-narrow (static checkers don't model assertIsNotNone)
        self.assertEqual(env.get("LC_ALL"), "C", "LC_ALL must be forced to C")
        # os.environ preserved (superset) — PATH/HOME etc. not clobbered
        for k in os.environ:
            self.assertIn(k, env, f"os.environ key {k!r} must be preserved")
        # the 6 pre-existing kwargs preserved (no regression on #61/#131 contracts)
        self.assertIs(captured.get("capture_output"), True)
        self.assertIs(captured.get("text"), True)
        self.assertEqual(captured.get("encoding"), "utf-8")
        self.assertEqual(captured.get("errors"), "replace")
        self.assertIs(captured.get("check"), False)
        self.assertIn("timeout", captured)

    def test_lc_all_c_does_not_mangle_cjk_git_log(self):
        """Real git on the ACTUAL git.py:181 path (`git log --oneline`): a CJK +
        emoji commit subject survives LC_ALL=C byte-for-byte (locale governs git's
        own diagnostics, NOT commit-message passthrough). Isolated tmpdir fixture.
        """
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            subj = "测试 中文 commit 主题 🚀 → end"
            for setup in (
                ["git", "init", "-q"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "--allow-empty", "-q", "-m", subj],
            ):
                subprocess.run(setup, cwd=repo, check=True, capture_output=True)
            rc, stdout, _ = _run(
                ["git", "log", "--oneline", "--no-decorate", "-1"], repo
            )
        self.assertEqual(rc, 0)
        # Full subject (CJK + emoji + arrow + ascii) must survive LC_ALL=C
        # byte-for-byte — matches the proposal's "CJK + em-dash" byte-identity claim.
        self.assertIn(subj, stdout, "full CJK+emoji+arrow subject must survive LC_ALL=C")


class TestNonInteractiveGitContract(unittest.TestCase):
    """Task 3.4 (main spec stale-refs-false-parity) — git can never block on a
    prompt. Asserts the MECHANISM (env vars + stdin wiring), not just that some
    command happened to succeed: in this test environment no git command would
    prompt anyway, so a passing end-to-end call proves nothing on its own
    (memory: `noop_in_test_env_hardening_needs_mechanism_assertion`).
    """

    def test_terminal_prompt_disabled(self):
        from collectors._common import _noninteractive_git_env

        self.assertEqual(_noninteractive_git_env(5)["GIT_TERMINAL_PROMPT"], "0")

    def test_locale_hardening_preserved(self):
        """#143 must survive task 3.4's rewrite of the env construction."""
        from collectors._common import _noninteractive_git_env

        self.assertEqual(_noninteractive_git_env(5)["LC_ALL"], "C")

    def test_ssh_batchmode_and_connect_timeout(self):
        from collectors._common import _noninteractive_git_env

        cmd = _noninteractive_git_env(5)["GIT_SSH_COMMAND"]
        self.assertIn("BatchMode=yes", cmd)
        self.assertIn("ConnectTimeout=4", cmd)

    def test_connect_timeout_capped_and_below_subprocess_deadline(self):
        """ConnectTimeout must stay STRICTLY below the subprocess timeout, else the
        two expire together, TimeoutExpired wins, and ssh's classifiable failure
        never surfaces (regression-locks a real bug: `min(timeout, 10)` made the
        real-git test below return rc=124).

        ⚠️ Assert on the GIT_SSH_COMMAND VALUE, never on the env dict — a failed
        assertion renders its subject, and this dict is the process environment
        (Rule #7: it carries live tokens).
        """
        from collectors._common import _noninteractive_git_env

        def ssh_cmd(t: int) -> str:
            return _noninteractive_git_env(t)["GIT_SSH_COMMAND"]

        self.assertIn("ConnectTimeout=10", ssh_cmd(600))
        self.assertIn("ConnectTimeout=9", ssh_cmd(10))
        self.assertIn("ConnectTimeout=1", ssh_cmd(0))
        self.assertIn("ConnectTimeout=1", ssh_cmd(-3))

    def test_existing_ssh_command_not_clobbered(self):
        """An adopter's custom ssh wrapper (proxy jump / alternate identity) wins —
        clobbering it would break the fetch, a louder failure than a hang."""
        from collectors._common import _noninteractive_git_env

        with mock.patch.dict(os.environ, {"GIT_SSH_COMMAND": "ssh -J bastion"}):
            self.assertEqual(_noninteractive_git_env(5)["GIT_SSH_COMMAND"], "ssh -J bastion")

    def test_run_passes_devnull_stdin_and_hardened_env(self):
        """`capture_output=True` governs stdout/stderr only — without an explicit
        `stdin=DEVNULL` the child inherits this process's stdin and can wait on it."""
        captured = {}

        class _FakeCompleted:
            returncode = 0
            stdout = ""
            stderr = ""

        def _fake_run(cmd, **kwargs):
            captured.update(kwargs)
            return _FakeCompleted()

        with mock.patch("subprocess.run", side_effect=_fake_run):
            _run(["git", "status"], Path("."), timeout=5)

        # Rule #7: pull the two values out FIRST — asserting against
        # `captured["env"]` itself would render the whole live environment
        # (tokens included) into the failure diff.
        prompt = captured["env"]["GIT_TERMINAL_PROMPT"]
        ssh_command = captured["env"]["GIT_SSH_COMMAND"]
        self.assertEqual(captured["stdin"], subprocess.DEVNULL)
        self.assertEqual(prompt, "0")
        self.assertIn("BatchMode=yes", ssh_command)

    def test_real_git_does_not_hang_on_unreachable_ssh_remote(self):
        """End-to-end in the REAL exec environment (memory:
        `defensive_fix_end2end_in_real_exec_env`): a genuine git call against an
        unroutable SSH host must return a non-zero rc well inside the deadline
        rather than sitting on a host-key/passphrase prompt. Uses TEST-NET-1
        (RFC 5737, guaranteed unroutable) so the box's own network config cannot
        turn this into a real connection."""
        with tempfile.TemporaryDirectory() as td:
            rc, _, _ = _run(
                ["git", "ls-remote", "ssh://git@192.0.2.1/x.git"], Path(td), timeout=6
            )
        self.assertNotEqual(rc, 0)
        self.assertNotEqual(rc, 124, "hit the subprocess deadline = it hung, not failed fast")


if __name__ == "__main__":
    unittest.main()
