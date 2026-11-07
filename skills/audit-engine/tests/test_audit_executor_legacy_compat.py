"""真实 build 入口的历史兼容回归；不运行 Workflow，不改仓内旧报告。

拒绝所有旧格式会破坏正向用例；忽略所有 checkpoint 冲突、忽略归属、
只取第一个重复字段或跳过历史读取会破坏相应负向用例。
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import patch

import test_audit_executor as fixtures


class LegacyCompatTests(unittest.TestCase):
    repo: Path
    run_dir: Path
    mod: ModuleType

    # 只复用真实临时仓/build fixture，不继承并重复运行其整个测试类。
    setUp = fixtures.BuildContractTests.setUp
    write = staticmethod(fixtures.BuildContractTests.write)
    build = fixtures.BuildContractTests.build
    scope = fixtures.BuildContractTests.scope
    record = fixtures.BuildContractTests.record
    other = "aria-2.0-m6-dispatch-input-delivery"

    @contextmanager
    def fresh(self):
        case = type(self)(self._testMethodName)
        case.setUp()
        try:
            yield case
        finally:
            case.doCleanups()

    def register(self, change, archived=False):
        directory = self.repo / "openspec" / ("archive" if archived else "changes")
        proposal = directory / (("2026-07-01-" if archived else "") + change) / "proposal.md"
        proposal.parent.mkdir(parents=True, exist_ok=True)
        proposal.write_text("# Historical change\n", encoding="utf-8")
        return proposal

    def report(self, fields=None, *, name=None):
        self.register(self.other)
        path = self.run_dir.parent / (name or
            "post_spec-R2-1783054040265-dispatch-input-delivery-code-reviewer.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        if fields is None:
            # 原件的实际 frontmatter 值；正文不参与归属推断。
            fields = ("audit_type: post_spec\nverdict: PASS\nagent: code-reviewer\n"
                      "round: 2\ncheckpoint: convergence\ntimestamp: 1783054040265\n"
                      f"spec_id: {self.other}\nvote: PASS\n")
        path.write_text("---\n" + fields + "---\n# Historical report\n", encoding="utf-8")
        return path

    def assert_rejected(self, path, code, reason=None):
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        with self.assertRaises(self.mod.ExecutorError) as caught:
            self.build()
        self.assertEqual(caught.exception.error_code, code)
        if reason is not None:
            self.assertEqual(caught.exception.reason, reason)
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.assertFalse((self.scope() / "genesis.json").exists())
        self.assertFalse((self.scope() / "events").exists())
        self.assertFalse((self.run_dir / "workflow.js").exists())
        self.assertFalse((self.run_dir / "build-record.json").exists())

    def assert_accepted(self, path, legacy=True):
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        try:
            result = self.build()
        except self.mod.ExecutorError as error:
            self.fail(f"recognizable history rejected: {error.error_code}/{error.reason}")
        self.assertIs(result["resume_only"], False)
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        genesis = json.loads((self.scope() / "genesis.json").read_bytes())
        observation = json.loads(Path(genesis["origin_observation"]["path"]).read_bytes())
        row = next(item for item in observation["files"] if item["file"]["path"] == str(path))
        self.assertEqual(row, {"file": {"path": str(path), "sha256": digest},
                               "attribution": "OTHER_SCOPE"})
        if legacy:
            self.assertIn({"code": "LEGACY_CHECKPOINT_MODE", "file": row["file"]},
                          observation["warnings"])
        closure = json.loads((self.run_dir / "input-closure.json").read_bytes())
        entry = next(item for item in closure["sources"] if item["origin"] == str(path))
        self.assertEqual(Path(entry["blob"]["path"]).read_bytes(), raw)
        self.assertEqual(len(list((self.scope() / "events").glob("*.json"))), 1)
        self.assertTrue((self.run_dir / "workflow.js").is_file())
        before = {str(p): p.read_bytes() for p in self.scope().rglob("*") if p.is_file()}
        self.assertIs(self.build()["resume_only"], True)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.scope().rglob("*") if p.is_file()})

    def test_health_canonical_other_checkpoint_remains_accepted(self):
        path = self.report("checkpoint: pre_merge\ncontext: build-target\n",
                           name="pre_merge-R1-old-build-target-aggregated.md")
        self.assert_accepted(path, legacy=False)

    def test_real_legacy_other_scope_is_observed_and_frozen_without_rewrite(self):
        self.assert_accepted(self.report())

    def test_both_modes_and_explicit_context_aliases_are_recognized(self):
        for mode in ("convergence", "challenge"):
            for kind in ("id", "relative", "absolute", "archive_relative", "archive_absolute", "both"):
                with self.subTest(mode=mode, context=kind), self.fresh() as case:
                    archived = kind.startswith("archive")
                    proposal = case.register(case.other, archived=archived)
                    value = (case.other if kind in ("id", "both") else
                             str(proposal.relative_to(case.repo)) if kind.endswith("relative") else str(proposal))
                    fields = f"audit_type: post_spec\ncheckpoint: {mode}\ncontext: '{value}'\n"
                    if kind == "both":
                        fields += f"spec_id: {case.other}\n"
                    # 不额外注册 active 目录，否则 archive 测例会退化成双路径正向用例。
                    path = case.run_dir.parent / "post_spec-R2-legacy-code-reviewer.md"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("---\n" + fields + "---\n", encoding="utf-8")
                    case.assert_accepted(path)

    def test_legacy_current_scope_still_refuses_genesis(self):
        for mode in ("convergence", "challenge"):
            with self.subTest(mode=mode), self.fresh() as case:
                path = case.report(f"audit_type: post_spec\ncheckpoint: {mode}\nspec_id: build-target\n",
                                   name="post_spec-R9-old-build-target-aggregated.md")
                case.assert_rejected(path, "E_PREVIOUS_IDENTITY", "existing_scope_history_no_migration")

    def test_legacy_other_checkpoint_with_current_change_is_other_scope(self):
        path = self.report("audit_type: pre_merge\ncheckpoint: challenge\nspec_id: build-target\n",
                           name="pre_merge-R2-old-build-target-aggregated.md")
        self.assert_accepted(path)

    def test_true_checkpoint_conflict_and_unknown_mode_remain_rejected(self):
        for mode in ("pre_merge", "exploratory", "CONVERGENCE"):
            with self.subTest(mode=mode), self.fresh() as case:
                path = case.report(f"audit_type: post_spec\ncheckpoint: {mode}\nspec_id: {case.other}\n")
                case.assert_rejected(path, "E_POLICY_SOURCE", "historical_checkpoint_conflict")

    def test_missing_or_wrong_type_and_missing_prefix_are_not_legacy(self):
        for audit in ("", "audit_type: pre_merge\n"):
            with self.subTest(audit=audit), self.fresh() as case:
                path = case.report(audit + f"checkpoint: convergence\nspec_id: {case.other}\n")
                case.assert_rejected(path, "E_POLICY_SOURCE")
        path = self.report(f"audit_type: post_spec\ncheckpoint: convergence\nspec_id: {self.other}\n",
                           name="unregistered-R2-legacy.md")
        self.assert_rejected(path, "E_POLICY_SOURCE")

    def test_unknown_missing_or_contradictory_ownership_is_not_ignored(self):
        variants = ("", "spec_id: unknown-change\n", f"spec_id: {self.other}\ncontext: unknown-change\n",
                    f"spec_id: {self.other}\ncontext: build-target\n",
                    f"spec_id: {self.other}\nchange_id: build-target\n",
                    "spec_id: [build-target]\n", "context: ../build-target/proposal.md\n")
        for ownership in variants:
            with self.subTest(ownership=ownership), self.fresh() as case:
                path = case.report("audit_type: post_spec\ncheckpoint: convergence\n" + ownership)
                case.assert_rejected(path, "E_POLICY_SOURCE")

    def test_filename_explicit_other_change_conflicts_with_fields(self):
        self.register("build-target-extra")
        path = self.report(f"audit_type: post_spec\ncheckpoint: convergence\nspec_id: {self.other}\n",
                           name="post_spec-R2-old-build-target-extra-aggregated.md")
        self.assert_rejected(path, "E_POLICY_SOURCE", "historical_change_conflict")

    def test_known_longer_filename_id_is_not_confused_with_current_id(self):
        longer = "build-target-extra"
        self.register(longer)
        path = self.report(f"audit_type: post_spec\ncheckpoint: convergence\nspec_id: {longer}\n",
                           name=f"post_spec-R2-old-{longer}-aggregated.md")
        self.assert_accepted(path)

    def test_duplicate_fields_even_identical_or_canonical_first_are_rejected(self):
        base = f"audit_type: post_spec\ncheckpoint: convergence\nspec_id: {self.other}\n"
        for duplicate in ("audit_type: post_spec\n", "checkpoint: convergence\n",
                          f"spec_id: {self.other}\n", "context: build-target\ncontext: build-target\n",
                          "vote: PASS\nvote: PASS\n"):
            with self.subTest(duplicate=duplicate), self.fresh() as case:
                path = case.report(base + duplicate)
                case.assert_rejected(path, "E_POLICY_SOURCE", "historical_duplicate_field")
        path = self.report("checkpoint: post_spec\n" + base)
        self.assert_rejected(path, "E_POLICY_SOURCE", "historical_duplicate_field")

    def test_body_fields_do_not_supply_missing_frontmatter_identity(self):
        path = self.report("checkpoint: convergence\n")
        path.write_text(path.read_text() + f"audit_type: post_spec\nspec_id: {self.other}\n", encoding="utf-8")
        self.assert_rejected(path, "E_POLICY_SOURCE")

    def test_unclosed_frontmatter_is_not_legacy(self):
        path = self.report()
        path.write_text(path.read_text().replace("---\n# Historical report", "# Historical report"), encoding="utf-8")
        self.assert_rejected(path, "E_POLICY_SOURCE")

    def test_symlink_report_remains_rejected(self):
        original = self.report()
        link = original.with_name("post_spec-R3-linked.md")
        link.symlink_to(original)
        self.assert_rejected(link, "E_POLICY_SOURCE", "historical_symlink_unattributed")

    def test_read_error_does_not_create_cycle_or_script(self):
        path = self.report()
        read_bytes = Path.read_bytes
        def denied(source):
            if source == path:
                raise PermissionError("fixture historical read denied")
            return read_bytes(source)
        with patch.object(Path, "read_bytes", denied):
            with self.assertRaises(self.mod.ExecutorError) as caught:
                self.build()
        self.assertEqual((caught.exception.error_code, caught.exception.reason),
                         ("E_POLICY_SOURCE", "source_unreadable"))
        self.assertEqual(caught.exception.input_ref, str(path))
        self.assertFalse((self.scope() / "genesis.json").exists())
        self.assertFalse((self.scope() / "events").exists())
        self.assertFalse((self.run_dir / "workflow.js").exists())
        self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
