"""TASK-004 build 行为边界；全部目标/插件副本位于新临时目录。

负控意图：删除原始类型检查、允许 manifest 覆载、跳过固定来源比较、
跳过短锁/谱系校验或重派 pending，均须令指定断言失败。
不运行 Workflow，不把后续历史重算/调度/collect/Rule6 宣称为完成。
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ENGINE = Path(__file__).resolve().parents[1]
EXECUTOR = ENGINE / "scripts" / "audit_executor.py"


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("isolated_audit_executor", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def ref(path: Path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


# VM host only adapts the leading Workflow export; the generated scheduler is unchanged.
# Negative targets: eager slot release, dispatch after stop, shared raw snapshots,
# argument overrides, checker timer reuse, missing request/anchor hash checks.
VM_HOST = r"""
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const match = input.script.match(/^export const meta = (\{[^\n]+\})\n/);
if (!match) throw new Error('missing literal Workflow metadata');
const meta = JSON.parse(match[1]);
let now = 0, serial = 0, returned = false, value = null, error = null;
let active = 0, maxActive = 0;
const timers = new Map(), calls = [], deferred = [], delivered = [], logs = [], trace = [];
const clone = x => JSON.parse(JSON.stringify(x));
const flush = async () => { for (let i=0;i<40;i++) await Promise.resolve(); };
const context = vm.createContext({
  args:input.args, Date:undefined,
  Math:Object.assign(Object.create(Math),{random(){throw new Error('random forbidden');}}),
  phase:title=>{ if (!meta.phases.some(p=>p.title===title)) throw new Error('phase mismatch'); },
  log:text=>logs.push(String(text)),
  setTimeout:(fn,ms)=>{const id=++serial;timers.set(id,{at:now+ms,fn});return id;},
  clearTimeout:id=>timers.delete(id),
  agent:(prompt,opts)=>{
    const index=calls.length; calls.push({prompt,opts:clone(opts),at:now});
    active++;maxActive=Math.max(maxActive,active);
    const mode=(input.modes||[])[index];
    if (mode && mode.kind==='throw') {active--;throw new Error(mode.message);}
    return new Promise((resolve,reject)=>{
      deferred[index]={resolve:raw=>{active--;delivered[index]=raw;resolve(raw);},
                       reject:message=>{active--;reject(new Error(message));}};
      if (mode && mode.kind==='resolve') deferred[index].resolve(mode.value);
      if (mode && mode.kind==='reject') deferred[index].reject(mode.message);
    });
  }
});
const body = input.script.replace(/^export /,'');
const run = vm.runInContext('(async()=>{'+body+'\n})()',context,{timeout:1000});
run.then(v=>{returned=true;value=v;},e=>{returned=true;error=String(e);});
const snapshot=()=>trace.push({at:now,returned,error,value:value===null?null:clone(value),
  calls:clone(calls),active,maxActive,timers:[...timers.values()].map(t=>t.at),logs:clone(logs)});
(async()=>{
  await flush();snapshot();
  for (const step of input.steps||[]) {
    if (step.kind==='advance') {
      const end=now+step.ms;
      while (true) {
        const next=[...timers].filter(([id,t])=>t.at<=end).sort((a,b)=>a[1].at-b[1].at||a[0]-b[0])[0];
        if (!next) break;
        timers.delete(next[0]);now=next[1].at;next[1].fn();await flush();
      }
      now=end;
    } else if (step.kind==='resolve') deferred[step.index].resolve(step.value);
    else if (step.kind==='reject') deferred[step.index].reject(step.message);
    else if (step.kind==='mutate') delivered[step.index].nested.value='changed';
    await flush();snapshot();
  }
  process.stdout.write(JSON.stringify({clock:'controlled_logical_clock',meta,trace}));
})().catch(e=>{process.stderr.write(String(e));process.exitCode=1;});
"""


class PreparePolicyTests(unittest.TestCase):
    """Synthetic build/capture/prepare integration; no real Workflow or consent."""

    def setUp(self):
        self.n = NativeEvidenceTests('test_control_timeout_accepts_legitimate_incomplete_snapshots')
        self.n.setUp()
        self.addCleanup(self.n.doCleanups)
        self.f, self.mod = self.n.f, self.n.mod
        self.capture()

    def capture(self):
        self.n.capture()
        self.n.index['attempt_index'] = self.f.manifest['attempt_index']
        self.f.write(self.n.index_path, self.n.index)

    def output(self):
        return self.f.run_dir / (self.f.run_dir.name + '.json')

    def prepare(self, native=None, output=None, previous=None):
        return self.mod._prepare_policy(self.f.repo, self.f.manifest_path,
            self.f.run_dir / 'build-record.json', 'synthetic-run', native or self.n.native_path,
            output or self.output(), previous)

    def cli(self, extra=(), cwd=None):
        args = [sys.executable, '-I', str(self.f.engine / 'scripts' / 'audit_executor.py'),
            'collect', '--repo-path', str(self.f.repo), '--manifest', str(self.f.manifest_path),
            '--build-record', str(self.f.run_dir / 'build-record.json'),
            '--workflow-run-id', 'synthetic-run', '--native-record', str(self.n.native_path),
            '--output', str(self.output()), *extra]
        return subprocess.run(args, cwd=cwd or self.f.root, capture_output=True)

    def second(self, *, findings=True, disabled=False, missing=False, full=False):
        h = HistoricalReplayTests()
        h.setUp()
        self.addCleanup(h.doCleanups)
        if disabled:
            h.f.defaults_value['audit']['drift_guard']['convergence_mode'] = False
        if missing:
            h.f.proposal.write_text('# Target\nLevel: Standard\n')
            h.f.policy_value['spec_source'] = ref(h.f.proposal)
            h.f.policy_value['anchor_selection']['primary_goal'] = None
            h.f.policy_value['fallback_sources'][0]['source'] = ref(h.f.proposal)
            for kind in ('issue_title', 'pr_title'):
                title_path = h.f.repo / (kind + '.json')
                h.f.write(title_path, {'title': ''})
                h.f.policy_value['fallback_sources'].append({'kind': kind,
                    'locator': str(title_path), 'source': ref(title_path)})
            h.f.write(h.f.policy, h.f.policy_value)
            h.f.manifest['evidence']['policy_inputs'] = ref(h.f.policy)
        h.start(full=full)
        h.finish()
        h.next_build(2, 2)
        self.f, self.mod = h.f, h.mod
        self.n.f, self.n.mod = self.f, self.mod
        self.n.native_path = self.f.run_dir / 'native.json'
        self.n.index_path = self.f.run_dir / 'audit-index.json'
        record = self.f.record()
        self.n.native['script'] = (self.f.run_dir / 'workflow.js').read_text()
        self.n.native['args'] = {'identity': record['identity'], 'manifest_sha256': record['manifest']['sha256']}
        self.n.native['result'].update(identity=record['identity'], manifest_sha256=record['manifest']['sha256'])
        for role, seat in zip(record['roles'], self.n.native['result']['results']):
            seat.update({k: role[k] for k in ('index', 'role_id', 'agentType', 'label')})
        self.n.native['workflowProgress'][1].update(label=record['roles'][0]['label'])
        self.n.native['result']['results'][0]['raw'] = StatePartitionTests.valid_raw()
        if findings:
            report = json.loads(StatePartitionTests.valid_raw())
            report['vote'] = 'REVISE'
            report['findings'] = [{'type': 'issue', 'severity': 'major', 'category': 'implementation',
                'scope': 'a.py', 'summary': 'synthetic finding', 'file': 'a.py', 'line': 1,
                'failure_scenario': 'synthetic fixture failure'}]
            self.n.native['result']['results'][0]['raw'] = encode(report).decode()
        self.capture()
        self.assertEqual(sum(role['execution_state'] == 'completed_admitted'
                             for role in self.n.classify()['roles']), 1,
                         'prepare fixture must actually reach the admitted branch')
        return Path(h.results[-1]['path'])

    def assert_error(self, code, **kwargs):
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.prepare(**kwargs)
        self.assertEqual(caught.exception.error_code, code)

    def test_cli_prepare_first_round_freezes_without_publication_or_commit(self):
        result = self.cli(['--prepare-policy'], cwd='/tmp')
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        value = json.loads(result.stdout)
        request = json.loads(Path(value['policy_request']['path']).read_bytes())
        self.assertEqual((request['reason'], request['required'], request['checker']), ('first_round', False, None))
        self.assertFalse(self.output().exists())
        self.assertFalse(self.output().with_suffix('.md').exists())
        self.assertEqual(len(list((self.f.scope() / 'events').iterdir())), 1)
        self.assertIsNone(value['policy_script'])
        self.assertEqual(Path(value['native_record']['path']).read_bytes(), self.n.native_path.read_bytes())

    def test_function_prepare_idempotent_clock_and_frozen_mapping(self):
        first = self.prepare()
        before = {p: p.read_bytes() for p in self.f.run_dir.iterdir() if p.is_file()}
        self.assertEqual(self.prepare(), first)
        frozen = Path(first['native_record']['path'])
        self.n.native_path.write_bytes(b'live capture grew after sealing')
        self.assertEqual(self.prepare(native=frozen), first)
        for path, raw in before.items():
            if path != self.n.native_path:
                self.assertEqual(path.read_bytes(), raw)
        self.assert_error('E_OUTPUT_CONFLICT')

    def test_request_priority_pairs_and_required_partial_full_scripts(self):
        previous = self.second()
        result = self.prepare(previous=previous)
        request = json.loads(Path(result['policy_request']['path']).read_bytes())
        self.assertEqual((request['reason'], request['required']), ('required', True))
        self.assertEqual(request['checker'], {'agentType': self.f.manifest['roles'][0]['agentType'],
            'label': 'drift:client-2', 'timeout_ms': 60000})
        expected = self.mod._render_policy_workflow(result['policy_request'])
        self.assertEqual(Path(result['policy_script']['path']).read_bytes(), expected)
        self.assertIn(encode('本次anchor为partial anchor').decode()[1:-1], expected.decode())
        self.assertEqual(request['conclusions'][0]['scope'], 'a.py')

    def test_disabled_empty_missing_and_full_are_source_recomputed(self):
        for options, reason in [({'disabled': True}, 'disabled_by_config'),
                ({'findings': False}, 'empty_conclusions'), ({'missing': True}, 'anchor_missing_observed'),
                ({'full': True}, 'required')]:
            with self.subTest(options=options):
                previous = self.second(**options)
                result = self.prepare(previous=previous)
                request = json.loads(Path(result['policy_request']['path']).read_bytes())
                self.assertEqual(request['reason'], reason)
                self.assertEqual(request['required'], reason == 'required')
                self.assertEqual(result['policy_script'] is not None, reason == 'required')
                if reason == 'required':
                    self.assertNotIn(encode('本次anchor为partial anchor').decode()[1:-1], Path(result['policy_script']['path']).read_text())

    def test_void_priority_over_first_round_and_required_checker_resource_pending(self):
        self.n.native['result']['results'][0]['raw'] = None
        self.capture()
        value = self.prepare()
        self.assertEqual(json.loads(Path(value['policy_request']['path']).read_bytes())['reason'], 'all_failed_void')
        previous = self.second()
        roles = self.f.record()['roles']
        for index in (1, 2):
            self.n.native['workflowProgress'].append({'type': 'workflow_agent', 'index': 80 + index,
                'label': roles[index]['label'], 'agentType': roles[index]['agentType'],
                'agentId': f'synthetic-unknown-{index}', 'model': None, 'queuedAt': 122000,
                'startedAt': 122000, 'state': 'progress'})
            self.n.native['result']['results'][index]['attempted'] = True
        self.n.native['agentCount'] = 3
        self.capture()
        self.assert_error('E_RESOURCE_PENDING', previous=previous)
        self.assertFalse((self.f.run_dir / 'policy-workflow.js').exists())

    def test_reject_bad_input_hash_source_identity_and_paths_without_replacing(self):
        self.n.index['native_record']['sha256'] = '0' * 64
        self.f.write(self.n.index_path, self.n.index)
        self.assert_error('E_NATIVE_EVIDENCE')
        self.capture()
        self.assert_error('E_OUTPUT_CONFLICT', output=self.f.root / 'escape.json')
        self.n.index['attempt_index'] = True
        self.f.write(self.n.index_path, self.n.index)
        self.assert_error('E_NATIVE_EVIDENCE')
        self.capture()
        value = self.prepare()
        request = Path(value['policy_request']['path'])
        original = request.read_bytes()
        request.write_bytes(original + b' ')
        self.assert_error('E_OUTPUT_CONFLICT')
        self.assertEqual(request.read_bytes(), original + b' ')
        request.write_bytes(original)
        Path(value['native_record']['path']).write_bytes(b'corrupt frozen source')
        self.assert_error('E_POLICY_SOURCE', native=Path(value['native_record']['path']))

    def test_cli_argument_pairs_and_final_fail_closed(self):
        for extra in (['--prepare-policy', '--check-result', str(self.output())],
                      ['--check-result', str(self.f.root / 'other.json')]):
            self.assertEqual(self.cli(extra).returncode, 2)
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stderr)['error_code'], 'E_POLICY_SOURCE')

    def snapshot(self):
        return {p: p.read_bytes() for p in self.f.root.rglob('*') if p.is_file()}

    def assert_admitted(self):
        roles = self.n.classify()['roles']
        self.assertEqual(sum(r['execution_state'] == 'completed_admitted' for r in roles), 1)
        self.assertFalse(any(r['execution_state'] == 'completed_parse_error' for r in roles))

    def fixed_source_pair(self, name):
        self.assert_admitted()
        source = Path(self.f.record()['sources'][name]['path'])
        original = source.read_bytes()
        source.write_bytes(original + b'\n ')
        before = self.snapshot()
        self.assert_error('E_SOURCE_DRIFT')
        self.assertEqual(self.snapshot(), before, 'drift must fail before any prepare publication')
        self.assertFalse((self.f.run_dir / 'audit-closure.json').exists())
        source.write_bytes(original)
        events = {p: p.read_bytes() for p in (self.f.scope() / 'events').iterdir()}
        value = self.prepare()
        request = json.loads(Path(value['policy_request']['path']).read_bytes())
        self.assertEqual((request['reason'], request['required']), ('first_round', False))
        self.assertEqual(len(request['conclusions']), 0)
        self.assertEqual({p: p.read_bytes() for p in (self.f.scope() / 'events').iterdir()}, events)
        self.assertFalse(self.output().exists())

    def test_prepare_config_byte_drift_pair_characterization(self):
        self.fixed_source_pair('config')

    def test_prepare_defaults_byte_drift_pair_characterization(self):
        self.fixed_source_pair('defaults')

    def test_prepare_executor_byte_drift_pair_characterization(self):
        self.fixed_source_pair('executor')

    def test_prepare_contract_byte_drift_pair_characterization(self):
        self.fixed_source_pair('contract')

    def test_prepare_convergence_algorithm_byte_drift_pair_characterization(self):
        self.fixed_source_pair('convergence_algorithm')

    def test_prepare_report_storage_byte_drift_pair_characterization(self):
        self.fixed_source_pair('report_storage')

    def interrupt_before(self, target, previous=None):
        # Stop at a real ordered publication boundary, not by deleting a completed
        # package and assuming that arbitrary missing artifacts are recoverable.
        from unittest.mock import patch
        publish = self.mod._publish
        hits = []

        def interrupted(path, raw, allowed, resume=False):
            if path == target:
                hits.append(path)
                raise OSError('synthetic prepare interruption')
            return publish(path, raw, allowed, resume=resume)

        self.assert_admitted()
        with patch.object(self.mod, '_publish', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'synthetic prepare interruption'):
                self.prepare(previous=previous)
        self.assertEqual(hits, [target], 'the intended production write must actually be reached')
        self.assertFalse(target.exists())

    def recover_prefix(self, target, *, required=False):
        previous = self.second() if required else None
        path = self.output().with_suffix('.policy-request.json') if target == 'request' else self.f.run_dir / target
        events = {p: p.read_bytes() for p in (self.f.scope() / 'events').iterdir()}
        reservation = self.f.record()['reservation']
        self.interrupt_before(path, previous)
        before = self.snapshot()
        result = self.prepare(previous=previous)
        for existing, raw in before.items():
            self.assertEqual(existing.read_bytes(), raw, 'recovery must not rewrite any existing bytes')
        request = json.loads(Path(result['policy_request']['path']).read_bytes())
        self.assertEqual((request['required'], request['reason']),
                         (required, 'required' if required else 'first_round'))
        self.assertEqual(len(request['conclusions']), int(required))
        self.assertEqual(result['policy_script'] is not None, required)
        self.assertEqual(self.f.record()['reservation'], reservation)
        self.assertEqual({p: p.read_bytes() for p in (self.f.scope() / 'events').iterdir()}, events)
        self.assertFalse(self.output().exists())
        self.assertFalse(self.output().with_suffix('.md').exists())
        return result, previous

    def test_prepare_blob_prefix_before_closure_recovers_characterization(self):
        self.recover_prefix('audit-closure.json')

    def test_prepare_audit_closure_prefix_recovers_characterization(self):
        self.recover_prefix('request')

    def test_prepare_required_audit_closure_prefix_recovers_characterization(self):
        self.recover_prefix('request', required=True)

    def test_prepare_required_request_before_script_recovers_characterization(self):
        self.recover_prefix('policy-workflow.js', required=True)

    def test_prepare_required_script_before_record_recovers_characterization(self):
        self.recover_prefix('prepare-record.json', required=True)

    def test_prepare_nonrequired_request_before_record_recovers_characterization(self):
        self.recover_prefix('prepare-record.json')

    def test_prepare_existing_metadata_reuses_clock_characterization(self):
        from unittest.mock import patch
        for required in (False, True):
            with self.subTest(required=required):
                previous = self.second() if required else None
                value = self.prepare(previous=previous)
                before = self.snapshot()
                with patch.object(self.mod, 'datetime') as clock:
                    clock.now.side_effect = AssertionError('existing prepare clock must not be replaced')
                    with patch.object(self.mod.time, 'monotonic_ns', return_value=10**30):
                        self.assertEqual(self.prepare(previous=previous), value)
                self.assertEqual(self.snapshot(), before)

    def test_prepare_partial_existing_request_and_script_conflict_characterization(self):
        for artifact in ('request', 'script'):
            with self.subTest(artifact=artifact):
                previous = self.second()
                self.interrupt_before(self.f.run_dir / 'prepare-record.json', previous)
                path = (self.output().with_suffix('.policy-request.json') if artifact == 'request'
                        else self.f.run_dir / 'policy-workflow.js')
                original = path.read_bytes()
                path.write_bytes(original + b' ')
                before = self.snapshot()
                self.assert_error('E_OUTPUT_CONFLICT', previous=previous)
                self.assertEqual(self.snapshot(), before)
                path.write_bytes(original)
                self.prepare(previous=previous)

    def test_prepare_partial_corrupt_and_missing_blob_refused_characterization(self):
        for damage in ('corrupt', 'missing'):
            with self.subTest(damage=damage):
                previous = self.second()
                self.interrupt_before(self.f.run_dir / 'policy-workflow.js', previous)
                closure = json.loads((self.f.run_dir / 'audit-closure.json').read_bytes())
                leaf = next(e for e in closure['sources'] if e['origin'] == str(self.n.native_path))
                blob = Path(leaf['blob']['path'])
                raw = blob.read_bytes()
                if damage == 'corrupt':
                    blob.write_bytes(raw + b' ')
                else:
                    blob.unlink()
                before = self.snapshot()
                self.assert_error('E_POLICY_SOURCE', previous=previous)
                self.assertEqual(self.snapshot(), before)
                blob.write_bytes(raw)
                value = self.prepare(previous=previous)
                self.assertTrue(json.loads(Path(value['policy_request']['path']).read_bytes())['required'])

    def test_prepare_partial_new_live_view_conflicts_but_frozen_view_resumes_characterization(self):
        previous = self.second()
        self.interrupt_before(self.f.run_dir / 'policy-workflow.js', previous)
        request = json.loads(self.output().with_suffix('.policy-request.json').read_bytes())
        blob = self.f.scope() / 'blobs' / (ref(self.n.native_path)['sha256'] + '.blob')
        self.n.native_path.write_bytes(self.n.native_path.read_bytes() + b' ')
        before = self.snapshot()
        self.assert_error('E_OUTPUT_CONFLICT', previous=previous)
        self.assertEqual(self.snapshot(), before)
        value = self.prepare(native=blob, previous=previous)
        self.assertEqual(json.loads(Path(value['policy_request']['path']).read_bytes()), request)
        self.assertEqual(Path(value['native_record']['path']), blob)


class GeneratedScriptTests(unittest.TestCase):
    """Controlled logical clock, not native T0/q/C/D or a real Workflow probe."""

    def setUp(self):
        # Composition intentionally avoids inheriting/counting the 41 build tests again.
        self.f = BuildContractTests('test_missing_project_and_missing_key_remain_false_without_team_or_evidence')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.mod = self.f.mod

    def run_js(self, script, args, steps=None, modes=None):
        payload = {'script': script.decode('utf-8'), 'args': args,
                   'steps': steps or [], 'modes': modes or []}
        result = subprocess.run(['node', '-e', VM_HOST], input=encode(payload),
                                capture_output=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        output = json.loads(result.stdout)
        self.assertEqual(output['clock'], 'controlled_logical_clock')
        return output['trace']

    def audit(self):
        self.f.build()
        script = (self.f.run_dir / 'workflow.js').read_bytes()
        record = self.f.record()
        args = {'identity': record['identity'], 'manifest_sha256': record['manifest']['sha256']}
        return script, args

    def request(self, partial=True):
        self.f.build()
        genesis = json.loads((self.f.scope() / 'genesis.json').read_bytes())
        anchor = json.loads(Path(genesis['anchor']['path']).read_bytes())
        if not partial:
            anchor['value']['in_scope'] = ['scope one']
        anchor_path = self.f.root / 'frozen-anchor.json'
        self.f.write(anchor_path, anchor)
        genesis['anchor'] = ref(anchor_path)
        genesis_path = self.f.root / 'frozen-genesis.json'
        self.f.write(genesis_path, genesis)
        identity = {key: self.f.manifest[key] for key in self.mod.IDENTITY_KEYS}
        identity.update(round=2, client_round_id='client-checker')
        # Synthetic wrapper files, not native capture or production prepare evidence.
        audit_index = self.f.root / 'fixture-audit-index.json'
        self.f.write(audit_index, {'schema_version': 1, 'identity': identity, 'attempt_index': 2,
            'workflow_run_id': 'fixture-only-not-native', 'native_record': ref(self.f.context),
            'termination_refs': []})
        finding = {'type': 'issue', 'severity': 'major', 'category': 'implementation',
                   'scope': 'a.py', 'summary': '完整结论 "\n` agent(\'escape\') ${x}'}
        finding = {**finding, 'file': 'a.py', 'line': 1, 'failure_scenario': 'fixture-only failure'}
        conclusion = {'id': hashlib.sha256(b'implementation:a.py:major:issue').hexdigest()[:8],
            **{key: finding[key] for key in ['type', 'severity', 'category', 'scope', 'summary']},
            'found_by': ['aria:qa-engineer'],
            'variants': [{'finding': finding, 'members': [{'role_id': 'aria:qa-engineer',
                'role_index': 1, 'finding_index': 0, 'raw_ref': {'file': ref(audit_index),
                'pointer': '/fixture-only'}}]}], 'conflict_state': 'none'}
        request = {'schema_version': 1, 'algorithm_version': 'canonical_v1', 'identity': identity,
            'attempt_index': 2, 'genesis': ref(genesis_path), 'anchor': ref(anchor_path),
            'audit_index': ref(audit_index), 'input_closure': ref(self.f.run_dir / 'input-closure.json'),
            'conclusions': [conclusion], 'required': True, 'reason': 'required',
            'checker': {'agentType': self.f.manifest['roles'][0]['agentType'],
                        'label': 'drift:client-checker', 'timeout_ms': 60000}}
        path = self.f.root / 'frozen-policy-request.json'
        self.f.write(path, request)
        args = {'identity': identity, 'request_sha256': ref(path)['sha256'],
                'anchor': anchor['value'], 'conclusions': request['conclusions']}
        return path, request, args

    def render(self, path):
        # Missing-symbol failures are initial scaffolding, never behavioral RED evidence.
        return self.mod._render_policy_workflow(ref(path))

    def test_build_literal_hash_stability_and_prompt_injection_characterization(self):
        evil = '\"; await agent("injected"); //\n` ${await agent("injected")} \\ 中文 '
        for role in self.f.manifest['roles']:
            role['prompt'] = evil
        script, args = self.audit()
        meta = json.loads(script.splitlines()[0].removeprefix(b'export const meta = '))
        self.assertEqual(meta['name'], 'audit-executor')
        self.assertEqual(self.mod._workflow(self.f.manifest, args['manifest_sha256']), script)
        self.assertEqual(hashlib.sha256(script).hexdigest(), self.f.record()['workflow_script']['sha256'])
        self.assertEqual(self.mod.build(self.f.repo, self.f.manifest_path, self.f.run_dir)['resume_only'], True)
        trace = self.run_js(script, args, modes=[{'kind': 'resolve', 'value': True}]*3)
        self.assertTrue(trace[-1]['returned'])
        self.assertEqual([c['prompt'] for c in trace[-1]['calls']], [evil]*3)
        for c in trace[-1]['calls']:
            self.assertEqual(set(c['opts']), {'agentType', 'label', 'phase'})
        self.assertLessEqual(trace[-1]['maxActive'], 2)

    def test_audit_args_are_closed_and_hash_bound_characterization(self):
        script, args = self.audit()
        cases = [None, {}, {**args, 'roles': []}, {**args, 'manifest_sha256': '0'*64},
                 {**args, 'identity': {**args['identity'], 'round': 2}},
                 {**args, 'identity': {**args['identity'], 'extra': True}}]
        for bad in cases:
            with self.subTest(args=bad):
                result = self.run_js(script, bad)[-1]
                self.assertIn('E_RUN_IDENTITY', result['error'])
                self.assertEqual(result['calls'], [])

    def test_audit_soft_timeout_keeps_slots_and_stop_blocks_late_dispatch_characterization(self):
        script, args = self.audit()
        trace = self.run_js(script, args, steps=[{'kind': 'advance', 'ms': 120000},
            {'kind': 'advance', 'ms': 180000}, {'kind': 'resolve', 'index': 0, 'value': {'late': True}},
            {'kind': 'reject', 'index': 1, 'message': 'late failure'}])
        self.assertEqual(len(trace[0]['calls']), 2)
        self.assertFalse(trace[1]['returned'])
        self.assertEqual(len(trace[1]['calls']), 2)
        self.assertEqual(len(trace[1]['logs']), 2)
        snapshot = trace[2]['value']
        self.assertTrue(snapshot['control']['stop_observed'])
        self.assertEqual(snapshot['control']['return_reason'], 'control_timeout')
        self.assertEqual([r['attempted'] for r in snapshot['results']], [True, True, False])
        self.assertEqual(trace[-1]['value'], snapshot)
        self.assertEqual(len(trace[-1]['calls']), 2)

    def test_single_unreturned_seat_still_limits_parallelism_characterization(self):
        script, args = self.audit()
        trace = self.run_js(script, args, modes=[None, {'kind': 'resolve', 'value': False},
            {'kind': 'resolve', 'value': ''}], steps=[{'kind': 'advance', 'ms': 300000}])
        self.assertEqual(len(trace[0]['calls']), 3)
        self.assertEqual(trace[-1]['maxActive'], 2)
        results = trace[-1]['value']['results']
        self.assertFalse(results[0]['settled'])
        self.assertIs(results[1]['raw'], False)
        self.assertEqual(results[2]['raw'], '')

    def test_audit_true_null_error_and_deep_copy_characterization(self):
        script, args = self.audit()
        trace = self.run_js(script, args, modes=[{'kind': 'resolve', 'value': True},
            {'kind': 'resolve', 'value': None}, {'kind': 'reject', 'message': 'actual failure'}])
        results = trace[-1]['value']['results']
        self.assertTrue(all(r['settled'] for r in results))
        self.assertIs(results[0]['raw'], True)
        self.assertIsNone(results[1]['raw'])
        self.assertIn('actual failure', results[2]['error'])
        nested = {'nested': {'value': 'original'}}
        trace = self.run_js(script, args, modes=[{'kind': 'resolve', 'value': nested}]*3,
                            steps=[{'kind': 'mutate', 'index': 0}])
        self.assertEqual(trace[-1]['value'], trace[0]['value'])
        self.assertEqual(trace[-1]['value']['results'][0]['raw'], nested)

    def test_generated_code_has_no_private_runtime_or_model_override_characterization(self):
        script, _ = self.audit()
        for token in [b'require(', b'import ', b'process.', b'fs.', b'Date.', b'Math.random',
                      b'AbortController', b'cancel(', b'model:']:
            self.assertNotIn(token, script)
        self.assertIn(b'model_alias', script)  # Trace only; actual agent opts checked above.

    def test_checker_literal_deterministic_complete_and_independent_call(self):
        path, request, args = self.request()
        script = self.render(path)
        self.assertEqual(self.render(path), script)
        meta = json.loads(script.splitlines()[0].removeprefix(b'export const meta = '))
        self.assertEqual(meta['name'], 'audit-policy-checker')
        raw = {'classifications': [{'key': ['issue', 'major', 'implementation', 'a.py'],
                                    'classification': 'on_topic'}], 'extra': {'unparsed': True}}
        trace = self.run_js(script, args, modes=[{'kind': 'resolve', 'value': raw}])
        self.assertEqual(len(trace[-1]['calls']), 1)
        call = trace[-1]['calls'][0]
        self.assertEqual(call['opts'], {'agentType': request['checker']['agentType'],
                                       'label': 'drift:client-checker', 'phase': 'Drift'})
        prompt = call['prompt']
        self.assertIn(args['request_sha256'], prompt)
        self.assertIn(json.dumps(args['anchor'], sort_keys=True, separators=(',', ':'), ensure_ascii=True), prompt)
        self.assertIn(json.dumps(args['conclusions'], sort_keys=True, separators=(',', ':'), ensure_ascii=True), prompt)
        result = trace[-1]['value']
        self.assertTrue(result['call_attempted'])
        self.assertEqual(result['raw'], raw)
        self.assertIsNone(result['error'])
        self.assertFalse(result['control']['stop_observed'])
        self.assertNotIn('PASS', result)

    def test_checker_partial_and_complete_instructions_are_host_derived(self):
        path, _, args = self.request()
        script = self.render(path)
        trace = self.run_js(script, args)
        fixed = '本次anchor为partial anchor；仅按每条结论与primary_goal的语义相关性分类：相关返回on_topic，否则返回adjacent；不得返回off_topic。逐个完整key恰分类一次，不返回scope-empty或confidence标注。'
        self.assertTrue(trace[0]['calls'][0]['prompt'].startswith(fixed))
        anchor_path = Path(json.loads(path.read_bytes())['anchor']['path'])
        anchor = json.loads(anchor_path.read_bytes())
        anchor['value']['in_scope'] = ['nonempty']
        self.f.write(anchor_path, anchor)
        request = json.loads(path.read_bytes())
        request['anchor'] = ref(anchor_path)
        genesis_path = Path(request['genesis']['path'])
        genesis = json.loads(genesis_path.read_bytes())
        genesis['anchor'] = ref(anchor_path)
        self.f.write(genesis_path, genesis)
        request['genesis'] = ref(genesis_path)
        self.f.write(path, request)
        args.update(request_sha256=ref(path)['sha256'], anchor=anchor['value'])
        prompt = self.run_js(self.render(path), args)[0]['calls'][0]['prompt']
        self.assertFalse(prompt.startswith(fixed))
        for token in ['on_topic', 'adjacent', 'off_topic']:
            self.assertIn(token, prompt)

    def test_checker_preserves_legal_empty_scope_without_new_admission_gate(self):
        path, request, args = self.request()
        conclusion = request['conclusions'][0]
        conclusion['scope'] = ''
        conclusion['id'] = hashlib.sha256(b'implementation::major:issue').hexdigest()[:8]
        conclusion['variants'][0]['finding']['scope'] = ''
        self.f.write(path, request)
        args.update(request_sha256=ref(path)['sha256'], conclusions=request['conclusions'])
        try:
            script = self.render(path)
        except self.mod.ExecutorError as error:
            self.fail('合法空scope被新增准入门拒绝: ' + error.reason)
        raw = {'classifications': [{'key': ['issue', 'major', 'implementation', ''],
                                    'classification': 'adjacent'}]}
        result = self.run_js(script, args, modes=[{'kind': 'resolve', 'value': raw}])[-1]['value']
        self.assertEqual(result['raw'], raw)

    def test_checker_preserves_proto_and_nested_special_finding_fields(self):
        path, request, args = self.request()
        finding = request['conclusions'][0]['variants'][0]['finding']
        finding['__proto__'] = {'note': 'legal-extra'}
        finding['extra'] = {'nested': [{'__proto__': {'value': 1},
                                        'constructor': {'prototype': 'data only'}}]}
        self.f.write(path, request)
        args.update(request_sha256=ref(path)['sha256'], conclusions=request['conclusions'])
        raw = {'classifications': [{'key': ['issue', 'major', 'implementation', 'a.py'],
                                    'classification': 'on_topic'}]}
        result = self.run_js(self.render(path), args, modes=[{'kind': 'resolve', 'value': raw}])[-1]
        self.assertEqual(len(result['calls']), 1, 'legal special finding keys rejected as E_RUN_IDENTITY')
        self.assertIsNone(result['error'])
        self.assertEqual(result['value']['raw'], raw)
        prompt = result['calls'][0]['prompt']
        preserved = json.loads(prompt.split('\nconclusions=', 1)[1])
        self.assertEqual(preserved, request['conclusions'])
        self.assertEqual(preserved[0]['variants'][0]['finding']['__proto__'], {'note': 'legal-extra'})

    def test_checker_accepts_actual_build_empty_and_whitespace_spans(self):
        for field in ('in_scope', 'out_of_scope_hints'):
            for text in ('', ' \t '):
                with self.subTest(field=field, span=text):
                    case = GeneratedScriptTests(self._testMethodName)
                    case.setUp()
                    try:
                        source = case.f.repo / 'scope-span.txt'
                        source.write_text(' \t ', encoding='utf-8')
                        case.f.policy_value['anchor_selection'][field] = [
                            {'source': ref(source), 'start': 0, 'end': len(text.encode('utf-8'))}]
                        case.f.write(case.f.policy, case.f.policy_value)
                        case.f.manifest['evidence']['policy_inputs'] = ref(case.f.policy)
                        path, _, args = case.request()
                        self.assertEqual(args['anchor'][field], [text])
                        try:
                            script = case.render(path)
                        except case.mod.ExecutorError as error:
                            self.fail('valid build span rejected by renderer: ' + error.reason)
                        raw = {'classifications': [{'key': ['issue', 'major', 'implementation', 'a.py'],
                                                    'classification': 'adjacent'}]}
                        result = case.run_js(script, args, modes=[{'kind': 'resolve', 'value': raw}])[-1]
                        self.assertEqual(len(result['calls']), 1)
                        self.assertEqual(result['value']['raw'], raw)
                        prompt = result['calls'][0]['prompt']
                        self.assertTrue(prompt.startswith('按完整anchor'))
                        self.assertIn(json.dumps(args['anchor'], sort_keys=True, separators=(',', ':'),
                                                 ensure_ascii=True), prompt)
                    finally:
                        case.doCleanups()

    def test_checker_timer_is_60000_and_not_audit_300000(self):
        path, _, args = self.request()
        trace = self.run_js(self.render(path), args, steps=[{'kind': 'advance', 'ms': 59999},
            {'kind': 'advance', 'ms': 1}, {'kind': 'resolve', 'index': 0, 'value': {'late': True}}])
        self.assertFalse(trace[0]['returned'])
        self.assertEqual(trace[0]['timers'], [60000])
        self.assertFalse(trace[1]['returned'])
        result = trace[2]['value']
        self.assertTrue(trace[2]['returned'])
        self.assertTrue(result['call_attempted'])
        self.assertIsNone(result['error'])
        self.assertIsNone(result['raw'])
        self.assertEqual(result['control'], {'timeout_ms': 60000, 'stop_observed': True,
                                              'return_reason': 'control_timeout'})
        self.assertEqual(trace[-1]['value'], result)
        self.assertEqual(len(trace[-1]['calls']), 1)

    def test_checker_preserves_falsy_raw_bad_raw_and_real_exceptions(self):
        path, _, args = self.request()
        script = self.render(path)
        for raw in [False, None, '', 'not JSON', {'classifications': 'bad'}, {'verdict': 'PASS'}]:
            with self.subTest(raw=raw):
                result = self.run_js(script, args, modes=[{'kind': 'resolve', 'value': raw}])[-1]['value']
                self.assertEqual(result['raw'], raw)
                self.assertIsNone(result['error'])
                self.assertTrue(result['settled'])
        for kind in ['throw', 'reject']:
            result = self.run_js(script, args, modes=[{'kind': kind, 'message': 'real checker error'}])[-1]['value']
            self.assertTrue(result['call_attempted'])
            self.assertIn('real checker error', result['error'])
            self.assertIsNone(result['raw'])
            self.assertFalse(result['control']['stop_observed'])

    def test_checker_deep_copy_after_success(self):
        path, _, args = self.request()
        trace = self.run_js(self.render(path), args,
            modes=[{'kind': 'resolve', 'value': {'nested': {'value': 'original'}}}],
            steps=[{'kind': 'mutate', 'index': 0}])
        self.assertEqual(trace[-1]['value'], trace[0]['value'])

    def test_checker_args_reject_overrides_before_any_call(self):
        path, _, args = self.request()
        script = self.render(path)
        cases = [None, {}, {**args, 'verified': True}, {**args, 'request_sha256': '0'*64},
            {**args, 'anchor': {**args['anchor'], 'primary_goal': 'changed'}},
            {**args, 'conclusions': []}, {**args, 'identity': {**args['identity'], 'round': 3}}]
        for bad in cases:
            with self.subTest(args=bad):
                result = self.run_js(script, bad)[-1]
                self.assertIn('E_RUN_IDENTITY', result['error'])
                self.assertEqual(result['calls'], [])

    def test_renderer_rejects_unbound_request_and_closed_schema_violations(self):
        path, request, _ = self.request()
        frozen_ref = ref(path)
        path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.mod._render_policy_workflow(frozen_ref)
        self.assertEqual(caught.exception.error_code, 'E_POLICY_SOURCE')
        variants = [{**request, 'verified': True}, {**request, 'required': False},
            {**request, 'checker': None}, {**request, 'reason': 'first_round'},
            {**request, 'checker': {**request['checker'], 'agentType': 'aria:qa-engineer'}},
            {**request, 'checker': {**request['checker'], 'timeout_ms': 300000}},
            {**request, 'checker': {**request['checker'], 'agentId': 'old-agent'}},
            {**request, 'checker': {**request['checker'], 'label': 'audit:client-checker:0'}},
            {**request, 'conclusions': [{**request['conclusions'][0], 'verified': True}]}]
        for bad in variants:
            with self.subTest(request=bad):
                self.f.write(path, bad)
                with self.assertRaises(self.mod.ExecutorError) as caught:
                    self.render(path)
                self.assertEqual(caught.exception.error_code, 'E_POLICY_SOURCE')

    def test_renderer_rejects_wrong_hash_and_invalid_anchor_not_caller_verified(self):
        path, request, _ = self.request()
        anchor_path = Path(request['anchor']['path'])
        original = anchor_path.read_bytes()
        anchor_path.write_bytes(original+b' ')
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.render(path)
        self.assertEqual(caught.exception.error_code, 'E_POLICY_SOURCE')
        anchor = json.loads(original)
        for bad in [{**anchor, 'status': 'missing', 'value': None},
                    {**anchor, 'value': {**anchor['value'], 'primary_goal': ''}},
                    {**anchor, 'verified': True}]:
            self.f.write(anchor_path, bad)
            request['anchor'] = ref(anchor_path)
            genesis_path = Path(request['genesis']['path'])
            genesis = json.loads(genesis_path.read_bytes())
            genesis['anchor'] = ref(anchor_path)
            self.f.write(genesis_path, genesis)
            request['genesis'] = ref(genesis_path)
            self.f.write(path, request)
            with self.assertRaises(self.mod.ExecutorError) as caught:
                self.render(path)
            self.assertEqual(caught.exception.error_code, 'E_POLICY_SOURCE')


class BuildContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="audit-build-contract-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.plugin = self.root / "plugin"
        self.engine = self.plugin / "skills" / "audit-engine"
        for name in ["scripts", "references"]:
            (self.engine / name).mkdir(parents=True)
        shutil.copyfile(EXECUTOR, self.engine / "scripts" / "audit_executor.py")
        for name in ["executor-contract.md", "convergence-algorithm.md", "report-storage.md"]:
            shutil.copyfile(ENGINE / "references" / name, self.engine / "references" / name)
        self.defaults = self.plugin / "skills" / "config-loader" / "DEFAULTS.json"
        self.defaults.parent.mkdir(parents=True)
        self.defaults_value = {"audit": {"require_same_admitted_roles": False,
            "enabled": False, "mode": "adaptive", "max_rounds": 5,
            "checkpoints": {"post_spec": "off", "pre_merge": "off"},
            "adaptive_rules": {"level_1": "off", "level_2": "convergence", "level_3": "challenge"},
            "drift_guard": {"warn_threshold": 0.2, "refocus_threshold": 0.5, "convergence_mode": True},
            "convergence_criteria": {"conclusion_match": True, "unanimous_pass": True}}}
        self.write(self.defaults, self.defaults_value)
        self.config = self.repo / ".aria" / "config.json"
        self.config_value = {"audit": {"enabled": True, "mode": "convergence",
            "require_same_admitted_roles": True,
            "checkpoints": {"post_spec": "convergence"},
            "teams": {"post_spec": ["aria:backend-architect", "aria:qa-engineer", "aria:tech-lead"]}}}
        self.write(self.config, self.config_value)
        self.proposal = self.repo / "openspec" / "changes" / "build-target" / "proposal.md"
        self.proposal.parent.mkdir(parents=True)
        self.proposal.write_text("# Target\nLevel: Standard\n## Why\n验证构建边界\n", encoding="utf-8")
        self.context = self.repo / "context.txt"
        self.context.write_text("明确审计上下文", encoding="utf-8")
        for args in [["git", "init", "-q", str(self.repo)],
                     ["git", "-C", str(self.repo), "-c", "user.name=Fixture", "-c",
                      "user.email=fixture@example.invalid", "commit", "-q", "--allow-empty", "-m", "fixture"]]:
            result = subprocess.run(args, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, "临时 Git fixture 初始化失败")
        head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"],
                              capture_output=True, check=True).stdout.decode().strip()
        self.policy = self.repo / "policy.json"
        text = self.proposal.read_bytes()
        start = text.index("验证".encode())
        self.policy_value = {"schema_version": 1, "context": ref(self.context),
            "spec_source": ref(self.proposal),
            "anchor_selection": {"primary_goal": {"source": ref(self.proposal),
                "start": start, "end": len(text) - 1}, "in_scope": [], "out_of_scope_hints": []},
            "fallback_sources": [{"kind": "proposal", "locator": str(self.proposal), "source": ref(self.proposal)}]}
        self.write(self.policy, self.policy_value)
        self.manifest_path = self.repo / "manifest.json"
        self.run_dir = self.repo / ".aria" / "audit-reports" / "post_spec-R1-client-one-build-target-aggregated"
        self.manifest = {"audit_cycle_id": "cycle-one", "client_round_id": "client-one",
            "checkpoint": "post_spec", "change_id": "build-target", "round": 1,
            "attempt_index": 1, "candidate_sha": head,
            "roles": [{"role_id": name, "agentType": name, "model_alias": "inherit",
                       "prompt": "独立审查\n` ${notExecutable} </script>"}
                      for name in self.config_value["audit"]["teams"]["post_spec"]],
            "single_agent_ms": 120000, "round_ms": 300000, "max_parallel": 2,
            "require_same_admitted_roles": True,
            "evidence": {"schema_version": 1, "cycle_origin": None, "previous_round": None,
                "dispatch_preflight": None, "policy_inputs": ref(self.policy),
                "post_audit_index_path": str(self.run_dir / "audit-index.json"),
                "post_drift_index_path": str(self.run_dir / "drift-index.json"),
                "post_disposition_index_path": str(self.run_dir / "disposition-index.json")}}
        self.mod = load_module(self.engine / "scripts" / "audit_executor.py")

    @staticmethod
    def write(path: Path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encode(value))

    def build(self):
        self.write(self.manifest_path, self.manifest)
        return self.mod.build(self.repo, self.manifest_path, self.run_dir)

    def rejected(self, code: str, reason: str | None = None):
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.build()
        self.assertEqual(caught.exception.error_code, code)
        if reason is not None:
            self.assertEqual(caught.exception.reason, reason)

    def scope(self):
        key = hashlib.sha256(encode(["post_spec", "build-target"])).hexdigest()
        return self.repo / ".aria" / "audit-reports" / "_executor-ledgers" / key

    def record(self):
        return json.loads((self.run_dir / "build-record.json").read_bytes())

    def test_missing_project_and_missing_key_remain_false_without_team_or_evidence(self):
        self.config.unlink()
        self.assertIs(self.mod._load_fixed_policy(self.repo)["require_same_admitted_roles"], False)
        self.write(self.config, {})
        self.assertIs(self.mod._load_fixed_policy(self.repo)["require_same_admitted_roles"], False)
        self.write(self.config, {"audit": {"require_same_admitted_roles": False}})
        self.assertIs(self.mod._load_fixed_policy(self.repo)["require_same_admitted_roles"], False)
        self.assertFalse(self.scope().exists())

    def test_raw_guard_types_reject_in_both_sources(self):
        for source in [self.config, self.defaults]:
            for bad in ["false", None, 0, 1, [], {}]:
                with self.subTest(source=source.name, value=bad):
                    original = source.read_bytes()
                    value = json.loads(original)
                    value["audit"]["require_same_admitted_roles"] = bad
                    self.write(source, value)
                    self.rejected("E_CONFIG_TYPE", "raw_guard_not_boolean")
                    source.write_bytes(original)

    def test_malformed_duplicate_nonfinite_json_rejects_both_sources_and_manifest(self):
        for source in [self.config, self.defaults, self.manifest_path]:
            for bad in [b"{", b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}']:
                with self.subTest(source=source.name, bad=bad):
                    self.write(self.manifest_path, self.manifest)
                    original = source.read_bytes()
                    source.write_bytes(bad)
                    with self.assertRaises(self.mod.ExecutorError) as caught:
                        self.mod.build(self.repo, self.manifest_path, self.run_dir)
                    self.assertEqual(caught.exception.error_code, "E_INPUT_SCHEMA")
                    source.write_bytes(original)

    def test_top_and_audit_must_be_objects(self):
        for source in [self.config, self.defaults]:
            for bad in [[], None, {"audit": []}, {"audit": None}, {"audit": 0}]:
                with self.subTest(source=source.name, value=bad):
                    original = source.read_bytes()
                    self.write(source, bad)
                    self.rejected("E_INPUT_SCHEMA", "config_object_required")
                    source.write_bytes(original)

    def test_defaults_must_exist_and_register_false(self):
        self.defaults.unlink()
        self.rejected("E_CONFIG_SOURCE")
        for bad in [{"audit": {}}, {"audit": {"require_same_admitted_roles": True}}]:
            self.write(self.defaults, bad)
            self.rejected("E_CONFIG_SOURCE", "defaults_guard_registration")

    def test_manifest_cannot_disable_guard(self):
        self.manifest["require_same_admitted_roles"] = False
        self.rejected("E_MANIFEST_MISMATCH", "guard_mismatch")

    def test_team_membership_order_identity_and_duplicates_are_enforced(self):
        original = copy.deepcopy(self.manifest["roles"])
        variants = [original[:2], list(reversed(original)), original + [original[0]],
                    [{**original[0], "role_id": "backend-architect"}, *original[1:]],
                    [{**original[0], "agentType": "backend-architect"}, *original[1:]]]
        for roles in variants:
            with self.subTest(roles=roles):
                self.manifest["roles"] = roles
                self.rejected("E_MANIFEST_MISMATCH", "team_mismatch")

    def test_missing_explicit_team_is_not_filled_from_defaults(self):
        self.config_value["audit"].pop("teams")
        self.write(self.config, self.config_value)
        self.rejected("E_UNSUPPORTED", "explicit_team_required")

    def test_project_team_must_be_nonempty_unique_string_array(self):
        for bad in [[], ["a", "a"], [""], [1], {"convergence": ["a"]}]:
            self.config_value["audit"]["teams"]["post_spec"] = bad
            self.write(self.config, self.config_value)
            self.rejected("E_UNSUPPORTED", "explicit_team_required")

    def test_model_manual_agents_and_backend_overrides_rejected(self):
        for key, value in [("model", "other"), ("agents_config", {}), ("team", ["x"]),
                           ("backend", "other"), ("mode", "convergence")]:
            with self.subTest(key=key):
                self.manifest[key] = value
                self.rejected("E_UNSUPPORTED", "caller_override")
                self.manifest.pop(key)
        self.manifest["roles"][0]["model"] = "other"
        self.rejected("E_UNSUPPORTED", "caller_override")

    def test_fixed_budgets_and_integer_boolean_separation(self):
        for key, bad in [("single_agent_ms", 120001), ("round_ms", 300001), ("max_parallel", 3)]:
            original = self.manifest[key]
            self.manifest[key] = bad
            self.rejected("E_MANIFEST_MISMATCH", "budget_mismatch")
            self.manifest[key] = original
        for key in ["round", "attempt_index", "single_agent_ms", "round_ms", "max_parallel"]:
            original = self.manifest[key]
            self.manifest[key] = True
            self.rejected("E_INPUT_SCHEMA", "integer_required")
            self.manifest[key] = original

    def test_missing_schema_fields_are_not_import_or_path_errors(self):
        for key in ["roles", "evidence", "audit_cycle_id", "candidate_sha"]:
            value = self.manifest.pop(key)
            self.rejected("E_INPUT_SCHEMA", "manifest_keys")
            self.manifest[key] = value

    def test_disabled_guard_build_does_not_force_new_adoption(self):
        self.config_value["audit"]["require_same_admitted_roles"] = False
        self.write(self.config, self.config_value)
        self.manifest["require_same_admitted_roles"] = False
        self.rejected("E_UNSUPPORTED", "guard_disabled_use_legacy")
        self.assertFalse(self.scope().exists())

    def test_mode_and_adaptive_level_are_resolved_from_actual_sources(self):
        self.config_value["audit"]["checkpoints"]["post_spec"] = "adaptive"
        self.config_value["audit"]["mode"] = "adaptive"
        self.write(self.config, self.config_value)
        self.build()
        self.assertEqual(self.record()["effective_config"]["resolved_mode"]["value"], "convergence")

    def test_challenge_off_or_unverifiable_adaptive_refuses(self):
        for mode in ["challenge", "off", "adaptive"]:
            self.config_value["audit"]["checkpoints"]["post_spec"] = mode
            self.write(self.config, self.config_value)
            if mode == "adaptive":
                self.proposal.write_text("# no verifiable level", encoding="utf-8")
                self.rejected("E_POLICY_SOURCE", "spec_level_unverifiable")
            else:
                self.rejected("E_UNSUPPORTED", "convergence_required")

    def test_genesis_closure_reservation_and_source_hashes_independently_recompute(self):
        result = self.build()
        self.assertIs(result["resume_only"], False)
        record = self.record()
        self.assertEqual(record["budgets"], {"single_agent_ms": 120000, "round_ms": 300000, "max_parallel": 2})
        self.assertEqual(record["roles"][0]["label"], "audit:client-one:0")
        for source in [record["manifest"], record["workflow_script"], record["genesis"], record["reservation"], *record["sources"].values()]:
            self.assertEqual(hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest(), source["sha256"])
        genesis = json.loads(Path(record["genesis"]["path"]).read_bytes())
        self.assertEqual(genesis["initial_max_rounds"], 5)
        self.assertNotIn("manifest", genesis)
        self.assertNotIn("build_record", genesis)
        anchor = json.loads(Path(genesis["anchor"]["path"]).read_bytes())
        self.assertEqual(anchor["status"], "present")
        self.assertEqual(anchor["value"]["primary_goal"], "验证构建边界")
        self.assertEqual(anchor["value"]["in_scope"], [])
        closure = json.loads(Path(record["input_closure"]["path"]).read_bytes())
        origins = set()
        for entry in closure["sources"]:
            blob = Path(entry["blob"]["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(blob).hexdigest(), entry["sha256"])
            self.assertEqual(entry["sha256"], entry["blob"]["sha256"])
            self.assertEqual(blob, Path(entry["origin"]).read_bytes())
            self.assertNotIn(entry["origin"], origins)
            origins.add(entry["origin"])
        self.assertIn(str(self.context), origins)
        self.assertIn(str(self.policy), origins)
        self.assertIn(str(self.manifest_path), origins)
        self.assertEqual(len(list((self.scope() / "events").glob("*.json"))), 1)
        script = (self.run_dir / "workflow.js").read_text()
        self.assertTrue(script.startswith("export const meta = {"))
        self.assertNotIn("Date.now", script)
        self.assertNotIn("require(", script)

    def test_policy_missing_hash_bad_span_and_fake_missing_refused_before_reserve(self):
        for mutation in ["hash", "span", "fake_missing", "omit_fallback"]:
            value = copy.deepcopy(self.policy_value)
            if mutation == "hash":
                value["context"]["sha256"] = "0" * 64
            elif mutation == "span":
                value["anchor_selection"]["primary_goal"]["start"] += 1
            elif mutation == "fake_missing":
                value["fallback_sources"][0]["source"] = None
            else:
                value["fallback_sources"] = []
            self.write(self.policy, value)
            self.manifest["evidence"]["policy_inputs"] = ref(self.policy)
            self.rejected("E_POLICY_SOURCE")
            self.assertFalse((self.scope() / "genesis.json").exists())
            self.assertFalse((self.run_dir / "workflow.js").exists())

    def test_existing_scope_null_new_cycle_and_old_previous_refused(self):
        self.build()
        record = self.record()
        self.manifest["client_round_id"] = "client-two"
        self.manifest["attempt_index"] = 2
        self.run_dir = self.run_dir.with_name(self.run_dir.name.replace("client-one", "client-two"))
        for key in ("post_audit_index_path", "post_drift_index_path", "post_disposition_index_path"):
            self.manifest["evidence"][key] = str(self.run_dir / Path(self.manifest["evidence"][key]).name)
        self.rejected("E_PREVIOUS_IDENTITY")
        self.manifest["evidence"]["cycle_origin"] = record["genesis"]
        self.manifest["audit_cycle_id"] = "cycle-two"
        self.rejected("E_PREVIOUS_IDENTITY")
        self.manifest["audit_cycle_id"] = "cycle-one"
        self.manifest["evidence"]["previous_round"] = ref(self.context)
        self.rejected("E_PREVIOUS_IDENTITY")

    def test_all_fixed_source_drift_refuses_without_extra_reservation(self):
        self.build()
        record = self.record()
        for name, source in record["sources"].items():
            with self.subTest(source=name):
                path = Path(source["path"])
                original = path.read_bytes()
                if name == "config":
                    value = json.loads(original)
                    value["audit"]["max_rounds"] = 999
                    path.write_bytes(encode(value))
                else:
                    path.write_bytes(original + b"\n")
                self.rejected("E_SOURCE_DRIFT")
                path.write_bytes(original)
                self.assertEqual(len(list((self.scope() / "events").glob("*.json"))), 1)

    def test_short_posix_lock_refuses_without_script(self):
        self.scope().mkdir(parents=True)
        with (self.scope() / "writer.lock").open("wb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.rejected("E_SCOPE_BUSY")
        self.assertFalse((self.run_dir / "workflow.js").exists())

    def test_pending_identical_resume_and_missing_record_repair_do_not_redispatch(self):
        self.build()
        before = {str(p): p.read_bytes() for p in self.scope().rglob("*") if p.is_file()}
        original = (self.run_dir / "build-record.json").read_bytes()
        self.assertIs(self.build()["resume_only"], True)
        (self.run_dir / "build-record.json").unlink()
        self.assertIs(self.build()["resume_only"], True)
        self.assertEqual((self.run_dir / "build-record.json").read_bytes(), original)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.scope().rglob("*") if p.is_file()})

    def test_pending_changed_prompt_or_input_and_output_conflict_not_overwritten(self):
        self.build()
        original = (self.run_dir / "build-record.json").read_bytes()
        self.manifest["evidence"]["cycle_origin"] = self.record()["genesis"]
        self.manifest["roles"][0]["prompt"] += "changed"
        self.rejected("E_RESOURCE_PENDING")
        self.assertEqual((self.run_dir / "build-record.json").read_bytes(), original)
        self.manifest["roles"][0]["prompt"] = self.manifest["roles"][0]["prompt"][:-7]
        self.manifest["evidence"]["cycle_origin"] = None
        self.context.write_text("changed", encoding="utf-8")
        self.rejected("E_OUTPUT_CONFLICT")

    def test_existing_other_bytes_are_not_overwritten(self):
        self.run_dir.mkdir(parents=True)
        path = self.run_dir / "workflow.js"
        path.write_bytes(b"do not replace")
        self.rejected("E_OUTPUT_CONFLICT")
        self.assertEqual(path.read_bytes(), b"do not replace")
        self.assertFalse((self.scope() / "genesis.json").exists())

    def test_paths_cwd_symlink_and_future_locators(self):
        self.manifest["evidence"]["post_audit_index_path"] = str(self.root / "escape.json")
        self.rejected("E_OUTPUT_CONFLICT")
        self.manifest["evidence"]["post_audit_index_path"] = str(self.run_dir / "audit-index.json")
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "audit-index.json").write_bytes(b"{}")
        self.rejected("E_OUTPUT_CONFLICT")
        (self.run_dir / "audit-index.json").unlink()
        self.run_dir.rmdir()
        self.run_dir.symlink_to(self.root, target_is_directory=True)
        self.rejected("E_OUTPUT_CONFLICT")
        self.run_dir.unlink()
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            self.build()
        finally:
            os.chdir(previous)
        self.assertEqual(self.record()["sources"]["defaults"]["path"], str(self.defaults))

    def test_existing_legacy_same_scope_refuses_but_other_checkpoint_is_not_same_scope(self):
        reports = self.repo / ".aria" / "audit-reports"
        reports.mkdir(parents=True)
        old = reports / "post_spec-R5-old-build-target-aggregated.md"
        old.write_text("---\ncheckpoint: post_spec\ncontext: build-target\n---\n", encoding="utf-8")
        self.rejected("E_PREVIOUS_IDENTITY")
        old.unlink()
        (reports / "pre_merge-R5-old-build-target-aggregated.md").write_text(
            "---\ncheckpoint: pre_merge\ncontext: build-target\n---\n", encoding="utf-8")
        (reports / "unattributed.md").write_text("unknown history", encoding="utf-8")
        self.build()
        genesis = json.loads((self.scope() / "genesis.json").read_bytes())
        observation = json.loads(Path(genesis["origin_observation"]["path"]).read_bytes())
        self.assertTrue(any(item["attribution"] == "UNKNOWN" for item in observation["files"]))

    def snapshot(self):
        return {str(path): path.read_bytes() for directory in (self.scope(), self.run_dir)
                if directory.exists() for path in directory.rglob("*") if path.is_file()}

    def pending_with_independent_leaves(self):
        # 缺少任一个 schema 依赖边都必须拒绝；叶子不与其它来源共用路径。
        leaves = {"policy": self.policy, "context": self.context, "spec": self.proposal}
        for field in ("in_scope", "out_of_scope_hints"):
            path = self.repo / (field + ".txt")
            path.write_bytes(field.encode())
            self.policy_value["anchor_selection"][field] = [
                {"source": ref(path), "start": 0, "end": len(path.read_bytes())}]
            leaves[field] = path
        self.proposal.write_text("# Target\nLevel: Standard\n", encoding="utf-8")
        self.policy_value["spec_source"] = ref(self.proposal)
        title = self.repo / "issue-title.json"
        self.write(title, {"title": "independent goal"})
        raw = title.read_bytes()
        start = raw.index(b"independent goal")
        self.policy_value["anchor_selection"]["primary_goal"] = {
            "source": ref(title), "start": start, "end": start + len(b"independent goal")}
        self.policy_value["fallback_sources"] = [
            {"kind": "proposal", "locator": str(self.proposal), "source": ref(self.proposal)},
            {"kind": "issue_title", "locator": str(title), "source": ref(title)}]
        leaves["fallback_primary"] = title
        self.write(self.policy, self.policy_value)
        self.manifest["evidence"]["policy_inputs"] = ref(self.policy)
        self.build()
        (self.run_dir / "build-record.json").unlink()
        return leaves

    def test_pending_missing_policy_origin_and_live_source_cannot_repair_record(self):
        self.build()
        (self.run_dir / "build-record.json").unlink()
        closure_path = self.run_dir / "input-closure.json"
        closure = json.loads(closure_path.read_bytes())
        closure["sources"] = [item for item in closure["sources"] if item["origin"] != str(self.policy)]
        self.write(closure_path, closure)
        self.policy.unlink()
        before = self.snapshot()
        self.rejected("E_OUTPUT_CONFLICT", "incomplete_pending_closure")
        self.assertEqual(self.snapshot(), before)

    def test_pending_recursive_leaf_origins_cannot_be_omitted_even_when_live_sources_exist(self):
        leaves = self.pending_with_independent_leaves()
        closure_path = self.run_dir / "input-closure.json"
        original = closure_path.read_bytes()
        for kind, path in leaves.items():
            with self.subTest(leaf=kind):
                closure = json.loads(original)
                closure["sources"] = [item for item in closure["sources"] if item["origin"] != str(path)]
                self.write(closure_path, closure)
                before = self.snapshot()
                try:
                    self.rejected("E_OUTPUT_CONFLICT", "incomplete_pending_closure")
                    self.assertEqual(self.snapshot(), before)
                finally:
                    closure_path.write_bytes(original)
                    (self.run_dir / "build-record.json").unlink(missing_ok=True)

    def test_pending_leaf_hash_and_blob_mapping_are_bound_without_overwrite(self):
        self.pending_with_independent_leaves()
        closure_path = self.run_dir / "input-closure.json"
        original = closure_path.read_bytes()
        for mutation in ("origin", "hash", "blob", "live_blob_alias", "missing_blob", "missing_genesis_mapping",
                         "missing_anchor_mapping", "missing_observations_mapping"):
            with self.subTest(mutation=mutation):
                closure = json.loads(original)
                entry = next(item for item in closure["sources"] if item["origin"] == str(self.context))
                removed = None
                blob_path = None
                if mutation == "origin":
                    entry["origin"] = str(self.repo / "unbound-context.txt")
                    Path(entry["origin"]).write_bytes(self.context.read_bytes())
                elif mutation == "hash":
                    entry["sha256"] = "0" * 64
                elif mutation == "blob":
                    entry["blob"] = ref(self.policy)
                elif mutation == "live_blob_alias":
                    entry["blob"] = ref(self.context)
                elif mutation == "missing_blob":
                    blob_path = Path(entry["blob"]["path"])
                    removed = blob_path.read_bytes()
                    blob_path.unlink()
                else:
                    genesis = json.loads((self.scope() / "genesis.json").read_bytes())
                    if mutation == "missing_genesis_mapping":
                        origin = str(self.scope() / "genesis.json")
                    elif mutation == "missing_anchor_mapping":
                        origin = genesis["anchor"]["path"]
                    else:
                        anchor = json.loads(Path(genesis["anchor"]["path"]).read_bytes())
                        origin = anchor["observations"]["path"]
                    closure["sources"] = [item for item in closure["sources"] if item["origin"] != origin]
                closure["sources"].sort(key=lambda item: (item["origin"], item["sha256"]))
                self.write(closure_path, closure)
                before = self.snapshot()
                try:
                    self.rejected("E_OUTPUT_CONFLICT")
                    self.assertEqual(self.snapshot(), before)
                finally:
                    closure_path.write_bytes(original)
                    if blob_path is not None and removed is not None:
                        blob_path.write_bytes(removed)
                    (self.run_dir / "build-record.json").unlink(missing_ok=True)

    def test_pending_full_recursive_closure_restores_identical_record_without_new_blobs(self):
        self.pending_with_independent_leaves()
        before = self.snapshot()
        result = self.build()
        self.assertIs(result["resume_only"], True)
        after = self.snapshot()
        after.pop(str(self.run_dir / "build-record.json"))
        self.assertEqual(after, before)
        record_bytes = (self.run_dir / "build-record.json").read_bytes()
        (self.run_dir / "build-record.json").unlink()
        self.assertIs(self.build()["resume_only"], True)
        self.assertEqual((self.run_dir / "build-record.json").read_bytes(), record_bytes)

    def test_pending_frozen_external_sources_do_not_require_live_bytes(self):
        leaves = self.pending_with_independent_leaves()
        self.assertIs(self.build()["resume_only"], True)
        record_path = self.run_dir / "build-record.json"
        expected = record_path.read_bytes()
        record_path.unlink()
        for mutation in ("remove", "replace"):
            for kind, path in leaves.items():
                with self.subTest(mutation=mutation, leaf=kind):
                    original = path.read_bytes()
                    if mutation == "remove":
                        path.unlink()
                    else:
                        path.write_bytes(b"new live bytes are not frozen input")
                    before = self.snapshot()
                    try:
                        try:
                            result = self.build()
                        except self.mod.ExecutorError as error:
                            self.fail(f"frozen {kind} still requires live bytes: {error.error_code}/{error.reason}")
                        self.assertIs(result["resume_only"], True)
                        self.assertTrue(record_path.exists())
                        self.assertEqual(record_path.read_bytes(), expected)
                        after = self.snapshot()
                        after.pop(str(record_path))
                        self.assertEqual(after, before)
                    finally:
                        path.write_bytes(original)
                        record_path.unlink(missing_ok=True)

    def test_pending_frozen_adaptive_spec_is_not_reselected_from_live_tree(self):
        self.config_value["audit"]["checkpoints"]["post_spec"] = "adaptive"
        self.write(self.config, self.config_value)
        self.pending_with_independent_leaves()
        self.assertIs(self.build()["resume_only"], True)
        record_path = self.run_dir / "build-record.json"
        expected = record_path.read_bytes()
        record_path.unlink()
        self.proposal.unlink()
        archive = self.repo / "openspec" / "archive" / "old-build-target" / "proposal.md"
        archive.parent.mkdir(parents=True)
        archive.write_text("# New live proposal\nLevel: Full\n", encoding="utf-8")
        before = self.snapshot()
        try:
            result = self.build()
        except self.mod.ExecutorError as error:
            self.fail(f"adaptive resume did not use frozen spec: {error.error_code}/{error.reason}")
        self.assertIs(result["resume_only"], True)
        self.assertEqual(record_path.read_bytes(), expected)
        after = self.snapshot()
        after.pop(str(record_path))
        self.assertEqual(after, before)

    def test_bootstrap_directory_symlink_history_is_not_an_empty_scan(self):
        history = self.root / "old-reports"
        history.mkdir()
        (history / "post_spec-R5-old-build-target-aggregated.md").write_text(
            "---\ncheckpoint: post_spec\ncontext: build-target\n---\n", encoding="utf-8")
        reports = self.run_dir.parent
        reports.mkdir(parents=True)
        direct = reports / "old-reports"
        shutil.copytree(history, direct)
        self.rejected("E_PREVIOUS_IDENTITY", "existing_scope_history_no_migration")
        shutil.rmtree(direct)
        direct.symlink_to(history, target_is_directory=True)
        self.rejected("E_POLICY_SOURCE", "historical_symlink_unattributed")
        self.assertFalse((self.scope() / "genesis.json").exists())
        self.assertFalse((self.scope() / "events").exists())

    def test_bootstrap_walk_errors_are_not_a_completed_empty_scan(self):
        # 注入唯一无法稳定用 chmod 触发的 OS 错误（测试可能由 root 运行）。
        from unittest.mock import patch
        def broken_walk(_, *, followlinks, onerror=None):
            self.assertIs(followlinks, False)
            if onerror is not None:
                onerror(PermissionError("fixture scan denied"))
            return iter(())
        with patch.object(self.mod.os, "walk", broken_walk):
            self.rejected("E_POLICY_SOURCE", "historical_scan_unreadable")
        self.assertFalse((self.scope() / "genesis.json").exists())

    def test_bootstrap_current_manifest_in_run_dir_is_not_history_or_overwritten(self):
        self.write(self.manifest_path, self.manifest)
        expected = self.manifest_path.read_bytes()
        root_path = self.manifest_path
        self.manifest_path = self.run_dir / "manifest.json"
        self.manifest_path.parent.mkdir(parents=True)
        self.manifest_path.write_bytes(expected)
        root_path.unlink()
        try:
            result = self.mod.build(self.repo, self.manifest_path, self.run_dir)
        except self.mod.ExecutorError as error:
            self.fail("current manifest rejected as historical cycle: " + error.error_code)
        self.assertIs(result["resume_only"], False)
        self.assertEqual(self.manifest_path.read_bytes(), expected)
        self.assertEqual(self.record()["manifest"], ref(self.manifest_path))
        genesis = json.loads((self.scope() / "genesis.json").read_bytes())
        observation = json.loads(Path(genesis["origin_observation"]["path"]).read_bytes())
        self.assertNotIn(str(self.manifest_path), [item["file"]["path"] for item in observation["files"]])
        self.assertIs(self.build()["resume_only"], True)

    def test_bootstrap_manifest_exclusion_does_not_hide_real_history_in_same_run_dir(self):
        self.manifest_path = self.run_dir / "manifest.json"
        self.run_dir.mkdir(parents=True)
        old = self.run_dir / "old-result.json"
        self.write(old, {"identity": {"checkpoint": "post_spec", "change_id": "build-target"}})
        self.rejected("E_PREVIOUS_IDENTITY", "existing_scope_history_no_migration")
        self.assertFalse((self.scope() / "genesis.json").exists())

    def test_bootstrap_unbound_manifest_shaped_file_is_still_history(self):
        reports = self.run_dir.parent
        reports.mkdir(parents=True)
        other = reports / "other-manifest.json"
        self.write(other, self.manifest)
        self.rejected("E_PREVIOUS_IDENTITY", "existing_scope_history_no_migration")
        self.assertEqual(other.read_bytes(), encode(self.manifest))

    def test_bootstrap_other_change_and_unknown_files_remain_observed_not_blocked(self):
        reports = self.run_dir.parent
        reports.mkdir(parents=True)
        self.write(reports / "other-result.json", {"identity": {
            "checkpoint": "post_spec", "change_id": "another-change"}})
        (reports / "unknown.txt").write_bytes(b"unknown")
        self.build()
        genesis = json.loads((self.scope() / "genesis.json").read_bytes())
        observation = json.loads(Path(genesis["origin_observation"]["path"]).read_bytes())
        self.assertEqual({item["attribution"] for item in observation["files"]}, {"OTHER_SCOPE", "UNKNOWN"})

    def test_bootstrap_longer_ids_are_scoped_consistently_in_changes_and_archive(self):
        longer = "build-target-extra"
        for location in ("changes", "archive"):
            for with_context in (False, True):
                for same_scope in (False, True):
                    with self.subTest(location=location, context=with_context, same_scope=same_scope):
                        case = BuildContractTests(self._testMethodName)
                        case.setUp()
                        try:
                            directory = longer if location == "changes" else "2026-01-01-" + longer
                            (case.repo / "openspec" / location / directory).mkdir(parents=True)
                            reported = case.manifest["change_id"] if same_scope else longer
                            report = case.run_dir.parent / f"post_spec-R1-old-{reported}-aggregated.md"
                            report.parent.mkdir(parents=True, exist_ok=True)
                            context = f"context: {reported}\n" if with_context else ""
                            report.write_text("---\ncheckpoint: post_spec\n" + context + "---\n", encoding="utf-8")
                            if same_scope:
                                case.rejected("E_PREVIOUS_IDENTITY", "existing_scope_history_no_migration")
                                self.assertFalse((case.scope() / "genesis.json").exists())
                                self.assertFalse((case.scope() / "events").exists())
                            else:
                                try:
                                    result = case.build()
                                except case.mod.ExecutorError as error:
                                    self.fail(f"other registered ID blocked bootstrap: {error.error_code}/{error.reason}")
                                self.assertIs(result["resume_only"], False)
                                genesis = json.loads((case.scope() / "genesis.json").read_bytes())
                                observation = json.loads(Path(genesis["origin_observation"]["path"]).read_bytes())
                                row = next(item for item in observation["files"] if item["file"]["path"] == str(report))
                                self.assertEqual(row["attribution"], "OTHER_SCOPE")
                        finally:
                            case.doCleanups()

    def test_cli_invalid_team_containers_return_structured_errors_without_reservation(self):
        for teams in (None, [], "invalid", True, 1):
            with self.subTest(teams=teams):
                self.config_value["audit"]["teams"] = teams
                self.write(self.config, self.config_value)
                self.write(self.manifest_path, self.manifest)
                result = subprocess.run([sys.executable, "-I", "-B", str(self.engine / "scripts" / "audit_executor.py"),
                    "build", "--repo-path", str(self.repo), "--manifest", str(self.manifest_path),
                    "--output-dir", str(self.run_dir)], cwd=self.root, capture_output=True, check=False)
                self.assertNotEqual(result.returncode, 0)
                try:
                    error = json.loads(result.stderr)
                except ValueError:
                    self.fail("invalid teams container escaped as a non-JSON CLI error")
                self.assertEqual(error["error_code"], "E_UNSUPPORTED")
                self.assertEqual(error["reason"], "explicit_team_required")
                self.assertEqual(error["input_ref"], str(self.config))
                self.assertFalse((self.scope() / "genesis.json").exists())
                self.assertFalse((self.scope() / "events").exists())

    def test_cli_adaptive_invalid_utf8_returns_policy_error_without_reservation(self):
        self.config_value["audit"]["checkpoints"]["post_spec"] = "adaptive"
        self.write(self.config, self.config_value)
        self.proposal.write_bytes(self.proposal.read_bytes() + b"\xff")
        source = ref(self.proposal)
        self.policy_value["spec_source"] = source
        self.policy_value["anchor_selection"]["primary_goal"]["source"] = source
        self.policy_value["fallback_sources"][0]["source"] = source
        self.write(self.policy, self.policy_value)
        self.manifest["evidence"]["policy_inputs"] = ref(self.policy)
        self.write(self.manifest_path, self.manifest)
        result = subprocess.run([sys.executable, "-I", "-B", str(self.engine / "scripts" / "audit_executor.py"),
            "build", "--repo-path", str(self.repo), "--manifest", str(self.manifest_path),
            "--output-dir", str(self.run_dir)], cwd=self.root, capture_output=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        try:
            error = json.loads(result.stderr)
        except ValueError:
            self.fail("invalid adaptive UTF-8 escaped as a non-JSON CLI error")
        self.assertEqual(error["error_code"], "E_POLICY_SOURCE")
        self.assertEqual(error["reason"], "invalid_proposal_utf8")
        self.assertEqual(error["input_ref"], str(self.proposal))
        self.assertFalse((self.scope() / "genesis.json").exists())
        self.assertFalse((self.scope() / "events").exists())

    def test_cli_uses_explicit_repo_and_collect_fails_closed(self):
        self.write(self.manifest_path, self.manifest)
        script = self.engine / "scripts" / "audit_executor.py"
        result = subprocess.run([sys.executable, "-I", "-B", str(script), "build", "--repo-path",
            str(self.repo), "--manifest", str(self.manifest_path), "--output-dir", str(self.run_dir)],
            cwd=self.root, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIs(json.loads(result.stdout)["resume_only"], False)
        before = self.snapshot()
        failed = subprocess.run([sys.executable, "-I", "-B", str(script), "collect"],
                                cwd=self.root, capture_output=True, check=False)
        self.assertEqual(failed.returncode, 2, "缺少 collect 必需参数应报 CLI 参数错误")
        self.assertNotIn(b"Traceback", failed.stderr)
        self.assertEqual(self.snapshot(), before)


# TASK-006 fixtures are synthetic and live only in a fresh temporary directory.
class NativeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.f = BuildContractTests('test_missing_project_and_missing_key_remain_false_without_team_or_evidence')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.build()
        self.mod = self.f.mod
        self.native_path = self.f.run_dir / 'native.json'
        self.index_path = self.f.run_dir / 'audit-index.json'
        record = self.f.record()
        self.native = {'runId': 'synthetic-run', 'startTime': 1000, 'durationMs': 300020,
            'status': 'completed', 'agentCount': 1,
            'script': (self.f.run_dir / 'workflow.js').read_text(),
            'scriptPath': 'not-proof-of-executed-content.js',
            'args': {'identity': record['identity'], 'manifest_sha256': record['manifest']['sha256']},
            'workflowProgress': [{'type': 'phase', 'title': 'Audit'},
                {'type': 'workflow_agent', 'index': 71, 'label': record['roles'][0]['label'],
                 'agentType': record['roles'][0]['agentType'], 'agentId': 'synthetic-agent',
                 'model': 'observed-model', 'queuedAt': 1000, 'startedAt': 1000,
                 'durationMs': 120000, 'state': 'done'}],
            'result': {'schema_version': 1, 'identity': record['identity'],
                'manifest_sha256': record['manifest']['sha256'],
                'control': {'round_timer_ms': 300000, 'stop_observed': True,
                            'return_reason': 'control_timeout'},
                'results': [{**{k: role[k] for k in ('index', 'role_id', 'agentType', 'label')},
                    'attempted': i == 0, 'settled': i == 0,
                    'raw': StatePartitionTests.valid_raw() if i == 0 else None, 'error': None}
                    for i, role in enumerate(record['roles'])]}}
        self.links = []

    def capture(self):
        self.f.write(self.native_path, self.native)
        self.index = {'schema_version': 1, 'identity': self.f.record()['identity'],
            'attempt_index': 1, 'workflow_run_id': 'synthetic-run',
            'native_record': {**ref(self.native_path), 'path': 'native.json'},
            'termination_refs': self.links}
        self.f.write(self.index_path, self.index)

    def classify(self, inputs=None):
        # Baseline has no classifier: an empty result is a behavioral failure, not ImportError.
        fn = getattr(self.mod, '_classify_native', lambda *a, **kw: {})
        return fn(self.f.repo, self.f.manifest_path, self.f.run_dir / 'build-record.json',
                  'synthetic-run', self.native_path, self.index_path, inputs=inputs)

    def rejected(self, code):
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.classify()
        self.assertEqual(caught.exception.error_code, code)

    def test_all_settled_requires_complete_attempt_and_settlement(self):
        roles = self.f.record()['roles']
        template = copy.deepcopy(self.native['workflowProgress'][1])
        nodes = []
        for index, role in enumerate(roles):
            node = copy.deepcopy(template)
            node.update(label=role['label'], agentType=role['agentType'],
                        agentId=f'all-settled-agent-{index}', queuedAt=1000 + index * 5000,
                        startedAt=1000 + index * 5000, durationMs=1000)
            nodes.append(node)
        self.native['workflowProgress'] = self.native['workflowProgress'][:1] + nodes
        self.native['agentCount'] = len(nodes)
        self.native['durationMs'] = 20000
        self.native['result']['control'].update(stop_observed=False, return_reason='all_settled')
        for seat in self.native['result']['results']:
            seat.update(attempted=True, settled=True, raw=StatePartitionTests.valid_raw(), error=None)
        self.capture()
        healthy = copy.deepcopy(self.native)
        value = self.classify()
        self.assertEqual([seat['execution_state'] for seat in value['roles']], ['completed_admitted'] * 3)
        for mutation in ('not_dispatched', 'not_settled'):
            with self.subTest(mutation=mutation):
                self.native = copy.deepcopy(healthy)
                if mutation == 'not_dispatched':
                    self.native['result']['results'][-1].update(attempted=False, settled=False, raw=None)
                    self.native['workflowProgress'].pop()
                    self.native['agentCount'] -= 1
                else:
                    self.native['result']['results'][0].update(settled=False, raw=None)
                self.capture()
                self.rejected('E_NATIVE_EVIDENCE')

    def test_control_timeout_accepts_legitimate_incomplete_snapshots(self):
        self.capture()
        states = [seat['execution_state'] for seat in self.classify()['roles']]
        self.assertEqual(states, ['completed_admitted', 'not_dispatched', 'not_dispatched'])
        self.native['result']['results'][0].update(settled=False, raw=None)
        self.capture()
        self.assertEqual(self.classify()['roles'][0]['execution_state'], 'completed_no_result')
        self.native['workflowProgress'][1]['state'] = 'progress'
        self.native['workflowProgress'][1].pop('durationMs')
        self.capture()
        seat = self.classify()['roles'][0]
        self.assertEqual(seat['execution_state'], 'dispatched_no_completion')
        self.assertIsNone(seat['completed_at_ms'])
        self.assertEqual(seat['termination_evidence'], 'unknown')

    def interrupt(self, body='[Request interrupted by user]', line=2):
        node = self.native['workflowProgress'][1]
        node['state'] = 'progress'
        node.pop('durationMs', None)
        seat = self.native['result']['results'][0]
        seat.update(settled=False, raw=None)
        self.event = {'type': 'user', 'agentId': node['agentId'], 'uuid': 'synthetic-event',
                      'message': {'role': 'user', 'content': [{'type': 'text', 'text': body}]}}
        log = self.f.run_dir / 'explicit-log.jsonl'
        log.parent.mkdir(parents=True, exist_ok=True)
        # LF byte lines: U+2028/U+2029 must NOT turn the following event into line 4.
        prefix = json.dumps({'text': 'before middle after'}, ensure_ascii=False).encode()
        log.write_bytes(prefix + b'\n' + encode(self.event) + b'\n')
        self.links = [{'native_pointer': '/workflowProgress/1', 'agent_id': node['agentId'],
            'event': {'file': {**ref(log), 'path': 'explicit-log.jsonl'}, 'line': line,
                      'agent_id': node['agentId'], 'event_uuid': self.event['uuid']}}]
        return log

    def test_complete_mapping_raw_refs_and_two_clocks(self):
        self.capture()
        value = self.classify()
        self.assertEqual(value.get('native_deadline_ms'), 301000)
        self.assertEqual(value.get('native_duration_ms'), 300020)
        self.assertEqual(value.get('control_native_alignment'), 'unknown')
        self.assertEqual(value.get('control_origin'), 'timer_installation')
        self.assertEqual(value.get('control_timer_ms'), 300000)
        roles = value.get('roles', [])
        self.assertEqual(len(roles), 3)
        self.assertEqual(roles[0]['execution_state'], 'completed_admitted')
        self.assertEqual(roles[0]['completed_at_ms'], 121000)
        self.assertEqual(roles[0]['native_ref']['pointer'], '/workflowProgress/1')
        self.assertEqual(roles[0]['raw_ref']['pointer'], '/result/results/0/raw')
        self.assertEqual(roles[0]['raw_sha256'], hashlib.sha256(StatePartitionTests.valid_raw().encode()).hexdigest())
        self.assertEqual(roles[0]['actual_model'], 'observed-model')
        self.assertEqual(roles[1]['execution_state'], 'not_dispatched')

    def test_run_script_args_and_index_identity_reject(self):
        original = copy.deepcopy(self.native)
        cases = [('runId', 'other'), ('script', original['script'] + '\n'),
                 ('args', {}), ('args', {**original['args'], 'extra': True})]
        for key, bad in cases:
            with self.subTest(key=key):
                self.native = copy.deepcopy(original)
                self.native[key] = bad
                self.capture()
                self.rejected('E_RUN_IDENTITY')
        self.native = original
        for key, bad in [('workflow_run_id', 'other'), ('attempt_index', True),
                         ('identity', {**self.f.record()['identity'], 'round': 2})]:
            with self.subTest(index=key):
                self.capture()
                self.index[key] = bad
                self.f.write(self.index_path, self.index)
                self.rejected('E_NATIVE_EVIDENCE')

    def test_bad_mapping_snapshots_and_counts_are_not_empty_population(self):
        original = copy.deepcopy(self.native)
        def duplicate(v):
            v['workflowProgress'].append(copy.deepcopy(v['workflowProgress'][1])); v['agentCount'] = 2
        mutations = [duplicate,
            lambda v: v.update(agentCount=2), lambda v: v.update(agentCount=True),
            lambda v: v.update(status='running'), lambda v: v.pop('result'),
            lambda v: v['workflowProgress'][1].update(label='audit:other:0'),
            lambda v: v['workflowProgress'][1].update(agentType='aria:other'),
            lambda v: v['result']['results'][0].update(attempted=False),
            lambda v: v['result']['results'][1].update(attempted=True),
            lambda v: v['result']['results'][0].update(index=True),
            lambda v: v['result']['results'][1].update(raw='preview'),
            lambda v: v['result']['results'].pop(),
            lambda v: v['workflowProgress'][1].pop('agentId')]
        for i, mutate in enumerate(mutations):
            with self.subTest(case=i):
                self.native = copy.deepcopy(original); mutate(self.native); self.capture()
                self.rejected('E_NATIVE_EVIDENCE')

    def test_time_and_unknown_state_reject_without_erasing_C(self):
        original = copy.deepcopy(self.native)
        cases = [('queuedAt', True), ('queuedAt', 999), ('startedAt', 999),
                 ('durationMs', -1), ('durationMs', 1.0), ('startedAt', None)]
        for key, bad in cases:
            with self.subTest(field=key, bad=bad):
                self.native = copy.deepcopy(original); self.native['workflowProgress'][1][key] = bad
                self.capture(); self.rejected('E_NATIVE_TIME')
        self.native = copy.deepcopy(original); self.native['workflowProgress'][1].pop('durationMs')
        self.capture(); self.rejected('E_NATIVE_TIME')
        self.native = copy.deepcopy(original); self.native['workflowProgress'][1]['state'] = 'mystery'
        self.capture(); self.rejected('E_NATIVE_SCHEMA')
        self.native = copy.deepcopy(original); self.native['workflowProgress'][1]['state'] = 'progress'
        self.capture(); self.rejected('E_NATIVE_EVIDENCE')

    def test_explicit_interruption_LF_lines_and_frozen_live_growth(self):
        log = self.interrupt(); self.capture()
        value = self.classify()
        self.assertEqual(len(value.get('roles', [])), 3)
        seat = value['roles'][0]
        self.assertEqual(seat['termination_evidence'], 'interrupted_observed')
        self.assertIsNone(seat['completed_at_ms'])
        self.assertTrue(seat['unfinished_at_native_deadline'])
        captured = self.mod._Inputs()
        before = self.classify(inputs=captured)
        frozen = self.mod._FrozenInputs(dict(captured.raw))
        log.write_bytes(log.read_bytes() + encode({'late': 'not an old vote'}) + b'\n')
        self.native['result']['results'][0].update(settled=True, raw=StatePartitionTests.valid_raw())
        self.f.write(self.native_path, self.native)
        self.assertEqual(self.classify(inputs=frozen), before)
        self.rejected('E_NATIVE_EVIDENCE')
        bad = dict(captured.raw); bad[str(log)] += b'changed'
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.classify(inputs=self.mod._FrozenInputs(bad))
        self.assertEqual(caught.exception.error_code, 'E_NATIVE_EVIDENCE')

    def test_wrong_termination_line_uuid_agent_hash_role_and_full_body_reject(self):
        for kind in ['line', 'uuid', 'agent', 'hash', 'type', 'role', 'substring', 'pointer', 'run']:
            with self.subTest(kind=kind):
                log = self.interrupt()
                link = self.links[0]
                if kind == 'line': link['event']['line'] = 1
                elif kind == 'uuid': link['event']['event_uuid'] = 'wrong'
                elif kind == 'agent': link['agent_id'] = 'wrong'
                elif kind == 'hash': link['event']['file']['sha256'] = '0' * 64
                elif kind == 'pointer': link['native_pointer'] = '/workflowProgress/0'
                elif kind in ('type', 'role', 'substring'):
                    if kind == 'type': self.event['type'] = 'assistant'
                    elif kind == 'role': self.event['message']['role'] = 'assistant'
                    else: self.event['message']['content'][0]['text'] += ' extra'
                    log.write_bytes(b'{}\n' + encode(self.event) + b'\n')
                    link['event']['file']['sha256'] = ref(log)['sha256']
                self.capture()
                if kind == 'run':
                    self.index['workflow_run_id'] = 'other'; self.f.write(self.index_path, self.index)
                self.rejected('E_NATIVE_EVIDENCE')

    def test_unfrozen_bad_raw_retains_type_and_explicit_drift_termination_link(self):
        self.native['result']['results'][0]['raw'] = {'vote': 'PASS'}
        self.capture(); value = self.classify()
        self.assertEqual(len(value.get('roles', [])), 3)
        seat = value['roles'][0]
        self.assertEqual(seat['execution_state'], 'completed_parse_error')
        self.assertEqual(self.mod._pointer(self.native, seat['raw_ref']['pointer']), {'vote': 'PASS'})
        self.assertEqual(seat['raw_sha256'], ref(self.native_path)['sha256'])
        self.interrupt('[Request interrupted by user for tool use]'); self.capture()
        # Same TerminationLink parser for drift, without claiming drift policy/collect ran.
        drift_index = {**self.index, 'kind': 'workflow', 'request': ref(self.index_path), 'tool_failure': None}
        links = self.mod._verify_termination(self.native, drift_index, self.index_path, self.mod._Inputs())
        self.assertEqual(links['/workflowProgress/1']['line'], 2)
        self.links = []; self.capture()
        self.assertEqual(self.classify()['roles'][0]['termination_evidence'], 'unknown')
        self.assertIsNone(self.classify()['roles'][0]['completed_at_ms'])

    def test_index_locator_and_native_surrogate_script_fail_closed(self):
        self.capture()
        other = self.f.run_dir / 'other-index.json'
        other.write_bytes(self.index_path.read_bytes())
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.mod._classify_native(self.f.repo, self.f.manifest_path,
                self.f.run_dir / 'build-record.json', 'synthetic-run', self.native_path, other)
        self.assertEqual(caught.exception.error_code, 'E_NATIVE_EVIDENCE')
        self.native['script'] = '\ud800'; self.capture()
        self.rejected('E_RUN_IDENTITY')

    def test_known_late_C_and_raw_not_backfilled_from_preview(self):
        node = self.native['workflowProgress'][1]
        node.update(queuedAt=201000, startedAt=201000, durationMs=110000)
        self.native['resultPreview'] = StatePartitionTests.valid_raw()
        self.native['result']['results'][0].update(settled=False, raw=None)
        self.capture(); value = self.classify()
        self.assertEqual(len(value.get('roles', [])), 3)
        seat = value['roles'][0]
        self.assertEqual(seat['completed_at_ms'], 311000)
        self.assertEqual(seat['execution_state'], 'completed_late')
        self.assertEqual(seat['termination_evidence'], 'completed')
        self.assertIsNone(seat['raw_ref']); self.assertIsNone(seat['late_raw_ref'])
        self.assertIsNone(seat['report']); self.assertIsNone(seat['parse_error'])


class StatePartitionTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module(EXECUTOR)

    @staticmethod
    def valid_raw():
        return '{"vote":"PASS","coverage_complete":true,"findings":[],"pending":[],"prior_findings":[]}'

    def classify(self, t0, node, raw, **kw):
        fn = getattr(self.mod, '_classify_seat', lambda *a, **kw: {})
        return fn(t0, node, raw, **kw)

    def test_all_portable_classification_vectors_use_real_core(self):
        path = ENGINE / 'tests/fixtures/audit_executor/boundary-cases.json'
        for vector in json.loads(path.read_bytes())['classification_vectors']:
            v = vector['input']
            with self.subTest(vector=vector['id']):
                value = self.classify(v['native_start_time_ms'], v['native_node'], v['raw'])
                expected = vector['expected']
                for k, source in [('completed_at_ms', 'C_ms'), ('execution_state', 'execution_state'),
                    ('unfinished_at_native_deadline', 'unfinished_at_native_deadline'),
                    ('dispatched_at_or_after_native_deadline', 'dispatched_at_or_after_native_deadline')]:
                    self.assertEqual(value.get(k, 'MISSING'), expected[source])
                self.assertEqual(value.get('late_raw_sha256'), expected['late_raw_sha256'])

    def test_raw_contract_revise_full_findings_and_no_scope_normalization(self):
        node = {'state': 'done', 'queuedAt': 0, 'startedAt': 0, 'durationMs': 1,
                'type': 'workflow_agent', 'agentId': 'synthetic', 'agentType': 'aria:qa-engineer',
                'label': 'synthetic', 'model': None}
        finding = {'severity': 'major', 'type': 'risk', 'category': 'testing', 'scope': ' A/../B ',
                   'file': '', 'failure_scenario': '', 'line': 1, 'extra': {'retained': True}}
        report = json.loads(self.valid_raw()); report.update(vote='REVISE', findings=[finding])
        value = self.classify(0, node, json.dumps(report))
        self.assertEqual(value.get('report'), report)
        bads = [False, 1, {}, [], '```JSON\n'+self.valid_raw()+'\n```',
                self.valid_raw().replace('true', '1'), self.valid_raw().replace('"PASS"', '"SKIP"'),
                self.valid_raw()[:-1] + ',"n":1e999}', self.valid_raw()[:-1] + ',"n":Infinity}']
        for changes in [{'vote': 'PASS'}, {'coverage_complete': 1}, {'pending': None}, {'prior_findings': {}}]:
            bads.append(json.dumps({**report, **changes}))
        for changes in [{'line': True}, {'line': 0}, {'scope': None}, {'severity': 'Major'},
                        {'category': 'security'}, {'type': 'bug'}, {'file': 0}, {'failure_scenario': []}]:
            bads.append(json.dumps({**report, 'findings': [{**finding, **changes}]}))
        for raw in bads:
            with self.subTest(raw=raw):
                value = self.classify(0, node, raw)
                self.assertEqual(value.get('execution_state'), 'completed_parse_error')
                self.assertIsNone(value.get('report'))
        for changes in [{'coverage_complete': False}, {'pending': [1]}, {'findings': [finding]}]:
            invalid = {**json.loads(self.valid_raw()), **changes}
            self.assertEqual(self.classify(0, node, json.dumps(invalid)).get('execution_state'), 'completed_parse_error')
            invalid['vote'] = 'REVISE'
            self.assertEqual(self.classify(0, node, json.dumps(invalid)).get('execution_state'), 'completed_admitted')

    def test_after_D_dispatch_and_late_priority(self):
        node = {'state': 'done', 'queuedAt': 300010, 'startedAt': 300010, 'durationMs': 5,
                'type': 'workflow_agent', 'agentId': 'synthetic', 'agentType': 'aria:qa-engineer',
                'label': 'synthetic', 'model': None}
        for raw in [None, False, 'bad', self.valid_raw()]:
            with self.subTest(raw=raw):
                value = self.classify(0, node, raw)
                self.assertEqual(value.get('execution_state'), 'completed_late')
                self.assertIs(value.get('dispatched_at_or_after_native_deadline'), True)
                self.assertFalse(value.get('unfinished_at_native_deadline'))
                self.assertEqual(value.get('completed_at_ms'), 300015)
                self.assertIsNone(value.get('report')); self.assertIsNone(value.get('parse_error'))

    def test_historical_partial_replay_counts_provenance_and_raw_seams(self):
        root = ENGINE / 'tests/fixtures/audit_executor'
        history = json.loads((root / 'history-r2-r5.json').read_bytes())
        provenance = json.loads((root / 'history-provenance.json').read_bytes())
        # Extraction hashes are exact TASK-003 encoding, not the product canonical encoding.
        pointer = self.mod._pointer
        for entry in provenance['extractions']:
            target = json.loads((root / entry['data_ref']['path']).read_bytes())
            actual = pointer(target, entry['data_ref']['pointer'])
            encoding = entry['new_data_encoding']
            raw = (actual.encode('utf-8') if encoding.startswith('text') else
                json.dumps(actual, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode())
            self.assertEqual(hashlib.sha256(raw).hexdigest(), entry['new_data_sha256'])
        counts, interrupted, placeholders, seams = [], 0, [0, 0], []
        for round_data in history['rounds']:
            dispatched = admitted = 0
            for role in round_data['roles']:
                node = role['native_node']; legacy = role['legacy_result']
                raw = legacy.get('rawUnadmitted')
                kw = {'historical_report': legacy['report']} if legacy['report'] is not None else {}
                value = self.classify(round_data['native_fields']['startTime'], node, raw, **kw)
                for key, oracle in [('completed_at_ms', 'C_ms'), ('execution_state', 'execution_state'),
                                   ('unfinished_at_native_deadline', 'unfinished_at_native_deadline'),
                                   ('dispatched_at_or_after_native_deadline', 'dispatched_at_or_after_native_deadline')]:
                    self.assertEqual(value.get(key), role['expected'][oracle])
                dispatched += node is not None
                admitted += value.get('execution_state') == 'completed_admitted'
                if legacy['report'] is not None:
                    self.assertIs(role['original_admitted_raw_available'], False)
                    if value.get('execution_state') == 'completed_parse_error': seams.append([round_data['round'], role['role_id'], value.get('parse_error')])
                if node is None: placeholders[1] += 1
                elif value.get('execution_state') == 'dispatched_no_completion': placeholders[0] += 1
                for event in role['interruption_events']:
                    assert isinstance(node, dict)
                    verify = getattr(self.mod, '_interruption_body', lambda *a: False)
                    self.assertTrue(verify(event, node['agentId'], event['uuid']))
                    self.assertIsNone(value.get('completed_at_ms'))
                    interrupted += 1
            counts.append([dispatched, admitted])
        self.assertEqual(seams, [], 'Historical raw contract seams must be explained, not washed into votes')
        self.assertEqual(counts, [[6, 2], [7, 4], [6, 2], [5, 1]])
        self.assertEqual(placeholders, [8, 4]); self.assertEqual(interrupted, 8)
        r2 = history['rounds'][0]
        self.assertNotEqual(r2['candidate_sha'], r2['historical_aggregate_only']['conclusions'][0]['fixed_in_later_candidate'])
        self.assertIn('not an additional agent vote', r2['historical_aggregate_only']['conclusions'][0]['source'])


class DriftEvidenceTests(unittest.TestCase):
    """Synthetic protocol fixtures, never evidence of a real Workflow tool failure."""

    def setUp(self):
        self.g = GeneratedScriptTests('test_checker_literal_deterministic_complete_and_independent_call')
        self.g.setUp()
        self.addCleanup(self.g.doCleanups)
        self.f, self.mod = self.g.f, self.g.mod
        self.request_path, self.request, _ = self.g.request()
        audit_native = self.f.root / 'synthetic-audit-native.json'
        self.f.write(audit_native, {'runId': 'synthetic-audit', 'workflowProgress': [
            {'type': 'workflow_agent', 'agentId': 'old-auditor'}]})
        audit_path = Path(self.request['audit_index']['path'])
        audit = json.loads(audit_path.read_bytes())
        audit.update(workflow_run_id='synthetic-audit', native_record=ref(audit_native))
        self.f.write(audit_path, audit)
        self.request['audit_index'] = ref(audit_path)
        self.f.write(self.request_path, self.request)
        self.request_ref = ref(self.request_path)
        anchor = json.loads(Path(self.request['anchor']['path']).read_bytes())['value']
        self.args = {'identity': self.request['identity'], 'request_sha256': self.request_ref['sha256'],
                     'anchor': anchor, 'conclusions': self.request['conclusions']}
        self.script_path = self.f.root / 'synthetic-checker.js'
        self.script_path.write_bytes(self.mod._render_policy_workflow(self.request_ref))
        self.native_path, self.index_path = self.f.root / 'synthetic-drift-native.json', self.f.root / 'synthetic-drift-index.json'
        self.native = {'runId': 'synthetic-drift', 'startTime': 1000, 'durationMs': 900000,
            'status': 'completed', 'agentCount': 1, 'script': self.script_path.read_text(),
            'args': copy.deepcopy(self.args), 'workflowProgress': [{'type': 'phase', 'title': 'Drift'},
                {'type': 'workflow_agent', 'agentId': 'new-checker', 'agentType': self.request['checker']['agentType'],
                 'label': 'drift:client-checker', 'model': 'observed-checker', 'queuedAt': 2000,
                 'startedAt': 3000, 'durationMs': 500000, 'state': 'done'}],
            'result': {'schema_version': 1, 'identity': self.request['identity'],
                'request_sha256': self.request_ref['sha256'], **self.request['checker'],
                'call_attempted': True, 'settled': True, 'raw': '{"classifications":[]}', 'error': None,
                'control': {'timeout_ms': 60000, 'stop_observed': False, 'return_reason': 'all_settled'}}}
        self.native['result'].pop('timeout_ms')
        self.links = []
        self.capture()

    def capture(self):
        self.f.write(self.native_path, self.native)
        self.index = {'schema_version': 1, 'identity': self.request['identity'], 'attempt_index': 2,
            'request': self.request_ref, 'kind': 'workflow', 'workflow_run_id': 'synthetic-drift',
            'native_record': ref(self.native_path), 'termination_refs': self.links, 'tool_failure': None}
        self.f.write(self.index_path, self.index)

    def verify(self, inputs=None):
        return self.mod._verify_drift(self.index_path, self.request_ref, self.script_path, inputs=inputs)

    def reject(self):
        with self.assertRaises(self.mod.ExecutorError):
            self.verify()

    def test_all_settled_checker_flags_must_match_completion(self):
        self.assertEqual(self.verify()['auxiliary_calls'][0]['termination_evidence'], 'completed')
        healthy = copy.deepcopy(self.native)
        for flag in ('call_attempted', 'settled'):
            with self.subTest(flag=flag):
                self.native = copy.deepcopy(healthy)
                self.native['result'].update(raw=None, error=None)
                self.native['result'][flag] = False
                self.capture()
                self.reject()

    def test_checker_raw_is_not_a_vote_and_native_clock_is_not_audit_budget(self):
        value = self.verify()
        self.assertEqual(value.get('kind'), 'workflow')
        seat = value['auxiliary_calls'][0]
        self.assertEqual((seat['queued_at_ms'], seat['started_at_ms'], seat['completed_at_ms']), (2000, 3000, 503000))
        self.assertEqual(seat['termination_evidence'], 'completed')
        self.assertEqual(seat['raw'], '{"classifications":[]}')
        self.assertEqual(seat['raw_ref']['pointer'], '/result/raw')
        self.assertEqual(seat['native_ref']['pointer'], '/workflowProgress/1')
        self.assertEqual(seat['actual_model'], 'observed-checker')
        self.assertEqual(value['control_native_alignment'], 'unknown')
        self.assertEqual(value['control_origin'], 'timer_installation')
        self.assertEqual(value['control_timer_ms'], 60000)
        self.assertEqual(value['native_duration_ms'], 900000)
        self.assertIsNone(value['failure_observation'])
        self.assertNotIn('report', seat)
        self.assertNotIn('ratio', value)
        self.assertNotIn('native_deadline_ms', value)

    def test_sync_and_async_errors_preserve_unknown_without_inventing_completion(self):
        for with_node in (False, True):
            with self.subTest(with_node=with_node):
                native = copy.deepcopy(self.native)
                native['result'].update(raw=None, error='synthetic spawn failure', settled=True)
                if with_node:
                    native['workflowProgress'][1].pop('durationMs')
                    native['workflowProgress'][1]['state'] = 'progress'
                else:
                    native['workflowProgress'] = []; native['agentCount'] = 0
                self.f.write(self.native_path, native)
                self.index['native_record'] = ref(self.native_path); self.f.write(self.index_path, self.index)
                value = self.verify()
                self.assertEqual(value.get('failure_observation'), 'error')
                seat = value['auxiliary_calls'][0]
                self.assertEqual(seat['termination_evidence'], 'unknown')
                self.assertIsNone(seat['completed_at_ms'])
                self.assertIsNone(seat['termination_ref'])
                self.assertEqual(seat['native_agent_id'], 'new-checker' if with_node else None)

    def unfinished(self):
        self.native['workflowProgress'][1].update(state='progress')
        self.native['workflowProgress'][1].pop('durationMs', None)
        self.native['result'].update(raw=None, settled=False)
        self.native['result']['control'].update(stop_observed=True, return_reason='control_timeout')

    def test_own_timer_and_missing_termination_stay_unknown_and_known_C_is_retained(self):
        self.unfinished(); self.capture()
        value = self.verify()
        self.assertEqual(value.get('failure_observation'), 'control_timeout')
        self.assertEqual(value['auxiliary_calls'][0]['termination_evidence'], 'unknown')
        self.assertIsNone(value['auxiliary_calls'][0]['completed_at_ms'])
        self.native['workflowProgress'][1].update(state='done', durationMs=700000)
        self.capture(); value = self.verify()
        self.assertEqual(value['auxiliary_calls'][0]['completed_at_ms'], 703000)
        self.assertEqual(value['auxiliary_calls'][0]['termination_evidence'], 'completed')
        self.assertIsNone(value['auxiliary_calls'][0]['raw_ref'])

    def test_binding_identity_script_args_snapshot_and_unique_checker_reject(self):
        original = copy.deepcopy(self.native)
        mutations = [lambda v: v.update(runId='synthetic-audit'), lambda v: v.update(script=v['script']+'\n'),
            lambda v: v.update(args={}), lambda v: v['args'].update(extra=True),
            lambda v: v['args'].update(request_sha256='0'*64), lambda v: v['args'].update(anchor={}),
            lambda v: v['args'].update(conclusions=[]), lambda v: v['args']['identity'].update(round=True),
            lambda v: v.update(status='running'), lambda v: v.update(agentCount=True),
            lambda v: v.update(agentCount=2), lambda v: v['workflowProgress'].append(copy.deepcopy(v['workflowProgress'][1])),
            lambda v: v['workflowProgress'][1].update(label='drift:other'),
            lambda v: v['workflowProgress'][1].update(agentType='aria:other'),
            lambda v: v['workflowProgress'][1].update(agentId='old-auditor'),
            lambda v: v['workflowProgress'][1].update(queuedAt=True),
            lambda v: v['workflowProgress'][1].update(startedAt=1999),
            lambda v: v['result'].update(call_attempted=1), lambda v: v['result'].update(call_attempted=False),
            lambda v: v['result'].update(settled=1), lambda v: v['result'].update(request_sha256='0'*64),
            lambda v: v['result'].update(label='drift:other'), lambda v: v['result'].update(agentType='aria:other'),
            lambda v: v['result'].update(report=json.loads(StatePartitionTests.valid_raw())),
            lambda v: v['result'].update(error='failure'), lambda v: v['result'].update(settled=False),
            lambda v: v['result']['control'].update(timeout_ms=True),
            lambda v: v['result']['control'].update(timeout_ms=300000),
            lambda v: v['result']['control'].update(stop_observed=1),
            lambda v: v['result']['control'].update(return_reason='control_timeout')]
        for i, mutate in enumerate(mutations):
            with self.subTest(case=i):
                self.native = copy.deepcopy(original); mutate(self.native); self.capture(); self.reject()
        self.native = original; self.capture()
        self.assertEqual(self.verify().get('kind'), 'workflow')

    def test_index_branches_request_hash_counts_and_explicit_nulls_reject(self):
        original = copy.deepcopy(self.index)
        for key, bad in [('identity', {}), ('attempt_index', True), ('schema_version', True),
                         ('request', {**self.request_ref, 'sha256': '0'*64}), ('workflow_run_id', 'synthetic-audit'),
                         ('native_record', None), ('termination_refs', None), ('tool_failure', {}),
                         ('kind', 'tool_error'), ('kind', 'other')]:
            with self.subTest(key=key):
                self.index = {**original, key: bad}; self.f.write(self.index_path, self.index); self.reject()
        self.index = copy.deepcopy(original)
        self.index.pop('tool_failure'); self.f.write(self.index_path, self.index); self.reject()
        self.f.write(self.index_path, original)
        self.assertEqual(self.verify().get('kind'), 'workflow')

    def interruption(self):
        self.unfinished()
        path = self.f.root / 'synthetic-checker-events.jsonl'
        self.event = {'type': 'user', 'uuid': 'synthetic-interrupt', 'agentId': 'new-checker',
            'message': {'role': 'user', 'content': '[Request interrupted by user for tool use]'}}
        prefix = json.dumps({'text': 'a b c'}, ensure_ascii=False).encode()
        path.write_bytes(prefix+b'\n'+encode(self.event)+b'\n')
        self.links = [{'native_pointer': '/workflowProgress/1', 'agent_id': 'new-checker',
            'event': {'file': ref(path), 'line': 2, 'agent_id': 'new-checker', 'event_uuid': self.event['uuid']}}]
        self.capture()
        return path

    def test_termination_LF_bytes_freeze_growth_and_tampered_blob(self):
        path = self.interruption(); captured = self.mod._Inputs()
        before = self.verify(captured)
        self.assertEqual(before.get('kind'), 'workflow')
        self.assertEqual(before['auxiliary_calls'][0]['termination_evidence'], 'interrupted_observed')
        frozen = self.mod._FrozenInputs(dict(captured.raw))
        path.write_bytes(path.read_bytes()+b'{"late":true}\n')
        self.native['result'].update(raw='late', settled=True)
        self.f.write(self.native_path, self.native)
        self.request_path.write_bytes(self.request_path.read_bytes()+b' ')
        self.assertEqual(self.verify(frozen), before)
        bad = dict(captured.raw); bad[str(path)] += b'changed'
        with self.assertRaises(self.mod.ExecutorError): self.verify(self.mod._FrozenInputs(bad))

    def test_wrong_termination_hash_line_uuid_actor_pointer_and_full_body_reject(self):
        for kind in ('hash', 'line', 'bool_line', 'uuid', 'actor', 'pointer', 'body', 'role'):
            with self.subTest(kind=kind):
                path = self.interruption(); link = self.links[0]
                if kind == 'hash': link['event']['file']['sha256'] = '0'*64
                elif kind == 'line': link['event']['line'] = 1
                elif kind == 'bool_line': link['event']['line'] = True
                elif kind == 'uuid': link['event']['event_uuid'] = 'other'
                elif kind == 'actor': link['agent_id'] = 'other'
                elif kind == 'pointer': link['native_pointer'] = '/workflowProgress/0'
                else:
                    if kind == 'body': self.event['message']['content'] += ' extra'
                    else: self.event['message']['role'] = 'assistant'
                    path.write_bytes(b'{}\n'+encode(self.event)+b'\n'); link['event']['file'] = ref(path)
                self.capture(); self.reject()

    def tool_error(self):
        self.call = {'type': 'assistant', 'uuid': 'synthetic-call', 'message': {'role': 'assistant', 'content': [
            {'type': 'tool_use', 'id': 'synthetic-tool-id', 'name': 'Workflow',
             'input': {'scriptPath': str(self.script_path), 'args': self.args}}]}}
        self.response = {'type': 'user', 'uuid': 'synthetic-response', 'sourceToolAssistantUUID': 'synthetic-call',
            'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'synthetic-tool-id',
                'is_error': True, 'content': 'synthetic transport failure; not a real tool failure'}]}}
        self.session_path = self.f.root / 'synthetic-session.jsonl'
        self.session_path.write_bytes(encode(self.call)+b'\n'+encode(self.response)+b'\n')
        self.index.update(kind='tool_error', workflow_run_id=None, native_record=None, termination_refs=[],
            tool_failure={'call': {'file': ref(self.session_path), 'line': 1, 'event_uuid': 'synthetic-call'},
                          'response': {'file': ref(self.session_path), 'line': 2, 'event_uuid': 'synthetic-response'}})
        self.f.write(self.index_path, self.index)

    def test_tool_error_links_unknown_auxiliary_call_and_not_error_substring(self):
        self.tool_error(); value = self.verify()
        self.assertEqual(value.get('kind'), 'tool_error')
        seat = value['auxiliary_calls'][0]
        self.assertTrue(seat['call_attempted'])
        self.assertIsNone(seat['native_agent_id']); self.assertIsNone(seat['completed_at_ms'])
        self.assertEqual(seat['termination_evidence'], 'unknown')
        self.assertIsNone(seat['termination_ref'])
        self.assertIsNone(value['workflow_run_id'])
        self.assertEqual(value['tool_failure']['call']['line'], 1)
        self.response['message']['content'][0].update(is_error=False, content='error error error')
        self.session_path.write_bytes(encode(self.call)+b'\n'+encode(self.response)+b'\n')
        for item in self.index['tool_failure'].values(): item['file'] = ref(self.session_path)
        self.f.write(self.index_path, self.index); self.reject()

    def test_tool_error_rejects_cross_tool_cross_request_link_and_schema_corruption(self):
        for kind in ('tool', 'tool_id', 'source_uuid', 'call_uuid', 'response_uuid', 'line', 'bool_line', 'hash',
                     'path', 'args', 'request', 'error_flag', 'role', 'body', 'run', 'native', 'links', 'missing'):
            with self.subTest(kind=kind):
                self.tool_error()
                if kind == 'tool': self.call['message']['content'][0]['name'] = 'AskUserQuestion'
                elif kind == 'tool_id': self.response['message']['content'][0]['tool_use_id'] = 'other'
                elif kind == 'source_uuid': self.response['sourceToolAssistantUUID'] = 'other'
                elif kind == 'path': self.call['message']['content'][0]['input']['scriptPath'] += '.other'
                elif kind == 'args': self.call['message']['content'][0]['input']['args'] = {}
                elif kind == 'request': self.call['message']['content'][0]['input']['args'] = {**self.args, 'request_sha256': '0'*64}
                elif kind == 'error_flag': self.response['message']['content'][0]['is_error'] = 1
                elif kind == 'role': self.response['message']['role'] = 'assistant'
                elif kind == 'body': self.response['message']['content'][0]['content'] = {'error': True}
                elif kind == 'run': self.index['workflow_run_id'] = 'fake'
                elif kind == 'native': self.index['native_record'] = ref(self.native_path)
                elif kind == 'links': self.index['termination_refs'] = [{}]
                elif kind == 'missing': self.index.pop('native_record')
                self.session_path.write_bytes(encode(self.call)+b'\n'+encode(self.response)+b'\n')
                for item in self.index['tool_failure'].values(): item['file'] = ref(self.session_path)
                if kind == 'call_uuid': self.index['tool_failure']['call']['event_uuid'] = 'other'
                elif kind == 'response_uuid': self.index['tool_failure']['response']['event_uuid'] = 'other'
                elif kind == 'line': self.index['tool_failure']['response']['line'] = 1
                elif kind == 'bool_line': self.index['tool_failure']['call']['line'] = True
                elif kind == 'hash': self.index['tool_failure']['call']['file']['sha256'] = '0'*64
                self.f.write(self.index_path, self.index); self.reject()

    def test_production_audit_does_not_rescue_raw_from_snapshot_report(self):
        n = NativeEvidenceTests('test_complete_mapping_raw_refs_and_two_clocks'); n.setUp()
        self.addCleanup(n.doCleanups)
        n.native['result']['results'][0].update(raw=None, report=json.loads(StatePartitionTests.valid_raw()))
        n.capture(); n.rejected('E_NATIVE_EVIDENCE')


# The direct unittest entry point lives after all test classes (including TASK-013).


class _CanonicalPolicyFixture(unittest.TestCase):
    """Synthetic normalized facts with real temporary source bytes, not tool receipts.

    These test the pure kernels, NOT recursive history verification or collect.
    NativeEvidenceTests/DriftEvidenceTests separately verify the input producers.
    """
    def setUp(self):
        self.f = BuildContractTests('test_missing_project_and_missing_key_remain_false_without_team_or_evidence')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.build()
        self.mod = self.f.mod
        self.genesis = json.loads((self.f.scope() / 'genesis.json').read_bytes())
        self.effective = self.f.record()['effective_config']
        self.anchor = {'record': json.loads(Path(self.genesis['anchor']['path']).read_bytes()),
                       'source': self.genesis['anchor']}
        self.serial = 0

    @staticmethod
    def finding(**changes):
        return {'type': 'issue', 'severity': 'minor', 'category': 'implementation',
                'scope': 'a.py', 'file': 'a.py', 'line': 1,
                'failure_scenario': 'synthetic failure', **changes}

    def facts(self, round_number, admitted=(0,), findings=None, votes=None, attempt_index=None):
        self.serial += 1
        attempt_index = round_number if attempt_index is None else attempt_index
        identity = {**self.f.record()['identity'], 'round': round_number,
                    'client_round_id': f'synthetic-client-{self.serial}'}
        path = self.f.root / f'kernel-native-{self.serial}.json'
        native = {'runId': f'synthetic-kernel-{self.serial}', 'startTime': 0,
                  'script': 'synthetic normalized-fact vector, not executed Workflow',
                  'workflowProgress': [], 'result': {'results': []}}
        rows = []
        for i, role in enumerate(self.f.record()['roles']):
            fs = copy.deepcopy((findings or {}).get(i, []))
            vote = (votes or {}).get(i, 'REVISE' if any(f['severity'] != 'minor' for f in fs) else 'PASS')
            report = {'vote': vote, 'coverage_complete': True, 'findings': fs, 'pending': [],
                      'prior_findings': [{'severity': 'critical', 'scope': 'not a current finding'}]}
            raw = encode(report).decode() if i in admitted else None
            node = {'type': 'workflow_agent', 'agentId': f'synthetic-{self.serial}-{i}',
                    'agentType': role['agentType'], 'label': f'audit:{identity["client_round_id"]}:{i}',
                    'model': None, 'queuedAt': i * 10, 'startedAt': i * 10,
                    'durationMs': 1, 'state': 'done'}
            native['workflowProgress'].append(node)
            native['result']['results'].append({'raw': raw})
            value = self.mod._classify_seat(0, node, raw)
            rows.append({**role, **value, 'label': node['label'], 'raw_ref': None,
                         'actual_model': None})
        self.f.write(path, native)
        for i, row in enumerate(rows):
            if i in admitted:
                row['raw_ref'] = {'file': ref(path), 'pointer': f'/result/results/{i}/raw'}
        return {'identity': identity, 'attempt_index': attempt_index,
                'audit': {'workflow_run_id': native['runId'], 'native_record': ref(path), 'roles': rows},
                'drift': None}

    @staticmethod
    def current(attempt):
        return {'identity': attempt['identity'], 'roles': attempt['audit']['roles']}

    def compare(self, current, previous=None, guard: object = True):
        return self.mod._compare_rounds(self.current(current),
            self.current(previous) if previous is not None else None, guard)

    def fold(self, attempts):
        return self.mod._apply_policy(self.genesis, attempts, self.effective, self.anchor)

    def drift(self, attempt, classes=None, failure=None):
        conclusions = self.mod._aggregate_admitted(attempt['audit']['roles'])['comparison_keys']
        classes = classes if classes is not None else ['on_topic'] * len(conclusions)
        raw = encode({'classifications': [{'key': key, 'classification': value}
                     for key, value in zip(conclusions, classes)]}).decode()
        path = self.f.root / f'drift-{attempt["identity"]["client_round_id"]}.json'
        error = 'synthetic spawn error' if failure == 'error' else None
        control = {'timeout_ms': 60000, 'stop_observed': failure == 'control_timeout',
                   'return_reason': 'control_timeout' if failure == 'control_timeout' else 'all_settled'}
        self.f.write(path, {'result': {'raw': raw if failure is None else None,
                                     'error': error, 'control': control}})
        attempt['drift'] = {'kind': 'workflow', 'failure_observation': failure,
            'workflow_run_id': 'synthetic-drift-' + attempt['identity']['client_round_id'],
            'native_record': ref(path), 'control': control,
            'auxiliary_calls': [{'call_attempted': True, 'settled': failure != 'control_timeout',
                'raw': raw if failure is None else None, 'error': error,
                'raw_ref': {'file': ref(path), 'pointer': '/result/raw'} if failure is None else None}]}
        return attempt

    def complete_anchor(self):
        self.anchor['record']['value']['in_scope'] = ['synthetic scope']
        path = self.f.root / 'complete-anchor.json'
        self.f.write(path, self.anchor['record'])
        self.anchor['source'] = ref(path)

    def reject(self, fn, code):
        with self.assertRaises(self.mod.ExecutorError) as caught:
            fn()
        self.assertEqual(caught.exception.error_code, code)


class CanonicalAggregationTests(_CanonicalPolicyFixture, unittest.TestCase):
    def test_bucket_highest_severity_each_type_and_conserved_full_members(self):
        minor = self.finding(summary='first issue', prior_id='old', extra={'__proto__': [1]})
        risk = self.finding(type='risk', severity='critical', summary='risk')
        other = self.finding(summary='other claim', __proto__={'retained': True})
        facts = self.facts(1, (0, 1), {0: [minor, minor, risk], 1: [other]})
        value = self.mod._aggregate_admitted(facts['audit']['roles'])
        cs = value['conclusions']
        self.assertEqual(value['comparison_keys'], [['issue', 'critical', 'implementation', 'a.py'],
                                                   ['risk', 'critical', 'implementation', 'a.py']])
        self.assertEqual([c['found_by'] for c in cs],
                         [[self.f.manifest['roles'][i]['role_id'] for i in (0, 1)],
                          [self.f.manifest['roles'][0]['role_id']]])
        self.assertEqual([c['conflict_state'] for c in cs], ['unresolved_variants'] * 2)
        self.assertEqual(sum(len(v['members']) for c in cs for v in c['variants']), 4)
        issue = cs[0]
        variants = {encode(v['finding']): v for v in issue['variants']}
        self.assertEqual(len(variants[encode(minor)]['members']), 2)
        self.assertIn(encode(other), variants)
        for c in cs:
            self.assertEqual(c['variants'], sorted(c['variants'], key=lambda v: encode(v['finding'])))
            for v in c['variants']:
                self.assertEqual(v['members'], sorted(v['members'], key=lambda m: (m['role_index'], m['finding_index'])))
                for m in v['members']:
                    path = Path(m['raw_ref']['file']['path'])
                    self.assertEqual(ref(path), m['raw_ref']['file'])
                    original = json.loads(self.mod._pointer(json.loads(path.read_bytes()), m['raw_ref']['pointer']))
                    self.assertEqual(original['findings'][m['finding_index']], v['finding'])

    def test_complete_variant_not_summary_or_prior_id_defines_deduplication(self):
        one = self.finding(summary='same', prior_id='one')
        two = {**one, 'prior_id': 'two'}
        value = self.mod._aggregate_admitted(self.facts(1, (0, 1), {0: [one], 1: [one, two]})['audit']['roles'])
        c = value['conclusions'][0]
        self.assertEqual(len(value['conclusions']), 1)
        self.assertEqual(len(c['variants']), 2)
        self.assertEqual(sum(len(v['members']) for v in c['variants']), 3)
        self.assertEqual(c['conflict_state'], 'unresolved_variants')

    def test_scope_and_unicode_are_not_normalized_and_full_tuples_sort(self):
        scopes = ['a.py', './a.py', ' A/../B ', '', 'A.py', 'é', 'é']
        value = self.mod._aggregate_admitted(self.facts(1, (0,), {0: [self.finding(scope=s) for s in scopes]})['audit']['roles'])
        self.assertEqual([c['scope'] for c in value['conclusions']], sorted(scopes))
        self.assertEqual(len(value['comparison_keys']), len(scopes))

    def test_summary_earliest_string_fallback_split_50_and_id_formula(self):
        first = self.finding(summary=' \t' + ' '.join(str(i) for i in range(55)))
        second = self.finding(summary='later', type='risk')
        nonstring = self.finding(summary=8, type='decision', failure_scenario=' fallback\n value ')
        value = self.mod._aggregate_admitted(self.facts(1, (0,), {0: [first, second, nonstring]})['audit']['roles'])
        by_type = {c['type']: c for c in value['conclusions']}
        self.assertEqual(by_type['issue']['summary'], ' '.join(str(i) for i in range(50)))
        self.assertEqual(by_type['decision']['summary'], 'fallback value')
        for c in value['conclusions']:
            text = ':'.join(c[k] for k in ('category', 'scope', 'severity', 'type'))
            self.assertEqual(c['id'], hashlib.sha256(text.encode()).hexdigest()[:8])

    def test_only_this_round_admitted_findings_and_original_inputs_unchanged(self):
        facts = self.facts(1, (0,), {0: [self.finding()]})
        before = copy.deepcopy(facts)
        value = self.mod._aggregate_admitted(facts['audit']['roles'])
        self.assertEqual(len(value['conclusions']), 1)
        self.assertEqual(value['conclusions'][0]['conflict_state'], 'none')
        value['conclusions'][0]['variants'][0]['finding']['file'] = 'mutated'
        self.assertEqual(facts, before)

    def test_real_eight_hex_collision_retains_both_full_keys(self):
        seen = {}
        pair = None
        for n in range(250000):
            scope = f'collision-{n}'
            short = hashlib.sha256(f'implementation:{scope}:minor:issue'.encode()).hexdigest()[:8]
            if short in seen:
                pair = [seen[short], scope]
                break
            seen[short] = scope
        self.assertIsNotNone(pair, 'deterministic real collision search failed')
        assert pair is not None
        value = self.mod._aggregate_admitted(self.facts(1, (0,), {0: [self.finding(scope=s) for s in pair]})['audit']['roles'])
        self.assertEqual(len(value['conclusions']), 2)
        self.assertEqual(len(value['comparison_keys']), 2)
        self.assertEqual(value['conclusions'][0]['id'], value['conclusions'][1]['id'])

    def test_actual_native_classifier_output_is_directly_accepted_characterization(self):
        n = NativeEvidenceTests('test_complete_mapping_raw_refs_and_two_clocks')
        n.setUp()
        self.addCleanup(n.doCleanups)
        n.capture()
        actual = n.mod._classify_native(n.f.repo, n.f.manifest_path,
            n.f.run_dir / 'build-record.json', 'synthetic-run', n.native_path, n.index_path)
        value = n.mod._aggregate_admitted(actual['roles'])
        self.assertEqual(value['admitted_roles'], [n.f.manifest['roles'][0]['role_id']])
        self.assertEqual(value['comparison_keys'], [])
        self.assertTrue(value['incomplete'])


class PopulationGuardTests(_CanonicalPolicyFixture, unittest.TestCase):
    def test_same_nonempty_partial_roles_can_converge(self):
        a, b = self.facts(1, (0, 2)), self.facts(2, (0, 2))
        value = self.compare(b, a)
        self.assertTrue(value['population_comparable'])
        self.assertEqual(value['population_reason'], 'same_population')
        self.assertTrue(value['incomplete'])
        self.assertTrue(value['converged'])

    def test_same_size_different_identity_and_different_size_are_not_comparable(self):
        a = self.facts(1, (0, 1))
        for roles in [(0, 2), (0,)]:
            with self.subTest(roles=roles):
                value = self.compare(self.facts(2, roles), a)
                self.assertTrue(value['conclusion_keys_equal'])
                self.assertFalse(value['population_comparable'])
                self.assertEqual(value['population_reason'], 'population_changed')
                self.assertFalse(value['converged'])

    def test_first_round_and_missing_previous_are_distinct(self):
        value = self.compare(self.facts(1))
        self.assertEqual(value['population_reason'], 'first_round')
        self.assertFalse(value['conclusion_keys_equal'])
        self.assertFalse(value['converged'])
        self.reject(lambda: self.compare(self.facts(2)), 'E_PREVIOUS_REQUIRED')

    def test_old_missing_participant_evidence_is_diagnostic_not_equality(self):
        a, b = self.facts(1), self.facts(2)
        prior = {'identity': a['identity'], 'comparison_keys': [], 'admitted_roles': ['not evidence']}
        for old in [prior, {'comparison_keys': []}]:
            value = self.mod._compare_rounds(self.current(b), old, True)
            self.assertEqual(value['population_reason'], 'missing_participant_evidence')
            self.assertFalse(value['conclusion_keys_equal'])
            self.assertFalse(value['converged'])

    def test_empty_current_or_previous_population_never_converges(self):
        for aroles, broles in [((0,), ()), ((), (0,)), ((), ())]:
            value = self.compare(self.facts(2, broles), self.facts(1, aroles))
            self.assertEqual(value['population_reason'], 'empty_population')
            self.assertFalse(value['converged'])
            if not broles:
                self.assertTrue(value['all_failed_void'])
                self.assertFalse(value['unanimous_pass'])

    def test_corrupt_duplicate_roles_and_wrong_indices_are_errors(self):
        for which in ['current', 'previous']:
            for mutation in ['duplicate', 'index']:
                a, b = self.facts(1), self.facts(2)
                target = b if which == 'current' else a
                rows = target['audit']['roles']
                if mutation == 'duplicate': rows[1]['role_id'] = rows[0]['role_id']
                else: rows[0]['index'] = True
                self.reject(lambda: self.compare(b, a), 'E_PREVIOUS_IDENTITY')

    def test_nonadjacent_or_cross_identity_is_error_not_a_new_baseline(self):
        a, b = self.facts(1), self.facts(2)
        for key, bad in [('audit_cycle_id', 'other'), ('checkpoint', 'pre_merge'),
                         ('change_id', 'other'), ('round', 3), ('round', True),
                         ('client_round_id', b['identity']['client_round_id'])]:
            with self.subTest(key=key, bad=bad):
                old = copy.deepcopy(a)
                old['identity'][key] = bad
                self.reject(lambda: self.compare(b, old), 'E_PREVIOUS_IDENTITY')

    def test_candidate_and_model_changes_are_only_traceability(self):
        a, b = self.facts(1), self.facts(2)
        b['identity']['candidate_sha'] = 'a' * 40
        b['audit']['roles'][0].update(model_alias='changed', actual_model='changed')
        self.assertTrue(self.compare(b, a)['converged'])

    def test_guard_disabled_vector_follows_legacy_not_a_production_routing_claim(self):
        a, b = self.facts(1, (0,)), self.facts(2, (1,))
        value = self.compare(b, a, False)
        self.assertIsNone(value['population_comparable'])
        self.assertEqual(value['population_reason'], 'disabled')
        self.assertTrue(value['converged'])
        self.reject(lambda: self.compare(b, a, 1), 'E_CONFIG_TYPE')

    def test_revise_vote_and_changed_full_keys_block_convergence(self):
        a, b = self.facts(1), self.facts(2, votes={0: 'REVISE'})
        self.assertFalse(self.compare(b, a)['converged'])
        b = self.facts(2, findings={0: [self.finding()]})
        self.assertFalse(self.compare(b, a)['conclusion_keys_equal'])
        self.assertFalse(self.compare(b, a)['converged'])


class PolicyKernelTests(_CanonicalPolicyFixture, unittest.TestCase):
    def test_empty_verified_prefix_derives_zero_state_and_sources(self):
        value = self.fold([])
        p = value['policy']
        for k, expected in [('charged_rounds', 0), ('consecutive_refocus_count', 0),
                            ('pending_refocus', False), ('effective_limit', 5),
                            ('remaining_rounds', 5), ('terminal_state', None)]:
            self.assertEqual(p[k], expected)
        self.assertEqual(value['attempts'], [])
        self.assertEqual(set(value['policy_sources']), set(p))
        self.assertTrue(all(value['policy_sources'].values()))

    def test_first_round_limit_one_is_exhausted_not_converged(self):
        self.genesis['initial_max_rounds'] = 1
        row = self.fold([self.facts(1)])['attempts'][0]
        self.assertEqual(row['policy']['charged_rounds'], 1)
        self.assertEqual(row['policy']['remaining_rounds'], 0)
        self.assertEqual(row['policy']['terminal_state'], 'MAX_ROUNDS_EXHAUSTED')
        self.assertEqual(row['policy']['drift_reason'], 'first_round')
        self.assertFalse(row['converged'])
        self.assertEqual(row['verdict'], 'PASS')

    def test_void_attempt_does_not_charge_or_replace_effective_baseline(self):
        a = self.facts(1, (0, 1))
        void = self.facts(2, (), attempt_index=2)
        b = self.facts(2, (0, 1), attempt_index=3)
        rows = self.fold([a, void, b])['attempts']
        self.assertEqual([r['policy']['charged_rounds'] for r in rows], [1, 1, 2])
        self.assertTrue(rows[-1]['converged'])
        self.assertEqual(rows[-1]['population_reason'], 'same_population')
        self.assertIsNone(rows[1]['policy']['terminal_state'])

    def test_reason_priority_and_missing_checker_fail_closed(self):
        a, b = self.facts(1, findings={0: [self.finding()]}), self.facts(2, findings={0: [self.finding()]})
        self.reject(lambda: self.fold([a, b]), 'E_POLICY_SOURCE')
        self.effective['drift_guard']['convergence_mode']['value'] = False
        self.assertEqual(self.fold([a, b])['attempts'][-1]['policy']['drift_reason'], 'disabled_by_config')
        self.effective['drift_guard']['convergence_mode']['value'] = True
        missing_path = self.f.root / 'missing-anchor.json'
        missing = {'schema_version': 1, 'status': 'missing', 'value': None,
                   'observations': self.anchor['record']['observations']}
        self.f.write(missing_path, missing)
        self.anchor = {'record': missing, 'source': ref(missing_path)}
        self.assertEqual(self.fold([a, b])['attempts'][-1]['policy']['drift_reason'], 'anchor_missing_observed')
        empty = self.facts(2)
        self.assertEqual(self.fold([a, empty])['attempts'][-1]['policy']['drift_reason'], 'empty_conclusions')

    def test_warn_overrides_raw_pass_but_quality_and_resources_are_separate(self):
        self.complete_anchor()
        fs = [self.finding(scope=str(i)) for i in range(5)]
        a = self.facts(1, findings={0: fs})
        b = self.drift(self.facts(2, findings={0: fs}), ['off_topic'] + ['on_topic'] * 4)
        b['audit']['roles'][1]['termination_evidence'] = 'unknown'
        row = self.fold([a, b])['attempts'][-1]
        self.assertEqual(row['policy']['drift_action'], 'WARN')
        self.assertFalse(row['unanimous_pass'])
        self.assertFalse(row['converged'])
        self.assertEqual(row['verdict'], 'PASS')
        self.assertNotIn('merge_clearance', row)
        self.assertNotIn('next_round_dispatch_allowed', row)

    def test_binary64_threshold_boundary_and_inclusive_zero(self):
        self.complete_anchor()
        for total, threshold, expected in [(10, .1, 'REFOCUS_ROUND'),
                (10, .10000000000000002, 'NONE'),
                (3, .3333333333333333, 'REFOCUS_ROUND'),
                (3, .33333333333333337, 'NONE')]:
            with self.subTest(total=total, threshold=threshold):
                self.effective['drift_guard']['warn_threshold']['value'] = threshold
                self.effective['drift_guard']['refocus_threshold']['value'] = threshold
                a = self.facts(1, findings={0: [self.finding(scope='prior')]})
                fs = [self.finding(scope=str(i)) for i in range(total)]
                b = self.drift(self.facts(2, findings={0: fs}), ['off_topic'] + ['adjacent'] * (total - 1))
                self.assertEqual(self.fold([a, b])['attempts'][-1]['policy']['drift_action'], expected)
        self.effective['drift_guard']['warn_threshold']['value'] = 0
        self.effective['drift_guard']['refocus_threshold']['value'] = 0
        a = self.facts(1, findings={0: [self.finding()]})
        b = self.drift(self.facts(2, findings={0: [self.finding()]}))
        self.assertEqual(self.fold([a, b])['attempts'][-1]['policy']['drift_action'], 'REFOCUS_ROUND')

    def test_partial_only_on_topic_adjacent_derived_annotations_and_zero_threshold(self):
        a = self.facts(1, findings={0: [self.finding()]})
        b = self.drift(self.facts(2, findings={0: [self.finding()]}), ['adjacent'])
        row = self.fold([a, b])['attempts'][-1]
        self.assertTrue(row['policy']['drift_required'])
        self.assertTrue(row['policy']['anchor_scope_empty'])
        self.assertEqual(row['policy']['drift_classification_confidence'], 'low')
        self.assertEqual(row['policy']['drift_ratio'], 0)
        self.assertEqual(row['policy']['drift_action'], 'NONE')
        self.effective['drift_guard']['warn_threshold']['value'] = 0
        self.effective['drift_guard']['refocus_threshold']['value'] = 0
        self.assertEqual(self.fold([a, b])['attempts'][-1]['policy']['drift_action'], 'REFOCUS_ROUND')
        self.drift(b, ['off_topic'])
        self.reject(lambda: self.fold([a, b]), 'E_POLICY_SOURCE')

    def test_exact_classification_keys_not_short_ids_duplicates_or_missing(self):
        a = self.facts(1)
        for classes in [[], ['bogus']]:
            b = self.drift(self.facts(2, findings={0: [self.finding()]}), classes)
            self.reject(lambda: self.fold([a, b]), 'E_POLICY_SOURCE')
        for mutation in ['duplicate', 'extra', 'missing_key']:
            b = self.drift(self.facts(2, findings={0: [self.finding()]}))
            call = b['drift']['auxiliary_calls'][0]
            body = json.loads(call['raw'])
            if mutation == 'duplicate': body['classifications'] *= 2
            elif mutation == 'extra': body['classifications'][0]['extra'] = True
            else: body['classifications'][0]['key'][3] = 'other'
            call['raw'] = encode(body).decode()
            self.reject(lambda: self.fold([a, b]), 'E_POLICY_SOURCE')

    def test_void_retains_pending_and_count_skipped_retains_count(self):
        self.complete_anchor()
        a = self.facts(1, findings={0: [self.finding(scope='one')]})
        b = self.drift(self.facts(2, findings={0: [self.finding(scope='two')]}), ['off_topic'])
        void = self.facts(3, (), attempt_index=3)
        skipped = self.drift(self.facts(3, findings={0: [self.finding(scope='three')]}, attempt_index=4), failure='control_timeout')
        c = self.drift(self.facts(4, findings={0: [self.finding(scope='four')]}, attempt_index=5), ['off_topic'])
        rows = self.fold([a, b, void, skipped, c])['attempts']
        self.assertEqual([r['policy']['charged_rounds'] for r in rows], [1, 2, 2, 3, 4])
        self.assertEqual([r['policy']['consecutive_refocus_count'] for r in rows], [0, 1, 1, 1, 2])
        self.assertTrue(rows[2]['policy']['pending_refocus'])
        self.assertTrue(rows[3]['policy']['is_refocus'])
        self.assertTrue(rows[3]['policy']['drift_check_skipped'])
        self.assertEqual(rows[-1]['policy']['terminal_state'], 'DRIFT_TERMINATED')
        self.assertEqual(rows[-1]['verdict'], 'FAIL')

    def test_successful_nonrefocus_resets_count_and_refocus_charges(self):
        self.complete_anchor()
        a = self.facts(1, findings={0: [self.finding(scope='one')]})
        b = self.drift(self.facts(2, findings={0: [self.finding(scope='two')]}), ['off_topic'])
        c = self.drift(self.facts(3, findings={0: [self.finding(scope='three')]}), ['on_topic'])
        row = self.fold([a, b, c])['attempts'][-1]
        self.assertTrue(row['policy']['is_refocus'])
        self.assertEqual(row['policy']['charged_rounds'], 3)
        self.assertEqual(row['policy']['consecutive_refocus_count'], 0)
        self.assertFalse(row['policy']['pending_refocus'])

    def test_normal_oscillation_uses_full_keys_and_excludes_refocus(self):
        self.effective['drift_guard']['convergence_mode']['value'] = False
        a = self.facts(1, findings={0: [self.finding(scope='A')]})
        b = self.facts(2, findings={0: [self.finding(scope='B')]})
        c = self.facts(3, findings={0: [self.finding(scope='A')]})
        row = self.fold([a, b, c])['attempts'][-1]
        self.assertEqual(row['policy']['terminal_state'], 'OSCILLATION')
        self.complete_anchor()
        self.effective['drift_guard']['convergence_mode']['value'] = True
        self.drift(b, ['off_topic'])
        self.drift(c, ['on_topic'])
        self.assertIsNone(self.fold([a, b, c])['attempts'][-1]['policy']['terminal_state'])

    def test_terminal_priority_converged_then_drift_then_oscillation_then_exhaustion(self):
        self.genesis['initial_max_rounds'] = 2
        self.assertEqual(self.fold([self.facts(1), self.facts(2)])['policy']['terminal_state'], 'CONVERGED')
        self.complete_anchor()
        self.genesis['initial_max_rounds'] = 3
        a = self.facts(1, findings={0: [self.finding(scope='A')]})
        b = self.drift(self.facts(2, findings={0: [self.finding(scope='B')]}), ['off_topic'])
        c = self.drift(self.facts(3, findings={0: [self.finding(scope='A')]}), ['off_topic'])
        self.assertEqual(self.fold([a, b, c])['policy']['terminal_state'], 'DRIFT_TERMINATED')
        self.effective['drift_guard']['convergence_mode']['value'] = False
        b['drift'] = c['drift'] = None
        self.assertEqual(self.fold([a, b, c])['policy']['terminal_state'], 'OSCILLATION')
        self.genesis['initial_max_rounds'] = 2
        self.drift(b, ['off_topic'])
        self.effective['drift_guard']['convergence_mode']['value'] = True
        self.assertEqual(self.fold([a, b])['policy']['terminal_state'], 'MAX_ROUNDS_EXHAUSTED')

    def test_no_callers_approved_or_used_rounds_reopen_exhausted_prefix(self):
        self.genesis['initial_max_rounds'] = 1
        a, b = self.facts(1), self.facts(2)
        b.update(approved=True, used_rounds=0, effective_limit=99)
        self.reject(lambda: self.fold([a, b]), 'E_POLICY_BLOCKED')
        state = {'genesis': self.genesis, 'events': [{'event': {'kind': 'disposition',
                  'payload': {'approved': True, 'action': 'increase_rounds'}}}]}
        self.reject(lambda: self.mod._replay_history(state), 'E_POLICY_SOURCE')

    def test_damage_sequence_or_sources_is_rejected_not_reset_to_first(self):
        a, b = self.facts(1), self.facts(2)
        for key, bad in [('attempt_index', 3), ('attempt_index', True)]:
            broken = copy.deepcopy(b)
            broken[key] = bad
            self.reject(lambda: self.fold([a, broken]), 'E_PREVIOUS_IDENTITY')
        broken = copy.deepcopy(b)
        broken['identity']['round'] = 3
        self.reject(lambda: self.fold([a, broken]), 'E_PREVIOUS_IDENTITY')
        broken = copy.deepcopy(self.effective)
        broken['drift_guard']['warn_threshold'].pop('source')
        self.reject(lambda: self.mod._apply_policy(self.genesis, [a], broken, self.anchor), 'E_POLICY_SOURCE')

    def test_quality_uses_promoted_canonical_severity_not_votes_or_variants(self):
        fs = [self.finding(type='risk', severity='critical'), self.finding(type='issue')]
        row = self.fold([self.facts(1, findings={0: fs})])['attempts'][0]
        self.assertEqual([c['severity'] for c in row['conclusions']], ['critical', 'critical'])
        self.assertEqual(row['verdict'], 'FAIL')
        self.assertFalse(row['converged'])
        row = self.fold([self.facts(1, findings={0: [self.finding(severity='major')]})])['attempts'][0]
        self.assertEqual(row['verdict'], 'PASS_WITH_WARNINGS')

    def test_every_policy_value_has_preserved_sources_and_folding_is_pure(self):
        a = self.facts(1)
        before = copy.deepcopy((self.genesis, [a], self.effective, self.anchor))
        value = self.fold([a])
        self.assertEqual((self.genesis, [a], self.effective, self.anchor), before)
        row = value['attempts'][0]
        self.assertEqual(set(row['policy_sources']), set(row['policy']))
        self.assertTrue(all(row['policy_sources'].values()))
        encoded = encode(row['policy_sources'])
        self.assertIn(a['audit']['native_record']['sha256'].encode(), encoded)
        self.assertIn(self.effective['max_rounds']['source']['sha256'].encode(), encoded)


class SlotLifecycleTests(unittest.TestCase):
    """Resource evidence is separate from votes; VM tests use a logical clock only.

    Negative targets: clearing uncovered unknowns, trusting caller flags, mutating
    the baseline, accepting rewritten times, or freeing physical calls at 120s.
    """
    def setUp(self):
        self.n = NativeEvidenceTests('test_complete_mapping_raw_refs_and_two_clocks')
        self.n.setUp()
        self.addCleanup(self.n.doCleanups)
        self.f, self.mod = self.n.f, self.n.mod
        node = self.n.native['workflowProgress'][1]
        node.update(state='progress')
        node.pop('durationMs')
        node.pop('startedAt')
        other = copy.deepcopy(node)
        other.update(agentId='other-agent', label=self.f.record()['roles'][1]['label'],
                     agentType=self.f.record()['roles'][1]['agentType'])
        self.n.native['workflowProgress'].append(other)
        self.n.native['agentCount'] = 2
        for seat in self.n.native['result']['results']:
            seat.update(attempted=seat['index'] < 2, settled=False, raw=None)
        self.n.capture()
        captured = self.mod._Inputs()
        self.audit = self.n.classify(captured)
        self.frozen = self.mod._FrozenInputs(dict(captured.raw))
        self.scope = self.f.scope()
        self.state = self.mod._load_scope(self.scope, self.f.manifest, self.mod._Inputs())
        self.original = encode(self.audit)
        self.baseline_files = {p: p.read_bytes() for p in self.f.run_dir.iterdir() if p.is_file()}

    def view(self, attempts=None, **kw):
        return self.mod._resource_view([self.audit] if attempts is None else attempts,
            inputs=self.frozen, **kw)

    def preflight(self, native=None, links=None, name='later'):
        path = self.f.run_dir / (name + '.json')
        self.f.write(path, copy.deepcopy(self.n.native) if native is None else native)
        pre = self.f.run_dir / (name + '-preflight.json')
        self.f.write(pre, {'schema_version': 1, 'observations': [{
            'workflow_run_id': 'synthetic-run', 'native_record': {**ref(path), 'path': path.name},
            'termination_refs': links or []}]})
        return pre

    def apply(self, pre):
        return self.mod._apply_preflight(self.state, self.scope, [self.audit], ref(pre), pre,
                                         inputs=self.frozen)

    def completed(self, indices=(1, 2)):
        native = copy.deepcopy(self.n.native)
        for index in indices:
            native['workflowProgress'][index].update(state='done', startedAt=1100, durationMs=400000)
        return native

    def reject(self, pre, code=None):
        before = {p: p.read_bytes() for p in self.scope.rglob('*') if p.is_file()}
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.apply(pre)
        if code:
            self.assertEqual(caught.exception.error_code, code)
        self.assertEqual(before, {p: p.read_bytes() for p in self.scope.rglob('*') if p.is_file()})

    def test_unknown_residual_void_and_not_dispatched_ignore_claimed_policy(self):
        audit = copy.deepcopy(self.audit)
        audit.update(all_failed_void=True, complete=True, policy_ok=True,
                     next_round_dispatch_allowed=True)
        view = self.view([audit])
        self.assertEqual(len(view['calls']), 2)
        self.assertEqual(len(view['unknown_calls']), 2)
        self.assertFalse(view['next_round_dispatch_allowed'])
        self.assertEqual(view['available_slots'], 0)

    def test_checker_full_capacity_is_pending_not_synthetic_failure(self):
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.view(for_checker=True)
        self.assertEqual(caught.exception.error_code, 'E_RESOURCE_PENDING')

    def test_partial_observation_keeps_uncovered_unknown_and_allows_one_checker(self):
        view = self.apply(self.preflight(self.completed((1,))))
        self.assertEqual(len(view['unknown_calls']), 1)
        self.assertEqual(view['available_slots'], 1)
        self.assertFalse(view['next_round_dispatch_allowed'])
        checker = self.view(observes=self.state['events'], scope=self.scope, for_checker=True)
        self.assertEqual(checker['available_slots'], 1)
        self.assertEqual(encode(self.audit), self.original)
        for p, raw in self.baseline_files.items():
            self.assertEqual(p.read_bytes(), raw)

    def test_cross_session_observe_replays_and_preserves_reserve_count(self):
        self.apply(self.preflight(self.completed()))
        state = self.mod._load_scope(self.scope, self.f.manifest, self.mod._Inputs())
        view = self.view(observes=state['events'], scope=self.scope)
        self.assertTrue(view['next_round_dispatch_allowed'])
        self.assertEqual(state['reserve_count'], 1)
        self.assertEqual(state['pending']['event']['kind'], 'reserve')
        self.assertEqual([v['event']['kind'] for v in state['events']], ['reserve', 'observe'])
        self.assertEqual(state['events'][-1]['event']['payload'].keys(), {'preflight'})

    def test_started_only_is_not_completion_or_permission(self):
        native = copy.deepcopy(self.n.native)
        native['workflowProgress'][1]['startedAt'] = 1100
        view = self.apply(self.preflight(native))
        self.assertEqual(len(view['unknown_calls']), 2)
        self.assertIsNone(view['calls'][0]['completed_at_ms'])
        self.assertEqual(view['calls'][0]['started_at_ms'], 1100)

    def test_second_observe_cannot_rewrite_previously_filled_start(self):
        native = copy.deepcopy(self.n.native)
        native['workflowProgress'][1]['startedAt'] = 1100
        self.apply(self.preflight(native))
        for changed in (1200, None):
            bad = copy.deepcopy(native)
            if changed is None:
                bad['workflowProgress'][1].pop('startedAt')
            else:
                bad['workflowProgress'][1]['startedAt'] = changed
            self.reject(self.preflight(bad, name='second'+str(changed)), 'E_NATIVE_TIME')

    def test_observe_outer_duration_uses_latest_folded_baseline_and_replays(self):
        first = self.completed()
        first['durationMs'] += 1000
        self.apply(self.preflight(first, name='duration-first'))
        state_before = copy.deepcopy(self.state)
        regressed = copy.deepcopy(first)
        regressed['durationMs'] = self.n.native['durationMs'] + 1
        self.reject(self.preflight(regressed, name='duration-regressed'), 'E_NATIVE_TIME')
        self.assertEqual(self.state, state_before)
        replayed = self.view(observes=self.state['events'], scope=self.scope)
        self.assertTrue(replayed['next_round_dispatch_allowed'])
        later = copy.deepcopy(first)
        later['durationMs'] += 1
        self.apply(self.preflight(later, name='duration-valid-later'))
        self.assertEqual(len(self.state['events']), 3)
        self.assertTrue(self.view(observes=self.state['events'], scope=self.scope)['next_round_dispatch_allowed'])
        self.assertEqual(encode(self.audit), self.original)

    def test_observe_cannot_replace_immutable_audit_result_snapshot(self):
        for mutation in ('empty', 'cycle', 'attempted'):
            with self.subTest(mutation=mutation):
                case = SlotLifecycleTests(self._testMethodName)
                case.setUp()
                try:
                    native = case.completed()
                    if mutation == 'empty':
                        native['result'] = {}
                    elif mutation == 'cycle':
                        native['result']['identity'] = {**native['result']['identity'], 'audit_cycle_id': 'other-cycle'}
                    else:
                        native['result']['results'][0]['attempted'] = False
                    state_before = copy.deepcopy(case.state)
                    case.reject(case.preflight(native), 'E_NATIVE_EVIDENCE')
                    self.assertEqual(case.state, state_before)
                    self.assertEqual(len(case.view(observes=case.state['events'], scope=case.scope)['unknown_calls']), 2)
                finally:
                    case.doCleanups()

    def test_observe_cannot_replace_immutable_checker_result_snapshot(self):
        for mutation in ('valid', 'empty', 'cycle', 'attempted'):
            with self.subTest(mutation=mutation):
                helper = DriftEvidenceTests('test_checker_raw_is_not_a_vote_and_native_clock_is_not_audit_budget')
                helper.setUp()
                try:
                    helper.native['workflowProgress'][1].update(state='progress')
                    helper.native['workflowProgress'][1].pop('durationMs')
                    helper.native['result'].update(settled=False, raw=None)
                    helper.native['result']['control'].update(stop_observed=True, return_reason='control_timeout')
                    helper.capture()
                    drift = helper.verify()
                    state = helper.mod._load_scope(helper.f.scope(), helper.f.manifest, helper.mod._Inputs())
                    state_before = copy.deepcopy(state)
                    native = copy.deepcopy(helper.native)
                    native['workflowProgress'][1].update(state='done', durationMs=400000)
                    if mutation == 'empty':
                        native['result'] = {}
                    elif mutation == 'cycle':
                        native['result']['identity'] = {**native['result']['identity'], 'audit_cycle_id': 'other-cycle'}
                    elif mutation == 'attempted':
                        native['result']['call_attempted'] = False
                    observed = helper.f.root / 'checker-later.json'
                    helper.f.write(observed, native)
                    pre = helper.f.root / 'checker-preflight.json'
                    helper.f.write(pre, {'schema_version': 1, 'observations': [{
                        'workflow_run_id': native['runId'], 'native_record': ref(observed), 'termination_refs': []}]})
                    before = {p: p.read_bytes() for p in helper.f.scope().rglob('*') if p.is_file()}
                    if mutation == 'valid':
                        result = helper.mod._apply_preflight(state, helper.f.scope(), [drift], ref(pre), pre)
                        self.assertTrue(result['next_round_dispatch_allowed'])
                        self.assertTrue(helper.mod._resource_view([drift], observes=state['events'],
                                                                  scope=helper.f.scope())['next_round_dispatch_allowed'])
                        self.assertIsNone(drift['auxiliary_calls'][0]['completed_at_ms'])
                    else:
                        with self.assertRaises(helper.mod.ExecutorError) as caught:
                            helper.mod._apply_preflight(state, helper.f.scope(), [drift], ref(pre), pre)
                        self.assertEqual(caught.exception.error_code, 'E_NATIVE_EVIDENCE')
                        self.assertEqual(state, state_before)
                        self.assertEqual({p: p.read_bytes() for p in helper.f.scope().rglob('*') if p.is_file()}, before)
                finally:
                    helper.doCleanups()

    def test_known_duration_and_C_cannot_change_or_clear(self):
        native = self.completed()
        self.apply(self.preflight(native))
        for key in ('startedAt', 'durationMs'):
            bad = copy.deepcopy(native)
            bad['workflowProgress'][1][key] += 1
            self.reject(self.preflight(bad, name=key), 'E_NATIVE_TIME')
        bad = copy.deepcopy(self.n.native)
        self.reject(self.preflight(bad, name='clear'), 'E_NATIVE_TIME')

    def test_native_identity_script_node_and_q_mismatch_are_atomic(self):
        for key, value in [('runId', 'other-run'), ('script', '// not the executed script'),
                           ('startTime', 1001), ('args', {})]:
            bad = self.completed()
            bad[key] = value
            self.reject(self.preflight(bad, name=key))
        for key, value in [('agentId', 'other'), ('agentType', 'other'), ('label', 'other'),
                           ('queuedAt', 1001), ('startedAt', True), ('startedAt', 999)]:
            bad = self.completed()
            bad['workflowProgress'][1][key] = value
            self.reject(self.preflight(bad, name=key+str(value)))

    def test_bad_second_observation_writes_no_partial_event_or_blobs(self):
        pre = self.preflight(self.completed())
        payload = json.loads(pre.read_bytes())
        payload['observations'].append({**payload['observations'][0], 'workflow_run_id': 'unknown-run'})
        self.f.write(pre, payload)
        self.reject(pre)

    def test_exact_preflight_schema_and_native_fields_not_length(self):
        pre = self.preflight(self.completed())
        original = json.loads(pre.read_bytes())
        for replacement in ({**original, 'complete': True}, {'schema_version': True, 'observations': []},
                            {'schema_version': 1, 'observations': [{**original['observations'][0], 'policy_ok': True}]}):
            self.f.write(pre, replacement)
            self.reject(pre)
        for key, value in [('status', 'running'), ('agentCount', True), ('agentCount', 1),
                           ('workflowProgress', []), ('durationMs', False)]:
            bad = self.completed()
            bad[key] = value
            self.reject(self.preflight(bad, name=key))

    def interrupt(self):
        log = self.f.run_dir / 'later-events.jsonl'
        event = {'type': 'user', 'agentId': 'synthetic-agent', 'uuid': 'later-event',
            'message': {'role': 'user', 'content': '[Request interrupted by user]'}}
        log.write_bytes(encode({'text': ' '}) + b'\n' + encode(event) + b'\n')
        link = {'native_pointer': '/workflowProgress/1', 'agent_id': 'synthetic-agent',
            'event': {'file': {**ref(log), 'path': log.name}, 'line': 2,
                      'agent_id': 'synthetic-agent', 'event_uuid': 'later-event'}}
        return log, link

    def test_interruption_releases_resource_without_backfilling_C_or_old_vote(self):
        _, link = self.interrupt()
        view = self.apply(self.preflight(links=[link]))
        self.assertEqual(view['calls'][0]['termination_evidence'], 'interrupted_observed')
        self.assertIsNone(view['calls'][0]['completed_at_ms'])
        self.assertEqual(len(view['unknown_calls']), 1)
        self.assertEqual(encode(self.audit), self.original)

    def test_bad_interruption_refs_never_become_unknown(self):
        _, link = self.interrupt()
        for field, value in [('line', 1), ('event_uuid', 'wrong'), ('agent_id', 'wrong')]:
            bad = copy.deepcopy(link)
            bad['event'][field] = value
            self.reject(self.preflight(links=[bad], name=field), 'E_NATIVE_EVIDENCE')
        bad = copy.deepcopy(link)
        bad['event']['file']['sha256'] = '0' * 64
        self.reject(self.preflight(links=[bad], name='hash'), 'E_NATIVE_EVIDENCE')

    def test_frozen_relative_carriers_survive_live_growth_and_deletion(self):
        log, link = self.interrupt()
        pre = self.preflight(links=[link])
        self.apply(pre)
        log.write_bytes(log.read_bytes() + b'{}\n')
        pre.unlink()
        (self.f.run_dir / 'later.json').unlink()
        log.unlink()
        state = self.mod._load_scope(self.scope, self.f.manifest, self.mod._Inputs())
        view = self.view(observes=state['events'], scope=self.scope)
        self.assertEqual(view['calls'][0]['termination_evidence'], 'interrupted_observed')
        self.assertEqual(len(view['unknown_calls']), 1)

    def test_auxiliary_tool_error_unknown_is_not_erased_by_audit_completion(self):
        drift = DriftEvidenceTests('test_checker_raw_is_not_a_vote_and_native_clock_is_not_audit_budget')
        drift.setUp()
        self.addCleanup(drift.doCleanups)
        drift.tool_error()
        auxiliary = drift.verify()
        self.assertEqual(auxiliary['failure_observation'], 'tool_error')
        self.apply(self.preflight(self.completed()))
        view = self.view([self.audit, auxiliary], observes=self.state['events'], scope=self.scope)
        self.assertEqual(len(view['unknown_calls']), 1)
        self.assertFalse(view['next_round_dispatch_allowed'])

    def test_actual_generated_scheduler_retains_physical_calls_until_return_characterization(self):
        helper = GeneratedScriptTests('test_audit_args_are_closed_and_hash_bound_characterization')
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        fourth = 'aria:fourth-seat'
        helper.f.config_value['audit']['teams']['post_spec'].append(fourth)
        helper.f.write(helper.f.config, helper.f.config_value)
        helper.f.manifest['roles'].append({'role_id': fourth, 'agentType': fourth,
                                          'model_alias': 'inherit', 'prompt': 'fourth'})
        script, args = helper.audit()
        trace = helper.run_js(script, args, [{'kind': 'advance', 'ms': 120000},
            {'kind': 'resolve', 'index': 0, 'value': None}, {'kind': 'advance', 'ms': 180000},
            {'kind': 'resolve', 'index': 1, 'value': None}])
        self.assertEqual([len(x['calls']) for x in trace], [2, 2, 3, 3, 3])
        self.assertEqual(trace[3]['active'], 2)
        self.assertTrue(trace[3]['returned'])
        self.assertTrue(all(x['maxActive'] <= 2 for x in trace))
        # Independently assembled bad program: two logical workers race agent against
        # 120s without cancellation. At 120s all four physical promises are pending.
        bad = b'export const meta = {"name":"bad","phases":[{"title":"Audit"}]}\n' + r"""
phase('Audit');
let next=0;
async function worker(){while(next<4){const i=next++;
  await Promise.race([agent('seat '+i,{agentType:'test',label:String(i),phase:'Audit'}),
                     new Promise(resolve=>setTimeout(resolve,120000))]);}}
await Promise.all([worker(),worker()]);
return null;
""".encode()
        bad_trace = helper.run_js(bad, {}, [{'kind': 'advance', 'ms': 120000}])
        self.assertEqual(bad_trace[-1]['active'], 4)
        with self.assertRaises(AssertionError):
            self.assertLessEqual(bad_trace[-1]['maxActive'], 2)


    def test_omitting_one_attempted_role_is_not_a_complete_population(self):
        bad = copy.deepcopy(self.audit)
        bad['roles'] = [bad['roles'][0], bad['roles'][2]]
        with self.assertRaises(self.mod.ExecutorError):
            self.view([bad])

    def test_empty_preflight_does_not_erase_old_unknown(self):
        pre = self.f.run_dir / 'empty-preflight.json'
        self.f.write(pre, {'schema_version': 1, 'observations': []})
        view = self.apply(pre)
        self.assertEqual(len(view['unknown_calls']), 2)

    def test_frozen_native_blob_tamper_is_rejected_not_read_from_live(self):
        pre = self.preflight(self.completed())
        self.apply(pre)
        native = self.f.run_dir / 'later.json'
        blob = self.scope / 'blobs' / (ref(native)['sha256'] + '.blob')
        blob.write_bytes(b'{}')
        with self.assertRaises(self.mod.ExecutorError):
            self.mod._load_scope(self.scope, self.f.manifest, self.mod._Inputs())

    def test_observe_does_not_open_budget_or_terminal_policy_gate(self):
        self.apply(self.preflight(self.completed()))
        for changes in ({'remaining_rounds': 0}, {'terminal_state': 'CONVERGED'},
                        {'terminal_state': 'DRIFT_TERMINATED'}, {'terminal_state': 'OSCILLATION'},
                        {'overridden_by_user': True}, {'degraded': True}):
            view = {'remaining_rounds': 1, 'terminal_state': None,
                    'overridden_by_user': False, 'degraded': False, **changes}
            with self.assertRaises(self.mod.ExecutorError) as caught:
                self.mod._require_dispatch_policy(view)
            self.assertEqual(caught.exception.error_code, 'E_POLICY_BLOCKED')
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.mod._replay_history(self.state)
        self.assertEqual(caught.exception.error_code, 'E_POLICY_SOURCE')


    def test_unknown_tool_failure_retains_locatable_original_references(self):
        drift = DriftEvidenceTests('test_checker_raw_is_not_a_vote_and_native_clock_is_not_audit_budget')
        drift.setUp()
        self.addCleanup(drift.doCleanups)
        drift.tool_error()
        auxiliary = drift.verify()
        view = self.view([self.audit, auxiliary])
        row = view['unknown_calls'][-1]
        self.assertEqual(row.get('tool_call_ref'), auxiliary['auxiliary_calls'][0]['tool_call_ref'])
        self.assertEqual(row.get('tool_response_ref'), auxiliary['auxiliary_calls'][0]['tool_response_ref'])

    def test_unknown_auxiliary_workflow_keeps_slot_after_real_timeout_characterization(self):
        drift = DriftEvidenceTests('test_checker_raw_is_not_a_vote_and_native_clock_is_not_audit_budget')
        drift.setUp()
        self.addCleanup(drift.doCleanups)
        drift.unfinished()
        drift.capture()
        captured = drift.mod._Inputs()
        auxiliary = drift.verify(captured)
        self.frozen = self.mod._FrozenInputs({**self.frozen.raw, **captured.raw})
        self.apply(self.preflight(self.completed()))
        view = self.view([self.audit, auxiliary], observes=self.state['events'], scope=self.scope)
        self.assertEqual(len(view['unknown_calls']), 1)
        self.assertEqual(view['available_slots'], 1)
        self.assertFalse(view['next_round_dispatch_allowed'])
        self.assertIsNotNone(view['unknown_calls'][0]['native_ref'])

    def test_stale_prefix_cannot_append_observe_characterization(self):
        stale = copy.deepcopy(self.state)
        self.apply(self.preflight(self.completed()))
        current = self.state
        self.state = stale
        self.reject(self.preflight(self.completed(), name='stale'), 'E_SCOPE_BUSY')
        self.state = current


    def test_pending_identical_build_after_observe_is_resume_only_characterization(self):
        self.apply(self.preflight(self.completed()))
        events = {p: p.read_bytes() for p in (self.scope / 'events').iterdir()}
        result = self.f.build()
        self.assertTrue(result['resume_only'])
        self.assertEqual(events, {p: p.read_bytes() for p in (self.scope / 'events').iterdir()})
        for p, raw in self.baseline_files.items():
            self.assertEqual(p.read_bytes(), raw)

    def test_bad_second_call_leaves_baseline_and_events_unchanged_characterization(self):
        bad = self.completed()
        bad['workflowProgress'][2]['queuedAt'] = 1001
        self.reject(self.preflight(bad), 'E_NATIVE_TIME')
        self.assertEqual(encode(self.audit), self.original)
        self.assertEqual(len(self.view()['unknown_calls']), 2)


class HistoricalReplayTests(unittest.TestCase):
    """Finite synthetic protocol chains, never historical/real tool receipts.

    Removing recursive source verification, using a result boolean as policy, or
    releasing unknown resources must make these behavioral assertions fail.
    """
    def setUp(self):
        self.f = BuildContractTests('test_missing_project_and_missing_key_remain_false_without_team_or_evidence')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.mod = self.f.mod
        self.attempts = []
        self.results = []

    def start(self, limit=5, full=False):
        self.f.defaults_value['audit']['max_rounds'] = limit
        self.f.write(self.f.defaults, self.f.defaults_value)
        if full:
            self.f.policy_value['anchor_selection']['in_scope'] = [copy.deepcopy(
                self.f.policy_value['anchor_selection']['primary_goal'])]
            self.f.write(self.f.policy, self.f.policy_value)
            self.f.manifest['evidence']['policy_inputs'] = ref(self.f.policy)
        self.f.build()
        self.genesis = json.loads((self.f.scope() / 'genesis.json').read_bytes())
        self.anchor = {'record': json.loads(Path(self.genesis['anchor']['path']).read_bytes()),
                       'source': self.genesis['anchor']}

    def state(self):
        return self.mod._load_scope(self.f.scope(), self.f.manifest, self.mod._Inputs())

    def replay(self):
        return self.mod._replay_history(self.state())

    def next_build(self, round_number, attempt_index):
        previous = self.results[-1] if self.results else None
        self.f.run_dir = self.f.repo / '.aria' / 'audit-reports' / (
            f'post_spec-R{round_number}-client-{attempt_index}-build-target-aggregated')
        self.f.manifest_path = self.f.repo / f'manifest-{attempt_index}.json'
        self.f.manifest.update(round=round_number, attempt_index=attempt_index,
                               client_round_id=f'client-{attempt_index}')
        self.f.manifest['evidence'].update(cycle_origin=ref(self.f.scope() / 'genesis.json'),
            previous_round=previous,
            post_audit_index_path=str(self.f.run_dir / 'audit-index.json'),
            post_drift_index_path=str(self.f.run_dir / 'drift-index.json'),
            post_disposition_index_path=str(self.f.run_dir / 'disposition-index.json'))
        return self.f.build()

    def finish(self, admitted=(0, 1), findings=None, unknown=False, classes=None, skipped=False,
               carriers=None):
        f, mod = self.f, self.mod
        carriers = carriers or {}
        build = f.record()
        ident = build['identity']
        run_id = 'synthetic-audit-' + ident['client_round_id']
        seats, nodes = [], []
        for i, role in enumerate(build['roles']):
            report = {'vote': 'REVISE' if findings else 'PASS', 'coverage_complete': True,
                      'findings': findings or [], 'pending': [], 'prior_findings': []}
            seats.append({**{k: role[k] for k in ('index', 'role_id', 'agentType', 'label')},
                'attempted': True, 'settled': not (unknown and i == 2),
                'raw': encode(report).decode() if i in admitted else None, 'error': None})
            node = {'type': 'workflow_agent', 'agentId': run_id + '-' + str(i),
                'agentType': role['agentType'], 'label': role['label'], 'model': 'synthetic',
                'queuedAt': 1000 + i * 100, 'startedAt': 1000 + i * 100,
                'durationMs': 10, 'state': 'done'}
            if unknown and i == 2:
                node.pop('durationMs'); node['state'] = 'progress'
            nodes.append(node)
        native = {'runId': run_id, 'startTime': 1000, 'durationMs': 300020,
            'status': 'completed', 'agentCount': 3, 'script': (f.run_dir / 'workflow.js').read_text(),
            'args': {'identity': ident, 'manifest_sha256': build['manifest']['sha256']},
            'workflowProgress': nodes, 'result': {'schema_version': 1, 'identity': ident,
                'manifest_sha256': build['manifest']['sha256'], 'results': seats,
                'control': {'round_timer_ms': 300000, 'stop_observed': unknown,
                            'return_reason': 'control_timeout' if unknown else 'all_settled'}}}
        native_path, index_path = f.run_dir / 'native.json', f.run_dir / 'audit-index.json'
        f.write(native_path, native)
        f.write(index_path, {'schema_version': 1, 'identity': ident,
            'attempt_index': build['attempt_index'], 'workflow_run_id': run_id,
            'native_record': ref(native_path), 'termination_refs': []})
        captured = mod._Inputs()
        audit = mod._classify_native(f.repo, f.manifest_path, f.run_dir / 'build-record.json',
                                    run_id, native_path, index_path, inputs=captured)
        view = mod._aggregate_admitted(audit['roles'])
        self.assertEqual(len(view['admitted_roles']), len(admitted), 'fixture must actually reach admission')
        reason = ('all_failed_void' if view['all_failed_void'] else 'first_round' if ident['round'] == 1
                  else 'empty_conclusions' if not view['conclusions'] else 'required')
        audit_closure = mod._freeze_closure(captured, f.scope(), f.run_dir / 'audit-closure.json')
        request = {'schema_version': 1, 'algorithm_version': 'canonical_v1', 'identity': ident,
            'attempt_index': build['attempt_index'], 'genesis': build['genesis'],
            'anchor': self.genesis['anchor'], 'audit_index': ref(index_path),
            'input_closure': audit_closure, 'conclusions': view['conclusions'],
            'required': reason == 'required', 'reason': reason,
            'checker': {'agentType': build['roles'][0]['agentType'],
                        'label': 'drift:' + ident['client_round_id'], 'timeout_ms': 60000}
                       if reason == 'required' else None}
        request_path = f.run_dir / 'policy-request.json'
        f.write(request_path, request)
        if carriers.get('request'):
            request_path = f.run_dir / 'request' / 'nested' / 'policy-request.json'
            for field in carriers['request']:
                request[field] = {**request[field], 'path': os.path.relpath(
                    request[field]['path'], request_path.parent)}
            f.write(request_path, request)
        if carriers.get('bad_request'):
            field = carriers['bad_request']
            original = mod._path(request[field]['path'], request_path)
            other = f.run_dir / ('other-' + field + '.json')
            other.write_bytes(original.read_bytes())
            request[field] = ref(other)
            request_path = f.run_dir / 'wrong-request.json'
            f.write(request_path, request)
            captured.read(other)
        drift, drift_ref, script_ref = None, None, None
        if reason == 'required':
            script_path = f.run_dir / 'policy-workflow.js'
            script_path.write_bytes(mod._render_policy_workflow(ref(request_path)))
            raw = encode({'classifications': [{'key': k, 'classification': c} for k, c in
                zip(view['comparison_keys'], classes or ['on_topic'] * len(view['comparison_keys']))]}).decode()
            checker = request['checker']
            checker_native = {'runId': 'synthetic-checker-' + ident['client_round_id'],
                'startTime': 400000, 'durationMs': 60001, 'status': 'completed', 'agentCount': 1,
                'script': script_path.read_text(), 'args': {'identity': ident,
                    'request_sha256': ref(request_path)['sha256'], 'anchor': self.anchor['record']['value'],
                    'conclusions': request['conclusions']},
                'workflowProgress': [{'type': 'workflow_agent', 'agentId': 'checker-' + run_id,
                    'agentType': checker['agentType'], 'label': checker['label'], 'model': 'synthetic',
                    'queuedAt': 400000, 'startedAt': 400000, 'durationMs': 10, 'state': 'done'}],
                'result': {'schema_version': 1, 'identity': ident,
                    'request_sha256': ref(request_path)['sha256'], 'agentType': checker['agentType'],
                    'label': checker['label'], 'call_attempted': True, 'settled': not skipped,
                    'raw': None if skipped else raw, 'error': None,
                    'control': {'timeout_ms': 60000, 'stop_observed': skipped,
                                'return_reason': 'control_timeout' if skipped else 'all_settled'}}}
            dn, di = f.run_dir / 'checker-native.json', f.run_dir / 'drift-index.json'
            f.write(dn, checker_native)
            f.write(di, {'schema_version': 1, 'identity': ident, 'attempt_index': build['attempt_index'],
                'request': ref(request_path), 'kind': 'workflow', 'workflow_run_id': checker_native['runId'],
                'native_record': ref(dn), 'termination_refs': [], 'tool_failure': None})
            drift = mod._verify_drift(di, ref(request_path), script_path, inputs=captured)
            drift_ref, script_ref = ref(di), ref(script_path)
        for path in (request_path, Path(audit_closure['path'])):
            captured.read(path)
        prepare_path = f.run_dir / 'prepare-record.json'
        publication_path = f.run_dir / 'publication-record.json'
        f.write(prepare_path, {'schema_version': 1, 'identity': ident, 'attempt_index': build['attempt_index'],
            'audit_index': ref(index_path), 'input_closure': audit_closure, 'policy_request': ref(request_path),
            'policy_script': script_ref, 'generated_at': 'synthetic-prepare', 'host_prepare_duration_ms': 2})
        f.write(publication_path, {'schema_version': 1, 'identity': ident, 'attempt_index': build['attempt_index'],
            'generated_at': 'synthetic-publication', 'host_collect_duration_ms': 3})
        captured.read(prepare_path)
        if carriers:
            prepare = json.loads(prepare_path.read_bytes())
            prepare_path = f.run_dir / 'prepare' / 'nested' / 'prepare-record.json'
            field = carriers.get('bad_prepare') or ('policy_script' if carriers.get('script_copy') else None)
            if field:
                original = Path(prepare[field]['path'])
                other = f.run_dir / ('other-' + original.name)
                other.write_bytes(b'not the generated checker script\n' if field == 'policy_script'
                                  and not carriers.get('script_copy') else original.read_bytes())
                prepare[field] = ref(other)
                captured.read(other)
            for field in carriers.get('prepare', ()):
                if prepare[field] is not None:
                    prepare[field] = {**prepare[field], 'path': os.path.relpath(
                        prepare[field]['path'], prepare_path.parent)}
            f.write(prepare_path, prepare)
            captured.read(prepare_path)
        captured.read(publication_path)
        attempt = {'identity': ident, 'attempt_index': build['attempt_index'], 'audit': audit, 'drift': drift}
        self.attempts.append(attempt)
        row = mod._apply_policy(self.genesis, self.attempts, build['effective_config'], self.anchor)['attempts'][-1]
        closure = mod._freeze_closure(captured, f.scope(), f.run_dir / 'final-closure.json')
        reserve = json.loads(Path(build['reservation']['path']).read_bytes())
        result = {k: v for k, v in row.items() if k not in ('policy', 'policy_sources')}
        result.update(schema_version=1, identity=ident, budgets=dict(mod.BUDGETS),
            inputs={'manifest': build['manifest'], 'build_record': ref(f.run_dir / 'build-record.json'),
                'config': build['sources']['config'], 'defaults': build['sources']['defaults'],
                'workflow_script': build['workflow_script'], 'native_record': ref(native_path),
                'genesis': build['genesis'], 'reservation': build['reservation'], 'input_closure': closure,
                'audit_index': ref(index_path), 'policy_request': ref(request_path),
                'prepare_record': ref(prepare_path), 'publication_record': ref(publication_path),
                'prefix_head': build['prefix_head'], 'previous_round': reserve['payload']['previous_round'],
                'previous_attempt': reserve['payload']['previous_attempt'], 'drift_index': drift_ref},
            attempt_index=build['attempt_index'], workflow_run_id=run_id,
            workflow_script_sha256=build['workflow_script']['sha256'], roles=audit['roles'],
            dispatched_roles=[r['role_id'] for r in audit['roles'] if r['attempted']],
            require_same_admitted_roles=True,
            clock={**{k: v for k, v in audit.items() if k not in ('roles', 'workflow_run_id', 'native_record')},
                   'host_prepare_duration_ms': 2, 'host_collect_duration_ms': 3},
            policy={**row['policy'], 'sources': row['policy_sources']},
            next_round_dispatch_allowed=mod._resource_view([a['audit'] for a in self.attempts] +
                [a['drift'] for a in self.attempts if a['drift'] is not None],
                observes=self.state()['events'], scope=f.scope())['next_round_dispatch_allowed'],
            generated_at='synthetic-publication')
        result_path = f.run_dir / 'result.json'
        f.write(result_path, result)
        markdown = f.run_dir / 'result.md'
        markdown.write_text('Synthetic fixture; not a real Workflow receipt.\n')
        state = self.state()
        event = {'schema_version': 1, 'seq': len(state['events']) + 1, 'genesis': state['genesis_ref'],
            'previous_event': state['head'], 'kind': 'commit', 'payload': {'reservation': build['reservation'],
                'result': ref(result_path), 'markdown': ref(markdown), 'input_closure': closure}}
        f.write(f.scope() / 'events' / f"{event['seq']:010d}.json", event)
        self.last_result, self.last_native = result_path, native
        if not row['all_failed_void']:
            self.results.append(ref(result_path))
        return result

    def reject_replay(self, code):
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.replay()
        self.assertEqual(caught.exception.error_code, code)

    def test_two_effective_partial_roles_converge_from_frozen_raw(self):
        self.start(); self.finish(); self.next_build(2, 2); self.finish()
        self.last_result.parent.joinpath('native.json').unlink()
        self.f.context.write_text('opaque live context may change')
        view = self.replay()
        self.assertEqual(view['charged_rounds'], 2)
        self.assertEqual(view['terminal_state'], 'CONVERGED')
        self.assertEqual(view['latest_round'], ref(self.last_result))

    def test_void_keeps_round_baseline_and_does_not_charge(self):
        self.start(); self.finish(); self.next_build(2, 2); self.finish(admitted=())
        self.assertEqual(self.replay()['charged_rounds'], 1)
        self.next_build(2, 3); self.finish()
        view = self.replay()
        self.assertEqual([r['policy']['charged_rounds'] for r in view['rounds']], [1, 1, 2])
        self.assertTrue(view['rounds'][-1]['converged'])

    def test_exhausted_build_rejects_before_script_or_reserve(self):
        self.start(limit=1); self.finish()
        before = {p: p.read_bytes() for p in self.f.scope().rglob('*') if p.is_file()}
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.next_build(2, 2)
        self.assertEqual(caught.exception.error_code, 'E_POLICY_BLOCKED')
        self.assertFalse((self.f.run_dir / 'workflow.js').exists())
        self.assertEqual(before, {p: p.read_bytes() for p in self.f.scope().rglob('*') if p.is_file()})

    def test_unknown_resource_blocks_new_build_before_policy_even_if_exhausted(self):
        self.start(limit=1); self.finish(unknown=True)
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.next_build(2, 2)
        self.assertEqual(caught.exception.error_code, 'E_RESOURCE_PENDING')
        self.assertEqual(len(list((self.f.scope() / 'events').iterdir())), 2)
        self.assertFalse((self.f.run_dir / 'workflow.js').exists())

    def test_result_derived_values_cannot_authorize_history(self):
        self.start(); self.finish()
        original = self.last_result.read_bytes()
        for field in ('admitted_roles', 'converged', 'policy'):
            value = json.loads(original)
            value[field] = ([] if field == 'admitted_roles' else True if field == 'converged' else
                            {**value['policy'], 'charged_rounds': 0})
            self.f.write(self.last_result, value)
            event_path = self.f.scope() / 'events' / '0000000002.json'
            event = json.loads(event_path.read_bytes()); event['payload']['result'] = ref(self.last_result)
            self.f.write(event_path, event)
            self.reject_replay('E_RESULT_MISMATCH')

    def test_back_edge_origin_precedes_bad_hash_check(self):
        self.start(); self.finish()
        value = json.loads(self.last_result.read_bytes())
        value['inputs']['previous_round'] = {'path': 'result.json', 'sha256': '0' * 64}
        self.f.write(self.last_result, value)
        event_path = self.f.scope() / 'events' / '0000000002.json'
        event = json.loads(event_path.read_bytes()); event['payload']['result'] = ref(self.last_result)
        self.f.write(event_path, event)
        self.reject_replay('E_HISTORY_CYCLE')

    def test_missing_frozen_native_leaf_is_not_first_round(self):
        self.start(); result = self.finish()
        blob = self.f.scope() / 'blobs' / (result['inputs']['native_record']['sha256'] + '.blob')
        blob.unlink()
        self.reject_replay('E_POLICY_SOURCE')

    def test_jump_attempt_is_identity_error_not_reset(self):
        self.start(); self.finish()
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.next_build(3, 3)
        self.assertEqual(caught.exception.error_code, 'E_PREVIOUS_IDENTITY')
        self.assertEqual(len(list((self.f.scope() / 'events').iterdir())), 2)

    def test_native_finding_path_objects_are_opaque(self):
        self.start()
        finding = _CanonicalPolicyFixture.finding(extra={'path': 'missing.json', 'sha256': '0' * 64})
        self.finish(findings=[finding])
        self.assertEqual(len(self.replay()['rounds'][0]['conclusions']), 1)

    def test_refocus_void_and_checker_skip_preserve_count(self):
        self.start(full=True)
        finding = _CanonicalPolicyFixture.finding()
        self.finish(findings=[finding]); self.next_build(2, 2)
        self.finish(findings=[finding], classes=['off_topic'])
        self.assertTrue(self.replay()['pending_refocus'])
        self.next_build(3, 3); self.finish(admitted=())
        self.assertTrue(self.replay()['pending_refocus'])
        self.next_build(3, 4); self.finish(findings=[finding], skipped=True)
        rows = self.replay()['rounds']
        self.assertEqual([r['policy']['consecutive_refocus_count'] for r in rows], [0, 1, 1, 1])
        self.assertTrue(rows[-1]['policy']['is_refocus'])
        self.assertTrue(rows[-1]['policy']['drift_check_skipped'])

    def test_same_pending_build_only_resumes_without_new_events(self):
        self.start(); self.finish(); self.next_build(2, 2)
        before = {p: p.read_bytes() for p in self.f.scope().rglob('*') if p.is_file()}
        self.assertTrue(self.f.build()['resume_only'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.f.scope().rglob('*') if p.is_file()})

    def test_terminal_converged_cannot_reserve_with_remaining_budget(self):
        self.start(); self.finish(); self.next_build(2, 2); self.finish()
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.next_build(3, 3)
        self.assertEqual(caught.exception.error_code, 'E_POLICY_BLOCKED')
        self.assertEqual(len(list((self.f.scope() / 'events').iterdir())), 4)

    def test_disposition_without_native_parser_fails_closed(self):
        self.start(limit=1); self.finish()
        state = self.state()
        event = {'schema_version': 1, 'seq': 3, 'genesis': state['genesis_ref'],
            'previous_event': state['head'], 'kind': 'disposition', 'payload': {'approved': True}}
        self.f.write(self.f.scope() / 'events' / '0000000003.json', event)
        self.reject_replay('E_POLICY_SOURCE')

    def test_preflight_releases_resources_without_rewriting_old_vote(self):
        self.start(); old = self.finish(unknown=True)
        before = self.last_result.read_bytes()
        later = copy.deepcopy(self.last_native)
        later['workflowProgress'][2].update(state='done', durationMs=20)
        path = self.f.repo / 'later-native.json'
        self.f.write(path, later)
        pre = self.f.repo / 'preflight.json'
        self.f.write(pre, {'schema_version': 1, 'observations': [{'workflow_run_id': later['runId'],
            'native_record': ref(path), 'termination_refs': []}]})
        self.f.manifest['evidence']['dispatch_preflight'] = ref(pre)
        self.next_build(2, 2); self.finish()
        view = self.replay()
        self.assertTrue(view['resource_view']['next_round_dispatch_allowed'])
        self.assertEqual(view['charged_rounds'], 2)
        self.assertEqual(self.results[0]['sha256'], hashlib.sha256(before).hexdigest())
        self.assertFalse(old['next_round_dispatch_allowed'])
        self.assertEqual([e['event']['kind'] for e in self.state()['events']],
                         ['reserve', 'commit', 'observe', 'reserve', 'commit'])

    def test_resource_clearance_cannot_bypass_exhausted_policy(self):
        self.start(limit=1); self.finish(unknown=True)
        later = copy.deepcopy(self.last_native)
        later['workflowProgress'][2].update(state='done', durationMs=20)
        path = self.f.repo / 'later-native.json'; self.f.write(path, later)
        pre = self.f.repo / 'preflight.json'
        self.f.write(pre, {'schema_version': 1, 'observations': [{'workflow_run_id': later['runId'],
            'native_record': ref(path), 'termination_refs': []}]})
        self.f.manifest['evidence']['dispatch_preflight'] = ref(pre)
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.next_build(2, 2)
        self.assertEqual(caught.exception.error_code, 'E_POLICY_BLOCKED')
        self.assertEqual(len(list((self.f.scope() / 'events').iterdir())), 2)
        self.assertFalse((self.f.run_dir / 'workflow.js').exists())

    def test_event_gap_rejects_without_changing_files_characterization(self):
        self.start(); self.finish()
        event = self.f.scope() / 'events' / '0000000002.json'
        event.rename(event.with_name('0000000003.json'))
        self.reject_replay('E_PREVIOUS_IDENTITY')

    def test_build_cannot_select_older_nonvoid_head(self):
        self.start(); finding = _CanonicalPolicyFixture.finding()
        self.finish(findings=[finding]); first = self.results[0]
        self.next_build(2, 2); self.finish(findings=[finding])
        self.results = [first]
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.next_build(3, 3)
        self.assertEqual(caught.exception.error_code, 'E_PREVIOUS_IDENTITY')
        self.assertFalse((self.f.run_dir / 'workflow.js').exists())

    def test_two_origin_cycle_checks_back_edge_before_invalid_hash(self):
        self.start(); result = self.finish()
        middle = copy.deepcopy(result)
        middle['inputs']['previous_round'] = {'path': str(self.last_result), 'sha256': '0' * 64}
        middle_path = self.f.repo / 'synthetic-cycle-middle.json'
        self.f.write(middle_path, middle)
        self.mod._freeze_blob(middle_path.read_bytes(), self.f.scope())
        result['inputs']['previous_round'] = ref(middle_path)
        self.f.write(self.last_result, result)
        ep = self.f.scope() / 'events' / '0000000002.json'
        event = json.loads(ep.read_bytes()); event['payload']['result'] = ref(self.last_result)
        self.f.write(ep, event)
        self.reject_replay('E_HISTORY_CYCLE')

    def test_bootstrapped_without_reserve_does_not_start_fresh_attempt(self):
        self.start()
        (self.f.scope() / 'events' / '0000000001.json').unlink()
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.next_build(1, 1)
        self.assertEqual(caught.exception.error_code, 'E_POLICY_SOURCE')
        self.assertFalse((self.f.run_dir / 'workflow.js').exists())

    def test_history_drift_termination_blocks_build(self):
        self.start(full=True); finding = _CanonicalPolicyFixture.finding()
        self.finish(findings=[finding]); self.next_build(2, 2)
        self.finish(findings=[finding], classes=['off_topic']); self.next_build(3, 3)
        self.finish(findings=[finding], classes=['off_topic'])
        self.assertEqual(self.replay()['terminal_state'], 'DRIFT_TERMINATED')
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.next_build(4, 4)
        self.assertEqual(caught.exception.error_code, 'E_POLICY_BLOCKED')
        self.assertFalse((self.f.run_dir / 'workflow.js').exists())

    def test_history_normal_oscillation_blocks_build(self):
        self.start(full=True)
        for n, scope in [(1, 'a'), (2, 'b'), (3, 'a')]:
            if n > 1:
                self.next_build(n, n)
            self.finish(findings=[_CanonicalPolicyFixture.finding(scope=scope)])
        self.assertEqual(self.replay()['terminal_state'], 'OSCILLATION')
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.next_build(4, 4)
        self.assertEqual(caught.exception.error_code, 'E_POLICY_BLOCKED')

    def test_history_highest_severity_and_member_conservation(self):
        self.start()
        findings = [_CanonicalPolicyFixture.finding(type='issue', severity='minor'),
                    _CanonicalPolicyFixture.finding(type='risk', severity='critical')]
        self.finish(findings=findings)
        row = self.replay()['rounds'][0]
        self.assertEqual([c['severity'] for c in row['conclusions']], ['critical', 'critical'])
        self.assertEqual(sum(len(v['members']) for c in row['conclusions'] for v in c['variants']), 4)
        self.assertEqual(row['verdict'], 'FAIL')

    def test_current_context_can_change_without_reanchoring_genesis(self):
        self.start(); self.finish()
        anchor = copy.deepcopy(self.genesis['anchor'])
        context = self.f.context; context.write_text('new current context at same opaque origin')
        policy = copy.deepcopy(self.f.policy_value); policy['context'] = ref(context)
        policy_path = self.f.repo / 'new-policy.json'; self.f.write(policy_path, policy)
        self.f.manifest['evidence']['policy_inputs'] = ref(policy_path)
        self.next_build(2, 2); self.finish()
        self.assertEqual(self.replay()['terminal_state'], 'CONVERGED')
        self.assertEqual(self.genesis['anchor'], anchor)

    def test_prepare_capture_must_contain_audit_native(self):
        self.start(); result = self.finish()
        final_path = Path(result['inputs']['input_closure']['path'])
        captured = self.mod._history_closure(result['inputs']['input_closure'], final_path,
                                           self.f.scope(), raw=final_path.read_bytes())
        prepare = json.loads(Path(result['inputs']['prepare_record']['path']).read_bytes())
        audit_closure = json.loads(Path(prepare['input_closure']['path']).read_bytes())
        native_path = result['inputs']['native_record']['path']
        audit_closure['sources'] = [e for e in audit_closure['sources'] if e['origin'] != native_path]
        bad_closure = self.f.run_dir / 'bad-audit-closure.json'; self.f.write(bad_closure, audit_closure)
        request = json.loads(Path(result['inputs']['policy_request']['path']).read_bytes())
        request['input_closure'] = ref(bad_closure)
        bad_request = self.f.run_dir / 'bad-request.json'; self.f.write(bad_request, request)
        prepare.update(input_closure=ref(bad_closure), policy_request=ref(bad_request))
        bad_prepare = self.f.run_dir / 'bad-prepare.json'; self.f.write(bad_prepare, prepare)
        for path in (bad_closure, bad_request, bad_prepare):
            captured.raw[str(path)] = path.read_bytes()
        final_ref = self.mod._freeze_closure(captured, self.f.scope(), self.f.run_dir / 'bad-final-closure.json')
        result['inputs'].update(input_closure=final_ref, policy_request=ref(bad_request),
                                prepare_record=ref(bad_prepare))
        self.f.write(self.last_result, result)
        ep = self.f.scope() / 'events' / '0000000002.json'
        event = json.loads(ep.read_bytes())
        event['payload'].update(result=ref(self.last_result), input_closure=final_ref)
        self.f.write(ep, event)
        self.reject_replay('E_POLICY_SOURCE')

    def test_deleted_older_published_result_uses_frozen_capture(self):
        self.start(); self.finish(); old_result = self.last_result
        self.next_build(2, 2)
        old_result.unlink()
        self.finish()
        self.assertEqual(self.replay()['terminal_state'], 'CONVERGED')

    def test_missing_required_checker_leaf_is_not_a_skip(self):
        self.start(); finding = _CanonicalPolicyFixture.finding()
        self.finish(findings=[finding]); self.next_build(2, 2)
        result = self.finish(findings=[finding])
        drift = json.loads(Path(result['inputs']['drift_index']['path']).read_bytes())
        (self.f.scope() / 'blobs' / (drift['native_record']['sha256'] + '.blob')).unlink()
        self.reject_replay('E_POLICY_SOURCE')

    def test_partial_off_topic_checker_cannot_publish_success(self):
        self.start(); finding = _CanonicalPolicyFixture.finding()
        self.finish(findings=[finding]); self.next_build(2, 2)
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.finish(findings=[finding], classes=['off_topic'])
        self.assertEqual(caught.exception.error_code, 'E_POLICY_SOURCE')
        self.assertFalse((self.f.run_dir / 'result.json').exists())
        self.assertEqual(len(list((self.f.scope() / 'events').iterdir())), 3)

    def test_result_input_refs_resolve_from_original_result_carrier(self):
        self.start(); result = self.finish()
        for reference in result['inputs'].values():
            if reference is not None:
                reference['path'] = os.path.relpath(reference['path'], self.last_result.parent)
        self.f.write(self.last_result, result)
        ep = self.f.scope() / 'events' / '0000000002.json'
        event = json.loads(ep.read_bytes()); event['payload']['result'] = ref(self.last_result)
        self.f.write(ep, event)
        self.assertEqual(self.replay()['charged_rounds'], 1)


class CarrierReplayTests(unittest.TestCase):
    """All alternate wrappers are written before hashing/freezing/commit.

    Real files and full capture packages distinguish carrier errors from missing
    leaves; no frozen receipt or published result is rewritten by this factory.
    """
    def chain(self, options, checker=True):
        h = HistoricalReplayTests()
        h.setUp()
        self.addCleanup(h.doCleanups)
        h.start()
        finding = _CanonicalPolicyFixture.finding()
        if checker:
            h.finish(findings=[finding])
            h.next_build(2, 2)
        result = h.finish(findings=[finding], classes=['adjacent'], carriers=options)
        return h, result

    @staticmethod
    def files(h):
        return {p: p.read_bytes() for root in (h.f.repo, h.f.plugin)
                for p in root.rglob('*') if p.is_file()}

    def accepts(self, options, checker=True):
        h, result = self.chain(options, checker)
        before = self.files(h)
        replay = h.replay()
        row = replay['rounds'][-1]
        for field in ('conclusions', 'comparison_keys', 'population_comparable', 'incomplete',
                      'converged', 'verdict'):
            self.assertEqual(row[field], result[field], field)
        self.assertEqual(row['policy'], {k: v for k, v in result['policy'].items() if k != 'sources'})
        self.assertEqual(before, self.files(h), 'read-only replay must preserve original bytes')
        self.assertEqual(replay['charged_rounds'], 2 if checker else 1)
        event_count = len(h.state()['events'])
        h.next_build(3 if checker else 2, 3 if checker else 2)
        self.assertEqual(len(h.state()['events']), event_count + 1)
        self.assertTrue((h.f.run_dir / 'workflow.js').is_file())

    def rejects(self, options, reason, checker=True, code='E_POLICY_SOURCE'):
        h, _ = self.chain(options, checker)
        before = self.files(h)
        with self.assertRaises(h.mod.ExecutorError) as caught:
            h.replay()
        self.assertEqual((caught.exception.error_code, caught.exception.reason), (code, reason))
        self.assertEqual(before, self.files(h))
        event_count = len(h.state()['events'])
        with self.assertRaises(h.mod.ExecutorError) as caught:
            h.next_build(3 if checker else 2, 3 if checker else 2)
        self.assertEqual((caught.exception.error_code, caught.exception.reason), (code, reason))
        self.assertEqual(len(h.state()['events']), event_count)
        self.assertFalse((h.f.run_dir / 'workflow.js').exists())
        # next_build legitimately writes its caller manifest, never ledger/old output.
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw, str(path))

    def test_absolute_chain_baseline(self):
        self.accepts({})

    def test_each_prepare_file_ref_uses_nested_original_carrier(self):
        for field in ('audit_index', 'policy_request', 'input_closure', 'policy_script'):
            with self.subTest(field=field):
                self.accepts({'prepare': [field]})

    def test_all_prepare_file_refs_and_nullable_script(self):
        fields = ['audit_index', 'policy_request', 'input_closure', 'policy_script']
        self.accepts({'prepare': fields})
        self.accepts({'prepare': fields}, checker=False)

    def test_each_request_file_ref_uses_its_own_nested_carrier(self):
        for field in ('genesis', 'anchor', 'audit_index', 'input_closure'):
            with self.subTest(field=field):
                self.accepts({'request': [field]})

    def test_request_and_prepare_use_distinct_original_carriers(self):
        self.accepts({'prepare': ['audit_index', 'policy_request', 'input_closure', 'policy_script'],
                      'request': ['genesis', 'anchor', 'audit_index', 'input_closure']})

    def test_wrong_prepare_origin_rejected_despite_identical_bytes_and_hash(self):
        for field, reason in [('audit_index', 'prepare_binding'), ('policy_request', 'prepare_binding'),
                              ('input_closure', 'request_not_recomputed')]:
            with self.subTest(field=field):
                self.rejects({'bad_prepare': field}, reason)

    def test_wrong_request_origin_rejected_despite_identical_bytes_and_hash(self):
        for field in ('genesis', 'anchor', 'audit_index', 'input_closure'):
            with self.subTest(field=field):
                self.rejects({'bad_request': field}, 'request_not_recomputed', checker=False)

    def test_wrong_script_content_rejected_with_real_matching_file_hash(self):
        self.rejects({'bad_prepare': 'policy_script'}, 'checker_script_not_generated',
                     code='E_RUN_IDENTITY')

    def test_same_script_content_at_other_origin_is_not_a_path_identity_gate(self):
        self.accepts({'script_copy': True, 'prepare': ['policy_script']})


class ResultIntegrityTests(unittest.TestCase):
    """Only synthetic captures; production build/prepare/final/check, no Workflow.

    Negative targets: self-reported derived fields, live raw upgrades, unchecked
    checker keys, overwrite recovery, omitted commits, and checker write effects.
    """
    def setUp(self):
        self.f = BuildContractTests('test_missing_project_and_missing_key_remain_false_without_team_or_evidence')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.mod = self.f.mod
        self.f.build()
        self.previous = None
        self.capture()

    def output(self):
        return self.f.run_dir / (self.f.run_dir.name + '.json')

    def capture(self, findings=None, late=False):
        f = self.f
        build = f.record()
        self.native_path = f.run_dir / 'native.json'
        self.run_id = 'synthetic-' + f.manifest['client_round_id']
        nodes, seats = [], []
        for i, role in enumerate(build['roles']):
            report = {'vote': 'REVISE' if findings else 'PASS', 'coverage_complete': True,
                      'findings': findings or [], 'pending': [], 'prior_findings': []}
            nodes.append({'type': 'workflow_agent', 'agentId': self.run_id + '-' + str(i),
                'agentType': role['agentType'], 'label': role['label'], 'model': 'synthetic',
                'queuedAt': 1000+i*100, 'startedAt': 1000+i*100,
                'durationMs': 120001 if late and i == 0 else 10, 'state': 'done'})
            seats.append({**{k: role[k] for k in ('index', 'role_id', 'agentType', 'label')},
                'attempted': True, 'settled': True, 'raw': encode(report).decode(), 'error': None})
        native = {'runId': self.run_id, 'startTime': 1000, 'durationMs': 300020,
            'status': 'completed', 'agentCount': 3, 'script': (f.run_dir/'workflow.js').read_text(),
            'args': {'identity': build['identity'], 'manifest_sha256': build['manifest']['sha256']},
            'workflowProgress': nodes, 'result': {'schema_version': 1, 'identity': build['identity'],
                'manifest_sha256': build['manifest']['sha256'], 'results': seats,
                'control': {'round_timer_ms': 300000, 'stop_observed': False, 'return_reason': 'all_settled'}}}
        f.write(self.native_path, native)
        f.write(f.run_dir/'audit-index.json', {'schema_version': 1, 'identity': build['identity'],
            'attempt_index': build['attempt_index'], 'workflow_run_id': self.run_id,
            'native_record': ref(self.native_path), 'termination_refs': []})

    def cli(self, *extra):
        args = [sys.executable, '-I', str(self.f.engine/'scripts'/'audit_executor.py'), 'collect',
            '--repo-path', str(self.f.repo), '--manifest', str(self.f.manifest_path),
            '--build-record', str(self.f.run_dir/'build-record.json'), '--workflow-run-id', self.run_id,
            '--native-record', str(self.native_path), '--output', str(self.output())]
        if self.previous is not None:
            args += ['--previous-round', str(self.previous)]
        return subprocess.run([*args, *extra], capture_output=True, cwd=self.f.root)

    def ok(self, response):
        self.assertEqual(response.returncode, 0, response.stderr.decode())
        return json.loads(response.stdout)

    def final(self):
        return self.ok(self.cli())

    def prepare(self):
        return self.ok(self.cli('--prepare-policy'))

    def check(self):
        return self.cli('--check-result', str(self.output()))

    def snapshot(self):
        return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.f.root.rglob('*') if p.is_file()}

    def next_round(self, findings=None):
        self.previous = self.output()
        f = self.f
        f.run_dir = f.repo/'.aria'/'audit-reports'/'post_spec-R2-client-two-build-target-aggregated'
        f.manifest_path = f.repo/'manifest-two.json'
        f.manifest.update(round=2, attempt_index=2, client_round_id='client-two')
        f.manifest['evidence'].update(cycle_origin=ref(f.scope()/'genesis.json'), previous_round=ref(self.previous),
            post_audit_index_path=str(f.run_dir/'audit-index.json'),
            post_drift_index_path=str(f.run_dir/'drift-index.json'),
            post_disposition_index_path=str(f.run_dir/'disposition-index.json'))
        f.build()
        self.capture(findings=findings)

    def checker(self, prepared, classifications=None, timeout=False):
        request_path = Path(prepared['policy_request']['path'])
        request = json.loads(request_path.read_bytes())
        self.assertTrue(request['required'])
        anchor = json.loads(Path(request['anchor']['path']).read_bytes())['value']
        keys = [[c[k] for k in ('type', 'severity', 'category', 'scope')] for c in request['conclusions']]
        rows = classifications if classifications is not None else [{'key': k, 'classification': 'on_topic'} for k in keys]
        ident, checker = request['identity'], request['checker']
        native = {'runId': 'synthetic-independent-checker', 'startTime': 400000, 'durationMs': 60001,
            'status': 'completed', 'agentCount': 1, 'script': Path(prepared['policy_script']['path']).read_text(),
            'args': {'identity': ident, 'request_sha256': ref(request_path)['sha256'], 'anchor': anchor,
                     'conclusions': request['conclusions']},
            'workflowProgress': [{'type': 'workflow_agent', 'agentId': 'synthetic-checker-agent',
                'agentType': checker['agentType'], 'label': checker['label'], 'model': 'synthetic',
                'queuedAt': 400000, 'startedAt': 400000, 'durationMs': 10, 'state': 'done'}],
            'result': {'schema_version': 1, 'identity': ident, 'request_sha256': ref(request_path)['sha256'],
                'agentType': checker['agentType'], 'label': checker['label'], 'call_attempted': True,
                'settled': not timeout, 'raw': None if timeout else encode({'classifications': rows}).decode(),
                'error': None, 'control': {'timeout_ms': 60000, 'stop_observed': timeout,
                    'return_reason': 'control_timeout' if timeout else 'all_settled'}}}
        path = self.f.run_dir/'checker-native.json'
        self.f.write(path, native)
        self.f.write(self.f.run_dir/'drift-index.json', {'schema_version': 1, 'identity': ident,
            'attempt_index': self.f.manifest['attempt_index'], 'request': ref(request_path), 'kind': 'workflow',
            'workflow_run_id': native['runId'], 'native_record': ref(path), 'termination_refs': [], 'tool_failure': None})

    def test_final_then_readonly_check_complete_two_round_chain(self):
        self.prepare()
        self.final()
        first = json.loads(self.output().read_bytes())
        self.assertFalse(first['converged'])
        self.next_round()
        self.prepare()
        self.final()
        result = json.loads(self.output().read_bytes())
        self.assertTrue(result['converged'])
        self.assertEqual(result['policy']['charged_rounds'], 2)
        before = self.snapshot()
        self.ok(self.check())
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(list((self.f.scope()/'events').glob('*.json'))), 4)
        md = self.output().with_suffix('.md').read_text()
        self.assertIn('checkpoint: post_spec', md)
        self.assertIn('verdict: ' + result['verdict'], md)

    def test_publication_closed_schema_and_attempt_type_reject_before_any_write(self):
        for mutation in ('unknown_field', 'boolean_attempt'):
            with self.subTest(mutation=mutation):
                case = ResultIntegrityTests(self._testMethodName)
                case.setUp()
                try:
                    case.prepare()
                    publication = {'schema_version': 1, 'identity': case.f.record()['identity'],
                        'attempt_index': 1, 'generated_at': 'synthetic-publication',
                        'host_collect_duration_ms': 3}
                    if mutation == 'unknown_field':
                        publication['unexpected_untrusted_field'] = True
                    else:
                        publication['attempt_index'] = True
                    case.f.write(case.f.run_dir / 'publication-record.json', publication)
                    before = case.snapshot()
                    result = case.cli()
                    self.assertNotEqual(result.returncode, 0, 'invalid publication metadata was committed')
                    error = json.loads(result.stderr)
                    self.assertEqual(error['error_code'], 'E_POLICY_SOURCE')
                    self.assertEqual(case.snapshot(), before)
                    self.assertFalse(case.output().exists())
                    self.assertEqual(len(list((case.f.scope() / 'events').glob('*.json'))), 1)
                finally:
                    case.doCleanups()

    def test_prepare_boolean_attempt_rejects_before_final_publication(self):
        self.prepare()
        path = self.f.run_dir / 'prepare-record.json'
        prepared = json.loads(path.read_bytes())
        prepared['attempt_index'] = True
        self.f.write(path, prepared)
        before = self.snapshot()
        result = self.cli()
        self.assertNotEqual(result.returncode, 0, 'boolean prepare attempt was committed as integer 1')
        self.assertEqual(json.loads(result.stderr)['error_code'], 'E_POLICY_SOURCE')
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.output().exists())

    def test_valid_publication_metadata_recovery_remains_replayable(self):
        self.prepare()
        path = self.f.run_dir / 'publication-record.json'
        publication = {'schema_version': 1, 'identity': self.f.record()['identity'],
            'attempt_index': 1, 'generated_at': 'synthetic-publication', 'host_collect_duration_ms': 3}
        self.f.write(path, publication)
        expected = path.read_bytes()
        self.final()
        self.assertEqual(path.read_bytes(), expected)
        before = self.snapshot()
        self.ok(self.check())
        self.assertEqual(self.snapshot(), before)
        self.next_round()
        self.assertTrue((self.f.run_dir / 'build-record.json').exists())
        self.assertEqual(self.f.manifest['round'], 2)

    def test_cli_markdown_preserves_legacy_schema_from_verified_sources(self):
        required = {'checkpoint', 'mode', 'rounds', 'converged', 'oscillation',
            'overridden_by_user', 'degraded', 'drift_terminated', 'drift_check_skipped',
            'is_refocus', 'verdict', 'timestamp', 'context', 'agents'}
        for number in (1, 2):
            if number == 2:
                self.next_round()
            self.capture(late=True)
            self.prepare(); self.final()
            result = json.loads(self.output().read_bytes())
            markdown = self.output().with_suffix('.md').read_text()
            lines = markdown.split('\n')
            self.assertEqual(lines[0], '---')
            end = lines.index('---', 1)
            front = dict(line.split(': ', 1) for line in lines[1:end])
            self.assertTrue(required <= front.keys(), 'legacy frontmatter fields missing: ' +
                            ','.join(sorted(required - front.keys())))
            self.assertNotIn('round', front, 'canonical legacy field is rounds, not round')
            parsed = {}
            for key, value in front.items():
                try:
                    parsed[key] = json.loads(value)
                except ValueError:
                    parsed[key] = value
            policy = result['policy']
            expected = {'checkpoint': result['identity']['checkpoint'],
                'mode': self.f.record()['effective_config']['resolved_mode']['value'],
                'rounds': number, 'converged': number == 2,
                'oscillation': policy['terminal_state'] == 'OSCILLATION',
                'overridden_by_user': policy['overridden_by_user'], 'degraded': policy['degraded'],
                'drift_terminated': policy['terminal_state'] == 'DRIFT_TERMINATED',
                'drift_check_skipped': policy['drift_check_skipped'], 'is_refocus': policy['is_refocus'],
                'verdict': result['verdict'], 'timestamp': result['generated_at'],
                'context': str(self.f.context), 'agents': result['configured_roles']}
            self.assertEqual({key: parsed[key] for key in required}, expected)
            self.assertEqual(parsed['converged'], result['converged'])
            self.assertEqual(len(parsed['agents']), 3)
            self.assertEqual(len(result['admitted_roles']), 2)
            before = self.snapshot(); self.ok(self.check()); self.assertEqual(self.snapshot(), before)

    def test_every_derived_result_domain_rejects_tamper_without_writes(self):
        self.prepare(); self.final()
        original = json.loads(self.output().read_bytes())
        mutations = [('run', lambda x: x.update(workflow_run_id='wrong')),
            ('script', lambda x: x.update(workflow_script_sha256='0'*64)),
            ('input', lambda x: x['inputs']['native_record'].update(sha256='0'*64)),
            ('identity', lambda x: x['identity'].update(round=9)),
            ('keys', lambda x: x['comparison_keys'].append(['bug','major','implementation','fake'])),
            ('conclusions', lambda x: x['conclusions'].append({'fake': True})),
            ('policy', lambda x: x['policy'].update(charged_rounds=99))]
        for key in ['configured_roles','dispatched_roles','admitted_roles']:
            mutations.append((key, lambda x, k=key: x[k].pop()))
        for key in ['conclusion_keys_equal','population_comparable','incomplete','all_failed_void',
                    'unanimous_pass','conclusions_stable','converged','next_round_dispatch_allowed']:
            mutations.append((key, lambda x, k=key: x.update({k: not x[k]})))
        for i in range(3):
            for key in ['execution_state', 'queued_at_ms', 'started_at_ms', 'duration_ms', 'completed_at_ms', 'native_deadline_ms']:
                mutations.append((f'role-{i}-{key}', lambda x, i=i, k=key: x['roles'][i].update({k: 'tampered'})))
        for key in ['anchor_scope_empty','drift_classification_confidence']:
            mutations.append((key, lambda x, k=key: x['policy'].update({k: 'tampered'})))
        for name, mutate in mutations:
            with self.subTest(domain=name):
                value = copy.deepcopy(original); mutate(value); self.f.write(self.output(), value)
                before = self.snapshot(); response = self.check()
                self.assertNotEqual(response.returncode, 0)
                self.assertEqual(json.loads(response.stderr)['error_code'], 'E_RESULT_MISMATCH')
                self.assertEqual(self.snapshot(), before)
        self.f.write(self.output(), original)

    def readonly_check(self):
        """Run the actual CLI with filesystem writes forbidden, including locks."""
        guard = '''import runpy,sys,os
script=sys.argv.pop(1)
def audit(event,args):
    if event=='open':
        mode,flags=args[1:3]
        if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)):
            raise AssertionError('check attempted write: '+str(args[0]))
    if event in {'os.mkdir','os.remove','os.rmdir','os.rename','os.link','os.symlink','os.chmod','os.utime','fcntl.flock'}:
        raise AssertionError('check attempted mutation: '+event)
sys.addaudithook(audit)
runpy.run_path(script,run_name='__main__')
'''
        args = [sys.executable, '-I', '-c', guard, str(self.f.engine/'scripts'/'audit_executor.py'),
            'collect', '--repo-path', str(self.f.repo), '--manifest', str(self.f.manifest_path),
            '--build-record', str(self.f.run_dir/'build-record.json'), '--workflow-run-id', self.run_id,
            '--native-record', str(self.native_path), '--output', str(self.output()),
            '--check-result', str(self.output())]
        if self.previous is not None:
            args += ['--previous-round', str(self.previous)]
        before = {str(p): (p.read_bytes() if p.is_file() else None, p.stat().st_mtime_ns)
                  for p in [self.f.root, *self.f.root.rglob('*')]}
        response = subprocess.run(args, capture_output=True, cwd=self.f.root)
        after = {str(p): (p.read_bytes() if p.is_file() else None, p.stat().st_mtime_ns)
                 for p in [self.f.root, *self.f.root.rglob('*')]}
        self.assertEqual(before, after, 'check mutated a file or directory')
        return response

    def assert_file_refs(self, value):
        if isinstance(value, dict):
            if set(value) == {'path', 'sha256'}:
                self.assertEqual(value, ref(Path(value['path'])), 'returned FileRef does not name its actual bytes')
            else:
                for item in value.values():
                    self.assert_file_refs(item)
        elif isinstance(value, list):
            for item in value:
                self.assert_file_refs(item)

    def display_successor(self, previous_ref, previous_path):
        f = self.f
        self.previous = previous_path
        f.run_dir = f.repo/'.aria'/'audit-reports'/'post_spec-R2-client-two-build-target-aggregated'
        f.manifest_path = f.repo/'manifest-two.json'
        f.manifest.update(round=2, attempt_index=2, client_round_id='client-two')
        f.manifest['evidence'].update(cycle_origin=ref(f.scope()/'genesis.json'), previous_round=previous_ref,
            post_audit_index_path=str(f.run_dir/'audit-index.json'),
            post_drift_index_path=str(f.run_dir/'drift-index.json'),
            post_disposition_index_path=str(f.run_dir/'disposition-index.json'))
        f.write(f.manifest_path, f.manifest)
        response = subprocess.run([sys.executable, '-I', str(f.engine/'scripts'/'audit_executor.py'),
            'build', '--repo-path', str(f.repo), '--manifest', str(f.manifest_path),
            '--output-dir', str(f.run_dir)], capture_output=True, cwd=f.root)
        self.ok(response)
        resumed = subprocess.run([sys.executable, '-I', str(f.engine/'scripts'/'audit_executor.py'),
            'build', '--repo-path', str(f.repo), '--manifest', str(f.manifest_path),
            '--output-dir', str(f.run_dir)], capture_output=True, cwd=f.root)
        self.assertTrue(self.ok(resumed)['resume_only'])
        self.capture(); self.prepare(); result = self.final()
        self.assert_file_refs(result)
        self.assert_file_refs(self.ok(self.readonly_check()))
        current = json.loads(self.output().read_bytes())
        self.assertEqual((current['identity']['audit_cycle_id'], current['policy']['charged_rounds'],
                          current['policy']['effective_limit']), ('cycle-one', 2, 5))
        self.assertTrue(current['converged'])

    def test_unmodified_public_result_requires_valid_existing_history_blob(self):
        self.prepare(); published = self.final()
        self.assert_file_refs(self.ok(self.readonly_check()))
        blob = self.f.scope() / 'blobs' / (published['result']['sha256'] + '.blob')
        original = blob.read_bytes()
        self.assertEqual(original, self.output().read_bytes())
        blob.write_bytes(b'corrupt committed result')
        before = self.snapshot()
        failed = self.readonly_check()
        self.assertNotEqual(failed.returncode, 0, 'check ignored the corrupted history-preferred result blob')
        self.assertEqual(json.loads(failed.stderr)['error_code'], 'E_POLICY_SOURCE')
        self.assertEqual(self.snapshot(), before)
        next_run = self.f.repo / '.aria' / 'audit-reports' / 'post_spec-R2-client-two-build-target-aggregated'
        next_manifest = copy.deepcopy(self.f.manifest)
        next_manifest.update(round=2, attempt_index=2, client_round_id='client-two')
        next_manifest['evidence'].update(cycle_origin=ref(self.f.scope() / 'genesis.json'),
            previous_round=ref(self.output()), post_audit_index_path=str(next_run / 'audit-index.json'),
            post_drift_index_path=str(next_run / 'drift-index.json'),
            post_disposition_index_path=str(next_run / 'disposition-index.json'))
        path = self.f.repo / 'manifest-two.json'
        self.f.write(path, next_manifest)
        args = [sys.executable, '-I', str(self.f.engine / 'scripts' / 'audit_executor.py'),
                'build', '--repo-path', str(self.f.repo), '--manifest', str(path), '--output-dir', str(next_run)]
        before = self.snapshot()
        failed_build = subprocess.run(args, capture_output=True, cwd=self.f.root)
        self.assertNotEqual(failed_build.returncode, 0)
        self.assertEqual(json.loads(failed_build.stderr)['error_code'], 'E_POLICY_SOURCE')
        self.assertEqual(self.snapshot(), before)
        blob.write_bytes(original)
        before = self.snapshot()
        self.assert_file_refs(self.ok(self.readonly_check()))
        self.assertEqual(self.snapshot(), before)
        self.ok(subprocess.run(args, capture_output=True, cwd=self.f.root))
        self.assertTrue((next_run / 'build-record.json').exists())

    def test_unmodified_public_result_without_blob_keeps_readonly_compatibility(self):
        self.prepare(); published = self.final()
        blob = self.f.scope() / 'blobs' / (published['result']['sha256'] + '.blob')
        blob.unlink()
        before = self.snapshot()
        self.assert_file_refs(self.ok(self.readonly_check()))
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(blob.exists(), 'read-only check must not recreate the missing compatibility blob')
        self.next_round()
        self.assertTrue((self.f.run_dir / 'build-record.json').exists())

    def test_display_generated_at_is_not_an_integrity_domain(self):
        self.prepare(); first = self.final(); self.assert_file_refs(first)
        self.assert_file_refs(self.ok(self.readonly_check()))
        original = json.loads(self.output().read_bytes())
        value = copy.deepcopy(original); value['generated_at'] = 'display-only'
        self.f.write(self.output(), value)
        checked = self.ok(self.readonly_check())
        self.assert_file_refs(checked)
        self.assertEqual({k: v for k, v in value.items() if k != 'generated_at'},
                         {k: v for k, v in original.items() if k != 'generated_at'})
        public = self.output(); public_bytes = public.read_bytes()
        self.display_successor(checked['result'], public)
        self.assertEqual(public.read_bytes(), public_bytes)

    def test_display_current_public_ref_and_frozen_previous_argument_continue(self):
        self.prepare(); published = self.final(); public = self.output()
        value = json.loads(public.read_bytes()); value['generated_at'] = 'different-display'
        self.f.write(public, value)
        checked = self.ok(self.readonly_check())
        # The new manifest may retain the existing public carrier; the explicit
        # previous argument may instead use check's immutable result carrier.
        self.display_successor(ref(public), Path(checked['result']['path']))
        self.assertEqual(published['commit'], ref(self.f.scope()/'events'/'0000000002.json'))

    def test_display_does_not_hide_non_display_tamper_from_successor(self):
        self.prepare(); self.assert_file_refs(self.final())
        value = json.loads(self.output().read_bytes())
        value.update(generated_at='display-only', converged=True)
        self.f.write(self.output(), value)
        before = self.snapshot(); response = self.readonly_check()
        self.assertEqual(json.loads(response.stderr)['error_code'], 'E_RESULT_MISMATCH')
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.next_round()
        self.assertIn(caught.exception.error_code, ('E_POLICY_SOURCE', 'E_PREVIOUS_IDENTITY', 'E_RESULT_MISMATCH'))
        self.assertFalse((self.f.run_dir/'workflow.js').exists())

    def test_display_previous_wrong_origin_hash_and_semantic_copy_are_not_aliases(self):
        self.prepare(); self.final(); public = self.output()
        value = json.loads(public.read_bytes()); value['generated_at'] = 'display-only'
        self.f.write(public, value)
        checked = self.ok(self.readonly_check())
        copy_path = self.f.repo/'not-the-result.json'; copy_path.write_bytes(public.read_bytes())
        candidates = [ref(copy_path), {**checked['result'], 'sha256': '0'*64}]
        for candidate in candidates:
            with self.subTest(reference=candidate):
                f = self.f
                f.run_dir = f.repo/'.aria'/'audit-reports'/'post_spec-R2-client-two-build-target-aggregated'
                f.manifest_path = f.repo/'manifest-two.json'
                f.manifest.update(round=2, attempt_index=2, client_round_id='client-two')
                f.manifest['evidence'].update(cycle_origin=ref(f.scope()/'genesis.json'), previous_round=candidate,
                    post_audit_index_path=str(f.run_dir/'audit-index.json'),
                    post_drift_index_path=str(f.run_dir/'drift-index.json'),
                    post_disposition_index_path=str(f.run_dir/'disposition-index.json'))
                f.write(f.manifest_path, f.manifest)
                before = self.snapshot()
                response = subprocess.run([sys.executable, '-I', str(f.engine/'scripts'/'audit_executor.py'),
                    'build', '--repo-path', str(f.repo), '--manifest', str(f.manifest_path),
                    '--output-dir', str(f.run_dir)], capture_output=True, cwd=f.root)
                self.assertNotEqual(response.returncode, 0, 'unbound previous result was accepted')
                self.assertEqual(json.loads(response.stderr)['error_code'], 'E_PREVIOUS_IDENTITY')
                self.assertEqual(self.snapshot(), before)
                self.assertFalse((f.run_dir/'workflow.js').exists())

    def test_display_write_recovery_does_not_overwrite_or_resample_clock(self):
        self.prepare(); self.final()
        value = json.loads(self.output().read_bytes()); value['generated_at'] = 'display-only'
        self.f.write(self.output(), value)
        before = self.snapshot(); self.assert_file_refs(self.final())
        self.assertEqual(self.snapshot(), before)

    def test_half_publications_resume_exactly_without_new_clocks(self):
        self.prepare(); self.final()
        paths = [self.output(), self.output().with_suffix('.md'), self.f.scope()/'events'/'0000000002.json']
        saved = {p: p.read_bytes() for p in paths}
        for missing in [(0,), (1,), (2,), (0,1), (0,2), (1,2), (0,1,2)]:
            with self.subTest(missing=missing):
                for i in missing: paths[i].unlink()
                self.final()
                self.assertEqual({p: p.read_bytes() for p in paths}, saved)
                before = self.snapshot(); self.final(); self.assertEqual(self.snapshot(), before)

    def test_conflicting_json_markdown_commit_never_overwrites(self):
        self.prepare(); self.final()
        paths = [self.output(), self.output().with_suffix('.md'), self.f.scope()/'events'/'0000000002.json']
        for path in paths:
            old = path.read_bytes(); path.write_bytes(b'conflicting bytes')
            before = self.snapshot(); response = self.cli()
            self.assertNotEqual(response.returncode, 0)
            self.assertEqual(self.snapshot(), before)
            path.write_bytes(old)

    def test_check_requires_both_files_and_commit_and_never_repairs(self):
        self.prepare(); self.final()
        for path in [self.output(), self.output().with_suffix('.md'), self.f.scope()/'events'/'0000000002.json']:
            if not path.exists(): continue
            raw = path.read_bytes(); path.unlink(); before = self.snapshot()
            self.assertNotEqual(self.check().returncode, 0)
            self.assertEqual(self.snapshot(), before); path.write_bytes(raw)

    def test_required_checker_missing_or_invalid_never_publishes(self):
        self.prepare(); self.final()
        finding = {'type': 'issue', 'severity': 'major', 'category': 'implementation',
                   'scope': 'required-key', 'file': 'synthetic.py', 'line': 1,
                   'failure_scenario': 'synthetic finding'}
        self.next_round(findings=[finding]); prepared = self.prepare()
        self.assertFalse(self.output().exists())
        self.assertNotEqual(self.cli().returncode, 0)
        self.assertFalse(self.output().exists())
        request = json.loads(Path(prepared['policy_request']['path']).read_bytes())
        key = [request['conclusions'][0][k] for k in ('type', 'severity', 'category', 'scope')]
        bad = [[], [{'key': key, 'classification': 'off_topic'}],
            [{'key': key, 'classification': 'on_topic'}]*2,
            [{'key': ['bug','major','implementation','extra'], 'classification': 'on_topic'}]]
        for rows in bad:
            with self.subTest(rows=rows):
                self.checker(prepared, rows); before = self.snapshot(); response = self.cli()
                self.assertNotEqual(response.returncode, 0)
                self.assertEqual(json.loads(response.stderr)['error_code'], 'E_POLICY_SOURCE')
                self.assertEqual(self.snapshot(), before)
        self.checker(prepared, timeout=True)
        native_path = self.f.run_dir/'checker-native.json'
        fake = json.loads(native_path.read_bytes())
        fake['result']['control']['stop_observed'] = False
        self.f.write(native_path, fake)
        self.assertNotEqual(self.cli().returncode, 0)
        self.checker(prepared); self.final(); self.ok(self.check())

    def test_sealed_late_raw_cannot_become_a_vote(self):
        self.capture(late=True); self.prepare(); self.final()
        value = json.loads(self.output().read_bytes())
        self.assertEqual(value['roles'][0]['execution_state'], 'completed_late')
        native = json.loads(self.native_path.read_bytes())
        native['workflowProgress'][0]['durationMs'] = 10
        self.f.write(self.native_path, native)
        before = self.snapshot(); self.assertNotEqual(self.check().returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_source_drift_bad_native_and_arguments_are_structured(self):
        self.prepare(); self.final()
        for path in [self.f.config, self.f.defaults, self.f.engine/'scripts'/'audit_executor.py',
                     self.f.engine/'references'/'executor-contract.md',
                     self.f.engine/'references'/'convergence-algorithm.md',
                     self.f.engine/'references'/'report-storage.md']:
            original = path.read_bytes(); path.write_bytes(original+b'\n')
            before = self.snapshot(); response = self.check()
            self.assertEqual(json.loads(response.stderr)['error_code'], 'E_SOURCE_DRIFT')
            self.assertEqual(self.snapshot(), before); path.write_bytes(original)
        raw = self.native_path.read_bytes()
        for mutate in [lambda n: n.update(runId='wrong'), lambda n: n.update(script='wrong')]:
            value = json.loads(raw); mutate(value); self.f.write(self.native_path,value)
            before = self.snapshot(); response = self.check()
            self.assertNotEqual(response.returncode, 0); self.assertEqual(self.snapshot(),before)
        self.native_path.write_bytes(raw)
        response = self.cli('--prepare-policy', '--check-result', str(self.output()))
        self.assertEqual(response.returncode, 2)
        self.assertIn('E_ARGUMENTS', response.stderr.decode())

    def test_final_rejects_missing_seal_without_new_writes(self):
        self.prepare(); self.final()
        (self.f.run_dir/'final-closure.json').unlink()
        before = self.snapshot(); response = self.cli()
        self.assertNotEqual(response.returncode, 0)
        self.assertEqual(self.snapshot(), before)


class HumanDispositionTests(unittest.TestCase):
    """Synthetic AskUserQuestion/tool_result only: never real user permission.

    Negative targets: ignoring late index, trusting wrapper action, replaying +2,
    mutating base policy, accepting aliases/notifications, and future-limit leaks.
    """
    def setUp(self):
        self.start_cycle()

    def start_cycle(self, limit=1, unknown=False):
        self.h = ResultIntegrityTests()
        self.f = BuildContractTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.config_value['audit']['max_rounds'] = limit
        self.f.write(self.f.config, self.f.config_value)
        self.h.f, self.h.mod, self.h.previous = self.f, self.f.mod, None
        self.f.build()
        self.h.capture()
        if unknown:
            native=json.loads(self.h.native_path.read_bytes())
            native['workflowProgress'][-1].update(state='progress')
            native['workflowProgress'][-1].pop('durationMs')
            native['result']['results'][-1].update(settled=False,raw=None)
            native['result']['control'].update(stop_observed=True, return_reason='control_timeout')
            self.f.write(self.h.native_path,native)
            index_path=self.f.run_dir/'audit-index.json'; index=json.loads(index_path.read_bytes())
            index['native_record']=ref(self.h.native_path); self.f.write(index_path,index)
        self.h.prepare(); self.h.final()
        self.base = self.h.output()
        self.base_bytes = self.base.read_bytes()
        self.md_bytes = self.base.with_suffix('.md').read_bytes()
        self.index = self.f.run_dir/'disposition-index.json'
        self.session = self.f.run_dir/'synthetic-session.jsonl'

    def question(self, action='increase_rounds'):
        options = [{'label': label, 'action': act} for label, act in [
            ('接受当前结论', 'accept_current'), ('增加轮次', 'increase_rounds'), ('降级为单轮', 'degrade_single')]]
        context = {k: self.f.manifest[k] for k in ('audit_cycle_id', 'checkpoint', 'change_id')}
        policy=json.loads(self.base.read_bytes())['policy']
        context.update(target_result=ref(self.base), used_rounds=policy['charged_rounds'], effective_limit=policy['effective_limit'])
        question = {'question': '合成处置，不是实际用户授权。\naudit-disposition-context=' + encode(context).decode(),
            'header': '审计处置', 'options': [{'label': o['label'], 'description': '合成测试选项说明'} for o in options],
            'multiSelect': False}
        self.q = {'uuid': 'synthetic-question', 'type': 'assistant', 'message': {'role': 'assistant',
            'content': [{'type': 'tool_use', 'id': 'synthetic-tool-use', 'name': 'AskUserQuestion',
                         'input': {'questions': [question]}}]}}
        self.r = {'uuid': 'synthetic-response', 'type': 'user', 'sourceToolAssistantUUID': self.q['uuid'],
            'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'synthetic-tool-use',
                'content': 'Synthetic tool result, not real consent.'}]},
            'toolUseResult': {'questions': copy.deepcopy([question]),
                'answers': {question['question']: next(o['label'] for o in options if o['action'] == action)}, 'annotations': {}}}
        self.idx = {'schema_version': 1, 'target_result': ref(self.base), 'options': options,
            'question': {'file': {}, 'line': 1, 'event_uuid': self.q['uuid']},
            'response': {'file': {}, 'line': 2, 'event_uuid': self.r['uuid']}}
        self.save_question()

    def save_question(self, suffix=b'\n'):
        self.session.write_bytes(encode(self.q)+b'\n'+encode(self.r)+suffix)
        for name in ('question', 'response'):
            self.idx[name]['file'] = ref(self.session)
        self.f.write(self.index, self.idx)

    def reject(self):
        before = self.h.snapshot()
        response = self.h.cli()
        self.assertNotEqual(response.returncode, 0, 'invalid synthetic disposition accepted')
        self.assertEqual(json.loads(response.stderr)['error_code'], 'E_POLICY_SOURCE', response.stderr.decode())
        self.assertEqual(self.h.snapshot(), before, 'rejected disposition wrote partial evidence')

    def consume(self):
        response = self.h.final()
        self.assertIn('sidecar', response, 'callable collect ignored the disposition index')
        path = Path(response['sidecar']['path'])
        self.assertEqual(path, self.base.with_suffix('.disposition.json'))
        self.assertEqual(self.base.read_bytes(), self.base_bytes)
        self.assertEqual(self.base.with_suffix('.md').read_bytes(), self.md_bytes)
        self.assertFalse(json.loads(self.base.read_bytes())['converged'])
        return json.loads(path.read_bytes())

    def replay(self):
        return self.f.mod._replay_history(self.f.mod._load_scope(self.f.scope(), self.f.manifest, self.f.mod._Inputs()))

    def test_display_question_targets_keep_committed_identity_and_one_shot(self):
        for timing in ('before_question', 'canonical_question', 'after_question', 'after_sidecar'):
            with self.subTest(timing=timing):
                case = HumanDispositionTests()
                case.setUp()
                try:
                    if timing not in ('before_question', 'canonical_question'):
                        case.question()
                    if timing == 'after_sidecar':
                        case.consume()
                    value = json.loads(case.base.read_bytes()); value['generated_at'] = 'display-only'
                    case.f.write(case.base, value)
                    case.base_bytes = case.base.read_bytes()
                    if timing in ('before_question', 'canonical_question'):
                        case.question()
                    if timing == 'canonical_question':
                        target = case.h.ok(case.h.readonly_check())['result']
                        q = case.q['message']['content'][0]['input']['questions'][0]
                        context = json.loads(q['question'].split('audit-disposition-context=')[1])
                        context['target_result'] = target
                        q['question'] = '合成处置。\naudit-disposition-context=' + encode(context).decode()
                        case.r['toolUseResult']['questions'] = copy.deepcopy([q])
                        case.r['toolUseResult']['answers'] = {q['question']: '增加轮次'}
                        case.idx['target_result'] = target
                        case.save_question()
                    side = case.consume()
                    self.assertEqual((side['effective_limit'], side['remaining_rounds']), (3, 2))
                    before = case.h.snapshot()
                    case.h.assert_file_refs(case.h.ok(case.h.readonly_check()))
                    case.consume()
                    self.assertEqual(case.h.snapshot(), before)
                    self.assertEqual(case.replay()['effective_limit'], 3)
                    self.assertEqual(case.replay()['charged_rounds'], 1)
                    self.assertEqual(len(case.replay()['dispositions']), 1)
                    case.h.next_round(); case.h.prepare(); case.h.final()
                    self.assertEqual(json.loads(case.h.output().read_bytes())['policy']['effective_limit'], 3)
                    self.assertEqual(case.base.read_bytes(), case.base_bytes)
                finally:
                    case.doCleanups()

    def test_increase_reopens_real_build_and_future_final_not_old_base(self):
        self.question(); sidecar = self.consume()
        self.assertEqual((sidecar['effective_limit'], sidecar['remaining_rounds']), (3, 2))
        self.assertEqual((self.replay()['effective_limit'], self.replay()['remaining_rounds']), (3, 2))
        before = self.h.snapshot(); self.h.ok(self.h.check()); self.assertEqual(before, self.h.snapshot())
        old_args = (self.f.manifest_path, self.f.run_dir, self.h.native_path, self.h.run_id)
        self.h.next_round(); self.h.prepare(); self.h.final()
        second = json.loads(self.h.output().read_bytes())
        self.assertEqual(second['policy']['effective_limit'], 3)
        self.assertEqual(second['policy']['remaining_rounds'], 1)
        self.assertTrue(second['converged'])
        self.assertEqual(json.loads(self.base.read_bytes())['policy']['effective_limit'], 1)
        self.assertEqual(json.loads(self.base.read_bytes())['policy']['terminal_state'], 'MAX_ROUNDS_EXHAUSTED')
        self.h.ok(self.h.check())
        self.f.manifest_path, self.f.run_dir, self.h.native_path, self.h.run_id = old_args
        self.h.previous = None
        before = self.h.snapshot(); self.h.ok(self.h.check()); self.assertEqual(before, self.h.snapshot())

    def test_identical_repetition_returns_same_sidecar_without_another_two(self):
        self.question(); self.consume()
        before = self.h.snapshot(); self.consume(); self.assertEqual(before, self.h.snapshot())
        self.assertEqual(self.replay()['effective_limit'], 3)
        self.assertEqual(len(list((self.f.scope()/'events').glob('*.json'))), 3)

    def test_accept_current_blocks_new_build_without_changing_base(self):
        self.question('accept_current'); sidecar = self.consume()
        self.assertTrue(sidecar['overridden_by_user']); self.assertFalse(sidecar['degraded'])
        self.assertEqual(sidecar['effective_limit'], 1)
        with self.assertRaises(self.f.mod.ExecutorError) as caught: self.h.next_round()
        self.assertEqual(caught.exception.error_code, 'E_POLICY_BLOCKED')
        self.assertFalse((self.f.run_dir/'workflow.js').exists())

    def test_degrade_single_blocks_new_build_without_changing_base(self):
        self.question('degrade_single'); sidecar = self.consume()
        self.assertTrue(sidecar['degraded']); self.assertFalse(sidecar['overridden_by_user'])
        with self.assertRaises(self.f.mod.ExecutorError) as caught: self.h.next_round()
        self.assertEqual(caught.exception.error_code, 'E_POLICY_BLOCKED')

    def test_context_wrong_cycle_checkpoint_change_head_count_and_limit_reject(self):
        self.question(); orig = copy.deepcopy((self.q, self.r))
        for key, value in [('audit_cycle_id','other'), ('checkpoint','pre_merge'), ('change_id','other'),
                           ('target_result', {'path': str(self.base), 'sha256':'0'*64}), ('used_rounds',2), ('effective_limit',3)]:
            with self.subTest(key=key):
                self.q, self.r = copy.deepcopy(orig)
                q = self.q['message']['content'][0]['input']['questions'][0]
                context = json.loads(q['question'].split('audit-disposition-context=')[1]); context[key] = value
                q['question'] = '合成\naudit-disposition-context='+encode(context).decode()
                self.r['toolUseResult']['questions'] = copy.deepcopy([q])
                self.r['toolUseResult']['answers'] = {q['question']: '增加轮次'}
                self.save_question(); self.reject()

    def test_wrapper_aliases_hash_line_uuid_and_options_reject(self):
        self.question(); original = copy.deepcopy(self.idx)
        mutations = [lambda x: x.update(approved=True), lambda x: x.update(target_result={'path':str(self.base),'sha256':'0'*64}),
            lambda x: x['question'].update(line=2), lambda x: x['response'].update(event_uuid='wrong'),
            lambda x: x['question']['file'].update(sha256='0'*64),
            lambda x: x['options'].reverse(), lambda x: x['options'][1].update(action='add_rounds')]
        for i, mutate in enumerate(mutations):
            with self.subTest(case=i):
                self.idx = copy.deepcopy(original); mutate(self.idx); self.f.write(self.index,self.idx); self.reject()

    def test_native_identity_shape_options_answers_and_notifications_reject(self):
        self.question(); original = copy.deepcopy((self.q,self.r))
        mutations = [lambda q,r: q.update(type='user'), lambda q,r: r.update(type='notification'),
            lambda q,r: r.update(sourceToolAssistantUUID='wrong'),
            lambda q,r: r['message']['content'][0].update(tool_use_id='wrong'),
            lambda q,r: q['message']['content'][0].update(name='OtherTool'),
            lambda q,r: r['message']['content'][0].update(is_error=True),
            lambda q,r: r['toolUseResult'].update(annotations={'note':'增加轮次'}),
            lambda q,r: r['toolUseResult'].update(answers={'wrong':'增加轮次'}),
            lambda q,r: r['toolUseResult']['answers'].update({'extra':'增加轮次'}),
            lambda q,r: r['toolUseResult']['questions'][0].update(multiSelect=True),
            lambda q,r: q['message']['content'][0]['input']['questions'][0]['options'].reverse(),
            lambda q,r: r['toolUseResult'].update(answers={next(iter(r['toolUseResult']['answers'])):'increase_rounds'}),
            lambda q,r: r['message'].update(content=[{'type':'text','text':'增加轮次'}])]
        for i, mutate in enumerate(mutations):
            with self.subTest(case=i):
                self.q,self.r=copy.deepcopy(original); mutate(self.q,self.r); self.save_question(); self.reject()

    def test_missing_duplicate_context_legacy_labels_multiselect_and_truncation_reject(self):
        self.question(); original = copy.deepcopy((self.q,self.r))
        for case in ('missing','duplicate','legacy','multi','truncated','duplicate_uuid'):
            with self.subTest(case=case):
                self.q,self.r=copy.deepcopy(original)
                q=self.q['message']['content'][0]['input']['questions'][0]
                if case=='missing': q['question']='合成但缺少绑定'
                elif case=='duplicate': q['question']+='\n'+q['question'].split('\n')[1]
                elif case=='legacy': q['options'][0]['label']='接受当前结论，继续实现'
                elif case=='multi': q['multiSelect']=True
                self.r['toolUseResult']['questions']=copy.deepcopy([q])
                self.r['toolUseResult']['answers']={q['question']:'增加轮次'}
                self.save_question(suffix=b'' if case=='truncated' else b'\n')
                if case=='duplicate_uuid':
                    self.session.write_bytes(self.session.read_bytes()+encode(self.q)+b'\n')
                    for key in ('question','response'): self.idx[key]['file']=ref(self.session)
                    self.f.write(self.index,self.idx)
                self.reject()

    def test_second_question_for_same_head_cannot_add_twice(self):
        self.question(); self.consume()
        self.q['uuid']='second-question'; self.r['uuid']='second-response'
        self.r['sourceToolAssistantUUID']='second-question'
        self.idx['question']['event_uuid']='second-question'; self.idx['response']['event_uuid']='second-response'
        self.save_question(); self.reject()
        self.assertEqual(self.replay()['effective_limit'],3)

    def test_readonly_uses_frozen_sidecar_not_live_jsonl_and_rejects_corrupt_references(self):
        self.question(); self.consume()
        self.session.write_bytes(b'live growth is not a new frozen answer\n')
        before=self.h.snapshot(); self.h.ok(self.h.check()); self.assertEqual(before,self.h.snapshot())
        sidecar=self.base.with_suffix('.disposition.json'); old=sidecar.read_bytes()
        sidecar.write_bytes(old+b' ')
        before=self.h.snapshot(); response=self.h.check()
        self.assertNotEqual(response.returncode,0)
        self.assertEqual(json.loads(response.stderr)['error_code'],'E_POLICY_SOURCE')
        self.assertEqual(before,self.h.snapshot()); sidecar.write_bytes(old)
        event_path=self.f.scope()/'events'/'0000000003.json'; event=json.loads(event_path.read_bytes())
        self.assertEqual(event['kind'], 'disposition')
        frozen=json.loads(Path(json.loads(old)['input_closure']['path']).read_bytes())
        leaf=next(s for s in frozen['sources'] if s['origin']==str(self.session))
        Path(leaf['blob']['path']).write_bytes(b'corrupt frozen answer')
        before=self.h.snapshot(); response=self.h.check(); self.assertNotEqual(response.returncode,0)
        self.assertEqual(json.loads(response.stderr)['error_code'],'E_POLICY_SOURCE'); self.assertEqual(before,self.h.snapshot())

    def test_absent_index_is_characterization_no_sidecar_or_event(self):
        before=self.h.snapshot(); self.h.final(); self.h.ok(self.h.check()); self.assertEqual(before,self.h.snapshot())
        self.assertFalse(self.base.with_suffix('.disposition.json').exists())


    def test_check_with_existing_sidecar_stays_readonly_during_successor_pending(self):
        self.question(); self.consume()
        args=(self.f.manifest_path,self.f.run_dir,self.h.native_path,self.h.run_id)
        self.h.next_round()
        self.f.manifest_path,self.f.run_dir,self.h.native_path,self.h.run_id=args
        self.h.previous=None
        before=self.h.snapshot(); self.h.ok(self.h.check()); self.assertEqual(before,self.h.snapshot())

    def test_old_unhandled_head_rejects_with_policy_source_not_output_conflict(self):
        self.start_cycle(limit=3)
        args=(self.f.manifest_path,self.f.run_dir,self.h.native_path,self.h.run_id)
        self.h.next_round(); self.h.prepare(); self.h.final()
        self.f.manifest_path,self.f.run_dir,self.h.native_path,self.h.run_id=args
        self.h.previous=None
        self.question(); self.reject()

    def test_nonexhausted_current_head_rejects_characterization(self):
        self.start_cycle(limit=3); self.question(); self.reject()

    def test_unknown_resources_still_block_after_increase_characterization(self):
        self.start_cycle(unknown=True); self.question(); self.consume()
        self.assertFalse(self.replay()['resource_view']['next_round_dispatch_allowed'])
        with self.assertRaises(self.f.mod.ExecutorError) as caught: self.h.next_round()
        self.assertEqual(caught.exception.error_code,'E_RESOURCE_PENDING')
        self.assertFalse((self.f.run_dir/'workflow.js').exists())

    def test_event_file_refs_and_sidecar_policy_reject_corruption_characterization(self):
        self.question(); self.consume()
        path=self.f.scope()/'events'/'0000000003.json'; saved=path.read_bytes()
        for key in ('target_result','evidence','sidecar'):
            with self.subTest(field=key):
                event=json.loads(saved); event['payload'][key]['sha256']='0'*64
                self.f.write(path,event); before=self.h.snapshot(); response=self.h.check()
                self.assertNotEqual(response.returncode,0)
                self.assertEqual(json.loads(response.stderr)['error_code'],'E_POLICY_SOURCE')
                self.assertEqual(before,self.h.snapshot()); path.write_bytes(saved)

    def advance(self, logical, findings):
        self.h.previous=self.h.output()
        f=self.f
        f.run_dir=f.repo/'.aria'/'audit-reports'/f'post_spec-R{logical}-client-{logical}-build-target-aggregated'
        f.manifest_path=f.repo/f'manifest-{logical}.json'
        f.manifest.update(round=logical,attempt_index=logical,client_round_id=f'client-{logical}')
        f.manifest['evidence'].update(cycle_origin=ref(f.scope()/'genesis.json'),previous_round=ref(self.h.previous),
            post_audit_index_path=str(f.run_dir/'audit-index.json'),post_drift_index_path=str(f.run_dir/'drift-index.json'),
            post_disposition_index_path=str(f.run_dir/'disposition-index.json'))
        f.build(); self.h.capture(findings=findings)
        prepared=self.h.prepare(); self.h.checker(prepared)
        native_path=f.run_dir/'checker-native.json'; native=json.loads(native_path.read_bytes())
        native['runId'] += '-' + str(logical); f.write(native_path,native)
        index_path=f.run_dir/'drift-index.json'; index=json.loads(index_path.read_bytes())
        index.update(workflow_run_id=native['runId'],native_record=ref(native_path)); f.write(index_path,index)
        self.h.final()

    def test_token_reuse_across_heads_and_fresh_token_increment_characterization(self):
        self.question(); self.consume()
        finding={'type':'issue','severity':'minor','category':'implementation','scope':'a.py',
                 'file':'a.py','line':1,'failure_scenario':'合成发现'}
        self.advance(2,[finding]); self.advance(3,[{**finding,'scope':'b.py'}])
        self.base=self.h.output(); self.base_bytes=self.base.read_bytes(); self.md_bytes=self.base.with_suffix('.md').read_bytes()
        self.index=self.f.run_dir/'disposition-index.json'; self.session=self.f.run_dir/'synthetic-session.jsonl'
        self.assertEqual(json.loads(self.base_bytes)['policy']['terminal_state'],'MAX_ROUNDS_EXHAUSTED')
        self.question(); self.reject()
        self.q['uuid']='new-question'; self.r['uuid']='new-response'
        self.q['message']['content'][0]['id']='new-tool-use'
        self.r['message']['content'][0]['tool_use_id']='new-tool-use'
        self.r['sourceToolAssistantUUID']='new-question'
        self.idx['question']['event_uuid']='new-question'; self.idx['response']['event_uuid']='new-response'
        self.save_question(); side=self.consume()
        self.assertEqual((side['effective_limit'],side['remaining_rounds']),(5,2))
        self.assertEqual(self.replay()['effective_limit'],5)
        before=self.h.snapshot(); self.h.ok(self.h.check()); self.assertEqual(before,self.h.snapshot())


    def test_repeat_with_same_index_but_changed_session_rejects_characterization(self):
        self.question(); self.consume()
        self.session.write_bytes(self.session.read_bytes()+encode({'uuid':'later-notification','type':'notification'})+b'\n')
        self.reject()
        before=self.h.snapshot(); self.h.ok(self.h.check()); self.assertEqual(before,self.h.snapshot())
        self.assertEqual(self.replay()['effective_limit'],3)

    def test_empty_session_missing_originals_and_orphan_sidecar_reject_characterization(self):
        self.question()
        self.session.write_bytes(b'')
        for name in ('question','response'): self.idx[name]['file']=ref(self.session)
        self.f.write(self.index,self.idx); self.reject()
        self.question(); self.session.unlink(); self.reject()
        self.question(); self.base.with_suffix('.disposition.json').write_bytes(b'{}'); self.reject()

    def test_reference_carriers_relative_paths_characterization(self):
        self.question()
        self.idx['target_result']['path']=self.base.name
        for name in ('question','response'): self.idx[name]['file']['path']=self.session.name
        self.f.write(self.index,self.idx); self.consume()
        before=self.h.snapshot(); self.h.ok(self.h.check()); self.assertEqual(before,self.h.snapshot())


# TASK-013: independent QA vectors. Composition reuses construction, not tests.
QA_NOTES = ENGINE.parents[2] / '.aria/notes/2026-11-02-audit-executor-implementation/TASK-013'
QA_CASES = ENGINE / 'tests/fixtures/audit_executor/compatibility-cases.json'


def qa_fixture(owner, case):
    """Retain complete replayable absolute-path sources, never dangling temp refs."""
    from unittest.mock import patch

    class Workspace:
        def __init__(self, *args, **kwargs):
            root = QA_NOTES / 'runs' / owner.id().split('.')[-1]
            root.mkdir(parents=True, exist_ok=True)
            self.name = tempfile.mkdtemp(prefix='source-', dir=root)

        def cleanup(self):
            pass  # Deliberately retained alongside output and fault snapshots.

    with patch.object(tempfile, 'TemporaryDirectory', Workspace):
        case.setUp()
    owner.addCleanup(case.doCleanups)
    return case


class GeneratedWorkflowRuntimeTests(unittest.TestCase):
    """Actual build JS with independent native/VM clocks and physical promises."""

    def setUp(self):
        self.f = qa_fixture(self, BuildContractTests(
            'test_missing_project_and_missing_key_remain_false_without_team_or_evidence'))
        self.f.build()
        self.mod = self.f.mod

    def runtime(self, steps, modes=None):
        # Installation cost shifts the control timer only. Native T0 stays zero.
        # Date/performance are unavailable; no mtime/subprocess clock enters the VM.
        host = VM_HOST.replace('args:input.args, Date:undefined,',
                               'args:input.args, Date:undefined, performance:undefined,')
        host = host.replace('at:now+ms,fn', 'at:now+ms+(ms===300000?20:0),fn')
        script = (self.f.run_dir / 'workflow.js').read_text()
        args = {'identity': self.f.record()['identity'],
                'manifest_sha256': self.f.record()['manifest']['sha256']}
        payload = {'script': script, 'args': args, 'steps': steps, 'modes': modes or []}
        self.f.write(self.f.root / 'vm-input.json', payload)
        (self.f.root / 'vm-host.js').write_text(host)
        result = subprocess.run(['node', '-e', host], input=encode(payload), capture_output=True, timeout=10)
        (self.f.root / 'vm-stdout.json').write_bytes(result.stdout)
        (self.f.root / 'vm-stderr.txt').write_bytes(result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return json.loads(result.stdout)['trace']

    def test_native_deadline_gap_allows_dispatch_but_rejects_late_vote(self):
        raw = encode({'vote': 'PASS', 'coverage_complete': True,
                      'findings': [], 'pending': [], 'prior_findings': []}).decode()
        trace = self.runtime([
            {'kind': 'advance', 'ms': 120000},
            {'kind': 'advance', 'ms': 180009},
            {'kind': 'resolve', 'index': 0, 'value': raw},
            {'kind': 'advance', 'ms': 11},
            {'kind': 'resolve', 'index': 1, 'value': {'nested': {'value': 'late'}}},
            {'kind': 'resolve', 'index': 2, 'value': raw}])
        self.assertEqual([len(t['calls']) for t in trace[:4]], [2, 2, 2, 3], 'QA_PHYSICAL_SLOT')
        self.assertEqual(trace[3]['calls'][2]['at'], 300009)
        self.assertFalse(trace[3]['returned'])
        self.assertEqual(trace[4]['at'], 300020)
        self.assertTrue(trace[4]['returned'])
        self.assertEqual(trace[-1]['value'], trace[4]['value'], 'QA_STOP_SNAPSHOT')
        self.assertTrue(all(t['maxActive'] == 2 for t in trace), 'QA_PHYSICAL_PENDING_LIMIT')
        role = self.f.record()['roles'][2]
        node = {'type': 'workflow_agent', 'agentId': 'qa-native-gap-agent',
                'agentType': role['agentType'], 'label': role['label'], 'model': None,
                'queuedAt': 300009, 'startedAt': 300009, 'durationMs': 1, 'state': 'done'}
        seat = self.mod._classify_seat(0, node, raw)
        self.assertEqual(seat['execution_state'], 'completed_late', 'QA_NATIVE_REJECTS_GAP_VOTE')
        self.assertTrue(seat['dispatched_at_or_after_native_deadline'])
        self.assertIsNone(seat['report'])
        self.assertEqual(len(trace[-1]['calls']), 3, 'QA_ZERO_DISPATCH_AFTER_STOP')

    def test_pending_never_releases_physical_slot_and_late_reject_cannot_dispatch(self):
        trace = self.runtime([{'kind': 'advance', 'ms': 300020},
            {'kind': 'reject', 'index': 0, 'message': 'QA post-stop rejection'},
            {'kind': 'resolve', 'index': 1, 'value': False}])
        self.assertEqual([len(t['calls']) for t in trace], [2, 2, 2, 2], 'QA_ZERO_DISPATCH_AFTER_STOP')
        self.assertEqual(trace[1]['active'], 2)
        self.assertEqual(trace[-1]['active'], 0)
        self.assertEqual(trace[-1]['value'], trace[1]['value'], 'QA_STOP_SNAPSHOT')
        self.assertEqual([r['attempted'] for r in trace[-1]['value']['results']], [True, True, False])


class WiringContractTests(unittest.TestCase):
    """Separate structural AI instructions from actual offline CLI/fence execution.

    No synthetic consumer is presented as an execution of the Skill's AI prose.
    Actual tool/report consumption and sidecar integration remain TASK-016.
    """

    def setUp(self):
        self.f = qa_fixture(self, BuildContractTests(
            'test_missing_project_and_missing_key_remain_false_without_team_or_evidence'))
        self.doc = (ENGINE / 'references/execution-modes.md').read_text()
        self.skill = (ENGINE / 'SKILL.md').read_text()
        self.capture_script = self.f.root / 'capture.py'
        self.route_script = self.f.root / 'route.py'
        self.capture_script.write_text(self.fence('CAPTURE'))
        self.route_script.write_text(self.fence('ROUTE'))
        self.serial = 0
        self.env = {'PATH': str(Path(sys.executable).parent) + ':' + os.defpath,
            'EXECUTOR': str(self.f.engine / 'scripts/audit_executor.py'), 'REPO': str(self.f.repo),
            'CAPTURE': str(self.capture_script)}
        self.previous = None

    def fence(self, name):
        begin = '# AUDIT_EXECUTOR_' + name + '_V1_BEGIN'
        end = '# AUDIT_EXECUTOR_' + name + '_V1_END'
        self.assertEqual(self.doc.count(begin), 1)
        self.assertEqual(self.doc.count(end), 1)
        return self.doc.split(begin, 1)[1].split(end, 1)[0]

    def route(self):
        return subprocess.run([sys.executable, '-I', str(self.route_script), self.env['EXECUTOR'],
            str(self.f.repo)], capture_output=True, cwd=self.f.root)

    def recipe(self, selector, *, expected=None):
        # Execute the original documentation line, including its actual redirections.
        lines = [l for l in self.doc.splitlines() if l.startswith('python3 -I ') and selector(l)]
        self.assertEqual(len(lines), 1, 'QA_RECIPE_AMBIGUOUS')
        self.serial += 1
        stem = self.f.root / f'command-{self.serial}'
        env = dict(self.env)
        for key in ('BUILD', 'PREPARE', 'FINAL', 'CHECK'):
            env[key + '_RECEIPT'] = str(stem.with_suffix('.stdout'))
            env[key + '_ERROR'] = str(stem.with_suffix('.stderr'))
        previous = ('PREVIOUS_ARGS=(--previous-round "$PREVIOUS_RESULT")' if self.previous else 'PREVIOUS_ARGS=()')
        (stem.with_suffix('.sh')).write_text(previous + '\n' + lines[0] + '\n')
        result = subprocess.run(['bash', '--noprofile', '--norc', '-c', previous + '\n' + lines[0]],
            env=env, capture_output=True, cwd=self.f.root, timeout=20)
        stdout = stem.with_suffix('.stdout')
        stderr = stem.with_suffix('.stderr')
        out = stdout.read_bytes() if stdout.exists() else result.stdout
        err = stderr.read_bytes() if stderr.exists() else result.stderr
        stdout.write_bytes(out); stderr.write_bytes(err)
        if expected:
            self.assertNotEqual(result.returncode, 0, 'QA_CLI_MUST_REJECT')
            self.assertEqual(json.loads(err)['error_code'], expected)
            return None
        self.assertEqual(result.returncode, 0, err.decode())
        return json.loads(out) if out.strip() else None

    def build_round(self):
        self.f.write(self.f.manifest_path, self.f.manifest)
        self.env.update(MANIFEST=str(self.f.manifest_path), RUN_DIR=str(self.f.run_dir))
        receipt = self.recipe(lambda l: ' build ' in l)
        if receipt is None:
            self.fail('QA_BUILD_RECEIPT_REQUIRED')
        self.assertFalse(receipt['resume_only'])
        self.h = ResultIntegrityTests('test_final_then_readonly_check_complete_two_round_chain')
        self.h.f, self.h.mod, self.h.previous = self.f, self.f.mod, self.previous
        self.h.capture(findings=[{'type': 'risk', 'severity': 'minor', 'category': 'testing',
            'scope': ' independent qa-seam scope ', 'summary': '独立QA非空checker路径',
            'file': 'qa-seam.py', 'line': 9, 'failure_scenario': 'isolated synthetic wiring'}])
        self.native = self.h.native_path
        data = json.loads(self.native.read_bytes())
        data['result']['results'][2]['raw'] = None  # Independent partial population.
        self.f.write(self.native, data)
        (self.f.run_dir / 'audit-index.json').unlink()  # The real fence must produce it.
        self.env.update(BUILD_RECORD=str(self.f.run_dir / 'build-record.json'),
            RUN_ID=self.h.run_id, LIVE_NATIVE=str(self.native), TRANSCRIPT_ENTRY=str(self.f.context),
            AUDIT_INDEX=str(self.f.run_dir / 'audit-index.json'), ROUND_RESULT=str(self.h.output()))
        self.recipe(lambda l: '"$CAPTURE" audit ' in l)

    def prepare(self):
        result = self.recipe(lambda l: '--prepare-policy' in l)
        if result is None:
            self.fail('QA_PREPARE_RECEIPT_REQUIRED')
        self.assertFalse(self.h.output().exists(), 'QA_PREPARE_NOT_PUBLICATION')
        self.env['FROZEN_NATIVE'] = result['native_record']['path']
        self.f.write(self.f.root / f'prepare-receipt-{self.serial}.json', result)
        return result

    def independent_checker(self, prepared):
        # Public fixture constructs only the native envelope. Raw data and generated
        # JS execution below are independently supplied and asserted by QA.
        self.h.checker(prepared)
        path = self.f.run_dir / 'checker-native.json'
        native = json.loads(path.read_bytes())
        req = json.loads(Path(prepared['policy_request']['path']).read_bytes())
        raw = {'classifications': [{'key': [c[k] for k in ('type', 'severity', 'category', 'scope')],
                                   'classification': 'adjacent'} for c in req['conclusions']]}
        payload = {'script': Path(prepared['policy_script']['path']).read_text(), 'args': native['args'],
                   'modes': [{'kind': 'resolve', 'value': encode(raw).decode()}], 'steps': []}
        self.f.write(self.f.run_dir / 'checker-vm-input.json', payload)
        run = subprocess.run(['node', '-e', VM_HOST], input=encode(payload), capture_output=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr.decode())
        (self.f.run_dir / 'checker-vm-output.json').write_bytes(run.stdout)
        trace = json.loads(run.stdout)['trace'][-1]
        self.assertEqual(len(trace['calls']), 1)
        self.assertEqual(trace['value']['raw'], encode(raw).decode())
        native['result'] = trace['value']
        self.f.write(path, native)
        (self.f.run_dir / 'drift-index.json').unlink()
        binding = self.f.run_dir / 'prepare-stdout.json'; self.f.write(binding, prepared)
        command = [sys.executable, '-I', str(self.capture_script), 'drift', '--binding', str(binding),
            '--run-id', native['runId'], '--native', str(path), '--transcript-entry', str(self.f.context),
            '--output', str(self.f.run_dir / 'drift-index.json')]
        response = subprocess.run(command, capture_output=True, timeout=10)
        self.assertEqual(response.returncode, 0, response.stderr.decode())

    def final_check(self):
        self.recipe(lambda l: '"$FROZEN_NATIVE"' in l and '--check-result' not in l)
        before = self.h.snapshot()
        receipt = self.recipe(lambda l: '"$FROZEN_NATIVE"' in l and '--check-result' in l)
        if receipt is None:
            self.fail('QA_CHECK_RECEIPT_REQUIRED')
        # Command receipt files are outside the target repo, not publication changes.
        after = self.h.snapshot()
        self.assertEqual({k:v for k,v in before.items() if '/repo/' in k},
                         {k:v for k,v in after.items() if '/repo/' in k}, 'QA_READONLY_CHECK')
        for key in ('result', 'markdown', 'commit'):
            value = receipt[key]
            self.assertEqual(ref(Path(value['path'])), value, 'QA_CHECK_FILEREF_' + key)
        commit = json.loads(Path(receipt['commit']['path']).read_bytes())
        self.assertEqual(commit['kind'], 'commit')
        self.assertEqual(commit['payload']['reservation'], self.f.record()['reservation'])
        return json.loads(Path(receipt['result']['path']).read_bytes())

    def test_real_cli_fences_required_checker_frozen_native_and_commit(self):
        self.assertIs(json.loads(self.route().stdout)['require_same_admitted_roles'], True)
        self.build_round(); p = self.prepare()
        self.assertFalse(json.loads(Path(p['policy_request']['path']).read_bytes())['required'])
        first = self.final_check()
        self.assertFalse(first['all_failed_void'], 'QA_R1_MUST_BE_NONVOID')
        self.assertEqual(first['admitted_roles'],
                         sorted(r['role_id'] for r in self.f.record()['roles'][:2]),
                         'QA_R1_ADMITTED_ROLES')
        self.assertEqual(first['policy']['charged_rounds'], 1, 'QA_R1_MUST_BE_CHARGED')
        self.assertTrue(first['incomplete']); self.assertFalse(first['converged'])
        self.previous = self.h.output()
        self.env['PREVIOUS_RESULT'] = str(self.previous)
        self.f.run_dir = self.f.repo / '.aria/audit-reports/post_spec-R2-qa-wiring-two-build-target-aggregated'
        self.f.manifest_path = self.f.repo / 'qa-round-two.json'
        self.f.manifest.update(round=2, attempt_index=2, client_round_id='qa-wiring-two')
        self.f.manifest['evidence'].update(cycle_origin=ref(self.f.scope() / 'genesis.json'),
            previous_round=ref(self.previous), post_audit_index_path=str(self.f.run_dir / 'audit-index.json'),
            post_drift_index_path=str(self.f.run_dir / 'drift-index.json'),
            post_disposition_index_path=str(self.f.run_dir / 'disposition-index.json'))
        self.build_round(); p = self.prepare()
        self.assertTrue(json.loads(Path(p['policy_request']['path']).read_bytes())['required'])
        self.recipe(lambda l: '"$FROZEN_NATIVE"' in l and '--check-result' not in l, expected='E_POLICY_SOURCE')
        self.independent_checker(p)
        # Real live source grows only after prepare; final/check must retain old bytes.
        self.native.write_bytes(self.native.read_bytes() + b'\n')
        second = self.final_check()
        self.assertTrue(second['incomplete']); self.assertFalse(second['converged'])  # REVISE votes.
        self.assertEqual(second['policy']['charged_rounds'], 2)
        self.assertEqual(second['policy']['drift_ratio'], 0.0)
        self.assertEqual(second['population_reason'], 'same_population')
        self.assertEqual(second['verdict'], 'PASS')
        body = json.loads(self.h.output().read_bytes()); body['converged'] = True
        self.f.write(self.h.output(), body)
        self.recipe(lambda l: '--check-result' in l, expected='E_RESULT_MISMATCH')

    def test_actual_route_false_default_invalid_and_legacy_branch_structure(self):
        self.assertEqual(self.route().returncode, 0)
        for guard in (False, None):
            if guard is None: self.f.config_value['audit'].pop('require_same_admitted_roles', None)
            else: self.f.config_value['audit']['require_same_admitted_roles'] = guard
            self.f.write(self.f.config, self.f.config_value)
            response = self.route()
            self.assertEqual(response.returncode, 0)
            self.assertIs(json.loads(response.stdout)['require_same_admitted_roles'], False)
        self.f.config_value['audit']['require_same_admitted_roles'] = 'false'
        self.f.write(self.f.config, self.f.config_value)
        response = self.route()
        self.assertNotEqual(response.returncode, 0)
        self.assertIn(b'E_CONFIG_TYPE', response.stderr)
        # This is a text contract, NOT evidence of real AI/tool consumption.
        branch = self.skill.split('- **false**', 1)[1].split('- **true**', 1)[0]
        for obligation in ('默认团队', 'agent-team-audit', '不要求 manifest', '不要求旧报告补参与字段'):
            self.assertIn(obligation, branch, 'QA_LEGACY_EXCLUSIVE_BRANCH')
        self.assertIn('完整沿用', branch)
        legacy = self.doc.split('### Legacy 入口 (仅 guard=false)', 1)[1]
        self.assertNotIn('require_same_admitted_roles', legacy)
        self.assertIn('true 在独占配方结束后返回', self.doc)

    def test_missing_prepare_and_resume_only_are_observed_by_real_cli(self):
        self.build_round()
        self.env['FROZEN_NATIVE'] = str(self.native)
        self.recipe(lambda l: '"$FROZEN_NATIVE"' in l and '--check-result' not in l, expected='E_POLICY_SOURCE')
        before = {str(p): p.read_bytes() for p in (self.f.scope() / 'events').glob('*')}
        receipt = self.recipe(lambda l: ' build ' in l)
        if receipt is None:
            self.fail('QA_RESUME_RECEIPT_REQUIRED')
        self.assertTrue(receipt['resume_only'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in (self.f.scope() / 'events').glob('*')})

    @staticmethod
    def instruction_contract(doc):
        section = doc.split('### 受守卫的 Workflow/convergence', 1)[1].split('### Capture adapter', 1)[0]
        commands = [l for l in section.splitlines() if l.startswith('python3 -I ') and ' collect ' in l]
        assert len(commands) == 3, 'QA_WIRING_PREPARE_FINAL_CHECK'
        prepare, final, check = commands
        assert '--prepare-policy' in prepare, 'QA_WIRING_PREPARE_ORDER'
        base = lambda l: l.split(' >', 1)[0].replace(' --check-result "$ROUND_RESULT"', '')
        assert base(final) == base(check), 'QA_WIRING_SAME_INPUTS'
        assert '--check-result "$ROUND_RESULT"' in check, 'QA_WIRING_CHECK_REQUIRED'
        assert '仅 check exit=0 后' in section, 'QA_WIRING_NONZERO_BLOCKS_CONSUMPTION'
        assert 'resume_only=true' in section and 'unknown' in section and 'auxiliary_calls' in section, 'QA_WIRING_RESOURCE_GATES'
        return commands

    def test_structural_negatives_delete_real_bearing_segments_not_keyword_synonyms(self):
        self.instruction_contract(self.doc)
        lines = self.instruction_contract(self.doc)
        variants = [(self.doc.replace(lines[0], '', 1), 'QA_WIRING_PREPARE_FINAL_CHECK'),
                    (self.doc.replace(lines[2], '', 1), 'QA_WIRING_PREPARE_FINAL_CHECK'),
                    (self.doc.replace('仅 check exit=0 后', 'check 结果不阻止后续消费', 1),
                     'QA_WIRING_NONZERO_BLOCKS_CONSUMPTION'),
                    (self.doc.replace(lines[2], lines[2].replace('$FROZEN_NATIVE', '$LIVE_NATIVE'), 1),
                     'QA_WIRING_SAME_INPUTS')]
        for i, (bad, assertion) in enumerate(variants):
            (self.f.root / f'instruction-fault-{i}.md.txt').write_text(bad)
            with self.assertRaisesRegex(AssertionError, assertion):
                self.instruction_contract(bad)


class CompatibilityTests(unittest.TestCase):
    """Independent fact vectors and frozen-history defects, never inherited cases."""

    def setUp(self):
        self.k = qa_fixture(self, _CanonicalPolicyFixture())
        self.mod = self.k.mod
        self.cases = json.loads(QA_CASES.read_bytes())

    def facts(self, number, admitted=(1, 2), scopes=(), votes=None, attempt=None):
        findings = {1: [self.k.finding(scope=s, summary='独立QA ' + s) for s in scopes]}
        return self.k.facts(number, admitted, findings, votes, attempt)

    def test_partial_population_revise_quality_and_false_formula_are_separate(self):
        a = self.facts(1); b = self.facts(2)
        view = self.k.fold([a, b])['attempts'][-1]
        self.assertEqual(view['admitted_roles'], ['aria:qa-engineer', 'aria:tech-lead'])
        self.assertTrue(view['incomplete']); self.assertTrue(view['converged'])
        self.assertEqual(view['verdict'], 'PASS')
        b['audit']['roles'][1]['report']['vote'] = 'REVISE'
        self.assertFalse(self.k.fold([a, b])['policy']['terminal_state'])
        self.assertEqual(self.k.fold([a, b])['attempts'][-1]['verdict'], 'PASS')
        other = self.facts(2, (0, 2))
        self.assertFalse(self.k.compare(other, a, True)['converged'])
        self.assertTrue(self.k.compare(other, a, False)['converged'])  # Formula only, not legacy entry.

    def test_void_distribution_retains_actual_effective_baseline(self):
        a = self.facts(1); void = self.facts(2, (), attempt=2); b = self.facts(2, attempt=3)
        rows = self.k.fold([a, void, b])['attempts']
        self.assertEqual([r['policy']['charged_rounds'] for r in rows], [1, 1, 2], 'QA_VOID_CHARGES')
        self.assertEqual([r['all_failed_void'] for r in rows], [False, True, False])
        self.assertTrue(rows[-1]['converged'], 'QA_VOID_BASELINE')
        for field in ('charged_rounds', 'baseline'):
            bad = copy.deepcopy(rows)
            if field == 'charged_rounds': bad[1]['policy']['charged_rounds'] = 2
            else: bad[-1]['converged'] = False
            self.k.f.write(self.k.f.root / ('bad-void-' + field + '.json'), bad)
            with self.assertRaisesRegex(AssertionError, 'QA_VOID_'):
                self.assertEqual([r['policy']['charged_rounds'] for r in bad], [1, 1, 2], 'QA_VOID_CHARGES')
                self.assertTrue(bad[-1]['converged'], 'QA_VOID_BASELINE')

    def test_binary64_independent_sevenths_threshold_neighbors(self):
        import math
        self.k.complete_anchor()
        for total in (7, 11):
            ratio = 2 / total
            for threshold, action in ((math.nextafter(ratio, 0), 'REFOCUS_ROUND'),
                                      (ratio, 'REFOCUS_ROUND'),
                                      (math.nextafter(ratio, 1), 'NONE')):
                with self.subTest(total=total, threshold=threshold):
                    self.k.effective['drift_guard']['warn_threshold']['value'] = threshold
                    self.k.effective['drift_guard']['refocus_threshold']['value'] = threshold
                    a = self.facts(1, scopes=('prior',))
                    b = self.facts(2, scopes=tuple('qa-scope-' + str(i) for i in range(total)))
                    self.k.drift(b, ['off_topic'] * 2 + ['adjacent'] * (total - 2))
                    p = self.k.fold([a, b])['policy']
                    self.assertEqual(p['drift_ratio'].hex(), ratio.hex(), 'QA_BINARY64_RATIO')
                    self.assertEqual(p['drift_action'], action, 'QA_BINARY64_GE')

    def test_warn_blocks_convergence_without_rewriting_quality(self):
        self.k.complete_anchor()
        scopes = tuple('warn-' + str(i) for i in range(7))
        a = self.facts(1, scopes=scopes); b = self.k.drift(self.facts(2, scopes=scopes),
            ['off_topic', 'off_topic'] + ['on_topic'] * 5)
        row = self.k.fold([a, b])['attempts'][-1]
        self.assertTrue(row['conclusions_stable'])
        self.assertEqual(row['policy']['drift_action'], 'WARN')
        self.assertFalse(row['converged']); self.assertFalse(row['unanimous_pass'])
        self.assertEqual(row['verdict'], 'PASS')

    def test_refocus_void_skipped_distribution_and_normal_oscillation(self):
        self.k.complete_anchor()
        a = self.facts(1, scopes=('qa-A',))
        b = self.k.drift(self.facts(2, scopes=('qa-B',)), ['off_topic'])
        void = self.facts(3, (), attempt=3)
        skipped = self.k.drift(self.facts(3, scopes=('qa-A',), attempt=4), failure='control_timeout')
        c = self.k.drift(self.facts(4, scopes=('qa-C',), attempt=5), ['off_topic'])
        rows = self.k.fold([a, b, void, skipped, c])['attempts']
        self.assertEqual([r['policy']['charged_rounds'] for r in rows], [1, 2, 2, 3, 4])
        self.assertEqual([r['policy']['consecutive_refocus_count'] for r in rows], [0, 1, 1, 1, 2], 'QA_SKIP_PRESERVES_COUNT')
        self.assertTrue(rows[2]['policy']['pending_refocus'])
        self.assertTrue(rows[3]['policy']['is_refocus'])
        self.assertEqual(rows[-1]['policy']['terminal_state'], 'DRIFT_TERMINATED')
        # Independent healthy A/B/A has oscillation; inserting a refocus suppresses it.
        self.k.effective['drift_guard']['convergence_mode']['value'] = False
        normal = [self.facts(i + 1, scopes=(s,)) for i, s in enumerate(('N-A', 'N-B', 'N-A'))]
        self.assertEqual(self.k.fold(normal)['policy']['terminal_state'], 'OSCILLATION')

    def test_limits_and_terminal_priority_from_fixture(self):
        self.k.effective['drift_guard']['convergence_mode']['value'] = False
        for vector in self.cases['limits']:
            self.k.genesis['initial_max_rounds'] = vector['limit']
            attempts = [self.facts(i + 1, scopes=(s,)) for i, s in enumerate(vector['scopes'])]
            self.assertEqual(self.k.fold(attempts)['policy']['terminal_state'], vector['terminal'])
        self.k.genesis['initial_max_rounds'] = 2
        self.assertEqual(self.k.fold([self.facts(1), self.facts(2)])['policy']['terminal_state'], 'CONVERGED')
        self.k.complete_anchor(); self.k.genesis['initial_max_rounds'] = 3
        self.k.effective['drift_guard']['convergence_mode']['value'] = True
        attempts = [self.facts(1, scopes=('last-A',)),
            self.k.drift(self.facts(2, scopes=('last-B',)), ['off_topic']),
            self.k.drift(self.facts(3, scopes=('last-A',)), ['off_topic'])]
        self.assertEqual(self.k.fold(attempts)['policy']['terminal_state'], 'DRIFT_TERMINATED')

    def history(self, full=False):
        h = qa_fixture(self, HistoricalReplayTests('test_two_effective_partial_roles_converge_from_frozen_raw'))
        h.start(full=full)
        return h

    def test_independent_acyclic_chain_and_cycle_precedes_hash_error(self):
        h = self.history(); h.finish(admitted=(1, 2)); h.next_build(2, 2); h.finish(admitted=(1, 2))
        self.assertEqual(h.replay()['terminal_state'], 'CONVERGED')
        value = json.loads(h.last_result.read_bytes())
        value['inputs']['previous_round'] = {'path': str(h.last_result), 'sha256': 'f' * 64}
        h.f.write(h.last_result, value)
        event_path = h.f.scope() / 'events/0000000004.json'
        event = json.loads(event_path.read_bytes()); event['payload']['result'] = ref(h.last_result)
        h.f.write(event_path, event)
        h.reject_replay('E_HISTORY_CYCLE')

    def test_independent_missing_policy_leaf_and_changed_cycle_fail_closed(self):
        h = self.history(); result = h.finish(admitted=(1, 2))
        self.assertEqual(h.replay()['charged_rounds'], 1)
        h.f.manifest['audit_cycle_id'] = 'independent-cross-cycle'
        with self.assertRaises(h.mod.ExecutorError) as caught:
            h.next_build(2, 2)
        self.assertEqual(caught.exception.error_code, 'E_PREVIOUS_IDENTITY')
        h.f.manifest['audit_cycle_id'] = result['identity']['audit_cycle_id']
        blob = h.f.scope() / 'blobs' / (result['inputs']['policy_request']['sha256'] + '.blob')
        self.assertTrue(blob.exists()); blob.unlink()
        h.reject_replay('E_POLICY_SOURCE')

    def test_independent_result_tampering_recomputed_not_trusted(self):
        for field, bad in (('incomplete', False), ('converged', True), ('admitted_roles', ['aria:backend-architect'])):
            h = self.history(); h.finish(admitted=(1, 2))
            self.assertEqual(h.replay()['charged_rounds'], 1)
            value = json.loads(h.last_result.read_bytes()); value[field] = bad
            h.f.write(h.last_result, value)
            p = h.f.scope() / 'events/0000000002.json'
            event = json.loads(p.read_bytes()); event['payload']['result'] = ref(h.last_result); h.f.write(p, event)
            h.reject_replay('E_RESULT_MISMATCH')

    def test_independent_canonical_members_variants_and_real_fault_function(self):
        # Distinct claims, duplicate member, type, severity promotion, exact scopes.
        fs = {1: [self.k.finding(scope=' Q ', summary='one'), self.k.finding(scope=' Q ', summary='one'),
                  self.k.finding(scope=' Q ', type='risk', severity='critical', summary='risk')],
              2: [self.k.finding(scope=' Q ', summary='two'), self.k.finding(scope='Q', summary='trim trap')]}
        attempt = self.k.facts(1, (1, 2), fs)
        healthy = self.mod._aggregate_admitted(attempt['audit']['roles'])

        def conservation(view):
            self.assertEqual(len(view['comparison_keys']), 3, 'QA_CANONICAL_FULL_KEYS')
            self.assertEqual(sum(len(v['members']) for c in view['conclusions'] for v in c['variants']), 5,
                             'QA_CANONICAL_MEMBERS')
            self.assertEqual(sum(len(c['variants']) for c in view['conclusions']), 4, 'QA_CANONICAL_VARIANTS')
            self.assertEqual({c['severity'] for c in view['conclusions'] if c['scope'] == ' Q '},
                             {'critical'}, 'QA_CANONICAL_PROMOTION')

        conservation(healthy)
        import inspect
        source = inspect.getsource(self.mod._aggregate_admitted)
        needle = 'return {"'
        # Fault code is injected at the actual function's final return boundary;
        # preserve the real aggregation and drop one actual provenance member.
        tree = __import__('ast').parse(source)
        returns = [n for n in __import__('ast').walk(tree) if isinstance(n, __import__('ast').Return)]
        last = max(returns, key=lambda n: n.lineno)
        lines = source.splitlines(True)
        fault = "    conclusions[0]['variants'][0]['members'].pop()\n"
        # The actual local list name is read from the real return expression below.
        self.assertIn('conclusions', source)
        lines.insert(last.lineno - 1, fault)
        mutated = ''.join(lines)
        (self.k.f.root / 'canonical-fault.py.txt').write_text(mutated)
        self.k.f.write(self.k.f.root / 'canonical-healthy.json', healthy)
        namespace = dict(vars(self.mod)); exec(compile(mutated, '<qa-canonical-fault>', 'exec'), namespace)
        bad = namespace['_aggregate_admitted'](attempt['audit']['roles'])
        self.k.f.write(self.k.f.root / 'canonical-fault-output.json', bad)
        with self.assertRaisesRegex(AssertionError, 'QA_CANONICAL_MEMBERS'):
            conservation(bad)


class IndependentSeamTests(unittest.TestCase):
    """TASK-013 fresh QA: synthetic sources, real kernels/CLI, no live agents.

    Each fault is applied before the production consumer runs. Mutants execute
    actual isolated function source; assertion failures, not setup errors, count.
    """

    def kernel(self):
        return qa_fixture(self, _CanonicalPolicyFixture())

    def history(self, limit=5, full=False):
        h = qa_fixture(self, HistoricalReplayTests())
        h.start(limit=limit, full=full)
        return h

    def integrity(self):
        return qa_fixture(self, ResultIntegrityTests())

    def retain(self, root, name, value):
        path = root / (name + '.json')
        path.write_bytes(encode(value))
        return path

    def mutation(self, k, function, old, new, name, args, assertion):
        import difflib
        import inspect
        original = inspect.getsource(getattr(k.mod, function))
        self.assertEqual(original.count(old), 1, 'QA_MUTANT_UNIQUE_SITE')
        changed = original.replace(old, new, 1)
        root = k.f.root
        (root / (name + '.source.py.txt')).write_text(original)
        (root / (name + '.mutant.py.txt')).write_text(changed)
        (root / (name + '.diff.txt')).write_text(''.join(difflib.unified_diff(
            original.splitlines(True), changed.splitlines(True), fromfile=function, tofile=name)))
        healthy = getattr(k.mod, function)(*args)
        assertion(healthy)
        ns = dict(vars(k.mod))
        exec(compile(changed, str(root / (name + '.mutant.py.txt')), 'exec'), ns)
        bad = ns[function](*args)  # Syntax/import/setup errors are never CAUGHT.
        self.retain(root, name + '-healthy', healthy)
        self.retain(root, name + '-actual-bad', bad)
        self.retain(root, name + '-hashes', {'source': hashlib.sha256(original.encode()).hexdigest(),
            'mutant': hashlib.sha256(changed.encode()).hexdigest()})
        return bad

    def test_real_fold_void_charge_mutant(self):
        k = self.kernel()
        attempts = [k.facts(1, (1, 2)), k.facts(2, (), attempt_index=2)]
        def check(value):
            self.assertEqual([r['policy']['charged_rounds'] for r in value['attempts']],
                             [1, 1], 'QA_REAL_VOID_CHARGE')
        bad = self.mutation(k, '_apply_policy', "        severity = {c['severity'] for c in view['conclusions']}",
            "        if view['all_failed_void']:\n            policy['charged_rounds'] += 1\n"
            "        severity = {c['severity'] for c in view['conclusions']}",
            'void-charges', (k.genesis, attempts, k.effective, k.anchor), check)
        with self.assertRaisesRegex(AssertionError, 'QA_REAL_VOID_CHARGE'):
            check(bad)

    def test_real_fold_void_replaces_baseline_mutant(self):
        k = self.kernel()
        attempts = [k.facts(1, (1, 2)), k.facts(2, (), attempt_index=2),
                    k.facts(2, (1, 2), attempt_index=3)]
        def check(value):
            self.assertTrue(value['attempts'][-1]['converged'], 'QA_REAL_VOID_BASELINE')
        bad = self.mutation(k, '_apply_policy', "        severity = {c['severity'] for c in view['conclusions']}",
            "        if view['all_failed_void'] and previous is not None:\n"
            "            previous = {**previous, 'roles': current['roles']}\n"
            "        severity = {c['severity'] for c in view['conclusions']}",
            'void-baseline', (k.genesis, attempts, k.effective, k.anchor), check)
        with self.assertRaisesRegex(AssertionError, 'QA_REAL_VOID_BASELINE'):
            check(bad)

    def test_real_fold_skipped_clears_count_mutant(self):
        k = self.kernel(); k.complete_anchor()
        attempts = [k.facts(1, findings={0: [k.finding(scope='fresh-start')]}),
            k.drift(k.facts(2, findings={0: [k.finding(scope='fresh-drift')]}), ['off_topic']),
            k.facts(3, (), attempt_index=3),
            k.drift(k.facts(3, findings={0: [k.finding(scope='fresh-skip')]}, attempt_index=4),
                    failure='control_timeout')]
        def check(value):
            self.assertEqual([r['policy']['consecutive_refocus_count'] for r in value['attempts']],
                             [0, 1, 1, 1], 'QA_REAL_SKIP_COUNT')
        bad = self.mutation(k, '_apply_policy', "elif drift['drift_ratio'] is not None:", 'elif True:',
            'skip-clears-count', (k.genesis, attempts, k.effective, k.anchor), check)
        with self.assertRaisesRegex(AssertionError, 'QA_REAL_SKIP_COUNT'):
            check(bad)

    def test_real_short_id_collision_and_merging_mutant(self):
        k = self.kernel()
        seen = {}; pair = None
        for i in range(400000):
            scope = 'fresh-qa-collision-' + str(i)
            short = hashlib.sha256(('implementation:' + scope + ':minor:issue').encode()).hexdigest()[:8]
            if short in seen:
                pair = (seen[short], scope); break
            seen[short] = scope
        if pair is None:
            self.fail('QA_COLLISION_FIXTURE_NOT_FOUND')
        attempt = k.facts(1, (1, 2), {1: [k.finding(scope=s) for s in pair]})
        def check(value):
            self.assertEqual(len(value['conclusions']), 2, 'QA_REAL_SHORT_ID_KEYS')
            self.assertEqual(len({c['id'] for c in value['conclusions']}), 1, 'QA_REAL_COLLISION_PRECONDITION')
            self.assertEqual(len(value['comparison_keys']), 2, 'QA_REAL_SHORT_ID_KEYS')
        import inspect
        source = inspect.getsource(k.mod._aggregate_admitted)
        import ast
        line = max(n.lineno for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Return))
        needle = source.split('\n')[line - 1]
        bad = self.mutation(k, '_aggregate_admitted', needle,
            "    conclusions = list({c['id']: c for c in conclusions}.values())\n" + needle,
            'short-id-merges-keys', (attempt['audit']['roles'],), check)
        self.retain(k.f.root, 'collision-input', {'scopes': pair, 'attempt': attempt})
        with self.assertRaisesRegex(AssertionError, 'QA_REAL_SHORT_ID_KEYS'):
            check(bad)

    def test_real_swallowed_variant_mutant(self):
        k = self.kernel()
        attempt = k.facts(1, (1, 2), {1: [k.finding(scope='Variant', failure_scenario='first claim')],
            2: [k.finding(scope='Variant', failure_scenario='different claim')]})
        def check(value):
            self.assertEqual(sum(len(c['variants']) for c in value['conclusions']), 2,
                             'QA_REAL_VARIANT_CONSERVATION')
        import ast
        import inspect
        source = inspect.getsource(k.mod._aggregate_admitted)
        line = max(n.lineno for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Return))
        needle = source.split('\n')[line - 1]
        bad = self.mutation(k, '_aggregate_admitted', needle,
            "    conclusions[0]['variants'].pop()\n" + needle, 'swallowed-variant',
            (attempt['audit']['roles'],), check)
        with self.assertRaisesRegex(AssertionError, 'QA_REAL_VARIANT_CONSERVATION'):
            check(bad)

    def candidate(self, h, logical, attempt, previous=None):
        f = h.f
        previous = h.results[-1] if previous is None and h.results else previous
        f.run_dir = f.repo / '.aria/audit-reports' / (
            f'post_spec-R{logical}-fresh-{attempt}-build-target-aggregated')
        f.manifest_path = f.repo / f'fresh-manifest-{attempt}.json'
        f.manifest.update(round=logical, attempt_index=attempt, client_round_id=f'fresh-{attempt}')
        f.manifest['evidence'].update(cycle_origin=ref(f.scope() / 'genesis.json'), previous_round=previous,
            post_audit_index_path=str(f.run_dir / 'audit-index.json'),
            post_drift_index_path=str(f.run_dir / 'drift-index.json'),
            post_disposition_index_path=str(f.run_dir / 'disposition-index.json'))

    def build_cli(self, f, code=None):
        f.write(f.manifest_path, f.manifest)
        before = {str(p): p.read_bytes() for p in f.scope().rglob('*') if p.is_file()}
        response = subprocess.run([sys.executable, '-I', str(f.engine / 'scripts/audit_executor.py'),
            'build', '--repo-path', str(f.repo), '--manifest', str(f.manifest_path),
            '--output-dir', str(f.run_dir)], capture_output=True, cwd=f.root)
        self.retain(f.root, 'fresh-build-last', {'exit': response.returncode,
            'stdout': response.stdout.decode(), 'stderr': response.stderr.decode()})
        if code is None:
            self.assertEqual(response.returncode, 0, response.stderr.decode())
            return json.loads(response.stdout)
        self.assertNotEqual(response.returncode, 0, 'QA_REAL_BUILD_MUST_REJECT')
        self.assertEqual(json.loads(response.stderr)['error_code'], code, response.stderr.decode())
        self.assertEqual(before, {str(p): p.read_bytes() for p in f.scope().rglob('*') if p.is_file()},
                         'QA_REJECT_NO_RESERVE')
        self.assertFalse((f.run_dir / 'workflow.js').exists(), 'QA_REJECT_NO_SCRIPT')
        return None

    def test_independent_bootstrap_reset_config_and_head_rejections(self):
        for bad in ('null', 'cycle', 'config', 'head'):
            with self.subTest(bad=bad):
                h = self.history()
                h.finish(admitted=(1, 2), findings=[_CanonicalPolicyFixture.finding(scope='fresh-history')])
                first = h.results[-1]
                self.assertEqual(h.replay()['charged_rounds'], 1)
                if bad == 'head':
                    h.next_build(2, 2)
                    h.finish(admitted=(1, 2), findings=[_CanonicalPolicyFixture.finding(scope='fresh-second')])
                self.candidate(h, 3 if bad == 'head' else 2, 3 if bad == 'head' else 2)
                code = 'E_PREVIOUS_IDENTITY'
                if bad == 'null':
                    h.f.manifest['evidence'].update(cycle_origin=None, previous_round=None)
                elif bad == 'cycle':
                    h.f.manifest['audit_cycle_id'] = 'fresh-forbidden-cycle'
                elif bad == 'head':
                    h.f.manifest['evidence']['previous_round'] = first
                else:
                    h.f.defaults_value['audit']['max_rounds'] = 19
                    h.f.write(h.f.defaults, h.f.defaults_value); code = 'E_SOURCE_DRIFT'
                self.build_cli(h.f, code)

    def test_independent_exhaustion_and_converged_precede_reserve(self):
        for terminal in ('MAX_ROUNDS_EXHAUSTED', 'CONVERGED'):
            with self.subTest(terminal=terminal):
                h = self.history(limit=1 if terminal == 'MAX_ROUNDS_EXHAUSTED' else 5)
                h.finish(admitted=(1, 2))
                logical = 2
                if terminal == 'CONVERGED':
                    h.next_build(2, 2); h.finish(admitted=(1, 2)); logical = 3
                self.assertEqual(h.replay()['terminal_state'], terminal)
                self.candidate(h, logical, logical)
                self.build_cli(h.f, 'E_POLICY_BLOCKED')

    def test_independent_jsonl_cross_agent_and_corrupt_selected_line(self):
        for fault in ('agent', 'json'):
            n = qa_fixture(self, NativeEvidenceTests())
            log = n.interrupt(); n.capture()
            self.assertEqual(n.classify()['roles'][0]['termination_evidence'], 'interrupted_observed')
            if fault == 'agent':
                event = copy.deepcopy(n.event); event['agentId'] = 'fresh-wrong-agent'
                log.write_bytes(b'{"prefix":"fresh"}\n' + encode(event) + b'\n')
            else:
                log.write_bytes(b'{"prefix":"fresh"}\n{"broken":\n')
            n.links[0]['event']['file'] = ref(log); n.capture()
            with self.assertRaises(n.mod.ExecutorError) as caught:
                n.classify()
            self.assertEqual(caught.exception.error_code, 'E_NATIVE_EVIDENCE')
            self.retain(n.f.root, 'jsonl-rejection', {'fault': fault, 'error': str(caught.exception)})

    def test_independent_partial_anchor_required_legal_and_off_topic(self):
        for label in ('on_topic', 'adjacent'):
            h = self.integrity(); h.prepare(); h.final()
            h.next_round(findings=[_CanonicalPolicyFixture.finding(scope='fresh-partial-anchor')])
            prepared = h.prepare()
            request = json.loads(Path(prepared['policy_request']['path']).read_bytes())
            self.assertTrue(request['required'], 'QA_PARTIAL_MUST_CALL_CHECKER')
            anchor = json.loads(Path(request['anchor']['path']).read_bytes())['value']
            self.assertTrue(anchor['primary_goal']); self.assertEqual(anchor['in_scope'], [])
            self.assertEqual(anchor['out_of_scope_hints'], [])
            key = [request['conclusions'][0][k] for k in ('type', 'severity', 'category', 'scope')]
            h.checker(prepared, [{'key': key, 'classification': 'off_topic'}])
            response = h.cli()
            self.assertEqual(json.loads(response.stderr)['error_code'], 'E_POLICY_SOURCE')
            self.assertFalse(h.output().exists())
            h.checker(prepared, [{'key': key, 'classification': label}]); h.final(); h.ok(h.check())
            result = json.loads(h.output().read_bytes())
            self.assertEqual(result['policy']['drift_ratio'], 0.0)
            self.assertTrue(result['policy']['anchor_scope_empty'])
            self.assertEqual(result['policy']['drift_classification_confidence'], 'low')
            self.assertFalse(result['policy']['drift_check_skipped'])

    def test_independent_monotonic_preflight_and_rewritten_start(self):
        s = qa_fixture(self, SlotLifecycleTests())
        s.n.native['startTime'] = 0
        for node in s.n.native['workflowProgress']:
            if node['type'] == 'workflow_agent':
                node['queuedAt'] = 100
        s.n.capture(); captured = s.mod._Inputs(); s.audit = s.n.classify(captured)
        s.frozen = s.mod._FrozenInputs(dict(captured.raw)); original = encode(s.audit)
        started = copy.deepcopy(s.n.native)
        for node in started['workflowProgress']:
            if node['type'] == 'workflow_agent': node['startedAt'] = 150
        view = s.apply(s.preflight(started, name='fresh-started'))
        self.assertEqual(len(view['unknown_calls']), 2)
        self.assertFalse(view['next_round_dispatch_allowed'])
        s.state = s.mod._load_scope(s.scope, s.f.manifest, s.mod._Inputs())
        done = copy.deepcopy(started)
        for node in done['workflowProgress']:
            if node['type'] == 'workflow_agent': node.update(state='done', durationMs=20)
        bad = copy.deepcopy(done); bad['workflowProgress'][1]['startedAt'] = 151
        s.reject(s.preflight(bad, name='fresh-rewritten-start'), 'E_NATIVE_TIME')
        view = s.apply(s.preflight(done, name='fresh-completed'))
        self.assertEqual(view['unknown_calls'], [])
        self.assertTrue(view['next_round_dispatch_allowed'])
        self.assertEqual(encode(s.audit), original, 'QA_OBSERVE_NO_OLD_VOTE_UPGRADE')

    def disposition(self):
        d = qa_fixture(self, HumanDispositionTests())
        d.question()
        d.q['uuid'] = 'fresh-question'; d.r['uuid'] = 'fresh-response'
        d.q['message']['content'][0]['id'] = 'fresh-tool-use'
        d.r['message']['content'][0]['tool_use_id'] = 'fresh-tool-use'
        d.r['sourceToolAssistantUUID'] = d.q['uuid']
        d.idx['question']['event_uuid'] = d.q['uuid']; d.idx['response']['event_uuid'] = d.r['uuid']
        d.save_question()
        return d

    def test_independent_increase_sidecar_duplicate_and_real_next_build(self):
        d = self.disposition()
        self.assertEqual(d.replay()['remaining_rounds'], 0)
        side = d.consume()
        self.assertEqual((side['effective_limit'], side['remaining_rounds']), (3, 2))
        before = d.h.snapshot(); d.consume(); self.assertEqual(d.h.snapshot(), before)
        self.assertEqual(len(d.replay()['dispositions']), 1)
        d.q['uuid'] = 'fresh-second-question'; d.r['sourceToolAssistantUUID'] = d.q['uuid']
        d.idx['question']['event_uuid'] = d.q['uuid']; d.save_question(); d.reject()
        # Remove rejected later locator; it is not a new authorization.
        d.index.unlink()
        d.h.next_round(); d.h.prepare(); d.h.final(); d.h.ok(d.h.check())
        self.assertEqual(json.loads(d.h.output().read_bytes())['policy']['effective_limit'], 3)
        self.assertEqual(d.base.read_bytes(), d.base_bytes)

    def test_independent_missing_commit_exact_recovery_and_conflict(self):
        h = self.integrity(); h.prepare(); h.final()
        result, md = h.output().read_bytes(), h.output().with_suffix('.md').read_bytes()
        commit = h.f.scope() / 'events/0000000002.json'; raw = commit.read_bytes()
        commit.unlink()
        h.final(); h.ok(h.check())
        self.assertEqual(commit.read_bytes(), raw)
        self.assertEqual(h.output().read_bytes(), result)
        self.assertEqual(h.output().with_suffix('.md').read_bytes(), md)
        self.assertEqual(len(list((h.f.scope() / 'events').glob('*.json'))), 2)
        commit.unlink(); h.output().write_bytes(result + b' ')
        before = h.snapshot(); response = h.cli()
        self.assertNotEqual(response.returncode, 0)
        self.assertEqual(json.loads(response.stderr)['error_code'], 'E_OUTPUT_CONFLICT')
        self.assertEqual(h.snapshot(), before); self.assertFalse(commit.exists())

    def test_independent_real_cli_pending_and_unknown_slots(self):
        h = self.history()
        receipt = self.build_cli(h.f)
        if receipt is None:
            self.fail('QA_PENDING_RECEIPT_REQUIRED')
        self.assertTrue(receipt['resume_only'])
        h.finish(admitted=(0, 1), unknown=True)
        self.assertFalse(h.replay()['resource_view']['next_round_dispatch_allowed'])
        self.candidate(h, 2, 2)
        self.build_cli(h.f, 'E_RESOURCE_PENDING')

    def test_independent_wrong_carrier_origin_not_equal_content(self):
        finding = _CanonicalPolicyFixture.finding(scope='fresh-carrier')
        healthy = self.history(); healthy.finish(admitted=(1, 2), findings=[finding])
        self.assertEqual(healthy.replay()['charged_rounds'], 1)
        for field in ('anchor', 'audit_index', 'input_closure'):
            with self.subTest(field=field):
                h = self.history()
                h.finish(admitted=(1, 2), findings=[finding], carriers={'bad_request': field})
                with self.assertRaises(h.mod.ExecutorError) as caught:
                    h.replay()
                self.assertEqual(caught.exception.error_code, 'E_POLICY_SOURCE')

    def test_independent_drift_and_oscillation_terminal_no_reserve(self):
        for terminal in ('DRIFT_TERMINATED', 'OSCILLATION'):
            with self.subTest(terminal=terminal):
                h = self.history(full=True)
                for i, scope in enumerate(('fresh-A', 'fresh-B', 'fresh-A'), 1):
                    if i > 1: h.next_build(i, i)
                    h.finish(admitted=(1, 2), findings=[_CanonicalPolicyFixture.finding(scope=scope)],
                        classes=['off_topic'] if terminal == 'DRIFT_TERMINATED' and i > 1 else None)
                self.assertEqual(h.replay()['terminal_state'], terminal)
                self.assertGreater(h.replay()['remaining_rounds'], 0)
                self.candidate(h, 4, 4); self.build_cli(h.f, 'E_POLICY_BLOCKED')

    def test_independent_accept_degrade_and_bad_question_sources(self):
        for action in ('accept_current', 'degrade_single'):
            with self.subTest(action=action):
                d = self.disposition()
                question = d.q['message']['content'][0]['input']['questions'][0]
                label = next(o['label'] for o in d.idx['options'] if o['action'] == action)
                d.r['toolUseResult']['answers'] = {question['question']: label}
                d.save_question(); original = copy.deepcopy((d.q, d.r))
                for bad in ('notification', 'cycle'):
                    d.q, d.r = copy.deepcopy(original)
                    if bad == 'notification': d.r['type'] = 'notification'
                    else:
                        q = d.q['message']['content'][0]['input']['questions'][0]
                        context = json.loads(q['question'].split('audit-disposition-context=')[1])
                        context['audit_cycle_id'] = 'fresh-cross-cycle'
                        q['question'] = 'synthetic\naudit-disposition-context=' + encode(context).decode()
                        d.r['toolUseResult']['questions'] = [copy.deepcopy(q)]
                        d.r['toolUseResult']['answers'] = {q['question']: label}
                    d.save_question(); d.reject()
                d.q, d.r = original; d.save_question(); side = d.consume()
                self.assertFalse(side['converged'])
                self.assertTrue(side['overridden_by_user'] if action == 'accept_current' else side['degraded'])
                h = HistoricalReplayTests(); h.f = d.f; h.results = [ref(d.base)]
                self.candidate(h, 2, 2); self.build_cli(d.f, 'E_POLICY_BLOCKED')

    def test_independent_real_cli_unknown_auxiliary_slot(self):
        h = self.integrity(); h.prepare(); h.final()
        h.next_round(findings=[_CanonicalPolicyFixture.finding(scope='fresh-aux-slot')])
        prepared = h.prepare(); self.assertTrue(json.loads(Path(prepared['policy_request']['path']).read_bytes())['required'])
        h.checker(prepared, timeout=True)
        native_path = h.f.run_dir / 'checker-native.json'
        native = json.loads(native_path.read_bytes())
        native['workflowProgress'][0]['state'] = 'progress'
        native['workflowProgress'][0].pop('durationMs')
        h.f.write(native_path, native)
        index_path = h.f.run_dir / 'drift-index.json'
        index = json.loads(index_path.read_bytes()); index['native_record'] = ref(native_path)
        h.f.write(index_path, index); h.final(); h.ok(h.check())
        result = json.loads(h.output().read_bytes())
        self.assertTrue(result['policy']['drift_check_skipped'])
        self.assertFalse(result['next_round_dispatch_allowed'])
        prior = h.output()
        shim = HistoricalReplayTests(); shim.f = h.f; shim.results = [ref(prior)]
        self.candidate(shim, 3, 3); self.build_cli(h.f, 'E_RESOURCE_PENDING')

    def test_required_checker_cli_health_and_tamper_without_live_growth(self):
        w = qa_fixture(self, WiringContractTests())
        w.build_round(); w.prepare(); first = w.final_check()
        self.assertEqual(first['policy']['charged_rounds'], 1)
        w.previous = w.h.output(); w.env['PREVIOUS_RESULT'] = str(w.previous)
        shim = HistoricalReplayTests(); shim.f = w.f; shim.results = [ref(w.previous)]
        self.candidate(shim, 2, 2)
        w.build_round(); prepared = w.prepare()
        self.assertTrue(json.loads(Path(prepared['policy_request']['path']).read_bytes())['required'])
        w.recipe(lambda l: '"$FROZEN_NATIVE"' in l and '--check-result' not in l, expected='E_POLICY_SOURCE')
        w.independent_checker(prepared); second = w.final_check()
        self.assertEqual(second['policy']['charged_rounds'], 2)
        self.assertEqual(second['policy']['drift_ratio'], 0.0)
        self.assertTrue(second['incomplete']); self.assertFalse(second['converged'])
        body = json.loads(w.h.output().read_bytes()); body['converged'] = True
        w.f.write(w.h.output(), body)
        w.recipe(lambda l: '--check-result' in l, expected='E_RESULT_MISMATCH')


class RequiredCheckerFrozenSourceTests(unittest.TestCase):
    """Old audit origins stay frozen; newly acquired checker facts stay live-verified."""

    def required_checker(self):
        w = qa_fixture(self, WiringContractTests())
        w.build_round(); w.prepare()
        first = w.final_check()
        self.assertFalse(first['all_failed_void'])
        self.assertEqual(len(first['admitted_roles']), 2)
        self.assertEqual(first['policy']['charged_rounds'], 1)
        w.previous = w.h.output()
        w.env['PREVIOUS_RESULT'] = str(w.previous)
        shim = HistoricalReplayTests(); shim.f = w.f; shim.results = [ref(w.previous)]
        IndependentSeamTests().candidate(shim, 2, 2)
        w.build_round(); prepared = w.prepare()
        self.assertTrue(json.loads(Path(prepared['policy_request']['path']).read_bytes())['required'])
        w.independent_checker(prepared)
        return w

    def assert_final_check_and_successor(self, w):
        second = w.final_check()  # Same frozen CLI argument for final and read-only check.
        self.assertEqual(second['policy']['charged_rounds'], 2)
        self.assertEqual(second['policy']['drift_ratio'], 0.0)
        self.assertTrue(second['incomplete']); self.assertFalse(second['converged'])
        w.previous = w.h.output()
        w.env['PREVIOUS_RESULT'] = str(w.previous)
        shim = HistoricalReplayTests(); shim.f = w.f; shim.results = [ref(w.previous)]
        IndependentSeamTests().candidate(shim, 3, 3)
        w.build_round()  # Real build must replay the preceding required-checker round.
        self.assertTrue((w.f.run_dir / 'build-record.json').exists())

    def test_required_final_check_history_ignore_old_audit_live_growth(self):
        w = self.required_checker()
        w.native.write_bytes(w.native.read_bytes() + b'\n')
        self.assert_final_check_and_successor(w)

    def test_required_final_check_history_survive_deleted_old_audit_origins(self):
        w = self.required_checker()
        w.native.unlink()
        (w.f.run_dir / 'audit-index.json').unlink()
        self.assert_final_check_and_successor(w)

    def test_new_checker_bad_hash_or_identity_rejects_without_publication_or_check_writes(self):
        for fault in ('hash', 'identity'):
            with self.subTest(fault=fault):
                w = self.required_checker()
                # A frozen audit must not hide a bad *new* checker behind old-source drift.
                w.native.write_bytes(w.native.read_bytes() + b'\n')
                checker_path = w.f.run_dir / 'checker-native.json'
                if fault == 'hash':
                    checker_path.write_bytes(checker_path.read_bytes() + b'\n')
                    expected, reason = 'E_NATIVE_EVIDENCE', 'source_hash_mismatch'
                else:
                    native = json.loads(checker_path.read_bytes())
                    native['runId'] = 'foreign-checker-run'
                    w.f.write(checker_path, native)
                    index_path = w.f.run_dir / 'drift-index.json'
                    index = json.loads(index_path.read_bytes())
                    index['native_record'] = ref(checker_path)
                    w.f.write(index_path, index)
                    expected, reason = 'E_RUN_IDENTITY', 'checker_native_run_script_args'
                before = {k: v for k, v in w.h.snapshot().items() if '/repo/' in k}
                w.recipe(lambda l: '"$FROZEN_NATIVE"' in l and '--check-result' not in l,
                         expected=expected)
                error = json.loads((w.f.root / f'command-{w.serial}.stderr').read_bytes())
                self.assertEqual(error['reason'], reason)
                self.assertEqual(error['input_ref'], str(checker_path))
                self.assertEqual({k: v for k, v in w.h.snapshot().items() if '/repo/' in k}, before)
                for path in (w.h.output(), w.h.output().with_suffix('.md'),
                             w.f.run_dir / 'publication-record.json', w.f.run_dir / 'final-closure.json'):
                    self.assertFalse(path.exists(), 'failed checker must not publish ' + str(path))
                w.recipe(lambda l: '"$FROZEN_NATIVE"' in l and '--check-result' in l,
                         expected='E_POLICY_SOURCE')
                self.assertEqual({k: v for k, v in w.h.snapshot().items() if '/repo/' in k}, before)


class FinalGapIndependentTests(unittest.TestCase):
    """Fresh B2 inputs and source mutations; no inherited test methods or live backend."""

    def fixture(self, case):
        from unittest.mock import patch
        root = QA_NOTES / 'final-gaps' / 'runs' / self.id().split('.')[-1]
        root.mkdir(parents=True, exist_ok=True)

        class RetainedWorkspace:
            def __init__(self, *args, **kwargs):
                self.name = tempfile.mkdtemp(prefix='source-', dir=root)

            def cleanup(self):
                pass

        with patch.object(tempfile, 'TemporaryDirectory', RetainedWorkspace):
            case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def save(self, root, name, value):
        path = root / (name + '.json')
        path.write_bytes(encode(value))
        return path

    def snapshot(self, root):
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*') if p.is_file() and p.name != 'writer.lock'}

    def cli(self, f):
        f.write(f.manifest_path, f.manifest)
        response = subprocess.run([sys.executable, '-I', str(f.engine / 'scripts/audit_executor.py'),
            'build', '--repo-path', str(f.repo), '--manifest', str(f.manifest_path),
            '--output-dir', str(f.run_dir)], cwd=f.root, capture_output=True)
        return response, json.loads(response.stdout if response.returncode == 0 else response.stderr)

    def mutate(self, module, function, old, new, root, name):
        import difflib
        import inspect
        source = inspect.getsource(getattr(module, function))
        self.assertEqual(source.count(old), 1, 'QA_B2_UNIQUE_MUTATION_SITE')
        mutant = source.replace(old, new, 1)
        source_path = root / (name + '.source.py.txt')
        mutant_path = root / (name + '.mutant.py.txt')
        source_path.write_text(source)
        mutant_path.write_text(mutant)
        (root / (name + '.diff.txt')).write_text(''.join(difflib.unified_diff(
            source.splitlines(True), mutant.splitlines(True), fromfile=function, tofile=name)))
        exec(compile(mutant, str(mutant_path), 'exec'), vars(module))
        self.save(root, name + '-source-hashes', {
            'function': function, 'source': ref(source_path), 'mutant': ref(mutant_path),
            'isolated_module': ref(Path(module.__file__)), 'compile': 'PASS'})

    def test_bootstrap_future_hash_and_self_referential_genesis(self):
        healthy = self.fixture(BuildContractTests())
        self.assertIsNone(healthy.manifest['evidence']['cycle_origin'])
        self.assertIsNone(healthy.manifest['evidence']['previous_round'])
        for key in ('post_audit_index_path', 'post_drift_index_path', 'post_disposition_index_path'):
            self.assertFalse(Path(healthy.manifest['evidence'][key]).exists())
        initial_manifest = copy.deepcopy(healthy.manifest)
        response, receipt = self.cli(healthy)
        self.assertEqual(response.returncode, 0, response.stderr.decode())
        if receipt is None:
            self.fail('QA_B2_BOOTSTRAP_RECEIPT_REQUIRED')
        self.assertFalse(receipt['resume_only'])
        genesis_path = healthy.scope() / 'genesis.json'
        genesis = json.loads(genesis_path.read_bytes())
        # Real graph validation of a complete, healthy genesis is the control.
        healthy.mod._HistoryGraph(healthy.scope()).walk(ref(genesis_path), genesis_path, 'genesis')
        self.save(healthy.root, 'bootstrap-healthy', {'input': initial_manifest, 'receipt': receipt,
            'genesis': ref(genesis_path), 'events': self.snapshot(healthy.scope() / 'events')})

        future = self.fixture(BuildContractTests())
        future_path = Path(future.manifest['evidence']['post_audit_index_path'])
        self.assertFalse(future_path.exists())
        # A complete manifest illegally depends on a post-run hash BEFORE bootstrap.
        future.manifest['evidence']['policy_inputs'] = {'path': str(future_path), 'sha256': '0' * 64}
        future.mod._validate_manifest(future.manifest)
        response, error = self.cli(future)
        self.assertNotEqual(response.returncode, 0)
        self.assertEqual(error['error_code'], 'E_POLICY_SOURCE', 'QA_B2_FUTURE_HASH')
        self.assertEqual(error['input_ref'], str(future_path))
        self.assertFalse((future.scope() / 'genesis.json').exists())
        self.assertFalse((future.run_dir / 'workflow.js').exists())
        self.assertFalse(list((future.scope() / 'events').glob('*.json')))
        self.save(future.root, 'future-hash-rejection', {'input': future.manifest, 'error': error,
            'returncode': response.returncode, 'events': [], 'workflow_exists': False})

        self_path = healthy.root / 'self-genesis.json'
        bad_genesis = copy.deepcopy(genesis)
        # The back edge has a deliberately WRONG hash. No SHA fixed point is sought.
        bad_genesis['policy_inputs'] = {'path': str(self_path), 'sha256': '0' * 64}
        healthy.write(self_path, bad_genesis)
        self.assertEqual(set(bad_genesis), set(genesis))
        with self.assertRaises(healthy.mod.ExecutorError) as caught:
            healthy.mod._HistoryGraph(healthy.scope()).walk(ref(self_path), self_path, 'genesis')
        self.assertEqual(caught.exception.error_code, 'E_HISTORY_CYCLE', 'QA_B2_SELF_GENESIS')
        self.assertEqual(caught.exception.reason, 'structural_origin_reentry')
        self.save(healthy.root, 'self-genesis-rejection', {'input': ref(self_path),
            'back_edge': bad_genesis['policy_inputs'], 'error_code': caught.exception.error_code,
            'reason': caught.exception.reason, 'complete_genesis_keys': sorted(bad_genesis)})

    def test_policy_ignored_source_mutant_really_reserves_terminal_head(self):
        for terminal, limit in (('MAX_ROUNDS_EXHAUSTED', 1), ('CONVERGED', 5)):
            with self.subTest(terminal=terminal):
                h = self.fixture(HistoricalReplayTests())
                h.start(limit=limit)
                h.finish(admitted=(1, 2))
                logical = 2
                if terminal == 'CONVERGED':
                    h.next_build(2, 2)
                    h.finish(admitted=(1, 2))
                    logical = 3
                view = h.replay()
                self.assertEqual(view['terminal_state'], terminal)
                self.assertEqual(view['resource_view']['unknown_calls'], [])
                self.assertTrue(view['resource_view']['next_round_dispatch_allowed'])
                # Bind the public constructor to its ORIGINAL type, not this TestCase.
                IndependentSeamTests().candidate(h, logical, logical)
                h.f.write(h.f.manifest_path, h.f.manifest)
                before = self.snapshot(h.f.scope())
                response, error = self.cli(h.f)
                self.assertNotEqual(response.returncode, 0)
                self.assertEqual(error['error_code'], 'E_POLICY_BLOCKED')
                self.assertEqual(error['reason'], 'prefix_policy_forbids_dispatch')
                self.assertEqual(self.snapshot(h.f.scope()), before)
                self.assertFalse((h.f.run_dir / 'workflow.js').exists())
                self.save(h.f.root, terminal + '-healthy', {'input': h.f.manifest,
                    'terminal_state': terminal, 'resource_view': view['resource_view'], 'error': error,
                    'remaining_rounds': view['remaining_rounds'], 'ledger': before})
                # Disable ONLY the actual common policy gate; round/resource checks stay real.
                self.mutate(h.mod, '_require_dispatch_policy',
                    '    if (view["remaining_rounds"] <= 0 or',
                    '    if False and (view["remaining_rounds"] <= 0 or', h.f.root, terminal)
                receipt = h.mod.build(h.f.repo, h.f.manifest_path, h.f.run_dir)
                if receipt is None:
                    self.fail('QA_B2_MUTANT_RECEIPT_REQUIRED')
                self.assertFalse(receipt['resume_only'])
                events = [json.loads(p.read_bytes()) for p in sorted((h.f.scope() / 'events').glob('*.json'))]
                self.assertEqual(events[-1]['kind'], 'reserve')
                self.assertEqual(events[-1]['payload']['identity']['client_round_id'], h.f.manifest['client_round_id'])
                after = self.snapshot(h.f.scope())
                def refuse_new_reservation():
                    self.assertEqual(after, before, 'QA_B2_POLICY_NO_RESERVE')
                with self.assertRaisesRegex(AssertionError, 'QA_B2_POLICY_NO_RESERVE') as caught:
                    refuse_new_reservation()
                self.save(h.f.root, terminal + '-caught', {'receipt': receipt, 'last_event': events[-1],
                    'before': before, 'after': after, 'error_code': None, 'assertion': str(caught.exception),
                    'status': 'CAUGHT', 'workflow_exists': (h.f.run_dir / 'workflow.js').exists()})

    def test_exact_scope_normalization_source_mutant(self):
        k = self.fixture(_CanonicalPolicyFixture())
        scopes = [' Scope ', 'Scope', 'scope', 'Ｓcope', 'Café', 'Café']
        findings = [_CanonicalPolicyFixture.finding(scope=scope) for scope in scopes]
        attempt = k.facts(1, (1, 2), {1: findings, 2: copy.deepcopy(findings)})
        roles = attempt['audit']['roles']
        expected_keys = sorted([['issue', 'minor', 'implementation', scope] for scope in scopes])
        def check(value):
            self.assertEqual(value['comparison_keys'], expected_keys, 'QA_B2_EXACT_SCOPE_KEYS')
            self.assertEqual(len(value['conclusions']), len(scopes), 'QA_B2_EXACT_SCOPE_BUCKETS')
            by_scope = {c['scope']: c for c in value['conclusions']}
            self.assertEqual(set(by_scope), set(scopes), 'QA_B2_EXACT_SCOPE_BUCKETS')
            for scope in scopes:
                conclusion = by_scope[scope]
                self.assertEqual(conclusion['found_by'], [roles[1]['role_id'], roles[2]['role_id']])
                self.assertEqual(len(conclusion['variants']), 1)
                members = conclusion['variants'][0]['members']
                self.assertEqual([(m['role_index'], m['finding_index']) for m in members],
                                 [(1, scopes.index(scope)), (2, scopes.index(scope))],
                                 'QA_B2_EXACT_SCOPE_MEMBERS')
                self.assertEqual(conclusion['variants'][0]['finding']['scope'], scope)
        healthy = k.mod._aggregate_admitted(roles)
        check(healthy)
        self.save(k.f.root, 'exact-scope-input', {'roles': roles, 'expected_keys': expected_keys})
        self.save(k.f.root, 'exact-scope-healthy', healthy)
        self.mutate(k.mod, '_aggregate_admitted',
            "            bucket = (finding['category'], finding['scope'])",
            "            bucket = (finding['category'], __import__('unicodedata').normalize('NFKC', finding['scope']).strip().casefold())",
            k.f.root, 'scope-normalization')
        bad = k.mod._aggregate_admitted(roles)
        self.save(k.f.root, 'exact-scope-mutant-output', bad)
        with self.assertRaisesRegex(AssertionError, 'QA_B2_EXACT_SCOPE_KEYS') as caught:
            check(bad)
        self.save(k.f.root, 'exact-scope-caught', {'status': 'CAUGHT', 'assertion': str(caught.exception),
            'error_code': None, 'expected_keys': expected_keys, 'actual_keys': bad['comparison_keys']})

    def test_pending_same_round_changed_client_cli_rejected(self):
        f = self.fixture(BuildContractTests())
        original_input = copy.deepcopy(f.manifest)
        response, receipt = self.cli(f)
        self.assertEqual(response.returncode, 0, response.stderr.decode())
        if receipt is None:
            self.fail('QA_B2_INITIAL_RECEIPT_REQUIRED')
        self.assertFalse(receipt['resume_only'])
        before = self.snapshot(f.repo / '.aria/audit-reports')
        response, resume = self.cli(f)
        self.assertEqual(response.returncode, 0, response.stderr.decode())
        if resume is None:
            self.fail('QA_B2_RESUME_RECEIPT_REQUIRED')
        self.assertTrue(resume['resume_only'])
        self.assertEqual(self.snapshot(f.repo / '.aria/audit-reports'), before)
        genesis_ref = ref(f.scope() / 'genesis.json')
        f.manifest['client_round_id'] = 'fresh-pending-client'
        f.manifest_path = f.repo / 'fresh-pending-client-manifest.json'
        f.run_dir = f.repo / '.aria/audit-reports/post_spec-R1-fresh-pending-client-build-target-aggregated'
        f.manifest['evidence']['cycle_origin'] = genesis_ref
        for key, basename in (('post_audit_index_path', 'audit-index.json'),
                              ('post_drift_index_path', 'drift-index.json'),
                              ('post_disposition_index_path', 'disposition-index.json')):
            f.manifest['evidence'][key] = str(f.run_dir / basename)
        # Correct existing origin and null previous pass scope_origin_or_head;
        # only pending_reservation_resume_only is the intended rejection.
        self.assertEqual(f.manifest['round'], original_input['round'])
        self.assertEqual(f.manifest['attempt_index'], original_input['attempt_index'])
        self.assertIsNone(f.manifest['evidence']['previous_round'])
        self.assertEqual(f.manifest['evidence']['policy_inputs'], original_input['evidence']['policy_inputs'])
        response, error = self.cli(f)
        self.assertNotEqual(response.returncode, 0)
        self.assertEqual(error['error_code'], 'E_RESOURCE_PENDING', 'QA_B2_PENDING_CLIENT')
        self.assertEqual(error['reason'], 'pending_reservation_resume_only')
        self.assertEqual(self.snapshot(f.repo / '.aria/audit-reports'), before, 'QA_B2_PENDING_NO_WRITES')
        self.assertFalse((f.run_dir / 'workflow.js').exists())
        events = [json.loads(p.read_bytes()) for p in (f.scope() / 'events').glob('*.json')]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['kind'], 'reserve')
        self.assertEqual(events[0]['payload']['identity']['client_round_id'], original_input['client_round_id'])
        self.save(f.root, 'pending-client-rejection', {'initial_input': original_input,
            'initial_receipt': receipt, 'original_client_resume': resume, 'rejected_input': f.manifest,
            'error': error, 'returncode': response.returncode, 'before': before,
            'after': self.snapshot(f.repo / '.aria/audit-reports'), 'reservation_count': 1,
            'workflow_dispatched': False, 'new_workflow_exists': False})


if __name__ == '__main__':
    unittest.main()
