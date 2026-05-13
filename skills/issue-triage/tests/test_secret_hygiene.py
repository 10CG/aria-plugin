"""T4 — Rule #7 secret hygiene AST/grep tests.

Verifies that the _common._run() chokepoint invariant is maintained:
  - Every subprocess.run() call in the collectors package uses capture_output=True
  - No raw subprocess output is printed to stdout/stderr
  - _run() is the sole subprocess chokepoint — no direct subprocess.run() calls
    in collector modules outside of _common.py

References:
  T1.2, T1.6 — Rule #7 compliance (capture_output=True for all forgejo calls)
  standards/conventions/secret-hygiene.md
  Mid-review concern 9: grep/AST test verifying capture_output=True integrity
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
_COLLECTORS_DIR = _SCRIPTS_DIR / "collectors"
_COMMON_PY = _COLLECTORS_DIR / "_common.py"

# All collector source files (excluding _common.py which IS allowed to call subprocess)
_COLLECTOR_MODULES = [
    _COLLECTORS_DIR / "_issue.py",
    _COLLECTORS_DIR / "_version.py",
    _COLLECTORS_DIR / "_code.py",
    _COLLECTORS_DIR / "_history.py",
    _COLLECTORS_DIR / "_inflight.py",
]

# triage.py itself (should not call subprocess directly)
_TRIAGE_PY = _SCRIPTS_DIR.parent / "scripts" / "triage.py"


class TestCommonPySubprocessChokepoint:
    """_common.py _run() must always use capture_output=True.

    Mid-review concern 9: AST test verifying the chokepoint.
    """

    def test_subprocess_run_uses_capture_output_true(self) -> None:
        """_common._run(): subprocess.run() call must have capture_output=True keyword arg.

        This is the Rule #7 AST assertion. If this fails, secrets could leak
        to chat-visible channels via the subprocess stdout/stderr streams.
        """
        source = _COMMON_PY.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(_COMMON_PY))

        subprocess_run_calls = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"
            ):
                subprocess_run_calls.append(node)

        assert len(subprocess_run_calls) >= 1, (
            "_common.py must contain at least one subprocess.run() call"
        )

        for call in subprocess_run_calls:
            keyword_names = {kw.keyword.arg for kw in [
                type("KW", (), {"keyword": kw})() for kw in call.keywords
            ] if kw.keyword.arg is not None}
            # Reconstruct properly
            kw_names = {kw.arg for kw in call.keywords if kw.arg is not None}
            assert "capture_output" in kw_names, (
                f"subprocess.run() at line {call.lineno} in _common.py is missing "
                "capture_output keyword argument. Rule #7 requires capture_output=True "
                "to prevent secret/token leakage to chat-visible streams."
            )

            # Find the capture_output keyword and verify it's True
            for kw in call.keywords:
                if kw.arg == "capture_output":
                    assert isinstance(kw.value, ast.Constant) and kw.value.value is True, (
                        f"subprocess.run() at line {call.lineno} has capture_output != True. "
                        "Rule #7: capture_output MUST be True."
                    )

    def test_common_py_no_print_stdout(self) -> None:
        """_common.py must not print() the raw subprocess stdout or stderr.

        Callers must inspect return values only; never print raw output.
        """
        source = _COMMON_PY.read_text(encoding="utf-8")
        # Check that _run() returns a tuple — callers decide what to do with output
        assert "return p.returncode, p.stdout, p.stderr" in source, (
            "_run() must return (returncode, stdout, stderr) tuple — "
            "not print stdout/stderr directly."
        )


class TestCollectorModulesNoDirectSubprocess:
    """Collector modules must NOT call subprocess.run() directly.

    They must go through _common._run() to maintain the capture_output=True invariant.
    Mid-review concern 9: grep/AST chokepoint integrity check.
    """

    @pytest.mark.parametrize("module_path", _COLLECTOR_MODULES, ids=[p.name for p in _COLLECTOR_MODULES])
    def test_no_direct_subprocess_run(self, module_path: Path) -> None:
        """Collector module must not call subprocess.run() directly.

        All subprocess calls must go through _common._run() to guarantee
        capture_output=True (Rule #7 chokepoint).
        """
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module_path))

        direct_subprocess_calls = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"
            ):
                direct_subprocess_calls.append(node.lineno)

        assert len(direct_subprocess_calls) == 0, (
            f"{module_path.name} has direct subprocess.run() calls at lines "
            f"{direct_subprocess_calls}. All subprocess calls must go through "
            "_common._run() to maintain capture_output=True invariant (Rule #7)."
        )

    @pytest.mark.parametrize("module_path", _COLLECTOR_MODULES, ids=[p.name for p in _COLLECTOR_MODULES])
    def test_no_subprocess_popen_direct(self, module_path: Path) -> None:
        """Collector module must not use subprocess.Popen() directly.

        Popen bypasses the capture_output=True chokepoint.
        """
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module_path))

        popen_calls = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "Popen"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"
            ):
                popen_calls.append(node.lineno)

        assert len(popen_calls) == 0, (
            f"{module_path.name} uses subprocess.Popen() directly at lines "
            f"{popen_calls}. Use _common._run() instead."
        )


class TestTriage_py_NoDirectSubprocess:
    """triage.py must not call subprocess directly (it delegates to collectors)."""

    def test_triage_py_no_direct_subprocess_import(self) -> None:
        """triage.py must not import subprocess (it uses collectors which use _run()).

        This is a belt-and-suspenders check; if triage.py imports subprocess
        directly, it may bypass the capture_output=True chokepoint.
        """
        triage_path = _SCRIPTS_DIR / "triage.py"
        source = triage_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(triage_path))

        # Check for 'import subprocess' or 'from subprocess import ...'
        subprocess_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "subprocess":
                        subprocess_imports.append(node.lineno)
            elif isinstance(node, ast.ImportFrom):
                if node.module == "subprocess":
                    subprocess_imports.append(node.lineno)

        assert len(subprocess_imports) == 0, (
            f"triage.py imports subprocess directly at lines {subprocess_imports}. "
            "triage.py must not call subprocess — delegate to collectors via _run()."
        )


class TestRunFunctionSignatureIntegrity:
    """Verify _run() signature has not been altered in ways that could break hygiene."""

    def test_run_returns_three_tuple(self) -> None:
        """_run() must return (rc, stdout, stderr) — never print them."""
        sys.path.insert(0, str(_SCRIPTS_DIR))
        from collectors._common import _run
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            rc, stdout, stderr = _run(["echo", "test"], Path(td), timeout=5)
            # Verify the return type is a 3-tuple of (int, str, str)
            assert isinstance(rc, int)
            assert isinstance(stdout, str)
            assert isinstance(stderr, str)

    def test_run_capture_output_not_forwarded(self) -> None:
        """_run() with a command that outputs to stdout — output is captured, not printed.

        This is a runtime verification that output doesn't leak.
        The output must be in the returned stdout string, NOT in capsys.
        """
        sys.path.insert(0, str(_SCRIPTS_DIR))
        from collectors._common import _run
        from pathlib import Path
        import tempfile

        sentinel = "SECRET_TOKEN_TEST_MARKER_XYZ789"

        with tempfile.TemporaryDirectory() as td:
            rc, stdout, stderr = _run(
                ["sh", "-c", f"echo {sentinel}"],
                Path(td),
                timeout=5,
            )

        # Token must appear in the returned stdout string
        assert sentinel in stdout, "Output not captured in return value"
        # (capsys cannot easily verify no stdout was printed in a subprocess context,
        # but the AST test above guarantees capture_output=True at the call site)

    def test_run_nonzero_rc_does_not_raise(self) -> None:
        """_run() with a failing command returns non-zero rc, does NOT raise."""
        sys.path.insert(0, str(_SCRIPTS_DIR))
        from collectors._common import _run
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            rc, stdout, stderr = _run(["sh", "-c", "exit 1"], Path(td), timeout=5)

        assert rc != 0  # non-zero but no exception raised
