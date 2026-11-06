"""独立 QA 负控：先验证当前代码，再仅在隔离源副本注入指定故障。

不运行 Workflow/LLM，不修改产品源。公开工具仅用于临时仓构造，不继承或
执行实现作者的测试。预期来自 SC 与契约，所有断言及 JS 宿主由本测试独立写。
ARIA_NEGATIVE_EVIDENCE_DIR 可保留全部原始 fixture/源码/输出；默认自动清理。
"""
from __future__ import annotations

import copy
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("qa_public_constructors", HERE / "test_audit_executor.py")
assert spec is not None and spec.loader is not None
constructors = importlib.util.module_from_spec(spec)
spec.loader.exec_module(constructors)
FIXTURE = json.loads((HERE / "fixtures/audit_executor/negative-controls.json").read_text())
EVIDENCE_ENV = "ARIA_NEGATIVE_EVIDENCE_DIR"


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_ref(path):
    return {"path": str(path), "sha256": digest(path.read_bytes())}


# 独立受控宿主：每一个 agent Promise 都进入 pending，不用 worker 数代替物理调用数。
# Date/performance/timers/微任务与 Promise 终态全部显式控制；没有 wall-clock 等待。
HOST = r"""
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
let clock = 0, serial = 0, peak = 0, done = false, output = null, failure = null;
const timers = new Map(), pending = new Map(), calls = [], snapshots = [];
const drain = async () => { for (let n=0;n<128;n++) await Promise.resolve(); };
class FrozenDate extends Date {
  constructor(...a) { super(...(a.length ? a : [clock])); }
  static now() { return clock; }
}
const sandbox = vm.createContext({
  args:input.args, Date:FrozenDate, performance:{now:()=>clock},
  Math:Object.assign(Object.create(Math), {random(){throw Error('unexpected entropy');}}),
  phase:()=>{}, log:()=>{},
  setTimeout:(fn,ms)=>{const id=++serial;timers.set(id,{at:clock+ms,fn});return id;},
  clearTimeout:id=>timers.delete(id),
  agent:(prompt,options)=>{
    const id=calls.length;
    calls.push({id,at:clock,options,returned:false});
    return new Promise(resolve=>{
      pending.set(id,()=>{pending.delete(id);calls[id].returned=true;resolve('controlled raw');});
      peak=Math.max(peak,pending.size);
    });
  }
});
const running=vm.runInContext('(async()=>{'+input.script.replace(/^export /,'')+'\n})()',sandbox,{timeout:1000});
running.then(v=>{done=true;output=v;},e=>{done=true;failure=String(e);});
const snap=()=>snapshots.push({at:clock,pending:[...pending.keys()],peak,call_count:calls.length,done,
                             timer_count:timers.size,failure,output});
async function advance(end) {
  for (;;) {
    const due=[...timers].filter(x=>x[1].at<=end).sort((a,b)=>a[1].at-b[1].at||a[0]-b[0])[0];
    if (!due) break;
    timers.delete(due[0]);clock=due[1].at;due[1].fn();await drain();
  }
  clock=end;await drain();snap();
}
(async()=>{
  await drain();snap();await advance(120000);await advance(300000);
  const beforeLate=calls.length;
  for (const resolve of [...pending.values()]) resolve();
  await drain();snap();
  process.stdout.write(JSON.stringify({clock_source:'fully_controlled',snapshots,calls,peak,
    final_pending:pending.size,late_dispatch:calls.length-beforeLate,failure}));
})().catch(e=>{process.stderr.write(String(e));process.exitCode=1;});
"""


class NegativeControlTests(unittest.TestCase):
    def setUp(self):
        self.record = {"test": self.id(), "execution_identity": {
            "role": "fresh_aria_qa_engineer_TASK011", "pid": os.getpid(),
            "implementation_author": False, "source": "independently authored from TASK-011 and contract"},
            "cases": []}
        value = os.environ.get(EVIDENCE_ENV)
        self.evidence = Path(value).resolve() / self._testMethodName if value else None
        if self.evidence:
            self.evidence.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self.write_record)

    def write_record(self):
        if self.evidence:
            (self.evidence / "evidence.json").write_bytes(encode(self.record))

    def case(self, name, mutations=()):
        # 公开 helper 只构造隔离仓，不注册/调用它的任何 test_* 方法。
        f = constructors.BuildContractTests("runTest")
        previous = tempfile.tempdir
        if self.evidence:
            tempfile.tempdir = str(self.evidence)
        try:
            f.setUp()
        finally:
            tempfile.tempdir = previous
        if self.evidence:
            # 留住源码闭包及原路径，不能清理后留下悬空证据引用。
            f.tmp._finalizer.detach()
            f._cleanups.clear()
        else:
            self.addCleanup(f.doCleanups)
        source = f.engine / "scripts/audit_executor.py"
        original = source.read_bytes()
        changed = original.decode()
        for patch in mutations:
            self.assertEqual(changed.count(patch["old"]), 1, "mutation anchor must be unique")
            changed = changed.replace(patch["old"], patch["new"], 1)
        source.write_bytes(changed.encode())
        # 编译检查先于行为实验；语法/导入失败绝不记 CAUGHT。
        compile(changed, str(source), "exec")
        # 同长度源码替换可能命中同秒生成的旧 pyc，必须执行本次实际字节。
        for cached in source.parent.glob("__pycache__/audit_executor.*.pyc"):
            cached.unlink()
        f.mod = constructors.load_module(source)
        item = {"name": name, "fixture_root": str(f.root), "source": str(source),
                "original_sha256": digest(original), "executed_sha256": digest(source.read_bytes()),
                "source_diff": "".join(difflib.unified_diff(original.decode().splitlines(True),
                    changed.splitlines(True), fromfile="correct/audit_executor.py", tofile="fault/audit_executor.py")),
                "outcome": "NOT-JUDGED"}
        if self.evidence:
            stem = self.evidence / name
            stem.with_suffix(".original.py").write_bytes(original)
            stem.with_suffix(".executed.py").write_bytes(source.read_bytes())
            stem.with_suffix(".diff").write_text(item["source_diff"])
        self.record["cases"].append(item)
        return f, item

    def judge(self, item, assertion, verify, *, fault):
        item["designated_assertion"] = assertion
        if fault:
            # 只接受已执行到指定业务断言的 AssertionError，不接收上游崩溃。
            with self.assertRaisesRegex(AssertionError, assertion) as caught:
                verify()
            item.update(outcome="CAUGHT", exception_type="AssertionError", assertion_error=str(caught.exception))
        else:
            verify()
            item["outcome"] = "GREEN"

    def require(self, condition, code, value):
        self.assertTrue(condition, code + ": " + repr(value))

    def pair(self, f, admitted_before, admitted_after):
        results = []
        for number, admitted in [(1, admitted_before), (2, admitted_after)]:
            identity = {k: f.manifest[k] for k in f.mod.IDENTITY_KEYS}
            identity.update(round=number, client_round_id=f"qa-round-{number}")
            raw_path = f.root / f"qa-raw-{number}.json"
            report = {"vote": "PASS", "coverage_complete": True,
                "findings": [{"type": "issue", "severity": "minor", "category": "testing",
                              "scope": "boundary.py", "summary": "same claim", "file": "boundary.py",
                              "line": 9, "failure_scenario": "same key across changed participants"}],
                "pending": [], "prior_findings": []}
            raw = encode(report).decode()
            f.write(raw_path, {"raw": raw})
            rows = []
            for i, configured in enumerate(f.manifest["roles"]):
                node = {"type": "workflow_agent", "agentId": f"qa-{number}-{i}",
                    "agentType": configured["agentType"], "label": f"qa-{number}-{i}", "model": None,
                    "queuedAt": 5000, "startedAt": 5000, "durationMs": 7, "state": "done"}
                classified = f.mod._classify_seat(5000, node if i in admitted else None,
                                                 raw if i in admitted else None)
                rows.append({"index": i, "role_id": configured["role_id"], **classified,
                    "raw_ref": {"file": file_ref(raw_path), "pointer": "/raw"} if i in admitted else None})
            results.append({"identity": identity, "roles": rows})
        return results

    def role_shape(self, shape):
        vector = FIXTURE["shapes"][shape]
        for fault in (False, True):
            f, item = self.case("fault" if fault else "correct", vector["mutations"] if fault else ())
            previous, current = self.pair(f, vector["previous_roles"], vector["current_roles"])
            value = f.mod._compare_rounds(current, previous, True)
            item.update(branch="_classify_seat -> _compare_rounds", inputs={"previous": previous, "current": current},
                        actual=value)
            self.assertTrue(value["conclusion_keys_equal"], "fixture must reach equal-key branch")
            if shape == "ignore_roles":
                def verify():
                    self.require(not value["conclusions_stable"] and not value["converged"] and
                                 value["population_reason"] == "population_changed", vector["assertion"], value)
            else:
                self.assertEqual(len(vector["previous_roles"]), len(vector["current_roles"]))
                self.assertEqual(len(set(vector["previous_roles"]) & set(vector["current_roles"])), 1)
                def verify():
                    self.require(value["population_comparable"] is False and
                                 value["population_reason"] == "population_changed", vector["assertion"], value)
            self.judge(item, vector["assertion"], verify, fault=fault)
            if not fault:
                legacy = f.mod._compare_rounds(current, previous, False)
                self.assertTrue(legacy["converged"], "disabled guard must preserve legacy formula")
                same = f.mod._compare_rounds(current, {**previous, "roles": copy.deepcopy(current["roles"])}, True)
                self.assertTrue(same["converged"], "same nonempty partial population may converge")
                self.assertTrue(same["incomplete"], "do not add a full-team gate")

    def test_ignore_roles(self):
        self.role_shape("ignore_roles")

    def test_cardinality_only(self):
        self.role_shape("cardinality_only")

    def test_release_without_cancel(self):
        vector = FIXTURE["shapes"]["release_without_cancel"]
        for fault in (False, True):
            f, item = self.case("fault" if fault else "correct", vector["mutations"] if fault else ())
            fourth = {"role_id": "qa:fourth", "agentType": "qa:fourth", "model_alias": "inherit", "prompt": "fourth"}
            f.manifest["roles"].append(fourth)
            f.config_value["audit"]["teams"]["post_spec"].append(fourth["role_id"])
            f.write(f.config, f.config_value)
            f.build()
            script = (f.run_dir / "workflow.js").read_text()
            build = f.record()
            payload = {"script": script, "args": {"identity": build["identity"],
                                                 "manifest_sha256": build["manifest"]["sha256"]}}
            response = subprocess.run(["node", "-e", HOST], input=encode(payload), capture_output=True, timeout=15)
            self.assertEqual(response.returncode, 0, response.stderr.decode())
            value = json.loads(response.stdout)
            self.assertIsNone(value["failure"], "JS must not crash before designated assertion")
            self.assertEqual(value["snapshots"][0]["pending"], [0, 1])
            self.assertEqual(value["final_pending"], 0, "host must settle every real agent Promise")
            self.assertEqual(value["late_dispatch"], 0)
            self.assertEqual(value["peak"], vector["expected_fault_peak"] if fault else vector["expected_correct_peak"])
            self.assertEqual(value["snapshots"][1]["at"], 120000)
            self.assertEqual(len(value["snapshots"][1]["pending"]), 4 if fault else 2)
            item.update(branch="build -> generated workflow.js -> isolated Node vm", actual=value,
                        generated_script_sha256=digest(script.encode()), host_sha256=digest(HOST.encode()))
            if self.evidence:
                (self.evidence / ("fault-host.json" if fault else "correct-host.json")).write_bytes(encode(value))
                (self.evidence / "controlled-host.js").write_text(HOST)
            self.judge(item, vector["assertion"], lambda: self.require(value["peak"] <= 2,
                       vector["assertion"], value["peak"]), fault=fault)

    def capture_native(self, f):
        build = f.record()
        run_id = "qa-independent-" + f.manifest["client_round_id"]
        nodes, seats = [], []
        for i, role in enumerate(build["roles"]):
            report = {"vote": "PASS", "coverage_complete": True, "findings": [], "pending": [], "prior_findings": []}
            nodes.append({"type": "workflow_agent", "agentId": f"{run_id}-{i}", "agentType": role["agentType"],
                "label": role["label"], "model": "synthetic-no-backend", "queuedAt": 20000 + i * 20,
                "startedAt": 20000 + i * 20, "durationMs": 5, "state": "done"})
            seats.append({**{k: role[k] for k in ("index", "role_id", "agentType", "label")},
                          "attempted": True, "settled": True, "raw": encode(report).decode(), "error": None})
        native_path = f.run_dir / "qa-native.json"
        f.write(native_path, {"runId": run_id, "startTime": 20000, "durationMs": 1000, "status": "completed",
            "agentCount": len(nodes), "script": (f.run_dir / "workflow.js").read_text(),
            "args": {"identity": build["identity"], "manifest_sha256": build["manifest"]["sha256"]},
            "workflowProgress": nodes, "result": {"schema_version": 1, "identity": build["identity"],
                "manifest_sha256": build["manifest"]["sha256"], "results": seats,
                "control": {"round_timer_ms": 300000, "stop_observed": False, "return_reason": "all_settled"}}})
        f.write(f.run_dir / "audit-index.json", {"schema_version": 1, "identity": build["identity"],
            "attempt_index": build["attempt_index"], "workflow_run_id": run_id,
            "native_record": file_ref(native_path), "termination_refs": []})
        return run_id, native_path

    def cli(self, f, run_id, native_path, *extra):
        output = f.run_dir / (f.run_dir.name + ".json")
        command = [sys.executable, "-I", str(f.engine / "scripts/audit_executor.py"), "collect",
            "--repo-path", str(f.repo), "--manifest", str(f.manifest_path), "--build-record",
            str(f.run_dir / "build-record.json"), "--workflow-run-id", run_id,
            "--native-record", str(native_path), "--output", str(output), *map(str, extra)]
        response = subprocess.run(command, capture_output=True, cwd=f.root, timeout=30)
        record = {"command": command, "returncode": response.returncode,
                  "stdout": response.stdout.decode(), "stderr": response.stderr.decode()}
        return response, record

    def test_tampered_result(self):
        vector = FIXTURE["shapes"]["tampered_result"]
        for fault in (False, True):
            f, item = self.case("fault" if fault else "correct", vector["mutations"] if fault else ())
            f.build()
            run_id, native = self.capture_native(f)
            item["commands"] = []
            for extra in [("--prepare-policy",), ()]:
                response, command = self.cli(f, run_id, native, *extra)
                item["commands"].append(command)
                self.assertEqual(response.returncode, 0, response.stderr.decode())
            output = f.run_dir / (f.run_dir.name + ".json")
            report = output.with_suffix(".md")
            report_before = report.read_bytes(), report.stat().st_mtime_ns
            original = output.read_bytes()
            response, command = self.cli(f, run_id, native, "--check-result", output)
            item["commands"].append(command)
            self.assertEqual(response.returncode, 0, response.stderr.decode())
            item["variants"] = []
            for field in vector["fields"]:
                value = json.loads(original)
                value[field] = not value[field] if field == "converged" else value[field][1:]
                f.write(output, value)
                snapshot = {str(p): (digest(p.read_bytes()), p.stat().st_mtime_ns)
                            for p in f.root.rglob("*") if p.is_file()}
                response, command = self.cli(f, run_id, native, "--check-result", output)
                item["commands"].append(command)
                after = {str(p): (digest(p.read_bytes()), p.stat().st_mtime_ns)
                         for p in f.root.rglob("*") if p.is_file()}
                self.assertEqual(after, snapshot, "check-result must never modify report/result/history")
                self.assertEqual((report.read_bytes(), report.stat().st_mtime_ns), report_before)
                if not fault:
                    self.assertEqual(json.loads(response.stderr)["error_code"], "E_RESULT_MISMATCH")
                variant = {"field": field, "actual_returncode": response.returncode,
                    "report_unchanged": True, "entire_fixture_unchanged": True,
                    "tampered_result_sha256": digest(output.read_bytes())}
                item["variants"].append(variant)
                self.judge(variant, vector["assertion"], lambda: self.require(response.returncode != 0,
                           vector["assertion"], response.returncode), fault=fault)
                if self.evidence:
                    (self.evidence / (("fault-" if fault else "correct-") + field + ".json")).write_bytes(output.read_bytes())
                output.write_bytes(original)
            item.update(outcome="CAUGHT" if fault else "GREEN", branch="CLI collect --check-result -> _collect_final",
                        designated_assertion=vector["assertion"], report_sha256=digest(report.read_bytes()))

    def test_missing_evidence_fallback_false(self):
        vectors = FIXTURE["shapes"]["missing_evidence_fallback_false"]["variants"]
        for variant, vector in vectors.items():
            for fault in (False, True):
                f, item = self.case(variant + ("-fault" if fault else "-correct"), vector["mutations"] if fault else ())
                if variant == "missing_native":
                    f.build()
                    run_id, native = self.capture_native(f)
                    native.unlink()
                    response, command = self.cli(f, run_id, native, "--prepare-policy")
                    item.update(branch="CLI collect --prepare-policy -> strict native evidence -> error handler",
                                actual=command)
                    if not fault:
                        self.assertEqual(json.loads(response.stderr)["error_code"], "E_NATIVE_EVIDENCE")
                    verify = lambda: self.require(response.returncode != 0, vector["assertion"], response.returncode)
                elif variant == "invalid_guard":
                    f.config_value["audit"]["require_same_admitted_roles"] = "false"
                    f.write(f.config, f.config_value)
                    outcome = {"error_code": None}
                    try:
                        value = f.mod._load_fixed_policy(f.repo)
                        outcome["returned_guard"] = value["require_same_admitted_roles"]
                    except f.mod.ExecutorError as error:
                        outcome["error_code"] = error.error_code
                    item.update(branch="_load_fixed_policy raw guard validation", actual=outcome)
                    verify = lambda: self.require(outcome["error_code"] == "E_CONFIG_TYPE", vector["assertion"], outcome)
                else:
                    previous, current = self.pair(f, [0], [0])
                    old = {"identity": previous["identity"], "comparison_keys": [["issue", "minor", "qa", "boundary.py"]]}
                    outcomes = [f.mod._compare_rounds(current, legacy, True)
                                for legacy in (old, {"comparison_keys": old["comparison_keys"]})]
                    item.update(branch="_compare_rounds legacy missing participant evidence (diagnostic, not blanket rejection)",
                                actual=outcomes)
                    verify = lambda: self.require(all(v["population_comparable"] is False and
                        not v["conclusions_stable"] and not v["converged"] and
                        v["population_reason"] == "missing_participant_evidence" for v in outcomes),
                        vector["assertion"], outcomes)
                self.judge(item, vector["assertion"], verify, fault=fault)


if __name__ == "__main__":
    unittest.main()
