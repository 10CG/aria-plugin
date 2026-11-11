"""Independent permanent contracts for generic legacy Workflow export locators.

Run in a fresh -I -B child with the reviewed pre-import isolation guard installed
BEFORE loading this module. Only synthetic RecoveryFixture trees are exercised.
No production native source, Workflow invocation, or historical note is read.
The optional EVIDENCE_SINK receives metadata, never native payloads.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

_spec = importlib.util.spec_from_file_location(
    'legacy_locator_fixture_support', Path(__file__).with_name('pre_dispatch_recovery_fixtures.py'))
assert _spec is not None and _spec.loader is not None
support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(support)

EVIDENCE_SINK = None
CASE_FILTER = frozenset()  # Runner-only selection; never affects production semantics.
TARGET = 'call_fixture_rejection'
MISSING = object()
NATIVE = 'E_NATIVE_EVIDENCE'
RECOVERY = 'E_RECOVERY_EVIDENCE'


class PrerequisiteBlocked(AssertionError):
    """A downstream assertion was NOT judged; do not count this as its RED."""


def foreign_native(run='independent-foreign-run'):
    return {'runId': run, 'status': 'completed', 'script': 'independent unrelated synthetic script',
            'args': {'identity': {'audit_cycle_id': 'independent-foreign-cycle'},
                     'manifest_sha256': 'f' * 64}, 'workflowProgress': [], 'result': {},
            'startTime': 1000, 'durationMs': 1, 'agentCount': 0}


class ArchiveFixture(support.RecoveryFixture):
    """Construct all archive inputs BEFORE the actual old host freezes them."""
    def __init__(self, flavor='string', defect='healthy'):
        self.flavor, self.defect = flavor, defect
        super().__init__()

    def link(self, path, carrier=None):
        if self.flavor == 'string':
            return str(path)
        ref = support.file_ref(path)
        if self.flavor == 'relative_ref':
            ref['path'] = os.path.relpath(path, (carrier or self.archive).parent)
        return ref

    def _old_build(self, padding):
        if not hasattr(self, 'archive'):
            self.archive = self.repo / 'independently-authored-archive.json'
            self.export = self.repo / 'foreign-export.payload'  # No suffix-based trust.
            self.leaf = self.repo / 'foreign-leaf.payload'
            self.agent = self.repo / 'independent-agent.jsonl'
            roots = self.config_root / 'projects' / 'independent-legacy-locators'
            self.root_a = roots / '77777777-1111-4222-8333-444444444444.jsonl'
            self.root_b = roots / '88888888-1111-4222-8333-444444444444.jsonl'
            roots.mkdir(parents=True)
            support.write_json(self.leaf, foreign_native('independent-leaf-run'))
            self.root_b.write_bytes(support.encode({'type': 'progress', 'sessionId': self.root_b.stem,
                                                    'data': {'toolUseID': 'unrelated-call'}}) + b'\n')
            self.root_a.write_bytes(support.encode({'type': 'progress', 'sessionId': self.root_a.stem,
                                                    'data': {'original_locator': str(self.root_b)}}) + b'\n')
            native = foreign_native()
            native_ref = support.write_json(self.export, native)
            carrier = {'native_record': self.link(self.export)}
            defect = self.defect
            self.expected_reads = [self.export]
            self.extra_roots = []
            if defect in ('deep_health', 'second_target', 'root_target', 'dag', 'sibling_target'):
                native['result'] = {'first': {'native_record': self.link(self.leaf, self.export)}}
                self.expected_reads.append(self.leaf)
                if defect == 'dag':
                    native['result']['second'] = {'native_record': self.link(self.leaf, self.export)}
                if defect in ('deep_health', 'root_target'):
                    leaf = foreign_native('independent-leaf-run')
                    leaf['native_source'] = str(self.root_a)
                    support.write_json(self.leaf, leaf)
                    native['result']['first']['native_record'] = self.link(self.leaf, self.export)
                    self.expected_reads += [self.root_a, self.root_b]
                    self.extra_roots = [self.root_a, self.root_b]
                if defect == 'second_target':
                    leaf = foreign_native('independent-leaf-run')
                    leaf['wireToolInputs'] = {TARGET: {'status': 'unknown'}}
                    support.write_json(self.leaf, leaf)
                    native['result']['first']['native_record'] = self.link(self.leaf, self.export)
                if defect in ('root_target', 'sibling_target'):
                    self.root_b.write_bytes(support.encode({'type': 'progress', 'sessionId': self.root_b.stem,
                                                            'data': {'toolUseID': TARGET}}) + b'\n')
                if defect == 'sibling_target':
                    carrier['sibling'] = {'native_source': str(self.root_a)}
                    self.expected_reads += [self.root_a, self.root_b]
            if defect.startswith('target_'):
                dimension = defect.removeprefix('target_')
                if dimension == 'id':
                    native['toolUseID'] = TARGET
                elif dimension == 'wire':
                    native['wireToolInputs'] = {TARGET: {}}
                elif dimension == 'cycle':
                    native['result'] = {'audit_cycle_id': self.manifest['audit_cycle_id']}
                elif dimension == 'script_hash':
                    # A distinct source path is frozen before build. Its content
                    # is copied afterwards, avoiding a self-referential FileRef.
                    self.later_script_binding = self.repo / 'same-program-other-path.js'
                    native['scriptPath'] = str(self.later_script_binding)
            if defect == 'context_target':
                carrier['audit_cycle_id'] = self.manifest['audit_cycle_id']
            if defect in ('self_cycle', 'two_cycle'):
                native['result'] = {'native_record': str(self.export if defect == 'self_cycle' else self.leaf)}
                if defect == 'two_cycle':
                    support.write_json(self.leaf, dict(foreign_native('independent-leaf-run'),
                                                      result={'native_record': str(self.export)}))
            if defect.startswith('shape_'):
                key = defect.removeprefix('shape_')
                if key == 'run_missing':
                    native.pop('runId')
                elif key in ('run_empty', 'run_type'):
                    native['runId'] = '' if key == 'run_empty' else 7
                elif key == 'args':
                    native['args'] = []
                elif key == 'script':
                    native['script'] = None
            if defect == 'run_mismatch':
                carrier['workflow_run_id'] = 'a-different-expected-run'
            if defect.startswith('term_'):
                event = {'type': 'user', 'agentId': 'independent-agent', 'uuid': 'independent-event',
                         'message': {'role': 'user', 'content': '[Request interrupted by user]'}}
                self.agent.write_bytes(support.encode(event) + b'\n')
                native['workflowProgress'] = [{'type': 'workflow_agent', 'agentId': 'independent-agent'}]
                event_ref = {'file': support.file_ref(self.agent), 'line': 1,
                             'agent_id': 'independent-agent', 'event_uuid': 'independent-event'}
                term = defect.removeprefix('term_')
                if term == 'line':
                    event_ref['line'] = 2
                elif term == 'uuid':
                    event_ref['event_uuid'] = 'different-event'
                elif term == 'agent':
                    event_ref['agent_id'] = 'different-agent'
                elif term == 'hash':
                    event_ref['file']['sha256'] = '0' * 64
                carrier.update(workflow_run_id=native['runId'], termination_refs=[{
                    'native_pointer': '/workflowProgress/0', 'agent_id': 'independent-agent', 'event': event_ref}])
                self.expected_reads.append(self.agent)
            support.write_json(self.export, native)
            if defect in ('invalid_json', 'duplicate_json', 'nonfinite_json', 'bad_utf8', 'nonobject'):
                self.export.write_bytes({'invalid_json': b'{', 'duplicate_json': b'{"runId":"a","runId":"b"}',
                                         'nonfinite_json': b'{"x":NaN}', 'bad_utf8': b'\xff',
                                         'nonobject': b'[]'}[defect])
            carrier['native_record'] = self.link(self.export)
            values = {'null': None, 'absent': MISSING, 'boolean': False, 'integer': 3,
                      'float': 1.5, 'list': [], 'dict_empty': {},
                      'dict_missing': {'path': str(self.export)},
                      'dict_extra': dict(native_ref, unexpected=True),
                      'dict_bad_hash': dict(native_ref, sha256='NOT-A-HASH'),
                      'dict_wrong_hash': dict(native_ref, sha256='0' * 64),
                      'relative': 'foreign-export.payload', 'empty': '',
                      'uri': 'file://' + str(self.export), 'double_slash': '/' + str(self.export),
                      'repeat_slash': str(self.repo) + '//' + self.export.name,
                      'dot': str(self.repo) + '/./' + self.export.name,
                      'dotdot': str(self.repo) + '/unused/../' + self.export.name,
                      'trailing_slash': str(self.export) + '/',
                      'control': str(self.export) + '\n', 'delete_control': str(self.export) + '\x7f'}
            if defect in values:
                value = values[defect]
                if value is MISSING:
                    carrier.pop('native_record')
                else:
                    carrier['native_record'] = value
                if defect in ('null', 'absent'):
                    carrier['sibling'] = {'native_source': str(self.root_a)}
                    self.expected_reads = [self.root_a, self.root_b]
            if defect == 'missing':
                self.export.unlink()
            if defect in ('symlink_file', 'symlink_parent'):
                if defect == 'symlink_file':
                    alias = self.repo / 'export-alias'
                    alias.symlink_to(self.export)
                else:
                    parent = self.repo / 'export-parent-alias'
                    parent.symlink_to(self.repo, target_is_directory=True)
                    alias = parent / self.export.name
                carrier['native_record'] = str(alias)
            self.carrier = carrier
            # Deliberately unrelated carrier context, even when a linked native is related.
            support.write_json(self.archive, {'revision2_and_scope_attribution': {'fixed_scope': {
                'legacy_attempts': [{'consumed': {'summary': 'synthetic only'}}, {'consumed': carrier}]}}})
            policy_path = self.repo / 'policy.json'
            policy = json.loads(policy_path.read_bytes())
            policy['context'] = support.file_ref(self.archive)
            support.write_json(policy_path, policy)
            self.manifest['evidence']['policy_inputs'] = support.file_ref(policy_path)
        return super()._old_build(padding)


class LegacyLocatorTests(unittest.TestCase):
    """Each subtest is separately judged; a failed prerequisite never counts GREEN."""
    @contextmanager
    def scenario(self, name, flavor='string', defect='healthy', mutant=None):
        self.row = {'case': name, 'flavor': flavor, 'defect': defect, 'stage': 'fixture_setup',
                    'calls': [], 'subtest_event': True, 'mutant': mutant}
        self.last_case = self.row
        f = None
        try:
            f = ArchiveFixture(flavor, defect)
            self.f = f
            closure = json.loads(Path(f.old_closure['path']).read_bytes())
            entries = [x for x in closure['sources'] if x['origin'] == str(f.archive)]
            self.assertEqual(len(entries), 1, 'SETUP: archive not normally frozen')
            self.assertEqual(Path(entries[0]['blob']['path']).read_bytes(), f.archive.read_bytes())
            self.row['old_archive_frozen'] = True
            self.row['old_script_bytes'] = f.script_path.stat().st_size
            self.assertEqual(self.row['old_script_bytes'], 570716)
            self.assertNotIn('identity', f.carrier)
            self.assertNotIn('audit_cycle_id', f.carrier) if defect != 'context_target' else None
            if getattr(f, 'later_script_binding', False):
                f.later_script_binding.write_bytes(f.script_path.read_bytes())
                f.expected_reads.append(f.later_script_binding)
            if mutant:
                raw = f.executor.read_text()
                if mutant == 'skip_string':
                    old = "    if reference is not None:\n        path, raw = _recovery_native_reference(reference, carrier, inputs)"
                    new = "    if reference is not None and not isinstance(reference, str):\n        path, raw = _recovery_native_reference(reference, carrier, inputs)"
                elif mutant == 'skip_nested':
                    old = "        _recovery_native_links(native, path, inputs, roots, build_record, seen | {str(path)}, target_context,\n                               selected_id=selected_id)"
                    new = '        pass  # independent bad implementation drops nested native traversal'
                else:
                    raise AssertionError('SETUP: unknown independent mutant')
                self.assertEqual(raw.count(old), 1, 'SETUP: mutant anchor changed; review required')
                f.executor.write_text(raw.replace(old, new))
                # Mechanical to-hash regeneration ONLY in the disposable copy.
                catalog = json.loads(f.compat_path.read_bytes())
                catalog['to'] = {'executor': support.digest(f.executor.read_bytes()),
                                 'contract': support.digest(f.contract.read_bytes())}
                support.write_json(f.compat_path, catalog)
                f.current_sources.update(executor=support.file_ref(f.executor), contract=support.file_ref(f.contract))
                self.row['mutant_compat_to_rehashed'] = True
            with patch.dict(os.environ, f.environment, clear=True):
                self.mod = support.load_module(f.executor)
                self.mod._RUNTIME_REJECTION_PROFILES = f.runtime_profiles  # Existing DATA-only seam.
                self.row['stage'] = 'ready'
                yield f
        finally:
            if f is not None:
                self.row['event_count_at_end'] = len(f.event_paths())
                f.assert_old_unchanged(self)
                self.row['pinned_old_files_unchanged'] = True
                f.close()

    def recover(self, check=True):
        f = self.f
        return self.mod.recover_dispatch_rejection(f.repo, f.manifest_path, f.build_record_path,
            f.native_path, TARGET, f.operator_index, f.acceptance_index, check_only=check)

    def invoke(self, function, label='check_only', hook=None):
        f, mod = self.f, self.mod
        record = {'entry': label, 'reads': {}, 'native_contexts': [], 'calls': {}}
        self.row['calls'].append(record)
        old_profile = sys.getprofile()
        def observe(frame, event, arg):
            if hook is not None:
                hook(frame, event, arg)
            if frame.f_code.co_filename != str(f.executor):
                return
            name = frame.f_code.co_name
            if event == 'call':
                record['calls'][name] = record['calls'].get(name, 0) + 1
                if name == '_recovery_native_links' and frame.f_locals.get('carrier') == f.archive:
                    value = frame.f_locals.get('value')
                    if isinstance(value, dict) and 'native_record' in value:
                        record['native_contexts'].append(bool(frame.f_locals.get('target_context')))
            if event == 'return' and name == 'read' and isinstance(arg, bytes):
                path = frame.f_locals.get('path')
                if path is not None:
                    record['reads'][str(path)] = support.digest(arg)
        sys.setprofile(observe)
        try:
            value = function()
        except mod.ExecutorError as exc:
            record['actual'] = {'error_code': exc.error_code, 'reason': exc.reason}
            record['input_role'] = self.role(exc.input_ref)
            return None, (exc.error_code, exc.reason)
        else:
            record['actual'] = {'returned': True}
            if isinstance(value, dict):
                record['return_keys'] = sorted(value)
                for key in ('eligible', 'would_append', 'resume_only'):
                    if key in value:
                        record[key] = value[key]
            return value, None
        finally:
            sys.setprofile(old_profile)

    def role(self, path):
        try:
            return str(Path(path).relative_to(self.f.root))
        except (ValueError, TypeError):
            return 'outside-fixture'

    def expect(self, expected=None, *, hook=None, preserve=True):
        self.row['stage'] = 'business'
        self.row['expected'] = list(expected) if expected else 'eligible=true,would_append=true,event=null'
        before = support.tree_snapshot(self.f.root) if preserve else None
        value, actual = self.invoke(lambda: self.recover(True), hook=hook)
        if preserve:
            self.assertEqual(support.tree_snapshot(self.f.root), before, 'BUSINESS: check_only wrote fixture')
            self.row['fixture_tree_bytes_mtime_mode_unchanged'] = True
        self.assertEqual(len(self.f.event_paths()), 1, 'BUSINESS: check_only appended event')
        self.assertEqual(actual, expected, 'BUSINESS: designated native terminal reason')
        if expected is None:
            self.assertEqual(value, {'eligible': True, 'would_append': True, 'event': None},
                             'BUSINESS: exact check_only return')
            reads = self.row['calls'][-1]['reads']
            for path in self.f.expected_reads:
                self.assertIn(str(path), reads, 'BUSINESS: legacy locator target was not inputs.read')
            self.assertNotIn(True, self.row['calls'][-1]['native_contexts'], 'BUSINESS: fixture context not unrelated')
        else:
            self.row['designated_refusal_observed'] = True
        return value

    def seq2(self):
        self.row['stage'] = 'prerequisite_seq2'
        value, actual = self.invoke(lambda: self.recover(False), 'recover_mutation')
        if actual is not None:
            raise PrerequisiteBlocked('seq2 prerequisite blocked: ' + '/'.join(actual))
        assert value is not None, 'BUSINESS: seq2 returned no recovery object'
        self.assertTrue(value['eligible'])
        self.assertTrue(value['would_append'])
        ref = value['event']
        event = json.loads(Path(ref['path']).read_bytes())
        self.assertEqual((event['seq'], event['kind']), (2, 'dispatch_rejected'))
        self.assertEqual(len(self.f.event_paths()), 2)
        self.row['stage'] = 'business'
        return ref, event

    def package(self, ref, event):
        return self.mod._history_closure(event['payload']['input_closure'], Path(ref['path']), self.f.scope)

    def build_successor(self, event):
        manifest, run, index = self.f.successor(event)
        value, error = self.invoke(lambda: self.mod.build(self.f.repo, manifest, run, recovery_sources=index),
                                   'first_successor_build')
        return manifest, run, index, value, error

    def test_L01_full_health_and_recursive_capture(self):
        for flavor in ('string', 'ref', 'relative_ref'):
            for defect in ('healthy', 'deep_health', 'dag'):
                with self.subTest(flavor=flavor, graph=defect):
                    with self.scenario('health_' + flavor + '_' + defect, flavor, defect):
                        self.expect()

    def test_L02_unrelated_context_still_follows_counterevidence(self):
        for flavor in ('string', 'ref'):
            for defect in ('target_id', 'target_wire', 'target_cycle', 'target_script_hash',
                           'second_target', 'root_target', 'sibling_target'):
                name = 'counter_' + flavor + '_' + defect
                if CASE_FILTER and name not in CASE_FILTER:
                    continue
                with self.subTest(flavor=flavor, channel=defect):
                    with self.scenario(name, flavor, defect):
                        reason = 'counterevidence_native' if defect in ('root_target', 'sibling_target') else 'counterevidence_native_record'
                        self.expect((RECOVERY, reason))
                        for path in self.f.expected_reads:
                            if defect in ('target_id', 'target_wire', 'target_cycle', 'target_script_hash') and path != self.f.export:
                                continue
                            self.assertIn(str(path), self.row['calls'][-1]['reads'], 'BUSINESS: counterevidence source was not read')

    def test_L03_generic_null_absent_keep_sibling_and_other_values_fail_closed(self):
        cases = {'null': None, 'absent': None, 'boolean': (NATIVE, 'file_ref'), 'integer': (NATIVE, 'file_ref'),
                 'float': (NATIVE, 'file_ref'), 'list': (NATIVE, 'file_ref'),
                 'dict_empty': (NATIVE, 'file_ref'), 'dict_missing': (NATIVE, 'file_ref'),
                 'dict_extra': (NATIVE, 'file_ref'), 'dict_bad_hash': (NATIVE, 'file_ref_hash'),
                 'dict_wrong_hash': (NATIVE, 'source_hash_mismatch')}
        for defect, expected in cases.items():
            with self.subTest(value=defect):
                with self.scenario('generic_' + defect, defect=defect):
                    self.expect(expected)

    def test_L03_string_lexical_and_symlink_boundary(self):
        for defect in ('relative', 'empty', 'uri', 'double_slash', 'repeat_slash', 'dot', 'dotdot',
                       'trailing_slash', 'control', 'delete_control', 'symlink_file', 'symlink_parent'):
            with self.subTest(path=defect):
                with self.scenario('path_' + defect, defect=defect):
                    self.expect((RECOVERY, 'native_symlink' if defect.startswith('symlink') else 'native_locator'))

    def test_L04_native_shape_and_source_matrix(self):
        cases = {'missing': (NATIVE, 'source_unreadable'), 'invalid_json': (NATIVE, 'invalid_json'),
                 'duplicate_json': (NATIVE, 'duplicate_json_key'), 'nonfinite_json': (NATIVE, 'nonfinite_json_number'),
                 'bad_utf8': (NATIVE, 'invalid_json'), 'nonobject': (NATIVE, 'native_object'),
                 'shape_run_missing': (RECOVERY, 'native_unattributable'),
                 'shape_run_empty': (RECOVERY, 'native_unattributable'),
                 'shape_run_type': (RECOVERY, 'native_unattributable'),
                 'shape_args': (RECOVERY, 'native_unattributable'),
                 'shape_script': (RECOVERY, 'native_unattributable'),
                 'run_mismatch': (RECOVERY, 'native_run_id_mismatch')}
        for flavor in ('string', 'ref'):
            for defect, expected in cases.items():
                with self.subTest(flavor=flavor, native=defect):
                    with self.scenario('native_' + flavor + '_' + defect, flavor, defect):
                        self.expect(expected)

    def test_L04_termination_links_share_real_verifier(self):
        cases = {'healthy': None, 'line': (NATIVE, 'jsonl_line_bounds'),
                 'uuid': (NATIVE, 'interruption_event_identity'),
                 'agent': (NATIVE, 'termination_agent_mismatch'), 'hash': (NATIVE, 'source_hash_mismatch')}
        for flavor in ('string', 'ref'):
            for defect, expected in cases.items():
                with self.subTest(flavor=flavor, termination=defect):
                    with self.scenario('termination_' + flavor + '_' + defect, flavor, 'term_' + defect):
                        self.expect(expected)

    def test_L04_true_native_cycles(self):
        for defect in ('self_cycle', 'two_cycle'):
            with self.subTest(graph=defect):
                with self.scenario(defect, defect=defect):
                    self.expect((RECOVERY, 'native_locator_cycle'))

    def test_L04_real_reader_rejects_unstable_and_changed_origin(self):
        for flavor in ('string', 'ref'):
            for timing in ('between_pair', 'same_origin_later'):
                with self.subTest(flavor=flavor, timing=timing):
                    with self.scenario('stability_' + flavor + '_' + timing, flavor, 'dag') as f:
                        fired = []
                        def change(frame, event, arg):
                            if fired or event != 'return':
                                return
                            parent = frame.f_back
                            first = (timing == 'between_pair' and frame.f_code.co_name == 'read_bytes' and
                                     frame.f_locals.get('self') == f.leaf and parent is not None and
                                     parent.f_code.co_filename == str(f.executor) and parent.f_code.co_name == 'read')
                            later = (timing == 'same_origin_later' and frame.f_code.co_filename == str(f.executor) and
                                     frame.f_code.co_name == 'read' and frame.f_locals.get('path') == f.leaf)
                            if first or later:
                                f.leaf.write_bytes(support.encode(foreign_native('changed-but-still-unrelated')))
                                fired.append(True)
                        expected = (NATIVE, 'source_unstable' if timing == 'between_pair' else 'source_changed_during_capture')
                        self.expect(expected, hook=change, preserve=False)
                        self.assertEqual(fired, [True], 'BUSINESS: reader timing boundary not reached')

    def typed_index(self, role, value):
        f = self.f
        native = json.loads(f.export.read_bytes())
        row = {'schema_version': 1, 'identity': f.record['identity'], 'attempt_index': 1,
               'workflow_run_id': native['runId'], 'native_record': value, 'termination_refs': []}
        if value is MISSING:
            row.pop('native_record')
        if role == 'drift':
            row.update(kind='workflow', request=support.file_ref(f.repo / 'policy.json'), tool_failure=None)
        path = Path(f.manifest['evidence']['post_' + role + '_index_path'])
        support.write_json(path, row)
        return path

    def test_L05_actual_typed_indexes_initial_and_committed(self):
        for phase in ('initial', 'committed'):
            for role in ('audit', 'drift'):
                for defect in ('string', 'null', 'absent', 'bad_dict'):
                    name = 'typed_' + phase + '_' + role + '_' + defect
                    if CASE_FILTER and name not in CASE_FILTER:
                        continue
                    with self.subTest(phase=phase, role=role, value=defect):
                        with self.scenario(name, 'ref') as f:
                            self.expect()  # Independent healthy control before bad index exists.
                            if phase == 'committed':
                                self.seq2()
                            value = {'string': str(f.export), 'null': None, 'absent': MISSING,
                                     'bad_dict': {'path': str(f.export)}}[defect]
                            self.typed_index(role, value)
                            self.row['stage'] = 'business'
                            _, actual = self.invoke(lambda: self.recover(True), 'recover_' + phase + '_typed_index')
                            reason = role + '_index_keys' if defect == 'absent' else 'file_ref'
                            # Existing committed rescan wraps acquisition failures
                            # as input_changed_*. It must still reject the same typed
                            # value, not fail for an unrelated setup/source reason.
                            expected = ((RECOVERY, 'input_changed_file_ref')
                                if phase == 'committed' and defect in ('string', 'bad_dict')
                                else (NATIVE, reason))
                            self.row['expected'] = list(expected)
                            self.assertEqual(actual, expected, 'BUSINESS: actual typed index boundary must remain FileRef')
                            self.assertEqual(len(f.event_paths()), 1 if phase == 'initial' else 2)

    def test_L05_preflight_typed_reader_and_bound_committed_rescan(self):
        # An actual first-attempt manifest MUST have dispatch_preflight=null;
        # the old host rejects it before freezing. This method therefore names
        # the typed consumer and bound rescan explicitly, not a full first recover.
        for phase in ('typed_reader', 'bound_rescan'):
            for defect in ('string', 'null', 'absent', 'bad_dict'):
                with self.subTest(phase=phase, value=defect):
                    with self.scenario('preflight_' + phase + '_' + defect, 'ref') as f:
                        ref, event = self.seq2()
                        self.assertIsNone(f.manifest['evidence']['dispatch_preflight'])
                        if phase == 'bound_rescan':
                            # Match _recovery_submission: verify the real seq2 package,
                            # then re-derive its baseline from that sealed capture.
                            proof, error = self.invoke(lambda: self.mod._verify_recovery_event(event, ref, f.scope),
                                                       'preflight_verified_seq2')
                            self.assertIsNone(error, 'BUSINESS: seq2 proof prerequisite')
                            assert proof is not None, 'BUSINESS: seq2 proof missing'
                            frozen = self.mod._FrozenInputs(proof['capture'])
                            baseline, error = self.invoke(lambda: self.mod._handoff_baseline(
                                f.repo, ref, frozen), 'preflight_frozen_baseline')
                            self.assertIsNone(error, 'BUSINESS: frozen baseline prerequisite')
                            assert baseline is not None, 'BUSINESS: frozen baseline missing'
                            self.assertEqual(baseline['event'], event)
                            self.assertEqual(proof['build'], f.record)
                            self.assertTrue(baseline['sources'])
                            self.assertTrue(baseline['roles'])
                            package = self.package(ref, event)
                            evidence = json.loads(package.read(Path(event['payload']['evidence']['path'])))
                        observation = {'workflow_run_id': foreign_native()['runId'],
                                       'native_record': support.file_ref(f.export), 'termination_refs': []}
                        path = f.repo / 'bound-dispatch-preflight.json'
                        manifest = copy.deepcopy(f.manifest)
                        def consume():
                            if phase == 'typed_reader':
                                return self.mod._read_preflight(manifest['evidence']['dispatch_preflight'],
                                                                f.manifest_path, self.mod._Inputs())
                            return self.mod._recovery_rescan_committed(f.repo, manifest, f.record, evidence,
                                package, baseline, f.native_path, TARGET, f.operator_index, f.acceptance_index, ())
                        manifest['evidence']['dispatch_preflight'] = support.write_json(
                            path, {'schema_version': 1, 'observations': [observation]})
                        _, actual = self.invoke(consume, 'preflight_' + phase + '_healthy')
                        self.assertIsNone(actual, 'BUSINESS: healthy typed FileRef preflight refused')
                        self.assertIn(str(f.export), self.row['calls'][-1]['reads'],
                                      'BUSINESS: healthy typed consumer did not read native')
                        value = {'string': str(f.export), 'null': None, 'absent': MISSING,
                                 'bad_dict': {'path': str(f.export)}}[defect]
                        if value is MISSING:
                            observation.pop('native_record')
                        else:
                            observation['native_record'] = value
                        manifest['evidence']['dispatch_preflight'] = support.write_json(
                            path, {'schema_version': 1, 'observations': [observation]})
                        self.row['stage'] = 'business'
                        reason = ('observation_keys' if phase == 'typed_reader' else 'preflight_observation') if defect == 'absent' else 'file_ref'
                        _, actual = self.invoke(consume, 'preflight_' + phase)
                        self.row['expected'] = [NATIVE, reason]
                        self.assertEqual(actual, (NATIVE, reason), 'BUSINESS: bound typed preflight was ignored or widened')
                        consumer = '_read_preflight' if phase == 'typed_reader' else '_recovery_preflight_links'
                        self.assertGreater(self.row['calls'][-1]['calls'].get(consumer, 0), 0,
                                           'BUSINESS: designated typed consumer not reached')
                        self.assertEqual(len(f.event_paths()), 2)

    def test_L05_tool_error_null_is_valid_branch_but_counterevidence(self):
        for phase in ('initial', 'committed'):
            with self.subTest(phase=phase):
                with self.scenario('tool_error_' + phase, 'ref') as f:
                    self.expect()
                    if phase == 'committed':
                        self.seq2()
                    path = Path(f.manifest['evidence']['post_drift_index_path'])
                    support.write_json(path, {'schema_version': 1, 'identity': f.record['identity'], 'attempt_index': 1,
                        'request': support.file_ref(f.repo / 'policy.json'), 'kind': 'tool_error',
                        'workflow_run_id': None, 'native_record': None, 'termination_refs': [],
                        'tool_failure': {'error': 'synthetic-tool-failure'}})
                    self.row['stage'] = 'business'
                    _, actual = self.invoke(lambda: self.recover(True), 'tool_error_' + phase)
                    self.row['expected'] = [RECOVERY, 'counterevidence_index']
                    self.assertEqual(actual, (RECOVERY, 'counterevidence_index'),
                                     'BUSINESS: tool_error null is not malformed FileRef and still blocks recovery')

    def test_L06_publish_capture_membership_and_offline_consumption(self):
        for flavor in ('string', 'ref'):
            with self.subTest(flavor=flavor):
                with self.scenario('publish_' + flavor, flavor, 'deep_health') as f:
                    ref, event = self.seq2()
                    package = self.package(ref, event)
                    evidence = json.loads(package.read(Path(event['payload']['evidence']['path'])))
                    known = evidence['known_binding_sources']
                    self.assertEqual(known, sorted(known, key=lambda x: (x['path'], x['sha256'])))
                    self.assertEqual(len({x['path'] for x in known}), len(known))
                    current_ref = event['payload']['source_transition']['new_source_closure']
                    current = self.mod._history_closure(current_ref, Path(ref['path']), f.scope)
                    for path in f.expected_reads:
                        raw = path.read_bytes()
                        expected = {'path': str(path), 'sha256': support.digest(raw)}
                        self.assertEqual(known.count(expected), 1, 'BUSINESS: captured native origin/hash absent')
                        self.assertEqual(current.read(path), raw)
                        self.assertEqual(package.read(path), raw)
                    for path in [f.export, f.leaf, f.root_a, f.root_b]:
                        path.unlink()
                    proof, error = self.invoke(lambda: self.mod._verify_recovery_event(event, ref, f.scope),
                                               'offline_recovery_proof')
                    self.assertIsNone(error, 'BUSINESS: frozen proof fell back to live')
                    assert proof is not None, 'BUSINESS: frozen proof returned no object'
                    for path in f.expected_reads:
                        self.assertIn(str(path), self.row['calls'][-1]['reads'], 'BUSINESS: frozen read not tracked')
                        self.assertIn(str(path), proof['capture'])
                    self.assertEqual(len(f.event_paths()), 2)

    def repack_event(self, ref, event, kind):
        """Independently build bad packages with correct outer content hashes."""
        f = self.f
        event = copy.deepcopy(event)
        payload = event['payload']
        main = json.loads(Path(payload['input_closure']['path']).read_bytes())
        source_ref = payload['source_transition']['new_source_closure']
        current = json.loads(Path(source_ref['path']).read_bytes())
        package = self.package(ref, event)
        evidence = json.loads(package.read(Path(payload['evidence']['path'])))
        def blob(value):
            raw = value if isinstance(value, bytes) else support.encode(value)
            path = f.scope / 'blobs' / (support.digest(raw) + '.blob')
            if not path.exists():
                path.write_bytes(raw)
            return support.file_ref(path)
        def replace(rows, origin, reference):
            found = [x for x in rows if x['origin'] == origin]
            self.assertEqual(len(found), 1, 'SETUP: independent repack origin missing')
            found[0].update(sha256=reference['sha256'], blob=reference)
        if kind in ('leaf_missing', 'leaf_wrong_origin', 'leaf_wrong_bytes', 'leaf_snapshot_alias', 'unconsumed'):
            for closure in (main, current):
                if kind == 'leaf_missing':
                    closure['sources'] = [x for x in closure['sources'] if x['origin'] != str(f.leaf)]
                elif kind == 'leaf_wrong_origin':
                    next(x for x in closure['sources'] if x['origin'] == str(f.leaf))['origin'] = str(f.repo / 'same-bytes-other-origin')
                elif kind == 'leaf_wrong_bytes':
                    replace(closure['sources'], str(f.leaf), blob(support.encode(foreign_native('replacement-leaf'))))
                elif kind == 'leaf_snapshot_alias':
                    row = next(x for x in closure['sources'] if x['origin'] == str(f.leaf))
                    alias = f.scope / 'blobs' / 'independent-same-bytes-alias.blob'
                    alias.write_bytes(Path(row['blob']['path']).read_bytes())
                    row['blob'] = support.file_ref(alias)
                else:
                    extra = blob(b'independent unconsumed input')
                    closure['sources'].append({'origin': str(f.repo / 'unconsumed.input'),
                                               'sha256': extra['sha256'], 'blob': extra})
            current['sources'].sort(key=lambda x: (x['origin'], x['sha256']))
            new_ref = blob(current)
            replace(main['sources'], source_ref['path'], new_ref)
            next(x for x in main['sources'] if x['origin'] == source_ref['path'])['origin'] = new_ref['path']
            payload['source_transition']['new_source_closure'] = new_ref
        else:
            known = evidence['known_binding_sources']
            if kind == 'known_missing':
                evidence['known_binding_sources'] = [x for x in known if x['path'] != str(f.leaf)]
            elif kind == 'known_extra':
                evidence['known_binding_sources'] = sorted(known + [evidence['operator_statement']],
                                                          key=lambda x: (x['path'], x['sha256']))
            else:
                raise AssertionError('SETUP: unknown repack kind')
            evidence_ref = blob(evidence)
            main['sources'].append({'origin': evidence_ref['path'], 'sha256': evidence_ref['sha256'], 'blob': evidence_ref})
            payload['evidence'] = evidence_ref
        for closure in (main, current):
            closure['sources'].sort(key=lambda x: (x['origin'], x['sha256']))
        payload['input_closure'] = blob(main)
        raw = support.encode(event)
        return event, {'path': ref['path'], 'sha256': support.digest(raw)}

    def test_L06_frozen_missing_misbound_and_membership_are_rejected(self):
        for flavor in ('string', 'ref'):
            for defect in ('leaf_missing', 'leaf_wrong_origin', 'leaf_wrong_bytes', 'leaf_snapshot_alias',
                           'known_missing', 'known_extra', 'unconsumed'):
                name = 'frozen_' + flavor + '_' + defect
                if CASE_FILTER and name not in CASE_FILTER:
                    continue
                with self.subTest(flavor=flavor, defect=defect):
                    with self.scenario(name, flavor, 'deep_health') as f:
                        ref, event = self.seq2()
                        healthy, error = self.invoke(lambda: self.mod._verify_recovery_event(event, ref, f.scope), 'healthy_frozen')
                        self.assertIsNone(error)
                        bad, bad_ref = self.repack_event(ref, event, defect)
                        self.row['stage'] = 'business'
                        _, actual = self.invoke(lambda: self.mod._verify_recovery_event(bad, bad_ref, f.scope), 'bad_frozen_' + defect)
                        self.assertIsNotNone(actual, 'BUSINESS: frozen bad membership/mapping accepted')
                        assert actual is not None
                        self.assertIn(actual[1], ('incomplete_pending_closure', 'history_recovery_known_sources_membership',
                            'history_recovery_unconsumed_verification_input', 'source_hash_mismatch',
                            'history_blob_path', 'history_blob_mapping', 'history_recovery_snapshot', 'history_recovery_cross_capture_binding'),
                            'BUSINESS: unrelated error is not frozen membership rejection')
                        self.row['designated_refusal_observed'] = True

    def test_L07_reentry_and_handoff_pin_nonroot_native_digest(self):
        for flavor in ('string', 'ref'):
            for entry in ('reentry', 'handoff'):
                for change in ('unrelated_replacement', 'related_replacement', 'new_nested_target'):
                    with self.subTest(flavor=flavor, entry=entry, change=change):
                        with self.scenario('binding_' + flavor + '_' + entry + '_' + change, flavor) as f:
                            ref, event = self.seq2()
                            value, error = self.invoke(lambda: self.recover(True), 'healthy_idempotent')
                            self.assertIsNone(error)
                            self.assertEqual(value, {'eligible': True, 'would_append': False, 'event': None})
                            if entry == 'handoff':
                                manifest, run, index = f.successor(ref)
                                state = self.mod._load_scope(f.scope, f.manifest, self.mod._Inputs())
                                view = self.mod._replay_history(state)
                                manifest_data = json.loads(manifest.read_bytes())
                                mr = support.file_ref(manifest)
                                sr = {'path': str(run / 'workflow.js'), 'sha256': support.digest(self.mod._workflow(manifest_data, mr['sha256']))}
                                _, error = self.invoke(lambda: self.mod._capture_recovery_handoff(f.repo, state,
                                    manifest_data, mr, sr, index, self.mod._FrozenInputs(view['frozen_raw'])), 'healthy_live_handoff_capture')
                                self.assertIsNone(error, 'BUSINESS: healthy native handoff refused')
                            new = foreign_native('another-valid-unrelated-run')
                            if change == 'related_replacement':
                                new['toolUseID'] = TARGET
                            if change == 'new_nested_target':
                                support.write_json(f.leaf, dict(foreign_native('new-associated-leaf'), toolUseID=TARGET))
                                new['result'] = {'native_record': str(f.leaf)}
                            support.write_json(f.export, new)
                            before = [p.read_bytes() for p in f.event_paths()]
                            self.row['stage'] = 'business'
                            fn = (lambda: self.recover(True)) if entry == 'reentry' else (
                                lambda: self.mod.build(f.repo, manifest, run, recovery_sources=index))
                            _, actual = self.invoke(fn, 'changed_' + entry)
                            self.assertIsNotNone(actual, 'BUSINESS: changed native digest was recomputed as same input')
                            assert actual is not None
                            self.assertTrue(actual[1].startswith(('input_changed_', 'source_hash_mismatch',
                                'counterevidence_', 'recovery_source_hash_mismatch', 'recovery_handoff_')),
                                'BUSINESS: wrong failure family for pinned native')
                            self.assertEqual([p.read_bytes() for p in f.event_paths()], before, 'BUSINESS: bad handoff reserved')
                            self.row['designated_refusal_observed'] = True

    def test_L07_roots_are_append_only_not_fixed_full_hashes(self):
        for flavor in ('string', 'ref'):
            for entry in ('reentry', 'handoff'):
                for change in ('unrelated_append', 'prefix_rewrite', 'related_append'):
                    with self.subTest(flavor=flavor, entry=entry, change=change):
                        with self.scenario('root_time_' + flavor + '_' + entry + '_' + change, flavor, 'deep_health') as f:
                            ref, event = self.seq2()
                            raw = f.root_b.read_bytes()
                            row = {'type': 'progress', 'sessionId': f.root_b.stem,
                                   'data': {'toolUseID': TARGET if change == 'related_append' else 'new-unrelated-call'}}
                            f.root_b.write_bytes(raw + support.encode(row) + b'\n' if change != 'prefix_rewrite' else
                                                 raw.replace(b'unrelated-call', b'rewritten-call'))
                            self.row['stage'] = 'business'
                            if entry == 'reentry':
                                fn = lambda: self.recover(True)
                            else:
                                manifest, run, index = f.successor(ref)
                                fn = lambda: self.mod.build(f.repo, manifest, run, recovery_sources=index)
                            result, actual = self.invoke(fn, 'root_' + entry)
                            if change == 'unrelated_append':
                                self.assertIsNone(actual, 'BUSINESS: root append rejected by fixed full hash')
                                self.assertEqual(len(f.event_paths()), 2 if entry == 'reentry' else 3)
                                if entry == 'handoff':
                                    assert result is not None, 'BUSINESS: handoff returned no build object'
                                    self.assertIs(result['resume_only'], False)
                            else:
                                self.assertIsNotNone(actual, 'BUSINESS: rewritten/related root accepted')
                                expected = ('counterevidence_native' if entry == 'reentry' else 'recovery_handoff_counterevidence') if change == 'related_append' else (
                                    'input_changed_source_prefix_or_bytes' if entry == 'reentry' else 'recovery_handoff_prefix_rewritten')
                                self.assertEqual(actual, (RECOVERY, expected), 'BUSINESS: root time-view refusal reason')
                                self.assertEqual(len(f.event_paths()), 2)

    def test_L08_final_live_recheck_before_reserve(self):
        for flavor in ('string', 'ref'):
            with self.subTest(flavor=flavor):
                with self.scenario('final_recheck_' + flavor, flavor) as f:
                    ref, event = self.seq2()
                    manifest, run, index = f.successor(ref)
                    reached = []
                    def change(frame, event, arg):
                        if (not reached and event == 'call' and frame.f_code.co_filename == str(f.executor) and
                                frame.f_code.co_name == '_reserve_build'):
                            self.assertTrue((run / 'recovery-preflight.json').exists(), 'BUSINESS: reserve before capture')
                            f.export.write_bytes(support.encode(foreign_native('changed-after-capture')))
                            reached.append(True)
                    self.row['stage'] = 'business'
                    _, error = self.invoke(lambda: self.mod.build(f.repo, manifest, run, recovery_sources=index),
                                           'handoff_final_reserve', hook=change)
                    self.assertEqual(reached, [True], 'BUSINESS: final reserve boundary was not reached')
                    self.assertEqual(error, (RECOVERY, 'recovery_handoff_source_changed_during_capture'))
                    self.assertEqual(len(f.event_paths()), 2, 'BUSINESS: changed export published successor reserve')

    def test_L08_frozen_pending_resume_no_live_no_new_dispatch(self):
        for flavor in ('string', 'ref'):
            with self.subTest(flavor=flavor):
                with self.scenario('pending_frozen_' + flavor, flavor, 'deep_health') as f:
                    ref, event = self.seq2()
                    manifest, run, index, result, error = self.build_successor(ref)
                    self.assertIsNone(error, 'BUSINESS: healthy first successor not built')
                    assert result is not None, 'BUSINESS: successor returned no build object'
                    self.assertIs(result['resume_only'], False)
                    build_path = run / 'build-record.json'
                    build_ref = self.mod._freeze_blob(build_path.read_bytes(), f.scope)
                    before = [p.read_bytes() for p in f.event_paths()]
                    # A legal attempt2 call is a later time-view, not old-run counterevidence.
                    record = json.loads(build_path.read_bytes())
                    request, response = f._pair('Workflow', {'scriptPath': record['workflow_script']['path'],
                        'args': {'identity': record['identity'], 'manifest_sha256': record['manifest']['sha256']}},
                        201, 'independent-legal-attempt2')
                    response['toolUseResult'] = {'runId': 'independent-attempt2', 'status': 'completed'}
                    f.rows.extend([request, response])
                    f._write_native()
                    for path in (f.export, f.leaf, f.root_a, f.root_b, f.native_path, index):
                        path.unlink()
                    self.row['stage'] = 'business'
                    consumers = [('native_build', lambda: self.mod._native_build(f.repo, manifest, build_path, self.mod._Inputs())),
                        ('HistoryGraph', lambda: self.mod._HistoryGraph(f.scope).walk(build_ref, build_path, 'build')),
                        ('replay', lambda: self.mod._replay_history(self.mod._load_scope(f.scope, f.manifest, self.mod._Inputs()))),
                        ('pending_resume', lambda: self.mod.build(f.repo, manifest, run))]
                    for label, fn in consumers:
                        value, actual = self.invoke(fn, 'frozen_' + label)
                        self.assertIsNone(actual, 'BUSINESS: frozen consumer used removed live original')
                        if label == 'pending_resume':
                            assert value is not None, 'BUSINESS: pending resume returned no build object'
                            self.assertIs(value['resume_only'], True)
                        self.assertEqual([p.read_bytes() for p in f.event_paths()], before)
                    self.assertEqual(len(f.event_paths()), 3)

    def completed_successor(self, ref):
        """Independent synthetic native result; only real Python consumers run."""
        f = self.f
        manifest, run, index, result, error = self.build_successor(ref)
        self.assertIsNone(error, 'BUSINESS: complete successor prerequisite build failed')
        assert result is not None, 'BUSINESS: complete successor returned no build object'
        self.assertIs(result['resume_only'], False)
        record = json.loads((run / 'build-record.json').read_bytes())
        run_id = 'independent-permanent-successor'
        nodes, seats = [], []
        for i, role in enumerate(record['roles']):
            report = {'vote': 'PASS', 'coverage_complete': True, 'findings': [], 'pending': [], 'prior_findings': []}
            nodes.append({'type': 'workflow_agent', 'agentId': run_id + '-' + str(i),
                'agentType': role['agentType'], 'label': role['label'], 'model': 'synthetic',
                'queuedAt': 1000 + i * 100, 'startedAt': 1000 + i * 100, 'durationMs': 10, 'state': 'done'})
            seats.append({**{k: role[k] for k in ('index', 'role_id', 'agentType', 'label')},
                'attempted': True, 'settled': True, 'raw': support.encode(report).decode(), 'error': None})
        native = {'runId': run_id, 'startTime': 1000, 'durationMs': 300020, 'status': 'completed',
            'agentCount': len(nodes), 'script': (run / 'workflow.js').read_text(),
            'args': {'identity': record['identity'], 'manifest_sha256': record['manifest']['sha256']},
            'workflowProgress': nodes, 'result': {'schema_version': 1, 'identity': record['identity'],
                'manifest_sha256': record['manifest']['sha256'], 'results': seats,
                'control': {'round_timer_ms': 300000, 'stop_observed': False, 'return_reason': 'all_settled'}}}
        path = run / 'independent-successor-native.json'
        support.write_json(path, native)
        support.write_json(run / 'audit-index.json', {'schema_version': 1, 'identity': record['identity'],
            'attempt_index': 2, 'workflow_run_id': run_id, 'native_record': support.file_ref(path), 'termination_refs': []})
        # Legal attempt2 rows must never be reinterpreted as old-run evidence by
        # immutable native_build/replay/prepare/collect/check consumers.
        request, response = f._pair('Workflow', {'scriptPath': record['workflow_script']['path'],
            'args': {'identity': record['identity'], 'manifest_sha256': record['manifest']['sha256']}},
            201, 'independent-completed-attempt2')
        response['toolUseResult'] = {'runId': run_id, 'status': 'completed'}
        f.rows.extend([request, response])
        f._write_native()
        for old in (f.export, f.leaf, f.root_a, f.root_b, f.native_path, index):
            if old.exists():
                old.unlink()
        args = (f.repo, manifest, run / 'build-record.json', run_id, path, run / (run.name + '.json'))
        for label, function in (
                ('offline_successor_native_build', lambda: self.mod._native_build(f.repo, manifest, args[2], self.mod._Inputs())),
                ('offline_prepare', lambda: self.mod._prepare_policy(*args)),
                ('offline_collect', lambda: self.mod._collect_final(*args)),
                ('offline_check', lambda: self.mod._collect_final(*args, check_result=args[-1]))):
            _, actual = self.invoke(function, label)
            self.assertIsNone(actual, 'BUSINESS: complete frozen successor consumer failed')
        self.assertEqual(len(f.event_paths()), 4)  # reserve1, rejection2, reserve3, round4.
        output = args[-1]
        result = json.loads(output.read_bytes())
        final_ref = result['inputs']['input_closure']
        final = self.mod._history_closure(final_ref, output, f.scope,
                                         raw=Path(final_ref['path']).read_bytes())
        genesis = json.loads(Path(f.binding['genesis']['path']).read_bytes())
        _, actual = self.invoke(lambda: self.mod._recompute_round(f.repo, result, final, genesis, [],
                                carrier=output, scope=f.scope), 'healthy_frozen_round_kernel')
        self.assertIsNone(actual, 'BUSINESS: healthy round kernel prerequisite')
        return result, final, genesis, output

    def test_L08_prepare_collect_check_after_removing_legacy_live_sources(self):
        for flavor in ('string', 'ref'):
            name = 'complete_frozen_' + flavor
            if CASE_FILTER and name not in CASE_FILTER:
                continue
            with self.subTest(flavor=flavor):
                with self.scenario(name, flavor, 'deep_health'):
                    ref, event = self.seq2()
                    self.completed_successor(ref)
                    state = self.mod._load_scope(self.f.scope, self.f.manifest, self.mod._Inputs())
                    view, error = self.invoke(lambda: self.mod._replay_history(state), 'complete_offline_replay')
                    self.assertIsNone(error)
                    assert view is not None, 'BUSINESS: offline replay returned no view'
                    self.assertEqual(len(view['attempts']), 1)
                    self.assertEqual(view['attempts'][0]['attempt_index'], 2)

    def test_L05_declared_result_native_record_does_not_inherit_generic_union(self):
        for defect in ('string', 'null', 'bad_dict'):
            name = 'typed_result_' + defect
            if CASE_FILTER and name not in CASE_FILTER:
                continue
            with self.subTest(value=defect):
                with self.scenario(name, 'ref', 'deep_health') as f:
                    ref, event = self.seq2()
                    result, frozen, genesis, output = self.completed_successor(ref)
                    original = result['inputs']['native_record']
                    bad = copy.deepcopy(result)
                    bad['inputs']['native_record'] = {'string': original['path'], 'null': None,
                                                      'bad_dict': {'path': original['path']}}[defect]
                    self.row['stage'] = 'business'
                    _, actual = self.invoke(lambda: self.mod._recompute_round(f.repo, bad, frozen, genesis, [],
                                            carrier=output, scope=f.scope), 'typed_result_round_kernel')
                    expected = ('E_PREVIOUS_IDENTITY', 'round_input_binding_native_record') if defect == 'null' else (
                                'E_POLICY_SOURCE', 'file_ref')
                    self.row['expected'] = list(expected)
                    self.assertEqual(actual, expected, 'BUSINESS: declared result native input accepted generic locator')
                    self.assertEqual(len(f.event_paths()), 4)

    def test_L09_non_author_bad_implementations_are_caught_by_business_assertions(self):
        with self.subTest(control='good_string_health'):
            with self.scenario('control_good_string_health', 'string'):
                self.expect()
        with self.subTest(mutant='skip_string'):
            with self.scenario('mutant_skip_string', 'string', mutant='skip_string'):
                self.row['stage'] = 'business_mutant'
                marker = 'legacy locator target was not inputs.read'
                try:
                    self.expect()
                except AssertionError as caught:
                    self.assertIn(marker, str(caught), 'BUSINESS: mutant was not caught by designated assertion')
                    actual = self.row['calls'][-1]['actual']
                    self.assertEqual(actual, {'returned': True}, 'BUSINESS: import/catalog/error is not CAUGHT')
                    self.row['mutant_caught'] = True
                    self.row['caught_assertion'] = marker
                else:
                    self.fail('BUSINESS: independently bad implementation survived')

        def component(f):
            # This is the recursive locator component, NOT a public recovery.
            return self.mod._recovery_native_links(f.carrier, f.archive, self.mod._RecoveryCaptureInputs(),
                                                  set(), f.record, selected_id=TARGET)

        for mutant in (None, 'skip_nested'):
            for defect in ('dag', 'second_target'):
                with self.subTest(component='nested', mutant=mutant, defect=defect):
                    with self.scenario('nested_' + (mutant or 'good') + '_' + defect,
                                       'ref', defect, mutant=mutant) as f:
                        compile(f.executor.read_bytes(), str(f.executor), 'exec')
                        self.row['stage'] = 'business_mutant' if mutant else 'business'
                        self.row['nested_proof_scope'] = 'component_recursion_and_public_retained_defense'
                        expected = (RECOVERY, 'counterevidence_native_record') if defect == 'second_target' else None
                        _, actual = self.invoke(lambda: component(f), 'nested_component')
                        component_call = self.row['calls'][-1]
                        self.assertIn(str(f.export), component_call['reads'],
                                      'BUSINESS: nested component did not reach outer native')
                        if mutant and expected is not None:
                            marker = 'nested component must reject associated leaf'
                            try:
                                self.assertEqual(actual, expected, 'BUSINESS: ' + marker)
                            except AssertionError as caught:
                                self.assertIn(marker, str(caught), 'BUSINESS: wrong component assertion caught')
                                self.assertEqual(component_call['actual'], {'returned': True},
                                                 'BUSINESS: component setup/error is not CAUGHT')
                                self.assertNotIn(str(f.leaf), component_call['reads'],
                                                 'BUSINESS: mutant did not actually omit nested read')
                                self.row['component_mutant_caught'] = True
                                self.row['caught_assertion'] = marker
                            else:
                                self.fail('BUSINESS: independently bad nested component survived')
                        else:
                            self.assertEqual(actual, expected, 'BUSINESS: good/healthy nested component contract')
                            if not mutant:
                                self.assertIn(str(f.leaf), component_call['reads'],
                                              'BUSINESS: good component did not follow nested native')
                            else:
                                self.assertNotIn(str(f.leaf), component_call['reads'],
                                                 'BUSINESS: healthy mutant did not omit nested read')
                        # Do not disable the fixedpoint or call ordinary refusal CAUGHT:
                        # this same mutant is redundant at the public entry boundary.
                        self.expect(expected)
                        public_call = self.row['calls'][-1]
                        self.assertIn(str(f.leaf), public_call['reads'],
                                      'BUSINESS: public retained defense did not reach nested native')
                        self.assertGreater(public_call['calls'].get('drain', 0), 0,
                                           'BUSINESS: public binding fixedpoint not reached')
                        self.assertNotIn('mutant_caught', self.row,
                                         'BUSINESS: component catch must not be public CAUGHT')
                        self.row['public_mutant_classification'] = (
                            'REDUNDANT_PUBLIC_REJECTION' if mutant and expected else
                            'HEALTHY_PUBLIC_ACCEPTANCE' if expected is None else 'GOOD_PUBLIC_REJECTION')


if __name__ == '__main__':
    unittest.main()
