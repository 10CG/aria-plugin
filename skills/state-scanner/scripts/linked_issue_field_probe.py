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

`--emit-arg <file>` mode:
  Reads ONE file and prints (no trailing newline) the E6 `--linked-issue`
  argument value for it — the mechanical host for the proposal's E6 four-cell
  table. Only an `OK`, non-sentinel verdict produces output; the other three
  cells print nothing. A read failure or an unavailable SOT module prints
  nothing to stdout, writes one line to stderr, and exits 2 (distinct from
  check mode's exit 1, since this is not a "found a violation" outcome).

`--emit-arg` and `--grandfathered` are mutually exclusive (argparse enforces
this, exiting 2 on stderr).

Scope-selection / allowlist policy live entirely in THIS file — the imported
`lib.linked_issue_field` module carries none of it, only the E0-E6 rules
themselves.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Sibling-skill-import style (state-scanner is its own package root; see
# CONTRACT-linked-issue-field.md §2 for why this is the mirror image of
# coordination_probe.py's scripts/lib insertion — that script needs
# scripts/lib/runtime_probe.py, this one needs the skill-root-level lib/
# package instead).
_SS = str(Path(__file__).resolve().parent.parent)
if _SS not in sys.path:
    sys.path.insert(0, _SS)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="linked-issue-field-availability E0-E6 probe (check mode + --emit-arg mode)"
    )
    parser.add_argument("root", nargs="?", default=".")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--grandfathered", default=None)
    mode.add_argument("--emit-arg", default=None)
    return parser


def _run_check(root: Path, grandfathered_arg, extract_linked_issue_field) -> int:
    root = root.resolve()
    changes = root / "openspec" / "changes"
    scope = sorted(changes.rglob("proposal.md")) if changes.is_dir() else []
    if not scope:
        print("##SKIP## openspec/changes/ 不存在或 0 份 proposal.md (作用域缺失)")
        return 0

    entries: list[str] = []
    missing_note = False
    if grandfathered_arg is None:
        missing_note = True
    else:
        wl_path = Path(grandfathered_arg)
        if not wl_path.is_absolute():
            wl_path = root / wl_path  # relative to root, not cwd
        if not wl_path.is_file():
            missing_note = True
        else:
            for raw in wl_path.read_text(encoding="utf-8", errors="replace").splitlines():
                s = raw.strip()
                if not s or s.startswith("#"):
                    continue
                entries.append(s)

    violations: list[tuple[str, str]] = []
    for p in scope:
        text = p.read_text(encoding="utf-8", errors="replace")
        fv = extract_linked_issue_field(text)
        rel = p.relative_to(root).as_posix()
        slug_dir = rel[: -len("/proposal.md")]
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
        e_clean = e.rstrip("/")
        cand = root / e_clean / "proposal.md"
        if not cand.is_file():
            slug = e_clean.rsplit("/", 1)[-1]
            if archive_dir.is_dir() and any(archive_dir.glob(f"*-{slug}")):
                stale.append((e, "b"))
            else:
                stale.append((e, "a"))
            continue
        cand_text = cand.read_text(encoding="utf-8", errors="replace")
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
        out_lines.append("(白名单文件缺失, 视为空集)")

    print("\n".join(out_lines))
    return exit_code


def _run_emit_arg(path: Path, extract_linked_issue_field, emit_arg) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"--emit-arg 读取失败: {path}: {exc}", file=sys.stderr)
        return 2
    fv = extract_linked_issue_field(text)
    sys.stdout.write(emit_arg(fv))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        from lib.linked_issue_field import (
            extract_linked_issue_field,
            is_sentinel,  # noqa: F401 -- re-exported import surface, contract-pinned
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

    return _run_check(Path(args.root), args.grandfathered, extract_linked_issue_field)


if __name__ == "__main__":
    sys.exit(main())
