#!/usr/bin/env python3
"""Spec B (stderr-leak) AC-2 — best-effort lint for the Rule #7 typed channel.

Asserts that in the IN-SCOPE collector files, the stderr value returned by ``_run``
(the third element of its ``(rc, stdout, stderr)`` tuple) never flows into an emitted
message — it may only be consumed by ``classify_git_error`` or a benign-gate string
test (``.lower()`` / ``.strip()`` producing a bool that is not emitted).

**Best-effort, NOT a sound completeness gate** (Spec B v5 option B): the authoritative
completeness gate is the Task 3.1b code-review of the §2 site list. This lint is a
second mechanical net. Known gaps (documented, out of scope): ``return _run(...)``
whole-tuple passthrough (issue_scan.py) and already-structured ``reason``-field
classifiers (multi_remote.py) are not scanned.

The real STRUCTURAL guarantee is ``GitErrorClass`` having no stderr field — this lint
just catches an in-scope author re-introducing a raw-stderr emit before review.
"""

from __future__ import annotations

import ast
from pathlib import Path

# The 4 files this Spec refactors. issue_scan.py / multi_remote.py are out of scope.
IN_SCOPE = ("git.py", "sync.py", "handoff_multibranch.py", "handoff_worktrees.py")

_CLASSIFIER = "classify_git_error"


def _stderr_vars_of_run(tree: ast.AST) -> dict[str, ast.FunctionDef]:
    """Map each `x, y, z = _run(...)` third-target name → the function it lives in."""
    out: dict[str, ast.FunctionDef] = {}
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(func):
            if not isinstance(node, ast.Assign):
                continue
            val = node.value
            if not (isinstance(val, ast.Call) and _is_run_call(val)):
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Tuple) and len(tgt.elts) == 3:
                    third = tgt.elts[2]
                    if isinstance(third, ast.Name):
                        out[third.id] = func  # type: ignore[assignment]
    return out


def _is_run_call(call: ast.Call) -> bool:
    f = call.func
    return (isinstance(f, ast.Name) and f.id == "_run") or (
        isinstance(f, ast.Attribute) and f.attr == "_run"
    )


def _call_name(call: ast.Call) -> str:
    f = call.func
    return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")


def lint_source(source: str) -> list[str]:
    """Return a list of violation messages (empty = clean).

    Rule: a Load of the stderr var (or a `.strip()`/`.lower()` derivative of it) is a
    VIOLATION iff it has an EMITTING ancestor within its function — a JoinedStr
    (f-string), a Call to ``soft_error``, or a ``return <value>`` statement (the
    `return [], err.strip()` helper form, which the in-scope helpers' `(list, msg)`
    shape makes directly reachable — review B2-Major). It is ALLOWED when it is an
    argument to ``classify_git_error`` or used only in a bool test (membership/compare,
    e.g. the benign-gate ``if "x" in stderr.lower()``), neither of which passes under
    such an ancestor.

    **Known gaps (best-effort, NOT sound — Spec B v5 option B)**: a stderr value first
    assigned to a plain intermediate variable and THEN emitted (``m = err.strip();
    soft_error(k, m)``), or routed through a list/dict then emitted, escapes this
    (single-level) tracer — catching those needs full multi-level taint tracking. The
    authoritative completeness gate is the Task 3.1b code-review; this lint is a second
    mechanical net for the common/direct forms, not a proof.
    """
    tree = ast.parse(source)
    stderr_vars = _stderr_vars_of_run(tree)
    violations: list[str] = []

    for var, func in stderr_vars.items():
        parents = {id(child): parent for parent in ast.walk(func) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(func):
            if not (isinstance(node, ast.Name) and node.id == var and isinstance(node.ctx, ast.Load)):
                continue
            # Walk ancestors: if an emitting context wraps this use → leak.
            cur: ast.AST | None = node
            emitting = False
            while cur is not None:
                if isinstance(cur, (ast.JoinedStr, ast.Return)):
                    emitting = True
                    break
                if isinstance(cur, ast.Call) and _call_name(cur) == "soft_error":
                    emitting = True
                    break
                # Stop at the classifier boundary: once the stderr value is inside a
                # classify_git_error(...) call it is safely consumed — don't keep
                # walking up into any enclosing return/assignment.
                if isinstance(cur, ast.Call) and _call_name(cur) == _CLASSIFIER:
                    break
                cur = parents.get(id(cur))
            if emitting:
                violations.append(
                    f"{func.name}: stderr var '{var}' (from _run) reaches an emitting "
                    f"context (f-string / soft_error) at line {node.lineno} — route it "
                    f"through {_CLASSIFIER}() instead"
                )
    return violations


def lint_files(scripts_dir: Path) -> dict[str, list[str]]:
    """Lint all in-scope collector files under scripts_dir/collectors/."""
    result: dict[str, list[str]] = {}
    for name in IN_SCOPE:
        path = scripts_dir / "collectors" / name
        result[name] = lint_source(path.read_text(encoding="utf-8"))
    return result


if __name__ == "__main__":
    import sys

    here = Path(__file__).resolve().parent
    findings = lint_files(here)
    bad = {f: v for f, v in findings.items() if v}
    for f, vs in bad.items():
        for v in vs:
            print(f"{f}: {v}")
    sys.exit(1 if bad else 0)
