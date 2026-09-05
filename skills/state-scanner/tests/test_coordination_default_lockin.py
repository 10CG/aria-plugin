"""Part A1 lock-in (coordination-claim-lifecycle-and-overlap).

`state_scanner.coordination.enabled` 的默认值没有 python 解析点 —— config-loader
SKILL.md 就是默认值 SOT, AI 编排层按文档解析。因此 default 翻转 (false→true) 的
lock-in 测试落在文档层: 机械断言 SOT 及其引用文档不回退 (精神同 memory
feedback_default_value_flip_needs_lock_in_test: 改默认值必须配断言新默认的测试)。
"""
import re

import unittest
from pathlib import Path

_SKILLS = Path(__file__).resolve().parents[2]  # aria/skills/


def _read(rel: str) -> str:
    return (_SKILLS / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# SC-22 (a1-entry-claim-duplicate-work-guard TASK-025) — A.1 前置认领块的机械断言
#
# 为什么不是裸 ``assertIn``: 子串检查对「把 `前置: REQUIRE claim` 原样塞进 A.1 现有
# ```yaml 动作列表」这一种失败**免疫**, 而那正是 §Why 引 R3/M6 论证过的原病 —— 埋进
# 长 YAML 列表的单行指令会被静默跳过。所以断言必须认「独立标题级块」这个结构, 而不是
# 认几个字符串出现过。
# ---------------------------------------------------------------------------

_A1_HEADING = re.compile(r"^#{2,4}[ \t]+前置: REQUIRE claim\b[^\n]*A\.1")
_ANY_HEADING = re.compile(r"^#{1,4}[ \t]")


def _outside_fences(text: str) -> str:
    """把 ``` 围栏内的行清空, 只留围栏外的文本 (行数不变, 便于按行求值)."""
    out, in_fence = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def _a1_block_slice(text: str):
    """标题行 → 下一个**围栏外**的 `^#{1,4}[ \t]` 行 (或文件尾) 之间的原文切片.

    围栏内的 `#` 不算块边界 (命令示例里的注释行会误切); 返回 None 表示没有这个块。
    切片保留围栏内容 —— ⑦ 要在里面找完整命令行。
    """
    lines = text.split("\n")
    start, in_fence = None, False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if start is None:
            if _A1_HEADING.match(line):
                start = i
            continue
        if _ANY_HEADING.match(line):
            return "\n".join(lines[start:i])
    return "\n".join(lines[start:]) if start is not None else None


def _fold_continuations(text: str) -> str:
    """反斜杠续行折成一行: `\\` + 换行 + 后续缩进 → 一个空格.

    §2 的命令模板是多物理行续行形; 不折就直接跑单行正则会误红 (R6/TL C2)。
    """
    return re.sub(r"\\\n[ \t]*", " ", text)


def _yaml_fences(text: str):
    return re.findall(r"(?ms)^```yaml[ \t]*\n(.*?)^```", text)


_SEVEN_LITERALS = (
    "phase1_gate.py",
    "--linked-issue",
    "--include-terminal",
    "--phase A.1",
    '--raw-track-id "<spec-slug>-<container_uuid>"',
    "--emit-arg",
    "未能核实",
)
_IDEMPOTENCE_PREDICATE = (
    "check: coordination ref 内按 (container_id, session_id) 定位到本 session 的 active claim"
)


class _A1RequireClaimBlockAssertions:
    """SC-22 ①②③④⑥⑦ —— 每个文件一个子类, 逐一断言, **不拼接两文件文本**.

    怎么会红 (已在 aria d69091d 基线亲跑):
      - 两文件今天都没有这个块 ⇒ ① 红 (基线全红的来源)
      - 把七字面量塞进 `## 相关文档` ⇒ 落在切片外 ⇒ ② 红
      - 把块原样塞进 A.1 现有 ```yaml 动作列表 ⇒ 标题不存在 ⇒ ① 红
        (裸 assertIn 对这种失败免疫 —— 明确不可接受)
      - 只列参数子串、没有一条可执行命令的散文实现 ⇒ ⑦ 红
      - 缺幂等谓词 (一次 A.1 写两条 claim + 两次外向 push) ⇒ ③ 红
      - 块里出现 `--phase B` (照抄 Phase B 模板) ⇒ ④ 红

    与既有 ``test_phase_b_require_claim_present`` (本文件内, 两条**裸 assertIn**) 的
    强度差异是**有意**的: B.0 那个块是 YAML 键形态而非标题, 属既有欠缺, 另开 issue,
    不在本 Spec 修 —— 所以那条测试不能照抄到这里当样板。
    """

    REL = None  # 子类填

    def _text(self):
        return _read(self.REL)

    def _slice(self):
        sl = _a1_block_slice(self._text())
        self.assertIsNotNone(sl, f"{self.REL} 没有独立标题级的「前置: REQUIRE claim (A.1)」块")
        return sl

    def test_01_heading_is_a_real_heading_outside_fences(self):
        self.assertRegex(_outside_fences(self._text()),
                         r"(?m)^#{2,4}[ \t]+前置: REQUIRE claim\b[^\n]*A\.1")

    def test_02_slice_contains_seven_literals(self):
        sl = self._slice()
        for lit in _SEVEN_LITERALS:
            self.assertIn(lit, sl, f"{self.REL} 块内缺字面量 {lit!r}")

    def test_03_slice_contains_idempotence_predicate_verbatim(self):
        sl = self._slice()
        self.assertIn(_IDEMPOTENCE_PREDICATE, sl,
                      f"{self.REL} 块内缺逐字幂等谓词 (不接受「或等价的…」逃逸口)")
        self.assertIn("claims/", sl)

    def test_04_slice_must_not_mention_phase_b(self):
        self.assertNotIn("--phase B", self._slice(),
                         f"{self.REL} 块内出现 --phase B —— 照抄了 Phase B 模板")

    def test_06_slice_contains_both_exit_obligations(self):
        sl = self._slice()
        self.assertIn("改名 ⇒ release 旧 + acquire 新", sl)
        self.assertIn("放弃方向 ⇒ release_gate.py --raw-track-id", sl)

    def test_07_slice_contains_one_complete_command_line(self):
        folded = _fold_continuations(self._slice())
        hits = [ln for ln in folded.split("\n")
                if ln.strip().startswith("python3")
                and "phase1_gate.py" in ln and "--phase A.1" in ln]
        self.assertTrue(hits,
                        f"{self.REL} 块内没有一条以 python3 起首、含 phase1_gate.py 与 "
                        f"--phase A.1 的完整命令行 (参数子串齐全但不可执行的散文不算)")


class TestA1RequireClaimBlockPhaseAPlanner(_A1RequireClaimBlockAssertions, unittest.TestCase):
    REL = "phase-a-planner/SKILL.md"


class TestA1RequireClaimBlockSpecDrafter(_A1RequireClaimBlockAssertions, unittest.TestCase):
    REL = "spec-drafter/SKILL.md"


class TestA1PreconditionPointer(unittest.TestCase):
    """SC-22 ⑤ —— **仅 phase-a-planner, 且在切片外求值** (与 ②③④⑥⑦ 互斥).

    A.1 的 YAML 动作项必须留一个指回小节的 ``precondition:`` 指针, 否则读到 YAML 表
    的人不会知道表之前还有一步必须先做。
    """

    REL = "phase-a-planner/SKILL.md"
    ANCHOR = "A.1 - Spec 管理:"
    POINTER = "precondition: 见「前置: REQUIRE claim」小节 (MUST, 在本表之前执行)"

    def test_pointer_lives_in_the_a1_yaml_fence_located_by_anchor(self):
        fences = _yaml_fences(_read(self.REL))
        self.assertGreater(len(fences), 1,
                           "文件内有多处 ```yaml 围栏 —— 必须按锚点定位, 不能抓第一个")
        hosts = [f for f in fences if self.ANCHOR in f]
        self.assertEqual(len(hosts), 1,
                         f"含锚点 {self.ANCHOR!r} 的 yaml 围栏应恰有一处, 实得 {len(hosts)}")
        self.assertIn(self.POINTER, hosts[0])


def _section_slice(text: str, heading_regex: str):
    """标题行 → 下一个**围栏外** `^#{1,4}[ \t]` 行 的切片; 找不到标题返回 None.

    切片是这批断言的关键: 全文 ``assertIn`` 对「字面量写对了但写在别的小节里」
    完全免疫, 而那恰恰是最常见的落地失误。
    """
    pat = re.compile(heading_regex)
    lines = text.split("\n")
    start, in_fence = None, False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if start is None:
            if pat.match(line):
                start = i
            continue
        if _ANY_HEADING.match(line):
            return "\n".join(lines[start:i])
    return "\n".join(lines[start:]) if start is not None else None


class TestA1CarryIdWordingThreeFiles(unittest.TestCase):
    """SC-34 (TASK-026): 三处模板逐字复用同一串占位措辞.

    守的是文本层承诺「carry-id 就是 A.1 认领时派生的那一串」—— SC-23 / SC-14(a) 的
    代码夹具对它感知不到 (它们验的是 release 能不能命中, 不是文档有没有这么说)。
    怎么会红: 基线三文件 0 命中; 只改两处 ⇒ 第三条红。
    """

    WORDING = "A.1 认领时派生的那一串"
    FILES = ("phase-b-developer/SKILL.md", "branch-manager/SKILL.md", "phase-d-closer/SKILL.md")

    def test_each_of_three_files_carries_the_wording(self):
        for rel in self.FILES:            # 三条独立断言, 失败信息点名文件
            with self.subTest(file=rel):
                self.assertGreaterEqual(
                    _read(rel).count(self.WORDING), 1,
                    f"{rel} 缺逐字占位措辞 {self.WORDING!r}",
                )

    def test_branch_manager_part_a1_heading_untouched(self):
        """R6/CR M1: branch-manager :146 的 `Part A1` 是已 ship Spec 的**部件名**,
        不是 Phase A.1 —— 本 Spec 不得把它改掉。"""
        self.assertIn("Part A1", _read("branch-manager/SKILL.md"))


class TestDefaultsJsonCoordinationKeys(unittest.TestCase):
    """rule6 substitute #6 (TASK-027): DEFAULTS.json 与 config-loader/SKILL.md 三键逐字一致.

    ``coordination.*`` 的默认值没有 python 解析点, SKILL.md 就是 SOT —— 两处各写一份
    默认值而无人比对, 是典型的「文档说 A、注册表写 B」漂移面。
    怎么会红: 基线 DEFAULTS.json 根本没有 coordination 段 ⇒ 红。
    """

    EXPECTED = {"enabled": True, "mode": "advisory", "unattended": False}

    def _json_coordination(self):
        import json
        data = json.loads((_SKILLS / "config-loader" / "DEFAULTS.json").read_text(encoding="utf-8"))
        ss = data.get("state_scanner", {})
        # 用 assertIn 而不是直接下标: KeyError 也红, 但读者要从 traceback 反推「哦是
        # 没注册」; 干净的断言信息直接说出来。
        self.assertIn("coordination", ss,
                      "DEFAULTS.json 的 state_scanner 下未注册 coordination 段")
        return ss["coordination"]

    def _skill_md_default(self, key: str):
        """从 SKILL.md 的 `state_scanner.coordination.<key>:` 条目下抓 `default:` 值."""
        text = _read("config-loader/SKILL.md")
        m = re.search(
            r"^state_scanner\.coordination\." + re.escape(key) + r":\n(?:(?!^state_scanner\.).)*?"
            r"^\s*default:[ \t]*(.+?)[ \t]*(?:#.*)?$",
            text, re.M | re.S,
        )
        self.assertIsNotNone(m, f"config-loader/SKILL.md 未登记 coordination.{key} 的 default")
        return m.group(1).strip()

    def test_json_registers_exactly_the_three_keys(self):
        self.assertEqual(set(self._json_coordination()), set(self.EXPECTED),
                         "三键集合须相等 —— 不多不少")

    def test_json_values_match_skill_md_verbatim(self):
        coord = self._json_coordination()
        for key, want in self.EXPECTED.items():
            with self.subTest(key=key):
                self.assertEqual(coord[key], want, f"DEFAULTS.json coordination.{key}")
                md_val = self._skill_md_default(key)
                # true/false 逐字, 字符串带引号逐字 —— 尾随空白等价物也算不一致
                expect_md = {True: "true", False: "false"}.get(want, f'"{want}"')
                self.assertEqual(md_val, expect_md,
                                 f"SKILL.md 登记的 coordination.{key} 默认值与 JSON 不一致")


class TestLayerLReferenceHeartbeatWiring(unittest.TestCase):
    """rule6 substitute #10a (TASK-028): layer-l-integration.md 不得留悬空 API 名.

    :45 今天写着 ``lib/claim_lifecycle.py::update_heartbeat()`` —— 全 aria 里
    **没有这个函数**, 只有 ``heartbeat()``。文档凭空发明一个 API 名, 读者照着 grep
    什么也找不到。
    怎么会红: 基线含 update_heartbeat ⇒ 第一条红。
    负控: 只删那一行不补任何 ``heartbeat(`` ⇒ 第二条红 —— 断言不是「删掉就绿」。
    """

    REL = "state-scanner/references/layer-l-integration.md"

    def test_no_dangling_update_heartbeat_name(self):
        self.assertNotIn("update_heartbeat", _read(self.REL),
                         "文档引用了一个 aria 里不存在的函数名")

    def test_real_heartbeat_api_is_still_referenced(self):
        self.assertIn("heartbeat(", _read(self.REL),
                      "删掉悬空名的同时必须留下真实 API 的引用")


class TestSchemaDocUnknownSchemaClaims(unittest.TestCase):
    """rule6 substitute #11 (TASK-029): unknown_schema_claims 的语义必须落在 §3.2.

    §3.2 讲的正是「读者遇到不认识的 schema 版本怎么办」, 这个新键是那条规则的输出面。
    负控: 把字面写进 §4.2 (reconcile 的 status="unknown") 而非 §3.2 ⇒ 切片外 ⇒ 红。
    全文 assertIn 对这种放错位置完全免疫, 所以必须切片。
    """

    REL = "state-scanner/docs/coordination-ref-schema.md"

    def test_section_3_2_documents_the_key(self):
        sl = _section_slice(_read(self.REL), r"^### 3\.2\b")
        self.assertIsNotNone(sl, "找不到 §3.2 小节")
        self.assertIn("unknown_schema_claims", sl,
                      "§3.2 未记录 unknown_schema_claims 语义 (写在别节不算)")


class TestLayerLA1HeartbeatSection(unittest.TestCase):
    """rule6 substitute #10b + #12 (TASK-030): 新小节与新键各自落在**自己该在的切片**里.

    负控: 标题在、命令行写在别节 ⇒ 红; push_skipped 写进 `## 相关文档` ⇒ 切片外 ⇒ 红。
    """

    LAYER_L = "state-scanner/references/layer-l-integration.md"
    SS_SKILL = "state-scanner/SKILL.md"

    def test_layer_l_has_a1_heartbeat_section_with_the_flag(self):
        sl = _section_slice(_read(self.LAYER_L), r"^#{2,4}[ \t]+Layer L A\.1 heartbeat 集成")
        self.assertIsNotNone(sl, "layer-l-integration.md 缺「Layer L A.1 heartbeat 集成」小节")
        self.assertIn("--heartbeat-only", sl, "该节内须给出完整 flag, 写在别节不算")

    def test_json_consumption_section_lists_push_skip_keys(self):
        sl = _section_slice(_read(self.SS_SKILL), r"^#{2,4}[ \t]+JSON 消费")
        self.assertIsNotNone(sl, "state-scanner/SKILL.md 缺「JSON 消费」小节")
        for key in ("push_skipped", "push_skipped_reason"):
            with self.subTest(key=key):
                self.assertIn(key, sl, f"JSON 消费节的键集缺 {key}")


class TestCoordinationEnabledDefaultLockin(unittest.TestCase):
    def test_config_loader_sot_default_true(self):
        text = _read("config-loader/SKILL.md")
        # 提取 state_scanner.coordination.enabled 块 (到下一个非缩进行/键为止)
        m = re.search(
            r"state_scanner\.coordination\.enabled:\n((?:[ \t]+.*\n)+)", text
        )
        self.assertIsNotNone(m, "coordination.enabled 键从 config-loader SOT 消失")
        block = m.group(1)
        self.assertIn(
            "default: true",
            block,
            "Part A1 默认翻转回退: coordination.enabled 默认必须是 true (opt-out)",
        )
        self.assertNotIn("default: false", block)

    def test_no_stale_default_false_wording(self):
        """引用文档不得残留「默认 false / opt-in」旧措辞 (针对 coordination.enabled)."""
        for rel in (
            "state-scanner/SKILL.md",
            "state-scanner/references/layer-l-integration.md",
        ):
            text = _read(rel)
            for line in text.splitlines():
                if "coordination.enabled" not in line:
                    continue
                # 「默认 false→true」是变更叙述, 不算残留 — 负向断言排除 →
                self.assertNotRegex(
                    line,
                    r"默认\s*`?false`?(?!\s*→|→)",
                    f"{rel} 残留 coordination.enabled 默认 false 旧措辞: {line!r}",
                )

    def test_phase_b_require_claim_present(self):
        """A1-2: Phase B 入口两个 skill 都必须带 REQUIRE claim 步骤."""
        self.assertIn("B.0 - REQUIRE claim", _read("phase-b-developer/SKILL.md"))
        self.assertIn("REQUIRE claim", _read("branch-manager/SKILL.md"))

    def test_phase_d_release_wiring_present(self):
        """Part C-5: phase-d-closer 必须带 D.2b claim 释放接线."""
        text = _read("phase-d-closer/SKILL.md")
        self.assertIn("D.2b", text)
        self.assertIn("release_gate.py", text)


if __name__ == "__main__":
    unittest.main()
