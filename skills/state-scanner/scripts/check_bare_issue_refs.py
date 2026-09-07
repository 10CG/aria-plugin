#!/usr/bin/env python3
"""跨仓 issue 引用纪律检查 (Part C3 / SC-12)。

违规 = 任何 `#<n>` 不能被下列**封闭**豁免集合覆盖。判据是 fail-CLOSED:
先假定每个 `#<n>` 都违规, 只有落进豁免集才放过 (post_planning R5 F13 订正
—— v1 用的是「`#` 前一个字符不是 / 或字母数字」这种单字符前瞻, 那是正向枚举,
对 `Aria#195` 这种「只有仓名没有 org」的半限定形态天然 fail-OPEN, memory
`invariant-needs-failclosed-default`)。

封闭豁免集 (仅三类):
  1. 全限定引用 `<org>/<repo>#<n>` —— 必须含 `/`, 半限定 (`Aria#195`) **不豁免**
  2. 不可协商规则编号 `Rule #<n>` / `规则 #<n>`
  3. 反引号 code span 内的 `#<n>`, **且该 code span 自身是全限定形态**
     —— v1 是「任意 code span 一律掏空」, 那会让 `` `#199` `` 这种反引号裹的
     裸号免检 (R5 F13 点名的盲区)。现改为: code span 内仍照常判, 全限定才豁免。

退出码: 0 = 零违规; 1 = 有违规 (逐条打印 file:line 与原文)。
"""
import re
import sys
from pathlib import Path

HASH = re.compile(r'#(\d+)')
# 全限定: <org>/<repo>#<n>, org/repo 段允许字母数字与 _ . -
QUALIFIED = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#\d+')
RULE_BEFORE = re.compile(r'(Rule|规则)\s*$')

# 豁免类 (c): 显式**封闭**白名单 —— Part B 要逐字写进 SKILL.md 而本身含裸 #<n> 的目标行。
# 新增须在此显式登记; 不得放宽成「任意反引号一律豁免」(那正是 R5 F13 点名的 fail-OPEN)。
TARGET_LITERALS = (
    "| D.2 | openspec-archive | Spec 归档 (**#95 完成度",
)


def scan(path):
    bad = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").split("\n"), 1):
        # 全限定引用占据的字符区间 —— 落在其中的 # 一律豁免 (豁免类 1 与 3 合流:
        # 反引号内也必须是全限定才算数, 反引号本身不再构成豁免)
        spans = [(m.start(), m.end()) for m in QUALIFIED.finditer(line)]
        if any(lit in line for lit in TARGET_LITERALS):   # 豁免类 (c)
            continue
        for m in HASH.finditer(line):
            if any(a <= m.start() < b for a, b in spans):  # 豁免类 (a) 全限定
                continue
            if RULE_BEFORE.search(line[:m.start()]):       # 豁免类 (b) 规则编号
                continue
            bad.append((n, m.group(0), line.strip()[:100]))
    return bad


if __name__ == "__main__":
    targets = sys.argv[1:] or ["proposal.md"]
    total = 0
    for t in targets:
        for n, tok, ctx in scan(t):
            print(f"  {Path(t).name}:{n} {tok}  {ctx}")
            total += 1
    print(f"裸 issue 引用: {total}")
    sys.exit(1 if total else 0)
