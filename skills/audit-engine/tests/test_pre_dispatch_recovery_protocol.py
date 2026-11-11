"""真实恢复消费者的未来契约测试；未实现只能 FEATURE_NOT_IMPLEMENTED_TDD_RED。

不 skip/xfail，不以默认空结果伪造拒绝，不实现恢复算法。缺入口时每个协议
测试在构造旧工件前明确失败；只有工厂构造自检独立于未来入口。
标准 flags/module/profile 边界见同目录工厂及私有 JSON 报告。
"""
from __future__ import annotations

import inspect
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

# The tests directory is not an import package; resolve only this owned file.
_support_path = Path(__file__).with_name('pre_dispatch_recovery_fixtures.py')
_support_spec = importlib.util.spec_from_file_location('recovery_protocol_test_support', _support_path)
if _support_spec is None or _support_spec.loader is None:
    raise RuntimeError('test support file is unavailable')
_support = importlib.util.module_from_spec(_support_spec)
_support_spec.loader.exec_module(_support)
EXECUTOR = _support.EXECUTOR
OLD_EXECUTOR_SHA = _support.OLD_EXECUTOR_SHA
OLD_CONTRACT_SHA = _support.OLD_CONTRACT_SHA
RecoveryFixture = _support.RecoveryFixture
digest = _support.digest
file_ref = _support.file_ref
load_module = _support.load_module
tree_snapshot = _support.tree_snapshot
write_json = _support.write_json


class FixtureConstructionTests(unittest.TestCase):
    def test_real_old_reserve_has_bound_script_and_two_mechanical_source_generations(self):
        """保护破坏：手写假 build/reserve、570716 空壳或同路径覆盖旧冻结来源。"""
        fixture = RecoveryFixture()
        self.addCleanup(fixture.close)
        self.assertEqual(fixture.script_path.stat().st_size, 570716)
        self.assertTrue(fixture.script_path.read_bytes().startswith(b"export const meta = "))
        self.assertEqual(len(fixture.event_paths()), 1)
        event = json.loads(fixture.event_paths()[0].read_bytes())
        self.assertEqual((event["seq"], event["kind"]), (1, "reserve"))
        self.assertEqual(fixture.record["attempt_index"], 1)
        self.assertEqual(fixture.record["identity"]["round"], 1)
        self.assertEqual(fixture.old_sources["executor"]["sha256"], OLD_EXECUTOR_SHA)
        self.assertEqual(fixture.old_sources["contract"]["sha256"], OLD_CONTRACT_SHA)
        for name in ("executor", "contract"):
            self.assertEqual(fixture.old_sources[name]["path"], fixture.current_sources[name]["path"])
            self.assertNotEqual(fixture.old_sources[name]["sha256"], fixture.current_sources[name]["sha256"])
        self.assertEqual(fixture.compat["to"]["executor"], digest(fixture.executor.read_bytes()))
        self.assertEqual(fixture.compat["to"]["contract"], digest(fixture.contract.read_bytes()))
        self.assertEqual(fixture.binding["manifest"], fixture.record["manifest"])
        self.assertEqual(fixture.binding["script"], fixture.record["workflow_script"])
        for path in (fixture.operator_index, fixture.acceptance_index):
            index = json.loads(path.read_bytes())
            self.assertEqual(index["target"], file_ref(fixture.target_path))
            for name in ("question", "response"):
                locator = index[name]
                line = fixture.native_path.read_bytes().split(b"\n")[locator["line"] - 1]
                self.assertEqual(locator["line_sha256"], digest(line))
                self.assertEqual(json.loads(line)["uuid"], locator["uuid"])
        fixture.assert_old_unchanged(self)


class RecoveryProtocolTests(unittest.TestCase):
    def setUp(self):
        """先验消费入口，缺功能不是对应业务负控 CAUGHT。"""
        help_result = subprocess.run([sys.executable, "-I", str(EXECUTOR), "--help"],
                                     capture_output=True, check=False)
        self.assertEqual(help_result.returncode, 0, "executor --help is not readable")
        self.assertIn("recover-dispatch-rejection", help_result.stdout.decode(),
                      "FEATURE_NOT_IMPLEMENTED_TDD_RED: recover-dispatch-rejection CLI absent")
        detail = subprocess.run([sys.executable, "-I", str(EXECUTOR),
                                 "recover-dispatch-rejection", "--help"], capture_output=True, check=False)
        self.assertEqual(detail.returncode, 0, "FEATURE_NOT_IMPLEMENTED_TDD_RED: recovery help absent")
        for flag in ("--repo-path", "--manifest", "--build-record", "--native-record", "--tool-use-id",
                     "--operator-index", "--evidence-acceptance-index", "--check-only", "--additional-source"):
            self.assertIn(flag, detail.stdout.decode(), "FEATURE_NOT_IMPLEMENTED_TDD_RED: " + flag)
        visible = load_module(EXECUTOR)
        self.assertTrue(callable(getattr(visible, "recover_dispatch_rejection", None)),
                        "FEATURE_NOT_IMPLEMENTED_TDD_RED: module recovery consumer absent")
        self.assertTrue(hasattr(visible, "_RUNTIME_REJECTION_PROFILES"),
                        "FEATURE_NOT_IMPLEMENTED_TDD_RED: natural static profile data boundary absent")
        self.assertIn("recovery_sources", inspect.signature(visible.build).parameters,
                      "FEATURE_NOT_IMPLEMENTED_TDD_RED: real build recovery_sources absent")
        self.fixture = RecoveryFixture()
        self.addCleanup(self.fixture.close)
        self.environment = mock.patch.dict(os.environ, self.fixture.environment, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.mod = load_module(self.fixture.executor)
        profiles = mock.patch.object(self.mod, "_RUNTIME_REJECTION_PROFILES", self.fixture.runtime_profiles)
        profiles.start()
        self.addCleanup(profiles.stop)

    def recover(self, *, check_only=False, additional_sources=()):
        """真实公开模块消费者；无 caller allowed/policy_ok/test flag。"""
        f = self.fixture
        return self.mod.recover_dispatch_rejection(
            repo_path=f.repo, manifest_path=f.manifest_path, build_record_path=f.build_record_path,
            native_record_path=f.native_path, tool_use_id="call_fixture_rejection",
            operator_index=f.operator_index, evidence_acceptance_index=f.acceptance_index,
            check_only=check_only, additional_sources=tuple(additional_sources))

    def refused(self, action, reason_prefix):
        """同时钉具体业务层和零写；不能让所有负控在 source/stale gate 提前红。"""
        before = tree_snapshot(self.fixture.root)
        with self.assertRaises(self.mod.ExecutorError) as caught:
            action()
        self.assertEqual(caught.exception.error_code, "E_RECOVERY_EVIDENCE")
        self.assertTrue(caught.exception.reason.startswith(reason_prefix),
                        (reason_prefix, caught.exception.reason))
        self.assertEqual(tree_snapshot(self.fixture.root), before)
        return caught.exception

    def replay(self):
        f = self.fixture
        state = self.mod._load_scope(f.scope, f.manifest, self.mod._Inputs())
        return state, self.mod._replay_history(state)

    def test_check_only_validates_both_authorities_without_any_tree_write(self):
        """保护破坏：只预览容量、不验 authority，或 check-only 偷建 blob/lock/event。"""
        before = tree_snapshot(self.fixture.root)
        result = self.recover(check_only=True)
        self.assertIs(result["eligible"], True)
        self.assertIs(result["would_append"], True)
        self.assertIsNone(result.get("event"))
        self.assertEqual(tree_snapshot(self.fixture.root), before)
        self.assertEqual(len(self.fixture.event_paths()), 1)

    def test_each_missing_authority_refuses_without_mutation(self):
        """保护破坏：独占声明和历史映像接受政策互相替代。"""
        f = self.fixture
        for path, prefix in ((f.operator_index, "operator_"), (f.acceptance_index, "evidence_acceptance_")):
            with self.subTest(authority=path.name):
                raw = path.read_bytes()
                path.unlink()
                try:
                    self.refused(lambda: self.recover(check_only=True), prefix)
                    self.refused(self.recover, prefix)
                finally:
                    path.write_bytes(raw)

    def test_decline_and_global_fencing_do_not_become_operator_confirmation(self):
        """保护破坏：把同文答案、任一 option 或 locator selection 当肯定声明。"""
        for selected in (1, 2):
            with self.subTest(option=selected):
                self.fixture.restore_authorities()
                self.fixture.choose("operator", selected)
                self.refused(self.recover, "operator_")

    def test_retain_threshold_does_not_become_evidence_acceptance(self):
        """保护破坏：把独立两选项政策中的拒绝也转换为 accept_boundary。"""
        self.fixture.choose("acceptance", 1)
        self.refused(self.recover, "evidence_acceptance_")

    def test_each_authority_binds_the_actual_old_target_not_just_a_valid_fileref(self):
        """保护破坏：FileRef 校验正确便允许另一对象借用同一签字。"""
        for kind in ("operator", "acceptance"):
            with self.subTest(authority=kind):
                self.fixture.restore_authorities()
                self.fixture.wrong_target(kind)
                self.refused(self.recover, "target_")

    def test_matching_request_answer_and_preview_still_reject_wrong_target_hash(self):
        """保护破坏：只比较问答相等，不重算 preview 中的真实 script 绑定。"""
        for kind in ("operator", "acceptance"):
            with self.subTest(authority=kind):
                self.fixture.restore_authorities()
                self.fixture.rewrite_template(kind, preview=True)
                self.refused(self.recover, "target_")

    def test_caller_selected_semantic_template_cannot_define_authority(self):
        """保护破坏：caller 同步修改请求/答案/locator 后自选语义白名单。"""
        for kind, prefix in (("operator", "operator_"), ("acceptance", "evidence_acceptance_")):
            with self.subTest(authority=kind):
                self.fixture.restore_authorities()
                self.fixture.rewrite_template(kind)
                self.refused(self.recover, prefix)

    def test_api_request_blob_copies_are_not_root_human_answers(self):
        """保护破坏：递归搜索 API envelope 的同文拷贝并冒充真人 root authority。"""
        for kind in ("operator", "acceptance"):
            with self.subTest(authority=kind):
                self.fixture.restore_authorities()
                self.fixture.api_copy(kind)
                self.refused(self.recover, "native_")

    def test_locator_approved_boolean_cannot_replace_real_authority(self):
        """保护破坏：索引布尔绕过原生拒绝选择，或容忍封闭 schema 的未知键。"""
        self.fixture.choose("acceptance", 1)
        index = json.loads(self.fixture.acceptance_index.read_bytes())
        index["approved"] = True
        write_json(self.fixture.acceptance_index, index)
        self.refused(self.recover, "evidence_acceptance_")

    def test_nonexact_capacity_error_remains_pending(self):
        """保护破坏：substring/timeout/普通业务 error 也被识别为精确平台容量拒绝。"""
        f = self.fixture
        for value in ("timeout", "quoted: <tool_use_error>Workflow script file exceeds 524288 bytes</tool_use_error>"):
            with self.subTest(error=value):
                f.restore_authorities()
                f.rows[1]["message"]["content"][0]["content"] = value
                f.rows[1]["toolUseResult"] = "Error: " + value
                f._write_native()
                self.refused(self.recover, "native_")

    def test_related_success_and_unpaired_unknown_veto_both_check_and_mutation(self):
        """保护破坏：无 runId 等同未运行，或单对象政策覆盖已知成功/未知调用。"""
        for status in ("success", "unknown"):
            with self.subTest(status=status):
                self.fixture.restore_authorities()
                self.fixture.append_workflow(status=status)
                self.refused(lambda: self.recover(check_only=True), "counterevidence")
                self.refused(self.recover, "counterevidence")

    def test_new_explicit_root_is_scanned_for_related_counterevidence(self):
        """保护破坏：只看原拒绝所在文件，静默忽略 caller 已知的另一个 root。"""
        other = self.fixture.append_workflow(status="unknown", new_root=True)
        self.refused(lambda: self.recover(additional_sources=(other,)), "counterevidence")

    def test_unrelated_success_does_not_become_a_permanent_red_gate(self):
        """保护破坏：把可信载体中的所有 Workflow 都视为旧对象关联调用。"""
        self.fixture.append_workflow(status="success", related=False)
        before = tree_snapshot(self.fixture.root)
        result = self.recover(check_only=True)
        self.assertIs(result["eligible"], True)
        self.assertIs(result["would_append"], True)
        self.assertEqual(tree_snapshot(self.fixture.root), before)

    def test_mutation_appends_only_seq2_dispatch_rejected_and_keeps_old_budget(self):
        """保护破坏：回写 genesis/seq1、伪造 void/commit，或恢复时消耗一个审计轮。"""
        result = self.recover()
        self.assertIs(result["eligible"], True)
        event_ref = result["event"]
        self.assertEqual(set(event_ref), {"path", "sha256"})
        self.assertEqual(file_ref(event_ref["path"]), event_ref)
        self.assertEqual(len(self.fixture.event_paths()), 2)
        event = json.loads(Path(event_ref["path"]).read_bytes())
        self.assertEqual((event["seq"], event["kind"]), (2, "dispatch_rejected"))
        self.assertEqual(event["previous_event"], self.fixture.binding["reservation"])
        self.assertEqual(event["genesis"], self.fixture.binding["genesis"])
        self.assertEqual(set(event["payload"]), {"reservation", "build_record", "evidence", "input_closure", "source_transition"})
        state, view = self.replay()
        self.assertEqual(state["reserve_count"], 1)
        self.assertIsNone(state["pending"])
        self.assertEqual(len(view["attempts"]), 0)
        self.assertEqual(view["charged_rounds"], 0)
        self.assertEqual(view["effective_limit"], 5)
        self.assertEqual(view["remaining_rounds"], 5)
        self.fixture.assert_old_unchanged(self)

    def test_both_authorities_are_derived_and_frozen_independently(self):
        """保护破坏：只验证一份 authority，或在 evidence 中抄 caller 输出。"""
        event = json.loads(Path(self.recover()["event"]["path"]).read_bytes())
        evidence_ref = event["payload"]["evidence"]
        self.assertEqual(file_ref(evidence_ref["path"]), evidence_ref)
        evidence = json.loads(Path(evidence_ref["path"]).read_bytes())
        operator = json.loads(Path(evidence["operator_statement"]["path"]).read_bytes())["sourceData"]
        acceptance = json.loads(Path(evidence["evidence_acceptance"]["path"]).read_bytes())["sourceData"]
        self.assertEqual(operator["decision"], "confirm_local_domain")
        self.assertEqual(acceptance["decision"], "accept_boundary")
        self.assertEqual(operator["target"], self.fixture.binding)
        self.assertEqual(acceptance["target"], self.fixture.binding)
        self.assertEqual(operator["counterevidence_policy"], "veto")
        self.assertEqual(acceptance["residual_uncertainty"], "historical_executable_identity_not_independently_verified")
        self.assertNotEqual(operator["question"]["uuid"], acceptance["question"]["uuid"])
        basis = json.loads(Path(evidence["runtime_rejection_basis"]["path"]).read_bytes())
        self.assertEqual(basis["native_version"], "2.1.318")
        self.assertEqual(basis["windows"], self.fixture.static_windows)

    def test_dual_source_closures_preserve_old_logical_identity_and_active_new_bytes(self):
        """保护破坏：同 path 的两代源码扁平入缓存，或重写旧 genesis 为新源。"""
        f = self.fixture
        event = json.loads(Path(self.recover()["event"]["path"]).read_bytes())
        transition = event["payload"]["source_transition"]
        self.assertEqual(transition["compatibility_id"], "pre-dispatch-rejection-v1")
        self.assertEqual(transition["from_sources"], f.old_sources)
        self.assertEqual(transition["to_sources"], f.current_sources)
        self.assertNotEqual(event["payload"]["input_closure"]["sha256"], f.old_closure["sha256"])
        self.assertEqual(file_ref(f.old_closure["path"]), f.old_closure)
        self.assertEqual(file_ref(transition["compatibility_manifest"]["path"]), transition["compatibility_manifest"])
        for name in ("executor", "contract"):
            self.assertEqual(transition["from_sources"][name]["path"], transition["to_sources"][name]["path"])
            self.assertNotEqual(transition["from_sources"][name]["sha256"], transition["to_sources"][name]["sha256"])
        self.replay()
        f.assert_old_unchanged(self)

    def test_same_key_is_idempotent_after_unrelated_native_append(self):
        """保护破坏：用整个活跃 JSONL hash 作幂等 key，或同一恢复追加第二事件。"""
        first = self.recover()["event"]
        self.fixture.append_unrelated_message()
        before = tree_snapshot(self.fixture.root)
        second = self.recover()["event"]
        self.assertEqual(second, first)
        self.assertEqual(len(self.fixture.event_paths()), 2)
        self.assertEqual(tree_snapshot(self.fixture.root), before)

    def test_idempotence_checks_current_same_root_counterevidence_before_shortcut(self):
        """保护破坏：看到已有 seq2 即返回旧成功，未扫描之后追加的相关调用。"""
        self.recover()
        self.fixture.append_workflow(status="success")
        self.refused(self.recover, "counterevidence")
        self.assertEqual(len(self.fixture.event_paths()), 2)

    def test_idempotence_checks_new_known_root_before_input_changed_shortcut(self):
        """保护破坏：新增载体时先报输入变化，从而不检查它带来的已知反证。"""
        self.recover()
        other = self.fixture.append_workflow(status="unknown", new_root=True)
        self.refused(lambda: self.recover(additional_sources=(other,)), "counterevidence")
        self.assertEqual(len(self.fixture.event_paths()), 2)

    def test_idempotence_rejects_prefix_rewrite_even_with_same_selected_lines(self):
        """保护破坏：只核 selected hashes，忽略旧冻结载体必须仍为 live 字节前缀。"""
        self.fixture.append_unrelated_message()
        self.recover()
        self.fixture.rows[-1]["message"]["content"][0]["text"] = "Changed old prefix bytes"
        self.fixture._write_native()
        error = self.refused(self.recover, "input_changed_source_prefix_or_bytes")
        self.assertEqual(error.reason, "input_changed_source_prefix_or_bytes")

    def test_real_build_requires_recovery_sources_without_another_recover_call(self):
        """保护破坏：把 live 续接门委托给调用方先调用 recover，而普通 build 仍可穿过。"""
        event = self.recover()["event"]
        manifest, run, _ = self.fixture.successor(event)
        error = self.refused(lambda: self.mod.build(self.fixture.repo, manifest, run), "recovery_sources_required")
        self.assertEqual(error.reason, "recovery_sources_required")
        self.assertFalse(run.exists())
        self.assertEqual(len(self.fixture.event_paths()), 2)

    def test_real_build_directly_vetoes_new_related_live_success_or_unknown(self):
        """保护破坏：seq2 重放无反证就当成此刻 live 无反证；不先重跑 recover。"""
        event = self.recover()["event"]
        manifest, run, index = self.fixture.successor(event)
        for status in ("success", "unknown"):
            with self.subTest(status=status):
                self.fixture.restore_authorities()
                self.fixture.append_workflow(status=status)
                error = self.refused(lambda: self.mod.build(self.fixture.repo, manifest, run, recovery_sources=index),
                                     "recovery_handoff_counterevidence")
                self.assertEqual(error.reason, "recovery_handoff_counterevidence")
                self.assertFalse(run.exists())
                self.assertEqual(len(self.fixture.event_paths()), 2)

    def test_real_build_scans_new_sources_index_root_before_successor_publication(self):
        """保护破坏：RecoverySourcesIndex 变成 caller 无冲突令牌，不读新增载体。"""
        event = self.recover()["event"]
        other = self.fixture.append_workflow(status="unknown", new_root=True)
        manifest, run, index = self.fixture.successor(event, (other,))
        self.refused(lambda: self.mod.build(self.fixture.repo, manifest, run, recovery_sources=index),
                     "recovery_handoff_counterevidence")
        self.assertFalse(run.exists())
        self.assertEqual(len(self.fixture.event_paths()), 2)

    def test_successor_is_attempt2_round1_with_frozen_preflight_not_a_new_cycle(self):
        """保护破坏：重开 cycle、重编号 round、写 observe，或未冻结真实 handoff。"""
        event_ref = self.recover()["event"]
        self.fixture.append_unrelated_message()
        manifest, run, index = self.fixture.successor(event_ref)
        self.mod.build(self.fixture.repo, manifest, run, recovery_sources=index)
        record = json.loads((run / "build-record.json").read_bytes())
        self.assertEqual(record["attempt_index"], 2)
        self.assertEqual(record["identity"]["round"], 1)
        self.assertEqual(record["identity"]["audit_cycle_id"], "cycle-protocol-fixture")
        self.assertEqual(record["genesis"], self.fixture.binding["genesis"])
        self.assertEqual(record["prefix_head"], event_ref)
        self.assertEqual(record["sources"], self.fixture.current_sources)
        preflight_ref = record["recovery_preflight"]
        self.assertEqual(preflight_ref, file_ref(run / "recovery-preflight.json"))
        preflight = json.loads(Path(preflight_ref["path"]).read_bytes())
        self.assertEqual(preflight["recovery_event"], event_ref)
        self.assertEqual(preflight["prefix_head"], event_ref)
        self.assertEqual(preflight["rejected_reservation"], self.fixture.binding["reservation"])
        self.assertEqual(preflight["successor"]["attempt_index"], 2)
        self.assertEqual(preflight["successor"]["manifest"], file_ref(manifest))
        self.assertEqual(preflight["successor"]["workflow_script"], file_ref(run / "workflow.js"))
        events = [json.loads(path.read_bytes()) for path in self.fixture.event_paths()]
        self.assertEqual([row["kind"] for row in events], ["reserve", "dispatch_rejected", "reserve"])
        state, view = self.replay()
        self.assertEqual(state["reserve_count"], 2)
        self.assertEqual(view["charged_rounds"], 0)
        self.assertEqual(len(view["attempts"]), 0)
        self.fixture.assert_old_unchanged(self)

    def test_frozen_replay_never_reads_missing_live_authority_or_static_sources(self):
        """保护破坏：离线历史重放重新读取 live 原件、重新签字或使用当前源码解旧源。"""
        self.recover()
        f = self.fixture
        blocked = {f.native_path.resolve(), f.operator_index.resolve(), f.acceptance_index.resolve(),
                   f.target_path.resolve(), f.executor.resolve(), f.contract.resolve()}
        blocked.update(Path(value[key]).resolve() for value in f.runtime_profiles.values()
                       for key in ("capacity_source", "loader_source"))
        for path in blocked:
            path.unlink()
        original_open = Path.open

        def reject_live(path, *args, **kwargs):
            if path.resolve() in blocked:
                raise AssertionError("historical replay attempted live read: " + str(path))
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, "open", reject_live):
            state, view = self.replay()
        self.assertIsNone(state["pending"])
        self.assertEqual(state["reserve_count"], 1)
        self.assertEqual(view["charged_rounds"], 0)

    def test_pending_successor_resumes_frozen_handoff_without_live_reauthorization(self):
        """保护破坏：attempt2 精确 resume 再走 live 门，将合法后续调用倒灌进旧证明。"""
        event = self.recover()["event"]
        manifest, run, index = self.fixture.successor(event)
        self.mod.build(self.fixture.repo, manifest, run, recovery_sources=index)
        original_record = (run / "build-record.json").read_bytes()
        self.fixture.append_workflow(status="success")
        self.fixture.native_path.unlink()
        index.unlink()
        before_events = [p.read_bytes() for p in self.fixture.event_paths()]
        result = self.mod.build(self.fixture.repo, manifest, run)
        self.assertIs(result["resume_only"], True)
        self.assertEqual((run / "build-record.json").read_bytes(), original_record)
        self.assertEqual([p.read_bytes() for p in self.fixture.event_paths()], before_events)
        self.assertEqual(len(self.fixture.event_paths()), 3)

    def test_recovery_cli_is_stale_after_legal_successor_not_reusable_authorization(self):
        """保护破坏：head 已到 attempt2 后仍返回旧恢复 eligible/成功并授新动作。"""
        event = self.recover()["event"]
        manifest, run, index = self.fixture.successor(event)
        self.mod.build(self.fixture.repo, manifest, run, recovery_sources=index)
        self.refused(self.recover, "target_")
        self.assertEqual(len(self.fixture.event_paths()), 3)


if __name__ == "__main__":
    unittest.main()
