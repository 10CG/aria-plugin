"""TASK-010 RED: replay, live evidence, commit boundary and concurrency.

All objects are isolated fixtures. No Workflow or private platform module runs.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import importlib.util
import inspect
import json
import multiprocessing
import os
from pathlib import Path
import unittest
from unittest import mock


def load_sibling(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


support = load_sibling('idempotence_support', 'pre_dispatch_recovery_fixtures.py')
transaction = load_sibling('idempotence_transaction_support', 'test_pre_dispatch_recovery_transaction.py')


def worker(mod, f, barrier, conn):
    try:
        barrier.wait(timeout=30)
        result = mod.recover_dispatch_rejection(
            repo_path=f.repo, manifest_path=f.manifest_path, build_record_path=f.build_record_path,
            native_record_path=f.native_path, tool_use_id='call_fixture_rejection',
            operator_index=f.operator_index, evidence_acceptance_index=f.acceptance_index,
            check_only=False, additional_sources=())
        conn.send(('ok', result))
    except mod.ExecutorError as exc:
        conn.send(('executor_error', exc.error_code, exc.reason))
    except BaseException as exc:
        conn.send(('unexpected', type(exc).__name__, str(exc)))
    finally:
        conn.close()


class Idempotence(unittest.TestCase):
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

    def recover(self, check=False, sources=(), **changes):
        f = self.f
        args = dict(repo_path=f.repo, manifest_path=f.manifest_path, build_record_path=f.build_record_path,
                    native_record_path=f.native_path, tool_use_id='call_fixture_rejection',
                    operator_index=f.operator_index, evidence_acceptance_index=f.acceptance_index,
                    check_only=check, additional_sources=tuple(sources))
        args.update(changes)
        return self.mod.recover_dispatch_rejection(**args)

    def ok(self, label, fn):
        try:
            return fn()
        except self.mod.ExecutorError as exc:
            self.fail(f'{label}: valid input refused {exc.error_code}/{exc.reason}')

    def history(self, ref):
        f, mod = self.f, self.mod
        self.ok('graph', lambda: mod._HistoryGraph(f.scope).walk(ref, Path(ref['path']), 'event'))
        state = self.ok('load scope', lambda: mod._load_scope(f.scope, f.manifest, mod._Inputs()))
        replay = self.ok('replay', lambda: mod._replay_history(state))
        return state, replay

    def first(self):
        f, mod = self.f, self.mod
        before = support.tree_snapshot(f.root)
        preview = self.ok('initial check-only', lambda: self.recover(check=True))
        self.assertTrue(preview['eligible'])
        self.assertTrue(preview['would_append'])
        self.assertIsNone(preview.get('event'))
        self.assertEqual(before, support.tree_snapshot(f.root))
        ref = self.ok('initial recovery', lambda: self.recover())['event']
        self.assertEqual(ref, support.file_ref(Path(ref['path'])))
        event = json.loads(Path(ref['path']).read_bytes())
        self.assertEqual((event['seq'], event['kind'], event['previous_event']),
                         (2, 'dispatch_rejected', f.binding['reservation']))
        self.assertEqual(len(f.event_paths()), 2)
        state, replay = self.history(ref)
        self.assertEqual(state['head'], ref)
        self.assertEqual(replay['attempts'], [])
        closure = mod._history_closure(event['payload']['input_closure'], Path(ref['path']), f.scope)
        evidence = json.loads(closure.read(Path(event['payload']['evidence']['path'])))
        sources = [evidence['source']]
        for name in ('operator_statement', 'evidence_acceptance'):
            authority = json.loads(closure.read(Path(evidence[name]['path'])))['sourceData']
            sources.append(authority['source'])
            for field in ('question', 'response'):
                selected = authority[field]
                raw = Path(authority['source']['original_locator']).read_bytes().splitlines()[selected['line'] - 1]
                self.assertEqual(support.digest(raw), selected['line_sha256'])
        for source in sources:
            frozen = closure.read(Path(source['snapshot']['path']))
            self.assertEqual(support.digest(frozen), source['snapshot']['sha256'])
            self.assertTrue(Path(source['original_locator']).read_bytes().startswith(frozen))
        f.assert_old_unchanged(self)
        return ref

    def refuse(self, prefixes, *, check=False, sources=(), codes=('E_RECOVERY_EVIDENCE',), **changes):
        before = support.tree_snapshot(self.f.root)
        events = self.f.event_paths()
        event_ref = support.file_ref(events[1]) if len(events) == 2 else None
        event_raw = events[1].read_bytes() if event_ref is not None else None
        try:
            with self.assertRaises(self.mod.ExecutorError) as caught:
                self.recover(check=check, sources=sources, **changes)
            self.assertIn(caught.exception.error_code, codes)
            self.assertTrue(caught.exception.reason.startswith(prefixes), caught.exception.reason)
            self.assertEqual(before, support.tree_snapshot(self.f.root))
        finally:
            # This executes even when the reason assertion exposes the premature
            # head gate; immutable history must remain independently replayable.
            if event_ref is not None:
                self.unchanged(event_ref, event_raw)

    def assert_scan_counterevidence(self, root, *, primary=False):
        # Exercise the real scanner independently of the premature head gate.
        pending = {root}
        exempt = (self.f._uuid(1), self.f._uuid(2)) if primary else None
        with self.assertRaises(self.mod.ExecutorError) as caught:
            while pending:
                path = pending.pop()
                self.mod._recovery_scan_root(self.f.repo, path, self.f.record,
                    'call_fixture_rejection', exempt if path == root else None,
                    self.mod._Inputs(), pending)
        self.assertEqual(caught.exception.error_code, 'E_RECOVERY_EVIDENCE')
        self.assertTrue(caught.exception.reason.startswith('counterevidence'), caught.exception.reason)

    def unchanged(self, ref, raw):
        self.assertEqual(Path(ref['path']).read_bytes(), raw)
        self.assertEqual(len(self.f.event_paths()), 2)
        self.f.assert_old_unchanged(self)
        self.history(ref)

    def implicit_roots(self, depth=1):
        """Known roots reached only by structured links, never additional args."""
        f = self.f
        first = f.append_workflow(status='success', related=False, new_root=True)
        roots = [first]
        if depth == 2:
            session = '77777777-8888-4999-8000-111111111111'
            second = first.with_name(session + '.jsonl')
            inputs = json.loads(first.read_bytes().splitlines()[0])['message']['content'][0]['input']
            request, response = f._pair('Workflow', inputs, 201, 'call_recursive_second', session=session)
            second.write_bytes(support.encode(request) + b'\n' + support.encode(response) + b'\n')
            row = f._root('user', 203, [{'type': 'text', 'text': 'Recursive note A'}], session=first.stem)
            row['original_locator'] = str(second)
            first.write_bytes(first.read_bytes() + support.encode(row) + b'\n')
            roots.append(second)
        f.append_unrelated_message()
        f.rows[-1]['native_source'] = str(first)
        f._write_native()
        return roots

    def assert_recursive_receipt(self, ref):
        before = support.tree_snapshot(self.f.root)
        raw = Path(ref['path']).read_bytes()
        for check in (False, True):
            with self.subTest(check_only=check):
                try:
                    repeated = self.ok('unchanged implicit recursive root must reuse receipt',
                                       lambda: self.recover(check=check))
                    self.assertFalse(repeated['would_append'])
                    if check:
                        self.assertIsNone(repeated.get('event'))
                    else:
                        self.assertEqual(repeated['event'], ref)
                finally:
                    self.assertEqual(before, support.tree_snapshot(self.f.root))
                    self.unchanged(ref, raw)

    def test_implicit_recursive_root_identical_reentry_reuses_event(self):
        self.implicit_roots()
        self.assert_recursive_receipt(self.first())

    def test_two_level_recursive_roots_identical_reentry_reuses_event(self):
        self.implicit_roots(depth=2)
        self.assert_recursive_receipt(self.first())

    def test_recursive_roots_unrelated_tail_growth_reuses_frozen_receipt(self):
        roots = self.implicit_roots(depth=2)
        ref = self.first()
        for i, root in enumerate(roots):
            old = root.read_bytes()
            row = self.f._root('user', 301 + i, [{'type': 'text', 'text': 'Unrelated tail'}], session=root.stem)
            root.write_bytes(old + support.encode(row) + b'\n')
            self.assertNotEqual(root.read_bytes(), old)
            self.assertTrue(root.read_bytes().startswith(old))
        self.assert_recursive_receipt(ref)

    def test_recursive_root_same_length_and_grown_prefix_rewrite_are_rejected(self):
        roots = self.implicit_roots(depth=2)
        for i, root in enumerate(roots):
            row = self.f._root('user', 401 + i, [{'type': 'text', 'text': 'Recursive note A'}], session=root.stem)
            root.write_bytes(root.read_bytes() + support.encode(row) + b'\n')
        self.first()
        for root in roots:
            original = root.read_bytes()
            rewritten = original.replace(b'Recursive note A', b'Recursive note B')
            self.assertEqual(len(original), len(rewritten))
            self.assertNotEqual(original, rewritten)
            for grow in (False, True):
                with self.subTest(root_depth=roots.index(root) + 1, grown=grow):
                    tail = support.encode(self.f._root('user', 501,
                        [{'type': 'text', 'text': 'Unrelated tail'}], session=root.stem)) + b'\n'
                    root.write_bytes(rewritten + (tail if grow else b''))
                    try:
                        for check in (False, True):
                            with self.subTest(check_only=check):
                                self.refuse(('input_changed_source_prefix_or_bytes',), check=check)
                    finally:
                        root.write_bytes(original)

    def test_new_implicit_unrelated_root_changes_input_not_receipt(self):
        roots = self.implicit_roots(depth=2)
        ref = self.first()
        old = roots[-1].read_bytes()
        third = roots[-1].with_name('88888888-9999-4000-8111-222222222222.jsonl')
        row = self.f._root('user', 601, [{'type': 'text', 'text': 'New unrelated root'}], session=third.stem)
        third.write_bytes(support.encode(row) + b'\n')
        link = self.f._root('user', 602, [{'type': 'text', 'text': 'New source link'}], session=roots[-1].stem)
        link['native_source'] = str(third)
        roots[-1].write_bytes(old + support.encode(link) + b'\n')
        for check in (False, True):
            self.refuse(('input_changed_known_roots',), check=check)
        self.unchanged(ref, Path(ref['path']).read_bytes())

    def test_recursive_root_success_and_unknown_veto_before_receipt(self):
        roots = self.implicit_roots(depth=2)
        ref = self.first()
        raw = Path(ref['path']).read_bytes()
        inputs = {'scriptPath': str(self.f.script_path), 'args': {
            'identity': copy.deepcopy(self.f.record['identity']),
            'manifest_sha256': self.f.record['manifest']['sha256']}}
        for root in roots:
            original = root.read_bytes()
            for status in ('success', 'unknown'):
                with self.subTest(root_depth=roots.index(root) + 1, status=status):
                    request, response = self.f._pair('Workflow', inputs, 701,
                        'call_recursive_associated', session=root.stem)
                    response['toolUseResult'] = {'runId': 'recursive-associated-run', 'status': 'completed'}
                    response['message']['content'][0]['content'] = 'Workflow completed: recursive-associated-run'
                    added = [request, response] if status == 'success' else [request]
                    root.write_bytes(original + b''.join(support.encode(row) + b'\n' for row in added))
                    try:
                        for check in (False, True):
                            self.refuse(('counterevidence_native',), check=check)
                        self.unchanged(ref, raw)
                    finally:
                        root.write_bytes(original)

    def test_identical_mutation_and_check_only_reentry(self):
        ref = self.first()
        before = support.tree_snapshot(self.f.root)
        for check in (False, True):
            with self.subTest(check_only=check):
                repeated = self.ok('same evidence reentry', lambda: self.recover(check=check))
                if check:
                    self.assertIsNone(repeated.get('event'))
                    self.assertFalse(repeated['would_append'])
                else:
                    self.assertEqual(repeated['event'], ref)
                self.assertEqual(before, support.tree_snapshot(self.f.root))
        self.assertEqual(len(self.f.event_paths()), 2)
        self.f.assert_old_unchanged(self)

    def test_unrelated_journal_append_keeps_original_key_and_blobs(self):
        ref = self.first()
        raw = Path(ref['path']).read_bytes()
        old = self.f.native_path.read_bytes()
        blobs = {p.name: p.read_bytes() for p in (self.f.scope / 'blobs').iterdir()}
        self.f.append_unrelated_message()
        self.f.rows[-1]['timestamp'] = '2030-01-01T00:00:00.000Z'
        self.f._write_native()
        self.assertTrue(self.f.native_path.read_bytes().startswith(old))
        self.assertNotEqual(old, self.f.native_path.read_bytes())
        self.assertEqual(self.ok('append-only reentry', lambda: self.recover())['event'], ref)
        self.assertEqual({p.name: p.read_bytes() for p in (self.f.scope / 'blobs').iterdir()}, blobs)
        self.unchanged(ref, raw)

    def test_primary_root_counterevidence_precedes_idempotence(self):
        ref = self.first()
        raw = Path(ref['path']).read_bytes()
        for status in ('success', 'unknown'):
            with self.subTest(status=status):
                self.f.restore_authorities()
                self.f.append_workflow(status=status)
                self.assert_scan_counterevidence(self.f.native_path, primary=True)
                for check in (False, True):
                    with self.subTest(check=check):
                        self.refuse(('counterevidence',), check=check)
                self.unchanged(ref, raw)

    def test_new_explicit_source_scanned_before_input_change(self):
        ref = self.first()
        raw = Path(ref['path']).read_bytes()
        for status in ('success', 'unknown'):
            with self.subTest(status=status):
                root = self.f.append_workflow(status=status, new_root=True)
                self.assert_scan_counterevidence(root)
                for check in (False, True):
                    self.refuse(('counterevidence',), check=check, sources=(root,))
                self.unchanged(ref, raw)

    def test_new_typed_locator_source_scanned_before_input_change(self):
        ref = self.first()
        raw = Path(ref['path']).read_bytes()
        extra = {'type': 'future-native-role', 'agentId': 'unrelated-agent', 'uuid': 'associated-event',
                 'data': {'toolUseID': 'call_fixture_rejection'}}
        root, leaf, log, row, native, event = transaction.install_typed_termination(self.f, self.mod, extra=extra)
        observed = self.ok('typed link health', lambda: transaction.typed_preflight(self.f, self.mod, row))
        self.assertEqual(observed['terminations']['/workflowProgress/0'], row['data']['termination_refs'][0]['event'])
        self.assertEqual(row['data']['native_record'], support.file_ref(leaf))
        self.assertEqual(row['data']['termination_refs'][0]['event']['file'], support.file_ref(log))
        self.assertEqual(json.loads(log.read_bytes().splitlines()[0]), event)
        self.assertEqual(json.loads(leaf.read_bytes()), native)
        self.assert_scan_counterevidence(root)
        self.refuse(('counterevidence',), sources=(root,))
        self.unchanged(ref, raw)

    def test_unrelated_new_source_changes_exact_input_set(self):
        ref = self.first()
        raw = Path(ref['path']).read_bytes()
        root = self.f.append_workflow(status='success', related=False, new_root=True)
        self.assertTrue(root.is_file())
        self.refuse(('input_changed', 'additional_source_'), sources=(root,))
        self.unchanged(ref, raw)

    def test_missing_truncated_or_rewritten_prefix_is_not_same_evidence(self):
        self.f.append_unrelated_message()
        ref = self.first()
        raw = Path(ref['path']).read_bytes()
        path = self.f.native_path
        original = path.read_bytes()
        lines = original.splitlines(keepends=True)
        for mutation in ('missing', 'truncated', 'prefix_rewritten'):
            with self.subTest(mutation=mutation):
                path.write_bytes(original)
                if mutation == 'missing':
                    path.unlink()
                elif mutation == 'truncated':
                    path.write_bytes(b''.join(lines[:2]))
                else:
                    row = json.loads(lines[-1])
                    row['timestamp'] = '2025-12-31T00:00:00.000Z'
                    path.write_bytes(b''.join(lines[:-1]) + support.encode(row) + b'\n')
                    self.assertEqual(path.read_bytes().splitlines()[:6], original.splitlines()[:6])
                self.refuse(('native_', 'input_changed', 'operator_', 'evidence_acceptance_'),
                            codes=('E_RECOVERY_EVIDENCE', 'E_NATIVE_EVIDENCE'))
                self.unchanged(ref, raw)
        path.write_bytes(original)

    def test_replaced_authority_locator_cannot_reuse_old_key(self):
        ref = self.first()
        raw = Path(ref['path']).read_bytes()
        copy_path = self.f.repo / 'operator-copy.json'
        copy_path.write_bytes(self.f.operator_index.read_bytes())
        self.assertNotEqual(copy_path, self.f.operator_index)
        self.assertEqual(copy_path.read_bytes(), self.f.operator_index.read_bytes())
        self.refuse(('input_changed', 'operator_'), operator_index=copy_path)
        self.unchanged(ref, raw)

    def alternate_pair(self, kind):
        """Append a second authentic pair and rebind the real canonical index."""
        f = self.f
        path = f.operator_index if kind == 'operator' else f.acceptance_index
        parser = (self.mod._parse_operator_recovery_statement if kind == 'operator'
                  else self.mod._parse_evidence_acceptance)
        old_native, old_index = f.native_path.read_bytes(), path.read_bytes()
        old_selected = self.ok('original authority adapter', lambda: parser(f.repo, f.binding, path))['sourceData']
        question, response = f._ask_pair(kind, 101)
        tool_id = 'call_fixture_new_' + kind
        question['message']['content'][0]['id'] = tool_id
        response['message']['content'][0]['tool_use_id'] = tool_id
        question_raw, response_raw = support.encode(question), support.encode(response)
        f.native_path.write_bytes(old_native + question_raw + b'\n' + response_raw + b'\n')
        index = copy.deepcopy(json.loads(old_index))
        start = len(old_native.splitlines())
        for key, row, line, raw in (('question', question, start + 1, question_raw),
                                    ('response', response, start + 2, response_raw)):
            index[key] = {'path': str(f.native_path), 'line': line, 'uuid': row['uuid'],
                          'line_sha256': support.digest(raw)}
        index['tool_use_id'] = tool_id
        support.write_json(path, index)
        self.assertTrue(f.native_path.read_bytes().startswith(old_native))
        self.assertEqual(response['parentUuid'], question['uuid'])
        self.assertEqual(response['sourceToolAssistantUUID'], question['uuid'])
        self.assertNotEqual(index['question']['uuid'], old_selected['question']['uuid'])
        self.assertNotEqual(index['response']['uuid'], old_selected['response']['uuid'])
        self.assertNotEqual(index['tool_use_id'], old_selected['tool_use_id'])
        selected = self.ok('new authority adapter', lambda: parser(f.repo, f.binding, path))['sourceData']
        self.assertEqual(selected['target'], f.binding)
        self.assertEqual(selected['tool_use_id'], tool_id)
        self.assertEqual(selected['question'], {k: index['question'][k] for k in ('uuid', 'line', 'line_sha256')})
        self.assertEqual(selected['response'], {k: index['response'][k] for k in ('uuid', 'line', 'line_sha256')})
        return path, old_index, old_native

    def test_alternate_authority_pairs_have_real_valid_adapters(self):
        ref = self.first()
        raw = Path(ref['path']).read_bytes()
        for kind in ('operator', 'acceptance'):
            with self.subTest(kind=kind):
                path, index, native = self.alternate_pair(kind)
                try:
                    self.unchanged(ref, raw)
                finally:
                    path.write_bytes(index)
                    self.f.native_path.write_bytes(native)

    def test_alternate_authority_pair_cannot_replace_seq2(self):
        ref = self.first()
        raw = Path(ref['path']).read_bytes()
        for kind in ('operator', 'acceptance'):
            with self.subTest(kind=kind):
                path, index, native = self.alternate_pair(kind)
                try:
                    # Both pairs are independently valid, but the new tuple and
                    # authority index produce a different legitimate input.
                    # Current public entry has no second-event candidate API.
                    self.refuse(('input_changed', 'authority_', 'operator_', 'evidence_acceptance_',
                                 'existing_output', 'concurrent_output'),
                                codes=('E_RECOVERY_EVIDENCE', 'E_OUTPUT_CONFLICT', 'E_PREVIOUS_IDENTITY'))
                finally:
                    self.unchanged(ref, raw)
                    path.write_bytes(index)
                    self.f.native_path.write_bytes(native)

    def test_future_host_clock_keeps_existing_authorities_valid(self):
        ref = self.first()
        raw = Path(ref['path']).read_bytes()
        native = self.f.native_path.read_bytes()
        indexes = (self.f.operator_index.read_bytes(), self.f.acceptance_index.read_bytes())
        class FutureClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2040, 1, 1, tzinfo=timezone.utc).astimezone(tz)
        with mock.patch.object(self.mod, 'datetime', FutureClock):
            # now() is a real module clock producer; inherited fromisoformat
            # still parses the unchanged authority timestamps. Recovery has no
            # own now() call in the present implementation.
            self.assertEqual(self.mod.datetime.now(timezone.utc).year, 2040)
            for path, parser in ((self.f.operator_index, self.mod._parse_operator_recovery_statement),
                                 (self.f.acceptance_index, self.mod._parse_evidence_acceptance)):
                self.ok('future clock authority parse', lambda: parser(self.f.repo, self.f.binding, path))
            try:
                self.assertEqual(self.ok('future clock reentry', lambda: self.recover())['event'], ref)
            finally:
                self.assertEqual(self.f.native_path.read_bytes(), native)
                self.assertEqual((self.f.operator_index.read_bytes(), self.f.acceptance_index.read_bytes()), indexes)
                self.unchanged(ref, raw)

    def test_legal_successor_makes_recovery_stale_but_replay_valid(self):
        ref = self.first()
        f = self.f
        manifest, run, index = f.successor(ref)
        kwargs = dict(repo_path=f.repo, manifest_path=manifest, output_dir=run)
        if 'recovery_sources' in inspect.signature(self.mod.build).parameters:
            kwargs['recovery_sources'] = index
        self.ok('successor build', lambda: self.mod.build(**kwargs))
        state = self.ok('successor load', lambda: self.mod._load_scope(f.scope, f.manifest, self.mod._Inputs()))
        self.assertEqual(state['reserve_count'], 2)
        self.assertNotEqual(state['head'], ref)
        self.assertEqual(len(f.event_paths()), 3)
        self.ok('successor graph', lambda: self.mod._HistoryGraph(f.scope).walk(
            state['head'], Path(state['head']['path']), 'event'))
        prefix_events = state['events'][:-1]
        prefix = {**state, 'events': prefix_events, 'pending': None,
                  'head': prefix_events[-1]['ref'], 'reserve_count': state['reserve_count'] - 1}
        replay = self.ok('successor committed prefix replay', lambda: self.mod._replay_history(prefix))
        self.assertEqual(replay['attempts'], [])
        self.refuse(('target_', 'input_changed'), codes=('E_RECOVERY_EVIDENCE', 'E_PREVIOUS_IDENTITY'))
        self.assertEqual(len(f.event_paths()), 3)

    def test_pre_event_crash_retains_blobs_and_retry_reuses_them(self):
        f, mod = self.f, self.mod
        self.assertTrue(self.ok('pre-crash check', lambda: self.recover(check=True))['eligible'])
        original = mod._publish
        target = f.scope / 'events' / '0000000002.json'
        reached = []
        def inject(path, raw, allowed, resume=False):
            if path == target:
                reached.append(support.digest(raw))
                raise RuntimeError('injected before seq2 publish')
            return original(path, raw, allowed, resume=resume)
        with mock.patch.object(mod, '_publish', side_effect=inject):
            with self.assertRaisesRegex(RuntimeError, 'before seq2'):
                self.recover()
        self.assertEqual(len(reached), 1)
        self.assertFalse(target.exists())
        self.assertEqual(len(f.event_paths()), 1)
        state = self.ok('pending after crash', lambda: mod._load_scope(f.scope, f.manifest, mod._Inputs()))
        self.assertEqual(state['pending']['ref'], f.binding['reservation'])
        blobs = {p.name: p.read_bytes() for p in (f.scope / 'blobs').iterdir()}
        self.assertTrue(blobs)
        ref = self.ok('pre-event retry', lambda: self.recover())['event']
        self.assertEqual(ref['sha256'], reached[0])
        self.assertEqual({p.name: p.read_bytes() for p in (f.scope / 'blobs').iterdir()}, blobs)
        self.history(ref)
        f.assert_old_unchanged(self)

    def test_post_event_crash_retry_returns_committed_event(self):
        f, mod = self.f, self.mod
        original = mod._publish
        target = f.scope / 'events' / '0000000002.json'
        reached = []
        def inject(path, raw, allowed, resume=False):
            result = original(path, raw, allowed, resume=resume)
            if path == target:
                reached.append(result)
                raise RuntimeError('injected after seq2 publish')
            return result
        with mock.patch.object(mod, '_publish', side_effect=inject):
            with self.assertRaisesRegex(RuntimeError, 'after seq2'):
                self.recover()
        self.assertEqual(len(reached), 1)
        self.assertEqual(support.file_ref(target), reached[0])
        self.assertEqual(len(f.event_paths()), 2)
        self.history(reached[0])
        before = support.tree_snapshot(f.root)
        self.assertEqual(self.ok('post-event retry', lambda: self.recover())['event'], reached[0])
        self.assertEqual(before, support.tree_snapshot(f.root))
        f.assert_old_unchanged(self)

    def test_concurrent_workers_one_event_busy_requires_retry(self):
        f, mod = self.f, self.mod
        self.assertTrue(self.ok('concurrent fixture check', lambda: self.recover(check=True))['eligible'])
        ctx = multiprocessing.get_context('fork')
        barrier = ctx.Barrier(2)
        receivers, processes = [], []
        for _ in range(2):
            recv, send = ctx.Pipe(duplex=False)
            process = ctx.Process(target=worker, args=(mod, f, barrier, send))
            process.start()
            send.close()
            receivers.append(recv)
            processes.append(process)
        results = []
        try:
            for recv in receivers:
                self.assertTrue(recv.poll(60), 'worker result timed out')
                results.append(recv.recv())
            for process in processes:
                process.join(60)
                self.assertFalse(process.is_alive(), 'worker did not terminate')
                self.assertEqual(process.exitcode, 0)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(10)
            for recv in receivers:
                recv.close()
        successes = [r[1]['event'] for r in results if r[0] == 'ok']
        failures = [r for r in results if r[0] != 'ok']
        self.assertTrue(successes, f'no worker committed: {results!r}')
        self.assertEqual(len(f.event_paths()), 2)
        self.assertTrue(all(ref == successes[0] for ref in successes), results)
        for failure in failures:
            self.assertEqual(failure, ('executor_error', 'E_SCOPE_BUSY', 'writer_lock_busy'), results)
            self.assertEqual(self.ok('busy worker controlled retry', lambda: self.recover())['event'], successes[0])
        self.history(successes[0])
        f.assert_old_unchanged(self)


if __name__ == '__main__':
    unittest.main(verbosity=2)
