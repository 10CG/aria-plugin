"""TASK-007 transaction RED, isolated from the later build/replay gates.

A missing consumer is an assertion failure, not evidence that any business
negative was caught. All carrier data and the old reserve are synthetic.
"""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

_spec = importlib.util.spec_from_file_location(
    "transaction_fixture_support", Path(__file__).with_name("pre_dispatch_recovery_fixtures.py"))
assert _spec is not None and _spec.loader is not None
support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(support)


def association(f, dimension):
    """Generate a real unknown call with one independent matching dimension.

    Path equality necessarily implies bytes equality; full identity necessarily
    implies cycle equality. Those logical implications are not extra bypasses.
    """
    f.restore_authorities()
    different = f.repo / "unrelated.js"
    different.write_bytes(b"unrelated synthetic workflow")
    copied = f.repo / "same-script-bytes.js"
    copied.write_bytes(f.script_path.read_bytes())
    f.append_workflow(status="unknown", related=False)
    call = f.rows[-1]["message"]["content"][0]["input"]
    if dimension == "script_path":
        call["scriptPath"] = str(f.script_path)
    elif dimension == "script_hash":
        call["scriptPath"] = str(copied)
    elif dimension == "manifest":
        call["args"]["manifest_sha256"] = f.record["manifest"]["sha256"]
    elif dimension == "identity":
        call["args"]["identity"] = copy.deepcopy(f.record["identity"])
    elif dimension == "cycle":
        call["args"]["identity"]["audit_cycle_id"] = f.record["identity"]["audit_cycle_id"]
    else:
        raise AssertionError(dimension)
    f._write_native()
    return call


def add_second_reserve(f):
    """Real event envelope and valid FileRef chain, invalid two-pending prefix."""
    first = json.loads(f.event_paths()[0].read_bytes())
    second = copy.deepcopy(first)
    second.update(seq=2, previous_event=support.file_ref(f.event_paths()[0]))
    path = f.scope / "events" / "0000000002.json"
    support.write_json(path, second)
    return path


def add_observe_head(f):
    """Change the live head with a valid observe, not a malformed second reserve."""
    raw = support.encode({"schema_version": 1, "observations": []})
    blob = f.scope / "blobs" / (support.digest(raw) + ".blob")
    blob.write_bytes(raw)
    event = {"schema_version": 1, "seq": 2, "genesis": f.binding["genesis"],
             "previous_event": f.binding["reservation"], "kind": "observe",
             "payload": {"preflight": support.file_ref(blob)}}
    path = f.scope / "events" / "0000000002.json"
    support.write_json(path, event)
    return support.file_ref(path)


def add_audit_index_with_missing_native(f):
    """Contract §10.4 audit index points at a genuinely unreadable export."""
    index = Path(f.manifest["evidence"]["post_audit_index_path"])
    missing = f.run_dir / "missing-native-export.json"
    support.write_json(index, {"schema_version": 1, "identity": copy.deepcopy(f.record["identity"]),
                              "attempt_index": 1, "workflow_run_id": "synthetic-run",
                              "native_record": {"path": str(missing), "sha256": support.digest(b"synthetic export")},
                              "termination_refs": []})
    return index, missing


def contradictory_audit_native(f, *, index_run="run-other", native_run="run-other", related=False):
    """Complete Workflow JSON under a target-bound audit index, never executed."""
    native = {"runId": native_run, "status": "completed",
              "script": f.script_path.read_text() if related else "unrelated synthetic script",
              "args": {"identity": copy.deepcopy(f.record["identity"]) if related else {"audit_cycle_id": "other-cycle"},
                       "manifest_sha256": f.record["manifest"]["sha256"] if related else "f" * 64},
              "workflowProgress": [], "result": {}, "startTime": 1000, "durationMs": 1, "agentCount": 0}
    export = f.run_dir / "independent-export.json"
    native_ref = support.write_json(export, native)
    index = Path(f.manifest["evidence"]["post_audit_index_path"])
    support.write_json(index, {"schema_version": 1, "identity": copy.deepcopy(f.record["identity"]),
                               "attempt_index": 1, "workflow_run_id": index_run,
                               "native_record": native_ref, "termination_refs": []})
    return index, export


def progress_row(f, field, has_run=True, *, root=None, row_type="progress", target=True):
    target_id = "call_fixture_rejection" if target else "unrelated-call"
    data: dict[str, object] = {"type": "workflow_progress"}
    if field == "wireToolInputs":
        data[field] = {target_id: {}}
    else:
        data[field] = target_id
    if has_run:
        data["runId"] = "synthetic-run"
    row = {"type": row_type, "sessionId": (root or f.native_path).stem, "data": data}
    return row


def install_recursive_native(f, mod, dimension, *, depth=1, envelope="progress"):
    """Create readable Workflow JSON references without invoking Workflow."""
    target = "call_fixture_rejection"
    def native(run):
        return {"runId": run, "status": "completed", "script": "foreign script",
                "args": {"identity": {"audit_cycle_id": "other-cycle"}, "manifest_sha256": "f" * 64},
                "workflowProgress": [], "result": {}, "startTime": 1000, "durationMs": 1, "agentCount": 0}
    body = native("nested-run" if depth == 2 else "synthetic-run")
    if dimension in ("id", "tool_use_id", "toolUseID", "toolUseId"):
        body[dimension] = target
    elif dimension == "wireToolInputs":
        body[dimension] = {target: {}}
    elif dimension == "script_path":
        body["scriptPath"] = str(f.script_path)
    elif dimension == "script_hash":
        copied = f.repo / "copy-of-old-script.js"
        copied.write_bytes(f.script_path.read_bytes())
        assert copied != f.script_path and support.digest(copied.read_bytes()) == f.record["workflow_script"]["sha256"]
        body["scriptPath"] = str(copied)
    elif dimension == "cycle":
        body["args"]["identity"]["audit_cycle_id"] = f.record["identity"]["audit_cycle_id"]
    elif dimension != "unrelated":
        raise AssertionError(dimension)
    ref = support.write_json(f.repo / "recursive-native-leaf.json", body)
    natives = [(body, ref)]
    if depth == 2:
        parent = native("synthetic-run")
        parent["result"] = {"workflow_run_id": "nested-run", "native_record": ref, "termination_refs": []}
        ref = support.write_json(f.repo / "recursive-native-parent.json", parent)
        natives.append((parent, ref))
    for index, (expected, native_ref) in enumerate(natives):
        preflight = f.repo / ("recursive-health-" + str(index) + ".json")
        pre_ref = support.write_json(preflight, {"schema_version": 1, "observations": [{
            "workflow_run_id": expected["runId"], "native_record": native_ref, "termination_refs": []}]})
        _, observed = mod._read_preflight(pre_ref, preflight, mod._Inputs())
        assert observed[0]["native"] == expected
        assert native_ref == support.file_ref(Path(native_ref["path"]))
    root = f.native_path.with_name("66666666-7777-4888-8999-000000000000.jsonl")
    row = {"type": envelope, "sessionId": root.stem, "data": {
        "workflow_run_id": "synthetic-run", "native_record": ref, "termination_refs": []}}
    root.write_bytes(support.encode(row) + b"\n")
    return root


def install_typed_termination(f, mod, *, extra=None):
    """One unrelated native with a real, complete agent JSONL TerminationLink."""
    root = install_recursive_native(f, mod, "unrelated")
    row = json.loads(root.read_bytes())
    leaf = Path(row["data"]["native_record"]["path"])
    native = json.loads(leaf.read_bytes())
    agent, uid = "unrelated-agent", "unrelated-event"
    log = f.repo / "unrelated-agent.jsonl"
    event = {"type": "user", "agentId": agent, "uuid": uid,
             "message": {"role": "user", "content": "[Request interrupted by user]"}}
    rows = [event] + ([extra] if extra is not None else [])
    log.write_bytes(b"\n".join(support.encode(item) for item in rows) + b"\n")
    native["workflowProgress"] = [{"type": "workflow_agent", "agentId": agent,
        "agentType": "aria:qa-engineer", "label": "other", "model": None,
        "state": "progress", "queuedAt": 1000}]
    native["agentCount"] = 1
    row["data"]["native_record"] = support.write_json(leaf, native)
    row["data"]["termination_refs"] = [{"native_pointer": "/workflowProgress/0", "agent_id": agent,
        "event": {"file": support.file_ref(log), "line": 1, "agent_id": agent, "event_uuid": uid}}]
    root.write_bytes(support.encode(row) + b"\n")
    return root, leaf, log, row, native, event


def typed_preflight(f, mod, row):
    path = f.repo / "typed-health-preflight.json"
    ref = support.write_json(path, {"schema_version": 1, "observations": [row["data"]]})
    return mod._read_preflight(ref, path, mod._Inputs())[1][0]


class FixtureHealth(unittest.TestCase):
    def test_typed_termination_real_bindings(self):
        f = support.RecoveryFixture()
        self.addCleanup(f.close)
        mod = support.load_module(f.executor)
        root, leaf, log, row, native, event = install_typed_termination(f, mod)
        observed = typed_preflight(f, mod, row)
        link = row["data"]["termination_refs"][0]
        self.assertEqual(observed["native"], native)
        self.assertEqual(row["data"]["native_record"], support.file_ref(leaf))
        self.assertEqual(link["event"]["file"], support.file_ref(log))
        self.assertEqual(json.loads(log.read_bytes().splitlines()[link["event"]["line"] - 1]), event)
        self.assertEqual((link["agent_id"], link["event"]["agent_id"], event["agentId"]), ("unrelated-agent",) * 3)
        self.assertEqual(link["event"]["event_uuid"], event["uuid"])
        self.assertEqual(event["message"], {"role": "user", "content": "[Request interrupted by user]"})
        self.assertEqual(native["workflowProgress"][0]["agentId"], link["agent_id"])
        self.assertEqual(observed["terminations"]["/workflowProgress/0"], link["event"])
        self.assertTrue(log.is_relative_to(f.repo))
        self.assertNotEqual(root.parent, log.parent)


    def test_association_dimensions_are_real_and_independent(self):
        f = support.RecoveryFixture()
        self.addCleanup(f.close)
        identity = f.record["identity"]
        for dimension in ("script_path", "script_hash", "manifest", "identity", "cycle"):
            with self.subTest(dimension=dimension):
                call = association(f, dimension)
                path = Path(call["scriptPath"])
                self.assertTrue(path.is_file())
                matches = {
                    "script_path": path == f.script_path,
                    "script_hash": support.digest(path.read_bytes()) == support.digest(f.script_path.read_bytes()),
                    "manifest": call["args"]["manifest_sha256"] == f.record["manifest"]["sha256"],
                    "identity": call["args"]["identity"] == identity,
                    "cycle": call["args"]["identity"]["audit_cycle_id"] == identity["audit_cycle_id"],
                }
                expected = {dimension}
                if dimension == "script_path":
                    expected.add("script_hash")
                if dimension == "identity":
                    expected.add("cycle")
                self.assertEqual({key for key, value in matches.items() if value}, expected)
                self.assertEqual(support.digest(f.manifest_path.read_bytes()), f.record["manifest"]["sha256"])
                self.assertEqual(json.loads(f.native_path.read_bytes().splitlines()[-1])["message"]["content"][0]["input"], call)

    def test_audit_index_names_actual_missing_workflow_export(self):
        f = support.RecoveryFixture()
        self.addCleanup(f.close)
        index, missing = add_audit_index_with_missing_native(f)
        obj = json.loads(index.read_bytes())
        self.assertEqual(set(obj), {"schema_version", "identity", "attempt_index", "workflow_run_id", "native_record", "termination_refs"})
        self.assertEqual((obj["schema_version"], obj["identity"], obj["attempt_index"]), (1, f.record["identity"], f.record["attempt_index"]))
        self.assertEqual(obj["workflow_run_id"], "synthetic-run")
        self.assertEqual(obj["termination_refs"], [])
        self.assertEqual(set(obj["native_record"]), {"path", "sha256"})
        self.assertEqual(obj["native_record"]["path"], str(missing))
        self.assertRegex(obj["native_record"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertFalse(missing.exists())
        self.assertEqual(index, Path(f.manifest["evidence"]["post_audit_index_path"]))

    def test_real_pair_authorities_and_source_generations_are_usable(self):
        f = support.RecoveryFixture()
        self.addCleanup(f.close)
        with mock.patch.dict(os.environ, f.environment, clear=True):
            mod = support.load_module(f.executor)
            with mock.patch.object(mod, "_RUNTIME_REJECTION_PROFILES", f.runtime_profiles):
                plan, old, current = mod._recovery_source_generations(
                    f.repo, f.manifest_path, f.build_record_path, inputs=mod._Inputs())
                self.assertEqual(plan["from_sources"], f.old_sources)
                self.assertEqual(plan["to_sources"], f.current_sources)
                for name in ("executor", "contract"):
                    path = Path(f.old_sources[name]["path"])
                    self.assertEqual(support.digest(old.read(path)), f.old_sources[name]["sha256"])
                    self.assertEqual(support.digest(current.read(path)), f.current_sources[name]["sha256"])
                native = mod._parse_recovery_rejection(f.repo, f.manifest, f.record,
                                                       f.native_path, "call_fixture_rejection")
                self.assertIsInstance(native, dict)
                for method, path, decision in (
                    (mod._parse_operator_recovery_statement, f.operator_index, "confirm_local_domain"),
                    (mod._parse_evidence_acceptance, f.acceptance_index, "accept_boundary"),
                ):
                    self.assertEqual(method(f.repo, f.binding, path)["sourceData"]["decision"], decision)
        self.assertEqual(f.compat["to"]["executor"], support.digest(f.executor.read_bytes()))
        self.assertEqual(f.compat["to"]["contract"], support.digest(f.contract.read_bytes()))
        actual_catalog = json.loads((support.ENGINE / "references" / "pre-dispatch-recovery-compat.json").read_bytes())
        self.assertEqual(actual_catalog["to"]["executor"], support.digest(support.EXECUTOR.read_bytes()))
        self.assertEqual(actual_catalog["to"]["contract"], support.digest((support.ENGINE / "references" / "executor-contract.md").read_bytes()))
        self.assertEqual(actual_catalog["from"], f.compat["from"])
        self.assertEqual(len(f.event_paths()), 1)
        f.assert_old_unchanged(self)


    def test_foreign_workflow_export_has_complete_readable_native_schema(self):
        f = support.RecoveryFixture()
        self.addCleanup(f.close)
        index, export = contradictory_audit_native(f)
        value = json.loads(index.read_bytes())
        native = json.loads(export.read_bytes())
        self.assertEqual(value["identity"], f.record["identity"])
        self.assertEqual(value["attempt_index"], 1)
        self.assertEqual(value["workflow_run_id"], native["runId"])
        self.assertEqual(value["native_record"], support.file_ref(export))
        self.assertNotEqual(native["args"]["identity"], f.record["identity"])
        self.assertNotEqual(support.digest(native["script"].encode()), f.record["workflow_script"]["sha256"])
        preflight = f.repo / "health-preflight.json"
        ref = support.write_json(preflight, {"schema_version": 1, "observations": [{
            "workflow_run_id": native["runId"], "native_record": support.file_ref(export), "termination_refs": []}]})
        mod = support.load_module(f.executor)
        _, observed = mod._read_preflight(ref, preflight, mod._Inputs())
        self.assertEqual(observed[0]["native"], native)
        self.assertEqual(observed[0]["nodes"], {})

    def test_observe_changes_head_without_invalidating_pending_prefix(self):
        """The CAS fault must not rely on the multiple-pending rejection branch."""
        f = support.RecoveryFixture()
        self.addCleanup(f.close)
        with mock.patch.dict(os.environ, f.environment, clear=True):
            mod = support.load_module(f.executor)
            before = mod._load_scope(f.scope, f.manifest, mod._Inputs())
            self.assertEqual(before["head"], f.binding["head"])
            changed = add_observe_head(f)
            state = mod._load_scope(f.scope, f.manifest, mod._Inputs())
            self.assertEqual([row["event"]["kind"] for row in state["events"]],
                             ["reserve", "observe"])
            self.assertEqual(state["reserve_count"], 1)
            self.assertEqual(state["pending"]["ref"], f.binding["reservation"])
            self.assertEqual(state["head"], changed)
            self.assertNotEqual(state["head"], f.binding["head"])


class CliContract(unittest.TestCase):
    def test_recovery_command_and_flags_are_exposed(self):
        base = [sys.executable, "-I", str(support.EXECUTOR)]
        root = subprocess.run([*base, "--help"], capture_output=True, check=False)
        self.assertEqual(root.returncode, 0)
        self.assertIn("recover-dispatch-rejection", root.stdout.decode(),
                      "FEATURE_NOT_IMPLEMENTED_TDD_RED: CLI absent")
        detail = subprocess.run([*base, "recover-dispatch-rejection", "--help"], capture_output=True, check=False)
        self.assertEqual(detail.returncode, 0, "FEATURE_NOT_IMPLEMENTED_TDD_RED: CLI help absent")
        for flag in ("--repo-path", "--manifest", "--build-record", "--native-record", "--tool-use-id",
                     "--operator-index", "--evidence-acceptance-index", "--check-only", "--additional-source"):
            self.assertIn(flag, detail.stdout.decode(), "FEATURE_NOT_IMPLEMENTED_TDD_RED: " + flag)


    def test_recovery_dispatcher_missing_native_emits_executor_error_json(self):
        f = support.RecoveryFixture()
        self.addCleanup(f.close)
        result = subprocess.run([sys.executable, "-I", str(f.executor), "recover-dispatch-rejection",
            "--repo-path", str(f.repo), "--manifest", str(f.manifest_path),
            "--build-record", str(f.build_record_path), "--native-record", str(f.native_path.with_name("missing.jsonl")),
            "--tool-use-id", "call_fixture_rejection", "--operator-index", str(f.operator_index),
            "--evidence-acceptance-index", str(f.acceptance_index), "--check-only"],
            cwd=f.repo, env=f.environment, capture_output=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        try:
            error = json.loads(result.stderr)
        except (ValueError, UnicodeDecodeError):
            self.fail("FEATURE_NOT_IMPLEMENTED_TDD_RED: dispatcher did not emit ExecutorError JSON")
        self.assertEqual(set(error), {"error_code", "reason", "input_ref"})
        self.assertIn(error["error_code"], ("E_RECOVERY_EVIDENCE", "E_NATIVE_EVIDENCE"))
        self.assertTrue(error["reason"].startswith(("native_", "source_")), error["reason"])


class Transaction(unittest.TestCase):
    def setUp(self):
        visible = support.load_module(support.EXECUTOR)
        self.assertTrue(callable(getattr(visible, "recover_dispatch_rejection", None)),
                        "FEATURE_NOT_IMPLEMENTED_TDD_RED: module recovery consumer absent")
        self.assertTrue(hasattr(visible, "_RUNTIME_REJECTION_PROFILES"),
                        "FEATURE_NOT_IMPLEMENTED_TDD_RED: static runtime profile boundary absent")
        self.f = support.RecoveryFixture()
        self.addCleanup(self.f.close)
        env = mock.patch.dict(os.environ, self.f.environment, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.mod = support.load_module(self.f.executor)
        profiles = mock.patch.object(self.mod, "_RUNTIME_REJECTION_PROFILES", self.f.runtime_profiles)
        profiles.start()
        self.addCleanup(profiles.stop)

    def recover(self, *, check_only=False, additional_sources=()):
        f = self.f
        return self.mod.recover_dispatch_rejection(
            repo_path=f.repo, manifest_path=f.manifest_path, build_record_path=f.build_record_path,
            native_record_path=f.native_path, tool_use_id="call_fixture_rejection",
            operator_index=f.operator_index, evidence_acceptance_index=f.acceptance_index,
            check_only=check_only, additional_sources=tuple(additional_sources))

    def positive(self):
        before = support.tree_snapshot(self.f.root)
        result = self.recover(check_only=True)
        self.assertIs(result["eligible"], True)
        self.assertIs(result["would_append"], True)
        self.assertIsNone(result.get("event"))
        self.assertEqual(support.tree_snapshot(self.f.root), before)
        return result

    def refused(self, prefix, *, check_only=False, additional_sources=()):
        before = support.tree_snapshot(self.f.root)
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.recover(check_only=check_only, additional_sources=additional_sources)
        self.assertEqual(caught.exception.error_code, "E_RECOVERY_EVIDENCE")
        self.assertTrue(caught.exception.reason.startswith(prefix), caught.exception.reason)
        self.assertEqual(support.tree_snapshot(self.f.root), before)

    def test_check_only_never_needs_writer_lock_or_changes_tree(self):
        with mock.patch.object(self.mod, "_writer_lock", side_effect=AssertionError("lock unavailable")):
            self.positive()
        self.assertEqual(len(self.f.event_paths()), 1)

    def test_authority_missing_or_substituted_is_not_authority(self):
        self.positive()
        f = self.f
        for name, path, prefix in (("operator", f.operator_index, "operator_"),
                                   ("acceptance", f.acceptance_index, "evidence_acceptance_")):
            with self.subTest(kind=name, mutation="missing"):
                raw = path.read_bytes()
                path.unlink()
                try:
                    for check in (True, False):
                        self.refused(prefix, check_only=check)
                finally:
                    path.write_bytes(raw)
            with self.subTest(kind=name, mutation="other_index"):
                raw = path.read_bytes()
                other = f.acceptance_index if name == "operator" else f.operator_index
                path.write_bytes(other.read_bytes())
                try:
                    self.refused(prefix)
                finally:
                    path.write_bytes(raw)

    def test_decline_retain_and_global_fencing_rejected(self):
        self.positive()
        for kind, option, prefix in (("operator", 1, "operator_"), ("operator", 2, "operator_"),
                                     ("acceptance", 1, "evidence_acceptance_")):
            with self.subTest(kind=kind, option=option):
                self.f.restore_authorities()
                self.f.choose(kind, option)
                self.refused(prefix)

    def test_wrong_target_preview_template_and_api_copy(self):
        self.positive()
        for kind in ("operator", "acceptance"):
            prefix = "operator_" if kind == "operator" else "evidence_acceptance_"
            for mutation, expected in (("wrong_target", "target_"), ("preview", "target_"),
                                       ("template", prefix), ("api_copy", "native_")):
                with self.subTest(kind=kind, mutation=mutation):
                    self.f.restore_authorities()
                    if mutation == "wrong_target":
                        self.f.wrong_target(kind)
                    elif mutation in ("preview", "template"):
                        self.f.rewrite_template(kind, preview=mutation == "preview")
                    else:
                        self.f.api_copy(kind)
                    self.refused(expected)

    def test_locator_boolean_does_not_override_retain(self):
        self.positive()
        self.f.choose("acceptance", 1)
        index = json.loads(self.f.acceptance_index.read_bytes())
        index["approved"] = True
        support.write_json(self.f.acceptance_index, index)
        self.refused("evidence_acceptance_")

    def test_nonexact_error_or_unpaired_selected_request_stays_pending(self):
        self.positive()
        for value in ("timeout", "quoted: <tool_use_error>Workflow script file exceeds 524288 bytes</tool_use_error>"):
            with self.subTest(error=value):
                self.f.restore_authorities()
                self.f.rows[1]["message"]["content"][0]["content"] = value
                self.f.rows[1]["toolUseResult"] = "Error: " + value
                self.f._write_native()
                self.refused("native_")
        self.f.restore_authorities()
        del self.f.rows[1]
        self.f._write_native()
        self.refused("native_")

    def test_related_success_unknown_and_unrelated_success(self):
        self.positive()
        self.f.append_workflow(status="success", related=False)
        self.positive()
        for status in ("success", "unknown"):
            with self.subTest(status=status):
                self.f.restore_authorities()
                self.f.append_workflow(status=status)
                for check in (True, False):
                    self.refused("counterevidence", check_only=check)

    def test_explicit_root_scanned_and_missing_or_foreign_root_refused(self):
        self.positive()
        other = self.f.append_workflow(status="unknown", new_root=True)
        for check in (True, False):
            self.refused("counterevidence", check_only=check, additional_sources=(other,))
        for path in (other.with_name("missing.jsonl"), self.f.repo / "outside.jsonl"):
            with self.subTest(path=path.name):
                if path.parent == self.f.repo:
                    path.write_bytes(other.read_bytes())
                # Prefixes for newly introduced source errors are task-local pending implementation.
                before = support.tree_snapshot(self.f.root)
                with self.assertRaises(self.mod.ExecutorError) as caught:
                    self.recover(check_only=True, additional_sources=(path,))
                self.assertEqual(caught.exception.error_code, "E_RECOVERY_EVIDENCE")
                self.assertTrue(caught.exception.reason.startswith(("native_", "additional_source_")), caught.exception.reason)
                self.assertEqual(support.tree_snapshot(self.f.root), before)

    def test_each_independent_association_vetoes(self):
        self.positive()
        f = self.f
        for dimension in ("script_path", "script_hash", "manifest", "identity", "cycle"):
            with self.subTest(dimension=dimension):
                association(f, dimension)
                for check in (True, False):
                    self.refused("counterevidence", check_only=check)

    def test_existing_audit_index_missing_native_is_source_refusal(self):
        self.positive()
        index, missing = add_audit_index_with_missing_native(self.f)
        self.assertEqual(json.loads(index.read_bytes())["native_record"]["path"], str(missing))
        self.assertFalse(missing.exists())
        before = support.tree_snapshot(self.f.root)
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.recover()
        self.assertIn(caught.exception.error_code, ("E_NATIVE_EVIDENCE", "E_RECOVERY_EVIDENCE"))
        self.assertTrue(caught.exception.reason.startswith(("source_", "native_", "audit_index_")), caught.exception.reason)
        self.assertEqual(support.tree_snapshot(self.f.root), before)
        self.assertEqual(len(self.f.event_paths()), 1)

    def test_missing_scope_is_source_or_structural_refusal_without_bootstrap(self):
        self.positive()
        shutil.rmtree(self.f.scope)
        before = support.tree_snapshot(self.f.root)
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.recover()
        self.assertIn((caught.exception.error_code, caught.exception.reason),
                      (("E_POLICY_SOURCE", "source_unreadable"),
                       ("E_PREVIOUS_IDENTITY", "missing_genesis_with_history"),
                       ("E_RECOVERY_EVIDENCE", "scope_missing")))
        self.assertEqual(support.tree_snapshot(self.f.root), before)
        self.assertFalse(self.f.scope.exists())

    def test_manifest_build_and_script_bound_data_refused(self):
        """Reject broken real bindings, not unanchored JSON formatting changes."""
        self.positive()
        for name, path in (("manifest", self.f.manifest_path), ("build", self.f.build_record_path),
                           ("script", self.f.script_path)):
            with self.subTest(binding=name):
                raw = path.read_bytes()
                if name == "build":
                    # The old reserve binds manifest/script, not a self-hash of
                    # the subsequently published build record. Corrupt its
                    # actual manifest binding instead of guessing a raw anchor.
                    value = json.loads(raw)
                    value["manifest"]["sha256"] = "0" * 64
                    support.write_json(path, value)
                else:
                    path.write_bytes(raw + b" ")
                try:
                    before = support.tree_snapshot(self.f.root)
                    with self.assertRaises(self.mod.ExecutorError) as caught:
                        self.recover()
                    self.assertIn(caught.exception.error_code,
                                  ("E_POLICY_SOURCE", "E_PREVIOUS_IDENTITY", "E_RECOVERY_EVIDENCE", "E_NATIVE_EVIDENCE"))
                    self.assertTrue(caught.exception.reason.startswith(("source_hash_mismatch", "manifest_", "build_", "script_", "native_manifest_", "native_script_", "recovery_identity_manifest", "target_")), caught.exception.reason)
                    self.assertEqual(support.tree_snapshot(self.f.root), before)
                finally:
                    path.write_bytes(raw)

    def test_second_reserve_is_not_a_valid_initial_prefix(self):
        self.positive()
        add_second_reserve(self.f)
        before = support.tree_snapshot(self.f.root)
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.recover()
        self.assertEqual((caught.exception.error_code, caught.exception.reason), ("E_PREVIOUS_IDENTITY", "multiple_pending"))
        self.assertEqual(support.tree_snapshot(self.f.root), before)

    def test_locked_head_change_refused_without_transaction_write(self):
        self.positive()
        original_lock = self.mod._writer_lock
        injected = []

        @contextlib.contextmanager
        def inject_after_lock(scope):
            with original_lock(scope):
                add_second_reserve(self.f)
                injected.append(support.tree_snapshot(self.f.root))
                yield

        with mock.patch.object(self.mod, "_writer_lock", inject_after_lock):
            with self.assertRaises(self.mod.ExecutorError) as caught:
                self.recover()
        self.assertEqual(len(injected), 1)
        self.assertIn((caught.exception.error_code, caught.exception.reason),
                      (("E_PREVIOUS_IDENTITY", "multiple_pending"), ("E_PREVIOUS_IDENTITY", "event_chain"),
                       ("E_RECOVERY_EVIDENCE", "target_head_changed")))
        self.assertEqual(support.tree_snapshot(self.f.root), injected[0])
        self.assertEqual([json.loads(p.read_bytes())["kind"] for p in self.f.event_paths()], ["reserve", "reserve"])

    def test_locked_legal_observe_head_change_refuses_stale_target_without_writes(self):
        """Fail if locked recovery ignores a changed, structurally valid live head."""
        self.positive()
        original_lock = self.mod._writer_lock
        injected = []

        @contextlib.contextmanager
        def inject_after_lock(scope):
            with original_lock(scope):
                changed = add_observe_head(self.f)
                state = self.mod._load_scope(self.f.scope, self.f.manifest, self.mod._Inputs())
                self.assertEqual(state["head"], changed)
                self.assertEqual(state["pending"]["ref"], self.f.binding["reservation"])
                injected.append(support.tree_snapshot(self.f.root))
                yield

        with mock.patch.object(self.mod, "_writer_lock", inject_after_lock):
            with self.assertRaises(self.mod.ExecutorError) as caught:
                self.recover()
        self.assertEqual(len(injected), 1)
        self.assertEqual(caught.exception.error_code, "E_RECOVERY_EVIDENCE")
        self.assertTrue(caught.exception.reason.startswith("target_"), caught.exception.reason)
        self.assertEqual(support.tree_snapshot(self.f.root), injected[0])
        self.assertEqual([json.loads(p.read_bytes())["kind"] for p in self.f.event_paths()],
                         ["reserve", "observe"])

    def test_locked_revalidation_catches_new_unknown_without_transaction_write(self):
        self.positive()
        original_lock = self.mod._writer_lock
        injected = []

        @contextlib.contextmanager
        def inject_after_lock(scope):
            with original_lock(scope):
                self.f.append_workflow(status="unknown")
                injected.append(support.tree_snapshot(self.f.root))
                yield

        with mock.patch.object(self.mod, "_writer_lock", inject_after_lock):
            with self.assertRaises(self.mod.ExecutorError) as caught:
                self.recover()
        self.assertEqual(len(injected), 1, "must reach the real lock and inject before validation")
        self.assertEqual(caught.exception.error_code, "E_RECOVERY_EVIDENCE")
        self.assertTrue(caught.exception.reason.startswith("counterevidence"), caught.exception.reason)
        self.assertEqual(support.tree_snapshot(self.f.root), injected[0])
        self.assertEqual(len(self.f.event_paths()), 1)

    def test_mutation_has_one_closed_event_and_keeps_old_inputs(self):
        self.positive()
        f = self.f
        genesis_raw = Path(f.record["genesis"]["path"]).read_bytes()
        build_raw = f.build_record_path.read_bytes()
        scopes = {str(p.parent) for p in f.repo.rglob("genesis.json")}
        indexes = [Path(f.manifest["evidence"][key]) for key in
                   ("post_audit_index_path", "post_drift_index_path", "post_disposition_index_path")]
        self.assertTrue(all(not path.exists() for path in indexes))
        result = self.recover()
        self.assertTrue(all(not path.exists() for path in indexes))
        self.assertEqual({str(p.parent) for p in f.repo.rglob("genesis.json")}, scopes)
        self.assertEqual(Path(f.record["genesis"]["path"]).read_bytes(), genesis_raw)
        self.assertEqual(f.build_record_path.read_bytes(), build_raw)
        self.assertEqual(json.loads(genesis_raw)["initial_max_rounds"], json.loads(Path(f.record["genesis"]["path"]).read_bytes())["initial_max_rounds"])
        self.assertEqual(json.loads(build_raw)["budgets"], json.loads(f.build_record_path.read_bytes())["budgets"])
        self.assertIs(result["eligible"], True)
        ref = result["event"]
        self.assertEqual(support.file_ref(Path(ref["path"])), ref)
        events = f.event_paths()
        self.assertEqual(len(events), 2)
        event = json.loads(Path(ref["path"]).read_bytes())
        self.assertEqual(set(event), {"schema_version", "seq", "genesis", "previous_event", "kind", "payload"})
        self.assertEqual((event["seq"], event["kind"]), (2, "dispatch_rejected"))
        self.assertEqual(event["previous_event"], f.binding["head"])
        self.assertEqual(event["genesis"], f.binding["genesis"])
        payload = event["payload"]
        self.assertEqual(set(payload), {"reservation", "build_record", "evidence", "input_closure", "source_transition"})
        self.assertEqual(payload["reservation"], f.binding["reservation"])
        self.assertEqual(payload["build_record"], support.file_ref(f.build_record_path))
        self.assertEqual(json.loads(events[0].read_bytes())["kind"], "reserve")
        f.assert_old_unchanged(self)

    def test_frozen_evidence_sources_and_both_generations_read_actual_bytes(self):
        self.positive()
        f = self.f
        other = f.append_workflow(status="success", related=False, new_root=True)
        event_ref = self.recover(additional_sources=(other,))["event"]
        event = json.loads(Path(event_ref["path"]).read_bytes())
        payload = event["payload"]
        transition = payload["source_transition"]
        self.assertEqual(set(transition), {"compatibility_id", "compatibility_manifest", "from_sources", "to_sources", "new_source_closure"})
        self.assertEqual(transition["from_sources"], f.old_sources)
        self.assertEqual(transition["to_sources"], f.current_sources)
        def frozen(ref):
            self.assertEqual(support.file_ref(Path(ref["path"])), ref)
            return self.mod._history_closure(ref, Path(event_ref["path"]), f.scope,
                                             raw=Path(ref["path"]).read_bytes())
        old = frozen(f.old_closure)
        new = frozen(transition["new_source_closure"])
        evidence_inputs = frozen(payload["input_closure"])
        genesis = json.loads(Path(f.record["genesis"]["path"]).read_bytes())
        for name in f.old_sources:
            path = Path(f.old_sources[name]["path"])
            old_bytes = old.read(path)
            self.assertEqual(support.digest(old_bytes), f.old_sources[name]["sha256"])
            self.assertEqual(support.digest(new.read(path)), f.current_sources[name]["sha256"])
            blob = genesis["initial_sources"][name]
            self.assertEqual(support.file_ref(Path(blob["path"])), blob)
            self.assertEqual(old_bytes, Path(blob["path"]).read_bytes())
        catalog = transition["compatibility_manifest"]
        self.assertEqual(catalog, support.file_ref(f.compat_path))
        self.assertEqual(new.read(Path(catalog["path"])), f.compat_path.read_bytes())
        def frozen_json(ref):
            raw = evidence_inputs.read(Path(ref["path"]))
            self.assertEqual(support.digest(raw), ref["sha256"])
            return json.loads(raw)
        evidence = frozen_json(payload["evidence"])
        self.assertEqual(set(evidence), {"schema_version", "cause", "source", "session_id", "request", "response", "script", "runtime_rejection_basis", "operator_statement", "evidence_acceptance", "known_binding_sources", "additional_sources"})
        operator = frozen_json(evidence["operator_statement"])["sourceData"]
        acceptance = frozen_json(evidence["evidence_acceptance"])["sourceData"]
        self.assertEqual(operator["decision"], "confirm_local_domain")
        self.assertEqual(acceptance["decision"], "accept_boundary")
        self.assertEqual(operator["target"], f.binding)
        self.assertEqual(acceptance["target"], f.binding)
        self.assertNotEqual(operator["question"]["uuid"], acceptance["question"]["uuid"])
        basis = frozen_json(evidence["runtime_rejection_basis"])
        self.assertEqual(set(basis), {"schema_version", "binary_sha256", "native_version", "capacity_source", "loader_source", "windows"})
        self.assertEqual(basis["windows"], f.static_windows)
        for ref in (basis["capacity_source"], basis["loader_source"], *evidence["known_binding_sources"]):
            self.assertEqual(support.digest(evidence_inputs.read(Path(ref["path"]))), ref["sha256"])
        known = evidence["known_binding_sources"]
        self.assertEqual([(ref["path"], ref["sha256"]) for ref in known],
                         sorted({(ref["path"], ref["sha256"]) for ref in known}))
        for path in (f.manifest_path, f.build_record_path, f.script_path,
                     Path(f.record["genesis"]["path"]), Path(f.record["reservation"]["path"])):
            self.assertIn(support.file_ref(path), known)
        self.assertEqual(len(evidence["additional_sources"]), 1)
        self.assertEqual(evidence["additional_sources"][0]["original_locator"], str(other))
        for source in (evidence["source"], operator["source"], acceptance["source"], *evidence["additional_sources"]):
            original = Path(source["original_locator"])
            self.assertIn(original, (f.native_path, other))
            snapshot = source["snapshot"]
            self.assertNotEqual(snapshot["path"], str(original))
            self.assertEqual(evidence_inputs.read(Path(snapshot["path"])), original.read_bytes())
            self.assertEqual(support.digest(original.read_bytes()), snapshot["sha256"])
        for path in (f.operator_index, f.acceptance_index, f.target_path):
            self.assertEqual(evidence_inputs.read(path), path.read_bytes())
        f.assert_old_unchanged(self)


class KnownSourceRegression(unittest.TestCase):
    @contextlib.contextmanager
    def scenario(self):
        f = support.RecoveryFixture()
        try:
            with mock.patch.dict(os.environ, f.environment, clear=True):
                mod = support.load_module(f.executor)
                with mock.patch.object(mod, "_RUNTIME_REJECTION_PROFILES", f.runtime_profiles):
                    def recover(check_only=True, sources=()):
                        return mod.recover_dispatch_rejection(
                            repo_path=f.repo, manifest_path=f.manifest_path, build_record_path=f.build_record_path,
                            native_record_path=f.native_path, tool_use_id="call_fixture_rejection",
                            operator_index=f.operator_index, evidence_acceptance_index=f.acceptance_index,
                            check_only=check_only, additional_sources=tuple(sources))
                    yield f, mod, recover
        finally:
            f.close()

    def assert_source_refusal(self, f, mod, recover, check, sources=(), prefixes=("counterevidence", "source_", "native_", "audit_index_")):
        before = support.tree_snapshot(f.root)
        error = None
        result = None
        try:
            result = recover(check_only=check, sources=sources)
        except mod.ExecutorError as exc:
            error = exc
        after = support.tree_snapshot(f.root)
        if error is None:
            raise AssertionError(f"wrongly accepted eligible={result.get('eligible') if isinstance(result, dict) else None}; wrote={before != after}")
        self.assertEqual(error.error_code, "E_RECOVERY_EVIDENCE")
        self.assertTrue(error.reason.startswith(prefixes), error.reason)
        self.assertEqual(after, before, "rejection must not publish or modify transaction files")
        self.assertEqual(len(f.event_paths()), 1)

    def test_typed_termination_healthy_check_and_frozen_mutation(self):
        for check in (True, False):
            with self.subTest(check_only=check), self.scenario() as (f, mod, recover):
                root, leaf, log, row, native, event = install_typed_termination(f, mod)
                self.assertEqual(typed_preflight(f, mod, row)["terminations"]["/workflowProgress/0"], row["data"]["termination_refs"][0]["event"])
                before = support.tree_snapshot(f.root)
                try:
                    result = recover(check_only=check, sources=(root,))
                except mod.ExecutorError as exc:
                    self.fail(f"healthy typed event wrongly refused: {exc.error_code}/{exc.reason}")
                self.assertTrue(result["eligible"])
                if check:
                    self.assertEqual(support.tree_snapshot(f.root), before)
                else:
                    ref = result["event"]
                    event_obj = json.loads(Path(ref["path"]).read_bytes())
                    closure = event_obj["payload"]["input_closure"]
                    frozen = mod._history_closure(closure, Path(ref["path"]), f.scope,
                                                  raw=Path(closure["path"]).read_bytes())
                    for path in (root, leaf, log):
                        self.assertEqual(frozen.read(path), path.read_bytes())
                    frozen_row = json.loads(frozen.read(root))
                    self.assertEqual(frozen_row["data"]["termination_refs"], row["data"]["termination_refs"])
                    self.assertEqual(json.loads(frozen.read(leaf)), native)
                    self.assertEqual(json.loads(frozen.read(log).splitlines()[0]), event)

    def test_typed_termination_associated_rows_veto(self):
        for dimension in ("tool_id", "cycle", "script_path"):
            for check in (True, False):
                with self.subTest(dimension=dimension, check_only=check), self.scenario() as (f, mod, recover):
                    data = {"toolUseID": "call_fixture_rejection"} if dimension == "tool_id" else (
                        {"audit_cycle_id": f.record["identity"]["audit_cycle_id"]} if dimension == "cycle"
                        else {"scriptPath": str(f.script_path)})
                    extra = {"type": "future-native-role", "agentId": "unrelated-agent", "uuid": "associated-event", "data": data}
                    root, leaf, log, row, native, event = install_typed_termination(f, mod, extra=extra)
                    self.assertEqual(typed_preflight(f, mod, row)["terminations"]["/workflowProgress/0"], row["data"]["termination_refs"][0]["event"])
                    self.assertEqual(json.loads(log.read_bytes().splitlines()[0]), event)
                    self.assertEqual(row["data"]["native_record"], support.file_ref(leaf))
                    self.assertEqual(row["data"]["termination_refs"][0]["event"]["file"], support.file_ref(log))
                    self.assert_source_refusal(f, mod, recover, check, (root,), ("counterevidence",))

    def test_typed_termination_broken_links_use_native_validation(self):
        for defect in ("agent", "uuid", "line", "hash"):
            for check in (True, False):
                with self.subTest(defect=defect, check_only=check), self.scenario() as (f, mod, recover):
                    root, _, _, row, _, _ = install_typed_termination(f, mod)
                    self.assertEqual(len(typed_preflight(f, mod, row)["terminations"]), 1)
                    event_ref = row["data"]["termination_refs"][0]["event"]
                    if defect == "agent":
                        event_ref["agent_id"] = "wrong-agent"
                    elif defect == "uuid":
                        event_ref["event_uuid"] = "wrong-event"
                    elif defect == "line":
                        event_ref["line"] = 2
                    else:
                        event_ref["file"]["sha256"] = "0" * 64
                    root.write_bytes(support.encode(row) + b"\n")
                    with self.assertRaises(mod.ExecutorError) as expected:
                        typed_preflight(f, mod, row)
                    self.assertEqual(expected.exception.error_code, "E_NATIVE_EVIDENCE")
                    reason = expected.exception.reason
                    self.assertIn(reason, ("termination_agent_mismatch", "interruption_event_identity", "jsonl_line_bounds", "source_hash_mismatch"))
                    before = support.tree_snapshot(f.root)
                    with self.assertRaises(mod.ExecutorError) as actual:
                        recover(check_only=check, sources=(root,))
                    self.assertEqual((actual.exception.error_code, actual.exception.reason), ("E_NATIVE_EVIDENCE", reason))
                    self.assertEqual(support.tree_snapshot(f.root), before)

    def test_session_event_ref_does_not_inherit_agent_namespace(self):
        for check in (True, False):
            with self.subTest(check_only=check), self.scenario() as (f, mod, recover):
                root = install_recursive_native(f, mod, "unrelated")
                self.assertTrue(recover(sources=(root,))["eligible"])
                log = f.repo / "foreign-session.jsonl"
                log.write_bytes(support.encode({"type": "user", "uuid": "unrelated-event"}) + b"\n")
                row = json.loads(root.read_bytes())
                row["data"]["foreign_session_event"] = {"file": support.file_ref(log), "line": 1, "event_uuid": "unrelated-event"}
                root.write_bytes(support.encode(row) + b"\n")
                self.assert_source_refusal(f, mod, recover, check, (root,), ("native_namespace",))

    def test_dangling_audit_index_is_not_missing(self):
        for check in (True, False):
            with self.subTest(check_only=check), self.scenario() as (f, mod, recover):
                index = Path(f.manifest["evidence"]["post_audit_index_path"])
                self.assertFalse(index.exists())
                self.assertFalse(index.is_symlink())
                before = support.tree_snapshot(f.root)
                self.assertTrue(recover()["eligible"])
                self.assertEqual(support.tree_snapshot(f.root), before)
                index.symlink_to(index.parent / "missing-target.json")
                self.assertTrue(index.is_symlink())
                self.assertFalse(index.exists())
                self.assert_source_refusal(f, mod, recover, check, prefixes=("source_", "native_", "audit_index_"))

    def test_target_index_foreign_native_is_unattributable(self):
        for check in (True, False):
            with self.subTest(check_only=check), self.scenario() as (f, mod, recover):
                self.assertTrue(recover()["eligible"])
                contradictory_audit_native(f)
                self.assert_source_refusal(f, mod, recover, check)

    def test_target_index_native_run_id_mismatch_is_contradiction(self):
        for check in (True, False):
            with self.subTest(check_only=check), self.scenario() as (f, mod, recover):
                self.assertTrue(recover()["eligible"])
                contradictory_audit_native(f, index_run="index-run", native_run="other-run")
                self.assert_source_refusal(f, mod, recover, check)

    def test_consistent_target_index_and_native_run_is_counterevidence_control(self):
        for check in (True, False):
            with self.subTest(check_only=check), self.scenario() as (f, mod, recover):
                self.assertTrue(recover()["eligible"])
                contradictory_audit_native(f, related=True)
                self.assert_source_refusal(f, mod, recover, check, prefixes=("counterevidence",))

    def test_secondary_root_structured_selected_tool_ids_are_counterevidence(self):
        for field in ("id", "tool_use_id", "toolUseID", "toolUseId", "wireToolInputs"):
            for has_run in (True, False):
                for check in (True, False):
                    with self.subTest(field=field, has_run=has_run, check_only=check), self.scenario() as (f, mod, recover):
                        self.assertTrue(recover()["eligible"])
                        other = f.native_path.with_name("66666666-7777-4888-8999-000000000000.jsonl")
                        row = progress_row(f, field, has_run, root=other)
                        other.write_bytes(support.encode(row) + b"\n")
                        self.assert_source_refusal(f, mod, recover, check, (other,), ("counterevidence",))

    def test_secondary_root_cycle_signal_is_counterevidence_control(self):
        for check in (True, False):
            with self.subTest(check_only=check), self.scenario() as (f, mod, recover):
                self.assertTrue(recover()["eligible"])
                other = f.native_path.with_name("66666666-7777-4888-8999-000000000000.jsonl")
                row = progress_row(f, "toolUseID", root=other)
                row["data"]["audit_cycle_id"] = f.record["identity"]["audit_cycle_id"]
                other.write_bytes(support.encode(row) + b"\n")
                self.assert_source_refusal(f, mod, recover, check, (other,), ("counterevidence",))

    def test_primary_root_structured_selected_tool_id_control(self):
        for has_run in (True, False):
            for check in (True, False):
                with self.subTest(has_run=has_run, check_only=check), self.scenario() as (f, mod, recover):
                    self.assertTrue(recover()["eligible"])
                    f.rows.append(progress_row(f, "toolUseID", has_run))
                    f._write_native()
                    self.assert_source_refusal(f, mod, recover, check, prefixes=("native_", "counterevidence"))

    def test_unknown_role_with_selected_id_is_not_discarded(self):
        for check in (True, False):
            with self.subTest(check_only=check), self.scenario() as (f, mod, recover):
                self.assertTrue(recover()["eligible"])
                other = f.native_path.with_name("66666666-7777-4888-8999-000000000000.jsonl")
                other.write_bytes(support.encode(progress_row(f, "toolUseID", root=other, row_type="future-native-role")) + b"\n")
                self.assert_source_refusal(f, mod, recover, check, (other,), ("counterevidence", "native_"))

    def test_recursive_native_structured_ids_and_script_bindings_veto(self):
        for dimension in ("id", "tool_use_id", "toolUseID", "toolUseId", "wireToolInputs", "script_path", "script_hash"):
            for check in (True, False):
                with self.subTest(dimension=dimension, check_only=check), self.scenario() as (f, mod, recover):
                    self.assertTrue(recover()["eligible"])
                    root = install_recursive_native(f, mod, dimension)
                    self.assert_source_refusal(f, mod, recover, check, (root,), ("counterevidence",))

    def test_two_level_recursive_native_keeps_association(self):
        for dimension in ("toolUseID", "script_hash"):
            for check in (True, False):
                with self.subTest(dimension=dimension, check_only=check), self.scenario() as (f, mod, recover):
                    self.assertTrue(recover()["eligible"])
                    root = install_recursive_native(f, mod, dimension, depth=2)
                    self.assert_source_refusal(f, mod, recover, check, (root,), ("counterevidence",))

    def test_recursive_native_cycle_counterevidence_control(self):
        for check in (True, False):
            with self.subTest(check_only=check), self.scenario() as (f, mod, recover):
                self.assertTrue(recover()["eligible"])
                root = install_recursive_native(f, mod, "cycle")
                self.assert_source_refusal(f, mod, recover, check, (root,), ("counterevidence",))

    def test_unrelated_recursive_native_is_readable_and_eligible(self):
        with self.scenario() as (f, mod, recover):
            self.assertTrue(recover()["eligible"])
            root = install_recursive_native(f, mod, "unrelated")
            before = support.tree_snapshot(f.root)
            self.assertTrue(recover(sources=(root,))["eligible"])
            self.assertEqual(support.tree_snapshot(f.root), before)

    def test_root_api_transport_native_reference_is_not_counterevidence(self):
        for envelope in ("api-request", "api-request-shape", "api-request-blob"):
            with self.subTest(envelope=envelope), self.scenario() as (f, mod, recover):
                self.assertTrue(recover()["eligible"])
                root = install_recursive_native(f, mod, "toolUseID", envelope=envelope)
                before = support.tree_snapshot(f.root)
                self.assertTrue(recover(sources=(root,))["eligible"])
                self.assertEqual(support.tree_snapshot(f.root), before)

    def test_unrelated_progress_and_api_copies_do_not_veto(self):
        with self.scenario() as (f, mod, recover):
            self.assertTrue(recover()["eligible"])
            other = f.native_path.with_name("66666666-7777-4888-8999-000000000000.jsonl")
            rows = [progress_row(f, "toolUseID", root=other, target=False)]
            rows.extend(progress_row(f, "toolUseID", root=other, row_type=kind)
                        for kind in ("api-request", "api-request-shape", "api-request-blob"))
            other.write_bytes(b"\n".join(support.encode(row) for row in rows) + b"\n")
            before = support.tree_snapshot(f.root)
            self.assertTrue(recover(sources=(other,))["eligible"])
            self.assertEqual(support.tree_snapshot(f.root), before)


if __name__ == "__main__":
    unittest.main()
