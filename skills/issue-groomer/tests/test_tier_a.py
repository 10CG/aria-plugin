"""Tests for lib/tier_a.py — issue-groomer Tier A rule engine (TASK-002).

Covers the four TASK-002 verification bullets:
  1. 裁定-1 覆盖非合并: project .aria/labels.yaml whole-file override + builtin
     fallback + fail-closed on broken project file (LoaderOverrideTests).
  2. 逐信号 confidence / unknown 不猜: enumerated signal sets with source
     strings, category resolution (agree/unknown/conflict), and the literal
     "no explicit signal -> category=unknown + signals=[]" case
     (ClassifyCategoryTests).
  3. 时钟 seam: injectable now for staleness tiers incl. boundary days
     (7/30/90) and timezone normalization (ClassifyClockTests /
     ClassifyActivityTests).
  4. SC-9 三层自检: named check per injected defect layer (prefix table /
     category-key table / label table) + restricted-yaml parser structural
     rejections (TaxonomyValidationTests / ParserTests).

Fixture 形态取自真语料 scratchpad/issues-open-full-18repos-2026-10-18.json
(2026-10-18 快照, 378 条; 条目逐字内嵌并注明仓号 — 裁定-7 防形态脱节)。
stdlib-only unittest, 与 phase-c-integrator/tests 同风格 (无网络/无真 API)。
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

# Add scripts/ to path for direct module import (house convention).
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))

from lib import tier_a  # noqa: E402


# ---------------------------------------------------------------- 语料真形态 fixtures
# 逐字取自 scratchpad/issues-open-full-18repos-2026-10-18.json (repo/number 即出处)。

CORPUS_BUG_PREFIX = {  # Aria#208 — "[缺陷]" 前缀, labels 空
    "repo": "Aria",
    "number": 208,
    "title": "[缺陷][归档闸门] C 分级死码检查对非 Python 符号结构性失明 — 任何 shell/yaml/配置类交付物都得「判不了死码 → warn」",
    "labels": [],
    "created": "2026-09-07",
    "updated": "2026-09-08",
}

CORPUS_SECURITY_PREFIX = {  # aria-plugin#219 — "[安全]" 前缀
    "repo": "aria-plugin",
    "number": 219,
    "title": "[安全][hooks][平台] v1.75.0 secret-guard/secret-scan 仅 Linux 验证 — Windows/MINGW64 实测缺口（grep/sed 差异 + 进程 ~10× 慢放大 5s 超时 fail-open；#154 报告环境即 MINGW64）",
    "labels": [],
    "created": "2026-10-15",
    "updated": "2026-10-16",
}

CORPUS_TRACKER_PREFIX = {  # Aria#216 — "[Archive Tracker]" 复合前缀
    "repo": "Aria",
    "number": 216,
    "title": "[Archive Tracker] rule6-description-change-trigger-eval-lane — 上游 skill-creator 反馈未发出 (归档残留)",
    "labels": [],
    "created": "2026-09-17",
    "updated": "2026-10-16",
}

CORPUS_PRIORITY_PREFIX = {  # Aether#521 — "[P3]" 优先级标记, 默认层刻意不收
    "repo": "Aether",
    "number": 521,
    "title": "[P3][cli/doctor] registry_image_availability 空 jobs 列表照报 PASS「no images found」(#437 家族最后一条活缺口, #518 R1 拆出)",
    "labels": [],
    "created": "2026-10-18",
    "updated": "2026-10-18",
}

CORPUS_LABEL_SIGNAL = {  # SilkNode#1219 — label 信号 (area/* priority/* 非分类)
    "repo": "SilkNode",
    "number": 1219,
    "title": "[deploy] deploy.sh --rollback 用不了（回滚锚点恒为 none）+ 手册 24 处重建 web 没固定镜像（§8.4 紧急切色会重建成崩溃版本）",
    "labels": ["area/deploy-ci", "priority/p2-high", "type/bug"],
    "created": "2026-10-07",
    "updated": "2026-10-14",
}

CORPUS_LABEL_FEATURE = {  # SilkNode#94 — type/feature label; 时钟 fixture 锚 (updated 2026-05-18)
    "repo": "SilkNode",
    "number": 94,
    "title": "[Luxeno 需求] BYOM — 用户自带模型端点注册（支持开源模型成本选择）",
    "labels": ["area/ai-features", "area/integrations", "priority/p3-low", "type/feature"],
    "created": "2026-04-08",
    "updated": "2026-05-18",
}


def _base_issue(**overrides) -> dict:
    """语料字段集基线 (title/labels/created/updated 与语料同形态), 可覆写。"""
    issue = {
        "repo": "Aria",
        "number": 999,
        "title": "plain title no bracket prefix",
        "labels": [],
        "created": "2026-10-01",
        "updated": "2026-10-01",
    }
    issue.update(overrides)
    return issue


def _mini_taxonomy_text(prefixes: str, signals: str = "", categories: str = "chore: chore") -> str:
    return (
        "version: 1\n"
        "categories:\n"
        f"  {categories}\n"
        "title_prefixes:\n"
        f"{prefixes}"
        "label_signals:\n"
        f"{signals}"
    )


class ParserTests(unittest.TestCase):
    """受限行级 yaml parser: 受控结构全接受, 未声明形态全拒绝 (fail-closed)。"""

    def test_parse_full_supported_shapes(self):
        text = (
            "# header comment\n"
            "version: 1\n"
            "categories:\n"
            "  bug: bug  # trailing comment\n"
            "  '[安全]': security\n"
            "title_prefixes:\n"
            '  "[bug]": bug\n'
            "label_signals:\n"
            "  type/bug: bug\n"
            "watch_repos:\n"
            "  - Aether\n"
            "  - SilkNode\n"
        )
        raw = tier_a._parse_simple_yaml(text)
        self.assertEqual(raw["version"], 1)
        self.assertEqual(raw["categories"], {"bug": "bug", "[安全]": "security"})
        self.assertEqual(raw["title_prefixes"], {"[bug]": "bug"})
        self.assertEqual(raw["label_signals"], {"type/bug": "bug"})
        self.assertEqual(raw["watch_repos"], ["Aether", "SilkNode"])

    def test_quoted_value_and_int_coercion(self):
        raw = tier_a._parse_simple_yaml('version: 1\nempty: ""\nname: "a # not comment"\n')
        self.assertEqual(raw["version"], 1)
        self.assertEqual(raw["empty"], "")
        self.assertEqual(raw["name"], "a # not comment")

    def test_tab_in_indentation_rejected(self):
        with self.assertRaisesRegex(ValueError, r"tab in indentation"):
            tier_a._parse_simple_yaml("categories:\n\tbug: bug\n")

    def test_duplicate_top_level_key_rejected(self):
        with self.assertRaisesRegex(ValueError, r"duplicate top-level key 'categories'"):
            tier_a._parse_simple_yaml("categories:\n  a: a\ncategories:\n  b: b\n")

    def test_duplicate_subkey_rejected(self):
        with self.assertRaisesRegex(ValueError, r"duplicate key 'bug' in block"):
            tier_a._parse_simple_yaml("categories:\n  bug: bug\n  bug: feature\n")

    def test_unquoted_bracket_key_rejected(self):
        with self.assertRaisesRegex(ValueError, r"must be quoted"):
            tier_a._parse_simple_yaml("title_prefixes:\n  [bug]: bug\n")

    def test_deeper_nesting_rejected(self):
        with self.assertRaisesRegex(ValueError, r"deeper nesting"):
            tier_a._parse_simple_yaml("categories:\n  bug:\n    x: y\n")

    def test_list_and_mapping_mixed_in_block_rejected(self):
        with self.assertRaisesRegex(ValueError, r"cannot mix"):
            tier_a._parse_simple_yaml("block:\n  a: b\n  - item\n")

    def test_indented_line_outside_block_rejected(self):
        with self.assertRaisesRegex(ValueError, r"outside any block"):
            tier_a._parse_simple_yaml("  orphan: value\n")

    def test_inconsistent_block_indent_rejected(self):
        with self.assertRaisesRegex(ValueError, r"indent 4 != block indent 2"):
            tier_a._parse_simple_yaml("block:\n  a: b\n    c: d\n")

    def test_colonless_line_rejected(self):
        with self.assertRaisesRegex(ValueError, r"no colon"):
            tier_a._parse_simple_yaml("just text\n")

    def test_illegal_bare_key_charset_rejected(self):
        with self.assertRaisesRegex(ValueError, r"illegal bare key"):
            tier_a._parse_simple_yaml("bad key: 1\n")

    def test_non_string_list_item_rejected(self):
        with self.assertRaisesRegex(ValueError, r"list items must be strings"):
            tier_a._parse_simple_yaml("block:\n  - 42\n")


class TaxonomyValidationTests(unittest.TestCase):
    """SC-9 三层一致性自检: 每层注错一份, 具名失败必出 (fixture 反事实面在
    TASK-008, 此处为实现面直测)。"""

    def _tax(self, **sections) -> dict:
        tax = {
            "version": 1,
            "categories": {"bug": "bug", "feature": "feature"},
            "title_prefixes": {"[bug]": "bug"},
            "label_signals": {"type/bug": "bug"},
        }
        tax.update(sections)
        return tax

    def test_consistent_taxonomy_passes(self):
        self.assertEqual(tier_a.validate_taxonomy(self._tax()), [])

    def test_layer1_prefix_to_unknown_category(self):
        problems = tier_a.validate_taxonomy(self._tax(title_prefixes={"[x]": "nope"}))
        self.assertTrue(any(p.startswith("prefix-unknown-category") for p in problems))

    def test_layer2_canonical_label_collision(self):
        problems = tier_a.validate_taxonomy(
            self._tax(categories={"bug": "kind/x", "feature": "kind/x"})
        )
        self.assertTrue(any(p.startswith("canonical-label-collision") for p in problems))

    def test_layer2_empty_categories(self):
        problems = tier_a.validate_taxonomy(self._tax(categories={}))
        self.assertTrue(any(p.startswith("categories-empty") for p in problems))

    def test_layer2_empty_canonical_label(self):
        problems = tier_a.validate_taxonomy(self._tax(categories={"bug": "  "}))
        self.assertTrue(any(p.startswith("canonical-label-empty") for p in problems))

    def test_layer3_label_signal_to_unknown_category(self):
        problems = tier_a.validate_taxonomy(self._tax(label_signals={"kind/x": "nope"}))
        self.assertTrue(any(p.startswith("label-signal-unknown-category") for p in problems))

    def test_layer3_canonical_label_contradiction(self):
        # label "bug" 是 bug 的规范名, 却在 label_signals 里指向 feature — 自相矛盾。
        problems = tier_a.validate_taxonomy(
            self._tax(label_signals={"bug": "feature", "type/bug": "bug"})
        )
        self.assertTrue(any(p.startswith("canonical-label-contradiction") for p in problems))

    def test_parse_taxonomy_rejects_unknown_top_key(self):
        with self.assertRaisesRegex(ValueError, "unknown top-level key"):
            tier_a.parse_taxonomy({"version": 1, "title_prefix": {}, "categories": {}, "label_signals": {}})

    def test_parse_taxonomy_rejects_wrong_version_type(self):
        raw = {"version": "1", "categories": {"a": "a"}, "title_prefixes": {}, "label_signals": {}}
        with self.assertRaisesRegex(ValueError, "version must be int"):
            tier_a.parse_taxonomy(raw)

    def test_parse_taxonomy_rejects_non_mapping_section(self):
        raw = {"version": 1, "categories": ["bug"], "title_prefixes": {}, "label_signals": {}}
        with self.assertRaisesRegex(ValueError, "must be a mapping"):
            tier_a.parse_taxonomy(raw)

    def test_load_taxonomy_text_fail_closed_on_inconsistency(self):
        bad = _mini_taxonomy_text('  "[x]": nope\n')
        with self.assertRaisesRegex(ValueError, "taxonomy inconsistent"):
            tier_a.load_taxonomy_text(bad)

    def test_load_taxonomy_text_fail_closed_on_parse_error(self):
        with self.assertRaisesRegex(ValueError, "parse error"):
            tier_a.load_taxonomy_text("categories:\n\tbug: bug\n")


class LoaderOverrideTests(unittest.TestCase):
    """裁定-1: 项目级 .aria/labels.yaml 整体覆盖默认层 (覆盖非合并)。"""

    PROJECT_YAML = _mini_taxonomy_text('  "[chore]": chore\n', signals="  chore-issue: chore\n")

    def test_project_file_whole_file_override_not_merge(self):
        with tempfile.TemporaryDirectory() as root:
            aria_dir = Path(root) / ".aria"
            aria_dir.mkdir()
            (aria_dir / "labels.yaml").write_text(self.PROJECT_YAML, encoding="utf-8")
            tax = tier_a.resolve_taxonomy(project_root=root)
            # 覆盖非合并: 内置层的 bug/feature/security/tracker 不应渗入项目层。
            self.assertEqual(set(tax["categories"]), {"chore"})
            self.assertNotIn("[bug]", tax["title_prefixes"])
            results = tier_a.classify(
                [
                    _base_issue(title="[bug] crash", labels=["type/bug"]),
                    _base_issue(title="[chore] cleanup", labels=["chore-issue"]),
                ],
                taxonomy=tax,
                now=datetime(2026, 10, 19),
            )
            # 内置信号源全部失效 (非合并的证据): "[bug]"/type/bug 不再命中任何分类。
            self.assertEqual(results[0]["category"], "unknown")
            self.assertEqual(
                [s["kind"] for s in results[0]["signals"]],
                ["staleness"],  # 仅剩属性信号, 零分类信号
            )
            self.assertEqual(results[1]["category"], "chore")

    def test_project_file_broken_fail_closed_no_silent_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            aria_dir = Path(root) / ".aria"
            aria_dir.mkdir()
            (aria_dir / "labels.yaml").write_text(
                _mini_taxonomy_text('  "[x]": nope\n'), encoding="utf-8"
            )
            # 项目文件在场但非法 → 报错, 绝不静默回落内置层。
            with self.assertRaisesRegex(ValueError, "taxonomy inconsistent"):
                tier_a.resolve_taxonomy(project_root=root)

    def test_project_file_absent_falls_back_to_builtin(self):
        with tempfile.TemporaryDirectory() as root:
            tax = tier_a.resolve_taxonomy(project_root=root)
            self.assertEqual(tax["_meta"]["layer"], "builtin")
            self.assertIn("[缺陷]", tax["title_prefixes"])

    def test_no_project_root_means_builtin(self):
        tax = tier_a.resolve_taxonomy()
        self.assertEqual(tax["_meta"]["layer"], "builtin")

    def test_explicit_path_loader(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "labels.yaml"
            p.write_text(self.PROJECT_YAML, encoding="utf-8")
            tax = tier_a.load_taxonomy_file(p)
            self.assertEqual(tax["_meta"]["layer"], "explicit")
            self.assertEqual(set(tax["categories"]), {"chore"})


class DefaultLayerTests(unittest.TestCase):
    """内置保守默认层 (config/labels-default.yaml) 契约。"""

    @classmethod
    def setUpClass(cls):
        cls.tax = tier_a.load_builtin_taxonomy()

    def test_default_has_exactly_four_generic_category_keys(self):
        self.assertEqual(
            set(self.tax["categories"]), {"bug", "feature", "security", "tracker"}
        )

    def test_default_conservatism_priority_prefixes_excluded(self):
        # [P0]-[P4] 是优先级标记非分类信号, 默认层刻意不收。
        for p in ("[P0]", "[P1]", "[P2]", "[P3]", "[P4]"):
            self.assertNotIn(p, self.tax["title_prefixes"])

    def test_default_evidence_anchored_prefixes_present(self):
        for p, cat in [
            ("[缺陷]", "bug"),
            ("[bug]", "bug"),
            ("[安全]", "security"),
            ("[security]", "security"),
            ("[tracker]", "tracker"),
            ("[Archive Tracker]", "tracker"),
            ("[Feature]", "feature"),
            ("[enhancement]", "feature"),
        ]:
            self.assertEqual(self.tax["title_prefixes"].get(p), cat, p)

    def test_builtin_hash_stable_and_content_sensitive(self):
        again = tier_a.load_builtin_taxonomy()
        self.assertEqual(tier_a.taxonomy_hash(self.tax), tier_a.taxonomy_hash(again))
        # 内容变化 → hash 变
        mutated = dict(self.tax)
        mutated["title_prefixes"] = dict(self.tax["title_prefixes"])
        mutated["title_prefixes"]["[new]"] = "bug"
        self.assertNotEqual(tier_a.taxonomy_hash(self.tax), tier_a.taxonomy_hash(mutated))

    def test_hash_declaration_order_sensitive_and_meta_blind(self):
        a = {
            "version": 1,
            "categories": {"a": "a", "b": "b"},
            "title_prefixes": {},
            "label_signals": {},
        }
        b = {
            "version": 1,
            "categories": {"b": "b", "a": "a"},
            "title_prefixes": {},
            "label_signals": {},
            "_meta": {"layer": "project", "source": "somewhere"},
        }
        # 同内容不同声明顺序 → 不同 hash (保守触发重分类); _meta 不入 hash。
        self.assertNotEqual(tier_a.taxonomy_hash(a), tier_a.taxonomy_hash(b))
        a_meta = dict(a)
        a_meta["_meta"] = {"layer": "builtin", "source": "x"}
        self.assertEqual(tier_a.taxonomy_hash(a), tier_a.taxonomy_hash(a_meta))


class ClassifyCategoryTests(unittest.TestCase):
    """逐信号 confidence + category 裁决 (agree / unknown / conflict)。"""

    NOW = datetime(2026, 10, 19)

    def test_corpus_bug_prefix_signal(self):
        (result,) = tier_a.classify([CORPUS_BUG_PREFIX], taxonomy=None, now=self.NOW)
        self.assertEqual(result["category"], "bug")
        self.assertEqual(result["repo"], "Aria")
        self.assertEqual(result["number"], 208)
        prefix_signals = [s for s in result["signals"] if s["kind"] == "title-prefix"]
        self.assertEqual(len(prefix_signals), 1)
        self.assertEqual(prefix_signals[0]["source"], "title-prefix:[缺陷]")
        self.assertEqual(prefix_signals[0]["value"], "[缺陷]")
        self.assertEqual(prefix_signals[0]["category"], "bug")

    def test_corpus_security_and_tracker_prefixes(self):
        results = tier_a.classify(
            [CORPUS_SECURITY_PREFIX, CORPUS_TRACKER_PREFIX], now=self.NOW
        )
        self.assertEqual(results[0]["category"], "security")
        self.assertEqual(
            [s["source"] for s in results[0]["signals"] if s["kind"] == "title-prefix"],
            ["title-prefix:[安全]"],
        )
        self.assertEqual(results[1]["category"], "tracker")

    def test_corpus_label_signal_with_non_category_labels_ignored(self):
        (result,) = tier_a.classify([CORPUS_LABEL_SIGNAL], now=self.NOW)
        self.assertEqual(result["category"], "bug")
        label_signals = [s for s in result["signals"] if s["kind"] == "label"]
        self.assertEqual(len(label_signals), 1)  # area/* priority/* 不产信号
        self.assertEqual(label_signals[0]["source"], "label:type/bug")

    def test_no_explicit_signal_unknown_with_empty_signals(self):
        # 负面判据的操作化形态: 无前缀命中 + 无已知 label + updated/comments_count
        # 均缺席 → 恰为 category=unknown + signals=[] (裁定-7 字面形态)。
        (result,) = tier_a.classify(
            [{"repo": "Aria", "number": 1, "title": "plain", "labels": []}], now=self.NOW
        )
        self.assertEqual(result["category"], "unknown")
        self.assertEqual(result["signals"], [])

    def test_no_category_signal_but_staleness_present_still_unknown(self):
        # 语料常态形态: updated 在场 → staleness 枚举, 但零分类信号 → 仍 unknown,
        # 且信号集中不存在任何带 category 的分类信号 (不猜)。
        (result,) = tier_a.classify([CORPUS_PRIORITY_PREFIX], now=self.NOW)
        self.assertEqual(result["category"], "unknown")
        self.assertTrue(result["signals"], "staleness signal expected")
        self.assertTrue(all(s["kind"] != "title-prefix" and s["kind"] != "label" for s in result["signals"]))
        self.assertTrue(all(s["source"].startswith("staleness:") for s in result["signals"]))

    def test_conflicting_signals_yield_conflict_not_guess(self):
        (result,) = tier_a.classify(
            [_base_issue(title="[bug] crash", labels=["type/feature"])], now=self.NOW
        )
        self.assertEqual(result["category"], "conflict")
        kinds = [s["kind"] for s in result["signals"]]
        self.assertEqual(kinds[:2], ["title-prefix", "label"])  # 冲突双方都在证据集里

    def test_signal_order_is_deterministic(self):
        (result,) = tier_a.classify(
            [_base_issue(title="[bug] x", labels=["type/bug"], comments_count=3)],
            now=self.NOW,
        )
        self.assertEqual(
            [s["kind"] for s in result["signals"]],
            ["title-prefix", "label", "staleness", "activity"],
        )

    def test_classify_revalidates_hand_built_taxonomy(self):
        bad = {
            "version": 1,
            "categories": {"bug": "bug"},
            "title_prefixes": {"[x]": "nope"},
            "label_signals": {},
        }
        with self.assertRaisesRegex(ValueError, "taxonomy inconsistent"):
            tier_a.classify([_base_issue()], taxonomy=bad, now=self.NOW)

    def test_missing_identity_field_raises_with_index(self):
        with self.assertRaisesRegex(ValueError, r"issue\[0\] missing required identity"):
            tier_a.classify([{"title": "x"}], now=self.NOW)

    def test_malformed_updated_raises(self):
        with self.assertRaisesRegex(ValueError, "unparseable ISO datetime"):
            tier_a.classify([_base_issue(updated="not-a-date")], now=self.NOW)

    def test_non_string_comments_count_raises(self):
        with self.assertRaisesRegex(ValueError, "comments_count must be an int"):
            tier_a.classify([_base_issue(comments_count="5")], now=self.NOW)

    def test_bool_comments_count_raises(self):
        with self.assertRaisesRegex(ValueError, "comments_count must be an int"):
            tier_a.classify([_base_issue(comments_count=True)], now=self.NOW)

    def test_non_string_title_raises(self):
        # E-4: title 在场但非 str (int/dict/...) ⇒ 显式 ValueError —
        # str.startswith 对非 str 会 AttributeError 炸穿; 静默跳过更糟
        # (丢主要存量分类信号面)。缺席仍按 "" (无信号, 不是错误)。
        for bad in (123, ["[bug]"], {"prefix": "[bug]"}, True):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "title must be a string or absent"):
                    tier_a.classify([_base_issue(title=bad)], now=self.NOW)

    def test_title_absent_treated_as_empty(self):
        # 对照: title 键缺席 ⇒ 无前缀信号, 条目照常分类 (缺席=无信号)。
        issue = _base_issue()
        del issue["title"]
        (result,) = tier_a.classify([issue], now=self.NOW)
        self.assertEqual(result["category"], "unknown")
        self.assertFalse(any(s["kind"] == "title-prefix" for s in result["signals"]))


class ClassifyClockTests(unittest.TestCase):
    """时钟 seam: now 注入跨档判定 + 边界含左不含右 + 时区/异常形态。"""

    def test_staleness_tiers_by_injected_now(self):
        # 锚: CORPUS_LABEL_FEATURE.updated = 2026-05-18
        cases = [
            (datetime(2026, 5, 18), "<7d"),      # age 0
            (datetime(2026, 5, 24), "<7d"),      # age 6
            (datetime(2026, 5, 25), "7-30d"),    # age 7 (边界含左)
            (datetime(2026, 6, 16), "7-30d"),    # age 29
            (datetime(2026, 6, 17), "30-90d"),   # age 30 (边界含左)
            (datetime(2026, 8, 15), "30-90d"),   # age 89
            (datetime(2026, 8, 16), ">90d"),     # age 90 (边界含左)
            (datetime(2027, 1, 1), ">90d"),
        ]
        for now, expected in cases:
            with self.subTest(now=now):
                (result,) = tier_a.classify([CORPUS_LABEL_FEATURE], now=now)
                (staleness,) = [s for s in result["signals"] if s["kind"] == "staleness"]
                self.assertEqual(staleness["source"], f"staleness:{expected}")

    def test_same_issue_crossing_tier_boundary_reclassifies(self):
        # 复用规则判据输入 (时间敏感字段): 仅换 now 跨档 → staleness 信号变化。
        early = tier_a.classify([CORPUS_LABEL_FEATURE], now=datetime(2026, 5, 20))[0]
        late = tier_a.classify([CORPUS_LABEL_FEATURE], now=datetime(2026, 9, 1))[0]
        self.assertEqual(early["signals"][-1]["value"], "<7d")
        self.assertEqual(late["signals"][-1]["value"], ">90d")

    def test_now_accepts_date_object(self):
        (result,) = tier_a.classify([CORPUS_LABEL_FEATURE], now=date(2026, 6, 17))
        (staleness,) = [s for s in result["signals"] if s["kind"] == "staleness"]
        self.assertEqual(staleness["value"], "30-90d")

    def test_aware_datetimes_normalized_to_naive_utc(self):
        # updated 带 Z (aware) vs 注入 aware now: 归一到 naive UTC 再比。
        issue = _base_issue(updated="2026-05-18T10:00:00Z")
        (result,) = tier_a.classify(
            [issue], now=datetime.fromisoformat("2026-05-25T00:00:00+00:00")
        )
        (staleness,) = [s for s in result["signals"] if s["kind"] == "staleness"]
        # age = 6d14h → 6 天 (floor) → <7d
        self.assertEqual(staleness["value"], "<7d")

    def test_future_updated_clamps_to_youngest_tier(self):
        issue = _base_issue(updated="2030-01-01")
        (result,) = tier_a.classify([issue], now=datetime(2026, 10, 19))
        (staleness,) = [s for s in result["signals"] if s["kind"] == "staleness"]
        self.assertEqual(staleness["value"], "<7d")

    def test_now_none_uses_system_clock(self):
        (result,) = tier_a.classify([CORPUS_BUG_PREFIX])
        tiers = {s["value"] for s in result["signals"] if s["kind"] == "staleness"}
        self.assertIn(tiers.pop(), tier_a.STALENESS_TIERS)

    def test_now_none_takes_utc_not_local_clock(self):
        # 模块 UTC 纪律 (B.3): now=None 的系统时钟必须取 UTC (naive),
        # 不是本地钟 — 比较基线是 naive UTC, 本地钟在非 UTC 主机上会
        # 系统性偏移 staleness 档。强制非 UTC 本地时区 (TZ+tzset) 下本地
        # 钟与 UTC 差数小时; 若实现退回 datetime.now() (本地), 差值断言必红。
        # (本机若本来就是 UTC 主机, 不加 TZ 强制则本测试退化为恒绿 —
        # tzset 注入保证它在任何主机上都有牙齿。)
        old_tz = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "America/New_York"  # UTC-5/UTC-4, 与 UTC 差 ≥4h
            time.tzset()
            got = tier_a._resolve_now(None)
            self.assertIsNone(got.tzinfo)  # naive-UTC 比较基线
            utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
            self.assertLess(abs((got - utc_now).total_seconds()), 300)  # 5min 容差
        finally:
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            time.tzset()

    def test_now_invalid_type_raises(self):
        with self.assertRaisesRegex(ValueError, "now must be datetime/date/None"):
            tier_a.classify([_base_issue()], now="2026-10-19")


class ClassifyActivityTests(unittest.TestCase):
    """活跃度档 (comments_count): 全分割边界 + 缺席不产信号。"""

    NOW = datetime(2026, 10, 19)

    def test_activity_tier_boundaries(self):
        for count, expected in [
            (0, "0"),
            (1, "1-2"),
            (2, "1-2"),
            (3, "3-9"),
            (9, "3-9"),
            (10, "10+"),
            (55, "10+"),
            (-1, "0"),  # 异常负计数确定性归 0 档
        ]:
            with self.subTest(comments_count=count):
                (result,) = tier_a.classify(
                    [_base_issue(comments_count=count)], now=self.NOW
                )
                (activity,) = [s for s in result["signals"] if s["kind"] == "activity"]
                self.assertEqual(activity["source"], f"activity:{expected}")

    def test_missing_comments_count_no_activity_signal(self):
        # 缺席不是 0 — 不产 activity 信号 (不猜)。
        (result,) = tier_a.classify([_base_issue()], now=self.NOW)
        self.assertFalse(any(s["kind"] == "activity" for s in result["signals"]))


if __name__ == "__main__":
    unittest.main()
