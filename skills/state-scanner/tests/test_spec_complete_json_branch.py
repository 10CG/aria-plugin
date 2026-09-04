#!/usr/bin/env python3
"""Aria#192: `_classify_file_occurrence` 的 `.json` 分支 (2026-09-04).

**症状**: sibling-spec-probe 归档时 D.2 gate 报 `verdict=warn`, 唯一 unverified claim
的原因是 ``symbol 'not_established' unclassified reference form``, 点名的两个
`unclassified_files` 都是 JSON (``ab-suite/audit-engine.json`` 与该次 AB run 的
``eval_metadata.json``) —— 而该符号在生产代码 ``sibling_spec_probe.py`` 与
``references/execution-modes.md`` 契约节里都有真实引用。

**根因** (实测, 非推断): `.json` 此前落在通用「代码性」分支, 文本先过
``_strip_comments_and_docstrings``。那个函数按 ``#`` 截到行尾, 而 ``#`` 在 JSON 里
从来不是注释。eval prompt 里含 ``aria-plugin#122`` / ``### Round N`` 这类 ``#``,
被截断后该行的字符串不再闭合 ⇒ 随后 ``_strip_string_literals`` 的状态机失步、不再
剥除该串 ⇒ 串内的符号被判成「剥注释后仍在代码体出现」⇒ unclassified ⇒ warn。

**处置**: `.json` 单列一支, 与非 CI yaml 同归宿 —— 声明性数据不是运行时调用面。
真正的注册面 (hooks.json / `.aria/config.json`) 由上游 ``_is_hooks_or_config_path``
先行拦截; 以字面脚本路径发起调用的 JSON (package.json scripts 段) 仍算 alive。

**极性说明 (有意, 非疏漏)**: 本改动把 JSON 从 `unclassified`(→warn) 移到
`prose`。`prose_files` 不参与 ``classify_symbol_liveness`` 的状态判定, 所以效果等同
「不计入任一桶」—— 噪声消失; 代价是「有 Python 定义 ∧ 全部引用只在 .md/.json」的
符号从 warn 变成 dead(block)。那正是 C 分级证据闸要判的高置信死代码 (数据文件不是
生产引用), 故为设计而非回归 —— 由 ``test_polarity_definition_plus_data_only_is_dead``
显式钉住: 将来若要改回 fail-toward-warn, 必须先改这条测试。

每条测试的「它怎么会红」写在各自 docstring 里 (memory `test-claims-vs-verifies`)。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from _helpers import tmp_project, write_file

# `_helpers` 已把 scripts/ 放进 sys.path —— 不要再插一次 position 0, 否则 scripts/
# 会盖过 state-scanner root 上的顶层 `lib` 包 (与 test_spec_complete_yaml_branch 同款注意事项)。
_LIB_DIR = str(Path(__file__).resolve().parent.parent / "scripts" / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)
from spec_complete import (  # noqa: E402
    _classify_file_occurrence,
    classify_symbol_liveness,
)

_SYMBOL = "not_established"

# Aria#192 的最小复现 —— **两个成分都承重, 且顺序不能反**:
#   (1) 符号出现在 JSON 字符串值里 (这里还内嵌了转义引号, 忠实于真实 eval prompt);
#   (2) **同一行、符号之后**出现 `#` (真实文件里是 prompt 末尾的 `### Round 1`)。
# 机制: `_strip_comments_and_docstrings` 从 `#` 截到行尾 ⇒ 该串的闭合引号被删 ⇒ 串未闭合
# ⇒ `_strip_string_literals` 不再剥除它 ⇒ 符号被当成「代码体里的引用」⇒ unclassified。
# ⚠️ 若把 `#` 挪到符号**之前**, 截行会把符号一起删掉, 旧实现反而"正确"判 prose ——
# 那样的夹具零复现力 (2026-09-04 首版夹具就是这么写的, 基线红数 0, 被
# `check-runs-at-baseline-first` 的三态亲跑当场抓到)。改夹具前先重测基线红数。
_EVAL_JSON_WITH_HASH = (
    '{\n'
    '  "skill_name": "audit-engine",\n'
    '  "evals": [\n'
    '    {\n'
    '      "id": 1,\n'
    '      "prompt": "探针 stdout {\\"status\\":\\"degraded\\",\\"verdict\\":\\"'
    + _SYMBOL + '\\"} 时, 在 ### Round 1 记录里渲染「未能核实」",\n'
    '      "expectations": ["渲染「未能核实」而非「无竞品」"]\n'
    '    }\n'
    '  ]\n'
    '}\n'
)

# 对照臂: 同一份 JSON 去掉符号之后的 `#`。旧实现在这份上**本来就**判 prose,
# 用来钉住「`#` 且在符号之后」这个位置条件是承重成分, 不是装饰。
_EVAL_JSON_NO_HASH = _EVAL_JSON_WITH_HASH.replace("### Round 1", "第一轮")


class TestJsonDataFileIsProseNotUnclassified(unittest.TestCase):
    """#192 主条: 数据型 JSON ⇒ prose, 不再落 unclassified。"""

    def test_eval_suite_json_with_hash_in_string_is_prose(self):
        """含 `#` 的 eval prompt 串里的符号 ⇒ prose (声明性数据), 不是 unclassified。

        它怎么会红: 回退到通用「代码性」分支 ⇒ `#` 截行 ⇒ 引号失衡 ⇒ 串未被剥除
        ⇒ 返回 {'prose': False} (unclassified) ⇒ 本断言红。这正是 v1.69.0 的行为。
        """
        with tmp_project() as root:
            rel = "aria-plugin-benchmarks/ab-suite/audit-engine.json"
            write_file(root / rel, _EVAL_JSON_WITH_HASH)
            got = _classify_file_occurrence(rel, root, _SYMBOL, set())
            self.assertEqual(
                got, {"alive": False, "categories": [], "prose": True}, got
            )

    def test_hash_position_is_the_load_bearing_ingredient(self):
        """对照臂: 去掉符号之后的 `#` ⇒ 旧实现本来就判 prose (该形态从不复现 bug)。

        用途不是验新行为, 而是钉住上面那条夹具的**复现力**: 承重的不是「有 `#`」,
        而是「`#` 在符号之后」。若将来有人「简化」夹具把 `#` 挪前或删掉, 主条就会
        在新旧两版上一起绿 = 零拒绝能力, 而这条注释与断言是留给他的路标。
        它怎么会红: 新实现在无 `#` 版上判非 prose ⇒ 说明 `.json` 分支写歪了。
        """
        with tmp_project() as root:
            rel = "aria-plugin-benchmarks/ab-suite/no-hash.json"
            write_file(root / rel, _EVAL_JSON_NO_HASH)
            got = _classify_file_occurrence(rel, root, _SYMBOL, set())
            self.assertEqual(got, {"alive": False, "categories": [], "prose": True}, got)

    def test_json_results_snapshot_is_prose(self):
        """AB 结果快照 (eval_metadata.json / grading.json) 同归宿。

        它怎么会红: 只按文件名白名单认 `ab-suite/` 而不按扩展名判 ⇒ 结果目录下的
        JSON 仍落 unclassified ⇒ 红 (#192 点名的两个文件里就有一个在结果目录下)。
        """
        with tmp_project() as root:
            rel = "aria-plugin-benchmarks/ab-results/2026-09-03-x/runs/eval-2/eval_metadata.json"
            write_file(root / rel, _EVAL_JSON_WITH_HASH)
            self.assertTrue(_classify_file_occurrence(rel, root, _SYMBOL, set())["prose"])


class TestJsonBranchNegativeControls(unittest.TestCase):
    """拒绝能力: 修复不得把**真正的调用面**一起静默 (memory `adversarial-fixture`);
    同时不得留下反向的假 alive。"""

    def test_prose_word_in_json_is_no_longer_a_false_alive(self):
        """**本改动最重要的一条**: JSON 散文串里的普通词不得再被判 `alive`。

        实测 (2026-09-04, aria master 上): `ab-suite/spec-drafter.json` 与
        `audit-engine.json` 里的 `descriptive` —— 它只出现在「两 eval prompt 显式声明
        产出形态 `descriptive`」这句散文里 —— 旧实现判 **alive / code_reference**。
        假 alive 是**危险方向**: 死代码判定会被一个 JSON 里的词语静默地喂饱, 从此
        对真正的死代码瞎掉 (假 warn 只是噪声, 假 alive 是漏检)。
        它怎么会红: 回退 `.json` 分支 ⇒ `#` 截行后残文里 `"descriptive":` 这类形态被
        `_code_reference_match` 认成代码引用 ⇒ alive=True ⇒ 红。
        """
        with tmp_project() as root:
            rel = "aria-plugin-benchmarks/ab-suite/spec-drafter.json"
            write_file(
                root / rel,
                '{\n  "evals": [\n    {\n      "id": 1,\n'
                '      "expectations": ["两 eval prompt 显式声明产出形态 `descriptive` '
                '(手册 :161-174); 见 ### 产出形态 一节"]\n    }\n  ]\n}\n',
            )
            got = _classify_file_occurrence(rel, root, "descriptive", set())
            self.assertFalse(got["alive"], f"假 alive 复现: {got}")
            self.assertTrue(got["prose"], got)



    def test_json_invoking_a_script_path_is_still_alive(self):
        """package.json 式 scripts 段里以字面脚本路径调用 ⇒ 仍算 alive。

        它怎么会红: 把 `.json` 一刀切判 prose (不先做路径匹配) ⇒ 真实调用面被静默
        ⇒ 死代码判定从此对 JSON 驱动的调用瞎掉 ⇒ 本断言红。
        """
        with tmp_project() as root:
            rel = "package.json"
            write_file(
                root / rel,
                '{\n  "scripts": {\n'
                '    "probe": "python3 scripts/sibling_spec_probe.py --repo-path ."\n'
                "  }\n}\n",
            )
            got = _classify_file_occurrence(
                rel, root, "sibling_spec_probe.py", {"scripts/sibling_spec_probe.py"}
            )
            self.assertTrue(got["alive"], got)
            self.assertIn("generic_path_call", got["categories"])

    def test_hooks_json_still_routed_to_registration_branch(self):
        """`hooks.json` 由 `_is_hooks_or_config_path` 先行拦截, 新分支走不到。

        它怎么会红: 把 `.json` 分支插到注册面判定**之前** ⇒ hooks 注册被当成声明性
        数据 ⇒ 插件注册型引用全体判死 ⇒ 红。
        """
        with tmp_project() as root:
            rel = "hooks/hooks.json"
            write_file(
                root / rel,
                '{\n  "PreToolUse": [\n'
                '    {"hooks": [{"type": "command", "command": "python3 hooks/secret_guard.py"}]}\n'
                "  ]\n}\n",
            )
            got = _classify_file_occurrence(
                rel, root, "secret_guard.py", {"hooks/secret_guard.py"}
            )
            self.assertTrue(got["alive"], got)


class TestJsonBranchEndToEnd(unittest.TestCase):
    """经 `classify_symbol_liveness` 的端到端 —— gate 真正消费的是这一层。"""

    def test_alive_in_python_plus_mentioned_in_json_yields_clean_alive(self):
        """符号在 .py 里真被调用 + 在数据 JSON 里被提及 ⇒ alive 且 unclassified 为空。

        这就是 sibling-spec-probe 归档那次的形状: 判定结果本来就该是 alive, JSON 只
        贡献了噪声。它怎么会红: JSON 仍落 unclassified ⇒ `unclassified_files` 非空
        ⇒ 下游把 verdict 顶成 warn (即 #192 的原症状) ⇒ 红。
        """
        with tmp_project() as root:
            write_file(root / "scripts" / "probe.py", f"def {_SYMBOL}():\n    return 1\n")
            write_file(
                root / "scripts" / "consumer.py",
                f"from probe import {_SYMBOL}\n\nprint({_SYMBOL}())\n",
            )
            write_file(root / "aria-plugin-benchmarks" / "ab-suite" / "x.json", _EVAL_JSON_WITH_HASH)
            got = classify_symbol_liveness(_SYMBOL, root, {"scripts/probe.py"})
            self.assertEqual(got["status"], "alive", got)
            self.assertEqual(got["unclassified_files"], [], got)

    def test_polarity_definition_plus_data_only_is_dead(self):
        """极性钉子: 有 Python 定义 ∧ 引用只在数据 JSON ⇒ `dead` (非 `ambiguous`)。

        这是本改动**有意**的副作用 (见模块 docstring §极性说明): 数据文件不是生产
        引用, 所以「定义了但没人调用」就是高置信死代码。
        它怎么会红: 若将来有人为了 fail-toward-warn 把 JSON 改回 unclassified,
        status 会变 `ambiguous` ⇒ 本条红 —— 那是提醒他这是一次极性变更, 要显式裁,
        不是顺手改。
        """
        with tmp_project() as root:
            write_file(root / "scripts" / "probe.py", f"def {_SYMBOL}():\n    return 1\n")
            write_file(root / "aria-plugin-benchmarks" / "ab-suite" / "x.json", _EVAL_JSON_WITH_HASH)
            write_file(root / "docs" / "note.md", f"我们讨论过 `{_SYMBOL}` 这个态。\n")
            got = classify_symbol_liveness(_SYMBOL, root, {"scripts/probe.py"})
            self.assertEqual(got["status"], "dead", got)
            self.assertEqual(got["unclassified_files"], [], got)


if __name__ == "__main__":
    unittest.main()
