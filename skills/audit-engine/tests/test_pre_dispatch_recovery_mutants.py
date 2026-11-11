"""TASK-012 非作者定向 fixture：每例单独建合法旧 reserve，防子例污染。

生产 consumer 不替换；只在隔离 native 输入中制造业务坏态。编译源码变异
和独立 good control 的重放脚本位于本轮 B-task012 证据目录，不运行 Workflow。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
import unittest

_spec = importlib.util.spec_from_file_location(
    'task012_handoff_support', Path(__file__).with_name('test_pre_dispatch_recovery_handoff.py'))
assert _spec is not None and _spec.loader is not None
_handoff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_handoff)
support = _handoff.support


class FreshMutationContracts(unittest.TestCase):
    f: Any
    mod: Any
    setUp = _handoff.HandoffTests.setUp
    recover = _handoff.HandoffTests.recover
    build_successor = _handoff.HandoffTests.build_successor
    require_feature = _handoff.HandoffTests.require_feature
    assert_counterevidence = _handoff.HandoffTests.assert_counterevidence

    def submit(self, additional=()):
        f = self.f
        return self.mod.recover_dispatch_rejection(
            f.repo, f.manifest_path, f.build_record_path, f.native_path,
            'call_fixture_rejection', f.operator_index, f.acceptance_index,
            check_only=False, additional_sources=tuple(additional))

    def refuse_recovery(self, action, reason):
        """指定业务原因、全树零写和同一个真实 seq1 都是承重断言。"""
        before = support.tree_snapshot(self.f.root)
        events = [p.read_bytes() for p in self.f.event_paths()]
        with self.assertRaises(self.mod.ExecutorError,
                               msg='SC-RECOVERY: invalid evidence unlocked the reservation') as caught:
            action()
        self.assertEqual((caught.exception.error_code, caught.exception.reason),
                         ('E_RECOVERY_EVIDENCE', reason))
        self.assertEqual(support.tree_snapshot(self.f.root), before)
        self.assertEqual([p.read_bytes() for p in self.f.event_paths()], events)
        self.assertEqual(len(events), 1)
        self.f.assert_old_unchanged(self)

    def error_text(self, value):
        self.f.rows[1]['message']['content'][0]['content'] = value
        self.f.rows[1]['toolUseResult'] = 'Error: ' + value
        self.f._write_native()
        self.refuse_recovery(self.submit, 'native_error')

    def test_timeout_error_does_not_unlock_old_reservation(self):
        self.error_text('timeout')

    def test_quoted_capacity_error_does_not_unlock_old_reservation(self):
        self.error_text('quoted: <tool_use_error>Workflow script file exceeds 524288 bytes</tool_use_error>')

    def extra_root_before_recovery(self, status):
        root = self.f.append_workflow(status=status, new_root=True)
        self.refuse_recovery(lambda: self.submit((root,)), 'counterevidence_native')

    def test_known_second_root_success_vetoes_both_valid_signatures(self):
        self.extra_root_before_recovery('success')

    def test_known_second_root_unknown_vetoes_both_valid_signatures(self):
        self.extra_root_before_recovery('unknown')

    def test_seq2_direct_build_scans_known_second_root_success(self):
        # No second recover: seq2 -> new indexed root -> ordinary public build.
        event = self.recover()
        root = self.f.append_workflow(status='success', new_root=True)
        manifest, run, index = self.f.successor(event, (root,))
        self.assert_counterevidence(manifest, run, index)
        self.assertEqual(len(self.f.event_paths()), 2)

    def test_plain_user_tool_use_result_is_not_independent_human_acceptance(self):
        # The same recorded content must not acquire authority merely by being
        # attached to an ordinary user row instead of the paired tool_result.
        self.mod._parse_evidence_acceptance(
            self.f.repo, self.f.binding, self.f.acceptance_index, inputs=self.mod._Inputs())
        _, response = self.f._authority('acceptance')
        response['message']['content'] = [{'type': 'text', 'text': '接受此边界，继续恢复'}]
        self.f._write_native()
        self.refuse_recovery(self.submit, 'native_ambiguous_pair')


if __name__ == '__main__':
    unittest.main()
