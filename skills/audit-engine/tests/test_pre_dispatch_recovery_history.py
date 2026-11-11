"""TASK-009: real recovery prefix consumed by history and result paths.

No Workflow is invoked. The native export is synthetic but uses the same
producer shape as ResultIntegrityTests.capture in test_audit_executor.py.
"""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import inspect
import json
import os
from pathlib import Path
from typing import Any
import unittest
from unittest import mock

_spec = importlib.util.spec_from_file_location(
    'history_fixture_support', Path(__file__).with_name('pre_dispatch_recovery_fixtures.py'))
assert _spec is not None and _spec.loader is not None
support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(support)


class RecoveryHistory(unittest.TestCase):
    def setUp(self):
        self.f = support.RecoveryFixture()
        self.addCleanup(self.f.close)
        env = mock.patch.dict(os.environ, self.f.environment, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.mod = support.load_module(self.f.executor)
        profile = mock.patch.object(self.mod, '_RUNTIME_REJECTION_PROFILES', self.f.runtime_profiles)
        profile.start()
        self.addCleanup(profile.stop)

    def recover(self):
        f = self.f
        return self.mod.recover_dispatch_rejection(
            repo_path=f.repo, manifest_path=f.manifest_path, build_record_path=f.build_record_path,
            native_record_path=f.native_path, tool_use_id='call_fixture_rejection',
            operator_index=f.operator_index, evidence_acceptance_index=f.acceptance_index,
            check_only=False, additional_sources=())['event']

    def succeeds(self, description, fn):
        try:
            return fn()
        except self.mod.ExecutorError as exc:
            self.fail(f'{description} must accept valid recovery history: {exc.error_code}/{exc.reason}')

    def state(self):
        return self.succeeds('load scope', lambda: self.mod._load_scope(
            self.f.scope, self.f.manifest, self.mod._Inputs()))

    def successor(self, event):
        f = self.f
        manifest, run, index = f.successor(event)
        kwargs = {'repo_path': f.repo, 'manifest_path': manifest, 'output_dir': run}
        if 'recovery_sources' in inspect.signature(self.mod.build).parameters:
            kwargs['recovery_sources'] = index
        self.succeeds('successor build', lambda: self.mod.build(**kwargs))
        return manifest, run

    def capture(self, manifest, run):
        build = json.loads((run / 'build-record.json').read_bytes())
        run_id = 'synthetic-successor'
        nodes, seats = [], []
        for i, role in enumerate(build['roles']):
            report = {'vote': 'PASS', 'coverage_complete': True, 'findings': [], 'pending': [], 'prior_findings': []}
            nodes.append({'type': 'workflow_agent', 'agentId': run_id + '-' + str(i),
                'agentType': role['agentType'], 'label': role['label'], 'model': 'synthetic',
                'queuedAt': 1000 + i * 100, 'startedAt': 1000 + i * 100,
                'durationMs': 10, 'state': 'done'})
            seats.append({**{k: role[k] for k in ('index', 'role_id', 'agentType', 'label')},
                'attempted': True, 'settled': True, 'raw': support.encode(report).decode(), 'error': None})
        native = {'runId': run_id, 'startTime': 1000, 'durationMs': 300020,
            'status': 'completed', 'agentCount': len(nodes), 'script': (run / 'workflow.js').read_text(),
            'args': {'identity': build['identity'], 'manifest_sha256': build['manifest']['sha256']},
            'workflowProgress': nodes, 'result': {'schema_version': 1, 'identity': build['identity'],
                'manifest_sha256': build['manifest']['sha256'], 'results': seats,
                'control': {'round_timer_ms': 300000, 'stop_observed': False, 'return_reason': 'all_settled'}}}
        path = run / 'native.json'
        support.write_json(path, native)
        support.write_json(run / 'audit-index.json', {'schema_version': 1, 'identity': build['identity'],
            'attempt_index': build['attempt_index'], 'workflow_run_id': run_id,
            'native_record': support.file_ref(path), 'termination_refs': []})
        return build, run_id, path

    def result(self, event):
        f, mod = self.f, self.mod
        manifest, run = self.successor(event)
        build, run_id, native = self.capture(manifest, run)
        self.assertEqual(build['attempt_index'], 2)
        self.assertEqual(build['identity']['round'], 1)
        self.assertEqual(build['identity']['client_round_id'], 'client-successor')
        self.assertEqual(build['genesis'], f.binding['genesis'])
        self.assertEqual(build['prefix_head'], event)
        reservation = json.loads(Path(build['reservation']['path']).read_bytes())['payload']
        self.assertIsNone(reservation['previous_round'])
        self.assertIsNone(reservation['previous_attempt'])
        self.assertEqual(build['sources'], f.current_sources)
        self.succeeds('native build', lambda: mod._native_build(f.repo, manifest, run / 'build-record.json', mod._Inputs()))
        output = run / (run.name + '.json')
        args = (f.repo, manifest, run / 'build-record.json', run_id, native, output)
        self.succeeds('prepare', lambda: mod._prepare_policy(*args))
        self.succeeds('collect', lambda: mod._collect_final(*args))
        result = json.loads(output.read_bytes())
        self.assertEqual(result['inputs']['prefix_head'], event)
        self.assertEqual(result['inputs']['genesis'], f.binding['genesis'])
        self.assertEqual(result['attempt_index'], 2)
        final_ref = result['inputs']['input_closure']
        final = mod._history_closure(final_ref, output, f.scope, raw=Path(final_ref['path']).read_bytes())
        def read_ref(reader, ref):
            raw = reader.read(Path(ref['path']))
            self.assertEqual(support.digest(raw), ref['sha256'])
            return raw
        # The result package must capture the structural prefix, while separate
        # historical closures carry the two versions of identical logical paths.
        for ref in (f.binding['genesis'], f.binding['reservation'], event):
            self.assertEqual(read_ref(final, ref), Path(ref['path']).read_bytes())
        prefix = json.loads(read_ref(final, event))
        recovery = prefix['payload']
        def nested(ref):
            return mod._history_closure(ref, output, f.scope, raw=read_ref(final, ref))
        evidence_inputs = nested(recovery['input_closure'])
        record = json.loads(read_ref(evidence_inputs, recovery['evidence']))
        for name in ('operator_statement', 'evidence_acceptance', 'runtime_rejection_basis'):
            read_ref(evidence_inputs, record[name])
        old = nested(f.old_closure)
        new = nested(recovery['source_transition']['new_source_closure'])
        genesis = json.loads(read_ref(final, f.binding['genesis']))
        for name in f.old_sources:
            path = Path(f.old_sources[name]['path'])
            old_bytes, new_bytes = old.read(path), new.read(path)
            self.assertEqual(support.digest(old_bytes), f.old_sources[name]['sha256'])
            self.assertEqual(support.digest(new_bytes), f.current_sources[name]['sha256'])
            self.assertEqual(old_bytes, read_ref(final, genesis['initial_sources'][name]))
        return args, output, result

    def test_fixture_health_real_event_and_two_source_closures(self):
        f = self.f
        event_ref = self.recover()
        self.assertEqual(support.file_ref(Path(event_ref['path'])), event_ref)
        event = json.loads(Path(event_ref['path']).read_bytes())
        self.assertEqual((event['seq'], event['kind']), (2, 'dispatch_rejected'))
        self.assertEqual(event['previous_event'], f.binding['reservation'])
        transition = event['payload']['source_transition']
        self.assertEqual(transition['from_sources'], f.old_sources)
        self.assertEqual(transition['to_sources'], f.current_sources)
        def closure(ref):
            return self.mod._history_closure(ref, Path(event_ref['path']), f.scope,
                                             raw=Path(ref['path']).read_bytes())
        old = closure(f.old_closure)
        new = closure(transition['new_source_closure'])
        evidence = closure(event['payload']['input_closure'])
        genesis = json.loads(Path(f.binding['genesis']['path']).read_bytes())
        for name in f.old_sources:
            with self.subTest(source=name):
                path = Path(f.old_sources[name]['path'])
                self.assertEqual(support.digest(old.read(path)), f.old_sources[name]['sha256'])
                self.assertEqual(support.digest(new.read(path)), f.current_sources[name]['sha256'])
                self.assertEqual(old.read(path), Path(genesis['initial_sources'][name]['path']).read_bytes())
        record = json.loads(evidence.read(Path(event['payload']['evidence']['path'])))
        for key in ('operator_statement', 'evidence_acceptance', 'runtime_rejection_basis'):
            raw = evidence.read(Path(record[key]['path']))
            self.assertEqual(support.digest(raw), record[key]['sha256'])
        f.assert_old_unchanged(self)

    def semantic_package(self, original, mutation):
        """Republish changed derived nodes and their capture, without touching origins.

        This is fixture construction, not an implementation of recovery or replay.
        The unchanged native/UI/static leaves remain the independent authority.
        """
        f, mod = self.f, self.mod
        event_path = Path(original['path'])
        event = json.loads(event_path.read_bytes())
        payload = event['payload']
        closure_ref = payload['input_closure']
        closure = json.loads(Path(closure_ref['path']).read_bytes())
        frozen = mod._history_closure(closure_ref, event_path, f.scope,
                                      raw=Path(closure_ref['path']).read_bytes())
        evidence = json.loads(frozen.read(Path(payload['evidence']['path'])))
        field = 'operator_statement' if mutation == 'operator' else 'runtime_rejection_basis'
        value = json.loads(frozen.read(Path(evidence[field]['path'])))
        if mutation == 'operator':
            self.assertEqual(value['sourceData']['transfer_state'], 'not_authorized_or_transferred')
            value['sourceData']['transfer_state'] = 'transferred'
        elif mutation == 'basis':
            self.assertEqual(value['windows'], f.static_windows)
            value['windows'][0]['end'] += 1
        else:
            raise AssertionError(mutation)
        def blob(obj):
            raw = support.encode(obj)
            path = f.scope / 'blobs' / (support.digest(raw) + '.blob')
            if path.exists():
                self.assertEqual(path.read_bytes(), raw)
            else:
                path.write_bytes(raw)
            return support.file_ref(path), raw
        node_ref, node_raw = blob(value)
        evidence[field] = node_ref
        evidence_ref, evidence_raw = blob(evidence)
        entries = {row['origin']: row for row in closure['sources']}
        for ref, raw in ((node_ref, node_raw), (evidence_ref, evidence_raw)):
            self.assertEqual(support.digest(raw), ref['sha256'])
            entries[ref['path']] = {'origin': ref['path'], 'sha256': ref['sha256'], 'blob': ref}
        closure['sources'] = sorted(entries.values(), key=lambda x: (x['origin'], x['sha256']))
        new_closure, _ = blob(closure)
        payload['evidence'] = evidence_ref
        payload['input_closure'] = new_closure
        return support.write_json(event_path, event), value

    def assert_semantic_package_health(self, event_ref, mutation, changed, original_evidence):
        f, mod = self.f, self.mod
        event_path = Path(event_ref['path'])
        self.assertEqual(support.file_ref(event_path), event_ref)
        event = json.loads(event_path.read_bytes())
        payload = event['payload']
        closure_ref = payload['input_closure']
        self.assertEqual(support.file_ref(Path(closure_ref['path'])), closure_ref)
        raw = Path(closure_ref['path']).read_bytes()
        frozen = mod._history_closure(closure_ref, event_path, f.scope, raw=raw)
        closure = json.loads(raw)
        # Independently verify every mapping and actual blob in the capture.
        for entry in closure['sources']:
            data = frozen.read(Path(entry['origin']))
            self.assertEqual(support.digest(data), entry['sha256'])
            self.assertEqual(support.file_ref(Path(entry['blob']['path'])), entry['blob'])
            self.assertEqual(Path(entry['blob']['path']).read_bytes(), data)
        def deref(ref):
            data = frozen.read(Path(ref['path']))
            self.assertEqual(support.digest(data), ref['sha256'], ref['path'])
            return data
        evidence = json.loads(deref(payload['evidence']))
        key = 'operator_statement' if mutation == 'operator' else 'runtime_rejection_basis'
        self.assertEqual(json.loads(deref(evidence[key])), changed)
        self.assertNotEqual(evidence[key], original_evidence[key])
        original_value = json.loads(deref(original_evidence[key]))
        expected = copy.deepcopy(original_value)
        if mutation == 'operator':
            expected['sourceData']['transfer_state'] = 'transferred'
        else:
            expected['windows'][0]['end'] += 1
        self.assertEqual(changed, expected)
        def check_refs(value):
            if isinstance(value, dict):
                if set(value) == {'path', 'sha256'}:
                    deref(value)
                else:
                    for child in value.values():
                        check_refs(child)
            elif isinstance(value, list):
                for child in value:
                    check_refs(child)
        check_refs(evidence)
        for field in ('operator_statement', 'evidence_acceptance', 'runtime_rejection_basis'):
            check_refs(json.loads(deref(evidence[field])))
        # The other derived record, real UI snapshot and static source bytes
        # remain byte-identical; the contradictory field is the only semantic edit.
        other = 'runtime_rejection_basis' if mutation == 'operator' else 'operator_statement'
        self.assertEqual(evidence[other], original_evidence[other])
        self.assertEqual(evidence['evidence_acceptance'], original_evidence['evidence_acceptance'])
        self.assertEqual(evidence['source'], original_evidence['source'])
        self.assertEqual(deref(evidence['source']['snapshot']), f.native_path.read_bytes())
        basis = json.loads(deref(evidence['runtime_rejection_basis']))
        for name in ('capacity_source', 'loader_source'):
            ref = basis[name]
            self.assertEqual(deref(ref), Path(ref['path']).read_bytes())
        # Verify exact UI binding, including its separate snapshot and target.
        for name in ('operator_statement', 'evidence_acceptance'):
            authority = json.loads(deref(evidence[name]))['sourceData']
            self.assertEqual(deref(authority['source']['snapshot']), f.native_path.read_bytes())
            self.assertEqual(authority['target'], f.binding)
        if mutation == 'operator':
            self.assertEqual(changed['sourceData']['transfer_state'], 'transferred')
        else:
            self.assertEqual(changed['windows'][0]['end'], f.static_windows[0]['end'] + 1)
            self.assertEqual(changed['windows'][0]['sha256'], f.static_windows[0]['sha256'])

    def test_semantic_mutant_package_health_independent_of_history_loader(self):
        original = self.recover()
        path = Path(original['path'])
        raw = path.read_bytes()
        event = json.loads(raw)
        captured = self.mod._history_closure(event['payload']['input_closure'], path, self.f.scope,
                                              raw=Path(event['payload']['input_closure']['path']).read_bytes())
        evidence = json.loads(captured.read(Path(event['payload']['evidence']['path'])))
        for mutation in ('operator', 'basis'):
            with self.subTest(mutation=mutation):
                path.write_bytes(raw)
                ref, value = self.semantic_package(original, mutation)
                self.assert_semantic_package_health(ref, mutation, value, evidence)
        path.write_bytes(raw)
        self.f.assert_old_unchanged(self)

    def test_graph_rejects_hash_consistent_semantic_mutants(self):
        original = self.recover()
        path = Path(original['path'])
        raw = path.read_bytes()
        event = json.loads(raw)
        frozen = self.mod._history_closure(event['payload']['input_closure'], path, self.f.scope,
                                            raw=Path(event['payload']['input_closure']['path']).read_bytes())
        evidence = json.loads(frozen.read(Path(event['payload']['evidence']['path'])))
        def walk(ref):
            return self.mod._HistoryGraph(self.f.scope).walk(ref, Path(ref['path']), 'event')
        self.succeeds('semantic graph baseline', lambda: walk(original))
        for mutation in ('operator', 'basis'):
            with self.subTest(mutation=mutation):
                path.write_bytes(raw)
                ref, value = self.semantic_package(original, mutation)
                self.assert_semantic_package_health(ref, mutation, value, evidence)
                with self.assertRaises(self.mod.ExecutorError) as caught:
                    walk(ref)
                # These are expected semantic families, not existing global
                # reason-string contracts for the not-yet-written consumer.
                self.assertIn(caught.exception.error_code, ('E_RECOVERY_EVIDENCE', 'E_POLICY_SOURCE', 'E_PREVIOUS_IDENTITY'))
                prefixes = ('operator_', 'authority_', 'recovery_operator_') if mutation == 'operator' else (
                    'basis_', 'runtime_', 'static_', 'recovery_basis_')
                self.assertTrue(caught.exception.reason.startswith(prefixes), caught.exception.reason)
        path.write_bytes(raw)

    def test_scope_and_replay_rejection_is_not_attempt_or_budget(self):
        event = self.recover()
        state = self.state()
        self.assertEqual(state['head'], event)
        self.assertIsNone(state['pending'])
        self.assertEqual(state['reserve_count'], 1)
        replay = self.succeeds('replay', lambda: self.mod._replay_history(state))
        self.assertEqual(replay['attempts'], [])
        self.assertEqual(replay['rounds'], [])
        self.assertEqual((replay['charged_rounds'], replay['effective_limit'], replay['remaining_rounds']), (0, 5, 5))
        self.assertIsNone(replay['latest_round'])
        self.assertIsNone(replay['latest_attempt'])

    def test_graph_walk_checks_both_generations_and_recovery_evidence(self):
        f, mod = self.f, self.mod
        event_ref = self.recover()
        event_path = Path(event_ref['path'])
        event = json.loads(event_path.read_bytes())
        def walk(ref):
            return mod._HistoryGraph(f.scope).walk(ref, Path(ref['path']), 'event')
        self.succeeds('history graph baseline', lambda: walk(event_ref))
        # Each hash corruption changes one frozen content-addressed leaf, not a live input.
        payload = event['payload']
        frozen = mod._history_closure(payload['input_closure'], event_path, f.scope,
                                      raw=Path(payload['input_closure']['path']).read_bytes())
        evidence = json.loads(frozen.read(Path(payload['evidence']['path'])))
        basis = json.loads(frozen.read(Path(evidence['runtime_rejection_basis']['path'])))
        refs = [payload['evidence'], payload['input_closure'],
                payload['source_transition']['new_source_closure'],
                evidence['operator_statement'], evidence['evidence_acceptance'],
                evidence['runtime_rejection_basis'], basis['capacity_source'], basis['loader_source'],
                evidence['source']['snapshot']]
        genesis = json.loads(Path(f.binding['genesis']['path']).read_bytes())
        refs += [genesis['initial_sources']['executor']]
        new_source = payload['source_transition']['to_sources']['executor']
        refs.append(new_source)
        for ref in refs:
            with self.subTest(frozen=ref['path']):
                blob = f.scope / 'blobs' / (ref['sha256'] + '.blob')
                if not blob.exists():
                    blob = Path(ref['path'])
                raw = blob.read_bytes()
                try:
                    blob.write_bytes(raw + b' ')
                    with self.assertRaises(mod.ExecutorError) as caught:
                        walk(event_ref)
                    self.assertIn(caught.exception.error_code, ('E_POLICY_SOURCE', 'E_RECOVERY_EVIDENCE'))
                    self.assertIn(caught.exception.reason, ('history_source_hash', 'history_blob_hash', 'history_closure_hash', 'source_hash_mismatch'))
                finally:
                    blob.write_bytes(raw)
        # The event's own hash is recomputed: this tests source identity rather
        # than an incidental outer hash mismatch.
        raw = event_path.read_bytes()
        try:
            event['payload']['source_transition']['from_sources']['executor']['path'] = str(f.repo / 'wrong-executor.py')
            altered_ref = support.write_json(event_path, event)
            with self.assertRaises(mod.ExecutorError) as caught:
                walk(altered_ref)
            self.assertIn(caught.exception.error_code, ('E_POLICY_SOURCE', 'E_PREVIOUS_IDENTITY', 'E_SOURCE_DRIFT', 'E_RECOVERY_EVIDENCE'))
            self.assertTrue(caught.exception.reason.startswith(('history_', 'source_', 'recovery_', 'transition_', 'fixed_')), caught.exception.reason)
        finally:
            event_path.write_bytes(raw)

    def test_successor_build_and_result_consumers(self):
        event = self.recover()
        args, output, _ = self.result(event)
        self.succeeds('check', lambda: self.mod._collect_final(*args, check_result=output))
        self.f.assert_old_unchanged(self)

    def test_result_check_and_replay_survive_removed_live_evidence(self):
        f, mod = self.f, self.mod
        event = self.recover()
        args, output, _ = self.result(event)
        for path in (f.native_path, f.operator_index, f.acceptance_index, f.target_path,
                     f.repo / 'static-fixture' / 'capacity.json', f.repo / 'static-fixture' / 'loader.json'):
            path.unlink()
        before = support.tree_snapshot(f.root)
        self.succeeds('offline result check', lambda: mod._collect_final(*args, check_result=output))
        state = self.state()
        view = self.succeeds('offline replay', lambda: mod._replay_history(state))
        self.assertEqual(len(view['attempts']), 1)
        self.assertEqual(support.tree_snapshot(f.root), before)

    def test_rejected_build_cannot_be_collected_as_a_run(self):
        f, mod = self.f, self.mod
        self.recover()
        self.state()  # Do not count an unrecognized event as a caught collect rejection.
        _, run_id, native = self.capture(f.manifest_path, f.run_dir)
        output = f.run_dir / (f.run_dir.name + '.json')
        with self.assertRaises(mod.ExecutorError) as caught:
            mod._collect_final(f.repo, f.manifest_path, f.build_record_path,
                               run_id, native, output)
        self.assertEqual(caught.exception.error_code, 'E_PREVIOUS_IDENTITY')
        self.assertTrue(caught.exception.reason.startswith(('rejected_', 'reservation_', 'pending_', 'collect_')), caught.exception.reason)
        self.assertFalse(output.exists())

    def test_ordinary_unrecovered_scope_still_rejects_source_drift(self):
        f, mod = self.f, self.mod
        # Use the short successor manifest so capacity validation does not hide
        # the drift gate; the scope is still the ordinary, pending old reserve.
        manifest, run, _ = f.successor(f.binding['reservation'])
        with self.assertRaises(mod.ExecutorError) as caught:
            mod.build(f.repo, manifest, run)
        self.assertEqual((caught.exception.error_code, caught.exception.reason),
                         ('E_SOURCE_DRIFT', 'active_cycle_fixed_source_changed'))
        self.assertEqual(len(f.event_paths()), 1)

    def review_blob(self, raw):
        path = self.f.scope / 'blobs' / (support.digest(raw) + '.blob')
        if path.exists():
            self.assertEqual(path.read_bytes(), raw)
        else:
            path.write_bytes(raw)
        return support.file_ref(path)

    def review_baseline(self):
        ref = self.recover()
        path = Path(ref['path'])
        raw = path.read_bytes()
        self.succeeds('review graph baseline', lambda: self.mod._HistoryGraph(self.f.scope).walk(ref, path, 'event'))
        state = self.state()
        self.assertEqual(state['head'], ref)
        self.assertIsNone(state['pending'])
        self.assertEqual(state['active_sources'], self.f.current_sources)
        event = json.loads(raw)
        payload = event['payload']
        transition = payload['source_transition']
        main = self.mod._history_closure(payload['input_closure'], path, self.f.scope)
        current = self.mod._history_closure(transition['new_source_closure'], path, self.f.scope)
        for source in [transition['compatibility_manifest'], *transition['to_sources'].values()]:
            origin = Path(source['path'])
            self.assertEqual(main.read(origin), current.read(origin))
            self.assertEqual(support.digest(current.read(origin)), source['sha256'])
        return ref, raw

    def review_mutant(self, original, raw, kind):
        """Rebuild only the chosen capture and event, preserving the other capture."""
        f, mod = self.f, self.mod
        path = Path(original['path'])
        event = json.loads(raw)
        payload = event['payload']
        transition = payload['source_transition']
        main_ref = payload['input_closure']
        main_raw = Path(main_ref['path']).read_bytes()
        main = mod._history_closure(main_ref, path, f.scope, raw=main_raw)
        new_ref = transition['new_source_closure']
        new_raw = Path(new_ref['path']).read_bytes()
        new_closure = json.loads(new_raw)
        catalog_ref = transition['compatibility_manifest']
        original_catalog = main.read(Path(catalog_ref['path']))
        original_evidence = json.loads(main.read(Path(payload['evidence']['path'])))
        original_known = original_evidence['known_binding_sources']
        if kind in ('executor', 'contract'):
            origin = transition['to_sources'][kind]['path']
            actual = main.read(Path(origin))
            self.assertEqual(support.digest(actual), transition['to_sources'][kind]['sha256'])
            replacement = b'synthetic alternate generation for ' + kind.encode() + b'\n'
            self.assertNotEqual(replacement, actual)
            source_blob = self.review_blob(replacement)
            catalog = json.loads(original_catalog)
            catalog['to'][kind] = source_blob['sha256']
            catalog_blob = self.review_blob(support.encode(catalog))
            for name, ref in ((origin, source_blob), (catalog_ref['path'], catalog_blob)):
                rows = [row for row in new_closure['sources'] if row['origin'] == name]
                self.assertEqual(len(rows), 1)
                rows[0].update(sha256=ref['sha256'], blob=ref)
            transition['to_sources'][kind]['sha256'] = source_blob['sha256']
            transition['compatibility_manifest']['sha256'] = catalog_blob['sha256']
        elif kind == 'catalog_path':
            rows = [row for row in new_closure['sources'] if row['origin'] == catalog_ref['path']]
            self.assertEqual(len(rows), 1)
            wrong = str(f.repo / 'arbitrary-catalog.json')
            rows[0]['origin'] = wrong
            transition['compatibility_manifest']['path'] = wrong
        elif kind in ('known_empty', 'known_missing', 'known_extra', 'additional_null'):
            evidence = copy.deepcopy(original_evidence)
            if kind == 'known_empty':
                evidence['known_binding_sources'] = []
            elif kind == 'known_missing':
                evidence['known_binding_sources'] = [r for r in original_known if r['path'] != str(f.manifest_path)]
                self.assertEqual(len(evidence['known_binding_sources']), len(original_known) - 1)
            elif kind == 'known_extra':
                extra = evidence['operator_statement']
                self.assertNotIn(extra, original_known)
                evidence['known_binding_sources'] = sorted([*original_known, extra], key=lambda r: (r['path'], r['sha256']))
            else:
                evidence['additional_sources'] = None
            evidence_ref = self.review_blob(support.encode(evidence))
            closure = json.loads(main_raw)
            closure['sources'].append({'origin': evidence_ref['path'], 'sha256': evidence_ref['sha256'], 'blob': evidence_ref})
            closure['sources'].sort(key=lambda r: (r['origin'], r['sha256']))
            payload['evidence'] = evidence_ref
            payload['input_closure'] = self.review_blob(support.encode(closure))
        else:
            raise AssertionError(kind)
        if kind in ('executor', 'contract', 'catalog_path'):
            new_closure['sources'].sort(key=lambda r: (r['origin'], r['sha256']))
            new_capture_ref = self.review_blob(support.encode(new_closure))
            transition['new_source_closure'] = new_capture_ref
            # The changed closure itself remains captured by the main package.
            # Only its source bytes disagree with the unchanged same-time inputs;
            # a missing-envelope check must not masquerade as source binding.
            closure = json.loads(main_raw)
            captured = [entry for entry in closure['sources'] if entry['origin'] == new_ref['path']]
            self.assertEqual(len(captured), 1)
            captured[0].update(origin=new_capture_ref['path'], sha256=new_capture_ref['sha256'],
                               blob=new_capture_ref)
            closure['sources'].sort(key=lambda r: (r['origin'], r['sha256']))
            payload['input_closure'] = self.review_blob(support.encode(closure))
        ref = support.write_json(path, event)
        return ref

    def review_health(self, ref, raw, kind):
        f, mod = self.f, self.mod
        path = Path(ref['path'])
        self.assertEqual(support.file_ref(path), ref)
        original = json.loads(raw)
        event = json.loads(path.read_bytes())
        payload, old_payload = event['payload'], original['payload']
        transition, old_transition = payload['source_transition'], old_payload['source_transition']
        def closure(reference):
            self.assertEqual(support.file_ref(Path(reference['path'])), reference)
            return mod._history_closure(reference, path, f.scope, raw=Path(reference['path']).read_bytes())
        main, current = closure(payload['input_closure']), closure(transition['new_source_closure'])
        previous = closure(f.old_closure)
        genesis = json.loads(Path(f.binding['genesis']['path']).read_bytes())
        self.assertEqual(transition['from_sources'], f.old_sources)
        for name in f.old_sources:
            logical = Path(f.old_sources[name]['path'])
            old_bytes = previous.read(logical)
            self.assertEqual(support.digest(old_bytes), f.old_sources[name]['sha256'])
            self.assertEqual(old_bytes, Path(genesis['initial_sources'][name]['path']).read_bytes())
            self.assertEqual(support.digest(current.read(logical)), transition['to_sources'][name]['sha256'])
        catalog_ref = transition['compatibility_manifest']
        catalog_raw = current.read(Path(catalog_ref['path']))
        self.assertEqual(support.digest(catalog_raw), catalog_ref['sha256'])
        catalog = json.loads(catalog_raw)
        for name in ('executor', 'contract'):
            self.assertEqual(catalog['to'][name], transition['to_sources'][name]['sha256'])
        original_main = closure(old_payload['input_closure'])
        evidence = json.loads(main.read(Path(payload['evidence']['path'])))
        known = evidence['known_binding_sources']
        self.assertEqual(known, sorted(known, key=lambda r: (r['path'], r['sha256'])))
        self.assertEqual(len(known), len({(r['path'], r['sha256']) for r in known}))
        for item in known:
            self.assertEqual(support.digest(main.read(Path(item['path']))), item['sha256'])
        if kind in ('executor', 'contract', 'catalog_path'):
            new_capture = transition['new_source_closure']
            self.assertEqual(main.read(Path(new_capture['path'])), Path(new_capture['path']).read_bytes())
            self.assertNotEqual(payload['input_closure'], old_payload['input_closure'])
        if kind in ('executor', 'contract'):
            self.assertEqual(main.read(Path(old_transition['compatibility_manifest']['path'])),
                             original_main.read(Path(old_transition['compatibility_manifest']['path'])))
            logical = Path(transition['to_sources'][kind]['path'])
            self.assertEqual(main.read(logical), original_main.read(logical))
            self.assertNotEqual(main.read(logical), current.read(logical))
            self.assertNotEqual(main.read(Path(old_transition['compatibility_manifest']['path'])), catalog_raw)
        elif kind == 'catalog_path':
            self.assertEqual(main.read(Path(old_transition['compatibility_manifest']['path'])),
                             original_main.read(Path(old_transition['compatibility_manifest']['path'])))
            self.assertNotEqual(catalog_ref['path'], old_transition['compatibility_manifest']['path'])
            self.assertEqual(catalog_raw, original_main.read(Path(old_transition['compatibility_manifest']['path'])))
        else:
            self.assertEqual(transition, old_transition)
            old_evidence = json.loads(original_main.read(Path(old_payload['evidence']['path'])))
            old_known = old_evidence['known_binding_sources']
            if kind == 'known_empty':
                self.assertGreater(len(old_known), 1)
                self.assertEqual(known, [])
            elif kind == 'known_missing':
                self.assertEqual(len(known), len(old_known) - 1)
                self.assertIn(support.file_ref(f.manifest_path), old_known)
                self.assertNotIn(support.file_ref(f.manifest_path), known)
            elif kind == 'known_extra':
                self.assertEqual(len(known), len(old_known) + 1)
                self.assertIn(evidence['operator_statement'], known)
            else:
                self.assertIsNone(evidence['additional_sources'])

    def review_refused(self, consumer, ref, kind):
        try:
            if consumer == 'graph':
                self.mod._HistoryGraph(self.f.scope).walk(ref, Path(ref['path']), 'event')
            else:
                result = self.mod._load_scope(self.f.scope, self.f.manifest, self.mod._Inputs())
                active = result.get('active_sources', {})
                self.fail(f'{consumer} accepted {kind}; active_sources_differ_from_original={active != self.f.current_sources}')
        except self.mod.ExecutorError as exc:
            self.assertIn(exc.error_code, ('E_POLICY_SOURCE', 'E_SOURCE_DRIFT', 'E_RECOVERY_EVIDENCE', 'E_PREVIOUS_IDENTITY'))
            self.assertTrue(exc.reason.startswith(('history_', 'source_', 'recovery_', 'catalog_', 'compatibility_', 'binding_', 'known_', 'fixed_')), exc.reason)
            return
        except AssertionError:
            raise
        except Exception as exc:
            self.fail(f'{consumer} raised unexpected {type(exc).__name__} for {kind}: {exc}')
        self.fail(f'{consumer} accepted {kind}')

    def test_review_capture_health_all_mutations(self):
        original, raw = self.review_baseline()
        path = Path(original['path'])
        for kind in ('executor', 'contract', 'catalog_path', 'known_empty', 'known_missing', 'known_extra', 'additional_null'):
            with self.subTest(kind=kind):
                path.write_bytes(raw)
                ref = self.review_mutant(original, raw, kind)
                self.review_health(ref, raw, kind)
        path.write_bytes(raw)
        self.f.assert_old_unchanged(self)

    def test_review_generation_pair_cross_capture_binding(self):
        original, raw = self.review_baseline()
        path = Path(original['path'])
        for kind in ('executor', 'contract'):
            for consumer in ('graph', 'scope'):
                with self.subTest(kind=kind, consumer=consumer):
                    path.write_bytes(raw)
                    ref = self.review_mutant(original, raw, kind)
                    self.review_health(ref, raw, kind)
                    self.review_refused(consumer, ref, kind)

    def test_review_catalog_fixed_logical_path(self):
        original, raw = self.review_baseline()
        path = Path(original['path'])
        for consumer in ('graph', 'scope'):
            with self.subTest(consumer=consumer):
                path.write_bytes(raw)
                ref = self.review_mutant(original, raw, 'catalog_path')
                self.review_health(ref, raw, 'catalog_path')
                self.review_refused(consumer, ref, 'catalog_path')

    def test_review_known_sources_exact_membership(self):
        original, raw = self.review_baseline()
        path = Path(original['path'])
        for kind in ('known_empty', 'known_missing', 'known_extra'):
            for consumer in ('graph', 'scope'):
                with self.subTest(kind=kind, consumer=consumer):
                    path.write_bytes(raw)
                    ref = self.review_mutant(original, raw, kind)
                    self.review_health(ref, raw, kind)
                    self.review_refused(consumer, ref, kind)

    def test_review_additional_sources_null_control(self):
        original, raw = self.review_baseline()
        path = Path(original['path'])
        for consumer in ('graph', 'scope'):
            with self.subTest(consumer=consumer):
                path.write_bytes(raw)
                ref = self.review_mutant(original, raw, 'additional_null')
                self.review_health(ref, raw, 'additional_null')
                self.review_refused(consumer, ref, 'additional_null')


class AuthorityIndexCollision(unittest.TestCase):
    """Unrelated captured JSON must not acquire an authority-index role."""

    @contextlib.contextmanager
    def scenario(self):
        fixture = RecoveryHistory('test_fixture_health_real_event_and_two_source_closures')
        fixture.setUp()
        try:
            yield fixture
        finally:
            fixture.doCleanups()

    def install_collision(self, x, authority, shape):
        f = x.f
        original_rows = copy.deepcopy(f.rows[:6])
        operator_raw = f.operator_index.read_bytes()
        acceptance_raw = f.acceptance_index.read_bytes()
        selected = f.operator_index if authority == 'operator' else f.acceptance_index
        adapter = support.OPERATOR_ADAPTER if authority == 'operator' else support.ACCEPTANCE_ADAPTER
        candidate = f.root / ('unrelated-' + authority + '-' + shape + '.json')
        data = support.encode({'adapter': adapter}) if shape == 'marker' else selected.read_bytes()
        candidate.write_bytes(data)
        f.append_workflow(status='success', related=False)
        request = f.rows[-2]['message']['content'][0]['input']
        request['scriptPath'] = str(candidate)
        f._write_native()
        self.assertEqual(f.rows[:6], original_rows)
        self.assertEqual(f.operator_index.read_bytes(), operator_raw)
        self.assertEqual(f.acceptance_index.read_bytes(), acceptance_raw)
        self.assertNotEqual(candidate, selected)
        self.assertEqual(candidate.read_bytes(), data)
        if shape == 'copy':
            self.assertEqual(data, selected.read_bytes())
            self.assertEqual(json.loads(data), json.loads(selected.read_bytes()))
        else:
            self.assertEqual(json.loads(data), {'adapter': adapter})
        self.assertNotEqual(candidate, f.script_path)
        self.assertNotEqual(support.digest(data), f.binding['script']['sha256'])
        self.assertNotEqual(request['args']['manifest_sha256'], f.binding['manifest']['sha256'])
        actual_identity = request['args']['identity']
        for field in ('audit_cycle_id', 'client_round_id', 'change_id', 'checkpoint', 'candidate_sha', 'round'):
            self.assertNotEqual(actual_identity[field], f.record['identity'][field], field)
        self.assertEqual(len(f.event_paths()), 1)
        return candidate, data, selected

    def publish_and_health(self, x, candidate, data, selected):
        f, mod = x.f, x.mod
        def check_only():
            return mod.recover_dispatch_rejection(
                repo_path=f.repo, manifest_path=f.manifest_path, build_record_path=f.build_record_path,
                native_record_path=f.native_path, tool_use_id='call_fixture_rejection',
                operator_index=f.operator_index, evidence_acceptance_index=f.acceptance_index,
                check_only=True, additional_sources=())
        self.assertTrue(x.succeeds('collision check-only', check_only)['eligible'])
        ref = x.succeeds('collision recovery publication', x.recover)
        event_path = Path(ref['path'])
        self.assertEqual(support.file_ref(event_path), ref)
        event = json.loads(event_path.read_bytes())
        self.assertEqual((event['seq'], event['kind']), (2, 'dispatch_rejected'))
        self.assertEqual(event['previous_event'], f.binding['reservation'])
        self.assertEqual(len(f.event_paths()), 2)
        payload = event['payload']
        transition = payload['source_transition']
        main_ref, new_ref = payload['input_closure'], transition['new_source_closure']
        for closure_ref in (main_ref, new_ref):
            self.assertEqual(support.file_ref(Path(closure_ref['path'])), closure_ref)
        main = mod._history_closure(main_ref, event_path, f.scope)
        current = mod._history_closure(new_ref, event_path, f.scope)
        self.assertEqual(main.read(Path(new_ref['path'])), Path(new_ref['path']).read_bytes())
        self.assertEqual(main.read(candidate), data)
        self.assertEqual(current.read(candidate), data)
        self.assertEqual(main.read(selected), selected.read_bytes())
        for source in (transition['compatibility_manifest'], *transition['to_sources'].values()):
            origin = Path(source['path'])
            self.assertEqual(main.read(origin), current.read(origin))
            self.assertEqual(support.digest(main.read(origin)), source['sha256'])
        self.assertEqual(transition['from_sources'], f.old_sources)
        self.assertEqual(transition['to_sources'], f.current_sources)
        evidence = json.loads(main.read(Path(payload['evidence']['path'])))
        snapshot = evidence['source']['snapshot']
        self.assertEqual(main.read(Path(snapshot['path'])), f.native_path.read_bytes())
        self.assertEqual(support.digest(main.read(Path(snapshot['path']))), snapshot['sha256'])
        for field, index, parser, decision in (
            ('operator_statement', f.operator_index, mod._parse_operator_recovery_statement, 'confirm_local_domain'),
            ('evidence_acceptance', f.acceptance_index, mod._parse_evidence_acceptance, 'accept_boundary'),
        ):
            authority_ref = evidence[field]
            authority_bytes = main.read(Path(authority_ref['path']))
            self.assertEqual(support.digest(authority_bytes), authority_ref['sha256'])
            frozen_value = json.loads(authority_bytes)['sourceData']
            parsed = x.succeeds('selected authority live parse', lambda: parser(f.repo, f.binding, index))
            self.assertEqual(frozen_value['target'], f.binding)
            self.assertEqual(frozen_value['decision'], decision)
            self.assertEqual(parsed['sourceData']['decision'], decision)
            self.assertEqual(main.read(index), index.read_bytes())
        f.assert_old_unchanged(self)
        return ref

    def consume_collision(self, x, authority, shape):
        f, mod = x.f, x.mod
        candidate, data, selected = self.install_collision(x, authority, shape)
        ref = self.publish_and_health(x, candidate, data, selected)
        def graph():
            return mod._HistoryGraph(f.scope).walk(ref, Path(ref['path']), 'event')
        def load():
            return mod._load_scope(f.scope, f.manifest, mod._Inputs())
        # Each consumer runs independently, so a graph failure cannot hide load
        # or the real successor build. The downstream result path is separate.
        for stage, operation in (('graph', graph), ('load', load),
                                 ('successor build', lambda: x.successor(ref))):
            with self.subTest(authority=authority, shape=shape, stage=stage):
                x.succeeds('collision ' + stage, operation)
        candidate.unlink()
        self.assertFalse(candidate.exists())
        with self.subTest(authority=authority, shape=shape, stage='offline load'):
            x.succeeds('collision offline load', load)
        with self.subTest(authority=authority, shape=shape, stage='offline result'):
            args, output, _ = x.result(ref)
            before = support.tree_snapshot(f.root)
            x.succeeds('collision offline check', lambda: mod._collect_final(*args, check_result=output))
            self.assertEqual(support.tree_snapshot(f.root), before)

    def test_collision_fixture_health_is_independent_of_history_consumer(self):
        for authority in ('operator', 'acceptance'):
            for shape in ('marker', 'copy'):
                with self.subTest(authority=authority, shape=shape), self.scenario() as x:
                    candidate, data, selected = self.install_collision(x, authority, shape)
                    self.publish_and_health(x, candidate, data, selected)

    def test_collision_marker_authorities_remain_replayable(self):
        for authority in ('operator', 'acceptance'):
            with self.scenario() as x:
                self.consume_collision(x, authority, 'marker')

    def test_collision_complete_authority_index_copies_remain_replayable(self):
        for authority in ('operator', 'acceptance'):
            with self.scenario() as x:
                self.consume_collision(x, authority, 'copy')

    def test_collision_selected_declined_authority_is_still_refused(self):
        for authority in ('operator', 'acceptance'):
            with self.subTest(authority=authority), self.scenario() as x:
                f = x.f
                self.install_collision(x, authority, 'marker')
                f.choose(authority, 1)
                before = support.tree_snapshot(f.root)
                with self.assertRaises(x.mod.ExecutorError) as caught:
                    x.recover()
                self.assertEqual(caught.exception.error_code, 'E_RECOVERY_EVIDENCE')
                prefix = 'operator_' if authority == 'operator' else 'evidence_acceptance_'
                self.assertTrue(caught.exception.reason.startswith(prefix), caught.exception.reason)
                self.assertEqual(support.tree_snapshot(f.root), before)
                self.assertEqual(len(f.event_paths()), 1)


class AuthorityProvenance(unittest.TestCase):
    @contextlib.contextmanager
    def scenario(self, collision=False):
        x = RecoveryHistory('test_fixture_health_real_event_and_two_source_closures')
        x.setUp()
        try:
            candidate = None
            if collision:
                helper = AuthorityIndexCollision('test_collision_fixture_health_is_independent_of_history_consumer')
                candidate, _, _ = helper.install_collision(x, 'operator', 'marker')
            yield x, candidate
        finally:
            x.doCleanups()

    def mutant(self, x, original, raw, kind, candidate):
        f, mod = x.f, x.mod
        event = json.loads(raw)
        payload = event['payload']
        transition = payload['source_transition']
        carrier = Path(original['path'])
        old_new_ref = transition['new_source_closure']
        current = mod._history_closure(old_new_ref, carrier, f.scope)
        observation_path = f.scope / 'recovery-read-observations.json'
        observation = json.loads(current.read(observation_path))
        roles = observation['authority_indexes']
        self.assertEqual(roles, {'operator_statement': support.file_ref(f.operator_index),
                                 'evidence_acceptance': support.file_ref(f.acceptance_index)})
        if kind == 'swapped':
            roles['operator_statement'], roles['evidence_acceptance'] = roles['evidence_acceptance'], roles['operator_statement']
        elif kind == 'missing':
            del roles['evidence_acceptance']
        elif kind == 'bad_hash':
            roles['operator_statement']['sha256'] = '0' * 64
        elif kind == 'marker':
            roles['operator_statement'] = support.file_ref(candidate)
        elif kind == 'other_role':
            roles['operator_statement'] = copy.deepcopy(roles['evidence_acceptance'])
        elif kind == 'acceptance_marker':
            roles['evidence_acceptance'] = support.file_ref(candidate)
        elif kind == 'acceptance_other':
            roles['evidence_acceptance'] = copy.deepcopy(roles['operator_statement'])
        else:
            raise AssertionError(kind)
        obs_raw = support.encode(observation)
        obs_blob = x.review_blob(obs_raw)
        new_closure = json.loads(Path(old_new_ref['path']).read_bytes())
        main_closure = json.loads(Path(payload['input_closure']['path']).read_bytes())
        def replace(closure, origin, replacement):
            rows = [row for row in closure['sources'] if row['origin'] == str(origin)]
            self.assertEqual(len(rows), 1)
            rows[0].update(sha256=replacement['sha256'], blob=replacement)
        replace(new_closure, observation_path, obs_blob)
        replace(main_closure, observation_path, obs_blob)
        new_ref = x.review_blob(support.encode(new_closure))
        matching = [row for row in main_closure['sources'] if row['origin'] == old_new_ref['path']]
        self.assertEqual(len(matching), 1)
        matching[0].update(origin=new_ref['path'], sha256=new_ref['sha256'], blob=new_ref)
        main_closure['sources'].sort(key=lambda r: (r['origin'], r['sha256']))
        payload['input_closure'] = x.review_blob(support.encode(main_closure))
        transition['new_source_closure'] = new_ref
        return support.write_json(carrier, event), observation

    def health(self, x, original, raw, ref, observation, kind, candidate):
        f, mod = x.f, x.mod
        carrier = Path(ref['path'])
        self.assertEqual(support.file_ref(carrier), ref)
        event = json.loads(carrier.read_bytes())
        original_event = json.loads(raw)
        payload = event['payload']
        new_ref = payload['source_transition']['new_source_closure']
        for closure_ref in (payload['input_closure'], new_ref):
            self.assertEqual(support.file_ref(Path(closure_ref['path'])), closure_ref)
        main = mod._history_closure(payload['input_closure'], carrier, f.scope)
        current = mod._history_closure(new_ref, carrier, f.scope)
        observation_path = f.scope / 'recovery-read-observations.json'
        obs_raw = support.encode(observation)
        self.assertEqual(main.read(observation_path), obs_raw)
        self.assertEqual(current.read(observation_path), obs_raw)
        self.assertEqual(main.read(Path(new_ref['path'])), Path(new_ref['path']).read_bytes())
        for source in [payload['source_transition']['compatibility_manifest'],
                       *payload['source_transition']['to_sources'].values()]:
            path = Path(source['path'])
            self.assertEqual(main.read(path), current.read(path))
            self.assertEqual(support.digest(main.read(path)), source['sha256'])
        original_main = mod._history_closure(original_event['payload']['input_closure'], carrier, f.scope)
        evidence_ref = payload['evidence']
        self.assertEqual(evidence_ref, original_event['payload']['evidence'])
        evidence_raw = main.read(Path(evidence_ref['path']))
        self.assertEqual(support.digest(evidence_raw), evidence_ref['sha256'])
        evidence = json.loads(evidence_raw)
        self.assertNotIn(str(observation_path), [r['path'] for r in evidence['known_binding_sources']])
        for item in evidence['known_binding_sources']:
            self.assertEqual(support.digest(main.read(Path(item['path']))), item['sha256'])
        for path in (f.operator_index, f.acceptance_index, candidate, f.native_path):
            self.assertEqual(main.read(path), current.read(path))
            self.assertEqual(main.read(path), original_main.read(path))
        roles = observation['authority_indexes']
        for role, role_ref in roles.items():
            actual = current.read(Path(role_ref['path']))
            self.assertEqual(main.read(Path(role_ref['path'])), actual)
            if kind == 'bad_hash' and role == 'operator_statement':
                self.assertNotEqual(support.digest(actual), role_ref['sha256'])
            else:
                self.assertEqual(support.digest(actual), role_ref['sha256'])
        if kind == 'marker':
            self.assertEqual(roles['operator_statement'], support.file_ref(candidate))
        if kind == 'other_role':
            self.assertEqual(roles['operator_statement'], support.file_ref(f.acceptance_index))
        if kind == 'acceptance_marker':
            self.assertEqual(roles['evidence_acceptance'], support.file_ref(candidate))
        if kind == 'acceptance_other':
            self.assertEqual(roles['evidence_acceptance'], support.file_ref(f.operator_index))
        if kind == 'missing':
            self.assertEqual(set(roles), {'operator_statement'})
        f.assert_old_unchanged(self)

    def test_provenance_mutant_closures_are_independently_healthy(self):
        with self.scenario(collision=True) as (x, candidate):
            original, raw = x.review_baseline()
            for kind in ('swapped', 'missing', 'bad_hash', 'marker', 'other_role', 'acceptance_marker', 'acceptance_other'):
                with self.subTest(kind=kind):
                    Path(original['path']).write_bytes(raw)
                    ref, observation = self.mutant(x, original, raw, kind, candidate)
                    self.health(x, original, raw, ref, observation, kind, candidate)

    def test_provenance_bad_roles_are_refused_after_healthy_baseline(self):
        with self.scenario(collision=True) as (x, candidate):
            original, raw = x.review_baseline()
            for kind in ('swapped', 'missing', 'bad_hash', 'marker', 'other_role', 'acceptance_marker', 'acceptance_other'):
                for consumer in ('graph', 'scope'):
                    with self.subTest(kind=kind, consumer=consumer):
                        Path(original['path']).write_bytes(raw)
                        ref, observation = self.mutant(x, original, raw, kind, candidate)
                        self.health(x, original, raw, ref, observation, kind, candidate)
                        try:
                            if consumer == 'graph':
                                x.mod._HistoryGraph(x.f.scope).walk(ref, Path(ref['path']), 'event')
                            else:
                                x.mod._load_scope(x.f.scope, x.f.manifest, x.mod._Inputs())
                        except x.mod.ExecutorError as exc:
                            self.assertIn(exc.error_code, ('E_POLICY_SOURCE', 'E_RECOVERY_EVIDENCE', 'E_NATIVE_EVIDENCE'))
                            expected = {'missing': ('history_recovery_authority_roles',),
                                        'bad_hash': ('source_hash_mismatch',),
                                        'swapped': ('operator_', 'authority_', 'history_recovery_authority_'),
                                        'marker': ('operator_', 'authority_', 'history_recovery_authority_'),
                                        'other_role': ('operator_', 'authority_', 'history_recovery_authority_'),
                                        'acceptance_marker': ('evidence_acceptance_', 'authority_', 'history_recovery_authority_'),
                                        'acceptance_other': ('evidence_acceptance_', 'authority_', 'history_recovery_authority_')}
                            self.assertTrue(exc.reason.startswith(expected[kind]), (kind, exc.error_code, exc.reason))
                            print(f'provenance kind={kind} consumer={consumer} refused={exc.error_code}/{exc.reason}')
                        except Exception as exc:
                            self.fail(f'{consumer} unexpected {type(exc).__name__} for {kind}: {exc}')
                        else:
                            self.fail(f'{consumer} wrongly accepted provenance mutation {kind}')

    def test_proof_failure_before_publish_keeps_seq1_and_originals(self):
        with self.scenario() as (x, _):
            f, mod = x.f, x.mod
            eligible = mod.recover_dispatch_rejection(
                repo_path=f.repo, manifest_path=f.manifest_path, build_record_path=f.build_record_path,
                native_record_path=f.native_path, tool_use_id='call_fixture_rejection',
                operator_index=f.operator_index, evidence_acceptance_index=f.acceptance_index,
                check_only=True, additional_sources=())
            self.assertTrue(eligible['eligible'])
            self.assertEqual(len(f.event_paths()), 1)
            def files_without_blobs():
                return {str(p): p.read_bytes() for p in f.root.rglob('*')
                        if p.is_file() and not p.is_relative_to(f.scope / 'blobs') and not p.name.endswith('.lock')}
            before = files_without_blobs()
            real_verify = mod._verify_recovery_event
            verified = []
            def inject(event, reference, scope):
                if event.get('kind') == 'dispatch_rejected' and event.get('seq') == 2:
                    self.assertEqual(Path(reference['path']), f.scope / 'events' / '0000000002.json')
                    self.assertFalse(Path(reference['path']).exists())
                    self.assertEqual(reference['sha256'], support.digest(support.encode(event)))
                    proof = real_verify(event, reference, scope)
                    self.assertEqual(proof['active_sources'], f.current_sources)
                    self.assertFalse(Path(reference['path']).exists())
                    verified.append(reference)
                    raise mod.ExecutorError('E_POLICY_SOURCE', 'injected_prepublication_proof', str(scope))
                return real_verify(event, reference, scope)
            with mock.patch.object(mod, '_verify_recovery_event', side_effect=inject):
                with self.assertRaises(mod.ExecutorError) as caught:
                    x.recover()
            self.assertEqual((caught.exception.error_code, caught.exception.reason),
                             ('E_POLICY_SOURCE', 'injected_prepublication_proof'))
            self.assertEqual(len(verified), 1)
            self.assertEqual(len(f.event_paths()), 1)
            self.assertFalse((f.scope / 'events' / '0000000002.json').exists())
            self.assertEqual(files_without_blobs(), before)
            f.assert_old_unchanged(self)


class _FrozenFilesystemCase(unittest.TestCase):
    """R2-SEAM-001: real archive operations, never mocked filesystem answers.

    The shared protocol factory is unchanged. These helpers only arrange/archive
    originals and measure consumers; they do not reconstruct or repair packages.
    """
    f: Any
    mod: Any
    setUp = RecoveryHistory.setUp
    recover = RecoveryHistory.recover
    succeeds = RecoveryHistory.succeeds
    state = RecoveryHistory.state
    successor = RecoveryHistory.successor
    capture = RecoveryHistory.capture
    result = RecoveryHistory.result

    def note_boundary(self, value):
        if not hasattr(self, 'boundary_observations'):
            self.boundary_observations = []
        self.boundary_observations.append(value)

    def sealed_tree(self):
        # Published ledger/blobs plus any successor run, not mutable originals.
        return {str(path): support.tree_snapshot(path)
                for path in getattr(self, 'frozen_roots', [self.f.scope])}

    @contextlib.contextmanager
    def archived_source(self, original, *, parent=False):
        """Move an original, leave a byte-identical symlink, then restore it.

        Parent cases are restricted to native/static input directories; never
        relocate the repo/scope or the published run closure/build-record tree.
        """
        original = Path(original)
        moved = original.parent if parent else original
        if parent:
            self.assertTrue(moved.is_relative_to(self.f.config_root / 'projects') or
                            moved == self.f.repo / 'static-fixture')
        self.assertFalse(moved.is_symlink())
        before_raw = original.read_bytes()
        sealed = self.sealed_tree()
        archive = self.f.root / 'source-archive'
        archive.mkdir(exist_ok=True)
        destination = archive / moved.name
        self.assertFalse(destination.exists())
        before_tree = support.tree_snapshot(moved) if parent else {
            moved.name: (moved.lstat().st_mode, moved.lstat().st_mtime_ns, support.digest(before_raw))}
        moved.rename(destination)
        moved.symlink_to(destination, target_is_directory=parent)
        try:
            self.assertTrue(moved.is_symlink())
            self.assertEqual(original.read_bytes(), before_raw)
            self.assertEqual(self.sealed_tree(), sealed)
            self.note_boundary({'operation': 'rename_then_symlink', 'original': str(original),
                'moved': str(moved), 'archive': str(destination), 'parent': parent,
                'before_tree': before_tree, 'link_target': str(moved.readlink()),
                'original_sha256': support.digest(before_raw), 'sealed_before': sealed})
            yield
        finally:
            try:
                after = self.sealed_tree()
                self.note_boundary({'operation': 'after_consumers', 'original': str(original),
                    'parent': parent, 'original_sha256': support.digest(original.read_bytes()),
                    'sealed_after': after, 'sealed_unchanged': after == sealed})
                self.assertEqual(original.read_bytes(), before_raw)
                self.assertEqual(after, sealed, 'archive or consumer changed frozen events/blobs/closure')
            finally:
                moved.unlink()
                destination.rename(moved)

    def accepts_frozen(self, label, consume):
        try:
            value = consume()
        except self.mod.ExecutorError as exc:
            self.note_boundary({'consumer': label, 'outcome': 'RED',
                'error_code': exc.error_code, 'reason': exc.reason, 'input_ref': exc.input_ref})
            self.fail(f'{label}: frozen history must ignore archived live originals; '
                      f'got {exc.error_code}/{exc.reason} at {exc.input_ref}')
        self.note_boundary({'consumer': label, 'outcome': 'GREEN'})
        return value

    def healthy_seq2(self):
        event = self.recover()
        state = self.state()
        self.assertIsNone(state['pending'])
        view = self.mod._replay_history(state)
        self.assertEqual((view['attempts'], view['charged_rounds']), ([], 0))
        self.assertEqual(len(self.f.event_paths()), 2)
        self.note_boundary({'consumer': 'healthy_seq2_load_and_replay', 'outcome': 'GREEN'})
        return event, state

    def frozen_runtime(self, event):
        value = json.loads(Path(event['path']).read_bytes())
        ref = value['payload']['source_transition']['new_source_closure']
        frozen = self.mod._history_closure(ref, Path(event['path']), self.f.scope)
        observation = json.loads(frozen.read(self.f.scope / 'recovery-read-observations.json'))
        return self.mod._RecoveryFrozenInputs(dict(frozen.raw), str(self.f.config_root),
                                              set(observation['unreadable_scripts']))

    def authority(self, acceptance, inputs):
        parser = self.mod._parse_evidence_acceptance if acceptance else self.mod._parse_operator_recovery_statement
        index = self.f.acceptance_index if acceptance else self.f.operator_index
        return parser(self.f.repo, self.f.binding, index, inputs=inputs)

    def archive_inputs(self):
        f = self.f
        # No removal of published input-closure/build-record, or fixed sources.
        return [('rejection_native', f.native_path, False),
                ('native_parent', f.native_path, True),
                ('old_manifest', f.manifest_path, False),
                ('old_script', f.script_path, False),
                ('static_capacity', f.repo / 'static-fixture/capacity.json', False),
                ('static_loader', f.repo / 'static-fixture/loader.json', False),
                ('static_parent', f.repo / 'static-fixture/capacity.json', True),
                ('authority_target_locator', f.target_path, False),
                ('operator_index', f.operator_index, False),
                ('acceptance_index', f.acceptance_index, False)]


class FrozenRecoveryFilesystemTests(_FrozenFilesystemCase):
    def test_seq2_scope_and_replay_ignore_archived_native_file_and_parent(self):
        """A sealed seq2 cannot depend on present native/ancestor lstat state."""
        event, state = self.healthy_seq2()
        value = json.loads(Path(event['path']).read_bytes())
        for parent in (False, True):
            with self.archived_source(self.f.native_path, parent=parent):
                consumers = [('proof', lambda: self.mod._verify_recovery_event(value, event, self.f.scope)),
                    ('load_scope', lambda: self.mod._load_scope(self.f.scope, self.f.manifest, self.mod._Inputs())),
                    ('replay_preloaded_state', lambda: self.mod._replay_history(state))]
                for label, consume in consumers:
                    with self.subTest(parent=parent, consumer=label):
                        self.accepts_frozen(label, consume)

    def test_frozen_authority_native_ignores_archived_file_and_parent(self):
        """Reach both authority native branches without rejection's earlier check."""
        event, _ = self.healthy_seq2()
        expected = {kind: self.authority(kind, self.frozen_runtime(event)) for kind in (False, True)}
        for parent in (False, True):
            with self.archived_source(self.f.native_path, parent=parent):
                for acceptance in (False, True):
                    with self.subTest(parent=parent, acceptance=acceptance):
                        value = self.accepts_frozen('authority_native', lambda: self.authority(
                            acceptance, self.frozen_runtime(event)))
                        self.assertEqual(value, expected[acceptance])

    def test_frozen_authority_bound_manifest_and_script_ignore_archival(self):
        """Reach target lstat directly; full proof meets rejection safe_path first."""
        event, _ = self.healthy_seq2()
        expected = {kind: self.authority(kind, self.frozen_runtime(event)) for kind in (False, True)}
        for path in (self.f.manifest_path, self.f.script_path):
            with self.archived_source(path):
                for acceptance in (False, True):
                    with self.subTest(original=path.name, acceptance=acceptance):
                        value = self.accepts_frozen('authority_target_binding', lambda: self.authority(
                            acceptance, self.frozen_runtime(event)))
                        self.assertEqual(value, expected[acceptance])

    def test_seq2_rejection_ignores_archived_manifest_script_and_static_basis(self):
        """safe_path also guards manifest/script and both static-basis inputs."""
        event, state = self.healthy_seq2()
        value = json.loads(Path(event['path']).read_bytes())
        for role, path, parent in self.archive_inputs()[2:7]:
            with self.archived_source(path, parent=parent):
                for label, consume in (
                    ('proof', lambda: self.mod._verify_recovery_event(value, event, self.f.scope)),
                    ('load_scope', lambda: self.mod._load_scope(self.f.scope, self.f.manifest, self.mod._Inputs())),
                    ('replay_preloaded_state', lambda: self.mod._replay_history(state))):
                    with self.subTest(role=role, consumer=label):
                        self.accepts_frozen(label, consume)

    def test_frozen_authority_locator_and_indexes_remain_valid_after_archival(self):
        """Locator/index reads already use Frozen bytes: control against blanket fixes."""
        event, state = self.healthy_seq2()
        for role, path, parent in self.archive_inputs()[7:]:
            with self.archived_source(path, parent=parent):
                with self.subTest(role=role):
                    self.accepts_frozen('load_scope', lambda: self.mod._load_scope(
                        self.f.scope, self.f.manifest, self.mod._Inputs()))
                    self.assertEqual(self.accepts_frozen('replay_preloaded_state', lambda:
                        self.mod._replay_history(state))['attempts'], [])
                    for acceptance in (False, True):
                        self.accepts_frozen('authority_locator_index', lambda: self.authority(
                            acceptance, self.frozen_runtime(event)))

    def test_committed_check_and_replay_ignore_archived_recovery_originals(self):
        """Real prepare/collect/check is healthy before only old sources are moved."""
        event, _ = self.healthy_seq2()
        args, output, result = self.result(event)
        self.mod._collect_final(*args, check_result=output)
        state = self.state()
        self.assertEqual(len(self.mod._replay_history(state)['attempts']), 1)
        self.assertEqual(result['attempt_index'], 2)
        self.frozen_roots = [self.f.scope, args[2].parent]
        self.note_boundary({'consumer': 'healthy_native_prepare_collect_check_replay', 'outcome': 'GREEN'})
        for role, path, parent in [*self.archive_inputs(),
                ('handoff_sources_index', self.f.repo / 'recovery-sources.json', False)]:
            with self.archived_source(path, parent=parent):
                for label, consume in (
                    ('offline_check', lambda: self.mod._collect_final(*args, check_result=output)),
                    ('committed_replay', lambda: self.mod._replay_history(state))):
                    with self.subTest(role=role, consumer=label):
                        self.accepts_frozen(label, consume)

    def test_frozen_parsers_still_reject_invalid_recorded_native_namespace(self):
        """Ignoring present lstat must not waive the recorded namespace identity."""
        event, _ = self.healthy_seq2()
        before = self.sealed_tree()
        outside = self.f.repo / self.f.native_path.name
        runtime = self.frozen_runtime(event)
        runtime.raw[str(outside)] = runtime.raw[str(self.f.native_path)]
        with self.subTest(parser='rejection'):
            with self.assertRaises(self.mod.ExecutorError) as caught:
                self.mod._parse_recovery_rejection(self.f.repo, self.f.manifest, self.f.record,
                    outside, 'call_fixture_rejection', inputs=runtime)
            self.assertEqual((caught.exception.error_code, caught.exception.reason),
                             ('E_RECOVERY_EVIDENCE', 'native_namespace'))
        for acceptance in (False, True):
            runtime = self.frozen_runtime(event)
            index_path = self.f.acceptance_index if acceptance else self.f.operator_index
            # Arrange invalid bytes before a separate read view starts; do not
            # mutate an origin already consumed by that view's stability trace.
            raw = dict(runtime.raw)
            index = json.loads(raw[str(index_path)])
            for field in ('question', 'response'):
                index[field]['path'] = str(outside)
            raw[str(index_path)] = support.encode(index)
            raw[str(outside)] = raw[str(self.f.native_path)]
            runtime = self.mod._RecoveryFrozenInputs(
                raw, runtime.runtime_config_root, set(runtime.unreadable_scripts))
            with self.subTest(parser='authority', acceptance=acceptance):
                with self.assertRaises(self.mod.ExecutorError) as caught:
                    self.authority(acceptance, runtime)
                self.assertEqual((caught.exception.error_code, caught.exception.reason),
                                 ('E_RECOVERY_EVIDENCE', 'native_namespace'))
        self.assertEqual(self.sealed_tree(), before)

    def test_first_live_recovery_check_only_and_mutation_reject_symlinked_native(self):
        """Fixing Frozen must not permit symlinks on either first live CLI lane."""
        f = self.f
        def recover(check_only):
            return self.mod.recover_dispatch_rejection(f.repo, f.manifest_path,
                f.build_record_path, f.native_path, 'call_fixture_rejection', f.operator_index,
                f.acceptance_index, check_only=check_only)
        self.assertIs(recover(True)['eligible'], True)
        for parent in (False, True):
            with self.archived_source(f.native_path, parent=parent):
                for check_only in (True, False):
                    with self.subTest(parent=parent, check_only=check_only):
                        with self.assertRaises(self.mod.ExecutorError) as caught:
                            recover(check_only)
                        self.assertEqual((caught.exception.error_code, caught.exception.reason),
                                         ('E_RECOVERY_EVIDENCE', 'native_namespace'))
                        self.assertEqual(len(f.event_paths()), 1)

    def test_live_parsers_still_reject_symlinked_native_binding_and_static_inputs(self):
        """Real live readers remain strict at every confirmed parser seam."""
        f = self.f
        def rejection():
            return self.mod._parse_recovery_rejection(f.repo, f.manifest, f.record,
                f.native_path, 'call_fixture_rejection', inputs=self.mod._Inputs())
        rejection()
        for acceptance in (False, True):
            self.authority(acceptance, self.mod._Inputs())
        for role, path, parent in self.archive_inputs()[:7]:
            with self.archived_source(path, parent=parent):
                with self.subTest(role=role, parser='rejection'):
                    with self.assertRaises(self.mod.ExecutorError) as caught:
                        rejection()
                    self.assertEqual((caught.exception.error_code, caught.exception.reason),
                        ('E_RECOVERY_EVIDENCE', 'runtime_symlink' if role.startswith('static_') else 'native_symlink'))
                if not role.startswith('static_'):
                    for acceptance in (False, True):
                        with self.subTest(role=role, parser='authority', acceptance=acceptance):
                            with self.assertRaises(self.mod.ExecutorError) as caught:
                                self.authority(acceptance, self.mod._Inputs())
                            self.assertEqual((caught.exception.error_code, caught.exception.reason),
                                ('E_RECOVERY_EVIDENCE', 'native_namespace' if role in
                                 ('rejection_native', 'native_parent') else 'target_path'))


if __name__ == '__main__':
    unittest.main()
