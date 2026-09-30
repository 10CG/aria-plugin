"""Tests for aria/skills/audit-engine/scripts/completeness_gate.py (SC-1~SC-22,
TASK-004/005/006 RED batches; see tasks.md's task list for the TASK-004 ->
TASK-006 boundary. Stage-scoped subsets of these subTests are also validated
incrementally at TASK-008~011, per detailed-tasks.yaml
metadata.stage_cells.cells/.rule -- SC method bodies below are not reordered
per-TASK; the yaml is the SOT for which cell belongs to which stage).

Spec: openspec/changes/pre-merge-completeness-gate-change-scope/{proposal.md,
detailed-tasks.yaml}. Expected values below are taken verbatim from
proposal.md's Success Criteria table (SC-1..SC-22), tasks.md's "读前必看" and
its TASK-003 fixture-premise matrix, corpus-freeze.md (SC-2/SC-4 literal
samples), config-loader/config-example.md (SC-15/SC-20's official scenario
A/B/C literals) and config-loader/DEFAULTS.json/SKILL.md (SC-21), and the
owner ruling
.aria/decisions/2026-09-30-199-b2-group1-spec-drift-rulings.md (SC-2's F-b
family retirement, SC-4's truncation-to-22 reading, SC-7(b)'s archive set C,
SC-9(2)'s two literal configs, SC-15(5)'s enabled_by assertion, SC-22(2)'s
WARN wording) -- never computed by calling the predicate under test. A
handful of assertions (flagged inline with "derived, not spec-literal") are
sound consequences of the spec's own rules rather than values quoted
verbatim from a table cell; they are called out at the point of use instead
of silently blended in.

completeness_gate.py does not exist yet at authoring time (TDD RED, this seat
writes only the test file; a separate seat implements the script later): every
test below first asserts the script file exists, inside its own ``subTest``,
so a missing script fails each subTest with AssertionError (not a bare
subprocess/FileNotFoundError or a json.JSONDecodeError).

Run:
    cd aria/skills/audit-engine/tests && python3 -B -m unittest test_completeness_gate -v
"""

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "completeness_gate.py"

# proposal.md §1.4's 16-key stdout envelope (SC-10 / TASK-005 verification 第 3 条).
STDOUT_KEYS = {
    "schema_version", "gate", "verdict", "error_kind", "scope_source",
    "change_ids", "checked_checkpoints", "no_prior_checkpoints", "results",
    "excluded_legacy_count", "unattributed_count", "unattributed",
    "scanned_dir_depth", "scan_status", "bypassed", "elapsed_ms",
}


class CompletenessGateTests(unittest.TestCase):
    maxDiff = None

    # ------------------------------------------------------------------
    # Fixture helpers. Every repo is a hermetic tmp dir (``git init -b
    # master``, per-test tempfile.mkdtemp + addCleanup) -- never the
    # enclosing Aria/aria checkout. completeness_gate.py reads
    # .aria/config.json and .aria/audit-reports/ straight off the
    # filesystem (no git involved for those two), so only the git
    # *diff* shape (tasks.md/src/docs/etc. changes) needs real commits.
    # ------------------------------------------------------------------

    def _new_repo(self):
        d = Path(tempfile.mkdtemp(prefix="cgate-"))
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self._git(d, "init", "-b", "master", "-q")
        self._git(d, "config", "user.email", "qa-fixture@example.invalid")
        self._git(d, "config", "user.name", "QA Fixture")
        return d

    def _git(self, repo, *args):
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, check=True,
        )

    def _write(self, repo, relpath, content=""):
        p = Path(repo) / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def _commit(self, repo, message="fixture"):
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "--no-gpg-sign", "-q", "-m", message)

    def _write_anchor(self, repo, change_id, level=2, inline_tasks=True,
                       archived=False, archive_prefix="2026-01-01"):
        """openspec/changes/{id}/proposal.md, or the archived-form path
        (S1's second anchor rule: archive dir name minus the date prefix
        equals change_id). ``inline_tasks`` controls whether a
        ``## Tasks`` section (matches ``^#{2,}\\s*Tasks``) is present --
        this is the SC-6 (c) A.2-artifact knob."""
        base = (f"openspec/archive/{archive_prefix}-{change_id}" if archived
                else f"openspec/changes/{change_id}")
        lines = [
            f"# Proposal: {change_id}", "",
            f"> **Level**: {level}", "",
            "## Why", "", "placeholder.", "",
            "## What", "", "placeholder.", "",
        ]
        if inline_tasks:
            lines += ["## Tasks", "", "1. placeholder task.", ""]
        return self._write(repo, f"{base}/proposal.md", "\n".join(lines))

    def _write_config(self, repo, checkpoints, mode="manual", enabled=True, max_rounds=None):
        """Hard constraints (1)+(3): every fixture pins audit.mode
        explicitly (default 'manual', so un-listed checkpoints resolve
        off via level 2d, not via the adaptive_rules ladder) and writes
        audit.enabled: true explicitly. max_rounds is omitted unless a
        caller passes it (cells quoting an official config-example.md
        scenario verbatim need it; every other fixture is unaffected)."""
        audit = {"enabled": enabled, "mode": mode, "checkpoints": dict(checkpoints)}
        if max_rounds is not None:
            audit["max_rounds"] = max_rounds
        cfg = {"audit": audit}
        self._write(repo, ".aria/config.json",
                    json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")

    def _write_report(self, repo, filename, content="placeholder\n"):
        return self._write(repo, f".aria/audit-reports/{filename}", content)

    def _run_gate(self, repo_path, diff_repo_path, base, change_ids=None,
                  no_spec=False, anchor_base=None, extra_args=None):
        """Hard constraint (4): --repo-path/--diff-repo-path always
        explicit. Invoked via subprocess (sys.executable -B), stdout is
        parsed as JSON by the caller; human-readable lines live on
        stderr only (proposal.md §1.4)."""
        self.assertTrue(
            SCRIPT_PATH.is_file(),
            f"completeness_gate.py 尚未实现 (TDD RED): {SCRIPT_PATH}",
        )
        argv = [sys.executable, "-B", str(SCRIPT_PATH),
                "--repo-path", str(repo_path),
                "--diff-repo-path", str(diff_repo_path),
                "--base", base]
        if anchor_base:
            argv += ["--anchor-base", anchor_base]
        for cid in (change_ids or []):
            argv += ["--change-id", cid]
        if no_spec:
            argv.append("--no-spec")
        if extra_args:
            argv += list(extra_args)
        return subprocess.run(argv, capture_output=True, text=True)

    def _find_result(self, data, checkpoint, change_id):
        for entry in data.get("results", []):
            if entry.get("checkpoint") == checkpoint and entry.get("change_id") == change_id:
                return entry
        return None

    # ------------------------------------------------------------------
    # SC-1 (proposal.md:457) -- hermetic case-1, issue reproduction: a
    # large pile of OTHER changes' post_implementation reports must not
    # count towards this change's own report.
    # ------------------------------------------------------------------
    def test_issue_case1_other_change_reports_do_not_count(self):
        with self.subTest(cell="SC-1.other-change-not-counted"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", inline_tasks=True)
            self._commit(repo, "base: anchor for x")
            self._git(repo, "checkout", "-b", "feature", "-q")
            self._write(repo, "openspec/changes/x/tasks.md", "# Tasks\n\n1. placeholder\n")
            self._write(repo, "src/a.py", "x = 1\n")
            self._commit(repo, "feature: implement x")
            for i in range(1, 38):
                self._write_report(
                    repo,
                    f"post_implementation-R1-{1785000000000 + i}-other-{i}-code-reviewer.md",
                )
            for i in range(1, 5):
                self._write_report(repo, f"post_spec-R{i}-2026-05-0{i}-x-tech-lead.md")
            self._write_config(repo, {"post_implementation": "convergence"})

            proc = self._run_gate(repo, repo, "master", change_ids=["x"])

            self.assertEqual(proc.returncode, 1, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["verdict"], "fail")
            entry = self._find_result(data, "post_implementation", "x")
            self.assertIsNotNone(entry, data.get("results"))
            self.assertEqual(entry["status"], "missing")
            self.assertIn("post_implementation@x", proc.stderr)

    # ------------------------------------------------------------------
    # SC-2 (proposal.md:458) -- real-corpus filename-shape attribution.
    # Samples are corpus-freeze.md §3.1-§3.5 literal filenames (not
    # re-derived here). F-b (3 pre_merge-prefixed samples) is retired
    # from this SC's assertion surface per the owner ruling 2026-09-30
    # (corpus-freeze.md §8.3 / decisions doc §1): pre_merge is one of
    # Step 3's five structural exclusions, so those 3 files can never
    # surface in `results`/the two exclusion counts under a *correct*
    # implementation -- asserting their attribution would be a
    # necessarily-red assertion.
    # ------------------------------------------------------------------
    def test_real_corpus_shapes_token_bounded_match(self):
        with self.subTest(cell="SC-2.corpus-freeze-six-families"):
            ids = [
                "state-scanner-inter-cycle-surfacing",
                "runtime-probe-archive-gate-integration",
                "phase-c-integrator-ci-path-coverage",
                "premerge-gate-mainbranch-failclosed",
                "state-scanner-git-operation-awareness",
            ]
            repo = self._new_repo()
            for cid in ids:
                self._write_anchor(repo, cid, inline_tasks=True)

            # F-a (2) + F-c/F-d (5 distinct; 1 file shared between the two
            # families, corpus-freeze.md:694-699) -> attribution-correctness
            # oracle, per corpus-freeze.md §3.1/§3.2/§3.3's independent
            # (frontmatter-sourced) labels.
            expected_pairs = {
                ("post_spec", "state-scanner-inter-cycle-surfacing"): [
                    "post_spec-R1-2026-05-08-state-scanner-inter-cycle-surfacing.md",
                    "post_spec-R2-2026-05-08-state-scanner-inter-cycle-surfacing.md",
                ],
                ("post_planning", "runtime-probe-archive-gate-integration"): [
                    "post_planning-FINAL-1783300200007-runtime-probe-archive-gate-integration-aggregated.md",
                ],
                ("post_spec", "runtime-probe-archive-gate-integration"): [
                    "post_spec-FINAL-1783275800006-runtime-probe-archive-gate-integration-aggregated.md",
                ],
                ("post_planning", "phase-c-integrator-ci-path-coverage"): [
                    "post_planning-R1-1785010000000-phase-c-integrator-ci-path-coverage-aggregated.md",
                ],
                ("post_planning", "premerge-gate-mainbranch-failclosed"): [
                    "post_planning-R1-1786280000000-premerge-gate-mainbranch-failclosed-aggregate.md",
                ],
                ("post_spec", "state-scanner-git-operation-awareness"): [
                    "post_spec-R1R2-2026-06-04-state-scanner-git-operation-awareness.md",
                ],
            }
            for filenames in expected_pairs.values():
                for fname in filenames:
                    self._write_report(repo, fname)

            # F-e (6, real 2-field legacy) + F-f (3, unattributed) -- only
            # "no cross-bucket leakage" is asserted, per proposal.md:458
            # (ii): legacy/unattributed classification itself is not this
            # SC's oracle (no independent source for those two buckets).
            files_legacy = [
                "post_planning-2026-04-11T0530Z.md",
                "post_spec-2026-04-01T23.md",
                "post_spec-2026-04-09T1240Z.md",
                "post_spec-2026-04-09T1315Z.md",
                "post_spec-2026-04-12T0400Z.md",
                "post_spec-2026-04-12T0800Z.md",
            ]
            files_unattributed = [
                "post_planning-R2-CONVERGED-dispatch-input-delivery.md",
                "post_spec-R1-1785112156889-phase-c-gate-path-coverage-backend-architect.md",
                "post_spec-R1-1785112156889-phase-c-gate-path-coverage-code-reviewer.md",
            ]
            for fname in files_legacy + files_unattributed:
                self._write_report(repo, fname)

            self._write_config(
                repo, {"post_spec": "convergence", "post_planning": "convergence"}
            )
            self._commit(repo, "corpus fixture")

            proc = self._run_gate(repo, repo, "master", change_ids=ids)
            data = json.loads(proc.stdout)

            # (i) F-a/F-c/F-d attribution correctness (F-b retired, see
            # class-level note above / corpus-freeze.md §8.3).
            for (checkpoint, change_id), filenames in expected_pairs.items():
                entry = self._find_result(data, checkpoint, change_id)
                self.assertIsNotNone(entry, (checkpoint, change_id, data.get("results")))
                self.assertEqual(sorted(entry["matched"]), sorted(filenames))

            # (ii) F-e/F-f: no cross-bucket leakage.
            matched_union = set()
            for entry in data["results"]:
                matched_union.update(entry.get("matched", []))
            for fname in files_legacy + files_unattributed:
                self.assertNotIn(fname, matched_union)
            for fname in files_legacy:
                self.assertNotIn(fname, data["unattributed"])
            total = (
                len(matched_union) + data["unattributed_count"] + data["excluded_legacy_count"]
            )
            self.assertLessEqual(total, 16)

    # ------------------------------------------------------------------
    # SC-3 (proposal.md:459) -- bounded containment (§1.2 rule 3): a
    # short id that is a prefix/suffix/infix of a longer real id must
    # not be falsely attributed the longer id's report.
    # ------------------------------------------------------------------
    def test_bounded_containment_excludes_all_three_shapes(self):
        with self.subTest(cell="SC-3.1-prefix-type"):
            self._assert_bounded_containment(
                short_id="aria-orchestrator",
                long_id="aria-orchestrator-divestiture",
                long_report="post_spec-R1-2026-05-01-aria-orchestrator-divestiture.md",
                short_report="post_spec-R1-2026-05-01-aria-orchestrator.md",
            )
        with self.subTest(cell="SC-3.2-suffix-type"):
            self._assert_bounded_containment(
                short_id="gate-scope",
                long_id="pre-merge-gate-scope",
                long_report="post_spec-R1-2026-05-01-pre-merge-gate-scope.md",
                short_report="post_spec-R1-2026-05-01-gate-scope.md",
            )
        with self.subTest(cell="SC-3.3-infix-type"):
            self._assert_bounded_containment(
                short_id="gate",
                long_id="pre-merge-gate-scope",
                long_report="post_spec-R1-2026-05-01-pre-merge-gate-scope.md",
                short_report="post_spec-R1-2026-05-01-gate.md",
            )

    def _assert_bounded_containment(self, short_id, long_id, long_report, short_report):
        # NOTE (derived, not spec-literal for the suffix/infix shapes):
        # proposal.md:459 spells out "both reports present -> each present,
        # matched sets don't cross" only for case (1) (the prefix shape);
        # cases (2)/(3) (suffix/infix) literally say only "missing" for the
        # long-only variant ("(3) ... 同上" points back to (2), which never
        # states a both-present outcome). Applying the same non-cross-
        # contamination check to all three shapes via this shared helper is
        # a straightforward consequence of the one non-containment rule
        # (§1.2 rule 3) that all three cases test -- it cannot fail on a
        # correct implementation -- but it is this test's extension, not a
        # value quoted from the table.
        #
        # (only the long id's report exists) short id must be missing --
        # a naive containment check would false-match it (R1 bug class).
        repo = self._new_repo()
        self._write_anchor(repo, short_id, inline_tasks=True)
        self._write_anchor(repo, long_id, inline_tasks=True)
        self._write_report(repo, long_report)
        self._write_config(repo, {"post_spec": "convergence"})
        self._commit(repo, "only-long-report")
        proc = self._run_gate(repo, repo, "master", change_ids=[short_id, long_id])
        data = json.loads(proc.stdout)
        short_entry = self._find_result(data, "post_spec", short_id)
        self.assertIsNotNone(short_entry, data.get("results"))
        self.assertEqual(short_entry["status"], "missing")

        # (both reports exist) matched sets must not cross-contaminate.
        repo2 = self._new_repo()
        self._write_anchor(repo2, short_id, inline_tasks=True)
        self._write_anchor(repo2, long_id, inline_tasks=True)
        self._write_report(repo2, long_report)
        self._write_report(repo2, short_report)
        self._write_config(repo2, {"post_spec": "convergence"})
        self._commit(repo2, "both-reports")
        proc2 = self._run_gate(repo2, repo2, "master", change_ids=[short_id, long_id])
        data2 = json.loads(proc2.stdout)
        short_entry2 = self._find_result(data2, "post_spec", short_id)
        long_entry2 = self._find_result(data2, "post_spec", long_id)
        self.assertIsNotNone(short_entry2, data2.get("results"))
        self.assertIsNotNone(long_entry2, data2.get("results"))
        self.assertEqual(short_entry2["status"], "present")
        self.assertEqual(long_entry2["status"], "present")
        self.assertEqual(short_entry2["matched"], [short_report])
        self.assertEqual(long_entry2["matched"], [long_report])

    # ------------------------------------------------------------------
    # SC-4 (proposal.md:460) -- excluded_legacy_count / unattributed_count
    # kept separate; the four-file corpus and the truncation-to-22 corpus
    # are proposal-text literals, not sampled (corpus-freeze.md §5: "与
    # 本仓真实语料无关, 不需要, 也不应该从本文件另行采样"). Truncation count
    # (22, not 23) and the WARN line's exact wording follow the owner
    # ruling 2026-09-30 §3 item 1 (decisions doc) and proposal.md §1.2's
    # comma-space connector rule.
    # ------------------------------------------------------------------
    def test_legacy_vs_unattributed_counts_split(self):
        with self.subTest(cell="SC-4.1-legacy-vs-unattributed-split"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", inline_tasks=True)
            self._write_report(repo, "post_spec-2026-04-11T0530Z.md")
            self._write_report(repo, "post_planning-2026-04-11T0530Z.md")
            self._write_report(repo, "post_spec-R1-2026-05-01-x.md")
            self._write_report(repo, "post_planning-R2-CONVERGED-trunc-id.md")
            self._write_config(
                repo, {"post_spec": "convergence", "post_planning": "convergence"}
            )
            self._commit(repo, "sc4.1")

            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)

            self.assertEqual(data["excluded_legacy_count"], 2)
            self.assertEqual(data["unattributed_count"], 1)
            self.assertEqual(
                data["unattributed"], ["post_planning-R2-CONVERGED-trunc-id.md"]
            )
            entry = self._find_result(data, "post_spec", "x")
            self.assertIsNotNone(entry, data.get("results"))
            self.assertEqual(entry["matched"], ["post_spec-R1-2026-05-01-x.md"])

        with self.subTest(cell="SC-4.2-truncation-to-20"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", inline_tasks=True)
            filenames = [f"post_spec-R1-CONVERGED-unattr-{i:02d}.md" for i in range(1, 23)]
            for fname in filenames:
                self._write_report(repo, fname)
            self._write_config(
                repo, {"post_spec": "convergence", "post_planning": "convergence"}
            )
            self._commit(repo, "sc4.2")

            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)

            self.assertEqual(data["unattributed_count"], 22)
            self.assertEqual(data["unattributed"], sorted(filenames))
            first_20 = sorted(filenames)[:20]
            # Exact template (proposal.md §1.2 + §1.4, byte-checked against
            # the source file): "[WARN] unattributed reports
            # (checked={cp1},{cp2},...): N 份 — <20 names>, … 其余 K 份见
            # stdout 的 `unattributed`", comma-space joins throughout, em
            # dash U+2014, ellipsis U+2026.
            expected_warn = (
                "[WARN] unattributed reports (checked=post_planning, post_spec): "
                f"22 份 — {', '.join(first_20)}, … 其余 2 份见 stdout 的 `unattributed`"
            )
            # Whole-line equality (proposal.md:460's own rewrite: "现改为对
            # 整条 WARN 行逐字相等比对"; TASK-004 verification 第 5 条 matches)
            # -- a plain assertIn would also pass an implementation that
            # prepends/appends stray characters to the same line.
            stderr_lines = proc.stderr.splitlines()
            self.assertIn(expected_warn, stderr_lines)
            warn_lines = [
                l for l in stderr_lines if l.startswith("[WARN] unattributed reports")
            ]
            self.assertEqual(len(warn_lines), 1, stderr_lines)

    # ------------------------------------------------------------------
    # SC-5 (proposal.md:461) -- not_applicable (b) "Phase A-only" channel
    # for post_implementation. Split across three test methods per
    # proposal.md:461's own name list (TASK-004 verification, test-name
    # entry):
    #   test_phase_a_only_not_applicable      -> the positive baseline
    #   test_md_and_docs_diff_still_missing   -> diff variants that still
    #                                             must NOT get a free pass
    #   test_empty_diff_is_missing            -> the empty-diff boundary
    #                                             (with/without --no-spec)
    # ------------------------------------------------------------------
    def _sc5_phase_a_repo(self, extra_files=None):
        """Base commit = README only, on master. Feature commit (on a
        'feature' branch checked out from that base) = the anchor for x +
        tasks.md + the post_spec report a real Phase-A-only PR carries (all
        three paths fall inside openspec/changes/x/** ∪
        .aria/audit-reports/**), plus whatever extra_files the caller adds
        to the SAME diff. All callers invoke _run_gate(..., "master", ...),
        so --base must resolve to an ancestor commit the feature branch has
        actually diverged from -- putting the anchor in the base commit
        (as an earlier revision of this helper did) left current-branch ==
        "master" itself, so merge-base(HEAD, master) == HEAD and the diff
        proposal.md:461/462's not_applicable(b) channel requires non-empty
        was always []. A correct implementation would then hit "missing"
        (empty diff, proposal.md:263) instead of not_applicable on every
        caller of this helper (SC-5.main, SC-5.1-5.3, SC-10.pass,
        SC-17.2/2b) -- the exact false-red this helper exists to avoid."""
        repo = self._new_repo()
        self._write(repo, "README.md", "base\n")
        self._commit(repo, "base: readme only")
        self._git(repo, "checkout", "-b", "feature", "-q")
        self._write_anchor(repo, "x", inline_tasks=True)
        self._write(repo, "openspec/changes/x/tasks.md", "# Tasks\n\n1. placeholder\n")
        self._write(
            repo, ".aria/audit-reports/post_spec-R1-2026-01-01-x-tech-lead.md", "placeholder\n"
        )
        for rel, content in (extra_files or {}).items():
            self._write(repo, rel, content)
        self._commit(repo, "feature: phase-a artifacts")
        self._write_config(repo, {"post_implementation": "convergence"})
        return repo

    def test_phase_a_only_not_applicable(self):
        with self.subTest(cell="SC-5.main-phase-a-only"):
            repo = self._sc5_phase_a_repo()
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            entry = self._find_result(data, "post_implementation", "x")
            self.assertIsNotNone(entry, data.get("results"))
            self.assertEqual(entry["status"], "not_applicable")
            self.assertEqual(entry["reason"], "phase-a-only-no-implementation")
            self.assertEqual(data["verdict"], "pass")
            self.assertEqual(proc.returncode, 0)
            self.assertIn("[INFO]", proc.stderr)
            self.assertIn("not_applicable", proc.stderr)

    def test_md_and_docs_diff_still_missing(self):
        # Each variant adds one path outside openspec/changes/x/** union
        # .aria/audit-reports/** to the Phase-A-only diff, which must
        # disqualify the not_applicable(b) channel and fall through to
        # "missing" (R1 Critical 3 / R2 rework's docs+archive+openspec
        # -corpus carve-outs).
        cases = {
            "SC-5.1-src-file-added": {"src/a.py": "x = 1\n"},
            "SC-5.2-md-skill-file-added": {
                "aria/skills/audit-engine/SKILL.md": "# prescriptive skill doc\n"
            },
            "SC-5.3-docs-file-added": {"docs/x.md": "# docs\n"},
        }
        for cell, extra in cases.items():
            with self.subTest(cell=cell):
                repo = self._sc5_phase_a_repo(extra)
                proc = self._run_gate(repo, repo, "master", change_ids=["x"])
                data = json.loads(proc.stdout)
                entry = self._find_result(data, "post_implementation", "x")
                self.assertIsNotNone(entry, data.get("results"))
                self.assertEqual(entry["status"], "missing")
                self.assertEqual(data["verdict"], "fail")
                self.assertEqual(proc.returncode, 1)

        with self.subTest(cell="SC-5.5-cross-repo-openspec-only"):
            # not_applicable(b) is disabled cross-repo regardless of diff
            # shape (proposal.md §1 fail-closed clause). tmpA carries the
            # anchor+config, tmpB carries an openspec-only diff.
            repo_a = self._new_repo()
            self._write_anchor(repo_a, "x", inline_tasks=True)
            self._write_config(repo_a, {"post_implementation": "convergence"})
            self._commit(repo_a, "tmpA: anchor + config")
            repo_b = self._new_repo()
            self._write(repo_b, "README.md", "tmpB base\n")
            self._commit(repo_b, "tmpB: base")
            self._git(repo_b, "checkout", "-b", "feature", "-q")
            self._write(repo_b, "openspec/changes/x/tasks.md", "# Tasks\n\n1. placeholder\n")
            self._commit(repo_b, "tmpB: feature diff, openspec-only")
            proc = self._run_gate(repo_a, repo_b, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            entry = self._find_result(data, "post_implementation", "x")
            self.assertIsNotNone(entry, data.get("results"))
            self.assertEqual(entry["status"], "missing")
            self.assertEqual(data["verdict"], "fail")

        with self.subTest(cell="SC-5.6-archive-only-pr"):
            # openspec/archive/** was removed from the not_applicable(b)
            # allow-list (R2 rework): a pure archival move proves Phase B
            # already happened, so it must not read as Phase-A-only.
            repo = self._new_repo()
            self._write(repo, "README.md", "base\n")
            self._commit(repo, "base: empty")
            self._git(repo, "checkout", "-b", "feature", "-q")
            self._write_anchor(repo, "x", inline_tasks=True, archived=True)
            self._write(repo, "openspec/archive/2026-01-01-x/tasks.md", "# Tasks\n\n1. placeholder\n")
            self._commit(repo, "feature: archive-only")
            self._write_config(repo, {"post_implementation": "convergence"})
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            entry = self._find_result(data, "post_implementation", "x")
            self.assertIsNotNone(entry, data.get("results"))
            self.assertEqual(entry["status"], "missing")

        with self.subTest(cell="SC-5.7-deliverable-is-openspec-corpus"):
            # Touching a *different*, already-archived change's proposal
            # is still outside openspec/changes/x/**, so it must also
            # disqualify not_applicable(b).
            repo = self._new_repo()
            self._write(repo, "README.md", "base\n")
            self._commit(repo, "base: empty")
            self._git(repo, "checkout", "-b", "feature", "-q")
            self._write_anchor(repo, "x", inline_tasks=True)
            self._write_anchor(
                repo, "spec-drafter", inline_tasks=True, archived=True,
                archive_prefix="2025-12-16",
            )
            self._commit(repo, "feature: two openspec proposals (this change + archived sibling)")
            self._write_config(repo, {"post_implementation": "convergence"})
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            entry = self._find_result(data, "post_implementation", "x")
            self.assertIsNotNone(entry, data.get("results"))
            self.assertEqual(entry["status"], "missing")

    def test_empty_diff_is_missing(self):
        with self.subTest(cell="SC-5.4-empty-diff"):
            # Single commit, --base points at the same commit as HEAD ->
            # zero-line diff. Empty diff does not satisfy not_applicable
            # (b)'s "diff non-empty" precondition, so it must fall to
            # "missing" (space does not get a free pass).
            repo = self._new_repo()
            self._write_anchor(repo, "x", inline_tasks=True)
            self._write_config(repo, {"post_implementation": "convergence"})
            self._commit(repo, "single commit, zero diff vs itself")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            entry = self._find_result(data, "post_implementation", "x")
            self.assertIsNotNone(entry, data.get("results"))
            self.assertEqual(entry["status"], "missing")
            self.assertEqual(data["verdict"], "fail")

        with self.subTest(cell="SC-5.8-no-spec-empty-diff"):
            # --no-spec's P2a precondition: anchor-face diff must be
            # non-empty, else error_kind=no_spec_unverifiable (exit 2) --
            # must NOT be read as a blanket not_applicable/level1-no-spec
            # (that would be a vacuous-truth full bypass, Critical
            # 34507656(b)). checkpoints defensively pinned per the matrix
            # note even though P2a short-circuits before P3/P4 read it.
            repo = self._new_repo()
            self._write_config(repo, {"post_spec": "convergence"})
            self._commit(repo, "single commit, zero diff vs itself")
            proc = self._run_gate(repo, repo, "master", no_spec=True)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["error_kind"], "no_spec_unverifiable")
            self.assertNotEqual(data.get("verdict"), "pass")

    # ------------------------------------------------------------------
    # SC-6 (proposal.md:462) -- not_applicable (c) "no A.2 artifact yet"
    # channel for post_planning. Four hermetic cells per tasks.md's
    # "重写 c": the real-repo self-referential (3)-branch snapshot moves
    # to TASK-022's live run (295KB snapshot, not plugin-distributed), so
    # only the four independently-constructed cells below live here.
    # ------------------------------------------------------------------
    def test_post_planning_a2_artifact_includes_inline_tasks(self):
        with self.subTest(cell="SC-6.1-no-tasks-section"):
            # change dir has only proposal.md, and it has no ## Tasks
            # section -> no A.2 artifact at all -> not_applicable.
            repo = self._new_repo()
            self._write_anchor(repo, "x", inline_tasks=False)
            self._write_config(repo, {"post_planning": "convergence"})
            self._commit(repo, "sc6.1: proposal-only, no Tasks section")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            entry = self._find_result(data, "post_planning", "x")
            self.assertIsNotNone(entry, data.get("results"))
            self.assertEqual(entry["status"], "not_applicable")
            self.assertEqual(entry["reason"], "no-a2-artifact")

        with self.subTest(cell="SC-6.2-three-line-tasks-present"):
            # a trivial tasks.md exists -> an A.2 artifact exists -> the
            # gate must not grant a free pass just because it is small
            # ("做了但简单" 不豁免) -> missing (no report either).
            repo = self._new_repo()
            self._write_anchor(repo, "x", inline_tasks=False)
            self._write(repo, "openspec/changes/x/tasks.md", "1. a\n2. b\n3. c\n")
            self._write_config(repo, {"post_planning": "convergence"})
            self._commit(repo, "sc6.2: trivial tasks.md present")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            entry = self._find_result(data, "post_planning", "x")
            self.assertIsNotNone(entry, data.get("results"))
            self.assertEqual(entry["status"], "missing")

        with self.subTest(cell="SC-6.3-inline-tasks-no-file"):
            # Level-2 standard shape: no tasks.md file, but proposal.md
            # carries an inline ## Tasks list -> that IS an A.2 artifact
            # -> must NOT be not_applicable (this SC's Critical-4 red
            # line: naive "two files present?" checks would wrongly
            # exempt every Level-2 change's post_planning check).
            repo = self._new_repo()
            self._write_anchor(repo, "x", inline_tasks=True)
            self._write_config(repo, {"post_planning": "convergence"})
            self._commit(repo, "sc6.3: inline Tasks, no tasks.md file")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            entry = self._find_result(data, "post_planning", "x")
            self.assertIsNotNone(entry, data.get("results"))
            self.assertEqual(entry["status"], "missing")

        with self.subTest(cell="SC-6.4-archived-form"):
            # Same three branches, re-run against the archived-form
            # anchor (openspec/archive/2026-01-01-x/), sequentially in
            # this one subTest per the matrix's "multi-run cell" style.
            variants = [
                (False, False, "not_applicable", "no-a2-artifact"),  # case (1)
                (False, True, "missing", None),  # case (2)
                (True, False, "missing", None),  # case (3)
            ]
            for inline_tasks, add_tasks_file, expected_status, expected_reason in variants:
                repo = self._new_repo()
                self._write_anchor(repo, "x", inline_tasks=inline_tasks, archived=True)
                if add_tasks_file:
                    self._write(
                        repo, "openspec/archive/2026-01-01-x/tasks.md", "1. a\n2. b\n3. c\n"
                    )
                self._write_config(repo, {"post_planning": "convergence"})
                self._commit(
                    repo, f"sc6.4 variant inline_tasks={inline_tasks} tasks_file={add_tasks_file}"
                )
                proc = self._run_gate(repo, repo, "master", change_ids=["x"])
                data = json.loads(proc.stdout)
                entry = self._find_result(data, "post_planning", "x")
                self.assertIsNotNone(entry, data.get("results"))
                self.assertEqual(entry["status"], expected_status)
                if expected_reason:
                    self.assertEqual(entry["reason"], expected_reason)


    # ------------------------------------------------------------------
    # TASK-005 (1.5) additions: SC-7~SC-10 and SC-18's excluded branch.
    # Helpers below extend (never edit) the TASK-004 helpers above --
    # _write_config's signature/behavior is untouched; _write_config_ext
    # adds the audit-level knobs this batch needs (allow_incomplete_
    # checkpoints / allow_dangling_change_ids / adaptive_rules / an
    # omittable checkpoints block) without touching any SC-1~SC-6 call
    # site. Expected values throughout are taken verbatim from
    # proposal.md SC-7~SC-10/SC-18, tasks.md's 读前必看 (items 6-9, 23-24)
    # and the owner ruling .aria/decisions/2026-09-30-199-b2-group1-spec
    # -drift-rulings.md §2/§3 (SC-7(b)'s archive set C; SC-9(2)'s two
    # literal configs) -- never computed by calling the predicate under
    # test.
    # ------------------------------------------------------------------

    def _write_config_ext(self, repo, checkpoints=None, mode="manual", enabled=True,
                           allow_incomplete_checkpoints=None,
                           allow_dangling_change_ids=None,
                           adaptive_rules=None, max_rounds=None):
        """Like _write_config, but checkpoints=None omits the
        "checkpoints" key entirely (some fixtures require literally "no
        checkpoints block") and exposes the two allow_* flags plus
        adaptive_rules. max_rounds is omitted unless a caller passes it
        (official-scenario cells need it quoted verbatim; every other
        fixture is unaffected)."""
        audit = {"enabled": enabled, "mode": mode}
        if checkpoints is not None:
            audit["checkpoints"] = dict(checkpoints)
        if allow_incomplete_checkpoints is not None:
            audit["allow_incomplete_checkpoints"] = allow_incomplete_checkpoints
        if allow_dangling_change_ids is not None:
            audit["allow_dangling_change_ids"] = allow_dangling_change_ids
        if adaptive_rules is not None:
            audit["adaptive_rules"] = adaptive_rules
        if max_rounds is not None:
            audit["max_rounds"] = max_rounds
        self._write(repo, ".aria/config.json",
                    json.dumps({"audit": audit}, ensure_ascii=False, indent=2) + "\n")

    def _write_bad_config(self, repo):
        """P0's config_unreadable fixture: syntactically invalid JSON."""
        self._write(repo, ".aria/config.json", "{ this is not valid json")

    def _write_anchor_no_level(self, repo, change_id):
        """S1 anchor with no parseable ``> **Level**:`` line anywhere --
        SC-9(4)'s spec_level_undetermined trigger."""
        lines = [
            f"# Proposal: {change_id}", "",
            "## Why", "", "placeholder.", "",
            "## What", "", "placeholder.", "",
            "## Tasks", "", "1. placeholder task.", "",
        ]
        return self._write(repo, f"openspec/changes/{change_id}/proposal.md", "\n".join(lines))

    def _run_gate_argv(self, argv_extra):
        """Raw invocation for the argparse-negative cells (SC-10): hard
        constraint (4)'s --repo-path/--diff-repo-path-always-explicit
        rule explicitly carves these out."""
        self.assertTrue(
            SCRIPT_PATH.is_file(),
            f"completeness_gate.py 尚未实现 (TDD RED): {SCRIPT_PATH}",
        )
        argv = [sys.executable, "-B", str(SCRIPT_PATH), *argv_extra]
        return subprocess.run(argv, capture_output=True, text=True)

    def _assert_required_arg_missing(self, stderr, flag):
        """argparse's usage summary line unconditionally lists every
        defined flag regardless of which one is actually absent from the
        invocation (and "--repo-path" is even a plain substring of the
        stderr text argparse emits for a missing "--diff-repo-path") -- a
        bare assertIn(flag, stderr) would pass no matter which required
        flag was the one actually missing. The one line that names the
        SPECIFIC missing flag(s) is argparse's own
        "error: the following arguments are required: ..." line."""
        required_lines = [
            l for l in stderr.splitlines()
            if "the following arguments are required" in l
        ]
        self.assertEqual(len(required_lines), 1, stderr)
        required_names = [
            n.strip() for n in required_lines[0].split("required:", 1)[1].split(",")
        ]
        self.assertIn(flag, required_names, required_lines)

    def _timed_run_gate(self, *args, **kwargs):
        """Wraps _run_gate with a test-side wall-clock bound (ms,
        ceil'd) for elapsed_ms's upper-bound assertion (tasks.md 读前
        必看第 24 条 / TASK-005 verification 第 4 条)."""
        t0 = time.monotonic()
        proc = self._run_gate(*args, **kwargs)
        t1 = time.monotonic()
        return proc, math.ceil((t1 - t0) * 1000)

    def _assert_elapsed_ms_bounded(self, data, upper_bound_ms):
        self.assertIsInstance(data["elapsed_ms"], int)
        self.assertNotIsInstance(data["elapsed_ms"], bool)
        self.assertGreaterEqual(data["elapsed_ms"], 1)
        self.assertLessEqual(data["elapsed_ms"], upper_bound_ms)

    def _assert_elapsed_ms_type_only(self, data):
        self.assertIsInstance(data["elapsed_ms"], int)
        self.assertNotIsInstance(data["elapsed_ms"], bool)
        self.assertGreaterEqual(data["elapsed_ms"], 0)

    def _bypass_missing_repo(self):
        """Shared by SC-9.1 and SC-10.bypassed-verdict-keyset (matrix:
        "SC-10.bypassed-verdict-keyset 复用 SC-9.1 的 fixture"):
        allow_incomplete_checkpoints=true + one nonexistent post_spec
        report for change x -> one missing pair -> verdict=bypassed."""
        repo = self._new_repo()
        self._write_anchor(repo, "x", inline_tasks=True)
        self._write_config_ext(
            repo, checkpoints={"post_spec": "convergence"},
            allow_incomplete_checkpoints=True,
        )
        self._commit(repo, "sc9.1/sc10.bypassed: anchor + config, zero reports")
        return repo

    # ------------------------------------------------------------------
    # SC-7 (proposal.md:463) -- change-scope resolution S1->S4, split
    # across three test methods per the SC row's own trailing name list.
    # This method covers the base S1-S4 matrix plus (e) (adaptive
    # Level-1's scope-side outcome); (a)/(b) live in
    # test_rename_and_anchor_semantics, (c)/(d) in
    # test_allow_dangling_inherited.
    # ------------------------------------------------------------------
    def test_scope_resolution_matrix(self):
        with self.subTest(cell="SC-7.diff-multi-scope"):
            repo = self._new_repo()
            self._write(repo, "README.md", "base\n")
            self._commit(repo, "base")
            self._git(repo, "checkout", "-b", "feature", "-q")
            self._write_anchor(repo, "a", inline_tasks=True)
            self._write_anchor(repo, "b", inline_tasks=True)
            self._commit(repo, "feature: add change dirs a and b (no --change-id given)")
            self._write_report(repo, "post_spec-R1-2026-05-01-a.md")
            self._write_config(repo, {"post_spec": "convergence"})
            proc = self._run_gate(repo, repo, "master")
            data = json.loads(proc.stdout)
            self.assertEqual(data["scope_source"], "diff")
            self.assertEqual(sorted(data["change_ids"]), ["a", "b"])
            self.assertEqual(data["checked_checkpoints"], ["post_spec"])
            entry_a = self._find_result(data, "post_spec", "a")
            entry_b = self._find_result(data, "post_spec", "b")
            self.assertIsNotNone(entry_a, data.get("results"))
            self.assertIsNotNone(entry_b, data.get("results"))
            self.assertEqual(entry_a["status"], "present")
            self.assertEqual(entry_b["status"], "missing")
            self.assertEqual(data["verdict"], "fail")
            self.assertEqual(proc.returncode, 1)

        with self.subTest(cell="SC-7.S4-unresolved"):
            repo = self._new_repo()
            self._write(repo, "README.md", "base\n")
            self._commit(repo, "single commit: nothing touches openspec/changes/**, no --no-spec")
            self._write_config(repo, {})
            proc = self._run_gate(repo, repo, "master")
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["error_kind"], "change_scope_unresolved")
            self.assertEqual(data["verdict"], "error")

        with self.subTest(cell="SC-7.no-spec-contradicted"):
            repo = self._new_repo()
            self._write(repo, "README.md", "base\n")
            self._commit(repo, "base")
            self._git(repo, "checkout", "-b", "feature", "-q")
            self._write_anchor(repo, "x", inline_tasks=True)
            self._commit(repo, "feature: touches openspec/changes/x/ while --no-spec is claimed")
            self._write_config(repo, {})
            proc = self._run_gate(repo, repo, "master", no_spec=True)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["error_kind"], "no_spec_contradicted")
            self.assertEqual(data["verdict"], "error")

        with self.subTest(cell="SC-7.no-spec-legal"):
            repo = self._new_repo()
            self._write(repo, "README.md", "base\n")
            self._commit(repo, "base")
            self._git(repo, "checkout", "-b", "feature", "-q")
            self._write(repo, "src/a.py", "x = 1\n")
            self._commit(repo, "feature: non-empty diff, does not touch openspec/changes/")
            self._write_config(repo, {"post_spec": "convergence"})
            proc = self._run_gate(repo, repo, "master", no_spec=True)
            data = json.loads(proc.stdout)
            self.assertGreaterEqual(len(data["results"]), 1, data.get("results"))
            self.assertEqual(data["checked_checkpoints"], ["post_spec"])
            self.assertEqual(data["scope_source"], "no_spec")
            self.assertEqual(data["change_ids"], [])
            for entry in data["results"]:
                self.assertIsNone(entry["change_id"])
                self.assertEqual(entry["status"], "not_applicable")
                self.assertEqual(entry["reason"], "level1-no-spec")
            self.assertEqual(data["verdict"], "pass")
            self.assertEqual(proc.returncode, 0)

        with self.subTest(cell="SC-7.typo-unanchored"):
            repo = self._new_repo()
            self._write_anchor(repo, "other-change", inline_tasks=True)
            self._write_anchor(repo, "other-archived", inline_tasks=True, archived=True,
                                archive_prefix="2026-02-02")
            self._write_config(repo, {})
            self._commit(repo, "decoy anchors only, none named typo")
            proc = self._run_gate(repo, repo, "master", change_ids=["typo"])
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["error_kind"], "change_id_unanchored")
            self.assertEqual(data["verdict"], "error")

        with self.subTest(cell="SC-7.e-adaptive-level1"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", level=1, inline_tasks=True)
            self._write_config_ext(
                repo, checkpoints=None, mode="adaptive",
                adaptive_rules={"level_1": "off", "level_2": "convergence", "level_3": "challenge"},
            )
            self._commit(repo, "sc7.e: Level 1 change, adaptive mode, no explicit checkpoints")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["verdict"], "pass")
            self.assertTrue(data["no_prior_checkpoints"])

    # ------------------------------------------------------------------
    # SC-7(a)/(b) (proposal.md:463) -- rename semantics (S2 + --no-renames)
    # and anchor literal-matching (S1, not glob). (b)'s archive set C
    # follows the owner ruling 2026-09-30 §2 (decisions doc): C holds
    # BOTH aria-orchestrator-divestiture (real precedent,
    # openspec/archive/2026-04-09-.../) and aria-orchestrator (S1's own
    # example, openspec/archive/2026-01-01-aria-orchestrator/) so a
    # bare-glob counterfactual (archive/*-orchestrator/) has something to
    # falsely match -- restoring this cell's discriminating power.
    # ------------------------------------------------------------------
    def test_rename_and_anchor_semantics(self):
        with self.subTest(cell="SC-7.a-rename-semantics"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", inline_tasks=True)
            self._commit(repo, "base: anchor for x")
            self._git(repo, "checkout", "-b", "feature", "-q")
            (repo / "openspec" / "archive" / "2026-01-01-x").mkdir(parents=True, exist_ok=True)
            self._git(repo, "mv", "openspec/changes/x/proposal.md",
                      "openspec/archive/2026-01-01-x/proposal.md")
            self._commit(repo, "feature: archive x via git mv (rename)")
            self._write_config(repo, {"post_spec": "convergence"})
            proc = self._run_gate(repo, repo, "master")
            data = json.loads(proc.stdout)
            # This cell's oracle is scope_source/change_ids only (matrix
            # SC-7.a-rename-semantics note): the checkpoint is pinned
            # only so the run completes past P5, not to assert
            # present/missing here.
            self.assertEqual(data["scope_source"], "diff")
            self.assertEqual(data["change_ids"], ["x"])

        with self.subTest(cell="SC-7.b-anchor-literal"):
            repo = self._new_repo()
            self._write_anchor(repo, "aria-orchestrator-divestiture", inline_tasks=True,
                                archived=True, archive_prefix="2026-04-09")
            self._write_anchor(repo, "aria-orchestrator", inline_tasks=True,
                                archived=True, archive_prefix="2026-01-01")
            self._write_config(repo, {"post_spec": "convergence"})
            self._commit(repo, "decision-doc §2 set C: both archive dirs present")
            proc = self._run_gate(repo, repo, "master", change_ids=["orchestrator"])
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["error_kind"], "change_id_unanchored")
            self.assertEqual(data["verdict"], "error")

    # ------------------------------------------------------------------
    # SC-7(c)/(d) (proposal.md:463) -- allow_dangling_change_ids inherited
    # from S1's own anchor-missing branch: the same unanchored id used in
    # (b) ("orchestrator") downgrades from exit-2 hard stop to a [WARN]
    # plus zero-report evaluation. (d) repeats it in adaptive mode, where
    # the missing anchor also means Level can't be resolved.
    # ------------------------------------------------------------------
    def test_allow_dangling_inherited(self):
        with self.subTest(cell="SC-7.c-dangling-inherited"):
            repo = self._new_repo()
            self._write_config_ext(
                repo, checkpoints={"post_spec": "convergence"},
                allow_dangling_change_ids=True,
            )
            self._commit(repo, "sc7.c: no anchor for orchestrator anywhere")
            proc = self._run_gate(repo, repo, "master", change_ids=["orchestrator"])
            self.assertNotEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["verdict"], "fail")
            self.assertEqual(proc.returncode, 1)
            # derived, not spec-literal: SC-7(c) itself does not name
            # scope_source, but an explicitly-passed --change-id with no
            # --no-spec can only resolve via S1 (explicit), so this follows
            # from §1.1's own S1-S4 definitions rather than a quoted value.
            self.assertEqual(data["scope_source"], "explicit")
            self.assertIn("[WARN] dangling change_id: orchestrator", proc.stderr)
            entry = self._find_result(data, "post_spec", "orchestrator")
            self.assertIsNotNone(entry, data.get("results"))
            self.assertEqual(entry["status"], "missing")

        with self.subTest(cell="SC-7.d-dangling-level-undetermined"):
            repo = self._new_repo()
            self._write_config_ext(
                repo, checkpoints={"post_spec": "convergence"}, mode="adaptive",
                allow_dangling_change_ids=True,
                adaptive_rules={"level_1": "off", "level_2": "convergence", "level_3": "challenge"},
            )
            self._commit(repo, "sc7.d: same dangling id, adaptive mode, Level unresolvable")
            proc = self._run_gate(repo, repo, "master", change_ids=["orchestrator"])
            self.assertNotEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertNotEqual(data.get("error_kind"), "spec_level_undetermined")
            self.assertEqual(data["verdict"], "fail")
            self.assertEqual(proc.returncode, 1)
            self.assertIn(
                "[WARN] dangling change_id: orchestrator — Level 不可解析, 跳过 adaptive 推导",
                proc.stderr,
            )
            entry = self._find_result(data, "post_spec", "orchestrator")
            self.assertIsNotNone(entry, data.get("results"))
            self.assertEqual(entry["status"], "missing")


    # ------------------------------------------------------------------
    # SC-8 (proposal.md:464) -- Step 3 enumeration order: sorted()
    # dict-order output, not config-key order; string "on" counts as
    # enabled; "off" and the four structural exclusions (pre_merge,
    # post_closure, mid_post_spec, mid_implementation) do not.
    # ------------------------------------------------------------------
    def test_step3_enumeration(self):
        with self.subTest(cell="SC-8.step3-enumeration-order"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", inline_tasks=True)
            self._write_config(repo, {
                "post_spec": "convergence",
                "post_planning": "on",
                "mid_post_spec": "convergence",
                "mid_implementation": "convergence",
                "post_closure": "convergence",
                "pre_merge": "challenge",
                "post_implementation": "off",
            })
            self._commit(repo, "sc8: seven explicit checkpoints, manual mode")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            self.assertEqual(data["checked_checkpoints"], ["post_planning", "post_spec"])

    # ------------------------------------------------------------------
    # SC-9 (proposal.md:465) -- allow_incomplete_checkpoints's three
    # escape hatches, all-stderr-asserted (R3 rework), plus the
    # S4-bypassed checked_checkpoints two-config lock (owner ruling
    # 2026-09-30 §3 item 2: both literal configs run, sequentially,
    # inside this one subTest -- not split into two same-named subTests,
    # not nested).
    # ------------------------------------------------------------------
    def test_bypass_semantics(self):
        with self.subTest(cell="SC-9.1-bypass-missing"):
            repo = self._bypass_missing_repo()
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["verdict"], "bypassed")
            self.assertTrue(data["bypassed"])
            self.assertIn("[WARN] incomplete checkpoint gate bypassed: missing=", proc.stderr)
            self.assertIn("post_spec@x", proc.stderr)
            self.assertIn("scope_unresolved=0", proc.stderr)

        with self.subTest(cell="SC-9.2-S4-bypassed-manual"):
            repo = self._new_repo()
            self._write(repo, "README.md", "base, nothing touches openspec/changes/**\n")
            self._commit(repo, "sc9.2: unresolved scope (no --change-id, no --no-spec)")

            # config-甲 (R4 "两跑" 首份, proposal.md:465; owner ruling §3
            # item 2).
            self._write_config_ext(
                repo, checkpoints={"post_spec": "convergence", "post_planning": "off"},
                allow_incomplete_checkpoints=True,
            )
            proc1 = self._run_gate(repo, repo, "master")
            self.assertEqual(proc1.returncode, 0, proc1.stderr)
            data1 = json.loads(proc1.stdout)
            self.assertEqual(data1["verdict"], "bypassed")
            self.assertIsNone(data1["error_kind"])
            self.assertIsNone(data1["scope_source"])
            self.assertEqual(data1["change_ids"], [])
            self.assertEqual(data1["results"], [])
            self.assertIn("scope_unresolved=1", proc1.stderr)
            self.assertEqual(data1["checked_checkpoints"], ["post_spec"])

            # config-乙 (R5 "锁短路", proposal.md:465) -- same repo, this
            # time with no post_planning key at all.
            self._write_config_ext(
                repo, checkpoints={"post_spec": "convergence"},
                allow_incomplete_checkpoints=True,
            )
            proc2 = self._run_gate(repo, repo, "master")
            self.assertEqual(proc2.returncode, 0, proc2.stderr)
            data2 = json.loads(proc2.stdout)
            self.assertEqual(data2["verdict"], "bypassed")
            self.assertIsNone(data2["error_kind"])
            self.assertIsNone(data2["scope_source"])
            self.assertEqual(data2["change_ids"], [])
            self.assertEqual(data2["results"], [])
            self.assertIn("scope_unresolved=1", proc2.stderr)
            self.assertEqual(data2["checked_checkpoints"], ["post_spec"])

        with self.subTest(cell="SC-9.2-S4-bypassed-adaptive"):
            repo = self._new_repo()
            self._write(repo, "README.md", "base, nothing touches openspec/changes/**\n")
            self._commit(repo, "sc9.2 adaptive: unresolved scope")
            self._write_config_ext(
                repo, checkpoints=None, mode="adaptive",
                allow_incomplete_checkpoints=True,
                adaptive_rules={"level_1": "off", "level_2": "convergence", "level_3": "challenge"},
            )
            proc = self._run_gate(repo, repo, "master")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["verdict"], "bypassed")
            self.assertEqual(data["checked_checkpoints"], [])

        with self.subTest(cell="SC-9.3-unanchored-not-exempt"):
            repo = self._new_repo()
            self._write_config_ext(repo, checkpoints={}, allow_incomplete_checkpoints=True)
            self._commit(repo, "sc9.3: no anchor for typo anywhere")
            proc = self._run_gate(repo, repo, "master", change_ids=["typo"])
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["error_kind"], "change_id_unanchored")
            self.assertEqual(data["verdict"], "error")

        with self.subTest(cell="SC-9.4-level-undetermined-bypassed"):
            repo = self._new_repo()
            self._write_anchor_no_level(repo, "x")
            self._write_config_ext(
                repo, checkpoints={"post_spec": "convergence"}, mode="adaptive",
                allow_incomplete_checkpoints=True,
            )
            self._commit(repo, "sc9.4: anchor with no parseable Level line")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["verdict"], "bypassed")
            self.assertIn("[WARN] bypassed: spec_level_undetermined", proc.stderr)
            self.assertEqual(data["checked_checkpoints"], ["post_spec"])


    # ------------------------------------------------------------------
    # SC-10 (proposal.md:466) -- stdout/argparse contract: 16-key JSON
    # envelope across all four verdict states, argparse-required-ness for
    # the three path/base flags, the --change-id/--no-spec mutex, and
    # elapsed_ms's three-way-distinguishable typing (tasks.md 读前必看
    # 第 24 条 / TASK-005 verification 第 4 条: real timing passes both bounds;
    # a hardcoded 0 fails the lower bound; null fails the type check;
    # some other quantity such as a timestamp fails the upper bound).
    # ------------------------------------------------------------------
    def test_stdout_contract(self):
        with self.subTest(cell="SC-10.argparse-missing-base"):
            repo = self._new_repo()
            proc = self._run_gate_argv([
                "--repo-path", str(repo), "--diff-repo-path", str(repo),
            ])
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertEqual(proc.stdout, "")
            self._assert_required_arg_missing(proc.stderr, "--base")

        with self.subTest(cell="SC-10.argparse-missing-repo-path"):
            repo = self._new_repo()
            proc = self._run_gate_argv([
                "--diff-repo-path", str(repo), "--base", "master",
            ])
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertEqual(proc.stdout, "")
            self._assert_required_arg_missing(proc.stderr, "--repo-path")

        with self.subTest(cell="SC-10.argparse-missing-diff-repo-path"):
            repo = self._new_repo()
            proc = self._run_gate_argv([
                "--repo-path", str(repo), "--base", "master",
            ])
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertEqual(proc.stdout, "")
            self._assert_required_arg_missing(proc.stderr, "--diff-repo-path")

        with self.subTest(cell="SC-10.argparse-mutex"):
            repo = self._new_repo()
            proc = self._run_gate_argv([
                "--repo-path", str(repo), "--diff-repo-path", str(repo),
                "--base", "master", "--change-id", "x", "--no-spec",
            ])
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertIn(
                "--change-id 与 --no-spec 互斥 —— 前者声明本 cycle 有 spec, 后者声明没有",
                proc.stderr,
            )

        with self.subTest(cell="SC-10.config-unreadable"):
            repo = self._new_repo()
            self._write_bad_config(repo)
            self._commit(repo, "bad json config")
            proc = self._run_gate(repo, repo, "master")
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["error_kind"], "config_unreadable")
            self.assertEqual(data["verdict"], "error")

        with self.subTest(cell="SC-10.error-verdict-keyset"):
            # Independent copy of the config-unreadable fixture (matrix:
            # a change_id_unanchored fixture would be a TASK-009-only
            # behavior and can't be relied on at this TASK-008 cell).
            repo = self._new_repo()
            self._write_bad_config(repo)
            self._commit(repo, "bad json config")
            proc = self._run_gate(repo, repo, "master")
            data = json.loads(proc.stdout)
            self.assertEqual(set(data.keys()), STDOUT_KEYS)
            self.assertIsInstance(data["results"], list)
            self.assertEqual(data["results"], [])
            self._assert_elapsed_ms_type_only(data)

        with self.subTest(cell="SC-10.pass-verdict-keyset"):
            repo = self._sc5_phase_a_repo()
            proc, upper_ms = self._timed_run_gate(repo, repo, "master", change_ids=["x"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(set(data.keys()), STDOUT_KEYS)
            self.assertEqual(data["verdict"], "pass")
            self.assertEqual(data["scan_status"], "ok")
            self.assertGreaterEqual(len(data["results"]), 1)
            for entry in data["results"]:
                self.assertIn("enabled_by", entry)
            self._assert_elapsed_ms_bounded(data, upper_ms)

        with self.subTest(cell="SC-10.fail-verdict-keyset"):
            # Same shape as SC-1's issue-case-1 fixture (explicit
            # --change-id x, a real implementation diff, post_implementation
            # enabled, zero own reports -> missing -> fail), without SC-1's
            # extra decoy reports -- those prove a different, unrelated
            # fact (other changes' reports don't count) that this cell's
            # own oracle (the JSON envelope) does not need.
            repo = self._new_repo()
            self._write_anchor(repo, "x", inline_tasks=True)
            self._commit(repo, "base: anchor for x")
            self._git(repo, "checkout", "-b", "feature", "-q")
            self._write(repo, "src/a.py", "x = 1\n")
            self._commit(repo, "feature: real implementation diff, zero own reports")
            self._write_config(repo, {"post_implementation": "convergence"})
            proc, upper_ms = self._timed_run_gate(repo, repo, "master", change_ids=["x"])
            self.assertEqual(proc.returncode, 1, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(set(data.keys()), STDOUT_KEYS)
            self.assertEqual(data["verdict"], "fail")
            self.assertGreaterEqual(len(data["results"]), 1)
            for entry in data["results"]:
                self.assertIn("enabled_by", entry)
            self._assert_elapsed_ms_bounded(data, upper_ms)

        with self.subTest(cell="SC-10.bypassed-verdict-keyset"):
            repo = self._bypass_missing_repo()
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(set(data.keys()), STDOUT_KEYS)
            self.assertEqual(data["verdict"], "bypassed")
            self.assertGreaterEqual(len(data["results"]), 1)
            for entry in data["results"]:
                self.assertIn("enabled_by", entry)
            self._assert_elapsed_ms_type_only(data)

    # ------------------------------------------------------------------
    # SC-18 (proposal.md:474) -- owner ruling on 复议清单第 1 项 (裁定 1): only the
    # "excluded" branch is written here; the "not adopted" branch
    # (post_brainstorm NOT excluded -> missing+fail) is deleted per the
    # ruling and the matrix's explicit "不采纳分支...已按裁定 1 删除, 不写" --
    # it must not be added.
    # ------------------------------------------------------------------
    def test_post_brainstorm_exclusion_decision(self):
        with self.subTest(cell="SC-18.post-brainstorm-excluded"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", inline_tasks=True)
            self._write_config(repo, {
                "post_brainstorm": "convergence", "post_spec": "convergence",
            })
            self._commit(repo, "sc18: post_brainstorm explicitly enabled, must stay excluded")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            self.assertEqual(data["checked_checkpoints"], ["post_spec"])

    # ------------------------------------------------------------------
    # TASK-006 (RED third batch, SC-15~SC-17 / SC-19~SC-22) shared
    # helpers. Expected values below come verbatim from proposal.md's
    # SC-15..SC-22 rows, tasks.md's 读前必看 items 6/7/8/9/23/24, the
    # TASK-003 fixture-premise matrix (matrix-v6.md), and the owner
    # ruling .aria/decisions/2026-09-30-199-b2-group1-spec-drift-rulings.md
    # items 3 and 5 -- never computed by calling completeness_gate.py
    # itself.
    # ------------------------------------------------------------------

    def _sc17_diff_repo(self, extra_files=None):
        """The --diff-repo-path shape shared by most SC-17 cells: a
        submodule stand-in with no openspec/ and no .aria/ anywhere --
        base commit, then a 'feature' branch commit touching real
        implementation files (default: one SKILL.md)."""
        repo = self._new_repo()
        self._write(repo, "README.md", "tmpB base\n")
        self._commit(repo, "tmpB: base")
        self._git(repo, "checkout", "-b", "feature", "-q")
        for rel, content in (extra_files or {"skills/foo/SKILL.md": "# real change\n"}).items():
            self._write(repo, rel, content)
        self._commit(repo, "tmpB: feature diff (real implementation)")
        return repo

    def _repo_with_stale_master(self):
        """SC-22(1)'s "local master lags origin/master by two commits,
        and the lagging range carries someone else's
        openspec/changes/other/proposal.md" shape, built hermetically
        with no real remote: M0 (local branch 'master' stays here,
        never advanced) -> M1 (adds change 'other''s own anchor,
        upstream-only) -> M2 (upstream filler; refs/remotes/origin/master
        is fabricated here via `git update-ref`, no clone/fetch needed)
        -> a 'feature' branch forked from M2 adds change x's own anchor
        and becomes HEAD."""
        repo = self._new_repo()
        self._write(repo, "README.md", "base\n")
        self._commit(repo, "M0: base (local master ref stays pinned here)")
        self._git(repo, "checkout", "-b", "upstream-sim", "-q")
        self._write_anchor(repo, "other", inline_tasks=True)
        self._commit(repo, "M1: change other's own proposal (upstream-only)")
        self._write(repo, "docs/upstream-filler.md", "filler\n")
        self._commit(repo, "M2: upstream filler")
        m2 = self._git(repo, "rev-parse", "HEAD").stdout.strip()
        self._git(repo, "update-ref", "refs/remotes/origin/master", m2)
        self._git(repo, "checkout", "-b", "feature", m2, "-q")
        self._write_anchor(repo, "x", inline_tasks=True)
        self._commit(repo, "F: this change's own anchor (HEAD)")
        return repo

    def _load_gate_module(self):
        """Loads completeness_gate.py by file path (importlib, not
        sys.path -- memory
        feedback_cross_skill_sot_import_use_importlib_file_load) so
        SC-21's inlined-defaults/mapping-table constants are read off
        the SAME module the CLI runs, never a re-typed copy that could
        drift. Callers assert SCRIPT_PATH.is_file() themselves, inside
        their own subTest, BEFORE calling this -- this helper has no
        existence check of its own, so a missing script always surfaces
        as the caller's AssertionError, never an ImportError from here."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_completeness_gate_for_sc21", SCRIPT_PATH
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    # ------------------------------------------------------------------
    # SC-15 (proposal.md:471) -- empty-inclusion-set five-bucket split
    # (A/B/C/D/E), plus (4)'s legacy mapping and (5)'s non-empty
    # convergence-mode contrast, split across four test methods per the
    # SC row's own trailing name list (TASK-006 verification 第 1 条).
    # Cells (1)/(2)/(3)/(5)/(6)/(7) share one method (the pre-D/E name
    # "three buckets" predates R4/R5's bucket-D/E additions and the
    # non-empty-set (5) contrast; no later revision minted new names for
    # them, unlike (4)/(8)/(9) which did get dedicated names).
    # ------------------------------------------------------------------
    def test_empty_checkpoint_set_three_buckets(self):
        # (1) 格 A -- audit_not_enabled, three config-shape variants.
        # Carve-out cells (§1.0 (1)(3) carve-out table row 1): P1 predates
        # scope resolution, so no --change-id/anchor is needed.
        with self.subTest(cell="SC-15.1-empty-config"):
            repo = self._new_repo()
            self._write(repo, ".aria/config.json", "{}\n")
            self._commit(repo, "sc15.1: empty config object")
            proc = self._run_gate(repo, repo, "master")
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["checked_checkpoints"], [])
            self.assertEqual(data["verdict"], "error")
            self.assertEqual(data["error_kind"], "audit_not_enabled")

        with self.subTest(cell="SC-15.1-no-audit-block"):
            repo = self._new_repo()
            # No "audit" key AND no "experiments" key at all, so
            # experiments.agent_team_audit is not True either -- this
            # must land in bucket A, not accidentally trip the legacy
            # compat mapping (SC-15(4)'s cells).
            self._write(repo, ".aria/config.json", json.dumps({"other": {}}) + "\n")
            self._commit(repo, "sc15.1: no audit block, no experiments block")
            proc = self._run_gate(repo, repo, "master")
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["checked_checkpoints"], [])
            self.assertEqual(data["verdict"], "error")
            self.assertEqual(data["error_kind"], "audit_not_enabled")

        with self.subTest(cell="SC-15.1-no-config-file"):
            repo = self._new_repo()
            self._write(repo, "README.md", "no .aria/config.json in this repo at all\n")
            self._commit(repo, "sc15.1: no .aria/config.json at all")
            proc = self._run_gate(repo, repo, "master")
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["checked_checkpoints"], [])
            self.assertEqual(data["verdict"], "error")
            self.assertEqual(data["error_kind"], "audit_not_enabled")

        # (2) 格 C -- resolved(pre_merge)=="off" via level 1 explicit,
        # enabled_by=='explicit' -> pre_merge_not_enabled (two道守卫 could
        # have predicted this).
        with self.subTest(cell="SC-15.2-cell-C"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", level=2, inline_tasks=True)
            self._write_config(repo, {"pre_merge": "off"}, mode="manual")
            self._commit(repo, "sc15.2: pre_merge off, manual mode, empty inclusion set")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["error_kind"], "pre_merge_not_enabled")
            self.assertEqual(data["verdict"], "error")

        # (3) 格 B -- official scenario A (config-example.md:381-400)
        # verbatim: empty inclusion set here is a LEGITIMATE config
        # decision, not an error.
        with self.subTest(cell="SC-15.3-cell-B"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", level=2, inline_tasks=True)
            self._write_config(repo, {
                "post_brainstorm": "off", "post_spec": "off", "post_planning": "off",
                "mid_implementation": "off", "post_implementation": "off",
                "pre_merge": "convergence", "post_closure": "off",
            }, mode="manual", max_rounds=3)
            self._commit(repo, "sc15.3: official scenario A verbatim (seven keys, incl. max_rounds)")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["checked_checkpoints"], [])
            self.assertEqual(data["verdict"], "pass")
            self.assertTrue(data["no_prior_checkpoints"])
            self.assertFalse(data["bypassed"])
            self.assertIn("[INFO]", proc.stderr)
            self.assertIn("无前置 checkpoint 纳入校验", proc.stderr)
            self.assertIsInstance(data["results"], list)

        # (5) mode='convergence' + no checkpoints block: a NON-empty
        # inclusion set (post_implementation/post_planning/post_spec,
        # three per 裁定 1 -- post_brainstorm dropped by 读前必看第 6 条),
        # zero reports for all three -> fail. enabled_by=='mode:convergence'
        # is kept verbatim per owner ruling §3 item 3.
        with self.subTest(cell="SC-15.5-convergence-no-checkpoints"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", level=2, inline_tasks=True)
            self._commit(repo, "sc15.5: anchor only, everything in one commit (zero diff)")
            self._write_config_ext(repo, checkpoints=None, mode="convergence")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            self.assertEqual(proc.returncode, 1, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(
                data["checked_checkpoints"],
                ["post_implementation", "post_planning", "post_spec"],
            )
            self.assertEqual(len(data["results"]), 3)
            self.assertEqual(data["verdict"], "fail")
            for cp in ("post_implementation", "post_planning", "post_spec"):
                entry = self._find_result(data, cp, "x")
                self.assertIsNotNone(entry, data.get("results"))
                self.assertEqual(entry["status"], "missing")
                self.assertEqual(entry["enabled_by"], "mode:convergence")

        with self.subTest(cell="SC-15.5-typo-mode"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", level=2, inline_tasks=True)
            self._write_config_ext(repo, checkpoints=None, mode="typo-mode")
            self._commit(repo, "sc15.5 counterfactual: mode value outside the four-value enum")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["error_kind"], "config_unreadable")
            self.assertEqual(data["verdict"], "error")

        # (6) 格 D -- official scenario B, Level 1 change: adaptive
        # derivation resolves pre_merge to "off" (enabled_by ==
        # 'adaptive:level_1'), which the two enablement guards cannot
        # predict (they don't know the change's Level) -> pass, not the
        # hard-stop bucket C.
        with self.subTest(cell="SC-15.6-cell-D"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", level=1, inline_tasks=True)
            self._write_config_ext(
                repo, checkpoints=None, mode="adaptive", max_rounds=5,
                adaptive_rules={"level_1": "off", "level_2": "convergence", "level_3": "challenge"},
            )
            self._commit(repo, "sc15.6: official scenario B verbatim (incl. max_rounds), Level 1 change")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["verdict"], "pass")
            self.assertTrue(data["no_prior_checkpoints"])
            self.assertFalse(data["bypassed"])
            # proposal.md:471(6): "stderr 的 [INFO] 行逐字含 adaptive_rules.level_1"
            # -- must land on an [INFO]-tagged line specifically, not just
            # anywhere in stderr (a [WARN]/other line mentioning the same
            # substring would not satisfy the spec).
            info_lines = [l for l in proc.stderr.splitlines() if "[INFO]" in l]
            self.assertTrue(
                any("adaptive_rules.level_1" in l for l in info_lines), proc.stderr
            )

        # (7) 格 B 三格穷举反例 -- mode:convergence, the four
        # non-excluded checkpoints all explicit off, the four
        # structurally-excluded ones left UNWRITTEN so they resolve via
        # level 2b to enabled_by=='mode:convergence': must land in
        # bucket B (not an undefined state across A/B/C).
        with self.subTest(cell="SC-15.7-cell-B-convergence"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", level=2, inline_tasks=True)
            self._write_config(repo, {
                "post_brainstorm": "off", "post_spec": "off",
                "post_planning": "off", "post_implementation": "off",
            }, mode="convergence")
            self._commit(repo, "sc15.7: four non-excluded off, four excluded unwritten")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["checked_checkpoints"], [])
            self.assertEqual(data["verdict"], "pass")
            self.assertTrue(data["no_prior_checkpoints"])

    # ------------------------------------------------------------------
    # SC-15(4) (proposal.md:471) -- legacy experiments.agent_team_audit
    # mapping, carve-out cells (§1.0 (1)(3) carve-out table row 2): the
    # trigger condition is literally "no audit block", so audit.mode /
    # audit.enabled must NOT be added.
    # ------------------------------------------------------------------
    def test_legacy_config_mapping_inlined(self):
        with self.subTest(cell="SC-15.4-legacy-post-spec-mapped"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", level=2, inline_tasks=True)
            self._write(repo, ".aria/config.json", json.dumps({
                "experiments": {
                    "agent_team_audit": True,
                    "agent_team_audit_points": ["post_spec", "pre_merge"],
                },
            }, ensure_ascii=False, indent=2) + "\n")
            self._commit(repo, "sc15.4a: legacy flag, no audit block")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            self.assertEqual(data["checked_checkpoints"], ["post_spec"])

        with self.subTest(cell="SC-15.4-legacy-pre-merge-only"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", level=2, inline_tasks=True)
            self._write(repo, ".aria/config.json", json.dumps({
                "experiments": {
                    "agent_team_audit": True,
                    "agent_team_audit_points": ["pre_merge"],
                },
            }, ensure_ascii=False, indent=2) + "\n")
            self._commit(repo, "sc15.4b: legacy flag, only pre_merge mapped")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["verdict"], "pass")

    # ------------------------------------------------------------------
    # SC-15(8) (proposal.md:471) -- bucket E: allow_dangling_change_ids
    # skips adaptive derivation entirely for an unanchored id (fixture
    # deliberately carries ZERO explicit checkpoints, the load-bearing
    # condition SC-7(d) lacked).
    # ------------------------------------------------------------------
    def test_dangling_skip_bucket_e(self):
        with self.subTest(cell="SC-15.8-cell-E"):
            repo = self._new_repo()
            self._write_config_ext(
                repo, checkpoints=None, mode="adaptive", max_rounds=5,
                adaptive_rules={"level_1": "off", "level_2": "convergence", "level_3": "challenge"},
                allow_dangling_change_ids=True,
            )
            self._commit(repo, "sc15.8: official scenario B verbatim (incl. max_rounds), no anchor anywhere")
            proc = self._run_gate(repo, repo, "master", change_ids=["typo-not-anchored"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertIn("[WARN] dangling change_id: typo-not-anchored", proc.stderr)
            self.assertEqual(data["checked_checkpoints"], [])
            self.assertEqual(data["verdict"], "pass")
            self.assertTrue(data["no_prior_checkpoints"])
            # Byte-checked against proposal.md's own 格 E template (:301):
            # "...pre_merge 取 \"off\"; 依 owner 显式开启的降级路径放行..." --
            # NOT "依据 owner" (a prior draft of this fixture had that typo;
            # a correct, spec-verbatim implementation would fail it).
            self.assertIn(
                "[INFO] completeness gate: 无前置 checkpoint 纳入校验 (checked_checkpoints=[]) "
                "— change typo-not-anchored 的 adaptive 推导已因 allow_dangling_change_ids "
                "跳过, pre_merge 取 \"off\"; 依 owner 显式开启的降级路径放行 "
                "(Rule #10 白名单第一类), 非零证据判绿",
                proc.stderr,
            )

    # ------------------------------------------------------------------
    # SC-15(9) (proposal.md:471) -- multi-change R-1/R-2 reduction:
    # resolved(pre_merge) reduces via existential quantification,
    # enabled_by(pre_merge) reduces via "predictability first" (any
    # adaptive:level_N present -> bucket D; all explicit/manual-default
    # -> bucket C).
    # ------------------------------------------------------------------
    def test_multi_change_axis_reduction(self):
        with self.subTest(cell="SC-15.9-two-changes-cell-D"):
            repo = self._new_repo()
            self._write_anchor(repo, "a", level=1, inline_tasks=True)
            self._write_anchor(repo, "b", level=2, inline_tasks=True)
            self._write_config_ext(
                repo, mode="adaptive",
                adaptive_rules={"level_1": "off", "level_2": "off", "level_3": "challenge"},
                checkpoints={
                    "post_brainstorm": "off", "post_spec": "off",
                    "post_planning": "off", "post_implementation": "off",
                },
            )
            self._commit(repo, "sc15.9: two changes, Level 1 and Level 2, both resolve pre_merge=off")
            proc = self._run_gate(repo, repo, "master", change_ids=["a", "b"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["verdict"], "pass")
            info_lines = [l for l in proc.stderr.splitlines() if "[INFO]" in l]
            self.assertEqual(len(info_lines), 2, proc.stderr)
            # proposal.md:471(9): the two lines "分别逐字含 change a +
            # adaptive_rules.level_1 与 change b + adaptive_rules.level_2"
            # -- checked per-line (not against the joined text), so an
            # implementation that swaps the two changes' levels across the
            # two lines cannot pass.
            line_a = [l for l in info_lines if "change a" in l]
            line_b = [l for l in info_lines if "change b" in l]
            self.assertEqual(len(line_a), 1, info_lines)
            self.assertEqual(len(line_b), 1, info_lines)
            self.assertIn("adaptive_rules.level_1", line_a[0])
            self.assertIn("adaptive_rules.level_2", line_b[0])

        with self.subTest(cell="SC-15.9-explicit-pre-merge-cell-C"):
            repo = self._new_repo()
            self._write_anchor(repo, "a", level=1, inline_tasks=True)
            self._write_anchor(repo, "b", level=2, inline_tasks=True)
            self._write_config_ext(
                repo, mode="adaptive",
                adaptive_rules={"level_1": "off", "level_2": "off", "level_3": "challenge"},
                checkpoints={"pre_merge": "off"},
            )
            self._commit(repo, "sc15.9 counterfactual: pre_merge explicit off for both changes")
            proc = self._run_gate(repo, repo, "master", change_ids=["a", "b"])
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["error_kind"], "pre_merge_not_enabled")
            self.assertEqual(data["verdict"], "error")

    # ------------------------------------------------------------------
    # SC-16 (proposal.md:472) -- mid_implementation exclusion: enabled
    # but its adoption threshold hasn't fired yet (real code diff, no
    # progress-percentage signal modeled here at all) must not read as
    # a missing report.
    # ------------------------------------------------------------------
    def test_mid_implementation_excluded(self):
        with self.subTest(cell="SC-16.mid-implementation-excluded"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", inline_tasks=True)
            self._commit(repo, "base: anchor for x")
            self._git(repo, "checkout", "-b", "feature", "-q")
            self._write(repo, "src/a.py", "x = 1\n")
            self._commit(repo, "feature: real code change, not docs-only")
            self._write_report(repo, "post_spec-R1-2026-01-01-x-tech-lead.md")
            self._write_config(
                repo, {"mid_implementation": "convergence", "post_spec": "convergence"},
                mode="manual",
            )
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertNotIn("mid_implementation", data["checked_checkpoints"])
            self.assertEqual(data["verdict"], "pass")

    # ------------------------------------------------------------------
    # SC-17 (proposal.md:473) -- cross-repo execution context (tmpA =
    # --repo-path, the anchor/scope/report repo; tmpB = --diff-repo-path,
    # a submodule stand-in with no openspec/ and no .aria/), split
    # across three test methods per the SC row's own trailing name list.
    # (3) is intentionally absent: the matrix says it reuses SC-5.5's
    # own assertion verbatim and adds no subTest of its own.
    # ------------------------------------------------------------------
    def test_split_repo_and_diff_paths(self):
        with self.subTest(cell="SC-17.1-anchor-resolves-cross-repo"):
            repo_a = self._new_repo()
            self._write(repo_a, "README.md", "tmpA base\n")
            self._commit(repo_a, "tmpA: base")
            self._git(repo_a, "checkout", "-b", "feature", "-q")
            self._write_anchor(repo_a, "x", level=2, inline_tasks=True)
            self._write_report(repo_a, "post_spec-R1-2026-01-01-x-tech-lead.md")
            self._commit(repo_a, "tmpA: Phase-A-only feature diff (anchor + its own post_spec report)")
            self._write_config(
                repo_a, {"post_spec": "convergence", "post_implementation": "convergence"},
            )
            repo_b = self._sc17_diff_repo()
            proc = self._run_gate(repo_a, repo_b, "master", change_ids=["x"])
            self.assertNotEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertNotEqual(data.get("error_kind"), "change_id_unanchored")
            entry_spec = self._find_result(data, "post_spec", "x")
            self.assertIsNotNone(entry_spec, data.get("results"))
            self.assertEqual(entry_spec["status"], "present")
            entry_impl = self._find_result(data, "post_implementation", "x")
            self.assertIsNotNone(entry_impl, data.get("results"))
            self.assertEqual(entry_impl["status"], "missing")
            self.assertNotEqual(entry_impl.get("reason"), "phase-a-only-no-implementation")
            self.assertEqual(data["verdict"], "fail")
            self.assertEqual(proc.returncode, 1)

        with self.subTest(cell="SC-17.2-same-repo-explicit-equivalence"):
            repo = self._sc5_phase_a_repo()
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            entry = self._find_result(data, "post_implementation", "x")
            self.assertIsNotNone(entry, data.get("results"))
            self.assertEqual(entry["status"], "not_applicable")
            self.assertEqual(entry["reason"], "phase-a-only-no-implementation")
            self.assertEqual(data["verdict"], "pass")
            self.assertEqual(proc.returncode, 0)

        with self.subTest(cell="SC-17.2b-path-spelling-normalized"):
            repo = self._sc5_phase_a_repo()
            repo_path_arg = str(repo) + "/"
            rel = os.path.relpath(str(repo), start=os.getcwd())
            diff_path_arg = rel if rel.startswith(".") else f"./{rel}"
            self.assertNotEqual(repo_path_arg, diff_path_arg)
            proc = self._run_gate(repo_path_arg, diff_path_arg, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            entry = self._find_result(data, "post_implementation", "x")
            self.assertIsNotNone(entry, data.get("results"))
            self.assertEqual(entry["status"], "not_applicable")
            self.assertEqual(entry["reason"], "phase-a-only-no-implementation")

        with self.subTest(cell="SC-17.6-anchor-scope-resolves-cross-repo"):
            repo_a = self._new_repo()
            self._write(repo_a, "README.md", "tmpA base\n")
            self._commit(repo_a, "tmpA: base")
            self._git(repo_a, "checkout", "-b", "feature", "-q")
            self._write_anchor(repo_a, "x", level=2, inline_tasks=True)
            self._commit(repo_a, "tmpA: feature diff touches openspec/changes/x/")
            self._write_config(repo_a, {"post_spec": "convergence"})
            repo_b = self._sc17_diff_repo()
            proc = self._run_gate(repo_a, repo_b, "master")
            data = json.loads(proc.stdout)
            # Oracle is scope_source/change_ids only (S2 must resolve off
            # the ANCHOR face i.e. --repo-path, not --diff-repo-path) --
            # this cell does not pin the resulting present/missing status.
            self.assertEqual(data["scope_source"], "diff")
            self.assertEqual(data["change_ids"], ["x"])

    # ------------------------------------------------------------------
    # SC-17(4)/(5) (proposal.md:473) -- cross-repo + --no-spec
    # interaction. (5) is TASK-006's rewrite under 裁定 11 (replaces
    # proposal :473's original (5) cell wholesale, per tasks.md 读前必看
    # 第 7 条): allow_incomplete_checkpoints now covers
    # no_spec_unverifiable (downgrades to bypassed/exit 0);
    # allow_dangling_change_ids does not; no_spec_contradicted is never
    # covered by either.
    # ------------------------------------------------------------------
    def test_cross_repo_no_spec_and_anchor_scope(self):
        with self.subTest(cell="SC-17.4-cross-no-spec-contradicted"):
            repo_a = self._new_repo()
            self._write(repo_a, "README.md", "tmpA base\n")
            self._commit(repo_a, "tmpA: base")
            self._git(repo_a, "checkout", "-b", "feature", "-q")
            self._write_anchor(repo_a, "x", level=2, inline_tasks=True)
            self._commit(repo_a, "tmpA: --no-spec claimed but diff touches openspec/changes/x/")
            self._write_config(repo_a, {"post_spec": "convergence"})
            repo_b = self._sc17_diff_repo()
            proc = self._run_gate(repo_a, repo_b, "master", no_spec=True)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["error_kind"], "no_spec_contradicted")
            self.assertEqual(data["verdict"], "error")
            self.assertEqual(data["results"], [])

        with self.subTest(cell="SC-17.4-cross-no-spec-not-applicable"):
            repo_a = self._new_repo()
            self._write(repo_a, "README.md", "tmpA base\n")
            self._commit(repo_a, "tmpA: base")
            self._git(repo_a, "checkout", "-b", "feature", "-q")
            # proposal.md:473's own text for this variant: "同一 fixture 把
            # tmpA 的 diff 换成只触 README.md" -- README.md specifically (a
            # prior draft used docs/x.md, an unrelated-but-still-plausible
            # path; using the spec's own named path removes any doubt that
            # this is the same "unrelated-to-openspec/changes" shape §1.1
            # S2 is being tested against).
            self._write(repo_a, "README.md", "tmpA base, edited\n")
            self._commit(repo_a, "tmpA: --no-spec, diff only touches README.md")
            self._write_config(repo_a, {"post_spec": "convergence"})
            repo_b = self._sc17_diff_repo()
            proc = self._run_gate(repo_a, repo_b, "master", no_spec=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertGreaterEqual(len(data["results"]), 1, data.get("results"))
            self.assertEqual(data["checked_checkpoints"], ["post_spec"])
            for entry in data["results"]:
                self.assertEqual(entry["status"], "not_applicable")
                self.assertEqual(entry["reason"], "level1-no-spec")
            self.assertEqual(data["verdict"], "pass")

        with self.subTest(cell="SC-17.5a-no-flag"):
            repo_a = self._new_repo()
            self._write(repo_a, "README.md", "tmpA base\n")
            self._commit(repo_a, "tmpA: base, zero further commits (zero anchor-face diff)")
            self._write_config(repo_a, {"post_spec": "convergence"})
            repo_b = self._sc17_diff_repo()
            proc = self._run_gate(repo_a, repo_b, "master", no_spec=True)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["verdict"], "error")
            self.assertEqual(data["error_kind"], "no_spec_unverifiable")

        with self.subTest(cell="SC-17.5b-dangling-only"):
            repo_a = self._new_repo()
            self._write(repo_a, "README.md", "tmpA base\n")
            self._commit(repo_a, "tmpA: base, zero further commits (zero anchor-face diff)")
            self._write_config_ext(
                repo_a, checkpoints={"post_spec": "convergence"},
                allow_dangling_change_ids=True,
            )
            repo_b = self._sc17_diff_repo()
            proc = self._run_gate(repo_a, repo_b, "master", no_spec=True)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["verdict"], "error")
            self.assertEqual(data["error_kind"], "no_spec_unverifiable")

        with self.subTest(cell="SC-17.5c-bypassed"):
            repo_a = self._new_repo()
            self._write(repo_a, "README.md", "tmpA base\n")
            self._commit(repo_a, "tmpA: base, zero further commits (zero anchor-face diff)")
            self._write_config_ext(
                repo_a, checkpoints={"post_spec": "convergence"},
                allow_incomplete_checkpoints=True,
            )
            repo_b = self._sc17_diff_repo()
            proc = self._run_gate(repo_a, repo_b, "master", no_spec=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["verdict"], "bypassed")
            self.assertIsNone(data["error_kind"])
            self.assertIsNone(data["scope_source"])
            self.assertEqual(data["change_ids"], [])
            self.assertEqual(data["results"], [])
            self.assertTrue(data["bypassed"])
            self.assertEqual(data["checked_checkpoints"], ["post_spec"])
            self.assertIn("scope_unresolved=1", proc.stderr)
            self.assertIn("[WARN] bypassed: no_spec_unverifiable", proc.stderr)

        with self.subTest(cell="SC-17.5d-contradicted-with-flag"):
            repo_a = self._new_repo()
            self._write(repo_a, "README.md", "tmpA base\n")
            self._commit(repo_a, "tmpA: base")
            self._git(repo_a, "checkout", "-b", "feature", "-q")
            self._write_anchor(repo_a, "x", level=2, inline_tasks=True)
            self._commit(repo_a, "tmpA: anchor-face diff now touches openspec/changes/x/")
            self._write_config_ext(
                repo_a, checkpoints={"post_spec": "convergence"},
                allow_incomplete_checkpoints=True,
            )
            repo_b = self._sc17_diff_repo()
            proc = self._run_gate(repo_a, repo_b, "master", no_spec=True)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["error_kind"], "no_spec_contradicted")
            self.assertEqual(data["verdict"], "error")

    # ------------------------------------------------------------------
    # SC-17(7) (proposal.md:473) -- cross-repo, --diff-repo-path
    # omitted: this must be an argparse-level required-argument error,
    # not a fall-back-to-same-repo interpretation (the R4 draft's
    # deleted "default = --repo-path" behavior, which would misjudge
    # tmpA's Phase-A-only diff as same-repo not_applicable = a false
    # green shaped exactly like the bug this spec fixes).
    # ------------------------------------------------------------------
    def test_cross_repo_missing_diff_repo_path_is_argparse_error(self):
        with self.subTest(cell="SC-17.7-missing-diff-repo-path"):
            repo_a = self._new_repo()
            self._write(repo_a, "README.md", "tmpA base\n")
            self._commit(repo_a, "tmpA: base")
            m0 = self._git(repo_a, "rev-parse", "HEAD").stdout.strip()
            self._git(repo_a, "update-ref", "refs/remotes/origin/master", m0)
            self._git(repo_a, "checkout", "-b", "feature", "-q")
            self._write_anchor(repo_a, "x", level=2, inline_tasks=True)
            self._write_report(repo_a, "post_spec-R1-2026-01-01-x-tech-lead.md")
            self._commit(repo_a, "tmpA: Phase-A-only feature diff (sequenced-ship shape)")
            self._write_config_ext(repo_a, checkpoints={"post_implementation": "convergence"})
            proc = self._run_gate_argv([
                "--repo-path", str(repo_a), "--base", "origin/master",
                "--change-id", "x",
            ])
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertEqual(proc.stdout, "")
            self._assert_required_arg_missing(proc.stderr, "--diff-repo-path")

    # ------------------------------------------------------------------
    # SC-19 (proposal.md:475) -- two SOT-undefined enumeration
    # boundaries: (a) top-level-only scan (no rglob), (b) a
    # change_id-prefixed-but-not-checkpoint-prefixed file counts in NONE
    # of the three buckets, (c) rule 1's startswith(f"{checkpoint}-")
    # prefix constraint is load-bearing on its own (isolated from rule
    # 2's "-{id}-" substring match).
    # ------------------------------------------------------------------
    def test_enumeration_boundaries(self):
        with self.subTest(cell="SC-19.a-subdirectory-excluded"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", level=2, inline_tasks=True)
            self._write_config(repo, {"post_spec": "convergence"})
            self._write_report(repo, "post_spec-R1-2026-01-01-x-tech-lead.md")
            self._write_report(repo, "sub/post_spec-R2-2026-01-02-x-tech-lead.md")
            self._commit(repo, "sc19.a: one top-level report + one duplicate in a subdirectory")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            entry = self._find_result(data, "post_spec", "x")
            self.assertIsNotNone(entry, data.get("results"))
            self.assertEqual(entry["matched_count"], 1)
            # Exact-equality (not just assertNotIn a "sub/"-prefixed string,
            # which an rglob()-then-basename-only implementation would
            # trivially satisfy -- it would store the subdirectory file
            # under its bare basename, never the literal "sub/..." string,
            # so that check alone cannot distinguish it from a correct
            # implementation; matched_count above already catches the
            # count, this pins the actual filename too).
            self.assertEqual(entry["matched"], ["post_spec-R1-2026-01-01-x-tech-lead.md"])
            self.assertEqual(data["scanned_dir_depth"], 1)

        with self.subTest(cell="SC-19.b-audit-trail-not-counted"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", level=2, inline_tasks=True)
            self._write_config(repo, {"post_spec": "convergence"})
            self._write_report(repo, "x-audit-trail.md")
            self._commit(repo, "sc19.b: only a change_id-prefixed, non-checkpoint-prefixed file")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            entry = self._find_result(data, "post_spec", "x")
            self.assertIsNotNone(entry, data.get("results"))
            self.assertEqual(entry["status"], "missing")
            self.assertNotIn("x-audit-trail.md", entry["matched"])
            self.assertEqual(data["unattributed_count"], 0)
            self.assertNotIn("x-audit-trail.md", data["unattributed"])
            self.assertEqual(data["excluded_legacy_count"], 0)

        with self.subTest(cell="SC-19.c-prefix-constraint-isolated"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", level=2, inline_tasks=True)
            self._write_config(repo, {"post_spec": "convergence"})
            self._write_report(repo, "post_planning-R1-2026-01-01-x-tech-lead.md")
            self._commit(repo, "sc19.c: only a post_planning-prefixed file; post_spec is what's checked")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            entry = self._find_result(data, "post_spec", "x")
            self.assertIsNotNone(entry, data.get("results"))
            self.assertEqual(entry["status"], "missing")
            self.assertEqual(entry["matched_count"], 0)
            self.assertNotIn("post_planning-R1-2026-01-01-x-tech-lead.md", entry["matched"])
            # proposal.md:475(c): "该文件不进 post_spec 口径的任何计数" -- not
            # just matched (checked above), but also the two global counts
            # (§1.4's "两个计数的作用域": scope = union of *checked*
            # checkpoints' name-prefixes; post_planning is not checked
            # here, so this post_planning- file is outside that scope
            # entirely, not merely excluded from post_spec's own match).
            self.assertEqual(data["unattributed_count"], 0)
            self.assertEqual(data["excluded_legacy_count"], 0)

    # ------------------------------------------------------------------
    # SC-20(1)~(6) (proposal.md:476) -- Step 3's enumeration source must
    # go through the resolved (config-key-merged) view, not a literal
    # scan of audit.checkpoints (both official scenarios B and C defeat
    # a literal-key-enumeration implementation), plus the Level-parsing
    # boundaries (strikethrough stripping, no head-window, three field
    # shapes).
    # ------------------------------------------------------------------
    def test_step3_priority_chain(self):
        with self.subTest(cell="SC-20.1-scenario-c-priority-chain"):
            repo = self._new_repo()
            lines = [
                "# Proposal: x", "",
                "> **Level**: Minimal (Level 2 Spec)", "",
                "## Why", "", "placeholder.", "",
                "## What", "", "placeholder.", "",
                "## Tasks", "", "1. placeholder task.", "",
            ]
            self._write(repo, "openspec/changes/x/proposal.md", "\n".join(lines))
            self._write_config_ext(
                repo, mode="adaptive", max_rounds=5,
                adaptive_rules={"level_1": "off", "level_2": "convergence", "level_3": "challenge"},
                checkpoints={"post_spec": "challenge", "post_closure": "off"},
            )
            self._commit(repo, "sc20.1: official scenario C verbatim (incl. max_rounds), 'Minimal (Level 2 Spec)' anchor")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            # derived, not spec-literal: SC-20(1) itself names no exit code
            # for this cell. Zero reports exist anywhere in this fixture,
            # and every non-excluded checkpoint that resolves "on" (post_spec
            # explicit + post_implementation via adaptive:level_2) has no
            # not_applicable channel available here, so each pair must be
            # "missing" -> verdict=fail -> exit 1 follows from §1.4's own
            # verdict rule, not a quoted SC value.
            self.assertEqual(proc.returncode, 1, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertIn("post_implementation", data["checked_checkpoints"])
            entry_impl = self._find_result(data, "post_implementation", "x")
            self.assertIsNotNone(entry_impl, data.get("results"))
            self.assertEqual(entry_impl["enabled_by"], "adaptive:level_2")
            entry_spec = self._find_result(data, "post_spec", "x")
            self.assertIsNotNone(entry_spec, data.get("results"))
            self.assertEqual(entry_spec["enabled_by"], "explicit")

        with self.subTest(cell="SC-20.2-scenario-b-level3"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", level=3, inline_tasks=True)
            self._write_config_ext(
                repo, checkpoints=None, mode="adaptive", max_rounds=5,
                adaptive_rules={"level_1": "off", "level_2": "convergence", "level_3": "challenge"},
            )
            self._commit(repo, "sc20.2: official scenario B verbatim (incl. max_rounds), Level 3 change")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            self.assertTrue(len(data["checked_checkpoints"]) > 0, data)
            # Non-empty precondition: a "for entry in []: ..." loop passes
            # vacuously, so a P6 results-population bug that leaves
            # results=[] while checked_checkpoints is still (correctly)
            # non-empty would otherwise slip through undetected.
            self.assertGreaterEqual(len(data["results"]), 1, data)
            for entry in data["results"]:
                self.assertEqual(entry["enabled_by"], "adaptive:level_3")

        with self.subTest(cell="SC-20.3-level-undetermined"):
            repo = self._new_repo()
            self._write_anchor_no_level(repo, "x")
            self._write_config_ext(repo, checkpoints=None, mode="adaptive")
            self._commit(repo, "sc20.3: no parseable Level line anywhere, adaptive mode")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["error_kind"], "spec_level_undetermined")

        with self.subTest(cell="SC-20.4-strikethrough-level"):
            repo = self._new_repo()
            lines = [
                "# Proposal: x", "",
                "> **Spec Level**: ~~2 (proposal only)~~ → **3**", "",
                "## Why", "", "placeholder.", "",
                "## What", "", "placeholder.", "",
                "## Tasks", "", "1. placeholder task.", "",
            ]
            self._write(repo, "openspec/changes/x/proposal.md", "\n".join(lines))
            self._write_config_ext(
                repo, checkpoints=None, mode="adaptive",
                adaptive_rules={"level_1": "off", "level_2": "off", "level_3": "convergence"},
            )
            self._commit(repo, "sc20.4: strikethrough Level field, must resolve to 3 not the struck 2")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            self.assertNotEqual(data.get("error_kind"), "spec_level_undetermined")
            self.assertTrue(len(data["checked_checkpoints"]) > 0, data)
            self.assertGreaterEqual(len(data["results"]), 1, data)
            for entry in data["results"]:
                self.assertEqual(entry["enabled_by"], "adaptive:level_3")

        with self.subTest(cell="SC-20.5-deep-line-number"):
            repo = self._new_repo()
            # proposal.md:476(5) requires the Level field to land past any
            # head-window (its own real-corpus reference file,
            # openspec/archive/2026-09-06-a1-entry-claim-duplicate-work-
            # guard/proposal.md, puts "> **Spec Level**: 2" on line 58 --
            # verified directly against `git show a563192:<that path>`).
            # 55 filler lines + the 2 lines before them ("# Proposal: x",
            # "") put the Level line at line 58, not 59 (a prior draft used
            # range(1, 57) = 56 filler lines, landing on line 59 instead --
            # off by one from the value this cell means to pin).
            header = [f"> filler line {i}" for i in range(1, 56)]
            lines = ["# Proposal: x", ""] + header + [
                "> **Spec Level**: 2", "",
                "## Why", "", "placeholder.", "",
                "## What", "", "placeholder.", "",
                "## Tasks", "", "1. placeholder task.", "",
            ]
            self.assertEqual(lines[57], "> **Spec Level**: 2", lines[:60])
            self._write(repo, "openspec/changes/x/proposal.md", "\n".join(lines))
            self._write_config_ext(
                repo, checkpoints=None, mode="adaptive",
                adaptive_rules={"level_1": "off", "level_2": "convergence", "level_3": "challenge"},
            )
            self._commit(repo, "sc20.5: Level field at line 58, past any head-window implementation")
            proc = self._run_gate(repo, repo, "master", change_ids=["x"])
            data = json.loads(proc.stdout)
            self.assertNotEqual(data.get("error_kind"), "spec_level_undetermined")
            self.assertTrue(len(data["checked_checkpoints"]) > 0, data)
            self.assertGreaterEqual(len(data["results"]), 1, data)
            for entry in data["results"]:
                self.assertEqual(entry["enabled_by"], "adaptive:level_2")

        with self.subTest(cell="SC-20.6-field-shape-three-forms"):
            variants = {
                "a": ("> **Spec Level**: 2", 2),
                "b": ("- **Level**: 3", 3),
                "c": ("## Level: 2", 2),
            }
            for suffix, (level_line, expected_level) in variants.items():
                change_id = f"sc20-6-{suffix}"
                repo = self._new_repo()
                lines = [
                    f"# Proposal: {change_id}", "",
                    level_line, "",
                    "## Why", "", "placeholder.", "",
                    "## What", "", "placeholder.", "",
                    "## Tasks", "", "1. placeholder task.", "",
                ]
                self._write(repo, f"openspec/changes/{change_id}/proposal.md", "\n".join(lines))
                self._write_config_ext(
                    repo, checkpoints=None, mode="adaptive",
                    adaptive_rules={"level_1": "off", "level_2": "convergence", "level_3": "challenge"},
                )
                self._commit(repo, f"sc20.6.{suffix}: field-shape variant")
                proc = self._run_gate(repo, repo, "master", change_ids=[change_id])
                data = json.loads(proc.stdout)
                self.assertNotEqual(
                    data.get("error_kind"), "spec_level_undetermined",
                    f"variant {suffix} ({level_line!r}) failed to parse: {data}",
                )
                self.assertTrue(len(data["checked_checkpoints"]) > 0, data)
                self.assertGreaterEqual(len(data["results"]), 1, data)
                for entry in data["results"]:
                    self.assertEqual(entry["enabled_by"], f"adaptive:level_{expected_level}")

    # ------------------------------------------------------------------
    # SC-20(7) (proposal.md:476) -- inclusion is per (checkpoint,
    # change_id), never a union-of-checkpoints times all-change_ids
    # cross product: a mixed-Level multi-change PR must not manufacture
    # a missing pair for a change whose own Level resolves that
    # checkpoint to "off".
    # ------------------------------------------------------------------
    def test_pairwise_not_cross_product(self):
        with self.subTest(cell="SC-20.7-pairwise-not-cross-product"):
            repo = self._new_repo()
            self._write_anchor(repo, "a", level=1, inline_tasks=True)
            self._write_anchor(repo, "b", level=3, inline_tasks=True)
            self._write_config_ext(
                repo, mode="adaptive",
                adaptive_rules={"level_1": "off", "level_2": "convergence", "level_3": "challenge"},
                checkpoints={
                    "post_brainstorm": "off", "post_planning": "off",
                    "post_implementation": "off",
                },
            )
            self._write_report(repo, "post_spec-R1-2026-01-01-b-tech-lead.md")
            self._commit(repo, "sc20.7: two changes, Level 1 and Level 3, only b's post_spec report exists")
            proc = self._run_gate(repo, repo, "master", change_ids=["a", "b"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(len(data["results"]), 1, data.get("results"))
            self.assertIsNone(self._find_result(data, "post_spec", "a"))
            entry_b = self._find_result(data, "post_spec", "b")
            self.assertIsNotNone(entry_b, data.get("results"))
            self.assertEqual(entry_b["status"], "present")
            self.assertEqual(data["checked_checkpoints"], ["post_spec"])
            self.assertEqual(data["verdict"], "pass")

    # ------------------------------------------------------------------
    # SC-21(1) (proposal.md:477) -- the script's inlined audit-defaults
    # subset must equal, verbatim, the upstream config-loader/
    # DEFAULTS.json audit subset (read at TEST TIME, not re-typed, so a
    # future DEFAULTS.json edit can't silently drift out from under the
    # inlined copy). Contract this RED batch pins for TASK-008
    # ("CLI 与 P0/P1: ... config 直读与内联映射 ...", detailed-tasks.yaml
    # metadata.stage_cells.cells lists both SC-21.1/SC-21.2 under
    # TASK-008 -- NOT TASK-002, which is corpus-freeze.md's own task; the
    # spec gives the VALUES verbatim via DEFAULTS.json but, since the
    # script doesn't exist yet, names no module attribute): a module-level
    # dict named DEFAULT_AUDIT with exactly these four keys. DEFAULT_AUDIT
    # / LEGACY_CHECKPOINT_MAPPING below are this test's own pinned
    # interface names (neither proposal.md nor the yaml names them) --
    # TASK-008's own implementer is free to rename them, but must then
    # update these two call sites' hasattr()/attribute-name strings too.
    # ------------------------------------------------------------------
    def test_inlined_defaults_equal_upstream(self):
        with self.subTest(cell="SC-21.1-defaults-equal"):
            self.assertTrue(
                SCRIPT_PATH.is_file(),
                f"completeness_gate.py 尚未实现 (TDD RED): {SCRIPT_PATH}",
            )
            defaults_path = (
                SCRIPT_PATH.resolve().parent.parent.parent / "config-loader" / "DEFAULTS.json"
            )
            self.assertTrue(defaults_path.is_file(), defaults_path)
            upstream_audit = json.loads(defaults_path.read_text(encoding="utf-8"))["audit"]
            upstream_subset = {
                "enabled": upstream_audit["enabled"],
                "mode": upstream_audit["mode"],
                "adaptive_rules": upstream_audit["adaptive_rules"],
                "checkpoints": upstream_audit["checkpoints"],
            }
            mod = self._load_gate_module()
            self.assertTrue(
                hasattr(mod, "DEFAULT_AUDIT"),
                "completeness_gate.py 必须导出模块级常量 DEFAULT_AUDIT "
                "(dict, 含 enabled/mode/adaptive_rules/checkpoints 四键) 供 SC-21(1) 相等性断言读取",
            )
            self.assertEqual(mod.DEFAULT_AUDIT, upstream_subset)

    # ------------------------------------------------------------------
    # SC-21(2)/(3) (proposal.md:477) -- (2) the script's inlined legacy
    # compat-mapping table must equal, verbatim, config-loader/SKILL.md's
    # 旧配置兼容层 three rules (same by-file-at-test-time reasoning as
    # (1) above; contract for TASK-008: a module-level dict named
    # LEGACY_CHECKPOINT_MAPPING), AND the trigger condition is a
    # conjunction (flag alone, with an audit block already present, must
    # NOT engage the mapping) -- both parts run sequentially inside this
    # one subTest per the matrix's general rule for multi-run cells.
    # detailed-tasks.yaml metadata.stage_cells.rule requires every cell
    # listed under TASK-008 to terminate before P6 (error/bypassed/格
    # A-E) or depend only on parameters/constants -- the conjunction
    # check's fixture below is therefore an audit.enabled:false block
    # (格 A, evaluated at P1, unconditionally before scope resolution),
    # not a checkpoints-bearing block that would need S1-S4 (TASK-009) +
    # P4 (TASK-010) + P6 (TASK-012) to produce an observable
    # results[].enabled_by (a matched-checkpoints-content block was used
    # in an earlier draft; it forced this TASK-008 cell to depend on
    # TASK-012 machinery, and gave a merge-shaped bad implementation
    # nothing to trip on either, since the block's own explicit post_spec
    # value already matched what a correct non-mapping resolution would
    # produce). matrix-v6.md's own SC-21.2 row only requires "flag=true +
    # an audit block exists" (already revised, R3 只读审查 Finding 8) and
    # does not pin the block's content, so this narrowing is compatible
    # with it; the "两条同时成立" (flag=true AND no audit block -> mapping
    # DOES engage) counterpart is covered by SC-15.4-legacy-post-spec-
    # mapped's existing fixture, which the matrix row itself names as the
    # fallback owner for that half. (3) bad JSON must hard-fail, not
    # follow config-loader's own warn-and-return-defaults prose (that
    # would silently produce an empty inclusion set instead).
    # ------------------------------------------------------------------
    def test_inlined_legacy_mapping_equal_upstream(self):
        with self.subTest(cell="SC-21.2-mapping-table-equal"):
            self.assertTrue(
                SCRIPT_PATH.is_file(),
                f"completeness_gate.py 尚未实现 (TDD RED): {SCRIPT_PATH}",
            )
            skill_md_path = (
                SCRIPT_PATH.resolve().parent.parent.parent / "config-loader" / "SKILL.md"
            )
            self.assertTrue(skill_md_path.is_file(), skill_md_path)
            skill_md_text = skill_md_path.read_text(encoding="utf-8")
            # Extracted straight out of the upstream "映射规则" fenced
            # block's three "{cp}" → audit.checkpoints.{cp}: "{val}"
            # lines, rather than re-typing them (freeze_corpus.py-style
            # by-file load, applied to prose instead of a .py module).
            rule_re = re.compile(
                r'"(?P<cp>\w+)"\s*→\s*audit\.checkpoints\.(?P=cp):\s*"(?P<val>\w+)"'
            )
            upstream_mapping = dict(rule_re.findall(skill_md_text))
            self.assertEqual(len(upstream_mapping), 3, upstream_mapping)

            mod = self._load_gate_module()
            self.assertTrue(
                hasattr(mod, "LEGACY_CHECKPOINT_MAPPING"),
                "completeness_gate.py 必须导出模块级常量 LEGACY_CHECKPOINT_MAPPING "
                "(dict, post_spec/post_implementation/pre_merge -> 'convergence') "
                "供 SC-21(2) 相等性断言读取",
            )
            self.assertEqual(mod.LEGACY_CHECKPOINT_MAPPING, upstream_mapping)

            # Conjunction check: flag=true alone, with an audit block
            # already present (even a minimal one), must NOT engage the
            # mapping -- config-loader/SKILL.md:311-314's trigger condition
            # number 2 is "the audit block does not exist", full stop, so its
            # mere presence (regardless of content) must suppress mapping.
            # No --change-id/anchor is written: this fixture is a single
            # flat commit with only the config file, so P1's 格 A check
            # (audit.enabled != true, unconditional, before scope
            # resolution) is meant to be the ONLY thing that runs.
            #   - correct impl: audit block exists -> mapping does not
            #     engage -> resolved audit.enabled stays explicit `false`
            #     -> 格 A -> error_kind=audit_not_enabled, exit 2.
            #   - "ignores whether an audit block exists" impl: engages
            #     the mapping regardless -> resolved audit.enabled becomes
            #     `true` (mapped) -> P1 passes -> falls through to scope
            #     resolution with no --change-id/--no-spec and an empty
            #     diff (single commit) -> S4 -> error_kind=
            #     change_scope_unresolved, exit 2. Same exit code, a
            #     different error_kind -- the discriminator.
            repo = self._new_repo()
            self._write(repo, ".aria/config.json", json.dumps({
                "experiments": {
                    "agent_team_audit": True,
                    "agent_team_audit_points": ["post_spec"],
                },
                "audit": {"enabled": False},
            }, ensure_ascii=False, indent=2) + "\n")
            self._commit(repo, "sc21.2 contrast: flag=true but an audit block already exists (enabled:false)")
            proc = self._run_gate(repo, repo, "master")
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["error_kind"], "audit_not_enabled")
            self.assertEqual(data["verdict"], "error")
            self.assertEqual(data["checked_checkpoints"], [])

        with self.subTest(cell="SC-21.3-bad-json"):
            repo = self._new_repo()
            self._write_bad_config(repo)
            self._commit(repo, "sc21.3: syntactically invalid JSON, not config-loader's warn+defaults")
            proc = self._run_gate(repo, repo, "master")
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["error_kind"], "config_unreadable")
            self.assertEqual(data["verdict"], "error")

    # ------------------------------------------------------------------
    # SC-22 (proposal.md:478) -- three environment boundaries: (1)/(1iii)
    # a stale --base/--anchor-base inflates scope (includes an unrelated
    # change) without blocking, and the WARN names whichever flag was
    # actually stale; (2) a missing .aria/audit-reports/ directory must
    # not crash and must be distinguishable from an existing-but-empty
    # one via scan_status; (3) an unresolvable --base is git_failed, not
    # a crash.
    # ------------------------------------------------------------------
    def test_env_boundaries(self):
        with self.subTest(cell="SC-22.1-base-stale-scope-inflation"):
            repo = self._repo_with_stale_master()
            self._write_config(repo, {"post_spec": "convergence"})
            self._write_report(repo, "post_spec-R1-2026-01-01-x-tech-lead.md")

            proc_stale = self._run_gate(repo, repo, "master")
            data_stale = json.loads(proc_stale.stdout)
            self.assertIn("other", data_stale["change_ids"])
            entry_other = self._find_result(data_stale, "post_spec", "other")
            self.assertIsNotNone(entry_other, data_stale.get("results"))
            self.assertEqual(entry_other["status"], "missing")
            entry_x_stale = self._find_result(data_stale, "post_spec", "x")
            self.assertIsNotNone(entry_x_stale, data_stale.get("results"))
            self.assertEqual(entry_x_stale["status"], "present")
            self.assertEqual(data_stale["verdict"], "fail")
            self.assertEqual(proc_stale.returncode, 1)
            # Both halves of proposal.md:478(ii)'s WARN requirement must be
            # the SAME line (two independent assertIn calls against the
            # whole stderr blob would also pass if they landed on two
            # unrelated lines).
            stale_warn_lines = [
                l for l in proc_stale.stderr.splitlines() if "[WARN] base ref 陈旧" in l
            ]
            self.assertEqual(len(stale_warn_lines), 1, proc_stale.stderr)
            self.assertIn(
                "作用域解析 (S2/S3, 锚点面) 与 not_applicable (b) 通道的路径集判据 (diff 面) 会被弱化",
                stale_warn_lines[0],
            )

            proc_fresh = self._run_gate(repo, repo, "origin/master")
            data_fresh = json.loads(proc_fresh.stdout)
            self.assertEqual(data_fresh["change_ids"], ["x"])
            entry_x_fresh = self._find_result(data_fresh, "post_spec", "x")
            self.assertIsNotNone(entry_x_fresh, data_fresh.get("results"))
            self.assertEqual(entry_x_fresh["status"], "present")
            self.assertEqual(data_fresh["verdict"], "pass")
            self.assertNotIn("[WARN] base ref 陈旧", proc_fresh.stderr)

        with self.subTest(cell="SC-22.1iii-anchor-base-stale-cross-repo"):
            repo_a = self._repo_with_stale_master()
            self._write_config(repo_a, {"post_spec": "convergence"})
            repo_b = self._sc17_diff_repo()
            b_head = self._git(repo_b, "rev-parse", "HEAD").stdout.strip()
            self._git(repo_b, "update-ref", "refs/remotes/origin/master", b_head)

            proc = self._run_gate(repo_a, repo_b, "origin/master", anchor_base="master")
            data = json.loads(proc.stdout)
            self.assertIn("other", data["change_ids"])
            # proposal.md:478(iii): "WARN 文案点名 anchor-base (不是 base)" --
            # checked as one line (parallel to (1)'s own "[WARN] base ref
            # 陈旧" template, substituting the flag name), and the bare
            # "base" wording must NOT appear (two independent substring
            # checks against the whole stderr blob would pass even if
            # "陈旧" and "anchor-base" were on unrelated lines, or if the
            # implementation wrongly emitted BOTH the base- and
            # anchor-base-named WARN lines).
            anchor_warn_lines = [
                l for l in proc.stderr.splitlines() if l.startswith("[WARN] anchor-base ref 陈旧")
            ]
            self.assertEqual(len(anchor_warn_lines), 1, proc.stderr)
            self.assertNotIn("[WARN] base ref 陈旧", proc.stderr)

        with self.subTest(cell="SC-22.2-report-dir-missing"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", level=2, inline_tasks=True)
            self._write_config(repo, {"post_spec": "convergence"})
            self._commit(repo, "sc22.2: anchor + config, .aria/audit-reports/ never created")

            proc_missing = self._run_gate(repo, repo, "master", change_ids=["x"])
            data_missing = json.loads(proc_missing.stdout)
            self.assertEqual(data_missing["scanned_dir_depth"], 1)
            self.assertEqual(data_missing["scan_status"], "dir_missing")
            self.assertIn(
                "[WARN] completeness gate: .aria/audit-reports/ 不存在, 按零报告评估",
                proc_missing.stderr,
            )
            # proposal.md:478(2): "verdict 按零报告评估 (missing 或
            # not_applicable)" -- an implementation that treats the missing
            # directory as an unhandled-exception/error state, while still
            # defensively populating scanned_dir_depth/scan_status/the WARN
            # line before reporting that error, would satisfy every
            # assertion above without this one. post_spec itself has no
            # not_applicable channel (proposal.md:269), so zero reports
            # here must resolve to "missing" -> verdict=fail (not "error").
            self.assertEqual(data_missing["verdict"], "fail")
            entry_missing = self._find_result(data_missing, "post_spec", "x")
            self.assertIsNotNone(entry_missing, data_missing.get("results"))
            self.assertEqual(entry_missing["status"], "missing")

            (repo / ".aria" / "audit-reports").mkdir(parents=True, exist_ok=True)
            proc_present = self._run_gate(repo, repo, "master", change_ids=["x"])
            data_present = json.loads(proc_present.stdout)
            self.assertEqual(data_present["scan_status"], "ok")
            entry = self._find_result(data_present, "post_spec", "x")
            self.assertIsNotNone(entry, data_present.get("results"))
            self.assertEqual(entry["matched"], [])
            self.assertNotIn(
                "[WARN] completeness gate: .aria/audit-reports/ 不存在, 按零报告评估",
                proc_present.stderr,
            )

        with self.subTest(cell="SC-22.3-base-unresolvable"):
            repo = self._new_repo()
            self._write_anchor(repo, "x", level=2, inline_tasks=True)
            self._write_config(repo, {"post_spec": "convergence"})
            self._commit(repo, "sc22.3: defensive scope, --base names a ref that does not exist")
            proc = self._run_gate(repo, repo, "refs/heads/does-not-exist-anywhere", change_ids=["x"])
            self.assertEqual(proc.returncode, 2, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["error_kind"], "git_failed")
            self.assertEqual(data["verdict"], "error")


if __name__ == "__main__":
    unittest.main()
