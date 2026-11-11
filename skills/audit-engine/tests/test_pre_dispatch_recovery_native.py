"""TASK005: 独立解析器的 RED；不调用恢复事务或两份 owner adapter。

每个 case 的 docstring 指出会使其变红的真实破坏；缺 helper 是功能缺失，
不是任何业务负控已被捕获。profile 只在临时模块的数据边界注入。
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest import mock

_support_path = Path(__file__).with_name("pre_dispatch_recovery_fixtures.py")
_spec = importlib.util.spec_from_file_location("native_recovery_test_support", _support_path)
assert _spec is not None and _spec.loader is not None
support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(support)

WINDOWS = [
    {"start": 0, "end": 35, "sha256": "20db551f31dd5638fab0b51ae240465ab34424c83316daca16f7f9d17730fdf1"},
    {"start": 35, "end": 71, "sha256": "9148578f394a3258b47b817961fe40844f7e8a92eb49335cafa45d993ffcb109"},
    {"start": 71, "end": 106, "sha256": "28b67d8a76c28d0cd0c056155564ce6c8f75e96df0dc597ce419a4aa31cb0ff8"},
]
BINARY_SHA = "8586839bfcd2dcfd6fa62a2101f68862fe8b31a7aa2e109ac30c9eccebae4d6d"
TOOL_ID = "call_fixture_rejection"


class FixtureControl(unittest.TestCase):
    def test_factory_produces_real_old_build_and_root_pair(self):
        """防止将缺失旧脚本或假造 JSON 外壳误作解析器业务 RED。"""
        f = support.RecoveryFixture()
        self.addCleanup(f.close)
        self.assertEqual(f.script_path.stat().st_size, 570716)
        self.assertEqual(len(f.event_paths()), 1)
        self.assertEqual(f.record["workflow_script"], support.file_ref(f.script_path))
        self.assertEqual([row["type"] for row in f.rows[:2]], ["assistant", "user"])
        self.assertEqual(f.rows[0]["message"]["content"][0]["id"], TOOL_ID)
        self.assertEqual(f.rows[1]["message"]["content"][0]["tool_use_id"], TOOL_ID)
        self.assertEqual(f.runtime_profiles["2.1.318"]["windows"], WINDOWS)


class RecoveryNativeTests(unittest.TestCase):
    def setUp(self):
        visible = support.load_module(support.EXECUTOR)
        self.assertTrue(callable(getattr(visible, "_parse_recovery_rejection", None)),
                        "FEATURE_NOT_IMPLEMENTED_TDD_RED: _parse_recovery_rejection absent")
        self.f = support.RecoveryFixture()
        self.addCleanup(self.f.close)
        env = mock.patch.dict(os.environ, self.f.environment, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.mod = support.load_module(self.f.executor)
        patch = mock.patch.object(self.mod, "_RUNTIME_REJECTION_PROFILES",
                                  copy.deepcopy(self.f.runtime_profiles), create=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.manifest = copy.deepcopy(self.f.manifest)
        self.record = copy.deepcopy(self.f.record)
        self.native = self.f.native_path

    def parse(self, inputs=None):
        return self.mod._parse_recovery_rejection(
            self.f.repo, self.manifest, self.record, self.native, TOOL_ID, inputs=inputs)

    def refused(self, prefix):
        before = support.tree_snapshot(self.f.root)
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.parse(inputs=self.mod._Inputs())
        self.assertEqual(caught.exception.error_code, "E_RECOVERY_EVIDENCE")
        self.assertTrue(caught.exception.reason.startswith(prefix), caught.exception.reason)
        self.assertEqual(support.tree_snapshot(self.f.root), before)

    def test_exact_rejection_and_static_basis_are_read_only(self):
        """防止拒绝行、原始行 hash、静态字节及目标 script 错绑或解析阶段写入。"""
        f = self.f
        before = support.tree_snapshot(f.root)
        inputs = self.mod._Inputs()
        result = self.parse(inputs)
        self.assertEqual(support.tree_snapshot(f.root), before)
        self.assertEqual(result["cause"], "workflow_input_file_too_large")
        self.assertEqual(result["session_id"], "11111111-2222-4333-8444-555555555555")
        self.assertEqual(result["source"], {"original_locator": str(f.native_path),
                         "runtime_config_root": str(f.config_root),
                         "snapshot": support.file_ref(f.native_path)})
        lines = f.native_path.read_bytes().split(b"\n")
        request, response = f.rows[:2]
        self.assertEqual(result["request"], {
            "uuid": "00000000-0000-4000-8000-000000000001", "tool_use_id": TOOL_ID,
            "line_sha256": hashlib.sha256(lines[0]).hexdigest(),
            "input": request["message"]["content"][0]["input"]})
        self.assertEqual(result["response"], {
            "uuid": "00000000-0000-4000-8000-000000000002", "tool_use_id": TOOL_ID,
            "line_sha256": hashlib.sha256(lines[1]).hexdigest(),
            "error": response["message"]["content"][0]["content"]})
        self.assertEqual(result["script"], support.file_ref(f.script_path))
        profile = f.runtime_profiles["2.1.318"]
        self.assertEqual(result["runtime_rejection_basis"], {
            "schema_version": 1, "binary_sha256": BINARY_SHA, "native_version": "2.1.318",
            "capacity_source": support.file_ref(profile["capacity_source"]),
            "loader_source": support.file_ref(profile["loader_source"]), "windows": WINDOWS})
        self.assertIsNot(result.get("eligible"), True)
        self.assertNotIn("no_run_proven", result)
        for path in (f.native_path, f.script_path, Path(profile["capacity_source"]), Path(profile["loader_source"])):
            self.assertEqual(inputs.raw[str(path)], path.read_bytes())

    def test_api_copies_coexisting_with_real_root_are_not_duplicates(self):
        """防止递归计数 API envelope 中的同文副本而错误拒绝有效 root 对。"""
        f = self.f
        f.rows.append({"type": "api-request-blob", "data": copy.deepcopy(f.rows[:2])})
        f._write_native()
        before = support.tree_snapshot(f.root)
        result = self.parse(inputs=self.mod._Inputs())
        self.assertEqual(result["request"]["tool_use_id"], TOOL_ID)
        self.assertEqual(result["response"]["tool_use_id"], TOOL_ID)
        self.assertEqual(support.tree_snapshot(f.root), before)

    def test_explicitly_linked_extra_native_evidence_is_not_silently_ignored(self):
        """合成未知关联载体必须拒绝；不冒称该progress布局已在真实日志出现。"""
        for link_key in ('tool_use_id', 'toolUseID'):
            with self.subTest(link=link_key):
                self.f.restore_authorities()
                self.f.rows.append({
                    'type': 'progress', 'uuid': '00000000-0000-4000-8000-000000000020',
                    'sessionId': self.f.session_id, 'cwd': str(self.f.repo),
                    'isSidechain': False, 'version': '2.1.318',
                    'data': {link_key: TOOL_ID, 'runId': 'synthetic-associated-run'}})
                self.f._write_native()
                self.refused('native_')

    def test_second_same_cycle_workflow_in_selected_assistant_row_is_unknown(self):
        """禁止整行跳过选中请求，从而漏掉同一message中第二个关联tool block。"""
        another = copy.deepcopy(self.f.rows[0]['message']['content'][0])
        another['id'] = 'another-associated-tool'
        another['input']['scriptPath'] = str(self.f.repo / 'other-associated.js')
        args = another['input']['args']
        args['manifest_sha256'] = 'f' * 64
        args['identity']['client_round_id'] = 'other-client-same-cycle'
        self.f.rows[0]['message']['content'].append(another)
        self.f._write_native()
        self.refused('native_')

    def test_unrelated_tool_block_in_selected_row_does_not_contaminate_rejection(self):
        """块级关联不能把同message里无关工具的runId当目标调用启动信号。"""
        self.f.rows[0]['message']['content'].append({
            'type': 'tool_use', 'id': 'unrelated-non-workflow-call',
            'name': 'OtherTool', 'input': {'runId': 'unrelated-run'}})
        self.f._write_native()
        try:
            result = self.parse(inputs=self.mod._Inputs())
        except self.mod.ExecutorError as error:
            self.fail('unrelated tool block was rejected: ' + error.reason)
        self.assertEqual(result['request']['tool_use_id'], TOOL_ID)
        self.assertIsNot(result.get('eligible'), True)

    def test_successful_structured_result_cannot_coexist_with_exact_capacity_error(self):
        """保留精确error内容，独立的结构化completed/success仍是矛盾证据。"""
        self.f.rows[1]['toolUseResult'] = {'status': 'completed', 'success': True}
        self.f._write_native()
        self.refused('native_')

    def test_matching_selected_structured_wire_input_is_consistent_evidence(self):
        """已观察wire布局是结构化input映射，匹配副本不能被误判第二个调用。"""
        self.f.rows[0]['wireToolInputs'] = {
            TOOL_ID: copy.deepcopy(self.f.rows[0]['message']['content'][0]['input'])}
        self.f._write_native()
        result = self.parse(inputs=self.mod._Inputs())
        self.assertEqual(result['request']['input'],
                         self.f.rows[0]['message']['content'][0]['input'])

    def test_selected_structured_wire_input_must_match_full_tool_input(self):
        """同一调用wire与tool block的路径/args矛盾时不能任取一份闭合拒绝。"""
        for change in ('path', 'args'):
            with self.subTest(change=change):
                self.f.restore_authorities()
                wire = copy.deepcopy(self.f.rows[0]['message']['content'][0]['input'])
                if change == 'path':
                    wire['scriptPath'] = str(self.f.repo / 'conflicting-wire.js')
                else:
                    wire['args']['manifest_sha256'] = '0' * 64
                self.f.rows[0]['wireToolInputs'] = {TOOL_ID: wire}
                self.f._write_native()
                self.refused('native_')

    def test_unrecognized_selected_wire_shape_is_not_parsed_as_ordinary_text(self):
        """未知wire映射或JSON样式普通字符串不能绕过结构一致性校验。"""
        original = copy.deepcopy(self.f.rows[0]['message']['content'][0]['input'])
        for wire in ([], {TOOL_ID: json.dumps(original)}):
            with self.subTest(wire=type(wire).__name__):
                self.f.restore_authorities()
                self.f.rows[0]['wireToolInputs'] = wire
                self.f._write_native()
                self.refused('native_')

    def test_target_wire_mapping_key_in_another_row_is_unresolved_evidence(self):
        """目标ID作为另一行wire映射的key也构成关联，不能只扫描字段value。"""
        wire = copy.deepcopy(self.f.rows[0]['message']['content'][0]['input'])
        wire['scriptPath'] = str(self.f.repo / 'other-row-wire.js')
        wire['args']['manifest_sha256'] = 'e' * 64
        wire['args']['identity']['audit_cycle_id'] = 'other-row-wire-cycle'
        wire['args']['identity']['client_round_id'] = 'other-row-wire-client'
        # Neutralize value-based links so only the target mapping KEY can catch this.
        self.assertNotEqual(wire['args']['identity']['audit_cycle_id'],
                            self.f.record['identity']['audit_cycle_id'])
        self.f.rows.append({
            'type': 'assistant', 'uuid': '00000000-0000-4000-8000-000000000030',
            'sessionId': self.f.session_id, 'cwd': str(self.f.repo),
            'isSidechain': False, 'version': '2.1.318',
            'message': {'role': 'assistant', 'content': []},
            'wireToolInputs': {TOOL_ID: wire}})
        self.f._write_native()
        self.refused('native_')

    def test_same_tool_id_in_unknown_message_role_is_not_silently_ignored(self):
        """先识别目标tool block ID再做shape判定，未知role不能当无关联。"""
        self.f.rows.append({
            'type': 'assistant', 'uuid': '00000000-0000-4000-8000-000000000031',
            'sessionId': self.f.session_id, 'cwd': str(self.f.repo),
            'isSidechain': False, 'version': '2.1.318',
            'message': {'role': 'unknown', 'content': [
                {'type': 'tool_use', 'id': TOOL_ID, 'name': 'Workflow', 'input': {}}]}})
        self.f._write_native()
        self.refused('native_')

    def test_unknown_role_and_wire_with_unrelated_ids_do_not_become_target_evidence(self):
        """未知结构里的无关调用ID仍不关联目标，禁止通过全局shape拒绝修漏检。"""
        self.f.rows.append({
            'type': 'assistant', 'uuid': '00000000-0000-4000-8000-000000000032',
            'sessionId': self.f.session_id, 'cwd': str(self.f.repo),
            'isSidechain': False, 'version': '2.1.318',
            'message': {'role': 'unknown', 'content': [
                {'type': 'tool_use', 'id': 'unrelated-id', 'name': 'Workflow', 'input': {}}]},
            'wireToolInputs': {'unrelated-id': {'scriptPath': str(self.f.repo / 'unrelated.js')}}})
        self.f._write_native()
        result = self.parse(inputs=self.mod._Inputs())
        self.assertEqual(result['request']['tool_use_id'], TOOL_ID)

    def test_same_cycle_extra_metadata_is_unknown_not_a_closed_rejection(self):
        """另一结构化同cycle记录不能靠缺少第二个tool_use就静默消失。"""
        self.f.rows.append({
            'type': 'progress', 'uuid': '00000000-0000-4000-8000-000000000021',
            'sessionId': self.f.session_id, 'cwd': str(self.f.repo),
            'isSidechain': False, 'version': '2.1.318',
            'data': {'identity': {'audit_cycle_id': self.f.record['identity']['audit_cycle_id'],
                                  'client_round_id': 'another-associated-client'},
                     'state': 'unknown'}})
        self.f._write_native()
        self.refused('native_')

    def test_unrelated_structured_native_progress_is_not_a_permanent_red_gate(self):
        """不相关的原生进度含runId不构成目标调用反证，禁止全局字符串扫红。"""
        self.f.rows.append({
            'type': 'progress', 'uuid': '00000000-0000-4000-8000-000000000022',
            'sessionId': self.f.session_id, 'cwd': str(self.f.repo),
            'isSidechain': False, 'version': '2.1.318',
            'data': {'tool_use_id': 'unrelated-call', 'runId': 'unrelated-run',
                     'identity': {'audit_cycle_id': 'unrelated-cycle'}}})
        self.f._write_native()
        result = self.parse(inputs=self.mod._Inputs())
        self.assertEqual(result['request']['tool_use_id'], TOOL_ID)
        self.assertIsNot(result.get('eligible'), True)

    def test_wrong_tool_or_input_shape(self):
        """防止同 id 的非 Workflow、错 scriptPath 或额外参数冒充目标调用。"""
        for change in ("tool", "path", "extra"):
            with self.subTest(change=change):
                self.f.restore_authorities()
                use = self.f.rows[0]["message"]["content"][0]
                if change == "tool":
                    use["name"] = "OtherTool"
                elif change == "path":
                    use["input"]["scriptPath"] += ".other"
                else:
                    use["input"]["extra"] = True
                self.f._write_native()
                self.refused("native_")

    def test_wrong_args_identity_or_manifest_hash(self):
        """防止请求参数偏离真实 build identity/hash 仍被认作目标调用。"""
        for change in ("identity", "hash", "extra"):
            with self.subTest(change=change):
                self.f.restore_authorities()
                args = self.f.rows[0]["message"]["content"][0]["input"]["args"]
                if change == "identity":
                    args["identity"]["change_id"] = "other"
                elif change == "hash":
                    args["manifest_sha256"] = "0" * 64
                else:
                    args["extra"] = "override"
                self.f._write_native()
                self.refused("native_")

    def test_manifest_or_build_record_mismatch(self):
        """防止仅比对请求与 build-record，漏验实际 manifest 和脚本摘要。"""
        for change in ("manifest_identity", "build_script_hash"):
            with self.subTest(change=change):
                self.manifest = copy.deepcopy(self.f.manifest)
                self.record = copy.deepcopy(self.f.record)
                if change == "manifest_identity":
                    self.manifest["change_id"] = "other"
                else:
                    self.record["workflow_script"]["sha256"] = "0" * 64
                self.refused("native_")

    def test_is_error_must_be_boolean_true(self):
        """防止数字 1 利用 Python 真值相等冒充原生 is_error=true。"""
        self.f.rows[1]["message"]["content"][0]["is_error"] = 1
        self.f._write_native()
        self.refused("native_")

    def test_exact_error_string_not_timeout_or_quoted_content(self):
        """防止非字符串、前缀引用或 timeout 被 substring 命中认作容量拒绝。"""
        error = self.f.rows[1]["message"]["content"][0]["content"]
        for value in ([error], "prefix " + error, "timeout"):
            with self.subTest(value=value):
                self.f.restore_authorities()
                self.f.rows[1]["message"]["content"][0]["content"] = value
                self.f._write_native()
                self.refused("native_")

    def test_response_must_pair_with_request_and_follow_it(self):
        """防止借用另一个 assistant 的响应，或接受时间顺序倒置的配对。"""
        for field in ("parentUuid", "sourceToolAssistantUUID", "timestamp"):
            with self.subTest(field=field):
                self.f.restore_authorities()
                self.f.rows[1][field] = ("2025-01-01T00:00:00.000Z" if field == "timestamp"
                                          else "00000000-0000-4000-8000-999999999999")
                self.f._write_native()
                self.refused("native_")

    def test_sidechain_and_api_copies_alone_are_not_root_events(self):
        """防止 sidechain 或 API 请求体中嵌套的副本冒充真实根记录。"""
        for mode in ("sidechain", "api"):
            with self.subTest(mode=mode):
                self.f.restore_authorities()
                for row in self.f.rows[:2]:
                    if mode == "sidechain":
                        row["isSidechain"] = True
                    else:
                        inner = copy.deepcopy(row)
                        row.clear()
                        row.update(type="api-request-blob", data=inner)
                self.f._write_native()
                self.refused("native_")

    def test_duplicate_root_calls_are_rejected(self):
        """防止同 tool_use_id 的两个真实 root 调用被任取一条造成歧义。"""
        request, response = copy.deepcopy(self.f.rows[:2])
        request["uuid"] = "00000000-0000-4000-8000-000000000010"
        response["uuid"] = "00000000-0000-4000-8000-000000000011"
        response["parentUuid"] = request["uuid"]
        response["sourceToolAssistantUUID"] = request["uuid"]
        self.f.rows.extend([request, response])
        self.f._write_native()
        self.refused("native_")

    def test_source_outside_runtime_namespace_is_rejected(self):
        """防止仓内任意 JSONL 伪装宿主原生来源。"""
        self.native = self.f.repo / (self.f.session_id + ".jsonl")
        self.native.write_bytes(self.f.native_path.read_bytes())
        self.refused("native_")

    def test_symbolic_link_to_valid_native_source_is_rejected(self):
        """防止 resolve 后丢失符号链接身份，使别名载体冒充固定原件。"""
        link_dir = self.f.config_root / 'projects' / 'symbolic-alias'
        link_dir.mkdir()
        link = link_dir / (self.f.session_id + '.jsonl')
        link.symlink_to(self.f.native_path)
        self.native = link
        self.refused('native_')

    def test_unsupported_native_version_is_rejected(self):
        """防止把未取证版本套用 2.1.318 的静态执行顺序。"""
        for row in self.f.rows[:2]:
            row["version"] = "9.9.9"
        self.f._write_native()
        self.refused("runtime_")

    def test_wrong_static_hash_or_bytes_rejected(self):
        """防止只相信静态 JSON 声明而不复核固定窗口哈希及实际字节。"""
        profile = self.f.runtime_profiles["2.1.318"]
        path = Path(profile["capacity_source"])
        original = path.read_bytes()
        for change in ("hash", "bytes"):
            with self.subTest(change=change):
                data = json.loads(original)
                if change == "hash":
                    data["windows"][0]["sha256"] = "0" * 64
                else:
                    data["windows"][0]["bytes_hex"] = "00" * 35
                support.write_json(path, data)
                self.refused("runtime_")


if __name__ == "__main__":
    unittest.main()
