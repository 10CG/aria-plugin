"""TASK-003 — groom-report schema v1 自测 (SC-8 验收面)。

三组断言:
  (a) schema 自身结构: json.loads 可解析 + draft 2020-12 声明 + 顶层必填/封闭 +
      additive-only 契约文档化 + labels_payload 键集封闭且无 remove (proposal §3)。
  (b) 合法样例 report 通过校验: 样例形态取自 2026-10-18 真语料
      (scratchpad/issues-open-2026-10-18.json: 裸仓名 / title 前缀 / labels 几乎全空),
      防形态脱节假绿。
  (c) 含 remove 字段的 labels_payload 判非法 (封闭键集), 外加一组负向样例证明
      mini-validate 有牙齿 (对已知非法输入必须报错, 防恒绿循环论证)。

双路径校验策略:
  - mini_validate: 纯 stdlib 结构断言器 (draft 2020-12 关键字子集), 无第三方依赖,
    任何环境可跑;
  - jsonschema (try-import): 本机装了 python3-jsonschema 时用标准验证器复核同一批
    正/负样例 (证明 schema 可被标准验证器直接加载校验), 未装则跳过该路径。

依赖方向 (B.3 修复轮): mini_validate 的 SOT 在**生产层**
``scripts/lib/schema_validate.py`` — 本文件反向 import 它 (groom.py 出厂
自校验与测试断言同源单点; 生产代码不再直载 tests/ 或依赖 pytest 环境),
``ValidatorProvenanceTests`` 钉死该方向。

References:
  openspec/changes/issue-groomer-p1-mvp (proposal §3, SC-8, 裁定-8);
  DEC-20261018-001 (裁定-3 分层采集 / 裁定-7 Tier A 唯四信号源 / 裁定-8 标签契约)。
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_SCHEMA_PATH = (
    Path(__file__).parent.parent / "scripts" / "groom-report.schema.json"
)

# 生产层校验器 (SOT): scripts/ 入 path 后以 lib.schema_validate 导入
# (house convention, 与 test_groom_cli 同款)。
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))

from lib.schema_validate import mini_validate  # noqa: E402

try:  # 双路径第二径: 标准验证器 (可选)
    import jsonschema
    from jsonschema.validators import Draft202012Validator

    HAS_JSONSCHEMA = True
except ImportError:  # pragma: no cover - environment-dependent
    HAS_JSONSCHEMA = False


def _assert_invalid(instance: Any, schema: dict[str, Any], needle: str) -> None:
    """Assert mini_validate flags the instance, with the expected reason substring.

    `needle` guards against a vacuous red: the failure must be the one we
    constructed, not an unrelated accident.
    """
    errors = mini_validate(instance, schema)
    assert errors, "expected validation errors, got none (vacuous pass)"
    assert any(needle in e for e in errors), (
        f"expected an error containing {needle!r}, got: {errors}"
    )


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _valid_report() -> dict[str, Any]:
    """合法样例 report — 形态取自 2026-10-18 真语料 (三个条目覆盖三种形态):
    纯 title 前缀信号 / label+staleness 信号 + 完整 assessment + 空差集 /
    无显式信号 => category=unknown (负面形态)。
    """
    return {
        "snapshot_schema_version": "1.1",
        "generated_at": "2026-10-19T12:00:00Z",
        "harness": "claude-code",
        "repos": [
            {"repo": "Aria", "open_issues": 2},
            {"repo": "aria-plugin", "open_issues": 1},
        ],
        "issues": [
            {
                "repo": "Aria",
                "number": 236,
                "title": "[archived] pre-merge-completeness-gate-change-scope 归档跟踪 (10CG/Aria#199, v1.76.0)",
                "labels": [],
                "category": "tracker",
                "signals": [
                    {
                        "source": "title_prefix",
                        "rule": "prefix:tracker",
                        "detail": "title 前缀 '[archived]' 命中 labels.yaml 前缀映射表 tracker 键",
                    }
                ],
                "confidence_source": ["title_prefix"],
                "assessment": None,
                "labels_payload": {
                    "existing": [],
                    "suggested": ["tracker"],
                    "apply_payload": {
                        "repo": "Aria",
                        "number": 236,
                        "add": ["tracker"],
                        "idempotent": True,
                    },
                },
            },
            {
                "repo": "aria-plugin",
                "number": 208,
                "title": "issue-list fetch limit=50 静默丢数据",
                "labels": ["bug"],
                "category": "bug",
                "signals": [
                    {
                        "source": "label",
                        "rule": "label:bug",
                        "detail": "tracker label 'bug' 命中分类键 bug",
                    },
                    {
                        "source": "staleness",
                        "rule": "staleness:gt-90d",
                        "detail": "最近更新 2026-07-14, 距今 >90 天",
                    },
                ],
                "confidence_source": ["label", "staleness"],
                "assessment": {
                    "verdict_priorities": "P2 — 与全分页 fetch 修复轨相关, 建议随 issue-groomer P1 一并处理",
                    "suspected_fixed": True,
                    "owner_decisions": ["是否随 #238 一起验收关单"],
                    "provenance": {"harness": "claude-code", "model_id": "glm-5.2"},
                },
                "labels_payload": {
                    "existing": ["bug"],
                    "suggested": ["bug"],
                    "apply_payload": {
                        "repo": "aria-plugin",
                        "number": 208,
                        "add": [],  # suggested − existing = 空差集 (幂等形态)
                        "idempotent": True,
                    },
                },
            },
            {
                "repo": "Aria",
                "number": 241,
                "title": "无显式编码信号的条目 (讨论型, 无前缀无 label)",
                "labels": [],
                "category": "unknown",
                "signals": [],
                "confidence_source": [],
                "assessment": None,
                "labels_payload": {
                    "existing": [],
                    "suggested": [],
                    "apply_payload": {
                        "repo": "Aria",
                        "number": 241,
                        "add": [],
                        "idempotent": True,
                    },
                },
            },
        ],
        "diff": {
            "new": [
                {"repo": "Aria", "number": 241, "title": "无显式编码信号的条目 (讨论型, 无前缀无 label)"}
            ],
            "closed": [
                {"repo": "aria-plugin", "number": 199, "title": "已随 v1.76.0 验收合并的条目"}
            ],
            "drift": [
                {
                    "repo": "aria-plugin",
                    "number": 208,
                    "title": "issue-list fetch limit=50 静默丢数据",
                    "from": "P1",
                    "to": "P2",
                }
            ],
            "baseline_run": False,
            "drift_truncated": False,
            "drift_total": 1,
        },
        "summary": {
            "total_issues": 3,
            "by_category": {"tracker": 1, "bug": 1, "unknown": 1},
            "by_repo": {"Aria": 2, "aria-plugin": 1},
            "assessed": 1,
            "diff_counts": {"new": 1, "closed": 1, "drift": 1},
        },
    }


@pytest.fixture()
def valid_report() -> dict[str, Any]:
    return _valid_report()


# ── (a) schema 自身结构断言 ────────────────────────────────────────────────────


class TestSchemaSelf:
    def test_schema_parses_as_json(self, schema: dict[str, Any]) -> None:
        """(a) schema 文件可被 json.loads (fixture 已隐含, 此处显式钉住加载源)。"""
        assert _SCHEMA_PATH.exists(), f"schema file missing: {_SCHEMA_PATH}"
        assert isinstance(schema, dict)

    def test_declares_draft_2020_12(self, schema: dict[str, Any]) -> None:
        """(a) $schema 声明 draft 2020-12 (标准验证器可据此选验证器)。"""
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"

    def test_toplevel_required_keyset(self, schema: dict[str, Any]) -> None:
        """(a) 顶层七个必填键全部声明。"""
        required = schema["required"]
        for key in (
            "snapshot_schema_version",
            "generated_at",
            "harness",
            "repos",
            "issues",
            "diff",
            "summary",
        ):
            assert key in required, f"top-level required missing {key!r}"

    def test_toplevel_closed_keyset(self, schema: dict[str, Any]) -> None:
        """(a) 顶层封闭 (additionalProperties:false) — 未版本化私加字段会被拒。"""
        assert schema["additionalProperties"] is False

    def test_snapshot_schema_version_is_const_1_1(self, schema: dict[str, Any]) -> None:
        """(a) snapshot_schema_version 钉 const '1.1' (1.1 = DiffSection 新增可选
        drift_truncated/drift_total; 加字段 ⇒ minor bump, 纪律见顶层 $comment)。"""
        version = schema["properties"]["snapshot_schema_version"]
        assert version.get("const") == "1.1"

    def test_additive_only_contract_documented(self, schema: dict[str, Any]) -> None:
        """(a) SC-8: additive-only 演进纪律写进 $comment/description (文档化断言)。"""
        comment = schema.get("$comment", "")
        assert "ADDITIVE-ONLY" in comment
        assert "minor" in comment and "major" in comment
        # 演进纪律同款写进 snapshot_schema_version 自身描述
        version_desc = schema["properties"]["snapshot_schema_version"]["description"]
        assert "minor" in version_desc and "major" in version_desc

    def test_harness_is_provenance_layer_one(self, schema: dict[str, Any]) -> None:
        """(a) 顶层 harness 字段存在且为非空字符串 (provenance 第一层, 脚本自报)。"""
        harness = schema["properties"]["harness"]
        assert harness["type"] == "string"
        assert harness.get("minLength") == 1

    def test_no_numeric_confidence_field_anywhere(self, schema: dict[str, Any]) -> None:
        """(a) 裁定-7: 全树不定义数值 confidence 字段 (confidence = 枚举信号集)。"""
        def walk(node: Any) -> None:
            if isinstance(node, dict):
                assert "confidence" not in node.get("properties", {}), (
                    "numeric confidence field must not be defined (裁定-7: 枚举信号集非分数)"
                )
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(schema)

    def test_signal_source_enum_is_closed_four(self, schema: dict[str, Any]) -> None:
        """(a) 裁定-7: Tier A 信号源封闭枚举 = 唯四显式编码信号。"""
        source = schema["$defs"]["SignalSource"]
        assert set(source["enum"]) == {"title_prefix", "label", "staleness", "activity"}

    def test_labels_payload_keyset_closed_and_remove_absent(
        self, schema: dict[str, Any]
    ) -> None:
        """(a) proposal §3: labels_payload / apply_payload 封闭键集, properties 无 remove。"""
        for def_name in ("LabelsPayload", "ApplyPayload"):
            node = schema["$defs"][def_name]
            assert node.get("additionalProperties") is False, (
                f"{def_name} must close its keyset (additionalProperties:false)"
            )
            assert "remove" not in node.get("properties", {}), (
                f"{def_name} must not define a 'remove' field (裁定-8 只加不删)"
            )

    def test_apply_payload_idempotent_is_const_true(
        self, schema: dict[str, Any]
    ) -> None:
        """(a) idempotent 恒 true (差集 ⇒ 重复 apply 无操作, schema const 钉死)。"""
        idem = schema["$defs"]["ApplyPayload"]["properties"]["idempotent"]
        assert idem.get("const") is True

    def test_assessment_nullable_but_face_always_present(
        self, schema: dict[str, Any]
    ) -> None:
        """(a) assessment 在 IssueEntry 必填且可 null (契约保证面存在, 质量随 harness)。"""
        issue = schema["$defs"]["IssueEntry"]
        assert "assessment" in issue["required"]
        assessment_types = issue["properties"]["assessment"]["type"]
        assert set(assessment_types) == {"object", "null"}
        # 非 null assessment 必须带 provenance{harness, model_id} (裁定-3 第二层)
        assessment = issue["properties"]["assessment"]
        assert assessment["required"] == ["provenance"]
        prov = schema["$defs"]["AssessmentProvenance"]
        assert set(prov["required"]) == {"harness", "model_id"}

    def test_diff_section_shape(self, schema: dict[str, Any]) -> None:
        """(a) diff 段: new/closed/drift/baseline_run 四键 + drift 有 maxItems 护栏。"""
        diff = schema["$defs"]["DiffSection"]
        assert set(diff["required"]) == {"new", "closed", "drift", "baseline_run"}
        assert diff["properties"]["drift"]["maxItems"] == 100
        assert diff["properties"]["baseline_run"]["type"] == "boolean"

    def test_category_retained_values_documented(self, schema: dict[str, Any]) -> None:
        """(a) 两个 Tier A 保留值必须文档化: 'unknown' (无显式编码信号, 不猜)
        与 'conflict' (分类信号互斥不一致, 原样枚举绝不任选 — 任选即隐性猜测;
        B-3/B-3-followup)。渲染层据此把 conflict 当「待人工归边」而非分类失败。"""
        category = schema["$defs"]["IssueEntry"]["properties"]["category"]
        desc = category["description"]
        assert "unknown" in desc and "conflict" in desc
        assert "任选" in desc  # 不任选其一的纪律语句必须在场
        assert "conflict" in category["examples"]


# ── (a+) 校验器依赖方向 (B.3 修复: 生产层 SOT, 无 pytest 毒井) ─────────────────


class TestValidatorProvenance:
    """mini_validate 单点 SOT = 生产层 ``scripts/lib/schema_validate.py``。

    反事实: 若校验器退回 tests/ 直载 + pytest stub 注入形态, 源码断言
    (groom.py 含 'pytest' 字面量 / 实现不 lib.schema_validate) 与子进程
    硬阻断 pytest 的端到端断言必红。"""

    def test_groom_self_check_uses_production_validator(self) -> None:
        import groom  # scripts/ 已在 sys.path (本文件头部)

        from lib import schema_validate

        assert groom._mini_validate() is schema_validate.mini_validate

    def test_groom_source_has_no_pytest_coupling(self) -> None:
        """stub 注入逻辑删除后, groom.py 源码不得再含任何结构性 pytest
        耦合面 (import / sys.modules 注入 / ModuleType stub / importlib
        直载 tests) — 依赖方向修正的结构面证据 (docstring 里说明 B.3
        裁量的 'pytest' 字样不属耦合, 不在断言面)。"""
        import groom

        source = Path(groom.__file__).read_text(encoding="utf-8")
        for marker in ("import pytest", "sys.modules", "ModuleType", "importlib"):
            assert marker not in source, f"groom.py must not contain {marker!r}"

    def test_validator_importable_and_usable_without_pytest(self) -> None:
        """端到端: 子进程硬阻断 pytest (模拟无 pytest 生产环境), groom 的
        出厂自校验入口仍可取用并给出正确判定 (毒井移除的运行面证明)。"""
        scripts_dir = str(Path(__file__).resolve().parents[1] / "scripts")
        probe = (
            "import sys\n"
            "sys.modules['pytest'] = None  # block pytest (simulated production)\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import groom\n"
            "fn = groom._mini_validate()\n"
            "schema = {'type': 'object', 'required': ['a'],\n"
            "          'properties': {'a': {'type': 'integer'}},\n"
            "          'additionalProperties': False}\n"
            "assert fn({'a': 1}, schema) == []\n"
            "assert fn({'a': 'x'}, schema)\n"
            "print('ok')\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", probe, scripts_dir],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "ok"


# ── (b) 合法样例通过校验 ───────────────────────────────────────────────────────


class TestValidReport:
    def test_valid_report_passes_mini_validate(
        self, schema: dict[str, Any], valid_report: dict[str, Any]
    ) -> None:
        """(b) 真语料形态的合法样例通过纯 stdlib mini-validate。"""
        errors = mini_validate(valid_report, schema)
        assert errors == [], f"valid report rejected:\n" + "\n".join(errors)

    @pytest.mark.skipif(
        not HAS_JSONSCHEMA, reason="python3-jsonschema not installed"
    )
    def test_schema_loadable_by_standard_validator(
        self, schema: dict[str, Any]
    ) -> None:
        """(b) 标准验证器可直接加载 (check_schema 对 draft 2020-12 无抱怨)。"""
        Draft202012Validator.check_schema(schema)

    @pytest.mark.skipif(
        not HAS_JSONSCHEMA, reason="python3-jsonschema not installed"
    )
    def test_valid_report_passes_jsonschema(
        self, schema: dict[str, Any], valid_report: dict[str, Any]
    ) -> None:
        """(b) 同一样例经标准 draft 2020-12 验证器校验通过 (双路径一致)。"""
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(valid_report), key=lambda e: list(e.path))
        assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


# ── (c) 封闭键集与负向样例 (mini-validate 必须有牙齿) ─────────────────────────


class TestClosedKeysetAndNegative:
    def test_labels_payload_with_remove_is_invalid(
        self, schema: dict[str, Any], valid_report: dict[str, Any]
    ) -> None:
        """(c) proposal §3 核心负向: labels_payload 带 remove 字段 => 非法。"""
        report = copy.deepcopy(valid_report)
        report["issues"][0]["labels_payload"]["remove"] = ["stale"]
        _assert_invalid(report, schema, "remove")

    def test_apply_payload_with_remove_is_invalid(
        self, schema: dict[str, Any], valid_report: dict[str, Any]
    ) -> None:
        """(c) apply_payload 带 remove 字段 => 同样非法 (封闭键集到叶子)。"""
        report = copy.deepcopy(valid_report)
        report["issues"][0]["labels_payload"]["apply_payload"]["remove"] = ["bug"]
        _assert_invalid(report, schema, "remove")

    @pytest.mark.skipif(
        not HAS_JSONSCHEMA, reason="python3-jsonschema not installed"
    )
    def test_labels_payload_with_remove_rejected_by_jsonschema(
        self, schema: dict[str, Any], valid_report: dict[str, Any]
    ) -> None:
        """(c) 标准验证器同样拒绝 remove 字段 (双路径负向一致)。"""
        report = copy.deepcopy(valid_report)
        report["issues"][0]["labels_payload"]["remove"] = ["stale"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=report, schema=schema)

    def test_missing_toplevel_harness_invalid(
        self, schema: dict[str, Any], valid_report: dict[str, Any]
    ) -> None:
        """负向: 删顶层必填 harness => 非法。"""
        report = copy.deepcopy(valid_report)
        del report["harness"]
        _assert_invalid(report, schema, "harness")

    def test_wrong_snapshot_schema_version_invalid(
        self, schema: dict[str, Any], valid_report: dict[str, Any]
    ) -> None:
        """负向: snapshot_schema_version='2.0' 违 const '1.1' => 非法。"""
        report = copy.deepcopy(valid_report)
        report["snapshot_schema_version"] = "2.0"
        _assert_invalid(report, schema, "const")

    def test_numeric_confidence_top_level_invalid(
        self, schema: dict[str, Any], valid_report: dict[str, Any]
    ) -> None:
        """负向: 数值 confidence 字段 (裁定-7 明令不设) => 顶层封闭键集拒绝。"""
        report = copy.deepcopy(valid_report)
        report["confidence"] = 0.9
        _assert_invalid(report, schema, "confidence")

    def test_assessment_without_provenance_invalid(
        self, schema: dict[str, Any], valid_report: dict[str, Any]
    ) -> None:
        """负向: 非 null assessment 缺 provenance => 非法 (裁定-3 复用门比对键不可缺)。"""
        report = copy.deepcopy(valid_report)
        del report["issues"][1]["assessment"]["provenance"]
        _assert_invalid(report, schema, "provenance")

    def test_signal_source_outside_enum_invalid(
        self, schema: dict[str, Any], valid_report: dict[str, Any]
    ) -> None:
        """负向: 语义猜测型信号源 ('semantic_guess') 不在封闭枚举 => 非法 (裁定-7)。"""
        report = copy.deepcopy(valid_report)
        report["issues"][0]["signals"] = [
            {"source": "semantic_guess", "rule": "vibe", "detail": "看起来像 bug"}
        ]
        _assert_invalid(report, schema, "enum")

    def test_idempotent_false_invalid(
        self, schema: dict[str, Any], valid_report: dict[str, Any]
    ) -> None:
        """负向: idempotent=false 违 const true => 非法 (差集结构保证)。"""
        report = copy.deepcopy(valid_report)
        report["issues"][0]["labels_payload"]["apply_payload"]["idempotent"] = False
        _assert_invalid(report, schema, "const")

    def test_unknown_category_with_nonempty_signals_shape_still_structural(
        self, schema: dict[str, Any], valid_report: dict[str, Any]
    ) -> None:
        """结构面补充: unknown 条目的 signals/confidence_source 为空数组是 Tier A
        引擎行为面 (TASK-002/TASK-008 fixture), schema 只钉类型 — 本测试钉住
        该形态本身合法, 防未来 schema 误收窄把负面 fixture 形态误杀。"""
        report = copy.deepcopy(valid_report)
        unknown_entry = report["issues"][2]
        assert unknown_entry["category"] == "unknown"
        assert unknown_entry["signals"] == []
        assert unknown_entry["confidence_source"] == []
        errors = mini_validate(report, schema)
        assert errors == []
