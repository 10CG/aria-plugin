"""TASK-009 配置注册与指令结构测试；不验证 CLI 拒绝或生产采用。

缺默认键、非 bool false、缺严格例外或通用回落表漏掉例外均应判红。
行为级拒绝属于 TASK-004，Skill 指令的 Rule #6 验证属于 TASK-017。
"""

import json
import re
import unittest
from pathlib import Path


CONFIG_LOADER = Path(__file__).resolve().parents[2] / "config-loader"
GUARD_KEY = "require_same_admitted_roles"
GUARD_FIELD = f"audit.{GUARD_KEY}"


class ConfigRegistrationTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.defaults = json.loads(
            (CONFIG_LOADER / "DEFAULTS.json").read_text(encoding="utf-8")
        )
        self.skill = (CONFIG_LOADER / "SKILL.md").read_text(encoding="utf-8")

    def _strict_exception(self):
        section = re.search(
            r"^### 审计执行器严格例外\n(.*?)(?=^#{1,3} |\Z)",
            self.skill,
            re.MULTILINE | re.DOTALL,
        )
        if section is None:
            self.fail("缺少审计执行器严格例外，通用回落可能静默关门")
        return section.group(1)

    def test_defaults_register_guard_as_boolean_false(self):
        self.assertIn(GUARD_KEY, self.defaults["audit"], "DEFAULTS 缺少守卫默认键")
        value = self.defaults["audit"][GUARD_KEY]
        self.assertIs(type(value), bool, "守卫默认值必须是 bool，不能是整数 0")
        self.assertIs(value, False, "注册不能提前激活守卫")

    def test_field_rule_declares_boolean_false(self):
        rule = re.search(
            rf"^{re.escape(GUARD_FIELD)}:\n((?:[ \t]+[^\n]*\n)+)",
            self.skill,
            re.MULTILINE,
        )
        if rule is None:
            self.fail("字段验证规则缺少守卫注册")
        self.assertRegex(rule.group(1), r"(?m)^  type: boolean\s*$")
        self.assertRegex(rule.group(1), r"(?m)^  default: false\s*$")

    def test_general_fallback_table_explicitly_defers_to_strict_exception(self):
        rows = {}
        for line in self.skill.splitlines():
            if line.startswith("| "):
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if len(cells) == 2:
                    rows[cells[0]] = cells[1]
        for scenario, legacy_action in (
            ("JSON 格式错误", "返回默认值"),
            ("字段类型错误", "使用该字段默认值"),
        ):
            with self.subTest(scenario=scenario):
                self.assertIn(scenario, rows)
                self.assertIn("严格例外", rows[scenario], "通用回落表未限定严格例外")
                self.assertIn(legacy_action, rows[scenario], "其他字段的既有容错应保留")

    def test_raw_fixed_sources_are_validated_before_defaults_and_routing(self):
        section = self._strict_exception()
        for token in ("分流选择", ".aria/config.json", "DEFAULTS.json", "object"):
            with self.subTest(token=token):
                self.assertIn(token, section)
        self.assertRegex(section, r"先读取原始 JSON[\s\S]*再合并默认值")
        self.assertRegex(section, r"优先于[\s\S]*加载流程[\s\S]*调用方式[\s\S]*错误处理表")
        self.assertRegex(section, r"JSON[\s\S]*损坏[\s\S]*报配置错误[\s\S]*中止")
        self.assertIn("不得", section)
        self.assertIn("回落", section)

    def test_raw_guard_types_cannot_silently_disable_guard(self):
        section = self._strict_exception()
        self.assertIn(GUARD_FIELD, section)
        self.assertIn("type(value) is bool", section)
        for invalid_type in ("字符串", "null", "0", "1", "数组", "对象"):
            with self.subTest(invalid_type=invalid_type):
                self.assertIn(invalid_type, section)
        self.assertRegex(section, r"均报配置错误")
        self.assertRegex(section, r"禁止[^\n]*truthy[^\n]*转换")
        self.assertRegex(section, r"不适用[^\n]*字段类型[^\n]*回落")

    def test_missing_project_key_is_distinct_from_broken_defaults(self):
        section = self._strict_exception()
        self.assertRegex(section, r"项目配置文件或该键缺失[^\n]*DEFAULTS[^\n]*false")
        self.assertRegex(section, r"DEFAULTS[^\n]*必须存在[^\n]*注册[^\n]*boolean false")
        self.assertRegex(section, r"缺注册[^\n]*非法类型[^\n]*缺省成功")
        self.assertRegex(section, r"其他字段[^\n]*通用容错")


if __name__ == "__main__":
    unittest.main()
