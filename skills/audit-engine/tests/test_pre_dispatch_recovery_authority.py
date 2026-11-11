"""TASK006: independent authority adapters, without invoking the recovery transaction.

Missing adapters are feature-absence RED, not evidence that a negative case was
caught. All records and identities are synthetic; no private notes are inputs.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest import mock

_support_path = Path(__file__).with_name("pre_dispatch_recovery_fixtures.py")
_spec = importlib.util.spec_from_file_location("authority_recovery_test_support", _support_path)
assert _spec is not None and _spec.loader is not None
support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(support)

KINDS = ("operator", "acceptance")
HELPERS = {"operator": "_parse_operator_recovery_statement",
           "acceptance": "_parse_evidence_acceptance"}
PREFIXES = {"operator": "operator_", "acceptance": "evidence_acceptance_"}


class AuthorityTests(unittest.TestCase):
    def fixture(self, kind):
        visible = support.load_module(support.EXECUTOR)
        helper = HELPERS[kind]
        self.assertTrue(callable(getattr(visible, helper, None)),
                        "FEATURE_NOT_IMPLEMENTED_TDD_RED: " + helper + " absent")
        f = support.RecoveryFixture()
        self.addCleanup(f.close)
        env = mock.patch.dict(os.environ, f.environment, clear=True)
        env.start()
        self.addCleanup(env.stop)
        module = support.load_module(f.executor)
        self.assertTrue(callable(getattr(module, helper, None)),
                        "FEATURE_NOT_IMPLEMENTED_TDD_RED: " + helper + " absent in isolated module")
        return f, module

    def index(self, f, kind):
        return f.operator_index if kind == "operator" else f.acceptance_index

    def parse(self, f, module, kind, *, index=None, binding=None, inputs=None):
        return getattr(module, HELPERS[kind])(
            f.repo, copy.deepcopy(f.binding if binding is None else binding),
            self.index(f, kind) if index is None else index, inputs=inputs)

    def refuse(self, f, module, kind, prefix, **kwargs):
        before = support.tree_snapshot(f.root)
        try:
            self.parse(f, module, kind, inputs=module._Inputs(), **kwargs)
        except module.ExecutorError as exc:
            self.assertEqual(exc.error_code, "E_RECOVERY_EVIDENCE")
            self.assertTrue(exc.reason.startswith(prefix), exc.reason)
        except Exception as exc:
            self.fail("NON_BUSINESS_EXCEPTION: " + type(exc).__name__ + ": " + str(exc))
        else:
            self.fail("INVALID_AUTHORITY_ACCEPTED: expected E_RECOVERY_EVIDENCE " + prefix)
        self.assertEqual(support.tree_snapshot(f.root), before)

    def expected(self, f, kind):
        index = json.loads(self.index(f, kind).read_bytes())
        data = {"adapter": ("operator_boundary_20261109_v1" if kind == "operator" else
                            "historical_evidence_acceptance_20261109_v1"),
                "decision": "confirm_local_domain" if kind == "operator" else "accept_boundary",
                "counterevidence_policy": "veto", "target": copy.deepcopy(f.binding),
                "target_locator": support.file_ref(f.target_path),
                "source": {"original_locator": str(f.native_path),
                           "runtime_config_root": str(f.config_root),
                           "snapshot": support.file_ref(f.native_path)},
                "question": {k: index["question"][k] for k in ("uuid", "line", "line_sha256")},
                "response": {k: index["response"][k] for k in ("uuid", "line", "line_sha256")},
                "tool_use_id": "call_fixture_" + kind}
        if kind == "operator":
            data.update(authorization_domain="root_session_and_explicit_delegations",
                        transfer_state="not_authorized_or_transferred",
                        recovery_scope="local_interactive_legacy_recovery")
        else:
            data.update(policy="accept_native_capacity_rejection_with_local_static_basis_and_prior_exclusive_operator_statement_for_this_target_only",
                        residual_uncertainty="historical_executable_identity_not_independently_verified")
        return {"schema_version": 1, "sourceData": data}

    def positive(self, f, module, kind, index=None):
        before = support.tree_snapshot(f.root)
        inputs = module._Inputs()
        try:
            result = self.parse(f, module, kind, index=index, inputs=inputs)
        except Exception as exc:
            self.fail("VALID_AUTHORITY_REJECTED: " + type(exc).__name__ + ": " + str(exc))
        self.assertEqual(result, self.expected(f, kind))
        self.assertIsNot(result.get("eligible"), True)
        self.assertEqual(support.tree_snapshot(f.root), before)
        for path in (index or self.index(f, kind), f.target_path, f.native_path,
                     *(Path(f.binding[k]["path"]) for k in
                       ("genesis", "reservation", "head", "manifest", "script"))):
            self.assertEqual(inputs.raw[str(path)], path.read_bytes(), str(path))

    def each(self, operation):
        for kind in KINDS:
            with self.subTest(kind=kind):
                f, module = self.fixture(kind)
                operation(f, module, kind)

    def test_canonical_operator_and_acceptance_derive_complete_data(self):
        self.each(lambda f, m, k: self.positive(f, m, k))

    def test_legacy_locator_normalizes_without_using_selection_or_boolean(self):
        def case(f, m, k):
            original = json.loads(self.index(f, k).read_bytes())
            q, r = original["question"], original["response"]
            if k == "operator":
                old = {"kind": "legacy", "native_source": str(f.native_path),
                       "exact_target": original["target"], "selection": "decline",
                       "authorizes": False, "does_not_authorize": [], "source_filter": {},
                       "native_binding": {"question": {"line": q["line"], "uuid": q["uuid"],
                           "raw_line_sha256": q["line_sha256"], "tool_use_id": original["tool_use_id"], "input": {}},
                           "answer": {"line": r["line"], "uuid": r["uuid"],
                                      "raw_line_sha256": r["line_sha256"], "content": "", "timestamp": ""},
                           "tool_use_result": {}}}
            else:
                old = {"kind": "legacy", "native_source": str(f.native_path), "target": original["target"],
                       "selection": "retain_threshold", "policy": "not_authority", "residual_uncertainty": "not_authority",
                       "does_not_authorize": [],
                       "question": {"line": q["line"], "uuid": q["uuid"], "line_sha256": q["line_sha256"],
                                    "tool_use_id": original["tool_use_id"], "input": {}},
                       "response": {"line": r["line"], "uuid": r["uuid"], "line_sha256": r["line_sha256"],
                                    "timestamp": "", "tool_use_result": {}}}
            path = f.repo / (k + "-legacy.json")
            support.write_json(path, old)
            self.positive(f, m, k, path)
        self.each(case)

    def test_missing_index_cannot_be_replaced_by_other_authority(self):
        self.each(lambda f, m, k: self.refuse(f, m, k, PREFIXES[k], index=f.repo / "missing.json"))

    def test_other_adapter_index_does_not_substitute(self):
        self.each(lambda f, m, k: self.refuse(f, m, k, PREFIXES[k],
                   index=self.index(f, "acceptance" if k == "operator" else "operator")))

    def test_decline_and_retain_rejected_even_with_empty_annotations(self):
        def case(f, m, k):
            f.choose(k, 1)
            _, response = f._authority(k)
            response["toolUseResult"]["annotations"] = {}
            f._write_native()
            self.refuse(f, m, k, PREFIXES[k])
        self.each(case)

    def test_global_fencing_is_not_confirmation(self):
        f, m = self.fixture("operator")
        f.choose("operator", 2)
        self.refuse(f, m, "operator", "operator_")

    def test_valid_fileref_to_wrong_target_rejected(self):
        self.each(lambda f, m, k: (f.wrong_target(k), self.refuse(f, m, k, "target_")))

    def test_preview_target_mismatch_rejected(self):
        self.each(lambda f, m, k: (f.rewrite_template(k, preview=True), self.refuse(f, m, k, "target_")))

    def test_caller_chosen_description_cannot_become_template(self):
        self.each(lambda f, m, k: (f.rewrite_template(k), self.refuse(f, m, k, PREFIXES[k])))

    def test_consistent_rewritten_question_and_option_are_not_authority(self):
        def case(f, m, k):
            request, response = f._authority(k)
            qs = request["message"]["content"][0]["input"]["questions"]
            qs[0]["question"] = "Caller-selected question"
            qs[0]["options"][0]["label"] = "Caller-selected approval"
            response["toolUseResult"] = {"questions": copy.deepcopy(qs),
                "answers": {qs[0]["question"]: qs[0]["options"][0]["label"]},
                "annotations": {qs[0]["question"]: {"preview": qs[0]["options"][0]["preview"]}}}
            f._write_native()
            self.refuse(f, m, k, PREFIXES[k])
        self.each(case)

    def test_answers_and_questions_must_match_request(self):
        def case(f, m, k):
            _, response = f._authority(k)
            response["toolUseResult"]["questions"][0]["header"] = "different"
            f._write_native()
            self.refuse(f, m, k, PREFIXES[k])
        self.each(case)

    def test_annotation_preview_must_match_selected_option(self):
        def case(f, m, k):
            _, response = f._authority(k)
            result = response["toolUseResult"]
            result["annotations"][result["questions"][0]["question"]]["preview"] = "wrong"
            f._write_native()
            self.refuse(f, m, k, PREFIXES[k])
        self.each(case)

    def test_sidechain_and_api_only_are_not_real_root(self):
        def case(f, m, k):
            request, response = f._authority(k)
            request["isSidechain"] = response["isSidechain"] = True
            f._write_native()
            self.refuse(f, m, k, "native_")
            f.restore_authorities()
            f.api_copy(k)
            self.refuse(f, m, k, "native_")
        self.each(case)

    def test_api_copy_coexists_with_root_and_unrelated_tool_run_id(self):
        def case(f, m, k):
            request, response = f._authority(k)
            f.rows.extend({"type": "api-request-blob", "data": copy.deepcopy(row)}
                          for row in (request, response))
            request["message"]["content"].append({"type": "tool_use", "id": "unrelated-tool",
                "name": "OtherTool", "input": {"runId": "unrelated-run"}})
            f.append_workflow(status="success", related=False)
            self.positive(f, m, k)
        self.each(case)

    def test_unknown_role_or_duplicate_tool_id_are_not_ignored(self):
        def case(f, m, k):
            request, _ = f._authority(k)
            duplicate = copy.deepcopy(request)
            duplicate["uuid"] = f._uuid(100)
            f.rows.append(duplicate)
            f._write_native()
            self.refuse(f, m, k, "native_")
            f.restore_authorities()
            request, _ = f._authority(k)
            duplicate = copy.deepcopy(request)
            duplicate["uuid"] = f._uuid(100)
            duplicate["type"] = duplicate["message"]["role"] = "unknown"
            f.rows.append(duplicate)
            f._write_native()
            self.refuse(f, m, k, "native_")
        self.each(case)

    def test_wire_input_conflicting_with_selected_question_rejected(self):
        def case(f, m, k):
            request, _ = f._authority(k)
            block = request["message"]["content"][0]
            request["wireToolInputs"] = {block["id"]: {"questions": []}}
            f._write_native()
            self.refuse(f, m, k, "native_")
        self.each(case)

    def test_bool_line_incomplete_line_and_bad_hash_rejected(self):
        def case(f, m, k):
            path = self.index(f, k)
            index = json.loads(path.read_bytes())
            for field, value in (("line", True), ("line_sha256", "0" * 64)):
                with self.subTest(field=field):
                    bad = copy.deepcopy(index)
                    bad["question"][field] = value
                    support.write_json(path, bad)
                    self.refuse(f, m, k, "native_")
            support.write_json(path, index)
            lines = f.native_path.read_bytes().splitlines()
            response_line = index["response"]["line"]
            f.native_path.write_bytes(b"\n".join(lines[:response_line])[:-1])
            self.refuse(f, m, k, "native_")
        self.each(case)

    def test_uuid_and_parent_binding_must_match(self):
        def case(f, m, k):
            path = self.index(f, k)
            original = json.loads(path.read_bytes())
            bad = copy.deepcopy(original)
            bad["question"]["uuid"] = f._uuid(999)
            support.write_json(path, bad)
            self.refuse(f, m, k, "native_")
            support.write_json(path, original)
            _, response = f._authority(k)
            response["parentUuid"] = f._uuid(999)
            f._write_native()
            self.refuse(f, m, k, "native_")
        self.each(case)

    def test_binding_recomputed_from_real_five_refs_not_caller(self):
        def case(f, m, k):
            for field in ("genesis", "reservation", "head", "manifest", "script"):
                with self.subTest(field=field):
                    binding = copy.deepcopy(f.binding)
                    binding[field] = support.file_ref(f.target_path)
                    self.refuse(f, m, k, "target_", binding=binding)
            binding = copy.deepcopy(f.binding)
            binding["identity"]["change_id"] = "caller-selected-other-object"
            self.refuse(f, m, k, "target_", binding=binding)
        self.each(case)

    def test_target_locator_descriptive_flags_do_not_authorize(self):
        def case(f, m, k):
            target = copy.deepcopy(f.target_locator)
            target["no_recovery_executed"] = False
            target["kind"] = "descriptive-only"
            support.write_json(f.target_path, target)
            f._refresh_indices()
            self.positive(f, m, k)
            f.choose(k, 1)
            self.refuse(f, m, k, PREFIXES[k])
        self.each(case)

    def refresh_reservation(self, f, mutate):
        """Rebind every dependent ref and regenerate both synthetic root UIs."""
        path = Path(f.binding["reservation"]["path"])
        reserve = json.loads(path.read_bytes())
        mutate(reserve)
        f.binding["reservation"] = support.write_json(path, reserve)
        f.binding["head"] = copy.deepcopy(f.binding["reservation"])
        f.target_locator["reservation"] = copy.deepcopy(f.binding["reservation"])
        f.target_locator["current_head"] = copy.deepcopy(f.binding["head"])
        support.write_json(f.target_path, f.target_locator)
        f.rows[2:4] = f._ask_pair("operator", 3)
        f.rows[4:6] = f._ask_pair("acceptance", 5)
        f._write_native()

    def test_review_reserve_identity_round_bool_not_integer(self):
        def case(f, m, k):
            # No-op reserialization is a reachable legal control, including both UIs.
            self.refresh_reservation(f, lambda reserve: None)
            self.positive(f, m, k)
            self.refresh_reservation(f, lambda reserve: reserve["payload"]["identity"].update(round=True))
            self.refuse(f, m, k, "target_")
        self.each(case)

    def test_review_locator_identity_round_bool_not_integer(self):
        def case(f, m, k):
            self.positive(f, m, k)
            target = copy.deepcopy(f.target_locator)
            target["identity"]["round"] = True
            support.write_json(f.target_path, target)
            f._refresh_indices()
            self.refuse(f, m, k, "target_")
        self.each(case)

    def test_review_response_multiselect_integer_not_false(self):
        def case(f, m, k):
            self.positive(f, m, k)
            _, response = f._authority(k)
            response["toolUseResult"]["questions"][0]["multiSelect"] = 0
            f._write_native()
            self.refuse(f, m, k, PREFIXES[k])
        self.each(case)

    def test_review_request_multiselect_integer_not_false(self):
        def case(f, m, k):
            self.positive(f, m, k)
            request, response = f._authority(k)
            request["message"]["content"][0]["input"]["questions"][0]["multiSelect"] = 0
            response["toolUseResult"]["questions"][0]["multiSelect"] = 0
            f._write_native()
            self.refuse(f, m, k, PREFIXES[k])
        self.each(case)

    def test_review_closed_genesis_cannot_add_unknown_key(self):
        def case(f, m, k):
            path = Path(f.binding["genesis"]["path"])
            genesis = json.loads(path.read_bytes())
            f.binding["genesis"] = support.write_json(path, genesis)
            f.target_locator["genesis"] = copy.deepcopy(f.binding["genesis"])
            self.refresh_reservation(f, lambda reserve: reserve.update(genesis=copy.deepcopy(f.binding["genesis"])))
            self.positive(f, m, k)
            genesis["invalid_extra"] = "bad"
            f.binding["genesis"] = support.write_json(path, genesis)
            f.target_locator["genesis"] = copy.deepcopy(f.binding["genesis"])
            self.refresh_reservation(f, lambda reserve: reserve.update(genesis=copy.deepcopy(f.binding["genesis"])))
            self.refuse(f, m, k, "target_")
        self.each(case)

    def test_review_sidechain_copies_do_not_duplicate_root_authority(self):
        def case(f, m, k):
            self.positive(f, m, k)
            # Both same and different UUID copies are non-root, not real answers.
            for same_uuid in (False, True):
                with self.subTest(same_uuid=same_uuid):
                    f.restore_authorities()
                    question, _ = f._authority(k)
                    duplicate = copy.deepcopy(question)
                    if not same_uuid:
                        duplicate["uuid"] = f._uuid(90)
                    duplicate["isSidechain"] = True
                    f.rows.append(duplicate)
                    f._write_native()
                    self.positive(f, m, k)
        self.each(case)

    def test_review_question_and_response_timestamp_type(self):
        def case(f, m, k):
            self.positive(f, m, k)
            for side in ("question", "response"):
                with self.subTest(side=side):
                    f.restore_authorities()
                    q, r = f._authority(k)
                    (q if side == "question" else r)["timestamp"] = 0
                    f._write_native()
                    self.refuse(f, m, k, "native_")
        self.each(case)

    def test_review_known_request_and_response_message_shapes(self):
        def case(f, m, k):
            self.positive(f, m, k)
            for row_index in (0, 1):
                with self.subTest(row_index=row_index):
                    f.restore_authorities()
                    f.rows[row_index]["message"] = None
                    f._write_native()
                    self.refuse(f, m, k, "native_")
        self.each(case)

    def test_review_reserve_integer_siblings_reject_boolean(self):
        def case(f, m, k):
            self.refresh_reservation(f, lambda reserve: None)
            self.positive(f, m, k)
            for field in ("seq", "attempt_index"):
                with self.subTest(field=field):
                    def mutate(reserve):
                        if field == "seq":
                            reserve["seq"] = True
                        else:
                            reserve["payload"]["attempt_index"] = True
                    self.refresh_reservation(f, mutate)
                    self.refuse(f, m, k, "target_")
                    self.refresh_reservation(f, lambda reserve: (reserve.update(seq=1),
                                             reserve["payload"].update(attempt_index=1)))
        self.each(case)

    def test_review_binding_identity_and_attempt_reject_boolean(self):
        def case(f, m, k):
            self.positive(f, m, k)
            for field in ("identity_round", "attempt_index"):
                with self.subTest(field=field):
                    binding = copy.deepcopy(f.binding)
                    if field == "identity_round":
                        binding["identity"]["round"] = True
                    else:
                        binding["attempt_index"] = True
                    self.refuse(f, m, k, "target_", binding=binding)
        self.each(case)

    def test_review_head_ref_cannot_alias_integer_typed_object(self):
        def case(f, m, k):
            self.refresh_reservation(f, lambda reserve: None)
            self.positive(f, m, k)
            # head and reservation point to the same actual first event; its seq
            # cannot be interpreted as integer 1 when encoded as boolean true.
            self.refresh_reservation(f, lambda reserve: reserve.update(seq=True))
            self.refuse(f, m, k, "target_")
        self.each(case)

    def test_review_genesis_schema_version_bool_not_integer(self):
        def case(f, m, k):
            path = Path(f.binding["genesis"]["path"])
            genesis = json.loads(path.read_bytes())
            f.binding["genesis"] = support.write_json(path, genesis)
            f.target_locator["genesis"] = copy.deepcopy(f.binding["genesis"])
            self.refresh_reservation(f, lambda reserve: reserve.update(genesis=copy.deepcopy(f.binding["genesis"])))
            self.positive(f, m, k)
            genesis["schema_version"] = True
            f.binding["genesis"] = support.write_json(path, genesis)
            f.target_locator["genesis"] = copy.deepcopy(f.binding["genesis"])
            self.refresh_reservation(f, lambda reserve: reserve.update(genesis=copy.deepcopy(f.binding["genesis"])))
            self.refuse(f, m, k, "target_")
        self.each(case)

    def add_second_ask(self, f, kind, *, with_result):
        question, response = f._authority(kind)
        other = copy.deepcopy(question["message"]["content"][0])
        other["id"] = "call_fixture_second_ask"
        question["message"]["content"].append(other)
        if with_result:
            result = copy.deepcopy(response["message"]["content"][0])
            result["tool_use_id"] = other["id"]
            response["message"]["content"].append(result)
        f._write_native()

    def rebind_script_bytes(self, f, raw):
        """Preserve true FileRefs while rebuilding both question/answer UIs."""
        script = Path(f.binding["script"]["path"])
        script.write_bytes(raw)
        f.binding["script"] = support.file_ref(script)
        f.target_locator["script"] = copy.deepcopy(f.binding["script"])
        f.target_locator["script_bytes"] = len(raw)
        self.refresh_reservation(f, lambda reserve: reserve["payload"].update(
            workflow_script=copy.deepcopy(f.binding["script"])))

    def test_review_r2_extra_paired_ask_in_selected_root_is_ambiguous(self):
        """RED if a second real Ask and its result are ignored by tool ID."""
        def case(f, m, k):
            self.positive(f, m, k)
            self.add_second_ask(f, k, with_result=True)
            self.refuse(f, m, k, "native_")
        self.each(case)

    def test_review_r2_extra_unpaired_ask_in_selected_root_is_ambiguous(self):
        """RED if a second real Ask is ignored merely because no result exists."""
        def case(f, m, k):
            self.positive(f, m, k)
            self.add_second_ask(f, k, with_result=False)
            self.refuse(f, m, k, "native_")
        self.each(case)

    def test_review_r2_other_tool_in_selected_root_is_valid(self):
        """RED if an overbroad fix forbids unrelated tools in a root message."""
        def case(f, m, k):
            request, response = f._authority(k)
            request["message"]["content"].append({"type": "tool_use", "id": "call_fixture_other",
                "name": "OtherTool", "input": {"value": "unrelated"}})
            response["message"]["content"].append({"type": "tool_result",
                "tool_use_id": "call_fixture_other", "content": "unrelated"})
            f._write_native()
            self.positive(f, m, k)
        self.each(case)

    def test_review_r2_operator_question_script_length_must_match(self):
        """RED if the fixed 570716-byte question authorizes adjacent sizes."""
        f, m = self.fixture("operator")
        original = f.script_path.read_bytes()
        self.assertEqual(len(original), 570716)
        self.rebind_script_bytes(f, original)
        self.positive(f, m, "operator")
        for raw in (original[:-1], original + b" "):
            with self.subTest(script_bytes=len(raw)):
                self.rebind_script_bytes(f, raw)
                self.assertEqual(f.script_path.stat().st_size, len(raw))
                self.refuse(f, m, "operator", "target_")

    def test_review_r2_acceptance_has_no_operator_script_size_claim(self):
        """RED if a fix invents a 570716-byte claim in the acceptance UI."""
        f, m = self.fixture("acceptance")
        original = f.script_path.read_bytes()
        self.assertEqual(len(original), 570716)
        for raw in (original[:-1], original, original + b" "):
            with self.subTest(script_bytes=len(raw)):
                self.rebind_script_bytes(f, raw)
                self.assertEqual(f.script_path.stat().st_size, len(raw))
                self.positive(f, m, "acceptance")

    def test_known_pair_root_fields_order_and_time(self):
        """Both locator-selected events must be a linked, ordered native root pair."""
        cases = (
            (0, ("type",), "user"), (1, ("type",), "assistant"),
            (0, ("message", "role"), "user"), (1, ("message", "role"), "assistant"),
            (0, ("cwd",), "/wrong"), (1, ("cwd",), "/wrong"),
            (0, ("sessionId",), "other-session"), (1, ("sessionId",), "other-session"),
            (0, ("isSidechain",), True), (1, ("isSidechain",), True),
            (0, ("isSidechain",), 0), (1, ("isSidechain",), 0),
            (0, ("isMeta",), True), (1, ("isMeta",), True),
            (0, ("isMeta",), 0), (1, ("isMeta",), 0),
            (1, ("parentUuid",), "wrong-parent"),
            (1, ("sourceToolAssistantUUID",), "wrong-source"),
            (0, ("timestamp",), None), (1, ("timestamp",), 123),
            (0, ("timestamp",), "2026-01-01T00:00:01"),
            (1, ("timestamp",), "2026-01-01T00:00:02"),
            (0, ("timestamp",), "not-a-timestamp"),
            (1, ("timestamp",), "2026-01-01T00:00:00Z"),
        )
        def case(f, m, k):
            self.positive(f, m, k)
            for row, path, value in cases:
                with self.subTest(adapter=k, row=row, field=".".join(path), value=value):
                    f.restore_authorities()
                    obj = f.rows[row]
                    for key in path[:-1]:
                        obj = obj[key]
                    obj[path[-1]] = value
                    f._write_native()
                    self.refuse(f, m, k, "native_")
            with self.subTest(adapter=k, field="physical_order"):
                f.restore_authorities()
                f.rows[0], f.rows[1] = f.rows[1], f.rows[0]
                f._write_native()
                self.refuse(f, m, k, "native_")
        self.each(case)

    def test_known_pair_tool_identity_and_input(self):
        """Pair blocks and complete typed Workflow input bind to the target."""
        def case(f, m, k):
            self.positive(f, m, k)
            # Pair validation is not a capacity-rejection policy.
            f.rows[1]["message"]["content"][0]["is_error"] = False
            f._write_native()
            self.positive(f, m, k)
            cases = (
                (0, ("name",), "OtherTool"),
                (0, ("id",), "other-call"),
                (1, ("tool_use_id",), "other-call"),
                (0, ("input", "scriptPath"), "/other"),
                (0, ("input", "args", "manifest_sha256"), "0" * 64),
                (0, ("input", "args", "identity", "round"), True),
                (0, ("input", "args", "extra"), "unexpected"),
            )
            for row, path, value in cases:
                with self.subTest(adapter=k, row=row, field=".".join(path)):
                    f.restore_authorities()
                    obj = f.rows[row]["message"]["content"][0]
                    for key in path[:-1]:
                        obj = obj[key]
                    obj[path[-1]] = value
                    f._write_native()
                    self.refuse(f, m, k, "native_")
        self.each(case)

    def test_known_pair_root_uniqueness_and_nonroot_copies(self):
        """Real roots cannot duplicate either selected UUID or target tool ID."""
        def case(f, m, k):
            self.positive(f, m, k)
            for row in (0, 1):
                for duplicate in ("uuid", "uuid_other_root_type", "tool", "unknown_role_tool"):
                    with self.subTest(adapter=k, row=row, duplicate=duplicate):
                        f.restore_authorities()
                        extra = copy.deepcopy(f.rows[row])
                        if duplicate.startswith("uuid"):
                            extra["message"]["content"] = []
                            if duplicate == "uuid_other_root_type":
                                extra["type"] = "user" if row == 0 else "assistant"
                        else:
                            extra["uuid"] = f._uuid(80 + row)
                            if duplicate == "unknown_role_tool":
                                extra["type"] = "unexpected-role"
                                extra["message"]["role"] = "unexpected-role"
                        f.rows.append(extra)
                        f._write_native()
                        self.refuse(f, m, k, "native_")
            for row in (0, 1):
                with self.subTest(adapter=k, row=row, copy_only="api"):
                    f.restore_authorities()
                    f.rows[row] = {"type": "api-request-blob", "payload": f.rows[row]}
                    f._write_native()
                    self.refuse(f, m, k, "native_")
            for copy_kind in ("sidechain", "api"):
                with self.subTest(adapter=k, copy_kind=copy_kind):
                    f.restore_authorities()
                    for row in copy.deepcopy(f.rows[:2]):
                        if copy_kind == "sidechain":
                            row["isSidechain"] = True
                        else:
                            row = {"type": "api-request-blob", "payload": row}
                        f.rows.append(row)
                    f._write_native()
                    self.positive(f, m, k)
        self.each(case)

    def test_known_pair_wire_input_matches_real_workflow_call(self):
        """Selected known-pair wire maps must bind to the complete real input."""
        def case(f, m, k):
            self.positive(f, m, k)
            target = f.target_locator["known_workflow_tool_call"]
            actual = copy.deepcopy(f.rows[0]["message"]["content"][0]["input"])
            for row in (0, 1):
                with self.subTest(adapter=k, row=row, wire="matching_and_unrelated"):
                    f.restore_authorities()
                    f.rows[row]["wireToolInputs"] = {
                        target: copy.deepcopy(actual), "call_fixture_other": {"unrelated": True}}
                    f._write_native()
                    self.positive(f, m, k)
                for wire_kind in ("conflicting", "not_dict"):
                    with self.subTest(adapter=k, row=row, wire=wire_kind):
                        f.restore_authorities()
                        f.rows[row]["wireToolInputs"] = (
                            {target: {"unrelated": True}} if wire_kind == "conflicting" else [])
                        f._write_native()
                        self.refuse(f, m, k, "native_")
        self.each(case)

    def test_known_pair_wire_only_duplicate_elsewhere_is_not_ignored(self):
        """A non-API, non-sidechain wire-only target ID is ambiguous."""
        def case(f, m, k):
            self.positive(f, m, k)
            target = f.target_locator["known_workflow_tool_call"]
            f.rows.append({"type": "progress", "isSidechain": False,
                           "wireToolInputs": {"call_fixture_other": {"unrelated": True}}})
            f._write_native()
            self.positive(f, m, k)
            f.restore_authorities()
            f.rows.append({"type": "progress", "isSidechain": False,
                           "wireToolInputs": {target: {"unrelated": True}}})
            f._write_native()
            self.refuse(f, m, k, "native_")
        self.each(case)


if __name__ == "__main__":
    unittest.main()
