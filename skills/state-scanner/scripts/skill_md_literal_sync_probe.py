#!/usr/bin/env python3
"""skill-md-sha-backlink-literal-sync — SKILL.md 复述的占位串 == 生产者产生的那一串。

守的是一条**跨文件靠人工保持一致**的字面串: `openspec-archive/SKILL.md` 的 Step 7
指示 AI 替换 `d_payload.body` 里的某一行, 而那一行的**唯一生产者**是
`state-scanner/scripts/lib/spec_complete.py::_build_d_payload`。两侧措辞一旦漂移,
逐字匹配就落空。2026-09-06 实测已漂移 (`Step2` vs `Step 7`, 差一字符加一空格)。

三条断言 (缺一则挡不住某类坏实现, 三态实证见 spec Part C1):
  (a) 两侧各恰好提取 1 处锚点 —— 否则措辞被改动, 探针需人工对齐
  (b) 两侧逐字相等
  (c) 命中串必须含 `Step 7` —— 只有 (b) 时「两侧同步改回 Step2」也满足相等

exit code (对齐 collectors/custom_checks.py 契约):
  0 → pass: 两侧逐字相等且值正确
  1 → fail: 两侧不等 / 锚点提取数 != 1 / 两侧一致但值错了 / 目标文件缺失或读不了

⚠️ **无 SKIP 态**: 探针落盘后就在插件内, `parents[3]` 必然可达两个目标文件 ⇒
「插件源码不可见」在健康常态下永不触发, 保留它就得人为构造生产中不可能的场景 =
测量剧场 (判据同 memory `false_green_dual_is_permanent_red`)。目标文件缺失直接
判 FAIL —— 插件损坏是真异常, 不是「不适用」。
"""
import re
import sys
from pathlib import Path

PREFIX = "> 归档 SHA 回链:"
REQUIRED_STEP = "Step 7"  # 理据见下方第三条断言处

_MD_RE = re.compile(r'"(' + re.escape(PREFIX) + r'[^"]*填入)"')
_PY_RE = re.compile(r'lines\.append\(\s*"(' + re.escape(PREFIX) + r'[^"]*)"\s*\)')


def _plugin_root():
    """插件根 = 本脚本所在处向上四级 (scripts → state-scanner → skills → aria)。

    不用 CLAUDE_PLUGIN_ROOT: 探针落盘后就在插件内, 脚本在哪插件根就在哪 ——
    对 marketplace 安装的采用方同样正确, 且不依赖 env 传递 (env 在本设计下完全惰性)。
    """
    return Path(__file__).resolve().parents[3]


def main(argv=None):
    # argv 收下但不用: 本探针的定位基准是自身位置, 不是调用方传的仓路径 (见 _plugin_root)。
    # 保留形参是为对齐同目录其余探针的调用接口 (custom_checks 统一传 repo 路径)。
    _ = argv if argv is not None else sys.argv[1:]
    root = _plugin_root()
    md = root / "skills/openspec-archive/SKILL.md"
    py = root / "skills/state-scanner/scripts/lib/spec_complete.py"

    missing = [str(p) for p in (md, py) if not p.is_file()]
    if missing:
        print("FAIL 目标文件缺失 (插件损坏?): " + ", ".join(missing))
        return 1

    try:
        md_text = md.read_text(encoding="utf-8", errors="replace")
        py_text = py.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        # 读不了 (权限 / IO) 与「两侧漂移」是两回事。
        # ⚠️ 理据订正 (发布前验证席): 不捕获时**两者都落 status=fail** —— Python 未捕获
        # 异常的退出码是 1 而非 127, 而 custom_checks.py 只在 rc==127 时判 error。
        # 这里显式 return 换来的是**可读的 FAIL 诊断文案**, 而不是 status 值本身的区分
        # (不捕获时 output 是空的, 回退成没有信息量的 "rc=1")。
        print("FAIL 目标文件读取失败 (%s) — fail-CLOSED, 不当作通过" % e)
        return 1
    md_hits = _MD_RE.findall(md_text)
    py_hits = _PY_RE.findall(py_text)
    if len(md_hits) != 1 or len(py_hits) != 1:
        print(
            "FAIL 锚点提取数异常 (期望各 1): SKILL.md=%d spec_complete.py=%d"
            " — 措辞被改动, 需人工对齐后更新本探针" % (len(md_hits), len(py_hits))
        )
        return 1
    if md_hits[0] == py_hits[0]:
        # 第三条断言: 双边相等还不够 ——「两侧同步改回 Step2」也满足相等。
        # `Step 7` 不是任选常量: 它有 2026-07-22 成文裁定背书
        # (openspec/archive/2026-07-22-state-scanner-gate-yaml-datasource/proposal.md:174
        #  逐字「裁定: 保留改名, 收窄声称」, 并论证 Step2 是**事实错误**的引用)。
        if REQUIRED_STEP not in md_hits[0]:
            print(
                "FAIL 两侧一致但值错了 (缺 %r): %r\n"
                "  该值有 2026-07-22 成文裁定背书, 不得改回 Step2"
                % (REQUIRED_STEP, md_hits[0])
            )
            return 1
        print("OK 两侧一致: %r" % (md_hits[0],))
        return 0
    print("FAIL SHA 回链占位串两侧漂移:")
    print("  SKILL.md         : %r" % (md_hits[0],))
    print("  _build_d_payload : %r" % (py_hits[0],))
    return 1


if __name__ == "__main__":
    sys.exit(main())
