"""TASK-002: isolated TDD contracts; no Workflow execution or real authority.

The production executor and all repos/native locations used here are temporary copies.
The future recovery CLI test is explicitly a feature-absence RED, not a caught
recovery-business failure. Tests do not execute historical scripts.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

# unittest discovery adds this directory; -I does not, so add only the known tests dir.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_audit_executor as fixture

LIMIT = 524288


def tree(path):
    if not path.exists():
        return {}
    return {str(p.relative_to(path)): ('dir' if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest())
            for p in path.rglob('*')}


class CapacityContracts(unittest.TestCase):
    def setUp(self):
        self.env = tempfile.TemporaryDirectory(prefix='recovery-test-home-')
        self.addCleanup(self.env.cleanup)
        environ = patch.dict(os.environ, {'HOME': self.env.name, 'CLAUDE_CONFIG_DIR': self.env.name})
        environ.start()
        self.addCleanup(environ.stop)
        self.f = fixture.BuildContractTests('test_pending_identical_resume_and_missing_record_repair_do_not_redispatch')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def sized(self, length, prefix=''):
        # One ASCII prompt byte adds exactly one rendered byte. Render here only to
        # size the fixture; the asserted boundary is the literal public 524288.
        self.f.manifest['roles'][0]['prompt'] = prefix
        base = len(self.f.mod._workflow(self.f.manifest, '0' * 64))
        self.f.manifest['roles'][0]['prompt'] += 'x' * (length - base)
        self.f.write(self.f.manifest_path, self.f.manifest)
        script = self.f.mod._workflow(self.f.manifest, hashlib.sha256(self.f.manifest_path.read_bytes()).hexdigest())
        self.assertEqual(len(script), length, 'fixture must hit the exact final byte boundary')
        return script

    def test_below_limit_build_succeeds_and_publishes_checked_bytes(self):
        """Rejecting L-1 or publishing a different render breaks a valid build."""
        expected = self.sized(524287)
        renderer = self.f.mod._workflow
        with patch.object(self.f.mod, '_workflow', wraps=renderer) as spy:
            result = self.f.mod.build(self.f.repo, self.f.manifest_path, self.f.run_dir)
        self.assertFalse(result['resume_only'])
        self.assertEqual(Path(result['workflow_script']).read_bytes(), expected)
        self.assertEqual(spy.call_count, 1, 'new reservation must render once')

    def test_publication_uses_first_checked_renderer_artifact(self):
        """A second renderer call must not replace the bytes that passed capacity."""
        self.f.write(self.f.manifest_path, self.f.manifest)
        checked = b'// controlled first renderer artifact; not executed\n'
        rerendered = b'// a different second artifact must never be published\n'
        with patch.object(self.f.mod, '_workflow', side_effect=[checked, rerendered]):
            result = self.f.mod.build(self.f.repo, self.f.manifest_path, self.f.run_dir)
        self.assertEqual(Path(result['workflow_script']).read_bytes(), checked,
                         'real publication must preserve the first checked producer artifact')

    def test_exact_limit_is_allowed(self):
        """An off-by-one >= limit rejection must fail this control."""
        expected = self.sized(524288)
        result = self.f.mod.build(self.f.repo, self.f.manifest_path, self.f.run_dir)
        self.assertEqual(Path(result['workflow_script']).read_bytes(), expected)

    def test_one_byte_over_reports_capacity(self):
        """Accepting 524289 final bytes must produce this specific business RED."""
        self.sized(524289)
        with self.assertRaises(self.f.mod.ExecutorError, msg='SC-CAPACITY: build accepted 524289 final bytes') as caught:
            self.f.mod.build(self.f.repo, self.f.manifest_path, self.f.run_dir)
        self.assertEqual(caught.exception.error_code, 'E_WORKFLOW_CAPACITY')

    def assert_capacity_error(self, error):
        if error is None:
            self.fail('SC-CAPACITY: expected capacity error, not success')
        self.assertEqual(getattr(error, 'error_code', None), 'E_WORKFLOW_CAPACITY',
                         'another error branch cannot stand in for capacity rejection')

    def test_one_byte_over_does_not_write_tree(self):
        """A wrong early error cannot make zero-write capacity validation green."""
        self.sized(524289)
        reports = self.f.repo / '.aria' / 'audit-reports'
        before = tree(reports)
        error = None
        try:
            self.f.mod.build(self.f.repo, self.f.manifest_path, self.f.run_dir)
        except self.f.mod.ExecutorError as exc:
            error = exc
        # Observe writes independently even when the baseline omitted the error.
        self.assertEqual(tree(reports), before, 'oversize build wrote audit tree')
        self.assert_capacity_error(error)

    def test_one_byte_over_never_enters_real_writer_lock(self):
        """Lock acquisition, even without a visible tree change, is too late."""
        self.sized(524289)
        lock = self.f.mod._writer_lock
        calls = []
        def observed(scope):
            calls.append(scope)
            return lock(scope)
        error = None
        with patch.object(self.f.mod, '_writer_lock', side_effect=observed):
            try:
                self.f.mod.build(self.f.repo, self.f.manifest_path, self.f.run_dir)
            except self.f.mod.ExecutorError as exc:
                error = exc
        self.assertEqual(calls, [], 'oversize build reached the real writer lock')
        self.assert_capacity_error(error)

    def test_small_utf8_manifest_expands_to_oversized_escaped_script(self):
        """Measuring UTF-8 manifest instead of final escaped JS accepts oversized input."""
        self.f.manifest['roles'][0]['prompt'] = '中' * 87000
        raw = json.dumps(self.f.manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        self.assertLess(len(raw), LIMIT)
        self.f.manifest_path.write_bytes(raw)
        final = self.f.mod._workflow(self.f.manifest, hashlib.sha256(raw).hexdigest())
        self.assertGreater(len(final), LIMIT)
        with self.assertRaises(self.f.mod.ExecutorError, msg='SC-CAPACITY: escaped script accepted') as caught:
            self.f.mod.build(self.f.repo, self.f.manifest_path, self.f.run_dir)
        self.assertEqual(caught.exception.error_code, 'E_WORKFLOW_CAPACITY')

    def test_healthy_pending_restores_record_without_new_event(self):
        """A compliant pending resume must repair its original record without redispatch."""
        self.f.build()
        record = self.f.run_dir / 'build-record.json'
        original = record.read_bytes()
        record.unlink()
        before = tree(self.f.scope())
        self.assertTrue(self.f.mod.build(self.f.repo, self.f.manifest_path, self.f.run_dir)['resume_only'])
        self.assertEqual(record.read_bytes(), original)
        self.assertEqual(tree(self.f.scope()), before)

    def test_only_source_change_keeps_pending_and_reports_source_drift(self):
        """Source mismatch must not reuse or replace the existing reservation."""
        self.f.build()
        executor = self.f.engine / 'scripts' / 'audit_executor.py'
        executor.write_bytes(executor.read_bytes() + b'\n# isolated source drift\n')
        before = tree(self.f.scope())
        with self.assertRaises(self.f.mod.ExecutorError) as caught:
            self.f.mod.build(self.f.repo, self.f.manifest_path, self.f.run_dir)
        self.assertEqual(caught.exception.error_code, 'E_SOURCE_DRIFT')
        self.assertEqual(tree(self.f.scope()), before)

    def test_legacy_oversized_pending_then_source_drift(self):
        """The unchanged released Python host repairs the same pending, but rejects source drift."""
        plugin = Path(__file__).resolve().parents[3]
        old = subprocess.run(['git', '-C', str(plugin), 'show',
                              '2d8e223f:skills/audit-engine/scripts/audit_executor.py'],
                             capture_output=True, check=True).stdout
        self.assertEqual(hashlib.sha256(old).hexdigest(),
                         '5b9a32e23d665e494a21dc002a1a8498db445462762fba52916ce79716333777')
        executor = self.f.engine / 'scripts' / 'audit_executor.py'
        executor.write_bytes(old)
        self.f.mod = fixture.load_module(executor)
        self.sized(524289)
        self.f.mod.build(self.f.repo, self.f.manifest_path, self.f.run_dir)
        record = self.f.run_dir / 'build-record.json'
        original = record.read_bytes()
        record.unlink()
        before = tree(self.f.scope())
        self.assertTrue(self.f.mod.build(self.f.repo, self.f.manifest_path, self.f.run_dir)['resume_only'])
        self.assertEqual(record.read_bytes(), original)
        self.assertEqual(tree(self.f.scope()), before)
        executor.write_bytes(old + b'\n# isolated source drift\n')
        with self.assertRaises(self.f.mod.ExecutorError) as caught:
            self.f.mod.build(self.f.repo, self.f.manifest_path, self.f.run_dir)
        self.assertEqual(caught.exception.error_code, 'E_SOURCE_DRIFT')
        self.assertEqual(tree(self.f.scope()), before, 'source drift must not append a reserve')

    def test_existing_legacy_oversize_capacity_error_precedes_source_drift_without_repair(self):
        """New host must reject old oversized input without repairing a missing record."""
        executor = self.f.engine / 'scripts' / 'audit_executor.py'
        current_host = executor.read_bytes()
        plugin = Path(__file__).resolve().parents[3]
        legacy = subprocess.run(
            ['git', '-C', str(plugin), 'show',
             '2d8e223f:skills/audit-engine/scripts/audit_executor.py'],
            capture_output=True, check=True).stdout
        self.assertEqual(hashlib.sha256(legacy).hexdigest(),
                         '5b9a32e23d665e494a21dc002a1a8498db445462762fba52916ce79716333777')
        executor.write_bytes(legacy)
        self.f.mod = fixture.load_module(executor)
        self.sized(524289)
        self.f.mod.build(self.f.repo, self.f.manifest_path, self.f.run_dir)
        record = self.f.run_dir / 'build-record.json'
        record.unlink()
        executor.write_bytes(current_host)
        self.f.mod = fixture.load_module(executor)
        reports = self.f.repo / '.aria' / 'audit-reports'
        before = tree(reports)
        error = None
        try:
            self.f.mod.build(self.f.repo, self.f.manifest_path, self.f.run_dir)
        except self.f.mod.ExecutorError as exc:
            error = exc
        self.assertEqual(tree(reports), before,
                         'capacity refusal must not repair record or touch existing audit paths')
        self.assertFalse(record.exists())
        self.assert_capacity_error(error)


class CheckerCapacityContracts(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix='recovery-checker-home-')
        self.addCleanup(home.cleanup)
        env = patch.dict(os.environ, {'HOME': home.name, 'CLAUDE_CONFIG_DIR': home.name})
        env.start()
        self.addCleanup(env.stop)
        self.h = fixture.PreparePolicyTests('test_request_priority_pairs_and_required_partial_full_scripts')
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.previous = self.h.second()

    def oversize(self):
        # Inject final bytes at the publication seam, not a real native script.
        called = []
        def render(*_args, **_kwargs):
            del _args, _kwargs  # producer seam deliberately supplies controlled bytes
            called.append(True)
            return b'x' * 524289
        error = None
        with patch.object(self.h.mod, '_render_policy_workflow', side_effect=render):
            try:
                self.h.prepare(previous=self.previous)
            except self.h.mod.ExecutorError as exc:
                error = exc
        self.assertEqual(called, [True], 'fixture must enter required checker renderer')
        return error

    def test_checker_reports_capacity(self):
        """Accepting oversized checker bytes must raise the exact business error."""
        error = self.oversize()
        if error is None:
            self.fail('SC-CHECKER-CAPACITY: oversize checker accepted')
        self.assertEqual(getattr(error, 'error_code', None), 'E_WORKFLOW_CAPACITY')

    def test_checker_does_not_publish_script(self):
        """Missing the error must not mask publication of the oversized script."""
        error = self.oversize()
        self.assertFalse((self.h.f.run_dir / 'policy-workflow.js').exists())
        self.assertEqual(getattr(error, 'error_code', None), 'E_WORKFLOW_CAPACITY',
                         'absence of a script on another error branch is not capacity protection')

    def test_checker_does_not_publish_success_record(self):
        """Missing the error must not mask an invalid success prepare record."""
        error = self.oversize()
        self.assertFalse((self.h.f.run_dir / 'prepare-record.json').exists())
        self.assertEqual(getattr(error, 'error_code', None), 'E_WORKFLOW_CAPACITY',
                         'absence of a record on another error branch is not capacity protection')

    def test_normal_checker_control(self):
        """A required normal-sized checker must still be published."""
        result = self.h.prepare(previous=self.previous)
        request = json.loads(Path(result['policy_request']['path']).read_bytes())
        self.assertTrue(request['required'])
        self.assertGreater(Path(result['policy_script']['path']).stat().st_size, 0)
        self.assertTrue(Path(result['prepare_record']['path']).is_file())


class CheckerToolFailureCharacterization(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory(prefix='recovery-tool-error-home-')
        self.addCleanup(home.cleanup)
        env = patch.dict(os.environ, {'HOME': home.name, 'CLAUDE_CONFIG_DIR': home.name})
        env.start()
        self.addCleanup(env.stop)

    def test_real_checker_error_evidence_remains_unknown_not_synthetic_completion(self):
        """Capacity support must not reinterpret a checker tool error as a terminal run."""
        h = fixture.DriftEvidenceTests(
            'test_tool_error_links_unknown_auxiliary_call_and_not_error_substring')
        h.setUp()
        self.addCleanup(h.doCleanups)
        h.tool_error()
        value = h.verify()
        self.assertEqual(value['kind'], 'tool_error')
        call = value['auxiliary_calls'][0]
        self.assertTrue(call['call_attempted'])
        self.assertIsNone(call['native_agent_id'])
        self.assertIsNone(call['completed_at_ms'])
        self.assertEqual(call['termination_evidence'], 'unknown')
        self.assertIsNone(value['workflow_run_id'])


class RecoveryEntryContract(unittest.TestCase):
    def test_cli_exposes_recovery_entry(self):
        """FEATURE_NOT_IMPLEMENTED_TDD_RED: callers cannot invoke the required CLI."""
        with tempfile.TemporaryDirectory(prefix='recovery-cli-home-') as home:
            env = dict(os.environ, HOME=home, CLAUDE_CONFIG_DIR=home)
            script = Path(__file__).resolve().parents[1] / 'scripts' / 'audit_executor.py'
            result = subprocess.run([sys.executable, '-I', str(script), '--help'], cwd=home,
                                    env=env, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, 'CLI help must execute before feature assertion')
            self.assertIn('recover-dispatch-rejection', result.stdout.decode(),
                          'FEATURE_NOT_IMPLEMENTED_TDD_RED: recovery CLI unavailable')


if __name__ == '__main__':
    unittest.main(verbosity=2)
