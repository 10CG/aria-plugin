"""TASK-008 source compatibility seam; absence RED is not a business CAUGHT.

All legacy execution is confined to the existing isolated fixture's build.  The
recovery tests treat historical source as bytes, never execute a workflow.
"""
from __future__ import annotations

import copy
import importlib.util
import inspect
import json
import os
from pathlib import Path
import unittest
from unittest import mock

_support_path = Path(__file__).with_name("pre_dispatch_recovery_fixtures.py")
_spec = importlib.util.spec_from_file_location("source_recovery_test_support", _support_path)
assert _spec is not None and _spec.loader is not None
support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(support)

NAMES = ("config", "defaults", "executor", "contract", "convergence_algorithm", "report_storage")
UNCHANGED = ("config", "defaults", "convergence_algorithm", "report_storage")


def rebind_bad_genesis_source(f):
    """Rebind the synthetic history by content hash; do not execute old code.

    The factory's first-reserve capture currently contains genesis as an origin,
    but not the reserve itself. Update the reserve origin if a future factory
    includes it; never manufacture an otherwise absent origin.
    """
    genesis_path = Path(f.record["genesis"]["path"])
    reserve_path = Path(f.record["reservation"]["path"])
    closure_path = Path(f.record["input_closure"]["path"])
    genesis = json.loads(genesis_path.read_bytes())
    genesis["initial_sources"]["executor"] = copy.deepcopy(genesis["initial_sources"]["contract"])
    genesis_ref = support.write_json(genesis_path, genesis)
    reserve = json.loads(reserve_path.read_bytes())
    reserve["genesis"] = genesis_ref
    reserve_ref = support.write_json(reserve_path, reserve)
    closure = json.loads(closure_path.read_bytes())
    for origin in (genesis_path, reserve_path):
        matches = [entry for entry in closure["sources"] if entry["origin"] == str(origin)]
        if origin == genesis_path and len(matches) != 1:
            raise AssertionError("expected exactly one genesis origin")
        if len(matches) > 1:
            raise AssertionError("duplicate history origin")
        if matches:
            raw = origin.read_bytes()
            sha = support.digest(raw)
            blob = f.scope / "blobs" / (sha + ".blob")
            blob.write_bytes(raw)
            matches[0].update(sha256=sha, blob=support.file_ref(blob))
    closure_ref = support.write_json(closure_path, closure)
    build = copy.deepcopy(f.record)
    build.update(genesis=genesis_ref, reservation=reserve_ref, input_closure=closure_ref)
    support.write_json(f.build_record_path, build)
    return build, genesis, reserve, closure


def assert_ref_bytes(test, ref):
    test.assertEqual(support.file_ref(Path(ref["path"])), ref)


def mutate_closure(f, case):
    closure_path = Path(f.old_closure["path"])
    closure = json.loads(closure_path.read_bytes())
    origin = f.old_sources["executor"]["path"]
    index = next(i for i, entry in enumerate(closure["sources"]) if entry["origin"] == origin)
    if case == "missing_origin":
        del closure["sources"][index]
    elif case == "bad_mapping":
        closure["sources"][index]["blob"]["path"] += ".wrong"
    else:
        raise AssertionError("unknown closure mutation")
    build = copy.deepcopy(f.record)
    build["input_closure"] = support.write_json(closure_path, closure)
    support.write_json(f.build_record_path, build)
    return build, closure


class SourceFixtureHealth(unittest.TestCase):
    def test_real_factory_has_two_generations_and_logical_blob_identities(self):
        f = support.RecoveryFixture()
        self.addCleanup(f.close)
        genesis = json.loads(Path(f.record["genesis"]["path"]).read_bytes())
        closure = json.loads(Path(f.old_closure["path"]).read_bytes())
        entries = {entry["origin"]: entry for entry in closure["sources"]}
        self.assertEqual(set(f.old_sources), set(NAMES))
        for name in NAMES:
            logical = f.old_sources[name]
            blob = genesis["initial_sources"][name]
            self.assertNotEqual(logical["path"], blob["path"])
            self.assertEqual(logical["sha256"], blob["sha256"])
            entry = entries[logical["path"]]
            self.assertEqual(entry["sha256"], logical["sha256"])
            self.assertEqual(Path(entry["blob"]["path"]).read_bytes(), Path(blob["path"]).read_bytes())
        for name in ("executor", "contract"):
            self.assertEqual(f.old_sources[name]["path"], f.current_sources[name]["path"])
            self.assertNotEqual(f.old_sources[name]["sha256"], f.current_sources[name]["sha256"])
        module = support.load_module(f.executor)
        old = module._history_closure(f.old_closure, f.build_record_path, f.scope,
                                      raw=Path(f.old_closure["path"]).read_bytes())
        self.assertIs(f.manifest["require_same_admitted_roles"], True)
        self.assertIs(f.record["effective_config"]["require_same_admitted_roles"]["value"], True)
        self.assertIs(module._load_fixed_policy(f.repo, old)["require_same_admitted_roles"], True)
        self.assertIs(module._load_fixed_policy(f.repo, module._Inputs())["require_same_admitted_roles"], True)
        self.assertEqual(len(f.event_paths()), 1)
        f.assert_old_unchanged(self)

    def test_same_pair_and_guard_mutants_are_constructed_without_stale_inputs(self):
        f = support.RecoveryFixture()
        self.addCleanup(f.close)
        original = copy.deepcopy(f.record)
        build = copy.deepcopy(original)
        self.assertIs(build["effective_config"]["require_same_admitted_roles"]["value"], True)
        build["effective_config"]["require_same_admitted_roles"]["value"] = False
        support.write_json(f.build_record_path, build)
        restored = copy.deepcopy(build)
        restored["effective_config"]["require_same_admitted_roles"]["value"] = True
        self.assertEqual(restored, original)
        for ref in (build["genesis"], build["reservation"], build["input_closure"]):
            assert_ref_bytes(self, ref)
        f.executor.write_bytes(f.old_executor)
        f.contract.write_bytes(f.old_contract)
        catalog = copy.deepcopy(f.compat)
        catalog["to"] = copy.deepcopy(catalog["from"])
        support.write_json(f.compat_path, catalog)
        self.assertEqual(catalog["to"], {"executor": support.digest(f.executor.read_bytes()),
                                         "contract": support.digest(f.contract.read_bytes())})
        self.assertEqual(catalog["from"], catalog["to"])
        for name in UNCHANGED:
            self.assertEqual(support.file_ref(Path(f.old_sources[name]["path"])), f.old_sources[name])

    def test_closure_mutators_reach_existing_specific_reasons(self):
        for case, reason in (("missing_origin", "incomplete_pending_closure"),
                             ("bad_mapping", "history_blob_mapping")):
            with self.subTest(case=case):
                f = support.RecoveryFixture()
                try:
                    module = support.load_module(f.executor)
                    build, closure = mutate_closure(f, case)
                    assert_ref_bytes(self, build["input_closure"])
                    self.assertEqual(build["genesis"], f.record["genesis"])
                    self.assertEqual(build["sources"], f.record["sources"])
                    self.assertEqual(build["reservation"], f.record["reservation"])
                    with self.assertRaises(module.ExecutorError) as caught:
                        frozen = module._history_closure(build["input_closure"], f.build_record_path, f.scope,
                                                         raw=Path(build["input_closure"]["path"]).read_bytes())
                        frozen.read(Path(f.old_sources["executor"]["path"]))
                    self.assertEqual(caught.exception.error_code, "E_POLICY_SOURCE")
                    self.assertEqual(caught.exception.reason, reason)
                    self.assertEqual(len(closure["sources"]), len({x["origin"] for x in closure["sources"]}))
                finally:
                    f.close()

    def test_rebound_wrong_genesis_has_self_consistent_history_refs(self):
        f = support.RecoveryFixture()
        self.addCleanup(f.close)
        original_genesis = json.loads(Path(f.record["genesis"]["path"]).read_bytes())
        original_reserve = json.loads(Path(f.record["reservation"]["path"]).read_bytes())
        build, genesis, reserve, closure = rebind_bad_genesis_source(f)
        for ref in (build["genesis"], build["reservation"], build["input_closure"]):
            assert_ref_bytes(self, ref)
        self.assertEqual(reserve["genesis"], build["genesis"])
        for key in ("anchor", "policy_inputs", "initial_max_rounds"):
            self.assertEqual(genesis[key], original_genesis[key])
        self.assertEqual({k: v for k, v in reserve.items() if k != "genesis"},
                         {k: v for k, v in original_reserve.items() if k != "genesis"})
        self.assertEqual(build["sources"], f.record["sources"])
        self.assertEqual(build["budgets"], f.record["budgets"])
        self.assertEqual(build["prefix_head"], f.record["prefix_head"])
        self.assertEqual(genesis["initial_sources"]["executor"], genesis["initial_sources"]["contract"])
        self.assertNotEqual(genesis["initial_sources"]["executor"]["sha256"], build["sources"]["executor"]["sha256"])
        for entry in closure["sources"]:
            assert_ref_bytes(self, entry["blob"])
            self.assertEqual(entry["sha256"], entry["blob"]["sha256"])
        module = support.load_module(f.executor)
        frozen = module._history_closure(build["input_closure"], f.build_record_path, f.scope,
                                                         raw=Path(build["input_closure"]["path"]).read_bytes())
        self.assertEqual(frozen.read(Path(build["genesis"]["path"])), Path(build["genesis"]["path"]).read_bytes())
        for name in NAMES:
            self.assertEqual(support.digest(frozen.read(Path(build["sources"][name]["path"]))),
                             build["sources"][name]["sha256"])
        for name, ref in genesis["initial_sources"].items():
            assert_ref_bytes(self, ref)
            if name != "executor":
                self.assertEqual(ref, original_genesis["initial_sources"][name])


class RecoverySourcesTests(unittest.TestCase):
    def setUp(self):
        visible = support.load_module(support.EXECUTOR)
        for name in ("_recovery_compatibility_manifest", "_recovery_source_generations"):
            self.assertTrue(callable(getattr(visible, name, None)),
                            "FEATURE_NOT_IMPLEMENTED_TDD_RED: " + name + " absent")
        self.f = support.RecoveryFixture()
        self.addCleanup(self.f.close)
        patcher = mock.patch.dict(os.environ, self.f.environment, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.mod = support.load_module(self.f.executor)

    def plan(self, inputs=None):
        return self.mod._recovery_source_generations(
            self.f.repo, self.f.manifest_path, self.f.build_record_path, inputs=inputs)

    def healthy(self):
        plan, old, new = self.plan(inputs=self.mod._Inputs())
        self.assertEqual(set(plan), {"compatibility_id", "compatibility_manifest", "from_sources", "to_sources"})
        self.assertEqual(plan["compatibility_id"], "pre-dispatch-rejection-v1")
        self.assertEqual(plan["compatibility_manifest"], support.file_ref(self.f.compat_path))
        self.assertEqual(plan["from_sources"], self.f.old_sources)
        self.assertEqual(plan["to_sources"], self.f.current_sources)
        return plan, old, new

    def reject(self, code, prefix):
        # recovery_compat*, recovery_source*, recovery_identity* are proposed
        # private-seam reasons, not pre-existing executor-wide error contracts.
        # history_blob_mapping and incomplete_pending_closure are existing
        # _history_closure / _FrozenInputs reasons and are checked separately.
        before = support.tree_snapshot(self.f.root)
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.plan(inputs=self.mod._Inputs())
        self.assertEqual(caught.exception.error_code, code)
        self.assertTrue(caught.exception.reason.startswith(prefix), caught.exception.reason)
        self.assertEqual(support.tree_snapshot(self.f.root), before)

    def write_compat(self, value):
        support.write_json(self.f.compat_path, value)

    def test_healthy_plan_readers_are_independent_and_pure(self):
        f = self.f
        before = support.tree_snapshot(f.root)
        genesis_before = Path(f.record["genesis"]["path"]).read_bytes()
        capturer = self.mod._Inputs()
        plan, old, new = self.plan(inputs=capturer)
        self.assertIs(new, capturer)
        self.assertIsInstance(old, self.mod._FrozenInputs)
        self.assertIsNot(old, new)
        self.assertEqual(set(plan), {"compatibility_id", "compatibility_manifest", "from_sources", "to_sources"})
        self.assertEqual(plan["from_sources"], f.old_sources)
        self.assertEqual(plan["to_sources"], f.current_sources)
        self.assertEqual(plan["compatibility_manifest"], support.file_ref(f.compat_path))
        for name in NAMES:
            path = Path(f.old_sources[name]["path"])
            old_bytes = old.read(path)
            new_bytes = new.read(path)
            self.assertEqual(support.digest(old_bytes), f.old_sources[name]["sha256"])
            self.assertEqual(support.digest(new_bytes), f.current_sources[name]["sha256"])
            if name in UNCHANGED:
                self.assertEqual(plan["from_sources"][name], plan["to_sources"][name])
            else:
                self.assertNotEqual(old_bytes, new_bytes)
        self.assertEqual(support.tree_snapshot(f.root), before)
        self.assertEqual(Path(f.record["genesis"]["path"]).read_bytes(), genesis_before)
        f.assert_old_unchanged(self)
        self.assertEqual(len(f.event_paths()), 1)
        missing = f.repo / "not-in-old-closure"
        missing.write_bytes(b"live only")
        with self.assertRaises(self.mod.ExecutorError) as caught:
            old.read(missing)
        self.assertEqual(caught.exception.error_code, "E_POLICY_SOURCE")
        self.assertTrue(caught.exception.reason.startswith("incomplete_pending_closure"))
        missing.unlink()
        self.assertEqual(Path(f.record["genesis"]["path"]).read_bytes(), genesis_before)
        # Removing the temporary probe changes its parent mtime; compare after probe separately.
        self.assertEqual(set(support.tree_snapshot(f.root)), set(before))
        f.assert_old_unchanged(self)
        self.assertEqual(len(f.event_paths()), 1)

    def test_manifest_is_mechanical_and_tracks_each_current_file(self):
        f = self.f
        before = support.tree_snapshot(f.root)
        expected = copy.deepcopy(f.compat)
        self.assertEqual(self.mod._recovery_compatibility_manifest(f.repo), expected)
        self.assertEqual(support.tree_snapshot(f.root), before)
        for name, path in (("executor", f.executor), ("contract", f.contract)):
            raw = path.read_bytes()
            try:
                path.write_bytes(raw + b"\n")
                expected["to"][name] = support.digest(raw + b"\n")
                self.assertEqual(self.mod._recovery_compatibility_manifest(f.repo), expected)
            finally:
                path.write_bytes(raw)
                expected["to"][name] = support.digest(raw)

    def test_fixed_catalog_no_caller_override(self):
        self.healthy()
        self.assertEqual(set(inspect.signature(self.mod._recovery_source_generations).parameters),
                         {"repo_path", "manifest_path", "build_record_path", "inputs"})
        alternative = self.f.repo / "other-catalog.json"
        support.write_json(alternative, self.f.compat)
        self.f.compat_path.unlink()
        self.reject("E_SOURCE_DRIFT", "recovery_compat")

    def test_catalog_schema_and_pair_rejections(self):
        self.healthy()
        for case in ("missing", "extra", "bool", "unknown", "wrong_from", "wrong_to"):
            with self.subTest(case=case):
                value = copy.deepcopy(self.f.compat)
                if case == "missing":
                    del value["from"]["contract"]
                elif case == "extra":
                    value["to"]["extra"] = "0" * 64
                elif case == "bool":
                    value["schema_version"] = True
                elif case == "unknown":
                    value["compatibility_id"] = "unknown"
                elif case == "wrong_from":
                    value["from"]["executor"] = "0" * 64
                elif case == "wrong_to":
                    value["to"]["contract"] = "0" * 64
                self.write_compat(value)
                self.reject("E_SOURCE_DRIFT", "recovery_compat")
                self.write_compat(self.f.compat)
                self.healthy()

    def test_same_generation_pair_rejected_without_stale_catalog(self):
        self.healthy()
        f = self.f
        current_executor, current_contract = f.executor.read_bytes(), f.contract.read_bytes()
        try:
            f.executor.write_bytes(f.old_executor)
            f.contract.write_bytes(f.old_contract)
            catalog = copy.deepcopy(f.compat)
            catalog["to"] = copy.deepcopy(catalog["from"])
            self.write_compat(catalog)
            self.assertEqual(catalog["to"], {"executor": support.digest(f.executor.read_bytes()),
                                             "contract": support.digest(f.contract.read_bytes())})
            self.reject("E_SOURCE_DRIFT", "recovery_compat_same_generation")
        finally:
            f.executor.write_bytes(current_executor)
            f.contract.write_bytes(current_contract)
            self.write_compat(f.compat)

    def test_to_stale_after_single_byte_change(self):
        self.healthy()
        for path in (self.f.executor, self.f.contract):
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                try:
                    path.write_bytes(raw + b"\n")
                    self.reject("E_SOURCE_DRIFT", "recovery_compat")
                finally:
                    path.write_bytes(raw)
                self.healthy()

    def test_one_component_may_remain_same_if_pair_changes(self):
        self.healthy()
        raw = self.f.contract.read_bytes()
        try:
            self.f.contract.write_bytes(self.f.old_contract)
            catalog = copy.deepcopy(self.f.compat)
            catalog["to"]["contract"] = catalog["from"]["contract"]
            self.write_compat(catalog)
            plan, old, new = self.plan(inputs=self.mod._Inputs())
            self.assertEqual(plan["to_sources"]["contract"], plan["from_sources"]["contract"])
            self.assertNotEqual(plan["to_sources"]["executor"], plan["from_sources"]["executor"])
            self.assertEqual(old.read(self.f.contract), new.read(self.f.contract))
        finally:
            self.f.contract.write_bytes(raw)
            self.write_compat(self.f.compat)

    def test_each_unchanged_source_byte_drift_is_rejected(self):
        self.healthy()
        for name in UNCHANGED:
            with self.subTest(name=name):
                path = Path(self.f.old_sources[name]["path"])
                raw = path.read_bytes()
                try:
                    path.write_bytes(raw + b"\n")
                    self.reject("E_SOURCE_DRIFT", "recovery_source")
                finally:
                    path.write_bytes(raw)
                self.healthy()

    def test_each_old_logical_ref_fake_path_with_same_hash_is_rejected(self):
        self.healthy()
        path = self.f.build_record_path
        raw = path.read_bytes()
        try:
            for name in NAMES:
                with self.subTest(name=name):
                    record = copy.deepcopy(self.f.record)
                    source = record["sources"][name]
                    fake = self.f.repo / ("fake-" + name)
                    fake.write_bytes(Path(source["path"]).read_bytes() if name in UNCHANGED else
                                     (self.f.old_executor if name == "executor" else self.f.old_contract))
                    self.assertEqual(support.digest(fake.read_bytes()), source["sha256"])
                    source["path"] = str(fake)
                    support.write_json(path, record)
                    self.reject("E_SOURCE_DRIFT", "recovery_source")
                    path.write_bytes(raw)
                    self.healthy()
        finally:
            path.write_bytes(raw)

    def test_old_closure_missing_origin_is_rejected(self):
        self.healthy()
        build, _ = mutate_closure(self.f, "missing_origin")
        assert_ref_bytes(self, build["input_closure"])
        self.reject("E_POLICY_SOURCE", "incomplete_pending_closure")

    def test_old_closure_bad_mapping_is_rejected(self):
        self.healthy()
        build, _ = mutate_closure(self.f, "bad_mapping")
        assert_ref_bytes(self, build["input_closure"])
        self.reject("E_POLICY_SOURCE", "history_blob_mapping")

    def test_old_blob_bytes_corruption_is_rejected(self):
        self.healthy()
        closure = json.loads(Path(self.f.old_closure["path"]).read_bytes())
        entry = next(x for x in closure["sources"] if x["origin"] == self.f.old_sources["executor"]["path"])
        blob = Path(entry["blob"]["path"])
        raw = blob.read_bytes()
        try:
            blob.write_bytes(raw + b"corrupt")
            self.reject("E_POLICY_SOURCE", "history_blob_hash")
        finally:
            blob.write_bytes(raw)

    def test_genesis_source_wrong_blob_is_rejected(self):
        self.healthy()
        build, genesis, reserve, closure = rebind_bad_genesis_source(self.f)
        for ref in (build["genesis"], build["reservation"], build["input_closure"]):
            assert_ref_bytes(self, ref)
        self.assertEqual(reserve["genesis"], build["genesis"])
        for entry in closure["sources"]:
            assert_ref_bytes(self, entry["blob"])
        self.assertNotEqual(genesis["initial_sources"]["executor"]["sha256"],
                            build["sources"]["executor"]["sha256"])
        self.reject("E_SOURCE_DRIFT", "recovery_source")

    def test_build_guard_false_is_rejected(self):
        self.healthy()
        build = copy.deepcopy(self.f.record)
        guard = build["effective_config"]["require_same_admitted_roles"]
        self.assertIs(guard["value"], True)
        guard["value"] = False
        expected = copy.deepcopy(self.f.record)
        expected["effective_config"]["require_same_admitted_roles"]["value"] = False
        self.assertEqual(build, expected)
        support.write_json(self.f.build_record_path, build)
        for name in NAMES:
            self.assertEqual(support.file_ref(Path(self.f.current_sources[name]["path"])),
                             self.f.current_sources[name])
        assert_ref_bytes(self, build["input_closure"])
        assert_ref_bytes(self, build["genesis"])
        assert_ref_bytes(self, build["reservation"])
        self.reject("E_SOURCE_DRIFT", "recovery_source_guard")

    def test_identity_mismatch_is_rejected_without_mutation(self):
        self.healthy()
        build = copy.deepcopy(self.f.record)
        build["identity"]["audit_cycle_id"] = "unrelated-cycle"
        support.write_json(self.f.build_record_path, build)
        self.reject("E_PREVIOUS_IDENTITY", "recovery_identity")


if __name__ == "__main__":
    unittest.main()
