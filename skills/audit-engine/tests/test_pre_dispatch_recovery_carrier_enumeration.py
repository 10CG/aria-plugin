"""R4-CODE-001: independent suffix-agnostic structured carrier contracts.

SOT: design 3.4/6.1 and executor-contract 13.6. Run a fresh -I -B child
with the reviewed pre-import guard installed BEFORE importing this module.
Only RecoveryFixture synthetic trees are touched; never execute Workflow.

The break caught here is omitting a complete JSON object/list solely because
its frozen origin lacks a lower-case .json suffix. Opaque bytes and JSON
strings are not links. Malformed untyped JSON recognition is deliberately not
newly defined here; the existing json.loads exception-skip semantics are not
changed, and this test file creates no additional policy or owner gate.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

_spec = importlib.util.spec_from_file_location(
    'carrier_enumeration_support', Path(__file__).with_name('pre_dispatch_recovery_fixtures.py'))
assert _spec is not None and _spec.loader is not None
support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(support)

TARGET = 'call_fixture_rejection'
RECOVERY = 'E_RECOVERY_EVIDENCE'
NATIVE = 'E_NATIVE_EVIDENCE'
EVIDENCE_SINK = None  # Optional runner callback; metadata only.
SUFFIXES = (('json', '.json'), ('none', ''), ('payload', '.payload'), ('upper', '.JSON'))
CONSUMERS = (('object', '.json'), ('object', '.payload'), ('list', ''))


class PrerequisiteBlocked(RuntimeError):
    """NOT_JUDGED, never a feature RED or a successful business assertion."""


def native_value(related=False, status='success'):
    return {'runId': 'synthetic-known-run',
            'status': 'completed' if status == 'success' else 'running',
            'script': 'unrelated synthetic program',
            'args': {'identity': {'audit_cycle_id':
                     'cycle-protocol-fixture' if related else 'unrelated-cycle'}},
            'workflowProgress': [], 'result': {} if status == 'success' else None}


class CarrierFixture(support.RecoveryFixture):
    """Old host normally freezes context bytes; no frozen old object is edited."""
    def __init__(self, shape='object', suffix='.json', defect='healthy',
                 *, linked_root=False, nested_export=False, export_suffix='.payload',
                 index_suffix='.json'):
        self.shape, self.suffix, self.defect = shape, suffix, defect
        self.linked_root_enabled, self.nested_export = linked_root, nested_export
        self.export_suffix, self.index_suffix = export_suffix, index_suffix
        super().__init__()

    def _old_build(self, padding):
        if not hasattr(self, 'archive'):
            self.archive = self.repo / ('structured-archive' + self.suffix)
            self.export = self.repo / ('workflow-export' + self.export_suffix)
            self.leaf = self.repo / 'workflow-leaf.bin'
            native = native_value(self.defect in ('success', 'unknown'), self.defect)
            if self.linked_root_enabled:
                self.linked_root = self.config_root / 'projects' / 'carrier-enumeration' / (
                    '66666666-7777-4888-8999-000000000000.jsonl')
                self.linked_root.parent.mkdir(parents=True)
                self.linked_root.write_bytes(support.encode({
                    'type': 'progress', 'sessionId': self.linked_root.stem,
                    'data': {'toolUseID': 'unrelated-call'}}) + b'\n')
                native['native_source'] = str(self.linked_root)
            if self.nested_export:
                support.write_json(self.leaf, native_value())
                native['result'] = {'archived': {'native_record': str(self.leaf)}}
            support.write_json(self.export, native)
            link = str(self.export)
            if self.defect == 'bad_ref':
                link = {'path': str(self.export)}
            elif self.defect == 'bad_hash':
                link = dict(support.file_ref(self.export), sha256='0' * 64)
            carrier = {'archived_attempt': {'native_record': link}}
            value = [carrier] if self.shape == 'list' else carrier
            raw = support.encode(value)
            if self.defect == 'prose':
                raw = b'Synthetic note, not a JSON document: ' + raw
            elif self.defect == 'fenced':
                raw = b'```json\n' + raw + b'\n```\n'
            elif self.defect == 'json_string':
                raw = support.encode(raw.decode('ascii'))
            elif self.defect == 'script':
                raw = b'# Synthetic script bytes, never executed\nARCHIVE = ' + repr(raw).encode() + b'\n'
            elif self.defect == 'document':
                raw = b'# Synthetic documentation\n\nAn example only.\n' + raw + b'\n'
            self.archive.write_bytes(raw)
            if self.defect == 'missing':
                self.export.unlink()
            policy_path = self.repo / 'policy.json'
            policy = json.loads(policy_path.read_bytes())
            policy['context'] = support.file_ref(self.archive)
            support.write_json(policy_path, policy)
            self.manifest['evidence']['policy_inputs'] = support.file_ref(policy_path)
            # Typed role comes from the manifest field, not the filename.
            self.manifest['evidence']['post_audit_index_path'] = str(
                self.run_dir / ('audit-index' + self.index_suffix))
        return super()._old_build(padding)


def read_closure(reference):
    """Independent byte/hash decoder, not the production proof consumer."""
    path = Path(reference['path'])
    if support.file_ref(path) != reference:
        raise PrerequisiteBlocked('SETUP: closure reference hash mismatch')
    value = json.loads(path.read_bytes())
    result = {}
    for entry in value['sources']:
        blob = Path(entry['blob']['path'])
        raw = blob.read_bytes()
        if support.file_ref(blob) != entry['blob'] or support.digest(raw) != entry['sha256']:
            raise PrerequisiteBlocked('SETUP: closure entry hash mismatch')
        if entry['origin'] in result:
            raise PrerequisiteBlocked('SETUP: duplicate closure origin')
        result[entry['origin']] = raw
    return result


def independent_repack(f, event_ref, defect):
    """Re-address only synthetic seq2/new capture, preserving ALL old bytes.

    Start with a genuinely healthy producer output. Independently replace the
    captured export with associated success/unknown bytes, or remove its mapping.
    Both new-source and enclosing closures and known hashes are reconstructed.
    This remains constructible when the producer is fixed: no buggy producer,
    changed six-source generation, broken hash, or altered old context is needed.
    """
    event_path = Path(event_ref['path'])
    event = json.loads(event_path.read_bytes())
    outer = read_closure(event['payload']['input_closure'])
    transition = event['payload']['source_transition']
    current = read_closure(transition['new_source_closure'])
    evidence = json.loads(outer[event['payload']['evidence']['path']])
    origin = str(f.export)
    if defect == 'missing':
        current.pop(origin, None)
        outer.pop(origin, None)
    else:
        current[origin] = support.encode(native_value(True, defect))
        outer[origin] = current[origin]
    evidence['known_binding_sources'] = sorted(
        [ref for ref in evidence['known_binding_sources'] if ref['path'] != origin]
        + ([{'path': origin, 'sha256': support.digest(current[origin])}]
           if origin in current else []), key=lambda ref: ref['path'])

    def freeze(raw):
        path = f.scope / 'blobs' / (support.digest(raw) + '.blob')
        if path.exists() and path.read_bytes() != raw:
            raise PrerequisiteBlocked('SETUP: synthetic content-address collision')
        path.write_bytes(raw)
        return support.file_ref(path)

    def closure(rawmap):
        return freeze(support.encode({'schema_version': 1, 'algorithm_version': 'canonical_v1',
            'sources': [{'origin': key, 'sha256': support.digest(raw), 'blob': freeze(raw)}
                        for key, raw in sorted(rawmap.items())]}))

    transition['new_source_closure'] = closure(current)
    ref = transition['new_source_closure']
    outer[ref['path']] = Path(ref['path']).read_bytes()
    event['payload']['evidence'] = freeze(support.encode(evidence))
    ref = event['payload']['evidence']
    outer[ref['path']] = Path(ref['path']).read_bytes()
    event['payload']['input_closure'] = closure(outer)
    # This seq2 was just created by this test, and is NOT a legacy pinned file.
    new_ref = support.write_json(event_path, event)
    # Prove the independent packaging, without asking the buggy consumer to bless it.
    packed = read_closure(event['payload']['input_closure'])
    view = read_closure(transition['new_source_closure'])
    if any(packed[key] != raw for key, raw in view.items()):
        raise PrerequisiteBlocked('SETUP: independent cross-capture binding mismatch')
    if f.archive.read_bytes() != read_closure(f.old_closure)[str(f.archive)]:
        raise PrerequisiteBlocked('SETUP: old context changed')
    return new_ref


class CarrierEnumerationTests(unittest.TestCase):
    @contextmanager
    def scenario(self, **kwargs):
        self.row = {'case': self._testMethodName, 'parameters': kwargs, 'steps': [],
                    'assertions_judged': [], 'not_judged': [], 'stage': 'fixture_setup'}
        self.last_case = self.row
        f = None
        try:
            f = CarrierFixture(**kwargs)
            self.f = f
            old = read_closure(f.old_closure)
            if old.get(str(f.archive)) != f.archive.read_bytes() or f.script_path.stat().st_size != 570716:
                raise PrerequisiteBlocked('SETUP: old host did not freeze exact intended input')
            self.row['old_context_normally_frozen'] = True
            self.row['old_script_bytes'] = f.script_path.stat().st_size
            self.row['old_context_sha256'] = support.digest(f.archive.read_bytes())
            self.row['candidate_sha256'] = support.digest(f.executor.read_bytes())
            with patch.dict(os.environ, f.environment, clear=True):
                self.mod = support.load_module(f.executor)
                with patch.object(self.mod, '_RUNTIME_REJECTION_PROFILES', f.runtime_profiles):
                    self.row['stage'] = 'business'
                    yield f
        finally:
            if f is not None:
                try:
                    f.assert_old_unchanged(self)
                    self.assertEqual(support.digest(f.executor.read_bytes()), self.row['candidate_sha256'],
                                     'SETUP: disposable executor changed')
                    self.row['old_pinned_files_unchanged'] = True
                finally:
                    f.close()
            if EVIDENCE_SINK is not None:
                EVIDENCE_SINK(self.row)

    def invoke(self, label, function):
        step = {'label': label, 'calls': {}, 'export_read': False, 'leaf_read': False}
        self.row['steps'].append(step)
        def observe(frame, event, arg):
            if frame.f_code.co_filename != str(self.f.executor):
                return
            name = frame.f_code.co_name
            if event == 'call':
                step['calls'][name] = step['calls'].get(name, 0) + 1
            if event == 'return' and name == 'read' and isinstance(arg, bytes):
                path = frame.f_locals.get('path')
                if path == self.f.export:
                    step['export_read'] = True
                if path == self.f.leaf:
                    step['leaf_read'] = True
        previous = sys.getprofile()
        try:
            sys.setprofile(observe)
            value = function()
            step['returned'] = True
            if isinstance(value, dict):
                step['result_metadata'] = {key: value[key] for key in
                    ('eligible', 'would_append', 'resume_only') if key in value}
            return value, None
        except self.mod.ExecutorError as error:
            step['error'] = {'code': error.error_code, 'reason': error.reason}
            return None, (error.error_code, error.reason)
        finally:
            sys.setprofile(previous)

    def recover(self, *, check_only=False, target=TARGET):
        f = self.f
        return self.mod.recover_dispatch_rejection(f.repo, f.manifest_path, f.build_record_path,
            f.native_path, target, f.operator_index, f.acceptance_index, check_only=check_only)

    def prepare_recovery(self):
        value, error = self.invoke('healthy_seq2_producer', lambda: self.recover())
        if error is not None or value is None or value.get('event') is None:
            raise PrerequisiteBlocked('NOT_JUDGED: healthy seq2 producer blocked: ' + str(error))
        self.row['healthy_seq2_setup'] = True
        return value['event']

    def expect_error(self, label, function, expected, *, gap_errors=(), unchanged_events=True):
        before = [p.read_bytes() for p in self.f.event_paths()]
        value, actual = self.invoke(label, function)
        after = [p.read_bytes() for p in self.f.event_paths()]
        self.row['steps'][-1]['event_reserve_observation'] = {
            'before_count': len(before), 'after_count': len(after), 'bytes_unchanged': before == after}
        # Unrelated setup failures must not masquerade as the specified RED.
        if actual is not None and actual != expected and actual not in gap_errors:
            raise PrerequisiteBlocked('NOT_JUDGED: unexpected preceding business blocker ' + str(actual))
        self.assertEqual(actual, expected, 'R4-CODE-001: ' + label + ' must reject for the specified business reason')
        self.row['assertions_judged'].append(label + '/reason')
        if unchanged_events:
            self.assertEqual([p.read_bytes() for p in self.f.event_paths()], before,
                             'R4-CODE-001: refusal must publish zero new event/reserve')
            self.row['assertions_judged'].append(label + '/zero_new_event_reserve')
        self.assertIsNone(value)

    def first_submission(self, shape, suffix, defect, mutation):
        with self.scenario(shape=shape, suffix=suffix, defect=defect) as f:
            before = support.tree_snapshot(f.root)
            call = lambda: self.recover(check_only=not mutation)
            if defect != 'healthy':
                expected = (NATIVE, 'source_unreadable') if defect == 'missing' else (
                    RECOVERY, 'counterevidence_native_record')
                self.row['not_judged'] = ['refusal/reason', 'refusal/zero_new_event_reserve']
                self.expect_error('first_submission', call, expected)
                self.row['not_judged'] = []
                if not mutation:
                    self.assertEqual(support.tree_snapshot(f.root), before)
                return
            value, error = self.invoke('first_submission', call)
            if error is not None or value is None:
                raise PrerequisiteBlocked('NOT_JUDGED: healthy complete JSON rejected ' + str(error))
            self.assertIs(value['eligible'], True)
            self.assertEqual(len(f.event_paths()), 2 if mutation else 1)
            self.row['assertions_judged'].append('healthy/accepted')
            if not mutation:
                self.assertEqual(support.tree_snapshot(f.root), before)
            self.row['not_judged'] = ['healthy/export_consumed']
            self.assertTrue(self.row['steps'][-1]['export_read'],
                            'R4-CODE-001: healthy complete JSON must actually consume export')
            self.row['assertions_judged'].append('healthy/export_consumed')
            self.row['not_judged'] = []

    def frozen_bad(self, shape, suffix, defect):
        with self.scenario(shape=shape, suffix=suffix) as f:
            event = independent_repack(f, self.prepare_recovery(), defect)
            self.row['consumer_bad_state_independently_repacked'] = True
            self.row['old_context_and_six_sources_rewritten'] = False
            manifest, run, index = f.successor(event)
            expected = (NATIVE, 'incomplete_pending_closure') if defect == 'missing' else (
                RECOVERY, 'counterevidence_native_record')
            # Public build MUST reject during immutable seq2 replay. No live
            # handoff is supplied, so it cannot hide a missed frozen proof.
            gaps = ((RECOVERY, 'recovery_sources_required'),
                    ('E_POLICY_SOURCE', 'history_recovery_known_sources_membership'),
                    ('E_POLICY_SOURCE', 'history_recovery_unconsumed_verification_input'))
            self.row['not_judged'] = ['frozen/reason', 'frozen/zero_new_event_reserve',
                                      'frozen/rejected_before_live_handoff']
            self.expect_error('frozen_seq2_replay', lambda: self.mod.build(f.repo, manifest, run),
                              expected, gap_errors=gaps)
            self.assertTrue(self.row['steps'][-1]['calls'].get('_verify_recovery_event', 0))
            self.assertFalse(self.row['steps'][-1]['calls'].get('_capture_recovery_handoff', 0))
            self.assertFalse(run.exists())
            self.row['not_judged'] = []

    def healthy_chain(self, shape, suffix):
        with self.scenario(shape=shape, suffix=suffix, linked_root=True) as f:
            event = self.prepare_recovery()
            manifest, run, index = f.successor(event)
            value, error = self.invoke('first_ordinary_successor',
                lambda: self.mod.build(f.repo, manifest, run, recovery_sources=index))
            if error is not None or value is None:
                raise PrerequisiteBlocked('NOT_JUDGED: healthy first successor blocked ' + str(error))
            self.assertIs(value['resume_only'], False)
            self.assertEqual(len(f.event_paths()), 3)
            self.row['assertions_judged'].append('healthy/seq3_published')
            # Exercise pending immutable consumer with all live sources removed.
            f.native_path.unlink()
            f.export.unlink()
            f.linked_root.unlink()
            index.unlink()
            value, error = self.invoke('frozen_pending_resume', lambda: self.mod.build(f.repo, manifest, run))
            if error is not None or value is None:
                raise PrerequisiteBlocked('NOT_JUDGED: frozen pending resume blocked ' + str(error))
            self.assertIs(value['resume_only'], True)
            self.assertEqual(len(f.event_paths()), 3)
            self.row['assertions_judged'].append('healthy/frozen_resume_without_live_sources')
            self.row['not_judged'] = ['healthy/handoff_export_consumed', 'healthy/frozen_export_consumed']
            for step in self.row['steps'][1:]:
                self.assertTrue(step['export_read'],
                    'R4-CODE-001: healthy handoff/frozen consumer must read structured export')
                self.row['assertions_judged'].append(self.row['not_judged'].pop(0))

    def handoff_bad(self, shape, suffix, defect):
        with self.scenario(shape=shape, suffix=suffix, linked_root=True) as f:
            event = self.prepare_recovery()
            manifest, run, index = f.successor(event)
            if defect == 'missing':
                f.linked_root.unlink()
                expected = (RECOVERY, 'source_unreadable')
            else:
                request, response = f._pair('Workflow', {'scriptPath': str(f.script_path),
                    'args': {'identity': {'audit_cycle_id': f.manifest['audit_cycle_id']}}},
                    800, 'call_carrier_handoff', session=f.linked_root.stem)
                added = [request, response] if defect == 'success' else [request]
                with f.linked_root.open('ab') as stream:
                    stream.write(b''.join(support.encode(row) + b'\n' for row in added))
                expected = (RECOVERY, 'recovery_handoff_counterevidence')
            self.row['not_judged'] = ['handoff/reason', 'handoff/zero_new_event_reserve',
                                      'handoff/no_preparation_published']
            self.expect_error('first_ordinary_successor',
                lambda: self.mod.build(f.repo, manifest, run, recovery_sources=index), expected)
            self.assertFalse((run / 'workflow.js').exists())
            self.assertFalse((run / 'recovery-preflight.json').exists())
            self.row['not_judged'] = []

    def committed_rescan(self, shape, export_suffix, defect):
        # A .json old carrier makes the producer capture this non-.json export
        # even on the buggy host. The committed scanner must enumerate its
        # actual known-source bytes, not just known *.json files.
        with self.scenario(shape=shape, suffix='.json', nested_export=True,
                           export_suffix=export_suffix) as f:
            event = self.prepare_recovery()
            if defect == 'healthy':
                value, error = self.invoke('committed_healthy_reentry', lambda: self.recover(check_only=True))
                if error is not None:
                    raise PrerequisiteBlocked('NOT_JUDGED: healthy committed reentry blocked ' + str(error))
                self.assertEqual(value, {'eligible': True, 'would_append': False, 'event': None})
                self.assertEqual(len(f.event_paths()), 2)
                self.assertTrue(self.row['steps'][-1]['calls'].get('_recovery_rescan_committed', 0))
                self.row['assertions_judged'].append('committed/healthy_idempotent')
                return
            if defect == 'missing':
                f.leaf.unlink()
                expected = (RECOVERY, 'input_changed_source_unreadable')
            else:
                support.write_json(f.leaf, native_value(True, defect))
                expected = (RECOVERY, 'counterevidence_native_record')
            # SOT 13.7: rescan precedes argument/key checks. A wrong new tool id
            # cannot hide counterevidence associated with the OLD proved id.
            self.row['not_judged'] = ['committed/reason', 'committed/zero_new_event_reserve']
            self.expect_error('committed_live_rescan',
                lambda: self.recover(check_only=True, target='different-current-argument'), expected,
                gap_errors=((RECOVERY, 'input_changed_recovery_arguments'),))
            self.assertTrue(self.row['steps'][-1]['calls'].get('_recovery_rescan_committed', 0))
            self.row['not_judged'] = []

    def opaque(self, suffix, defect):
        with self.scenario(suffix=suffix, defect=defect) as f:
            # The complete export is associated; treating its prose example as
            # a link would reject this otherwise healthy opaque context.
            support.write_json(f.export, native_value(True))
            value, error = self.invoke('opaque_check_only', lambda: self.recover(check_only=True))
            if error is not None or value is None:
                raise PrerequisiteBlocked('NOT_JUDGED: opaque context rejected ' + str(error))
            self.assertIs(value['eligible'], True)
            event = self.prepare_recovery()
            value, error = self.invoke('opaque_committed_reentry', lambda: self.recover(check_only=True))
            self.assertIsNone(error, 'R4-CODE-001: opaque bytes must remain opaque at reentry')
            manifest, run, index = f.successor(event)
            value, error = self.invoke('opaque_successor',
                lambda: self.mod.build(f.repo, manifest, run, recovery_sources=index))
            self.assertIsNone(error, 'R4-CODE-001: opaque bytes must remain opaque at handoff')
            if value is None:
                raise PrerequisiteBlocked('NOT_JUDGED: opaque handoff returned no result')
            self.assertIs(value['resume_only'], False)
            self.assertFalse(any(step['export_read'] for step in self.row['steps']),
                             'R4-CODE-001: prose/fence/JSON string must not become a link')
            self.row['assertions_judged'].append('opaque/no_link_across_four_entrances')

    def explicit_ref(self, shape, suffix, defect):
        with self.scenario(shape=shape, suffix=suffix, defect=defect):
            expected = (NATIVE, 'file_ref' if defect == 'bad_ref' else 'source_hash_mismatch')
            self.row['not_judged'] = ['explicit_ref/reason', 'explicit_ref/zero_new_event_reserve']
            self.expect_error('explicit_generic_ref', lambda: self.recover(), expected)
            self.row['not_judged'] = []

    def typed_role(self, suffix, defect, committed):
        with self.scenario(index_suffix=suffix) as f:
            if committed:
                self.prepare_recovery()
            ref = str(f.export) if defect == 'string' else dict(support.file_ref(f.export), sha256='0' * 64)
            path = Path(f.manifest['evidence']['post_audit_index_path'])
            support.write_json(path, {'schema_version': 1, 'identity': f.record['identity'],
                'attempt_index': 1, 'workflow_run_id': 'synthetic-known-run',
                'native_record': ref, 'termination_refs': []})
            expected = ((RECOVERY, 'input_changed_file_ref') if committed else (NATIVE, 'file_ref')) if defect == 'string' else (
                RECOVERY if committed else NATIVE,
                'input_changed_source_hash_mismatch' if committed else 'source_hash_mismatch')
            self.row['not_judged'] = ['typed_role/reason', 'typed_role/zero_new_event_reserve']
            self.expect_error('typed_role_not_filename', lambda: self.recover(check_only=True), expected)
            self.row['not_judged'] = []


def install_cases():
    """One unittest method = one independent fixture case; no subtest inflation."""
    def add(name, method, *args):
        def case(self):
            return getattr(self, method)(*args)
        case.__name__ = 'test_' + name
        case.__doc__ = 'R4-CODE-001 independent case: ' + name
        setattr(CarrierEnumerationTests, case.__name__, case)
    for shape in ('object', 'list'):
        for tag, suffix in SUFFIXES:
            for defect in ('healthy', 'success', 'unknown', 'missing'):
                for mutation in (False, True):
                    lane = 'mutation' if mutation else 'check'
                    add(f'{lane}_{shape}_{tag}_{defect}', 'first_submission', shape, suffix, defect, mutation)
    for shape, suffix in CONSUMERS:
        tag = suffix.lstrip('.') or 'none'
        add(f'chain_{shape}_{tag}_healthy', 'healthy_chain', shape, suffix)
        for defect in ('success', 'unknown', 'missing'):
            add(f'frozen_{shape}_{tag}_{defect}', 'frozen_bad', shape, suffix, defect)
            add(f'handoff_{shape}_{tag}_{defect}', 'handoff_bad', shape, suffix, defect)
    for shape, export_suffix in CONSUMERS:
        tag = export_suffix.lstrip('.') or 'none'
        for defect in ('healthy', 'success', 'unknown', 'missing'):
            add(f'rescan_{shape}_{tag}_{defect}', 'committed_rescan', shape, export_suffix, defect)
    for suffix, defect in (('.json', 'prose'), ('.md', 'fenced'), ('.payload', 'json_string'),
                           ('.py', 'script'), ('.md', 'document'), ('', 'json_string')):
        add(f'opaque_{suffix.lstrip(chr(46)) or "none"}_{defect}', 'opaque', suffix, defect)
    for shape in ('object', 'list'):
        for tag, suffix in (('json', '.json'), ('payload', '.payload')):
            for defect in ('bad_ref', 'bad_hash'):
                add(f'explicit_{shape}_{tag}_{defect}', 'explicit_ref', shape, suffix, defect)
    for suffix in ('.json', '.payload'):
        for defect in ('string', 'bad_hash'):
            for committed in (False, True):
                lane = 'rescan' if committed else 'first'
                add(f'typed_{suffix[1:]}_{defect}_{lane}', 'typed_role', suffix, defect, committed)


install_cases()

if __name__ == '__main__':
    unittest.main()
