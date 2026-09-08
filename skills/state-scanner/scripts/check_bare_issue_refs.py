#!/usr/bin/env python3
"""跨仓 issue 引用纪律检查 — 文档里的 `#<n>` 必须带 `<org>/<repo>` 限定。

判据 **fail-CLOSED**: 先假定每个 `#<n>` 都违规, 只有落进**封闭**豁免集才放过。

封闭豁免集 (仅三类):
  (a) **全限定** `<org>/<repo>#<n>` —— 恰一个 `/`; repo 段不含 `.`
      (排除 `docs/handoff/x.md#123` 这类**路径伪装**: 它有两个 `/` 且末段带扩展名,
       不是 issue 引用形态。Phase B 落地复审实测: 旧版单看「有没有 `/`」会放行它)
  (b) `Rule #N` / `规则 #N` 规则编号
  (c) 命中**允许清单**里某条字面的 `#<n>` —— 且只豁免**落在该字面覆盖区间内**的那个
      `#<n>`, 不豁免整行 (旧版用整行子串包含判定, 同一行后面追加的新裸引用会被连带放行)

允许清单来源: 调用仓的 `.aria/bare-issue-ref-allowlist.txt` (每行一条完整字面, `#` 开头
的行为注释)。**脚本本身不硬编码任何项目专属字面** —— 它随插件分发给第三方, 硬编码本仓的
字面对采用方既无意义又会造成不可预期的豁免。文件缺失 ⇒ 清单为空 (最严格), 不是错误。

退出码:
  0 = 零违规
  1 = 有违规 (逐条打印 file:line 与原文)
  2 = 无法判定 (文件读不了 / 清单读不了) —— fail-CLOSED, 与「有违规」区分开
"""
import re
import sys
from pathlib import Path

HASH = re.compile(r'#(\d+)')
# 全限定: 恰一个 `/`; org 段允许 . _ -; repo 段**不含 .** (排除 `a/b.md#1` 这类路径伪装);
# 左侧不得紧邻 `/` 或字母数字 (排除 `x/a/b#1` 这类多级路径)
QUALIFIED = re.compile(r'(?<![\w./-])[A-Za-z0-9_.-]+/[A-Za-z0-9_-]+#\d+')
RULE_BEFORE = re.compile(r'(Rule|规则)\s*$')
ALLOWLIST_REL = ".aria/bare-issue-ref-allowlist.txt"


def load_allowlist(repo_root):
    """读调用仓的允许清单。缺失 ⇒ 空清单 (最严格)。读不了 ⇒ 抛, 调用方判 rc 2。"""
    p = Path(repo_root) / ALLOWLIST_REL
    if not p.is_file():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def scan(path, allowlist):
    bad = []
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    for n, line in enumerate(lines, 1):
        # 豁免区间: 全限定引用 + 允许清单字面各自占据的字符区间
        spans = [(m.start(), m.end()) for m in QUALIFIED.finditer(line)]
        for lit in allowlist:
            start = 0
            while True:
                k = line.find(lit, start)
                if k < 0:
                    break
                spans.append((k, k + len(lit)))
                start = k + 1
        for m in HASH.finditer(line):
            if any(a <= m.start() < b for a, b in spans):
                continue
            if RULE_BEFORE.search(line[:m.start()]):
                continue
            bad.append((n, m.group(0), line.strip()[:100]))
    return bad


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    targets = [a for a in argv if not a.startswith("--")]
    root = Path.cwd()
    for a in argv:
        if a.startswith("--repo-root="):
            root = Path(a.split("=", 1)[1])
    if not targets:
        print("usage: check_bare_issue_refs.py [--repo-root=DIR] <file> [<file>...]", file=sys.stderr)
        return 2
    try:
        allowlist = load_allowlist(root)
    except OSError as e:
        print("UNDECIDABLE: 允许清单读不了 (%s) — fail-CLOSED, 不当作通过" % e, file=sys.stderr)
        return 2
    total = 0
    for t in targets:
        try:
            hits = scan(t, allowlist)
        except (OSError, UnicodeDecodeError) as e:
            print("UNDECIDABLE: %s 读不了 (%s) — fail-CLOSED, 不当作通过" % (t, e), file=sys.stderr)
            return 2
        for n, tok, ctx in hits:
            print("  %s:%d %s  %s" % (Path(t).name, n, tok, ctx))
            total += 1
    print("裸 issue 引用: %d" % total)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
