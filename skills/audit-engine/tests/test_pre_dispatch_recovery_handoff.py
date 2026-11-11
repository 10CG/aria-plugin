"""TASK-011: independent first-successor live handoff contracts.

Fixture construction uses the real recovery producer. A missing new build keyword
is a feature-absence RED, not evidence that any downstream assertion was judged.
"""
from __future__ import annotations

import copy
import importlib.util
import inspect
import json
from pathlib import Path
from typing import Any
import unittest
from unittest import mock

_spec = importlib.util.spec_from_file_location(
    'task011_history_support', Path(__file__).with_name('test_pre_dispatch_recovery_history.py'))
assert _spec is not None and _spec.loader is not None
_history = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_history)
support = _history.support


class HandoffTests(unittest.TestCase):
    f: Any
    mod: Any
    # Reuse fixture lifecycle and real producer, not the older test cases.
    setUp = _history.RecoveryHistory.setUp
    recover = _history.RecoveryHistory.recover
    succeeds = _history.RecoveryHistory.succeeds
    state = _history.RecoveryHistory.state
    successor = _history.RecoveryHistory.successor
    capture = _history.RecoveryHistory.capture
    result = _history.RecoveryHistory.result

    def prepared(self):
        event = self.recover()
        manifest, run, index = self.f.successor(event)
        return event, manifest, run, index

    def require_feature(self):
        self.assertIn('recovery_sources', inspect.signature(self.mod.build).parameters,
                      'FEATURE_NOT_IMPLEMENTED_TDD_RED: build recovery_sources; business body NOT_JUDGED')

    def build_successor(self, manifest, run, index):
        self.require_feature()
        return self.mod.build(self.f.repo, manifest, run, recovery_sources=index)

    def assert_counterevidence(self, manifest, run, index):
        before = [p.read_bytes() for p in self.f.event_paths()]
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.build_successor(manifest, run, index)
        self.assertEqual((caught.exception.error_code, caught.exception.reason),
                         ('E_RECOVERY_EVIDENCE', 'recovery_handoff_counterevidence'))
        self.assertEqual([p.read_bytes() for p in self.f.event_paths()], before)
        self.assertFalse((run / 'workflow.js').exists())
        self.assertFalse((run / 'recovery-preflight.json').exists())
        self.f.assert_old_unchanged(self)

    def reused_client_manifest(self, manifest_path, run, client):
        """Change a real successor's identity, keeping all path/size rules valid."""
        manifest = json.loads(manifest_path.read_bytes())
        manifest['client_round_id'] = client
        run = run.with_name(f"post_planning-R{manifest['round']}-{client}-fresh-directory")
        for kind in ('audit', 'drift', 'disposition'):
            manifest['evidence']['post_' + kind + '_index_path'] = str(run / (kind + '-index.json'))
        support.write_json(manifest_path, manifest)
        self.mod._validate_manifest(manifest)
        self.mod._check_workflow_capacity(self.mod._workflow(manifest, support.digest(manifest_path.read_bytes())))
        self.assertFalse(run.exists())
        return manifest, run

    def assert_client_refused_before_preparation(self, manifest, run, index=None):
        # Directory mtimes may change for writer.lock. No new file/blob/event is permitted.
        files = {str(p.relative_to(self.f.root)): p.read_bytes()
                 for p in self.f.root.rglob('*') if p.is_file()}
        events = [p.read_bytes() for p in self.f.event_paths()]
        try:
            with self.assertRaises(self.mod.ExecutorError,
                                   msg='reused reserve client was accepted and published') as caught:
                self.mod.build(self.f.repo, manifest, run, recovery_sources=index)
            self.assertEqual((caught.exception.error_code, caught.exception.reason),
                             ('E_PREVIOUS_IDENTITY', 'scope_latest_head_or_attempt'))
            self.assertFalse(run.exists(), 'identity rejection left new preparation files')
            self.assertEqual({str(p.relative_to(self.f.root)): p.read_bytes()
                              for p in self.f.root.rglob('*') if p.is_file()}, files)
        finally:
            self.assertEqual([p.read_bytes() for p in self.f.event_paths()], events,
                             'reused client must never publish another reserve')
            self.f.assert_old_unchanged(self)

    def test_rejected_client_reuse_fails_before_new_preparations(self):
        _, path, run, index = self.prepared()
        _, run = self.reused_client_manifest(path, run, self.f.record['identity']['client_round_id'])
        self.assertEqual(self.mod._replay_history(self.state())['attempts'], [])
        self.assert_client_refused_before_preparation(path, run, index)

    def test_unique_client_full_pending_replay_and_frozen_resume(self):
        event, manifest, run, index = self.prepared()
        self.assertIs(self.build_successor(manifest, run, index)['resume_only'], False)
        view = self.mod._replay_history(self.state())
        self.assertEqual((view['attempts'], view['charged_rounds']), ([], 0))
        self.assertEqual(self.state()['reserve_count'], 2)
        record = json.loads((run / 'build-record.json').read_bytes())
        self.assertEqual((record['attempt_index'], record['identity']['round']), (2, 1))
        self.assertEqual(record['prefix_head'], event)
        for payload in (json.loads(p.read_bytes())['payload'] for p in self.f.event_paths()
                        if json.loads(p.read_bytes())['kind'] == 'reserve'):
            self.assertIsNone(payload['previous_round'])
            self.assertIsNone(payload['previous_attempt'])
        self.f.native_path.unlink()
        index.unlink()
        before = support.tree_snapshot(self.f.root)
        self.assertIs(self.mod.build(self.f.repo, manifest, run)['resume_only'], True)
        # Lock churn is allowed by build; files and event bytes are frozen.
        after = support.tree_snapshot(self.f.root)
        self.assertEqual({k: v for k, v in before.items() if v[2] is not None},
                         {k: v for k, v in after.items() if v[2] is not None})
        self.mod._replay_history(self.state())
        self.f.assert_old_unchanged(self)

    def test_actual_reserve_gate_rejects_rejected_client_with_complete_handoff(self):
        # Construct real immutable preparation independently of build's outer gate.
        # No production guard is removed; every handoff leaf is produced/verified.
        _, path, run, index = self.prepared()
        manifest, run = self.reused_client_manifest(path, run, 'client-old')
        mod, f = self.mod, self.f
        state = self.state()
        view = mod._replay_history(state)
        inputs = mod._Inputs()
        inputs.raw.update(view['frozen_raw'])
        inputs.read(path)
        manifest_ref = support.file_ref(path)
        program = mod._workflow(manifest, manifest_ref['sha256'])
        script_path = run / 'workflow.js'
        script_ref = {'path': str(script_path), 'sha256': support.digest(program)}
        capture = mod._capture_recovery_handoff(f.repo, state, manifest, manifest_ref, script_ref,
                                               index, mod._FrozenInputs(view['frozen_raw']))
        handoff = mod._publish_recovery_handoff(capture, state, f.scope, run, inputs)
        mod._publish(script_path, program, run)
        inputs.read(script_path)
        mod._freeze_closure(inputs, f.scope, run / 'input-closure.json')
        frozen = mod._FrozenInputs(dict(inputs.raw))
        proof = mod._verify_recovery_handoff(handoff, manifest, manifest_ref, script_ref,
                                             state['head'], frozen, f.repo)
        self.assertEqual(proof['handoff']['successor']['identity']['client_round_id'], 'client-old')
        self.assertEqual(view['attempts'], [])
        before = [p.read_bytes() for p in f.event_paths()]
        with self.assertRaises(mod.ExecutorError,
                               msg='actual _reserve_build published a duplicate rejected client') as caught:
            mod._reserve_build(state, f.scope, manifest, manifest_ref, script_ref,
                               recovery_preflight=handoff, inputs=frozen, live=capture['live'])
        self.assertEqual(caught.exception.error_code, 'E_PREVIOUS_IDENTITY')
        self.assertIn(caught.exception.reason, ('round_attempt_sequence', 'scope_latest_head_or_attempt'))
        self.assertEqual([p.read_bytes() for p in f.event_paths()], before)
        f.assert_old_unchanged(self)

    def next_attempt_manifest(self):
        event = self.recover()
        args, output, _ = self.result(event)
        self.mod._collect_final(*args, check_result=output)
        view = self.mod._replay_history(self.state())
        self.assertEqual(len(view['attempts']), 1)
        self.mod._require_dispatch_policy(view)
        manifest = json.loads(args[1].read_bytes())
        manifest.update(round=2, attempt_index=3, client_round_id='client-next')
        run = args[2].parent.with_name('post_planning-R2-client-next-protocol-fixture-aggregated')
        manifest['evidence'].update(previous_round=support.file_ref(output),
            post_audit_index_path=str(run / 'audit-index.json'),
            post_drift_index_path=str(run / 'drift-index.json'),
            post_disposition_index_path=str(run / 'disposition-index.json'))
        path = self.f.repo / 'next-round-manifest.json'
        support.write_json(path, manifest)
        return path, run

    def test_later_build_still_rejects_the_rejected_reserve_client(self):
        path, run = self.next_attempt_manifest()
        _, run = self.reused_client_manifest(path, run, 'client-old')
        self.assert_client_refused_before_preparation(path, run)

    def test_later_build_still_rejects_committed_attempt_client(self):
        path, run = self.next_attempt_manifest()
        _, run = self.reused_client_manifest(path, run, 'client-successor')
        self.assert_client_refused_before_preparation(path, run)

    def assert_later_reserve_refuses_client(self, client):
        path, run = self.next_attempt_manifest()
        manifest, run = self.reused_client_manifest(path, run, client)
        # Independent caller supplies matching real manifest/script bytes to the
        # final publisher, without relying on build's earlier identity check.
        script = self.mod._workflow(manifest, support.digest(path.read_bytes()))
        script_path = run / 'workflow.js'
        script_path.parent.mkdir(parents=True)
        script_path.write_bytes(script)
        before = [p.read_bytes() for p in self.f.event_paths()]
        with self.assertRaises(self.mod.ExecutorError,
                               msg='later _reserve_build accepted a previously reserved client') as caught:
            self.mod._reserve_build(self.state(), self.f.scope, manifest,
                                    support.file_ref(path), support.file_ref(script_path))
        self.assertEqual(caught.exception.error_code, 'E_PREVIOUS_IDENTITY')
        self.assertIn(caught.exception.reason, ('round_attempt_sequence', 'scope_latest_head_or_attempt'))
        self.assertEqual([p.read_bytes() for p in self.f.event_paths()], before)

    def test_later_actual_reserve_gate_rejects_rejected_client(self):
        self.assert_later_reserve_refuses_client('client-old')

    def test_later_actual_reserve_gate_rejects_committed_client(self):
        self.assert_later_reserve_refuses_client('client-successor')

    def independently_repacked_duplicate_client(self):
        """Build only a legal unique package, then address an illegal duplicate independently.

        This counterexample survives fixing both producer gates. No duplicate
        build/reserve call, altered producer, or broken hash is used to create it.
        """
        _, manifest_path, original_run, index = self.prepared()
        self.build_successor(manifest_path, original_run, index)
        self.mod._replay_history(self.state())
        manifest = json.loads(manifest_path.read_bytes())
        original_client = manifest['client_round_id']
        duplicate = self.f.record['identity']['client_round_id']
        run = original_run.with_name('post_planning-R1-' + duplicate + '-independent-repacked')
        run.mkdir()
        for source in original_run.iterdir():
            self.assertTrue(source.is_file())
            (run / source.name).write_bytes(source.read_bytes())
        path = self.f.repo / 'independent-duplicate-manifest.json'
        manifest['client_round_id'] = duplicate
        for kind in ('audit', 'drift', 'disposition'):
            manifest['evidence']['post_' + kind + '_index_path'] = str(run / (kind + '-index.json'))
        manifest_ref = support.write_json(path, manifest)
        program = self.mod._workflow(manifest, manifest_ref['sha256'])
        self.mod._check_workflow_capacity(program)
        (run / 'workflow.js').write_bytes(program)
        script_ref = support.file_ref(run / 'workflow.js')
        record = json.loads((run / 'build-record.json').read_bytes())
        identity = {key: manifest[key] for key in record['identity']}
        handoff_path = run / 'recovery-preflight.json'
        handoff = json.loads(handoff_path.read_bytes())
        handoff['successor'] = {'identity': identity, 'attempt_index': 2,
                                'manifest': manifest_ref, 'workflow_script': script_ref}
        handoff_ref = support.write_json(handoff_path, handoff)
        closure_path = run / 'input-closure.json'
        closure = json.loads(closure_path.read_bytes())

        def blob(raw):
            target = self.f.scope / 'blobs' / (support.digest(raw) + '.blob')
            if target.exists():
                self.assertEqual(target.read_bytes(), raw)
            else:
                target.write_bytes(raw)
            return support.file_ref(target)

        entries = []
        for entry in closure['sources']:
            origin = Path(entry['origin'])
            if origin == manifest_path:
                origin, raw = path, path.read_bytes()
            elif origin.is_relative_to(original_run):
                origin = run / origin.relative_to(original_run)
                raw = origin.read_bytes()
            else:
                raw = Path(entry['blob']['path']).read_bytes()
            entries.append({'origin': str(origin), 'sha256': support.digest(raw), 'blob': blob(raw)})
        closure['sources'] = sorted(entries, key=lambda row: (row['origin'], row['sha256']))
        closure_ref = support.write_json(closure_path, closure)
        reserve_path = self.f.event_paths()[-1]
        reserve = json.loads(reserve_path.read_bytes())
        self.assertEqual((reserve['seq'], reserve['kind']), (3, 'reserve'))
        reserve['payload'].update(identity=identity, manifest=manifest_ref, workflow_script=script_ref)
        reservation = support.write_json(reserve_path, reserve)
        record.update(identity=identity, manifest=manifest_ref, workflow_script=script_ref,
                      reservation=reservation, input_closure=closure_ref, recovery_preflight=handoff_ref)
        for role in record['roles']:
            role['label'] = role['label'].replace(original_client, duplicate)
        record_ref = support.write_json(run / 'build-record.json', record)
        blob((run / 'build-record.json').read_bytes())
        # Independently establish byte/address integrity before asking consumers.
        self.assertEqual(support.file_ref(Path(record_ref['path'])), record_ref)
        for ref in (manifest_ref, script_ref, handoff_ref, closure_ref, reservation):
            self.assertEqual(support.file_ref(Path(ref['path'])), ref)
        for entry in closure['sources']:
            raw = Path(entry['blob']['path']).read_bytes()
            self.assertEqual(support.digest(raw), entry['sha256'])
            self.assertEqual(support.file_ref(Path(entry['blob']['path'])), entry['blob'])
        frozen = self.mod._history_closure(closure_ref, closure_path, self.f.scope,
                                           raw=closure_path.read_bytes())
        for origin in (path, run / 'workflow.js', handoff_path, run / 'build-metadata.json',
                       run / 'recovery-handoff-observations.json'):
            self.assertEqual(frozen.read(origin), origin.read_bytes())
        self.assertEqual(record['sources'], self.f.current_sources)
        self.assertEqual(record['prefix_head'], support.file_ref(self.f.event_paths()[1]))
        self.assertEqual(reserve['previous_event'], record['prefix_head'])
        self.assertEqual(record['identity'], reserve['payload']['identity'])
        self.assertEqual(record['identity'], handoff['successor']['identity'])
        self.assertEqual(record['identity']['client_round_id'], self.f.record['identity']['client_round_id'])
        self.f.assert_old_unchanged(self)
        return path, run, index

    def assert_duplicate_prefix_identity_rejection(self):
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.mod._replay_history(self.state())
        self.assertEqual((caught.exception.error_code, caught.exception.reason),
                         ('E_PREVIOUS_IDENTITY', 'history_reservation_sequence'))

    def assert_duplicate_consumer_refused(self, label, consume):
        before = support.tree_snapshot(self.f.root)
        try:
            with self.assertRaises(self.mod.ExecutorError,
                                   msg=label + ' accepted a self-consistent duplicate-client seq3') as caught:
                consume()
            self.assertEqual(caught.exception.error_code, 'E_PREVIOUS_IDENTITY')
            self.assertIn(caught.exception.reason, ('history_reservation_sequence',
                'scope_latest_head_or_attempt', 'round_attempt_sequence'))
        finally:
            self.assertEqual(support.tree_snapshot(self.f.root), before)
            self.f.assert_old_unchanged(self)

    def test_independent_duplicate_package_full_replay_refuses_identity(self):
        self.independently_repacked_duplicate_client()
        self.assert_duplicate_prefix_identity_rejection()

    def test_native_build_refuses_self_consistent_duplicate_client_package(self):
        path, run, _ = self.independently_repacked_duplicate_client()
        self.assert_duplicate_prefix_identity_rejection()
        self.assert_duplicate_consumer_refused('_native_build', lambda: self.mod._native_build(
            self.f.repo, path, run / 'build-record.json', self.mod._Inputs()))

    def test_graph_build_refuses_self_consistent_duplicate_client_package(self):
        _, run, _ = self.independently_repacked_duplicate_client()
        self.assert_duplicate_prefix_identity_rejection()
        self.assert_duplicate_consumer_refused('_HistoryGraph build', lambda: self.graph_build(run / 'build-record.json'))

    def test_pending_resume_refuses_self_consistent_duplicate_client_package(self):
        path, run, index = self.independently_repacked_duplicate_client()
        self.assert_duplicate_prefix_identity_rejection()
        self.f.native_path.unlink()
        index.unlink()
        self.assert_duplicate_consumer_refused('frozen exact pending resume',
            lambda: self.mod.build(self.f.repo, path, run))

    def test_unique_client_package_all_consumers_and_frozen_resume_healthy(self):
        _, path, run, index = self.prepared()
        self.build_successor(path, run, index)
        view = self.mod._replay_history(self.state())
        self.assertEqual((view['attempts'], view['charged_rounds']), ([], 0))
        self.mod._native_build(self.f.repo, path, run / 'build-record.json', self.mod._Inputs())
        self.graph_build(run / 'build-record.json')
        self.f.native_path.unlink()
        index.unlink()
        before = support.tree_snapshot(self.f.root)
        self.assertIs(self.mod.build(self.f.repo, path, run)['resume_only'], True)
        self.assertEqual(support.tree_snapshot(self.f.root), before)
        self.assertEqual(len(self.f.event_paths()), 3)
        self.f.assert_old_unchanged(self)

    def test_fixture_health_real_seq2_two_generations_and_short_successor(self):
        event_ref, manifest_path, _, index_path = self.prepared()
        f, mod = self.f, self.mod
        self.assertEqual(support.file_ref(Path(event_ref['path'])), event_ref)
        event = json.loads(Path(event_ref['path']).read_bytes())
        self.assertEqual((event['seq'], event['kind'], event['previous_event']),
                         (2, 'dispatch_rejected', f.binding['reservation']))
        transition = event['payload']['source_transition']
        self.assertEqual(transition['from_sources'], f.old_sources)
        self.assertEqual(transition['to_sources'], f.current_sources)
        def closure(ref):
            return mod._history_closure(ref, Path(event_ref['path']), f.scope,
                                        raw=Path(ref['path']).read_bytes())
        old, new = closure(f.old_closure), closure(transition['new_source_closure'])
        for name in f.old_sources:
            path = Path(f.old_sources[name]['path'])
            self.assertEqual(support.digest(old.read(path)), f.old_sources[name]['sha256'])
            self.assertEqual(support.digest(new.read(path)), f.current_sources[name]['sha256'])
        evidence = closure(event['payload']['input_closure'])
        rec = json.loads(evidence.read(Path(event['payload']['evidence']['path'])))
        for key in ('operator_statement', 'evidence_acceptance', 'runtime_rejection_basis'):
            self.assertEqual(support.digest(evidence.read(Path(rec[key]['path']))), rec[key]['sha256'])
        manifest_raw = manifest_path.read_bytes()
        manifest = json.loads(manifest_raw)
        mod._validate_manifest(manifest)
        script = mod._workflow(manifest, support.digest(manifest_raw))
        mod._check_workflow_capacity(script)
        self.assertLessEqual(len(script.encode() if isinstance(script, str) else script), 524288)
        self.assertIsNone(manifest['evidence']['dispatch_preflight'])
        index = json.loads(index_path.read_bytes())
        self.assertEqual(index, {'schema_version': 1, 'recovery_event': event_ref, 'additional_sources': []})
        self.assertEqual(len(f.event_paths()), 2)
        f.assert_old_unchanged(self)

    def test_missing_sources_must_reject_real_build_without_second_recover(self):
        # RED on an actual wrong acceptance, not on introspection of the future API.
        _, manifest, run, _ = self.prepared()
        before = [p.read_bytes() for p in self.f.event_paths()]
        try:
            result = self.mod.build(self.f.repo, manifest, run)
        except self.mod.ExecutorError as error:
            self.assertEqual((error.error_code, error.reason),
                             ('E_RECOVERY_EVIDENCE', 'recovery_sources_required'))
            self.assertEqual([p.read_bytes() for p in self.f.event_paths()], before)
            self.assertFalse(run.exists())
        else:
            paths = self.f.event_paths()
            events = [json.loads(p.read_bytes()) for p in paths]
            new = events[len(before):]
            payload = new[-1].get('payload') if new else None
            self.fail(f'WRONG_ACCEPTANCE: returned={result!r}; '
                      f'old_events={len(before)} final_events={len(events)} '
                      f'new_kinds={[e.get("kind") for e in new]!r} '
                      f'new_reservation={payload!r}')

    def test_same_root_success_vetoes_before_publication(self):
        _, manifest, run, index = self.prepared()
        self.f.append_workflow(status='success')
        self.assert_counterevidence(manifest, run, index)

    def test_same_root_unknown_vetoes_before_publication(self):
        _, manifest, run, index = self.prepared()
        self.f.append_workflow(status='unknown')
        self.assert_counterevidence(manifest, run, index)

    def test_added_index_root_is_not_an_approval_token(self):
        event = self.recover()
        other = self.f.append_workflow(status='unknown', new_root=True)
        _, manifest, run, index = (event, *self.f.successor(event, (other,)))
        parsed = json.loads(index.read_bytes())
        self.assertEqual(parsed['additional_sources'], [str(other.resolve())])
        self.assert_counterevidence(manifest, run, index)

    def test_first_successor_handoff_binds_actual_bytes_and_history(self):
        event, manifest, run, index = self.prepared()
        self.build_successor(manifest, run, index)
        record = json.loads((run / 'build-record.json').read_bytes())
        self.assertEqual(record['attempt_index'], 2)
        self.assertEqual(record['identity']['round'], 1)
        self.assertEqual(record['identity']['audit_cycle_id'], self.f.record['identity']['audit_cycle_id'])
        self.assertEqual(record['prefix_head'], event)
        reserve = json.loads(Path(record['reservation']['path']).read_bytes())['payload']
        self.assertIsNone(reserve['previous_round'])
        self.assertIsNone(reserve['previous_attempt'])
        ref = record['recovery_preflight']
        self.assertEqual(ref, support.file_ref(run / 'recovery-preflight.json'))
        handoff = json.loads(Path(ref['path']).read_bytes())
        self.assertEqual(set(handoff), {'schema_version', 'recovery_event', 'prefix_head',
            'rejected_reservation', 'successor', 'sources_index', 'sources'})
        self.assertEqual(handoff['schema_version'], 1)
        self.assertEqual(handoff['recovery_event'], event)
        self.assertEqual(handoff['prefix_head'], event)
        self.assertEqual(handoff['rejected_reservation'], self.f.binding['reservation'])
        successor = handoff['successor']
        self.assertEqual(set(successor), {'identity', 'attempt_index', 'manifest', 'workflow_script'})
        self.assertEqual(successor['identity'], record['identity'])
        self.assertEqual(successor['attempt_index'], 2)
        self.assertEqual(successor['manifest'], support.file_ref(manifest))
        self.assertEqual(successor['workflow_script'], support.file_ref(run / 'workflow.js'))
        self.assertEqual(handoff['sources_index']['original_locator'], str(index.resolve()))
        snapshot = handoff['sources_index']['snapshot']
        self.assertEqual(Path(snapshot['path']).read_bytes(), index.read_bytes())
        self.assertEqual(support.file_ref(Path(snapshot['path'])), snapshot)
        sources = handoff['sources']
        self.assertEqual([x['original_locator'] for x in sources], sorted({x['original_locator'] for x in sources}))
        self.assertIn(str(self.f.native_path.resolve()), [x['original_locator'] for x in sources])
        for source in sources:
            self.assertEqual(set(source), {'original_locator', 'runtime_config_root', 'baseline_snapshot', 'snapshot'})
            for leaf in (source['baseline_snapshot'], source['snapshot']):
                if leaf is not None:
                    self.assertEqual(support.file_ref(Path(leaf['path'])), leaf)
        self.assertEqual([json.loads(p.read_bytes())['kind'] for p in self.f.event_paths()],
                         ['reserve', 'dispatch_rejected', 'reserve'])
        self.f.assert_old_unchanged(self)

    def test_unrelated_live_tail_allows_first_build(self):
        _, manifest, run, index = self.prepared()
        self.f.append_workflow(status='success', related=False)
        self.build_successor(manifest, run, index)
        self.assertEqual(len(self.f.event_paths()), 3)
        self.assertTrue((run / 'recovery-preflight.json').is_file())

    def test_pending_resume_without_live_originals_is_frozen_and_idempotent(self):
        _, manifest, run, index = self.prepared()
        self.build_successor(manifest, run, index)
        record = (run / 'build-record.json').read_bytes()
        events = [p.read_bytes() for p in self.f.event_paths()]
        script = (run / 'workflow.js').read_bytes()
        self.f.native_path.unlink()
        index.unlink()
        result = self.mod.build(self.f.repo, manifest, run)
        self.assertIs(result['resume_only'], True)
        self.assertEqual((run / 'build-record.json').read_bytes(), record)
        self.assertEqual((run / 'workflow.js').read_bytes(), script)
        self.assertEqual([p.read_bytes() for p in self.f.event_paths()], events)

    def test_real_native_prepare_collect_and_offline_replay(self):
        self.require_feature()
        event = self.recover()
        args, output, _ = self.result(event)
        self.f.native_path.unlink()
        self.mod._collect_final(*args, check_result=output)
        self.mod._replay_history(self.state())

    def inject_at_reserve(self, target):
        """Mutate only after real capture, at the real reservation boundary."""
        event, manifest, run, index = self.prepared()
        self.require_feature()
        original = self.mod._reserve_build
        before = [p.read_bytes() for p in self.f.event_paths()]
        seen = []

        def boundary(*args, **kwargs):
            handoff_path = run / 'recovery-preflight.json'
            self.assertTrue(handoff_path.is_file(), 'capture did not reach reserve boundary')
            handoff = json.loads(handoff_path.read_bytes())
            if target == 'root':
                entry = next(x for x in handoff['sources']
                             if x['original_locator'] == str(self.f.native_path.resolve()))
                snapshot = entry['snapshot']
                self.assertEqual(Path(snapshot['path']).read_bytes(), self.f.native_path.read_bytes())
                self.f.append_workflow(status='unknown')
                changed = self.f.native_path.read_bytes()
            else:
                snapshot = handoff['sources_index']['snapshot']
                self.assertEqual(Path(snapshot['path']).read_bytes(), index.read_bytes())
                index.write_bytes(index.read_bytes() + b' ')
                changed = index.read_bytes()
            self.assertNotEqual(changed, Path(snapshot['path']).read_bytes())
            seen.append(changed)
            return original(*args, **kwargs)

        with mock.patch.object(self.mod, '_reserve_build', side_effect=boundary):
            with self.assertRaises(self.mod.ExecutorError) as caught:
                self.build_successor(manifest, run, index)
        self.assertEqual(len(seen), 1, 'must actually reach final reserve boundary')
        self.assertEqual(caught.exception.error_code, 'E_RECOVERY_EVIDENCE')
        self.assertTrue(caught.exception.reason.startswith('recovery_'), caught.exception.reason)
        self.assertEqual([p.read_bytes() for p in self.f.event_paths()], before)
        self.assertEqual(support.file_ref(Path(event['path'])), event)
        self.f.assert_old_unchanged(self)

    def test_root_changes_after_capture_fail_final_live_recheck(self):
        self.inject_at_reserve('root')

    def test_sources_index_changes_after_capture_fail_final_live_recheck(self):
        self.inject_at_reserve('index')

    def test_reserve_requires_each_internal_handoff_input(self):
        _, manifest, run, index = self.prepared()
        self.require_feature()
        original = self.mod._reserve_build
        signature = inspect.signature(original)
        for name in ('recovery_preflight', 'inputs', 'live'):
            self.assertIn(name, signature.parameters,
                          'FEATURE_NOT_IMPLEMENTED_TDD_RED: reserve internal inputs; NOT_JUDGED')
        examined = []

        def boundary(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            for name in ('recovery_preflight', 'inputs', 'live'):
                self.assertIsNotNone(bound.arguments[name], name)
            events = [p.read_bytes() for p in self.f.event_paths()]
            for name in ('recovery_preflight', 'inputs', 'live'):
                with self.subTest(missing=name):
                    trial = signature.bind(*args, **kwargs)
                    trial.apply_defaults()
                    trial.arguments[name] = None
                    with self.assertRaises(self.mod.ExecutorError) as caught:
                        original(*trial.args, **trial.kwargs)
                    self.assertTrue(caught.exception.reason.startswith('recovery_'), caught.exception.reason)
                    self.assertEqual([p.read_bytes() for p in self.f.event_paths()], events)
                    examined.append(name)
            return original(*args, **kwargs)

        with mock.patch.object(self.mod, '_reserve_build', side_effect=boundary):
            self.build_successor(manifest, run, index)
        self.assertEqual(examined, ['recovery_preflight', 'inputs', 'live'])
        self.assertEqual(len(self.f.event_paths()), 3)

    def test_native_build_rejects_required_record_field_removed(self):
        _, manifest, run, index = self.prepared()
        self.build_successor(manifest, run, index)
        record_path = run / 'build-record.json'
        self.mod._native_build(self.f.repo, manifest, record_path, self.mod._Inputs())
        record = json.loads(record_path.read_bytes())
        self.assertIn('recovery_preflight', record)
        del record['recovery_preflight']
        support.write_json(record_path, record)
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.mod._native_build(self.f.repo, manifest, record_path, self.mod._Inputs())
        self.assertIn('build', caught.exception.reason)
        self.assertNotIn('sha', caught.exception.reason)

    def test_published_reservation_repairs_same_record_without_live_capture(self):
        _, manifest, run, index = self.prepared()
        self.require_feature()
        original = self.mod._publish
        intended = []

        class Interrupted(Exception):
            pass

        def before_record(path, raw, allowed, *args, **kwargs):
            if Path(path) == run / 'build-record.json':
                intended.append(raw)
                raise Interrupted()
            return original(path, raw, allowed, *args, **kwargs)

        with mock.patch.object(self.mod, '_publish', side_effect=before_record):
            with self.assertRaises(Interrupted):
                self.build_successor(manifest, run, index)
        self.assertEqual(len(intended), 1)
        self.assertFalse((run / 'build-record.json').exists())
        events = [p.read_bytes() for p in self.f.event_paths()]
        self.assertEqual(len(events), 3)
        self.assertEqual(json.loads(events[-1])['kind'], 'reserve')
        script = (run / 'workflow.js').read_bytes()
        self.f.native_path.unlink()
        index.unlink()
        result = self.mod.build(self.f.repo, manifest, run)
        self.assertIs(result['resume_only'], True)
        self.assertEqual((run / 'build-record.json').read_bytes(), intended[0])
        self.assertEqual((run / 'workflow.js').read_bytes(), script)
        self.assertEqual([p.read_bytes() for p in self.f.event_paths()], events)

    def test_pending_attempt2_own_live_workflow_does_not_reauthorize(self):
        _, manifest, run, index = self.prepared()
        self.build_successor(manifest, run, index)
        record_raw = (run / 'build-record.json').read_bytes()
        record = json.loads(record_raw)
        events = [p.read_bytes() for p in self.f.event_paths()]
        self.f._serial += 2
        request, response = self.f._pair('Workflow', {
            'scriptPath': str(run / 'workflow.js'),
            'args': {'identity': record['identity'], 'manifest_sha256': record['manifest']['sha256']}},
            self.f._serial, 'call_fixture_successor')
        response['toolUseResult'] = {'runId': 'synthetic-successor-live', 'status': 'completed'}
        response['message']['content'][0]['content'] = 'Workflow completed: synthetic-successor-live'
        self.f.rows.extend([request, response])
        self.f._write_native()
        result = self.mod.build(self.f.repo, manifest, run)
        self.assertIs(result['resume_only'], True)
        self.assertEqual((run / 'build-record.json').read_bytes(), record_raw)
        self.assertEqual([p.read_bytes() for p in self.f.event_paths()], events)

    def package_handoff(self, run, change):
        """Re-address each changed artifact; keep reservation/manifest/script intact."""
        record_path = run / 'build-record.json'
        handoff_path = run / 'recovery-preflight.json'
        closure_path = run / 'input-closure.json'
        record = json.loads(record_path.read_bytes())
        handoff = json.loads(handoff_path.read_bytes())
        closure = json.loads(closure_path.read_bytes())
        extras = change(handoff) or []
        raw = support.encode(handoff)
        handoff_path.write_bytes(raw)
        handoff_blob = self.mod._freeze_blob(raw, self.f.scope)
        entries = {entry['origin']: entry for entry in closure['sources']}
        entries[str(handoff_path)] = {'origin': str(handoff_path), 'sha256': support.digest(raw), 'blob': handoff_blob}
        for alias in extras:
            data = alias.read_bytes()
            blob = self.mod._freeze_blob(data, self.f.scope)
            entries[str(alias)] = {'origin': str(alias), 'sha256': support.digest(data), 'blob': blob}
        closure['sources'] = sorted(entries.values(), key=lambda entry: (entry['origin'], entry['sha256']))
        closure_path.write_bytes(support.encode(closure))
        record['input_closure'] = support.file_ref(closure_path)
        record['recovery_preflight'] = support.file_ref(handoff_path)
        record_path.write_bytes(support.encode(record))
        record_ref = self.mod._freeze_blob(record_path.read_bytes(), self.f.scope)
        # Graph build ref retains the genuine origin while its bytes are addressed by digest.
        record_ref = {'path': str(record_path), 'sha256': record_ref['sha256']}
        frozen = self.mod._history_closure(record['input_closure'], record_path, self.f.scope,
                                           raw=closure_path.read_bytes())
        for entry in closure['sources']:
            actual = frozen.read(Path(entry['origin']))
            self.assertEqual(support.digest(actual), entry['sha256'])
            self.assertEqual(support.file_ref(Path(entry['blob']['path'])), entry['blob'])
        self.assertEqual(frozen.read(handoff_path), handoff_path.read_bytes())
        self.assertEqual(support.file_ref(record_path), record_ref)
        self.assertEqual(support.file_ref(closure_path), record['input_closure'])
        self.assertEqual(support.file_ref(handoff_path), record['recovery_preflight'])
        return record_ref, handoff, frozen

    def graph_build(self, record_path):
        ref = self.mod._freeze_blob(record_path.read_bytes(), self.f.scope)
        ref = {'path': str(record_path), 'sha256': ref['sha256']}
        return self.mod._HistoryGraph(self.f.scope).walk(ref, record_path, 'build')

    def handoff_baseline(self, additional=()):
        event = self.recover()
        manifest, run, index = self.f.successor(event, additional)
        self.build_successor(manifest, run, index)
        record_path = run / 'build-record.json'
        self.mod._native_build(self.f.repo, manifest, record_path, self.mod._Inputs())
        self.graph_build(record_path)
        self.mod._replay_history(self.state())
        return manifest, run, index

    def test_integrity_real_result_graph_prepare_collect_check_and_replay(self):
        event = self.recover()
        args, output, _ = self.result(event)
        self.mod._collect_final(*args, check_result=output)
        record_path = args[2]
        self.graph_build(record_path)
        view = self.mod._replay_history(self.state())
        self.assertEqual(len(view['attempts']), 1)
        self.f.assert_old_unchanged(self)

    def test_integrity_hash_consistent_wrong_head_and_successor_rejected(self):
        manifest, run, _ = self.handoff_baseline()
        paths = [run / x for x in ('build-record.json', 'recovery-preflight.json', 'input-closure.json')]
        original = {p: p.read_bytes() for p in paths}
        def wrong_head(value):
            value['prefix_head'] = self.f.binding['reservation']
        def wrong_successor(value):
            value['successor']['identity']['client_round_id'] = 'other-client'
        try:
            for name, mutation in [('head', wrong_head), ('successor', wrong_successor)]:
                with self.subTest(mutation=name):
                    for path, raw in original.items():
                        path.write_bytes(raw)
                    self.package_handoff(run, mutation)
                    for consumer in ('native', 'graph'):
                        with self.subTest(consumer=consumer):
                            with self.assertRaises(self.mod.ExecutorError) as caught:
                                if consumer == 'native':
                                    self.mod._native_build(self.f.repo, manifest, paths[0], self.mod._Inputs())
                                else:
                                    self.graph_build(paths[0])
                            self.assertEqual((caught.exception.error_code, caught.exception.reason),
                                             ('E_RECOVERY_EVIDENCE', 'recovery_handoff_binding'))
        finally:
            for path, raw in original.items():
                path.write_bytes(raw)

    def test_integrity_source_set_and_baseline_recomputed_not_self_reported(self):
        event = self.recover()
        other = self.f.append_workflow(status='success', related=False, new_root=True)
        manifest, run, index = self.f.successor(event, (other,))
        self.build_successor(manifest, run, index)
        record_path = run / 'build-record.json'
        self.mod._native_build(self.f.repo, manifest, record_path, self.mod._Inputs())
        self.graph_build(record_path)
        paths = [record_path, run / 'recovery-preflight.json', run / 'input-closure.json']
        original = {p: p.read_bytes() for p in paths}
        def omit(value):
            value['sources'] = [x for x in value['sources'] if x['original_locator'] != str(other.resolve())]
        def baseline_null(value):
            next(x for x in value['sources'] if x['original_locator'] == str(self.f.native_path.resolve()))['baseline_snapshot'] = None
        def duplicate(value):
            value['sources'].append(copy.deepcopy(value['sources'][0]))
        try:
            for name, mutation in [('omitted_additional', omit), ('baseline_null', baseline_null), ('duplicate', duplicate)]:
                with self.subTest(mutation=name):
                    for path, raw in original.items():
                        path.write_bytes(raw)
                    _, handoff, frozen = self.package_handoff(run, mutation)
                    snapshot = handoff['sources_index']['snapshot']
                    self.assertEqual(frozen.dereference(snapshot, paths[1])[1], index.read_bytes())
                    for consumer in ('native', 'graph'):
                        with self.subTest(consumer=consumer):
                            with self.assertRaises(self.mod.ExecutorError) as caught:
                                if consumer == 'native':
                                    self.mod._native_build(self.f.repo, manifest, record_path, self.mod._Inputs())
                                else:
                                    self.graph_build(record_path)
                            self.assertEqual((caught.exception.error_code, caught.exception.reason),
                                             ('E_RECOVERY_EVIDENCE', 'recovery_handoff_sources_recomputed'))
        finally:
            for path, raw in original.items():
                path.write_bytes(raw)

    def test_integrity_same_bytes_index_snapshot_alias_observation(self):
        manifest, run, index = self.handoff_baseline()
        record_path = run / 'build-record.json'
        alias = run / 'index-snapshot-alias.json'
        original_handoff = json.loads((run / 'recovery-preflight.json').read_bytes())
        original_ref = original_handoff['sources_index']['snapshot']
        self.assertEqual(original_ref['path'], str(self.f.scope / 'blobs' / (original_ref['sha256'] + '.blob')))
        for source in original_handoff['sources']:
            ref = source['snapshot']
            self.assertEqual(ref['path'], str(self.f.scope / 'blobs' / (ref['sha256'] + '.blob')))
        alias.write_bytes(index.read_bytes())
        def change(value):
            value['sources_index']['snapshot'] = support.file_ref(alias)
            return [alias]
        _, handoff, frozen = self.package_handoff(run, change)
        self.assertNotEqual(handoff['sources_index']['snapshot']['path'], original_ref['path'])
        self.assertEqual(frozen.dereference(handoff['sources_index']['snapshot'], record_path)[1], index.read_bytes())
        self.assertEqual(handoff['sources_index']['snapshot']['sha256'], original_ref['sha256'])
        outcomes = []
        for consumer in ('native', 'graph'):
            try:
                if consumer == 'native':
                    self.mod._native_build(self.f.repo, manifest, record_path, self.mod._Inputs())
                else:
                    self.graph_build(record_path)
            except self.mod.ExecutorError as error:
                outcomes.append((consumer, error.error_code, error.reason))
            else:
                outcomes.append((consumer, 'ACCEPTED', 'same_bytes_alias'))
        self.assertEqual(outcomes, [('native', 'E_RECOVERY_EVIDENCE', 'recovery_handoff_snapshot_mapping'),
                                    ('graph', 'E_RECOVERY_EVIDENCE', 'recovery_handoff_snapshot_mapping')],
                         'same-bytes alias changes the specified _freeze_blob FileRef; technical ruling needed')

    def test_integrity_pre_reserve_crash_preserves_old_run_and_retry_attempt2(self):
        _, manifest, run, index = self.prepared()
        before = [p.read_bytes() for p in self.f.event_paths()]
        class Interrupted(Exception):
            pass
        with mock.patch.object(self.mod, '_reserve_build', side_effect=Interrupted):
            with self.assertRaises(Interrupted):
                self.build_successor(manifest, run, index)
        self.assertEqual([p.read_bytes() for p in self.f.event_paths()], before)
        frozen = {p: p.read_bytes() for p in (run / 'workflow.js', run / 'input-closure.json', run / 'recovery-preflight.json')}
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.build_successor(manifest, run, index)
        self.assertEqual((caught.exception.error_code, caught.exception.reason),
                         ('E_OUTPUT_CONFLICT', 'unreserved_existing_output'))
        self.assertEqual({p: p.read_bytes() for p in frozen}, frozen)
        retry = json.loads(manifest.read_bytes())
        retry['client_round_id'] = 'client-retry'
        retry_run = run.with_name(run.name.replace('client-successor', 'client-retry'))
        for kind in ('audit', 'drift', 'disposition'):
            retry['evidence']['post_' + kind + '_index_path'] = str(retry_run / (kind + '-index.json'))
        retry_path = self.f.repo / 'successor-retry-manifest.json'
        support.write_json(retry_path, retry)
        result = self.build_successor(retry_path, retry_run, index)
        self.assertIs(result['resume_only'], False)
        record = json.loads((retry_run / 'build-record.json').read_bytes())
        self.assertEqual((record['attempt_index'], record['identity']['round']), (2, 1))
        self.assertEqual(len(self.f.event_paths()), 3)
        self.assertEqual({p: p.read_bytes() for p in frozen}, frozen)

    def test_integrity_ordinary_record_excludes_recovery_field(self):
        record_path = self.f.build_record_path
        original = record_path.read_bytes()
        record = json.loads(original)
        self.assertNotIn('recovery_preflight', record)
        self.graph_build(record_path)
        self.assertFalse(self.mod._recovery_build_schema(record, record_path, self.mod._Inputs()))
        try:
            for name, value in [('null', None), ('fileref', self.f.binding['reservation'])]:
                with self.subTest(value=name):
                    record['recovery_preflight'] = value
                    record_path.write_bytes(support.encode(record))
                    with self.assertRaises(self.mod.ExecutorError) as caught:
                        self.graph_build(record_path)
                    self.assertEqual((caught.exception.error_code, caught.exception.reason),
                                     ('E_POLICY_SOURCE', 'build_record_keys'))
        finally:
            record_path.write_bytes(original)

    def test_integrity_committed_attempt2_next_round_does_not_recheck_old_live_gate(self):
        event = self.recover()
        args, output, result = self.result(event)
        self.mod._collect_final(*args, check_result=output)
        record = json.loads(args[2].read_bytes())
        self.f._serial += 2
        request, response = self.f._pair('Workflow', {
            'scriptPath': record['workflow_script']['path'],
            'args': {'identity': record['identity'], 'manifest_sha256': record['manifest']['sha256']}},
            self.f._serial, 'call_fixture_committed_successor')
        response['toolUseResult'] = {'runId': 'synthetic-successor-live', 'status': 'completed'}
        response['message']['content'][0]['content'] = 'Workflow completed: synthetic-successor-live'
        self.f.rows.extend([request, response])
        self.f._write_native()
        view = self.mod._replay_history(self.state())
        self.mod._require_dispatch_policy(view)
        self.assertTrue(view['resource_view']['next_round_dispatch_allowed'])
        self.assertEqual(result['attempt_index'], 2)
        manifest = json.loads(args[1].read_bytes())
        manifest.update(round=2, attempt_index=3, client_round_id='client-next')
        run = args[2].parent.with_name('post_planning-R2-client-next-protocol-fixture-aggregated')
        manifest['evidence'].update(cycle_origin=self.f.binding['genesis'], previous_round=support.file_ref(output),
            post_audit_index_path=str(run / 'audit-index.json'),
            post_drift_index_path=str(run / 'drift-index.json'),
            post_disposition_index_path=str(run / 'disposition-index.json'))
        manifest_path = self.f.repo / 'next-round-manifest.json'
        support.write_json(manifest_path, manifest)
        before = [p.read_bytes() for p in self.f.event_paths()]
        result_next = self.mod.build(self.f.repo, manifest_path, run)
        self.assertIs(result_next['resume_only'], False)
        next_record = json.loads((run / 'build-record.json').read_bytes())
        self.assertEqual((next_record['attempt_index'], next_record['identity']['round']), (3, 2))
        self.assertNotIn('recovery_preflight', next_record)
        self.assertEqual([p.read_bytes() for p in self.f.event_paths()][:len(before)], before)
        self.assertEqual(len(self.f.event_paths()), len(before) + 1)


class FrozenHandoffFilesystemTests(_history._FrozenFilesystemCase):
    def test_pending_attempt2_native_graph_replay_and_resume_ignore_archived_originals(self):
        """The first reserve is already sealed; no fresh live authorization is needed."""
        event, _ = self.healthy_seq2()
        manifest, run = self.successor(event)
        build_path = run / 'build-record.json'
        build_ref = support.file_ref(build_path)
        # Graph build nodes consume a captured blob, not the merely published
        # pending record. Match graph_build's existing package precondition.
        self.assertEqual(self.mod._freeze_blob(build_path.read_bytes(), self.f.scope)['sha256'],
                         build_ref['sha256'])
        state = self.state()
        consumers = [
            ('native_build', lambda: self.mod._native_build(self.f.repo, manifest, build_path, self.mod._Inputs())),
            ('build_graph', lambda: self.mod._HistoryGraph(self.f.scope).walk(build_ref, build_path, 'build')),
            ('pending_replay', lambda: self.mod._replay_history(state)),
            ('frozen_resume', lambda: self.mod.build(self.f.repo, manifest, run))]
        for label, consume in consumers:
            value = self.accepts_frozen('healthy_' + label, consume)
            if label == 'frozen_resume':
                self.assertIs(value['resume_only'], True)
        self.assertEqual(len(self.f.event_paths()), 3)
        self.frozen_roots = [self.f.scope, run]
        for role, path, parent in [*self.archive_inputs(),
                ('handoff_sources_index', self.f.repo / 'recovery-sources.json', False)]:
            with self.archived_source(path, parent=parent):
                for label, consume in consumers:
                    with self.subTest(role=role, consumer=label):
                        value = self.accepts_frozen(label, consume)
                        if label == 'frozen_resume':
                            self.assertIs(value['resume_only'], True)
                        self.assertEqual(len(self.f.event_paths()), 3)

    def test_first_successor_live_handoff_rejects_symlinked_new_native_file_and_parent(self):
        """Use an additional healthy root so frozen seq2 cannot mask the live gate."""
        event, _ = self.healthy_seq2()
        f = self.f
        session = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
        root = f.config_root / 'projects' / 'separate-live-root' / (session + '.jsonl')
        root.parent.mkdir()
        row = f._root('user', 701, [{'type': 'text', 'text': 'Unrelated healthy native root'}], session=session)
        root.write_bytes(support.encode(row) + b'\n')
        manifest, run, index = f.successor(event, additional_sources=(root,))
        value = json.loads(manifest.read_bytes())
        state = self.state()
        view = self.mod._replay_history(state)
        frozen = self.mod._FrozenInputs(dict(view['frozen_raw']))
        manifest_ref = support.file_ref(manifest)
        script = self.mod._workflow(value, manifest_ref['sha256'])
        script_ref = {'path': str(run / 'workflow.js'), 'sha256': support.digest(script)}
        # Real capture is a read-only positive control, not a published reserve.
        self.mod._capture_recovery_handoff(f.repo, state, value, manifest_ref, script_ref, index, frozen)
        self.note_boundary({'consumer': 'healthy_first_live_capture_separate_root', 'outcome': 'GREEN'})
        for parent in (False, True):
            with self.archived_source(root, parent=parent):
                with self.subTest(parent=parent):
                    with self.assertRaises(self.mod.ExecutorError) as caught:
                        self.mod.build(f.repo, manifest, run, recovery_sources=index)
                    self.assertEqual((caught.exception.error_code, caught.exception.reason),
                                     ('E_RECOVERY_EVIDENCE', 'native_namespace'))
                    self.assertEqual(caught.exception.input_ref, str(root))
                    self.assertFalse(run.exists())
                    self.assertEqual(len(f.event_paths()), 2)


if __name__ == '__main__':
    unittest.main()
