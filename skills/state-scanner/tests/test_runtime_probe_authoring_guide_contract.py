#!/usr/bin/env python3
"""Rule #6 第三行定向 fixture — authoring 向导承诺 ↔ 运行时现实一致性 (#113).

**为什么存在 (Rule #6 判据 2026-07-20 第三次收敛 / standards/conventions/skill-benchmark-exemption.md §3)**

#113 改了 `references/runtime-probe-declaration.md` 的「前置条件」段 —— 那是**处方性
authoring 向导**: spec 作者 (AI 或人) 读它来判断「我这份 spec 写了 `runtime_probe:`
声明, 归档门到底会不会评估它」。它影响的是 **authoring 行为**, 不是 scanning 行为。

state-scanner 的固定 AB 测试集结构上测不到这个行为 —— 11 个 eval 全是 scanning 场景
(「查看项目状态」/「扫描并告诉我是否落后 upstream」…), 全套件零个 eval 提到
`runtime_probe`。对一个套件结构上测不到的行为跑 AB 是**测量剧场**, 故按判据第三行走
「换一个能验到的手段 + 把盲区记成债」。本文件就是那个「能验到的手段」。

**它验什么**: 向导里那张前置条件表对三种 spec 形态各自宣称「声明是否被评估」, 逐行
拿去跟 `gate_result` 的**实际行为**对撞。作者被误导的失败形态是「向导说不评估, 实际
评估了」(或反之) —— 那正是本测试唯一会红的情形。

**可证伪性 (已实证)**: 把 #113 对该向导的改动回退 (恢复成「无 tasks.md 的 spec 即使
写了声明也不会被评估」), 本测试转红 —— 向导宣称 yaml-only 不评估, 而运行时评估。

**与 test_gate_yaml_probe_reach.py 的分工**: 那个文件测**运行时行为本身**对不对; 本
文件测**向导有没有如实描述那个行为**。运行时正确但文档撒谎, 前者全绿, 只有后者会红。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from _helpers import tmp_project, write_file

_LIB_DIR = str(Path(__file__).resolve().parent.parent / "scripts" / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)
from spec_complete import gate_result  # noqa: E402

_GUIDE = (
    Path(__file__).resolve().parent.parent / "references" / "runtime-probe-declaration.md"
)

_PROBE_YAML = (
    "runtime_probe:\n"
    "  partition: nonexistent-partition-for-test\n"
    "  symbol: some_symbol\n"
    "  max_age_days: 14\n"
)
_CLEAN_YAML = "tasks:\n  - id: TASK-001\n    title: parser work\n    status: done\n"

# 三种 spec 形态 → 在向导表格行里认出它的关键词 (按互斥性从窄到宽匹配)
_FORMS = (
    ("proposal_only", ("皆无",)),
    ("yaml_only", ("detailed-tasks.yaml",)),
    ("tasks_md", ("tasks.md",)),
)


def _documented_claims() -> dict[str, bool]:
    """从向导的前置条件表抽出「该形态的声明是否被评估」。

    解析失败不静默返回空 dict —— 调用方 pin 住必须集齐三形态, 否则本测试会退化成
    无断言的 no-op (本 cycle pre-merge review 抓到过同型缺陷)。
    """
    text = _GUIDE.read_text(encoding="utf-8")
    claims: dict[str, bool] = {}
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        has_yes, has_no = "✅" in line, "❌" in line
        if has_yes == has_no:  # 表头 / 分隔行 / 两者皆无或皆有 → 非判定行
            continue
        for form, keywords in _FORMS:
            if form in claims:
                continue
            if any(k in line for k in keywords):
                claims[form] = has_yes
                break
    return claims


def _spec_with_probe(root: Path, spec_id: str, *, yaml_text: str | None, tasks_md: bool):
    spec_dir = root / "openspec" / "changes" / spec_id
    write_file(
        spec_dir / "proposal.md",
        "---\n" + _PROBE_YAML + "---\n\n"
        f"# {spec_id}\n\n> **Status**: Approved\n\n## Why\ntest\n",
    )
    if yaml_text is not None:
        write_file(spec_dir / "detailed-tasks.yaml", yaml_text)
    if tasks_md:
        write_file(spec_dir / "tasks.md", "# tasks\n\n- [x] 1.1 done\n")
    return spec_dir


def _observed_evaluated(spec_id: str, *, yaml_text: str | None, tasks_md: bool) -> bool:
    """运行时事实: 该形态下 `runtime_probe` 声明有没有真被评估。"""
    with tmp_project() as root:
        result = gate_result(
            _spec_with_probe(root, spec_id, yaml_text=yaml_text, tasks_md=tasks_md)
        )
        return "runtime_probe" in result


class TestAuthoringGuideMatchesRuntime(unittest.TestCase):
    """向导对三形态的承诺必须与 gate_result 的实际行为逐行相符。"""

    def setUp(self):
        self.claims = _documented_claims()
        # fixture 前提先钉死: 表格解析不到 = 机读契约消失, 必须红而不是静静跳过
        self.assertEqual(
            set(self.claims),
            {"proposal_only", "yaml_only", "tasks_md"},
            f"前置条件表未能解析出全部三形态 (解析到 {sorted(self.claims)}) — "
            f"向导的机读契约被改坏或被删, 见 {_GUIDE.name}",
        )

    def test_tasks_md_form_matches_doc(self):
        observed = _observed_evaluated("guide-md", yaml_text=None, tasks_md=True)
        self.assertEqual(
            self.claims["tasks_md"], observed,
            "向导对『有 tasks.md』形态的承诺与运行时不符",
        )

    def test_yaml_only_form_matches_doc(self):
        observed = _observed_evaluated("guide-yaml", yaml_text=_CLEAN_YAML, tasks_md=False)
        self.assertEqual(
            self.claims["yaml_only"], observed,
            "向导对『仅 detailed-tasks.yaml』形态的承诺与运行时不符 "
            "(#113 把该子态从不评估改为评估, 向导若未跟改即在误导 spec 作者)",
        )

    def test_proposal_only_form_matches_doc(self):
        observed = _observed_evaluated("guide-bare", yaml_text=None, tasks_md=False)
        self.assertEqual(
            self.claims["proposal_only"], observed,
            "向导对『两者皆无』形态的承诺与运行时不符",
        )

    def test_guide_states_the_version_the_reversal_landed(self):
        """作者要能判断『我用的插件版本吃不吃这条新行为』, 故向导须写明起始版本。"""
        text = _GUIDE.read_text(encoding="utf-8")
        self.assertRegex(
            text, r"v1\.6[3-9]\.\d+|v1\.[7-9]\d?\.\d+",
            "向导未写明 yaml-only 子态从哪个版本起被评估 — 作者无法判断自己的版本",
        )


if __name__ == "__main__":
    unittest.main()
