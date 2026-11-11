"""SEAM-015-001: late old-manifest indexes, using synthetic native carriers only.

The five refusal methods are RED on c611: ordinary build wrongly publishes a
successor. Healthy controls must stay GREEN. Schema/missing-leaf probes test
mandatory typed acquisition, not a claim of a valid related Workflow run.
No test executes Workflow, real recovery, ELF or private platform modules.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
from typing import Any, Generator
import unittest
from unittest.mock import patch


def _module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TESTS = Path(__file__).resolve().parent
support: Any = _module('late_index_fixture_support', TESTS / 'pre_dispatch_recovery_fixtures.py')
transaction: Any = _module('late_index_native_constructor', TESTS / 'test_pre_dispatch_recovery_transaction.py')
KEEP_FIXTURES = False  # Evidence runner only; never changes business assertions.
RECORDED_CASES: list[dict[str, Any]] = []
ACTIVE_CASE: dict[str, Any] | None = None  # Optional passive audit observer.
INDEX_KEYS = ('post_audit_index_path', 'post_drift_index_path', 'post_disposition_index_path')
PREPARATION = ('workflow.js', 'build-record.json', 'input-closure.json', 'build-metadata.json',
               'recovery-preflight.json', 'recovery-handoff-observations.json')


def _events(f: Any) -> list[dict[str, Any]]:
    return [{'ref': support.file_ref(p), 'event': json.loads(p.read_bytes())} for p in f.event_paths()]


def _roots(f: Any) -> list[dict[str, Any]]:
    return [support.file_ref(p) for p in sorted(f.config_root.glob('projects/*/*.jsonl'))]


class LateIndexHandoff(unittest.TestCase):
    @contextmanager
    def scenario(self) -> Generator[tuple[Any, Any, Path, Path, Path, dict[str, Any]], None, None]:
        f = support.RecoveryFixture()
        if KEEP_FIXTURES:
            f.temporary._finalizer.detach()
        row: dict[str, Any] = {'id': self.id(), 'fixture_root': str(f.root), 'builds': []}
        RECORDED_CASES.append(row)
        try:
            with patch.dict('os.environ', f.environment, clear=True):
                m = support.load_module(f.executor)
                with patch.object(m, '_RUNTIME_REJECTION_PROFILES', f.runtime_profiles):
                    catalog_raw = (support.ENGINE / 'references/pre-dispatch-recovery-compat.json').read_bytes()
                    self.assertEqual(json.loads(catalog_raw), json.loads(f.compat_path.read_bytes()),
                                     'SETUP: published catalog must match this actual fixture generation')
                    f.compat_path.write_bytes(catalog_raw)
                    self.assertEqual(json.loads(f.compat_path.read_bytes()), m._recovery_compatibility_manifest(f.repo),
                                     'SETUP: current compatibility catalog must match actual fixture source')
                    row['package'] = {key: support.file_ref(path) for key, path in
                                      [('source', f.executor), ('contract', f.contract), ('catalog', f.compat_path)]}
                    bound = {key: Path(f.manifest['evidence'][key]) for key in INDEX_KEYS}
                    self.assertTrue(all(not p.exists() and not p.is_symlink() for p in bound.values()),
                                    'SETUP: all old bound post-run locators must be absent during seq2')
                    row['old_bound_indexes'] = {key: str(p) for key, p in bound.items()}
                    row['known_roots_before'] = _roots(f)
                    recovered = m.recover_dispatch_rejection(f.repo, f.manifest_path, f.build_record_path,
                        f.native_path, 'call_fixture_rejection', f.operator_index, f.acceptance_index)
                    manifest, output, index = f.successor(recovered['event'])
                    self.assertEqual(json.loads(index.read_bytes())['additional_sources'], [])
                    self.assertEqual([e['event']['kind'] for e in _events(f)], ['reserve', 'dispatch_rejected'])
                    row.update(seq2_result=recovered, prefix_before=_events(f),
                               recovery_sources=support.file_ref(index),
                               recovery_sources_value=json.loads(index.read_bytes()),
                               build_arguments={'repo': str(f.repo), 'manifest': str(manifest),
                                                'output': str(output), 'recovery_sources': str(index)})
                    try:
                        yield f, m, manifest, output, index, row
                    finally:
                        row['events_after'] = _events(f)
                        row['known_roots_after'] = _roots(f)
                        row['preparation_after'] = [name for name in PREPARATION if (output / name).exists()]
                        row['pinned_old_unchanged'] = all(Path(p).read_bytes() == raw for p, raw in f.pinned_old_files.items())
                        self.assertEqual(row['known_roots_before'], row['known_roots_after'], 'native root bytes changed')
                        self.assertEqual(row['prefix_before'], row['events_after'][:2], 'old seq1/seq2 bytes changed')
                        self.assertTrue(row['pinned_old_unchanged'], 'old immutable preparation changed')
        finally:
            if not KEEP_FIXTURES:
                f.close()

    def build(self, m: Any, f: Any, manifest: Path, output: Path, index: Path | None,
              row: dict[str, Any]) -> tuple[dict[str, Any], Any]:
        global ACTIVE_CASE
        phase: dict[str, Any] = {'fixture_root': str(f.root), 'physical_opens': [], 'logical_reads': []}
        row['builds'].append(phase)
        original = m._recovery_read

        def read(reader: Any, path: Path, code: str, role: str) -> bytes:
            phase['logical_reads'].append({'path': str(path), 'role': role, 'reader': type(reader).__name__})
            return original(reader, path, code, role)

        error: Any = None
        ACTIVE_CASE = phase
        try:
            with patch.object(m, '_recovery_read', read):
                value = m.build(f.repo, manifest, output, recovery_sources=index) if index is not None else m.build(f.repo, manifest, output)
            phase.update(status='returned', returned=value)
        except m.ExecutorError as caught:
            error = caught
            phase.update(status='rejected', code=caught.error_code, reason=caught.reason, input_ref=caught.input_ref)
        finally:
            ACTIVE_CASE = None
        return phase, error

    def witness(self, m: Any, f: Any, index: Path, key: str, expected: tuple[str, str]) -> dict[str, Any]:
        reader = m._Inputs()
        caught: Any = None
        try:
            m._recovery_index_links(json.loads(index.read_bytes()), index, key, reader, set(),
                                    f.record, 'call_fixture_rejection')
        except m.ExecutorError as error:
            caught = error
        self.assertIsNotNone(caught, 'SETUP: the real typed consumer must reject this exact carrier')
        self.assertEqual((caught.error_code, caught.reason), expected, 'SETUP: wrong typed-consumer refusal')
        return {'index': support.file_ref(index), 'code': caught.error_code, 'reason': caught.reason,
                'input_ref': caught.input_ref, 'read_origins': sorted(reader.raw)}

    def assert_refusal(self, f: Any, m: Any, phase: dict[str, Any], error: Any, output: Path,
                       row: dict[str, Any], expected: tuple[str, str] | None = None,
                       relevant: set[str] | None = None) -> None:
        # Separate subtests retain every business violation, even when no error
        # was raised. An unrelated setup/schema/capacity error is never success.
        with self.subTest(contract='business_refusal'):
            self.assertIsNotNone(error, 'EXPECTED_BUSINESS_REFUSAL: ordinary build returned and must have refused')
            self.assertIsInstance(error, m.ExecutorError)
            if expected is not None:
                self.assertEqual((error.error_code, error.reason), expected)
            else:
                # No invented future reason enum: pin the existing handoff error
                # domain, exact live input, and actual post-capture recheck stage.
                self.assertEqual(error.error_code, 'E_RECOVERY_EVIDENCE')
                self.assertTrue(error.reason.startswith('recovery_handoff_'), error.reason)
                self.assertIn(error.input_ref, relevant or set())
                self.assertTrue(row.get('rejected_in_post_capture_recheck'), 'not the final live recheck')
            self.assertEqual(phase['status'], 'rejected')
        with self.subTest(contract='zero_successor_reserve'):
            self.assertEqual(_events(f), row['prefix_before'], 'UNEXPECTED_SUCCESSOR_RESERVE: seq3 must not exist')
        with self.subTest(contract='zero_successor_preparation'):
            present = [p.name for p in output.rglob('*') if p.is_file()] if output.exists() else []
            self.assertEqual(present, [], 'UNEXPECTED_SUCCESSOR_PREPARATION: failed live validation must leave no new preparation')

    def test_missing_indexes_allow_first_successor(self) -> None:
        """Good: missing indexes permit seq3. Bad blanket fail-closed must turn RED."""
        with self.scenario() as (f, m, manifest, output, index, row):
            phase, error = self.build(m, f, manifest, output, index, row)
            self.assertIsNone(error)
            self.assertFalse(phase['returned']['resume_only'])
            self.assertEqual([(e['event']['seq'], e['event']['kind']) for e in _events(f)],
                             [(1, 'reserve'), (2, 'dispatch_rejected'), (3, 'reserve')])

    def test_unbound_unrelated_index_is_not_a_global_scan_target(self) -> None:
        """Good: unbound foreign carrier is irrelevant. Bad global scan turns RED."""
        with self.scenario() as (f, m, manifest, output, index, row):
            bound, native = transaction.contradictory_audit_native(f, related=False)
            value = json.loads(bound.read_bytes())
            value['identity'] = {**value['identity'], 'audit_cycle_id': 'other-cycle', 'change_id': 'other-change'}
            foreign = f.repo / 'unbound-foreign-audit-index.json'
            support.write_json(foreign, value)
            bound.unlink()
            reader = m._Inputs()
            self.assertFalse(m._recovery_associated(json.loads(native.read_bytes()), f.record, reader, 'call_fixture_rejection'))
            m._recovery_native_links(value, foreign, reader, set(), f.record, selected_id='call_fixture_rejection')
            row['unrelated_witness'] = {'index': support.file_ref(foreign), 'export': support.file_ref(native),
                                        'generic_consumer_accepted': True, 'bound_locator_absent': not bound.exists()}
            phase, error = self.build(m, f, manifest, output, index, row)
            self.assertIsNone(error)
            self.assertFalse(phase['returned']['resume_only'])
            self.assertEqual(len(f.event_paths()), 3)

    def test_frozen_pending_resume_ignores_live_index_addition_and_deletion(self) -> None:
        """Good: fixed pending proof ignores live presence changes. Live recheck is RED."""
        with self.scenario() as (f, m, manifest, output, index, row):
            phase, error = self.build(m, f, manifest, output, index, row)
            self.assertIsNone(error)
            self.assertFalse(phase['returned']['resume_only'])
            prefix = _events(f)
            late, native = transaction.contradictory_audit_native(f, related=True)
            for present in (True, False):
                with self.subTest(live_index_present=present):
                    if not present:
                        late.unlink()
                    self.assertEqual(late.exists(), present)
                    # Exact resume must not even attempt to open either live
                    # locator, not merely ignore a swallowed read exception.
                    original = Path.open
                    def no_live_open(path: Path, *args: Any, **kwargs: Any) -> Any:
                        if path in (late, native):
                            self.fail('FROZEN_RESUME_READ_LIVE_INDEX_OR_EXPORT: ' + str(path))
                        return original(path, *args, **kwargs)
                    with patch.object(Path, 'open', no_live_open):
                        resumed, failure = self.build(m, f, manifest, output, None, row)
                    self.assertIsNone(failure)
                    self.assertTrue(resumed['returned']['resume_only'])
                    self.assertEqual(_events(f), prefix)

    def test_late_bound_audit_before_capture_rejects_related_run(self) -> None:
        """Good: exact handoff counterevidence, no successor. Omitted probe is RED."""
        with self.scenario() as (f, m, manifest, output, index, row):
            late, native = transaction.contradictory_audit_native(f, related=True)
            self.assertTrue(m._recovery_associated(json.loads(native.read_bytes()), f.record, m._Inputs(), 'call_fixture_rejection'))
            row['typed_witness'] = self.witness(m, f, late, 'post_audit_index_path',
                ('E_RECOVERY_EVIDENCE', 'counterevidence_target_native_record'))
            row['export'] = support.file_ref(native)
            phase, error = self.build(m, f, manifest, output, index, row)
            self.assert_refusal(f, m, phase, error, output, row,
                                expected=('E_RECOVERY_EVIDENCE', 'recovery_handoff_counterevidence'))

    def test_late_bound_audit_after_capture_requires_final_recheck(self) -> None:
        """Good: final live recheck rejects/cleans preparation. Stale-only recheck is RED."""
        global ACTIVE_CASE
        with self.scenario() as (f, m, manifest, output, index, row):
            capture, recheck = m._capture_recovery_handoff, m._handoff_recheck
            relevant: set[str] = set()
            row['capture_returned'] = False
            row['post_capture_rechecks'] = []

            def capture_then_add(*args: Any, **kwargs: Any) -> Any:
                global ACTIVE_CASE
                captured = capture(*args, **kwargs)
                self.assertEqual(_events(f), row['prefix_before'])
                self.assertFalse(any((output / name).exists() for name in PREPARATION))
                previous = ACTIVE_CASE
                ACTIVE_CASE = None  # Exclude only injector setup/diagnostic opens.
                try:
                    late, native = transaction.contradictory_audit_native(f, related=True)
                    row['typed_witness'] = self.witness(m, f, late, 'post_audit_index_path',
                        ('E_RECOVERY_EVIDENCE', 'counterevidence_target_native_record'))
                    row['export'] = support.file_ref(native)
                    relevant.update((str(late), str(native)))
                finally:
                    ACTIVE_CASE = previous
                row['capture_returned'] = True
                return captured

            def final_recheck(*args: Any, **kwargs: Any) -> Any:
                entry = {'after_capture': row['capture_returned'], 'event_count': len(f.event_paths())}
                row['post_capture_rechecks'].append(entry)
                try:
                    return recheck(*args, **kwargs)
                except m.ExecutorError as failure:
                    entry.update(code=failure.error_code, reason=failure.reason, input_ref=failure.input_ref)
                    if row['capture_returned']:
                        row['rejected_in_post_capture_recheck'] = True
                        self.assertEqual(entry['event_count'], 2)
                    raise

            with patch.object(m, '_capture_recovery_handoff', capture_then_add), patch.object(m, '_handoff_recheck', final_recheck):
                phase, error = self.build(m, f, manifest, output, index, row)
            self.assertTrue(row['capture_returned'], 'SETUP: late index injection was not reached')
            self.assertTrue(any(e['after_capture'] for e in row['post_capture_rechecks']), 'SETUP: final live recheck was not reached')
            self.assert_refusal(f, m, phase, error, output, row, relevant=relevant)

    def test_late_audit_missing_native_leaf_requires_typed_acquisition(self) -> None:
        """Typed acquisition only: a real FileRef to missing native must fail, not skip."""
        with self.scenario() as (f, m, manifest, output, index, row):
            late, missing = transaction.add_audit_index_with_missing_native(f)
            self.assertFalse(missing.exists())
            row['typed_witness'] = self.witness(m, f, late, 'post_audit_index_path',
                                               ('E_NATIVE_EVIDENCE', 'source_unreadable'))
            phase, error = self.build(m, f, manifest, output, index, row)
            self.assert_refusal(f, m, phase, error, output, row,
                                expected=('E_NATIVE_EVIDENCE', 'source_unreadable'))

    def test_late_drift_index_requires_its_typed_schema(self) -> None:
        """Typed schema only: incomplete drift index is not related-run evidence."""
        self.check_late_schema('post_drift_index_path', 'drift_index_keys')

    def test_late_disposition_index_requires_its_typed_schema(self) -> None:
        """Typed schema only: incomplete disposition is not a signed disposition."""
        self.check_late_schema('post_disposition_index_path', 'disposition_index_keys')

    def check_late_schema(self, key: str, reason: str) -> None:
        with self.scenario() as (f, m, manifest, output, index, row):
            late = Path(f.manifest['evidence'][key])
            support.write_json(late, {'schema_version': 1})
            row['typed_acquisition_only'] = True
            row['typed_witness'] = self.witness(m, f, late, key, ('E_NATIVE_EVIDENCE', reason))
            phase, error = self.build(m, f, manifest, output, index, row)
            self.assert_refusal(f, m, phase, error, output, row, expected=('E_NATIVE_EVIDENCE', reason))


if __name__ == '__main__':
    unittest.main()
