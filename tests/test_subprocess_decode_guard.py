"""aria-plugin #147 — UnicodeDecodeError 类级守卫 (repo-wide AST test).

不变量: 生产代码 (repo 全量 *.py, 排除 tests/examples/__pycache__/.git) 里
每一个**文本模式** subprocess 调用点 — ``text=True`` / ``universal_newlines=True``
(旧别名, 语义同) / 裸 ``encoding=`` kwarg (单给也开启文本模式+严格解码) —
必须满足二者其一:

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

范围史: 首版只扫 skills/** 且只认 text=True 字面 — superseded spec
subprocess-decode-hardening (archive/2026-08-21) residual_delta 点名后扩为
repo 全量 + 三轴谓词 (universal_newlines / 裸 encoding= 两条旧别名逃逸路径
在扩轴时语料零命中, 本测试使其保持为零)。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# except 子句里任何一个这些名字都能接住 UnicodeDecodeError。
_CATCHING_NAMES = {
    "ValueError",
    "UnicodeError",
    "UnicodeDecodeError",
    "Exception",
    "BaseException",
}

# 生产面之外的目录段 (测试自己裸抛可接受; examples 是教学示例非生产)。
_EXCLUDED_PARTS = {"tests", "test", "examples", "__pycache__", ".git", "node_modules"}


_SUBPROCESS_FUNCS = {"run", "Popen", "check_output", "check_call", "call"}


def _is_subprocess_call(node: ast.Call) -> bool:
    """subprocess.run(...) / run(...) 形态 (Attribute 或裸 Name 均认)."""
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr in _SUBPROCESS_FUNCS
    if isinstance(f, ast.Name):
        return f.id in _SUBPROCESS_FUNCS
    return False


def _is_text_mode_run(node: ast.Call) -> bool:
    """True for a SUBPROCESS call in TEXT (self-decoding) mode:
    text=True / universal_newlines=True (legacy alias) / bare non-None
    encoding= kwarg (implies text mode with STRICT decode unless errors= set).
    Scoped to subprocess-shaped calls — open()/read_text() 的 encoding= 是另一
    个类 (读仓内文件, 严格解码常为期望的 fail-loud), 不在 #147 面内."""
    if not _is_subprocess_call(node):
        return False
    for kw in node.keywords:
        if not isinstance(kw, ast.keyword):
            continue
        if kw.arg in ("text", "universal_newlines"):
            if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                return True
        elif kw.arg == "encoding":
            if not (isinstance(kw.value, ast.Constant) and kw.value.value is None):
                return True
    return False


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
        for p in REPO_ROOT.rglob("*.py")
        if not (_EXCLUDED_PARTS & set(p.relative_to(REPO_ROOT).parts))
    )


def test_every_text_true_run_survives_undecodable_bytes() -> None:
    offenders: list[str] = []
    for path in _production_python_files():
        src = path.read_text(encoding="utf-8", errors="replace")
        if not any(k in src for k in ("text=True", "universal_newlines=True", "encoding=")):
            continue
        tree = ast.parse(src, filename=str(path))
        parents: dict = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _is_text_mode_run(node)):
                continue
            if _has_errors_kwarg(node):
                continue
            if _guarded_by_valueerror_family(node, parents):
                continue
            rel = path.relative_to(REPO_ROOT)
            offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        "text-mode call site(s) where UnicodeDecodeError (a ValueError, NOT an "
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
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_text_mode_run(n)]
    assert calls, "fixture must contain a text=True call"
    assert not _has_errors_kwarg(calls[0])
    assert not _guarded_by_valueerror_family(calls[0], parents), (
        "guard failed to flag an (OSError, TimeoutExpired)-only tuple"
    )


def test_guard_flags_legacy_alias_and_bare_encoding() -> None:
    """新轴拒绝能力: universal_newlines=True 与裸 encoding= 均属文本模式."""
    for src, why in (
        ("import subprocess\nsubprocess.run(['x'], universal_newlines=True)\n", "universal_newlines"),
        ("import subprocess\nsubprocess.run(['x'], encoding='utf-8')\n", "bare encoding="),
        ("import subprocess\nsubprocess.run(['x'], capture_output=True, encoding='utf-8', errors='replace')\n", None),
        ("import subprocess\nsubprocess.run(['x'], encoding=None)\n", None),
    ):
        tree = ast.parse(src)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        flagged = any(_is_text_mode_run(c) and not _has_errors_kwarg(c) for c in calls)
        if why:
            assert flagged, f"guard failed to flag {why}"
        else:
            assert not flagged, f"guard wrongly flags a safe/non-text site: {src!r}"


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
        call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_text_mode_run(n))
        ok = _has_errors_kwarg(call) or _guarded_by_valueerror_family(call, parents)
        assert ok, f"guard wrongly flags a safe site ({why})"
