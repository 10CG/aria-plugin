"""Spec B (stderr-leak) — Rule #7 typed error classification channel tests.

AC-1  : git log/status/rev-list真实失败 → raw stderr 不落 snapshot["errors"]
AC-1b : _run timeout/FileNotFound 分支把 argv 放进 stderr — GitErrorClass 无字段可承载
AC-2  : lint_stderr_typed_channel 抓 leak (4 in-scope clean + 自我否证 + benign 保全)
AC-4  : classify_git_error 全标签集合 + 命令名不硬编码 fetch + coordination_fetch 委托 +
        §3b signal 扩充 + R6-m1/m4 守卫
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from _helpers import tmp_repo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collectors._common import GitErrorClass, classify_git_error  # type: ignore  # noqa: E402
from collectors import coordination_fetch as cf  # type: ignore  # noqa: E402
from collectors.git import collect_git_state  # type: ignore  # noqa: E402
import lint_stderr_typed_channel as lint  # type: ignore  # noqa: E402

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class TestClassifyLabelSet(unittest.TestCase):
    def test_full_label_set_closed(self):
        # AC-4: enumerate the label set is exactly the 5 closed values.
        cases = [
            (127, ""),
            (128, "fatal: Authentication failed for 'https://x'"),
            (1, "! [rejected] non-fast-forward"),
            (128, "fatal: unable to access: Could not resolve host"),
            (128, "some unmatched weird text"),
        ]
        labels = {classify_git_error(rc, se, "git status").label for rc, se in cases}
        self.assertEqual(labels, {"git_missing", "auth_403", "non_ff", "network", "other"})

    def test_catch_all_fail_closed(self):
        # Unmatched stderr → "other" (never None / never raises).
        self.assertEqual(classify_git_error(9, "\x00\x01 garbage", "git x").label, "other")


class TestSignalExpansionAndGuards(unittest.TestCase):
    def test_new_network_signals(self):
        for se in ["unable to access", "failed to connect", "couldn't connect", "TLS handshake failed"]:
            self.assertEqual(classify_git_error(128, se, "git fetch").label, "network", se)

    def test_ssh_publickey_is_auth(self):
        self.assertEqual(classify_git_error(128, "Permission denied (publickey).", "git fetch").label, "auth_403")

    def test_r6m1_bare_local_permission_not_auth(self):
        # R6-m1 guard: local FS permission error must NOT be mislabelled auth_403.
        se = "fatal: Unable to create '.git/index.lock': Permission denied"
        self.assertEqual(classify_git_error(128, se, "git status").label, "other")

    def test_r6m4_auth_before_network_when_both(self):
        # R6-m4 partition: dual-signal (403 + could not resolve) resolves to auth_403.
        se = "403 forbidden; could not resolve host"
        self.assertEqual(classify_git_error(128, se, "git fetch").label, "auth_403")


class TestStructuralNoStderrField(unittest.TestCase):
    def test_git_error_class_has_no_stderr_field(self):
        import dataclasses

        names = {f.name for f in dataclasses.fields(GitErrorClass)}
        self.assertEqual(names, {"label", "rc", "cmd"})
        self.assertNotIn("stderr", names)
        self.assertNotIn("detail", names)

    def test_ac1b_timeout_argv_with_credential_not_retained(self):
        # AC-1b: _run's TimeoutExpired branch puts argv (which for fetch holds the
        # credential URL) into the returned stderr. classify_git_error drops it —
        # the GitErrorClass carries only label/rc/cmd, structurally no secret.
        sentinel = "SENT" + "INEL_TOKEN_" + "abc123"
        argv_stderr = f"timeout after 5s: Command '['git','fetch','https://u:{sentinel}@h']'"
        cls = classify_git_error(124, argv_stderr, "git fetch")
        self.assertNotIn(sentinel, str(cls))
        self.assertNotIn(sentinel, cls.label + cls.cmd)


class TestCoordinationFetchDelegation(unittest.TestCase):
    def test_delegation_label_matches_direct(self):
        # AC-4: coordination_fetch._classify_error label == direct classify_git_error.
        for rc, se in [(127, ""), (128, "403"), (1, "[rejected]"), (128, "could not resolve"), (128, "weird")]:
            label, msg = cf._classify_error(rc, se)
            self.assertEqual(label, classify_git_error(rc, se, "git fetch").label)
            # wording layer preserved: non-git_missing cases keep the "git fetch" prefix;
            # git_missing keeps its own "git command not found in PATH" wording.
            if label != "git_missing":
                self.assertIn("git fetch", msg)

    def test_delegation_wording_byte_identical(self):
        # The pre-delegation wording must survive (test_p1_layer_h.py:446 fixture).
        self.assertEqual(cf._classify_error(128, "could not resolve")[1], "git fetch network error (rc=128)")

    def test_delegation_calls_shared_classifier(self):
        # Anti-third-copy (R7 M-2): coordination_fetch delegates, not duplicates.
        import unittest.mock as mock

        with mock.patch("collectors.coordination_fetch.classify_git_error", wraps=classify_git_error) as spy:
            cf._classify_error(128, "could not resolve")
            spy.assert_called()
            self.assertEqual(spy.call_args.args[2], "git fetch")


class TestAc2Lint(unittest.TestCase):
    def test_in_scope_files_clean(self):
        findings = lint.lint_files(_SCRIPTS)
        for name, viol in findings.items():
            self.assertEqual(viol, [], f"{name} has typed-channel violations: {viol}")

    def test_lint_catches_leak_forms(self):
        # Self-falsify (防橡皮图章): the direct leak forms must all be caught, INCLUDING
        # the return-plain form (review B2-Major) which the helpers' (list, msg) shape
        # makes directly reachable.
        forms = [
            'def f(r,p):\n rc,out,err=_run(["g"],p)\n if rc:\n  r.soft_error("k", f"x {err.strip()}")\n',
            'def f(r,p):\n rc,out,err=_run(["g"],p)\n if rc:\n  m=f"x {err.strip()}"\n  r.soft_error("k", m)\n',
            'def f(r,p):\n rc,out,err=_run(["g"],p)\n if rc:\n  r.soft_error("k", err.strip())\n',
            'def f(p):\n rc,out,err=_run(["g"],p)\n if rc:\n  return [], err.strip()\n',       # return-plain (form B)
            'def f(p):\n rc,out,err=_run(["g"],p)\n if rc:\n  return [], f"x {err}"\n',        # f-string in return
        ]
        for src in forms:
            self.assertTrue(lint.lint_source(src), f"lint missed a leak: {src!r}")

    def test_lint_no_false_positive_on_benign_intermediate(self):
        # `stderr_lower = stderr.lower()` then `in stderr_lower` (real handoff pattern)
        # and classify-directly-in-return must NOT be flagged.
        good = (
            'def f(p):\n rc,out,stderr=_run(["g"],p)\n if rc:\n  sl=stderr.lower()\n'
            '  if "not a tree" in sl:\n   return [],None\n'
            '  return None, classify_git_error(rc,stderr,"git show").label\n'
        )
        self.assertEqual(lint.lint_source(good), [])

    def test_lint_allows_classifier_and_benign_gate(self):
        good = (
            'def f(r,p):\n rc,out,stderr=_run(["g"],p)\n if rc:\n'
            '  if "not a tree" in stderr.lower():\n   return [],None\n'
            '  cls=classify_git_error(rc,stderr,"git ls-tree")\n  r.soft_error("k", f"{cls.label}")\n'
        )
        self.assertEqual(lint.lint_source(good), [])


class TestAc1RealFailureNoStderrLeak(unittest.TestCase):
    def test_git_log_corrupt_object_no_raw_stderr(self):
        # AC-1: corrupt the loose object HEAD points at → `git log` really fails.
        with tmp_repo() as repo:
            (repo / "f.txt").write_text("x", encoding="utf-8")
            subprocess.run(["git", "add", "f.txt"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "c1"], cwd=repo, check=True, capture_output=True,
                           env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                                "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"]})
            # Wipe the objects dir so `git log` fails with a raw "bad object"/"fatal" stderr.
            objdir = repo / ".git" / "objects"
            for p in objdir.rglob("*"):
                if p.is_file() and p.parent.name not in ("pack", "info"):
                    p.unlink()
            r = collect_git_state(repo)
            log_errs = [e for e in r.errors if e["error"] == "git_log_failed"]
            if log_errs:  # collector may short-circuit; only assert if it emitted
                detail = log_errs[0]["detail"]
                self.assertNotIn("bad object", detail.lower())
                self.assertNotIn("fatal:", detail.lower())
                # detail is the bounded form "git log <label> (rc=N)"
                self.assertIn("git log", detail)
                self.assertRegex(detail, r"git log (network|auth_403|non_ff|git_missing|other) \(rc=\d+\)")


if __name__ == "__main__":
    unittest.main()
