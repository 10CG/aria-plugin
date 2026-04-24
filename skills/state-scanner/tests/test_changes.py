"""Phase 1.5 changes analysis collector tests."""

from __future__ import annotations

import unittest

from _helpers import tmp_project  # noqa: F401 — imported to set sys.path
from collectors.changes import _classify_file, collect_changes_analysis


class TestClassifyFile(unittest.TestCase):
    def test_code_extensions(self):
        for p in ["foo.py", "bar.ts", "baz.go", "q.rs", "a.dart"]:
            self.assertEqual(_classify_file(p), "code", msg=p)

    def test_test_markers_override_code(self):
        # A test_*.py file must classify as "test", not "code"
        self.assertEqual(_classify_file("test_foo.py"), "test")
        self.assertEqual(_classify_file("src/tests/foo.py"), "test")
        self.assertEqual(_classify_file("foo.spec.ts"), "test")
        self.assertEqual(_classify_file("foo_test.go"), "test")

    def test_docs(self):
        self.assertEqual(_classify_file("README.md"), "docs")
        self.assertEqual(_classify_file("x.rst"), "docs")

    def test_config(self):
        self.assertEqual(_classify_file("package.json"), "config")
        self.assertEqual(_classify_file("pyproject.toml"), "config")

    def test_other(self):
        self.assertEqual(_classify_file("foo.png"), "other")
        self.assertEqual(_classify_file("Dockerfile"), "other")


class TestComplexityHeuristic(unittest.TestCase):
    def _git(self, **kw):
        base = {"staged_files": [], "unstaged_files": [], "untracked_files": []}
        base.update(kw)
        return base

    def test_level_1_empty(self):
        r = collect_changes_analysis(self._git())
        self.assertEqual(r.data["complexity"], "Level 1")
        self.assertEqual(r.data["change_count"], 0)

    def test_level_1_only_single_doc(self):
        r = collect_changes_analysis(self._git(unstaged_files=["README.md"]))
        # 1 doc file → Level 2 per current heuristic (>=1 code+test trips L2)
        # Actually README.md is "docs" so neither code nor test incremented.
        # With 1 docs file only, n=1 ≥3? no. L1.
        self.assertEqual(r.data["complexity"], "Level 1")

    def test_level_2_code_and_test(self):
        r = collect_changes_analysis(
            self._git(staged_files=["lib/auth.py", "tests/test_auth.py"])
        )
        self.assertEqual(r.data["complexity"], "Level 2")
        self.assertTrue(r.data["test_coverage"])

    def test_level_3_architecture_impact(self):
        r = collect_changes_analysis(
            self._git(staged_files=["docs/architecture/system-architecture.md"])
        )
        self.assertEqual(r.data["complexity"], "Level 3")
        self.assertTrue(r.data["architecture_impact"])

    def test_level_3_skill_modification(self):
        r = collect_changes_analysis(
            self._git(staged_files=["aria/skills/state-scanner/SKILL.md"])
        )
        self.assertEqual(r.data["complexity"], "Level 3")
        self.assertTrue(r.data["skill_changes"]["detected"])

    def test_level_3_many_files(self):
        r = collect_changes_analysis(
            self._git(staged_files=[f"f{i}.py" for i in range(15)])
        )
        self.assertEqual(r.data["complexity"], "Level 3")


class TestDedupeR2N3(unittest.TestCase):
    """R2-N3: change_count must align with uncommitted_count via dedup."""

    def test_same_file_staged_and_unstaged(self):
        r = collect_changes_analysis(
            {
                "staged_files": ["a.py"],
                "unstaged_files": ["a.py"],
                "untracked_files": [],
            }
        )
        self.assertEqual(r.data["change_count"], 1)


class TestSkillChangesDetection(unittest.TestCase):
    def test_multiple_skills_modified(self):
        r = collect_changes_analysis(
            {
                "staged_files": [
                    "aria/skills/foo/SKILL.md",
                    "aria/skills/bar/scripts/x.py",
                ],
                "unstaged_files": [],
                "untracked_files": [],
            }
        )
        self.assertIn("foo", r.data["skill_changes"]["modified_skills"])
        self.assertIn("bar", r.data["skill_changes"]["modified_skills"])
        self.assertEqual(
            r.data["skill_changes"]["ab_status"]["needs_benchmark"],
            r.data["skill_changes"]["modified_skills"],
        )


if __name__ == "__main__":
    unittest.main()
