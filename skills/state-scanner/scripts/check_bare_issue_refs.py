#!/usr/bin/env python3
"""跨仓 issue 引用纪律检查 — 文档里的 `#<n>` 必须带 `<org>/<repo>` 限定。

判据 **fail-CLOSED**: 先假定每个 `#<n>` 都违规, 只有落进**封闭**豁免集才放过。

封闭豁免集 (仅三类):
  (a) **全限定** `<org>/<repo>#<n>` —— 恰一个 `/`; repo 段可含 `.` (真仓名如 `10cg.local`),
      但**不得以文件扩展名结尾** (封闭集 FILE_EXTENSIONS)
      (排除 `docs/handoff/x.md#123` 这类**路径伪装**: 它有两个 `/` 且末段带扩展名,
       不是 issue 引用形态。Phase B 落地复审实测: 旧版单看「有没有 `/`」会放行它;
       2026-09-13 aria-plugin#196: 旧版 repo 段一律禁 `.`, 把 `10CG/10cg.local#40` 误报)
  (b) `Rule #N` / `规则 #N` 规则编号
  (c) 命中**允许清单**里某条字面的 `#<n>` —— 且只豁免**落在该字面覆盖区间内**的那个
      `#<n>`, 不豁免整行 (旧版用整行子串包含判定, 同一行后面追加的新裸引用会被连带放行)

写法规范 SOT: `standards/conventions/content-integrity.md` §4.4「Issue / PR 引用写法」
(owner 2026-09-13 裁定修法 B: `#` 只留给 issue / PR, 文内编号直接写数字; 有违规时本脚本把
读者指到该节, 不只打印违规行)。

允许清单来源: **从被扫文件向上找最近的** `.aria/bare-issue-ref-allowlist.txt` (与 cwd 无关;
显式 `--repo-root=DIR` 优先) (每行一条完整字面, `#` 开头
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
# 全限定: 恰一个 `/`; org 段允许 . _ -; repo 段允许 . _ - (真仓名可带 `.`, 如 `10cg.local`);
# 左侧不得紧邻 `/` 或字母数字 (排除 `x/a/b#1` 这类多级路径)。
# 左边界**显式枚举 ASCII**, 不用 `\w` —— Python 的 `\w` 匹配 CJK, 会让「参见10CG/Aria#195」
# 这种中文紧邻全限定引用的写法被判成裸引用 (落地复审实测)。
# repo 段命名捕获, 供 `_is_path_disguise` 看末尾扩展名。
QUALIFIED = re.compile(r'(?<![A-Za-z0-9_./-])[A-Za-z0-9_.-]+/(?P<repo>[A-Za-z0-9_.-]+)#\d+')
# 单级路径伪装 `a/b.md#1`: repo 段以这些扩展名结尾就不当全限定引用。
# **封闭集** (fail-CLOSED 精神: 只放这些已知形态, 不做开放式启发); 采用方撞到新扩展名 → 加进来。
FILE_EXTENSIONS = frozenset((
    "md", "markdown", "txt", "rst",
    "py", "sh", "bash", "js", "ts", "go", "rs", "rb", "java", "c", "h", "cpp",
    "yaml", "yml", "json", "toml", "ini", "cfg", "conf", "env",
    "html", "htm", "css", "xml", "csv", "log", "lock",
))
RULE_BEFORE = re.compile(r'(Rule|规则)\s*$')
ALLOWLIST_REL = ".aria/bare-issue-ref-allowlist.txt"
# 有违规时打印的规范指引 (aria-plugin#196 owner 裁定修法 B 的第二半: 报错文案指向规范)。
CONVENTION_HINT = (
    "写法规范: standards/conventions/content-integrity.md §4.4「Issue / PR 引用写法」\n"
    "  规则 1 跨仓一律全限定 <org>/<repo>#<n> (例 10CG/Aria#195), 只写仓名或只写 #数字 都算裸引用\n"
    "  规则 2 `#` 只留给 issue / PR: 文内编号 (条目 / 表格行 / 步骤) 直接写数字, 不加 `#`\n"
    "  豁免仅三类: 全限定引用 / Rule #N / 调用仓 .aria/bare-issue-ref-allowlist.txt 所列字面"
)


def _is_path_disguise(m):
    """`a/b.md#1` 这类单级路径伪装: repo 段以封闭扩展名集里的扩展名结尾。"""
    repo = m.group("repo")
    if "." not in repo:
        return False
    return repo.rsplit(".", 1)[1].lower() in FILE_EXTENSIONS


def _find_allowlist(start):
    """从被扫文件向上找最近的 `.aria/bare-issue-ref-allowlist.txt`。

    **不依赖 cwd** (落地复审实测: 原版相对 `Path.cwd()` 解析, 换个目录跑自检就红两条假阳性,
    而 Spec 自己规定落地前必跑该自检)。显式 `--repo-root=` 仍然优先。
    """
    cur = Path(start).resolve()
    cur = cur if cur.is_dir() else cur.parent
    for d in [cur, *cur.parents]:
        cand = d / ALLOWLIST_REL
        if cand.is_file():
            return cand
    return None


def load_allowlist(repo_root):
    """读允许清单。缺失 ⇒ 空清单 (最严格)。读不了 ⇒ 抛, 调用方判 rc 2。"""
    p = Path(repo_root) / ALLOWLIST_REL if repo_root else None
    if p is None or not p.is_file():
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
        spans = [(m.start(), m.end()) for m in QUALIFIED.finditer(line)
                 if not _is_path_disguise(m)]
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
    root = None
    for a in argv:
        if a.startswith("--repo-root="):
            root = Path(a.split("=", 1)[1])
    if not targets:
        print("usage: check_bare_issue_refs.py [--repo-root=DIR] <file> [<file>...]", file=sys.stderr)
        return 2
    try:
        if root is not None:
            allowlist = load_allowlist(root)
        else:
            # 无显式 --repo-root: 按**第一个被扫文件**向上找, 与 cwd 无关
            found = _find_allowlist(targets[0])
            allowlist = load_allowlist(found.parent.parent) if found else []
    except (OSError, UnicodeDecodeError) as e:
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
    if total:
        print(CONVENTION_HINT)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
