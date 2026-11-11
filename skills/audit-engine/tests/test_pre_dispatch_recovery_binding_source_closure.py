"""R5-CODE-001: actual authority-target inputs are source-closure seeds.

Run only in a fresh -I -B child with the reviewed pre-import legacy guard.
SOT: executor-contract 13.5-13.8. No new metadata role is authorized here:
only the target FileRefs of the TWO actual authority arguments are seeds.
Explicit native_source/original_locator and native_record retain their roles.
All trees are synthetic; the historical Python host only generates fixtures.
No Workflow execution, production edit, shared-fixture edit or old-byte edit.
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
    'binding_source_support', Path(__file__).with_name('pre_dispatch_recovery_fixtures.py'))
assert _spec is not None and _spec.loader is not None
support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(support)

EVIDENCE_SINK = None
TARGET = 'call_fixture_rejection'
RECOVERY = 'E_RECOVERY_EVIDENCE'
NATIVE = 'E_NATIVE_EVIDENCE'
POLICY = 'E_POLICY_SOURCE'
PLACEMENTS = ('shared', 'operator', 'acceptance')
GRAPHS = ('root', 'export', 'recursive_root')
BAD = ('success', 'unknown', 'missing')


class NotJudged(RuntimeError):
    """An unmet prerequisite is an ERROR, never a passed test or business RED."""


def closure_bytes(ref):
    path = Path(ref['path'])
    if support.file_ref(path) != ref:
        raise NotJudged('SETUP: closure FileRef mismatch')
    value = json.loads(path.read_bytes())
    result = {}
    for entry in value['sources']:
        blob = Path(entry['blob']['path'])
        raw = blob.read_bytes()
        if support.file_ref(blob) != entry['blob'] or support.digest(raw) != entry['sha256']:
            raise NotJudged('SETUP: closure blob/hash mismatch')
        if entry['origin'] in result:
            raise NotJudged('SETUP: duplicate closure origin')
        result[entry['origin']] = raw
    return result


class BindingFixture(support.RecoveryFixture):
    def __init__(self, placement='shared', graph='root', status='healthy', key='native_source'):
        super().__init__()
        self.placement, self.graph, self.link_key = placement, graph, key
        self.authority_bytes = self.native_path.read_bytes()
        self.locators = {'operator': self.target_path, 'acceptance': self.target_path}
        if placement != 'shared':
            other = self.repo / 'other-authority-target.payload'
            support.write_json(other, self.target_locator)
            self.locators['acceptance' if placement == 'operator' else 'operator'] = other
        self.selected_locator = self.locators['acceptance' if placement == 'acceptance' else 'operator']
        self.bridge = self.native_path.with_name('77777777-2222-4333-8444-555555555555.jsonl')
        self.leaf = self.native_path.with_name('88888888-2222-4333-8444-555555555555.jsonl')
        self.export = self.repo / 'binding-linked-export.payload'
        self.entry = self.leaf if graph == 'root' else self.bridge
        value = copy.deepcopy(self.target_locator)
        value[key] = str(self.entry)
        support.write_json(self.selected_locator, value)
        for role, path in (('operator', self.operator_index), ('acceptance', self.acceptance_index)):
            index = json.loads(path.read_bytes())
            index['target'] = support.file_ref(self.locators[role])
            support.write_json(path, index)
        self.set_status(status)
        self.graph_paths = [self.leaf] if graph == 'root' else (
            [self.bridge, self.export] if graph == 'export' else [self.bridge, self.export, self.leaf])
        # These are the normally frozen old bytes, not a patched old closure.
        self.old_map = closure_bytes(self.old_closure)
        if any(str(path) in self.old_map for path in [*self.locators.values(), *self.graph_paths]):
            raise NotJudged('SETUP: new authority metadata accidentally belongs to old generation')
        if self.native_path.read_bytes() != self.authority_bytes:
            raise NotJudged('SETUP: original rejection or Q&A changed')
        for path in set(self.locators.values()):
            target = json.loads(path.read_bytes())
            if any(target.get(k) != v for k, v in self.target_locator.items()):
                raise NotJudged('SETUP: original complete target binding changed')

    def root_bytes(self, path, status):
        related = status != 'healthy'
        request, response = self._pair('Workflow', {
            'scriptPath': str(self.script_path if related else self.executor),
            'args': {'identity': {'audit_cycle_id': self.manifest['audit_cycle_id'] if related else 'unrelated-cycle'}}},
            800 if not related else 900, 'call_binding_leaf_' + status, session=path.stem)
        response['toolUseResult'] = {'runId': 'synthetic-binding-run', 'status': 'completed'}
        response['message']['content'][0]['content'] = 'Synthetic completed run'
        rows = [request] if status == 'unknown' else [request, response]
        return b''.join(support.encode(row) + b'\n' for row in rows)

    def export_value(self, status='healthy'):
        return {'runId': 'synthetic-binding-export', 'script': 'unrelated synthetic program',
                'args': {'identity': {'audit_cycle_id': self.manifest['audit_cycle_id']
                         if status != 'healthy' else 'unrelated-cycle'}},
                'status': 'running' if status == 'unknown' else 'completed',
                'result': None if status == 'unknown' else {}, 'workflowProgress': []}

    def set_status(self, status):
        if self.graph != 'root':
            self.bridge.write_bytes(support.encode({'type': 'progress', 'sessionId': self.bridge.stem,
                'data': {'native_record': str(self.export)}}) + b'\n')
            value = self.export_value(status if self.graph == 'export' else 'healthy')
            if self.graph == 'recursive_root':
                value['native_source'] = str(self.leaf)
            support.write_json(self.export, value)
        terminal = self.export if self.graph == 'export' else self.leaf
        if self.graph != 'export':
            terminal.write_bytes(self.root_bytes(terminal, status))
        if status == 'missing':
            terminal.unlink()
        self.terminal = terminal
        self.validate_native_graph()

    def validate_native_graph(self):
        """Check our synthetic native identities/pairs, not the recovery decision."""
        roots = [self.leaf] if self.graph == 'root' else (
            [self.bridge] if self.graph == 'export' else [self.bridge, self.leaf])
        for path in roots:
            if not path.exists():
                continue  # Intentional missing evidence is a business fixture.
            raw = path.read_bytes()
            if not raw.endswith(b'\n'):
                raise NotJudged('SETUP: synthetic root is incomplete')
            rows = [json.loads(line) for line in raw.splitlines()]
            uuids = [r['uuid'] for r in rows if 'uuid' in r]
            if len(uuids) != len(set(uuids)):
                raise NotJudged('SETUP: duplicate synthetic root UUID')
            requests = {}
            for row in rows:
                if row.get('type') not in ('assistant', 'user'):
                    continue
                if row.get('sessionId') != path.stem:
                    raise NotJudged('SETUP: synthetic root session mismatch')
                for block in row['message']['content']:
                    if block['type'] == 'tool_use':
                        if block['id'] in requests:
                            raise NotJudged('SETUP: duplicate synthetic tool id')
                        requests[block['id']] = row['uuid']
                    elif block['type'] == 'tool_result':
                        parent = requests.get(block['tool_use_id'])
                        if parent is None or row.get('parentUuid') != parent or row.get('sourceToolAssistantUUID') != parent:
                            raise NotJudged('SETUP: synthetic native pair mismatch')

    def live_change(self, status):
        if status == 'missing':
            self.terminal.unlink()
        elif self.graph == 'export':
            support.write_json(self.export, self.export_value(status))
        else:
            # Preserve the complete healthy root snapshot as an append-only prefix.
            with self.terminal.open('ab') as stream:
                stream.write(self.root_bytes(self.terminal, status))
        self.validate_native_graph()


def repack(f, event_ref, status=None, *, unused_blob=False):
    """Independently address a NEW seq2 package, never a legacy pinned object.

    Start from the actual healthy producer. Rebuild both new and enclosing maps,
    known FileRefs and content-addressed hashes independently. A fixed producer
    may already capture every graph node; that is NOT a fixture failure. No
    current source, old input, authority answer, or capacity proof is rewritten.
    """
    event_path = Path(event_ref['path'])
    event = json.loads(event_path.read_bytes())
    outer = closure_bytes(event['payload']['input_closure'])
    transition = event['payload']['source_transition']
    current = closure_bytes(transition['new_source_closure'])
    evidence = json.loads(outer[event['payload']['evidence']['path']])
    original_sources = copy.deepcopy((transition['from_sources'], transition['to_sources']))
    if status is not None:
        f.set_status(status)
        for path in f.graph_paths:
            if path.exists():
                current[str(path)] = outer[str(path)] = path.read_bytes()
            else:
                current.pop(str(path), None)
                outer.pop(str(path), None)
    if unused_blob:
        # Frozen does NOT imply consumed. These origins have no actual input role.
        # A scan-all-package.raw fix must not mint their own known membership.
        unused_root = f.native_path.with_name('99999999-2222-4333-8444-555555555555.jsonl')
        blob = f.repo / 'extra-frozen-but-unconsumed.json'
        additions = {str(blob): support.encode({'native_source': str(unused_root)}),
                     str(unused_root): f.root_bytes(unused_root, 'healthy')}
        current.update(additions)
        outer.update(additions)
    observation = str(f.scope / 'recovery-read-observations.json')
    evidence['known_binding_sources'] = [
        {'path': origin, 'sha256': support.digest(raw)}
        for origin, raw in sorted(current.items()) if origin != observation]

    def freeze(raw):
        path = f.scope / 'blobs' / (support.digest(raw) + '.blob')
        if path.exists() and path.read_bytes() != raw:
            raise NotJudged('SETUP: independent content-address collision')
        path.write_bytes(raw)
        return support.file_ref(path)

    def closure(rawmap):
        return freeze(support.encode({'schema_version': 1, 'algorithm_version': 'canonical_v1',
            'sources': [{'origin': origin, 'sha256': support.digest(raw), 'blob': freeze(raw)}
                        for origin, raw in sorted(rawmap.items())]}))

    transition['new_source_closure'] = closure(current)
    ref = transition['new_source_closure']
    outer[ref['path']] = Path(ref['path']).read_bytes()
    event['payload']['evidence'] = freeze(support.encode(evidence))
    ref = event['payload']['evidence']
    outer[ref['path']] = Path(ref['path']).read_bytes()
    event['payload']['input_closure'] = closure(outer)
    ref = support.write_json(event_path, event)
    packed = closure_bytes(event['payload']['input_closure'])
    view = closure_bytes(transition['new_source_closure'])
    if any(packed[origin] != raw for origin, raw in view.items()):
        raise NotJudged('SETUP: independent cross-capture mismatch')
    if original_sources != (transition['from_sources'], transition['to_sources']):
        raise NotJudged('SETUP: source generations changed')
    if f.old_map != closure_bytes(f.old_closure):
        raise NotJudged('SETUP: original frozen input changed')
    return ref


class BindingSourceClosureTests(unittest.TestCase):
    @contextmanager
    def scenario(self, **kwargs):
        self.row = {'case': self._testMethodName, 'parameters': kwargs, 'stage': 'setup',
                    'steps': [], 'assertions': [], 'not_reached': [], 'subtests': 0}
        f = None
        try:
            f = BindingFixture(**kwargs)
            self.f = f
            self.row.update(old_host_first_reserve=True, old_script_bytes=f.script_path.stat().st_size,
                            complete_target_binding_preserved=True, original_qa_unchanged=True,
                            target_file_refs_match_bytes=True, synthetic_native_uuid_and_pair_consistency_checked=True,
                            candidate_sha256=support.digest(f.executor.read_bytes()))
            with patch.dict(os.environ, f.environment, clear=True):
                self.mod = support.load_module(f.executor)
                with patch.object(self.mod, '_RUNTIME_REJECTION_PROFILES', f.runtime_profiles):
                    self.row['stage'] = 'business'
                    yield f
        except NotJudged as error:
            self.row['not_judged'] = str(error)
            raise
        finally:
            if f is not None:
                try:
                    f.assert_old_unchanged(self)
                    self.assertEqual(support.digest(f.executor.read_bytes()), self.row['candidate_sha256'])
                    self.row['old_pinned_bytes_unchanged'] = True
                finally:
                    f.close()
            if EVIDENCE_SINK is not None:
                EVIDENCE_SINK(copy.deepcopy(self.row))

    def check(self, name, actual, expected: object = True):
        self.row['assertions'].append({'name': name, 'reached': True, 'actual': actual,
                                       'expected': expected, 'passed': actual == expected})

    def finish(self):
        bad = [a['name'] for a in self.row['assertions'] if not a['passed']]
        self.assertFalse(bad, 'R5-CODE-001: ' + ', '.join(bad))

    def invoke(self, label, function):
        step = {'label': label, 'calls': {}, 'reads': [], 'event_count_before': len(self.f.event_paths())}
        self.row['steps'].append(step)
        watched = {str(p) for p in [*self.f.locators.values(), *self.f.graph_paths]}
        def observe(frame, event, arg):
            if frame.f_code.co_filename != str(self.f.executor):
                return
            name = frame.f_code.co_name
            if event == 'call':
                step['calls'][name] = step['calls'].get(name, 0) + 1
            if event == 'return' and name == 'read':
                path = str(frame.f_locals.get('path'))
                item = {'path': path, 'successful': isinstance(arg, bytes),
                        'reader': type(frame.f_locals.get('self')).__name__}
                if path in watched and item not in step['reads']:
                    step['reads'].append(item)
        previous = sys.getprofile()
        try:
            sys.setprofile(observe)
            value = function()
            step['returned'] = True
            if isinstance(value, dict):
                step['metadata'] = {k: value[k] for k in ('eligible', 'would_append', 'resume_only') if k in value}
            return value, None
        except self.mod.ExecutorError as error:
            result = (error.error_code, error.reason)
            step['error'] = {'code': result[0], 'reason': result[1]}
            return None, result
        finally:
            sys.setprofile(previous)
            step['event_count_after'] = len(self.f.event_paths())

    def recover(self, check_only=False, extra=(), target=TARGET):
        f = self.f
        return self.mod.recover_dispatch_rejection(f.repo, f.manifest_path, f.build_record_path,
            f.native_path, target, f.operator_index, f.acceptance_index,
            check_only=check_only, additional_sources=extra)

    def healthy_event(self):
        value, error = self.invoke('healthy_producer_setup', lambda: self.recover())
        if error is not None or value is None or not value.get('event') or len(self.f.event_paths()) != 2:
            raise NotJudged('NOT_JUDGED: healthy seq2 setup ' + str(error))
        self.row['healthy_producer_setup_reached'] = True
        return value['event']

    def consumed(self, label):
        successful = {r['path'] for r in self.row['steps'][-1]['reads'] if r['successful']}
        self.check(label + '/all_actual_target_locators_consumed',
                   all(str(p) in successful for p in self.f.locators.values()))
        for path in self.f.graph_paths:
            self.check(label + '/consumed/' + path.name, str(path) in successful)

    def expected(self, label, function, errors, *, gaps=()):
        before = [p.read_bytes() for p in self.f.event_paths()]
        self.row['not_reached'] += [label + '/reason', label + '/no_new_event']
        value, actual = self.invoke(label, function)
        if actual is not None and actual not in errors and actual not in gaps:
            raise NotJudged('NOT_JUDGED: unexpected earlier blocker ' + str(actual))
        self.check(label + '/specified_business_reason', actual in errors)
        self.check(label + '/no_success_result', value is None)
        self.check(label + '/no_new_event', [p.read_bytes() for p in self.f.event_paths()] == before)
        self.row['steps'][-1]['designated_errors'] = [list(e) for e in errors]
        self.row['steps'][-1]['wrong_layer_gap'] = actual in gaps
        self.row['not_reached'] = [v for v in self.row['not_reached'] if not v.startswith(label + '/')]

    def producer(self, placement, graph, status, key='native_source'):
        with self.scenario(placement=placement, graph=graph, status=status, key=key) as f:
            expected = ((NATIVE, 'source_unreadable') if graph == 'export' else
                        (RECOVERY, 'native_source_unreadable')) if status == 'missing' else (
                        RECOVERY, 'counterevidence_native_record' if graph == 'export' else 'counterevidence_native')
            for mutation in (False, True):
                label = 'mutation' if mutation else 'initial_check_only'
                snapshot = support.tree_snapshot(f.root)
                if status == 'healthy':
                    value, error = self.invoke(label, lambda: self.recover(check_only=not mutation))
                    self.check(label + '/healthy_not_rejected', error is None and value is not None)
                    if error is not None or value is None:
                        self.row['not_reached'].append(label + '/eligible_and_source_consumption')
                        continue
                    self.check(label + '/eligible', value['eligible'])
                    self.check(label + '/event_count', len(f.event_paths()), 2 if mutation else 1)
                    self.consumed(label)
                    if mutation:
                        event = json.loads(Path(value['event']['path']).read_bytes())
                        captured = closure_bytes(event['payload']['source_transition']['new_source_closure'])
                        evidence_map = closure_bytes(event['payload']['input_closure'])
                        evidence = json.loads(evidence_map[event['payload']['evidence']['path']])
                        known = {r['path']: r['sha256'] for r in evidence['known_binding_sources']}
                        for path in f.graph_paths:
                            self.check(label + '/captured_known/' + path.name,
                                str(path) in captured and known.get(str(path)) == support.digest(path.read_bytes()))
                else:
                    self.expected(label, lambda: self.recover(check_only=not mutation), (expected,))
                if not mutation:
                    self.check(label + '/zero_tree_writes', support.tree_snapshot(f.root) == snapshot)
            self.finish()

    def healthy_chain(self, placement, graph):
        with self.scenario(placement=placement, graph=graph) as f:
            event = self.healthy_event()
            package = closure_bytes(json.loads(Path(event['path']).read_bytes())['payload']['input_closure'])
            manifest, run, index = f.successor(event)
            value, error = self.invoke('committed_healthy', lambda: self.recover(True))
            self.check('committed/healthy_not_rejected', error is None and value is not None)
            self.check('committed/no_new_event', len(f.event_paths()), 2)
            self.consumed('committed')
            event_value = json.loads(Path(event['path']).read_bytes())
            # Live source bytes must not be consulted by an immutable proof.
            protected = {f.native_path, *f.locators.values(), *f.graph_paths}
            original_read = Path.read_bytes
            def no_live_read(path):
                if path in protected:
                    raise NotJudged('NOT_JUDGED: frozen proof attempted live source read')
                return original_read(path)
            with patch.object(Path, 'read_bytes', no_live_read):
                value, error = self.invoke('frozen_healthy',
                    lambda: self.mod._verify_recovery_event(event_value, event, f.scope))
            self.check('frozen/healthy_not_rejected', error is None and value is not None)
            self.consumed('frozen')
            self.row['frozen_live_source_reads_forbidden'] = True
            value, error = self.invoke('ordinary_first_successor',
                lambda: self.mod.build(f.repo, manifest, run, recovery_sources=index))
            self.check('successor/healthy_not_rejected', error is None and value is not None)
            if error is not None or value is None:
                self.row['not_reached'] += ['successor/seq3', 'pending/frozen_resume']
                self.finish()
                return
            self.check('successor/seq3', len(f.event_paths()), 3)
            self.check('successor/not_resume', value['resume_only'], False)
            self.consumed('handoff')
            record = json.loads((run / 'build-record.json').read_bytes())
            self.check('successor/attempt', record['attempt_index'], 2)
            self.check('successor/round', record['identity']['round'], 1)
            self.check('successor/same_cycle', record['identity']['audit_cycle_id'], f.record['identity']['audit_cycle_id'])
            for path in {f.native_path, *f.locators.values(), *f.graph_paths, index}:
                if path.exists():
                    path.unlink()
            value, error = self.invoke('pending_frozen_resume', lambda: self.mod.build(f.repo, manifest, run))
            self.check('pending/without_live_sources', error is None and value is not None)
            if value is not None:
                self.check('pending/resume_only', value['resume_only'])
            self.consumed('pending')
            self.row['outer_package_entries'] = len(package)
            self.finish()

    def frozen_bad(self, placement, graph, status):
        with self.scenario(placement=placement, graph=graph) as f:
            event = repack(f, self.healthy_event(), status)
            self.row.update(independent_consumer_repack=True, source_pairs_and_old_inputs_unchanged=True)
            manifest, run, index = f.successor(event)
            expected = ((NATIVE, 'incomplete_pending_closure') if graph == 'export' else
                        (RECOVERY, 'native_incomplete_pending_closure')) if status == 'missing' else (
                        RECOVERY, 'counterevidence_native_record' if graph == 'export' else 'counterevidence_native')
            gaps = ((RECOVERY, 'recovery_sources_required'),
                    (POLICY, 'history_recovery_known_sources_membership'),
                    (POLICY, 'history_recovery_unconsumed_verification_input'))
            # Deliberately omit the live handoff: the frozen proof must decide first.
            self.expected('frozen_public_build', lambda: self.mod.build(f.repo, manifest, run), (expected,), gaps=gaps)
            calls = self.row['steps'][-1]['calls']
            self.check('frozen/proof_reached', calls.get('_verify_recovery_event', 0) > 0)
            self.check('frozen/no_live_handoff', calls.get('_capture_recovery_handoff', 0), 0)
            self.check('frozen/no_preparation', not run.exists())
            self.finish()

    def live_bad(self, placement, graph, status, consumer):
        with self.scenario(placement=placement, graph=graph) as f:
            event = self.healthy_event()
            manifest, run, index = f.successor(event)
            f.live_change(status)
            if consumer == 'committed':
                expected = ((NATIVE, 'source_unreadable') if graph == 'export' else
                            (RECOVERY, 'native_source_unreadable')) if status == 'missing' else (
                            RECOVERY, 'counterevidence_native_record' if graph == 'export' else 'counterevidence_native')
                if graph == 'export' and status == 'missing':
                    expected = (RECOVERY, 'input_changed_source_unreadable')
                self.expected('committed_rescan', lambda: self.recover(True, target='different-current-argument'),
                              (expected,), gaps=((RECOVERY, 'input_changed_recovery_arguments'),))
                self.check('committed/rescan_reached',
                           self.row['steps'][-1]['calls'].get('_recovery_rescan_committed', 0) > 0)
            else:
                expected = ((NATIVE, 'source_unreadable') if graph == 'export' else
                            (RECOVERY, 'source_unreadable')) if status == 'missing' else (
                            (NATIVE, 'recovery_source_hash_mismatch') if graph == 'export' else
                            (RECOVERY, 'recovery_handoff_counterevidence'))
                self.expected('first_ordinary_successor',
                    lambda: self.mod.build(f.repo, manifest, run, recovery_sources=index), (expected,))
                self.check('handoff/capture_reached',
                           self.row['steps'][-1]['calls'].get('_capture_recovery_handoff', 0) > 0)
                self.check('handoff/no_workflow_preparation', not (run / 'workflow.js').exists())
                self.check('handoff/no_preflight', not (run / 'recovery-preflight.json').exists())
            self.finish()

    def boundary(self, defect):
        with self.scenario() as f:
            if defect == 'unused_frozen_json':
                event = repack(f, self.healthy_event(), unused_blob=True)
                manifest, run, index = f.successor(event)
                self.row['unconsumed_json_not_an_authorized_seed'] = True
                self.expected('unused_frozen_json', lambda: self.mod.build(f.repo, manifest, run),
                    ((POLICY, 'history_recovery_known_sources_membership'),
                     (POLICY, 'history_recovery_unconsumed_verification_input')),
                    gaps=((RECOVERY, 'recovery_sources_required'),))
            elif defect == 'top_level_json_string':
                value = json.loads(f.selected_locator.read_bytes())
                support.write_json(f.selected_locator, support.encode(value).decode('ascii'))
                f._refresh_indices()
                self.expected(defect, lambda: self.recover(True), ((RECOVERY, 'target_locator_shape'),))
            elif defect == 'opaque_prose':
                value = json.loads(f.selected_locator.read_bytes())
                value.pop('native_source')
                value['description'] = 'Synthetic example only: ' + support.encode(
                    {'native_source': str(f.leaf)}).decode('ascii')
                support.write_json(f.selected_locator, value)
                f._refresh_indices()
                f.set_status('success')
                value, error = self.invoke(defect, lambda: self.recover(True))
                self.check(defect + '/not_interpreted_as_links', error is None and value is not None)
                self.check(defect + '/no_leaf_read', not any(
                    r['path'] == str(f.leaf) for r in self.row['steps'][-1]['reads']))
            elif defect == 'root_namespace':
                outside = f.repo / 'outside.jsonl'
                outside.write_bytes(f.leaf.read_bytes())
                value = json.loads(f.selected_locator.read_bytes())
                value['native_source'] = str(outside)
                support.write_json(f.selected_locator, value)
                f._refresh_indices()
                self.expected(defect, lambda: self.recover(True), ((RECOVERY, 'native_namespace'),))
            elif defect in ('authority_string_ref', 'authority_extra_key', 'authority_bad_digest'):
                value = json.loads(f.operator_index.read_bytes())
                if defect == 'authority_string_ref':
                    value['target'] = str(f.target_path)
                    expected = 'target_file_ref'
                elif defect == 'authority_extra_key':
                    value['unexpected'] = None
                    expected = 'operator_index_shape'
                else:
                    value['target']['sha256'] = '0' * 64
                    expected = 'target_source_hash_mismatch'
                support.write_json(f.operator_index, value)
                self.expected(defect, lambda: self.recover(True), ((RECOVERY, expected),))
            else:
                # A typed manifest index must not gain the generic string-export lane.
                index = Path(f.manifest['evidence']['post_audit_index_path'])
                support.write_json(index, {'schema_version': 1, 'identity': f.record['identity'],
                    'attempt_index': 1, 'workflow_run_id': 'synthetic-binding-export',
                    'native_record': str(f.export), 'termination_refs': []})
                support.write_json(f.export, f.export_value())
                self.expected(defect, lambda: self.recover(True), ((NATIVE, 'file_ref'),))
            self.finish()


def install_cases():
    """One method = one fixture = one case; zero subtest-based inflation."""
    def add(name, method, *args):
        def case(self):
            return getattr(self, method)(*args)
        case.__name__ = 'test_' + name
        setattr(BindingSourceClosureTests, case.__name__, case)
    for placement in PLACEMENTS:
        for graph in GRAPHS:
            for status in ('healthy', *BAD):
                add(f'producer_{placement}_{graph}_{status}', 'producer', placement, graph, status)
            add(f'healthy_chain_{placement}_{graph}', 'healthy_chain', placement, graph)
            for status in BAD:
                add(f'frozen_{placement}_{graph}_{status}', 'frozen_bad', placement, graph, status)
                for consumer in ('committed', 'handoff'):
                    add(f'{consumer}_{placement}_{graph}_{status}', 'live_bad', placement, graph, status, consumer)
        for status in ('healthy', *BAD):
            add(f'producer_{placement}_original_locator_{status}', 'producer', placement, 'root', status,
                'original_locator')
    for defect in ('unused_frozen_json', 'opaque_prose', 'top_level_json_string', 'root_namespace',
                   'authority_string_ref', 'authority_extra_key', 'authority_bad_digest', 'typed_index_string'):
        add('boundary_' + defect, 'boundary', defect)


install_cases()

if __name__ == '__main__':
    unittest.main()
