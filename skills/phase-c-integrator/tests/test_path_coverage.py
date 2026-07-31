"""Tests for path_coverage.py — C.2.4 路径覆盖评估器 (aria-plugin #122, v1.65.0+).

覆盖 Spec SC-1~8, 14, 16~20, 23~28 (openspec/changes/
phase-c-gate-path-coverage-not-applicable/proposal.md)。

Fixture 纪律: 每个临时 git 仓用独立 tempfile.mkdtemp, 绝不用 repo.parent
(memory feedback_test_worktree_fixture_isolated_tmpdir, QA-13)。
SC-2 用 aria 仓自己的真实 workflow 文件 live-read (真语料回归, 随现实漂移);
SC-23 用主仓 3-workflow 语料快照 (2026-07-27, 独立仓分发时主仓文件不可达)。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))

import path_coverage as pc  # noqa: E402

# aria 仓根 (tests/ → phase-c-integrator/ → skills/ → 仓根)。
_ARIA_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_REAL_ARIA_WORKFLOW = os.path.join(
    _ARIA_ROOT, ".forgejo", "workflows", "issue-triage-tests.yml"
)

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}

# ---- 主仓 3-workflow 语料快照 (SC-23; 触发形态与 2026-07-27 真实文件一致) ----

MAIN_ISSUE_TRIAGE_YML = """\
name: issue-triage tests
on:
  push:
    branches: [master, 'feature/aria-issue-triage-sop']
    paths:
      - 'aria/skills/issue-triage/**'
  pull_request:
    paths:
      - 'aria/skills/issue-triage/**'
  workflow_dispatch: {}
jobs:
  t:
    runs-on: x
"""

MAIN_BUILD_RUNNER_YML = """\
name: build aria-runner
on:
  workflow_dispatch:
    inputs:
      deploy_env:
        description: 'gate'
        required: true
        default: 'internal'
  push:
    branches: [feature/aria-2.0-m0-prerequisite]
    paths:
      - 'aria-orchestrator/docker/aria-runner/**'
jobs:
  b:
    runs-on: x
"""

MAIN_TRIPWIRE_YML = """\
name: submodule tripwire
on:
  workflow_dispatch:
    inputs:
      dry_run:
        description: "Dry run"
        required: false
        default: "false"
  # schedule:  (deprecated, 被注释)
jobs:
  a:
    runs-on: x
"""

PUSH_NO_PATHS_YML = """\
name: everything
on:
  push:
    branches: [master]
jobs:
  x:
    runs-on: x
"""


def _git(root: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", root, *args],
        capture_output=True,
        text=True,
        env=_GIT_ENV,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {args}: {proc.stderr}")
    return proc.stdout


class _RepoFixtureMixin:
    """独立 tempdir 临时仓构建器 (QA-13)。"""

    def build_repo(
        self,
        workflows: dict[str, str],
        pr_changes: dict[str, str],
        main_files: dict[str, str] | None = None,
        pr_git_ops: list[list[str]] | None = None,
        empty_pr: bool = False,
    ) -> str:
        root = tempfile.mkdtemp(prefix="pc-test-")
        self.addCleanup(shutil.rmtree, root, True)
        _git(root, "init", "-q", "-b", "master")
        files = {"README.md": "seed\n", **(main_files or {}), **workflows}
        for rel, content in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path) or root, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "main")
        _git(root, "checkout", "-q", "-b", "feat/x")
        if not empty_pr:
            for op in pr_git_ops or []:
                _git(root, *op)
            for rel, content in pr_changes.items():
                path = os.path.join(root, rel)
                os.makedirs(os.path.dirname(path) or root, exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(content)
            _git(root, "add", "-A")
            _git(root, "commit", "-q", "-m", "pr")
        return root

    def evaluate(self, root: str) -> dict:
        return pc.evaluate_path_coverage("master", "feat/x", repo_root=root)


class DecisionRulesTests(_RepoFixtureMixin, unittest.TestCase):
    """SC-1/2/3/6/7/8/16/17/24/25/26/28 — 判定规则 1-8 端到端。"""

    def test_sc1_no_workflow_files(self) -> None:
        out = self.evaluate(self.build_repo({}, {"docs/x.md": "x"}))
        self.assertEqual(out["decision"], "not_applicable")
        self.assertEqual(out["reason"], "no-workflow-files")
        self.assertEqual(out["workflows_scanned"], 0)

    def test_sc2_real_aria_corpus_regression(self) -> None:
        # 真实语料 live-read: aria 仓唯一 workflow (paths=skills/issue-triage/**)
        # + v1.64.1 复发形态的变更路径 → not_applicable (#122 本尊场景)。
        with open(_REAL_ARIA_WORKFLOW, encoding="utf-8") as fh:
            real = fh.read()
        root = self.build_repo(
            {".forgejo/workflows/issue-triage-tests.yml": real},
            {"skills/run_all_tests.sh": "#!/bin/bash\n"},
        )
        out = self.evaluate(root)
        self.assertEqual(out["decision"], "not_applicable")
        self.assertEqual(out["reason"], "no-triggering-paths")

    def test_sc3_matching_change_covered(self) -> None:
        with open(_REAL_ARIA_WORKFLOW, encoding="utf-8") as fh:
            real = fh.read()
        root = self.build_repo(
            {".forgejo/workflows/issue-triage-tests.yml": real},
            {"skills/issue-triage/x.py": "pass\n"},
        )
        out = self.evaluate(root)
        self.assertEqual(out["decision"], "covered")
        self.assertEqual(out["reason"], "workflow-trigger-matched")
        self.assertIn(
            ".forgejo/workflows/issue-triage-tests.yml",
            out["matched_workflows"],
        )

    def test_sc6_paths_ignore_covered(self) -> None:
        wf = "on:\n  push:\n    paths-ignore:\n      - 'docs/**'\njobs:\n  x:\n    runs-on: x\n"
        root = self.build_repo(
            {".forgejo/workflows/w.yml": wf}, {"src/a.py": "x"}
        )
        out = self.evaluate(root)
        self.assertEqual(out["decision"], "covered")
        self.assertEqual(out["reason"], "workflow-trigger-matched")

    def test_sc7_all_malformed_unknown(self) -> None:
        # 无 on: 块 → 文件级解析失败 → unknown (gate 行为=现状)。
        root = self.build_repo(
            {".forgejo/workflows/bad.yml": "jobs:\n  x:\n    runs-on: x\n"},
            {"docs/x.md": "x"},
        )
        out = self.evaluate(root)
        self.assertEqual(out["decision"], "unknown")
        self.assertTrue(out["reason"].startswith("workflow-parse-failed:"))
        self.assertIn(".forgejo/workflows/bad.yml", out["reason"])

    def test_sc8_git_diff_failure_unknown(self) -> None:
        root = self.build_repo({}, {"docs/x.md": "x"})
        out = pc.evaluate_path_coverage(
            "no-such-branch", "feat/x", repo_root=root
        )
        self.assertEqual(out["decision"], "unknown")
        self.assertTrue(out["reason"].startswith("git-diff-failed:"))

    def test_sc8_not_a_repo_unknown(self) -> None:
        root = tempfile.mkdtemp(prefix="pc-notrepo-")
        self.addCleanup(shutil.rmtree, root, True)
        out = pc.evaluate_path_coverage("master", "feat/x", repo_root=root)
        self.assertEqual(out["decision"], "unknown")
        self.assertTrue(out["reason"].startswith("git-diff-failed:"))

    def test_sc16_workflow_file_itself_changed(self) -> None:
        # 对 CI 配置本身动刀的 PR 永不 not_applicable (D10/QA-1)。
        with open(_REAL_ARIA_WORKFLOW, encoding="utf-8") as fh:
            real = fh.read()
        root = self.build_repo(
            {".forgejo/workflows/issue-triage-tests.yml": real},
            {
                ".forgejo/workflows/issue-triage-tests.yml": real
                + "# tampered\n"
            },
        )
        out = self.evaluate(root)
        self.assertEqual(out["decision"], "covered")
        self.assertEqual(out["reason"], "workflow-files-changed")

    def test_sc17_push_pull_request_or_semantics(self) -> None:
        # push 无 paths + pull_request 有 paths → 任一触发即 covered (QA-4)。
        wf_a = (
            "on:\n  push:\n    branches: [master]\n"
            "  pull_request:\n    paths:\n      - 'never/**'\n"
            "jobs:\n  x:\n    runs-on: x\n"
        )
        root = self.build_repo(
            {".forgejo/workflows/a.yml": wf_a}, {"docs/x.md": "x"}
        )
        self.assertEqual(self.evaluate(root)["decision"], "covered")
        # 反向: push 有不命中 paths + pull_request 无 paths → 仍 covered。
        wf_b = (
            "on:\n  push:\n    paths:\n      - 'never/**'\n"
            "  pull_request:\n    branches: [master]\n"
            "jobs:\n  x:\n    runs-on: x\n"
        )
        root_b = self.build_repo(
            {".forgejo/workflows/b.yml": wf_b}, {"docs/x.md": "x"}
        )
        self.assertEqual(self.evaluate(root_b)["decision"], "covered")

    def test_sc24_covered_beats_parse_failed(self) -> None:
        root = self.build_repo(
            {
                ".forgejo/workflows/good.yml": PUSH_NO_PATHS_YML,
                ".forgejo/workflows/bad.yml": "no on block here\n",
            },
            {"docs/x.md": "x"},
        )
        out = self.evaluate(root)
        self.assertEqual(out["decision"], "covered")
        self.assertEqual(out["reason"], "workflow-trigger-matched")

    def test_sc25_pull_request_target_covered(self) -> None:
        # 未建模自动触发键白名单方向 (R2-C1): 不得归零贡献。
        wf = (
            "on:\n  pull_request_target:\n    branches: [master]\n"
            "jobs:\n  x:\n    runs-on: x\n"
        )
        root = self.build_repo(
            {".forgejo/workflows/prt.yml": wf}, {"docs/x.md": "x"}
        )
        out = self.evaluate(root)
        self.assertEqual(out["decision"], "covered")

    def test_sc26_wrong_repo_context_safety_net(self) -> None:
        # 在"主仓"对子模块专属分支名评估 — ref 不存在 → git-diff-failed → unknown
        # (BA-2 残留: cwd 错仓不会静默产出错误 decision)。
        root = self.build_repo({}, {"docs/x.md": "x"})
        out = pc.evaluate_path_coverage(
            "feature/only-in-submodule", "feat/x", repo_root=root
        )
        self.assertEqual(out["decision"], "unknown")
        self.assertTrue(out["reason"].startswith("git-diff-failed:"))

    def test_sc28_empty_diff_covered(self) -> None:
        # diff 成功但为空 (pr 分支零新 commit) → covered/empty-diff (规则 2)。
        root = self.build_repo(
            {".forgejo/workflows/w.yml": PUSH_NO_PATHS_YML},
            {},
            empty_pr=True,
        )
        out = self.evaluate(root)
        self.assertEqual(out["decision"], "covered")
        self.assertEqual(out["reason"], "empty-diff")


class TriggerFormTests(_RepoFixtureMixin, unittest.TestCase):
    """SC-4/5/20 — on: 三形 + 块映射 paths 双子用例。"""

    def test_sc4_block_mapping_push_no_paths(self) -> None:
        out = self.evaluate(
            self.build_repo(
                {".forgejo/workflows/w.yml": PUSH_NO_PATHS_YML},
                {"docs/x.md": "x"},
            )
        )
        self.assertEqual(out["decision"], "covered")
        self.assertEqual(out["reason"], "workflow-trigger-matched")

    def test_sc5_flow_list_form(self) -> None:
        wf = "on: [push]\njobs:\n  x:\n    runs-on: x\n"
        out = self.evaluate(
            self.build_repo(
                {".forgejo/workflows/w.yml": wf}, {"docs/x.md": "x"}
            )
        )
        self.assertEqual(out["decision"], "covered")
        self.assertEqual(out["reason"], "workflow-trigger-matched")

    def test_sc5_scalar_form(self) -> None:
        wf = "on: push\njobs:\n  x:\n    runs-on: x\n"
        out = self.evaluate(
            self.build_repo(
                {".forgejo/workflows/w.yml": wf}, {"docs/x.md": "x"}
            )
        )
        self.assertEqual(out["decision"], "covered")
        self.assertEqual(out["reason"], "workflow-trigger-matched")

    def test_sc20a_block_paths_hit(self) -> None:
        wf = (
            "on:\n  push:\n    paths:\n      - 'src/**'\n"
            "jobs:\n  x:\n    runs-on: x\n"
        )
        out = self.evaluate(
            self.build_repo(
                {".forgejo/workflows/w.yml": wf}, {"src/a.py": "x"}
            )
        )
        self.assertEqual(out["decision"], "covered")
        self.assertEqual(out["reason"], "workflow-trigger-matched")

    def test_sc20b_block_paths_miss(self) -> None:
        wf = (
            "on:\n  push:\n    paths:\n      - 'src/**'\n"
            "jobs:\n  x:\n    runs-on: x\n"
        )
        out = self.evaluate(
            self.build_repo(
                {".forgejo/workflows/w.yml": wf}, {"docs/x.md": "x"}
            )
        )
        self.assertEqual(out["decision"], "not_applicable")
        self.assertEqual(out["reason"], "no-triggering-paths")


class GlobMatcherTests(unittest.TestCase):
    """SC-14 表驱动 — 期望值来源: GHA/forgejo paths filter 文档
    (docs.github.com/actions "Workflow syntax" filter patterns; forgejo 沿用)。
    大小写敏感 (QA-8); 未建模语法一律判匹配 (BA-1)。
    """

    CASES = [
        # (pattern, path, expect_match)
        ("skills/issue-triage/**", "skills/issue-triage/x.py", True),
        ("skills/issue-triage/**", "skills/issue-triage/a/b.py", True),
        ("skills/issue-triage/**", "skills/other/x.py", False),
        ("skills/issue-triage/**", "skills/issue-triage", False),  # 尾 /** 不含目录自身
        ("docs/*", "docs/a.md", True),
        ("docs/*", "docs/a/b.md", False),  # * 不跨段
        ("**/tests/**", "a/b/tests/c.py", True),
        ("*.md", "README.md", True),
        ("*.md", "docs/README.md", False),
        ("a?.md", "ab.md", True),
        ("a?.md", "a/b.md", False),  # ? 不跨段 (a/.md 形)
        ("Skills/**", "skills/foo.py", False),  # 大小写敏感 (QA-8)
    ]

    UNMODELED = ["[abc]x.py", "!excluded/**", "{a,b}/x", "a\\*b"]

    def test_table_driven(self) -> None:
        for pattern, path, expect in self.CASES:
            with self.subTest(pattern=pattern, path=path):
                self.assertEqual(
                    pc._pattern_matches_any(pattern, [path]), expect
                )

    def test_unmodeled_syntax_treated_as_match(self) -> None:
        for pattern in self.UNMODELED:
            with self.subTest(pattern=pattern):
                self.assertIsNone(pc._glob_to_regex(pattern))
                self.assertTrue(
                    pc._pattern_matches_any(pattern, ["whatever/x.py"])
                )


class GitlinkAndCorpusTests(_RepoFixtureMixin, unittest.TestCase):
    """SC-19 (gitlink 语义) + SC-23 (主仓 3-workflow 联合语料)。"""

    MAIN_CORPUS = {
        ".forgejo/workflows/issue-triage-tests.yml": MAIN_ISSUE_TRIAGE_YML,
        ".forgejo/workflows/build-aria-runner.yaml": MAIN_BUILD_RUNNER_YML,
        ".forgejo/workflows/submodule-gate-tripwire.yml": MAIN_TRIPWIRE_YML,
    }

    def test_sc19_gitlink_only_bump(self) -> None:
        # gitlink bump 在 --name-only 输出为单 token `aria` — 与普通同名文件
        # 在评估器视角不可区分 (评估器只见路径串), 用同形 fixture 复现。
        root = self.build_repo(self.MAIN_CORPUS, {"aria": "gitlink-stand-in"})
        out = self.evaluate(root)
        self.assertEqual(out["decision"], "not_applicable")
        self.assertEqual(out["reason"], "no-triggering-paths")
        self.assertEqual(out["matched_workflows"], [])

    def test_sc19_positive_exact_token_workflow(self) -> None:
        # 正证 (QA-10): 合成 paths 含精确 token `aria` 的 workflow → covered,
        # 验证 gitlink 按不透明单段路径参与匹配、不展开。
        wf = (
            "on:\n  push:\n    paths:\n      - 'aria'\n"
            "jobs:\n  x:\n    runs-on: x\n"
        )
        root = self.build_repo(
            {**self.MAIN_CORPUS, ".forgejo/workflows/syn.yml": wf},
            {"aria": "gitlink-stand-in"},
        )
        out = self.evaluate(root)
        self.assertEqual(out["decision"], "covered")
        self.assertIn(".forgejo/workflows/syn.yml", out["matched_workflows"])

    def test_sc23_joint_corpus_docs_change(self) -> None:
        out = self.evaluate(
            self.build_repo(self.MAIN_CORPUS, {"docs/x.md": "x"})
        )
        self.assertEqual(out["decision"], "not_applicable")
        self.assertEqual(out["reason"], "no-triggering-paths")

    def test_sc23_joint_corpus_runner_change(self) -> None:
        # branches 不建模 → build-aria-runner 的 push paths 命中即 covered。
        out = self.evaluate(
            self.build_repo(
                self.MAIN_CORPUS,
                {"aria-orchestrator/docker/aria-runner/Dockerfile": "FROM x"},
            )
        )
        self.assertEqual(out["decision"], "covered")
        self.assertEqual(out["reason"], "workflow-trigger-matched")
        self.assertIn(
            ".forgejo/workflows/build-aria-runner.yaml",
            out["matched_workflows"],
        )


class RenameAndContextTests(_RepoFixtureMixin, unittest.TestCase):
    """SC-18 (rename 双路径) + SC-27 (show-toplevel 机制)。"""

    def test_sc18_rename_out_of_covered_path(self) -> None:
        # --no-renames 下 rename 呈 delete+add, 旧路径参与匹配 → covered。
        wf = (
            "on:\n  push:\n    paths:\n      - 'src/**'\n"
            "jobs:\n  x:\n    runs-on: x\n"
        )
        root = self.build_repo(
            {".forgejo/workflows/w.yml": wf},
            {},
            main_files={"src/x.py": "pass\n"},
            pr_git_ops=[["mv", "src/x.py", "docs-x.py"]],
        )
        out = self.evaluate(root)
        self.assertEqual(out["decision"], "covered")
        self.assertEqual(out["reason"], "workflow-trigger-matched")

    def test_sc27_cwd_subdir_uses_toplevel(self) -> None:
        wf = PUSH_NO_PATHS_YML
        root = self.build_repo(
            {".forgejo/workflows/w.yml": wf},
            {"docs/x.md": "x"},
            main_files={"sub/dir/keep.txt": "k\n"},
        )
        expected = self.evaluate(root)
        old_cwd = os.getcwd()
        self.addCleanup(os.chdir, old_cwd)
        os.chdir(os.path.join(root, "sub", "dir"))
        out = pc.evaluate_path_coverage("master", "feat/x", repo_root=None)
        self.assertEqual(out, expected)


if __name__ == "__main__":
    unittest.main()
