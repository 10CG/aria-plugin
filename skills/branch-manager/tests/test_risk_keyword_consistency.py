"""branch-risk-build-gate-alignment (10CG/Aria#231) — 双源一致性结构化测试。

Rule #6 判据 (skill-benchmark-exemption SOT 表第一行): 描述性 hunk (config-loader
schema 新键 / template 键) 的 substitute = SC 级 baseline-failing 结构化测试。
本套同时钉住处方性 hunk 的**静态面**: 关键词表在 SKILL.md 与
internal/MODE_DECISION_LOGIC.md 双源逐字一致 (spec Constraints「双源」行),
以及 #231 的两条反事实回归钉 (裸 api / 裸 核心 不得回 flat 高风险表)。

反事实自证 (改前 v1.77.0 基线上本套必红): 裸 api 在 flat 表 ✓红 / 双表不一致 ✓红 /
无 branch_manager config 面 ✓红。动态行为面 (共现判定真伪) 由 Rule #6 场景 1 AB
覆盖, 不在此重复。

注意 (memory: skill runner 只扫自己 tests/): 本测试跨目录读 ../config-loader 与
../../../.aria/config.template.json (主仓), 全仓回归须显式包含本目录。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent          # skills/branch-manager
ARIA_ROOT = SKILL_DIR.parent.parent                          # aria 仓根
SKILL_MD = SKILL_DIR / "SKILL.md"
LOGIC_MD = SKILL_DIR / "internal" / "MODE_DECISION_LOGIC.md"
CONFIG_LOADER_MD = ARIA_ROOT / "skills" / "config-loader" / "SKILL.md"
TEMPLATE = ARIA_ROOT.parent / ".aria" / "config.template.json"


def _skill_flat_rows() -> dict[str, list[str]]:
    text = SKILL_MD.read_text(encoding="utf-8")
    # 风险检测节的 flat 表行形如: | refactor, rewrite, ... |  (类 | 词表 两列表)
    rows = {}
    high = re.search(r"api 类词 \| api, 接口, endpoint", text)
    assert high, "SKILL.md 缺 api 共现规则表"
    m_high = re.search(r"\|\s*(refactor[^\|]*)\|", text)
    m_low = re.search(r"\|\s*(typo[^\|]*)\|", text)
    assert m_high and m_low, "SKILL.md 缺 flat 风险表"
    rows["high"] = [w.strip() for w in m_high.group(1).split(",") if w.strip()]
    rows["low"] = [w.strip() for w in m_low.group(1).split(",") if w.strip()]
    m_api = re.search(r"\|\s*api 类词\s*\|\s*([^\|]+)\|", text)
    m_chg = re.search(r"\|\s*变更类词\s*\|\s*([^\|]+)\|", text)
    assert m_api and m_chg, "SKILL.md 缺共现词表"
    rows["api_terms"] = [w.strip() for w in m_api.group(1).split(",") if w.strip()]
    rows["change_terms"] = [w.strip() for w in m_chg.group(1).split(",") if w.strip()]
    return rows


def _logic_lists() -> dict[str, list[str]]:
    text = LOGIC_MD.read_text(encoding="utf-8")

    def bracket_list(name: str) -> list[str]:
        m = re.search(name + r"\s*=\s*\[(.*?)\]", text, re.S)
        assert m, f"MODE_DECISION_LOGIC.md 缺 {name}"
        return [
            w.strip().strip('"\'')
            for w in m.group(1).split(",")
            if w.strip().strip('"\'')
        ]

    return {
        "high": bracket_list("high_risk_keywords"),
        "low": bracket_list("low_risk_keywords"),
        "api_terms": bracket_list("api_terms"),
        "change_terms": bracket_list("change_terms"),
    }


def test_high_flat_table_identical_across_sources():
    assert _skill_flat_rows()["high"] == _logic_lists()["high"]


def test_low_flat_table_identical_across_sources():
    assert _skill_flat_rows()["low"] == _logic_lists()["low"]


def test_cooccurrence_tables_identical_across_sources():
    s, l = _skill_flat_rows(), _logic_lists()
    assert s["api_terms"] == l["api_terms"]
    assert s["change_terms"] == l["change_terms"]


def test_bare_api_and_core_not_in_high_flat_table():
    """#231 反事实钉: 裸 api 不得回 flat 高风险表 (须走共现); 裸 核心 同病灶出表。"""
    for src, name in ((_skill_flat_rows(), "SKILL.md"), (_logic_lists(), "LOGIC.md")):
        assert "api" not in src["high"], f"{name}: 裸 api 回到了 flat 高风险表"
        assert "核心" not in src["high"], f"{name}: 裸 核心 回到了 flat 高风险表"


def test_api_cooccurrence_terms_present():
    for src in (_skill_flat_rows(), _logic_lists()):
        assert "api" in src["api_terms"]
        for must in ("变更", "breaking", "重构"):
            assert must in src["change_terms"], f"变更类词缺 {must}"


def test_config_keys_three_surfaces():
    """branch_manager.high/low_risk_keywords 三面齐: branch-manager 配置节 + config-loader schema + template。"""
    bm = SKILL_MD.read_text(encoding="utf-8")
    cl = CONFIG_LOADER_MD.read_text(encoding="utf-8")
    for key in ("branch_manager.high_risk_keywords", "branch_manager.low_risk_keywords"):
        assert key in bm, f"branch-manager SKILL.md 配置节缺 {key}"
        assert key in cl, f"config-loader SKILL.md schema 缺 {key}"
    assert "整体覆盖" in bm or "整体替换" in bm, "配置节须写明覆盖非合并语义"


def test_template_branch_manager_section():
    """模板段存在且键齐 (null 默认); 覆盖语义注释在段内。"""
    d = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    sec = d.get("branch_manager")
    assert isinstance(sec, dict), "config.template.json 缺 branch_manager 段"
    assert sec.get("high_risk_keywords") is None
    assert sec.get("low_risk_keywords") is None
    assert "覆盖" in json.dumps(sec, ensure_ascii=False)
