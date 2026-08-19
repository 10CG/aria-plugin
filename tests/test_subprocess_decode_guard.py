"""aria-plugin #147 — UnicodeDecodeError 类级守卫 (repo-wide AST test).

不变量: 生产代码 (skills/**, 排除 tests/ 与 examples/) 里每一个
``subprocess.run(..., text=True)`` 调用点必须满足二者其一:

  (a) 调用自带 ``errors=`` 关键字 (如 ``errors="replace"`` — 解码永不抛,
      canonical 先例: state-scanner/lib/coordination_ref.py #61); 或
  (b) 被一个能接住 ValueError 族的 try 包住 (except 含 ValueError /
      UnicodeError / UnicodeDecodeError / Exception / bare except)。

为什么: ``text=True`` 让 subprocess 自己解码, 解码失败抛 UnicodeDecodeError
—— 它是 ValueError 族而非 OSError 族 (``issubclass(UnicodeDecodeError,
OSError) == False``), 直觉写下的 ``except (OSError, TimeoutExpired)`` 元组
接不住, 异常从底下穿过 (#147; empirical-traps.md 坑 #4)。本测试让**新写的**
调用点在犯同款直觉错误时立刻红 — 修类, 不只修实例。

修复指引 (测试红时): 首选给调用加 ``errors="replace"``; 若该点确需区分解码
失败, 再在 except 元组补 ``UnicodeDecodeError``。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SKILLS_DIR = REPO_ROOT / "skills"

# except 子句里任何一个这些名字都能接住 UnicodeDecodeError。
_CATCHING_NAMES = {
    "ValueError",
    "UnicodeError",
    "UnicodeDecodeError",
    "Exception",
    "BaseException",
}

# 生产面之外的目录段 (测试自己裸抛可接受; examples 是教学示例非生产)。
_EXCLUDED_PARTS = {"tests", "test", "examples", "__pycache__"}


def _is_text_true_run(node: ast.Call) -> bool:
    """True for any call carrying keyword text=True (subprocess.run/Popen 形态)."""
    return any(
        isinstance(kw, ast.keyword)
        and kw.arg == "text"
        and isinstance(kw.value, ast.Constant)
        and kw.value.value is True
        for kw in node.keywords
    )


def _has_errors_kwarg(node: ast.Call) -> bool:
    return any(isinstance(kw, ast.keyword) and kw.arg == "errors" for kw in node.keywords)


def _handler_names(handler: ast.ExceptHandler) -> set[str]:
    if handler.type is None:  # bare except
        return {"BARE"}
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return {ast.unparse(t).split(".")[-1] for t in types}


def _guarded_by_valueerror_family(node: ast.Call, parents: dict) -> bool:
    """Climb ancestors: is `node` inside a try-body whose handlers catch the family?"""
    n: ast.AST = node
    while n in parents:
        par = parents[n]
        if isinstance(par, ast.Try) and n in par.body:
            names: set[str] = set()
            for h in par.handlers:
                names |= _handler_names(h)
            if names & (_CATCHING_NAMES | {"BARE"}):
                return True
        n = par
    return False


def _production_python_files() -> list[Path]:
    return sorted(
        p
        for p in SKILLS_DIR.rglob("*.py")
        if not (_EXCLUDED_PARTS & set(p.parts))
    )


def test_every_text_true_run_survives_undecodable_bytes() -> None:
    offenders: list[str] = []
    for path in _production_python_files():
        src = path.read_text(encoding="utf-8", errors="replace")
        if "text=True" not in src:
            continue
        tree = ast.parse(src, filename=str(path))
        parents: dict = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _is_text_true_run(node)):
                continue
            if _has_errors_kwarg(node):
                continue
            if _guarded_by_valueerror_family(node, parents):
                continue
            rel = path.relative_to(REPO_ROOT)
            offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        "text=True call site(s) where UnicodeDecodeError (a ValueError, NOT an "
        "OSError) escapes uncaught — add errors=\"replace\" to the call, or catch "
        "the ValueError family in the enclosing try (#147):\n  "
        + "\n  ".join(offenders)
    )


def test_guard_rejects_bad_implementation() -> None:
    """拒绝能力自证: 坏实现 (OSError 元组 + 无 errors=) 必须被本守卫抓住."""
    bad = (
        "import subprocess\n"
        "try:\n"
        "    subprocess.run(['x'], capture_output=True, text=True)\n"
        "except (OSError, subprocess.TimeoutExpired):\n"
        "    pass\n"
    )
    tree = ast.parse(bad)
    parents: dict = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_text_true_run(n)]
    assert calls, "fixture must contain a text=True call"
    assert not _has_errors_kwarg(calls[0])
    assert not _guarded_by_valueerror_family(calls[0], parents), (
        "guard failed to flag an (OSError, TimeoutExpired)-only tuple"
    )


def test_guard_accepts_good_implementations() -> None:
    """好实现两式 (errors= kwarg / ValueError 族 except) 必须放行."""
    good_errors_kw = "import subprocess\nsubprocess.run(['x'], text=True, errors='replace')\n"
    good_except = (
        "import subprocess\n"
        "try:\n"
        "    subprocess.run(['x'], text=True)\n"
        "except (OSError, ValueError):\n"
        "    pass\n"
    )
    for src, why in ((good_errors_kw, "errors kwarg"), (good_except, "ValueError except")):
        tree = ast.parse(src)
        parents: dict = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_text_true_run(n))
        ok = _has_errors_kwarg(call) or _guarded_by_valueerror_family(call, parents)
        assert ok, f"guard wrongly flags a safe site ({why})"
