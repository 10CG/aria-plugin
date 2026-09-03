#!/usr/bin/env python3
"""linked-issue-field-availability probe — check mode + `--emit-arg` mode.

Two independent modes, selected by whether `--emit-arg` is given:

check mode (default):
  Scans `<root>/openspec/changes/**/proposal.md` (never `archive/`) and runs
  `extract_linked_issue_field` (imported from
  `aria/skills/state-scanner/lib/linked_issue_field.py`, the sole SOT for the
  E0-E6 rules) over each file. Any proposal whose verdict is not `OK` is a
  violation unless its `openspec/changes/<slug>` directory is listed in the
  `--grandfathered` allowlist file. The allowlist is also checked for staleness
  (entries that no longer point at a non-compliant, in-scope proposal) so it
  cannot decay into a permanent exemption list.

  Exit 0 with `OK (<n> 份在范围内, <m> 条在册)` when everything in scope is
  either compliant or grandfathered and no allowlist entry is stale.
  Exit 1 with `FAIL <k> 项` followed by one line per violation/stale entry
  otherwise. Missing/empty scope, or a failed import of the SOT module,
  degrades to `##SKIP##` (exit 0) rather than a false pass or false fail.

  Fail-CLOSED surfaces (v1.68.1 / v1.68.2): anything in scope that cannot be
  read or enumerated is a violation line, never a silent omission —
  `<rel>:- UNREADABLE <Exc> (无法读取, 按违规计)` for a proposal.md that
  cannot be read, `<dir>:- UNREADABLE <Exc> (目录无法枚举, 按违规计)` for a
  directory under `openspec/changes/` that cannot be listed (os.walk onerror),
  and `<dir>:- SYMLINK 目录不跟随 (按违规计)` for a symlinked directory
  (symlinks are not followed; a symlinked slug would otherwise vanish from the
  scope). An unlistable `openspec/changes/` itself is FAIL, not `##SKIP##`.
  Allowlist entries are normalized with `posixpath.normpath` (`./`, `//`,
  `/./`, trailing `/`, `a/../b`) and the file is read as `utf-8-sig` (BOM
  tolerated); an unlistable `openspec/archive/` makes the stale guard fall
  back to (a) with a stderr warning instead of a traceback.

`--emit-arg <file>` mode:
  Reads ONE file and prints (no trailing newline) the E6 `--linked-issue`
  argument value for it — the mechanical host for the proposal's E6 four-cell
  table. Only an `OK`, non-sentinel verdict produces output; the other three
  cells print nothing. A read failure or an unavailable SOT module prints
  nothing to stdout, writes one line to stderr, and exits 2 (distinct from
  check mode's exit 1, since this is not a "found a violation" outcome).
  The argument is machine-consumed, so it is written verbatim: if stdout's
  encoding cannot represent it (e.g. `PYTHONIOENCODING=ascii` with a non-ASCII
  repo slug) the probe fails LOUDLY (stderr + exit 2, empty stdout) instead of
  rewriting the argument with `?` (E6: 探针自身失败 ⇒ 非 0; the check-mode
  `errors="replace"` degradation is deliberately NOT applied here).

`--emit-arg` and `--grandfathered` are mutually exclusive (argparse enforces
this, exiting 2 on stderr).

Scope-selection / allowlist policy live entirely in THIS file — the imported
`lib.linked_issue_field` module carries none of it, only the E0-E6 rules
themselves.
"""

from __future__ import annotations

import argparse
import os
import posixpath
import sys
from pathlib import Path

# Sibling-skill-import style: state-scanner's skill root goes on sys.path so
# that `lib` resolves to the skill-root package (lib/collision.py uses relative
# imports and must be imported as a package member). This is the deliberate
# mirror image of coordination_probe.py:80-85, which inserts scripts/lib and
# imports a bare module — that script needs scripts/lib/runtime_probe.py, this
# one needs the skill-root-level lib/ package. Rationale + both measured
# outcomes: openspec/changes/linked-issue-field-availability/proposal.md §4
# 「归一的导入方式」.
_SS = str(Path(__file__).resolve().parent.parent)
if _SS not in sys.path:
    sys.path.insert(0, _SS)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="linked-issue-field-availability E0-E6 probe (check mode + --emit-arg mode)"
    )
    parser.add_argument("root", nargs="?", default=None)  # check mode only; None -> "." 
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--grandfathered", default=None)
    mode.add_argument("--emit-arg", default=None)
    return parser


def _normalize_entry(raw: str) -> str:
    """Allowlist entry canonical form: strip + `posixpath.normpath`.

    Both the violation check and the stale guard compare against this form, so
    `openspec/changes/foo/`, `./openspec/changes/foo`, `openspec/changes/./foo`,
    `openspec//changes/foo` and `openspec/changes/foo/.` are all the same entry
    as `openspec/changes/foo` (pre_merge R1 code-reviewer: the two sites used
    to normalize differently; R2/R3 4a675f17: the prefix/suffix-only
    normalization left `./` infixes uncollapsed, so such an entry counted as
    在册 yet never exempted anything). Duplicates are collapsed (first
    occurrence wins). Empty / `.` entries normalize to "" and are dropped.
    """
    e = raw.strip()
    if not e:
        return ""
    e = posixpath.normpath(e)
    return "" if e == "." else e


def _enumerate_scope(changes: Path) -> tuple[list[Path], list[tuple[str, str]]]:
    """Walk `openspec/changes/` for proposal.md files — fail-CLOSED.

    Returns `(files, problems)`. `problems` are `(path, detail)` pairs for every
    directory that could not be listed (os.walk `onerror`) and every symlinked
    directory (not followed). `Path.rglob` swallowed both silently, so an
    unreadable or symlinked slug simply vanished from the scope and the probe
    printed `OK` — fail-OPEN by omission (pre_merge R3 4a675f17-(i)).
    """
    files: list[Path] = []
    problems: list[tuple[str, str]] = []

    def _onerror(exc: OSError) -> None:
        problems.append((str(exc.filename or changes), f"UNREADABLE {exc.__class__.__name__} (目录无法枚举, 按违规计)"))

    for dirpath, dirnames, filenames in os.walk(changes, onerror=_onerror, followlinks=False):
        for d in list(dirnames):
            full = Path(dirpath) / d
            if full.is_symlink():
                problems.append((str(full), "SYMLINK 目录不跟随 (按违规计)"))
            elif d == "proposal.md":
                # a directory named proposal.md: unreadable-as-file, reported not skipped
                problems.append((str(full), "UNREADABLE IsADirectoryError (无法读取, 按违规计)"))
                dirnames.remove(d)
        dirnames.sort()
        if "proposal.md" in filenames:
            files.append(Path(dirpath) / "proposal.md")
    return sorted(files), problems


def _run_check(root: Path, grandfathered_arg, extract_linked_issue_field) -> int:
    root = root.resolve()
    changes = root / "openspec" / "changes"
    scope, scope_problems = _enumerate_scope(changes) if changes.is_dir() else ([], [])
    if not scope and not scope_problems:
        print("##SKIP## openspec/changes/ 不存在或 0 份 proposal.md (作用域缺失)")
        return 0

    entries: list[str] = []
    missing_note: str | None = None  # final stdout line when the allowlist is absent/unreadable
    if grandfathered_arg is None:
        missing_note = "(白名单文件缺失, 视为空集)"
    else:
        wl_path = Path(grandfathered_arg)
        if not wl_path.is_absolute():
            wl_path = root / wl_path  # relative to root, not cwd
        if not wl_path.is_file():
            missing_note = "(白名单文件缺失, 视为空集)"
        else:
            try:
                wl_lines = wl_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
            except OSError as exc:
                wl_lines = []
                missing_note = f"(白名单文件不可读, 视为空集: {exc.__class__.__name__})"
            seen: set[str] = set()
            for raw in wl_lines:
                s = raw.strip()
                if not s or s.startswith("#"):
                    continue
                e = _normalize_entry(s)
                if e and e not in seen:
                    seen.add(e)
                    entries.append(e)

    violations: list[tuple[str, str]] = []
    for problem_path, detail in scope_problems:
        try:  # no resolve(): a symlink must be reported under its own name, not its target
            prel = Path(problem_path).relative_to(root).as_posix()
        except ValueError:
            prel = problem_path
        violations.append((prel, f"{prel}:- {detail}"))
    for p in scope:
        rel = p.relative_to(root).as_posix()
        slug_dir = rel[: -len("/proposal.md")]
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            # fail-CLOSED: a proposal we cannot read is a violation, never a silent skip
            violations.append((rel, f"{rel}:- UNREADABLE {exc.__class__.__name__} (无法读取, 按违规计)"))
            continue
        fv = extract_linked_issue_field(text)
        # fail-CLOSED: only the literal "OK" verdict passes; every other
        # (closed-enum) verdict is a violation unless grandfathered.
        if fv.verdict != "OK" and slug_dir not in entries:
            line_part = str(fv.line_no) if fv.line_no is not None else "-"
            if fv.verdict == "NO_FIELD":
                detail = "缺字段行 (E0 三谓词无命中)"
            elif fv.verdict == "NO_TOKEN":
                detail = "首个非空白不是反引号 (E2)"
            else:  # BAD_TOKEN -- only remaining member of the closed verdict set
                detail = (
                    "不可解析元素: "
                    + ", ".join(fv.bad_elements)
                    + " (无关联请写 `none`)"
                )
            violations.append((rel, f"{rel}:{line_part} {fv.verdict} {detail}"))

    stale: list[tuple[str, str]] = []
    archive_dir = root / "openspec" / "archive"
    for e in entries:
        if not e.startswith("openspec/changes/"):
            stale.append((e, "b"))
            continue
        cand = root / e / "proposal.md"  # e is already normalized (no trailing slash)
        try:
            cand_is_file = cand.is_file()
        except OSError:
            # slug directory exists but cannot be stat-ed (EACCES): the scope
            # walk already reported it as UNREADABLE; not judged stale.
            continue
        if not cand_is_file:
            slug = e.rsplit("/", 1)[-1]
            # exact suffix match over real directory names — no glob, so slug
            # metacharacters ([, ], *, ?) cannot change the meaning
            try:
                archived = archive_dir.is_dir() and any(
                    d.is_dir() and d.name.endswith("-" + slug) for d in archive_dir.iterdir()
                )
            except OSError as exc:
                # archive/ unlistable: cannot prove (b); fall back to (a) loudly
                print(f"警告: openspec/archive 不可枚举 ({exc.__class__.__name__}), 陈旧条目 {e} 按 (a) 处置", file=sys.stderr)
                archived = False
            stale.append((e, "b" if archived else "a"))
            continue
        try:
            cand_text = cand.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue  # unreadable -> already reported as a violation above; not judged stale
        cand_fv = extract_linked_issue_field(cand_text)
        if cand_fv.verdict == "OK":
            stale.append((e, "c"))
        # else: still a legitimate (non-compliant, in-scope) grandfather entry.

    violations.sort(key=lambda t: t[0])
    stale.sort(key=lambda t: t[0])

    out_lines: list[str] = []
    k = len(violations) + len(stale)
    if k > 0:
        out_lines.append(f"FAIL {k} 项")
        out_lines.extend(line for _, line in violations)
        out_lines.extend(f"FAIL allowlist 陈旧: {e} ({letter})" for e, letter in stale)
        exit_code = 1
    else:
        out_lines.append(f"OK ({len(scope)} 份在范围内, {len(entries)} 条在册)")
        exit_code = 0

    if missing_note:
        out_lines.append(missing_note)

    print("\n".join(out_lines))
    return exit_code


def _run_emit_arg(path: Path, extract_linked_issue_field, emit_arg) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"--emit-arg 读取失败: {path}: {exc}", file=sys.stderr)
        return 2
    fv = extract_linked_issue_field(text)
    value = emit_arg(fv)
    try:
        sys.stdout.write(value)
        sys.stdout.flush()
    except UnicodeEncodeError as exc:
        # machine-consumed argument: never rewrite it with `?`; fail loudly (E6)
        print(
            f"--emit-arg 输出失败: stdout 编码 {sys.stdout.encoding} 无法表示实参 ({exc.__class__.__name__}); 探针自身失败, 实参未改写",
            file=sys.stderr,
        )
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.emit_arg is not None and args.root is not None:
        parser.error("--emit-arg 与位置参数 root 互斥 (root 仅 check 模式)")  # exit 2
    if args.emit_arg is None:
        # check mode only: stdout carries CJK status text; on a non-UTF-8 stdout
        # (PYTHONIOENCODING=ascii, native Windows pipes) never crash — degrade
        # unknown characters to `?`. NOT applied in --emit-arg mode, whose stdout
        # is a machine-consumed argument (R2 2ed89c8a: replacing bytes there
        # silently rewrote the argument; E6 requires a loud non-zero failure).
        try:
            sys.stdout.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    try:
        from lib.linked_issue_field import (
            extract_linked_issue_field,
            is_sentinel,  # noqa: F401 -- unused here on purpose: a lib older than v1.68.0 lacks the symbol, so the whole import fails -> check mode ##SKIP## / emit-arg exit 2 (version probe)
            emit_arg,
        )
    except Exception:
        if args.emit_arg is not None:
            print(
                "归一 SOT 不可导入 (aria 侧 lib/collision.py 或 lib/linked_issue_field.py 缺失 / 版本 < 1.68.0)",
                file=sys.stderr,
            )
            return 2
        print(
            "##SKIP## 归一 SOT 不可导入 (aria 侧 lib/collision.py 或 lib/linked_issue_field.py 缺失 / 版本 < 1.68.0)"
        )
        return 0

    if args.emit_arg is not None:
        return _run_emit_arg(Path(args.emit_arg), extract_linked_issue_field, emit_arg)

    return _run_check(Path(args.root or "."), args.grandfathered, extract_linked_issue_field)


if __name__ == "__main__":
    sys.exit(main())
