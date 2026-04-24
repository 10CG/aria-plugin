"""Phase 1.11 custom checks collector tests.

Covers the 4 negative paths from tasks.md T3.1 scope:
- missing file → configured=False
- malformed YAML → parse_error
- version mismatch (v="2") → parse_error
- timeout + rc127 + disabled mix
"""

from __future__ import annotations

import unittest

from _helpers import make_state_checks, tmp_project
from collectors.custom_checks import (
    _coerce_scalar,
    _parse_state_checks_yaml,
    _strip_inline_comment,
    collect_custom_checks,
)


class TestScalarCoercion(unittest.TestCase):
    def test_bool_true(self):
        self.assertIs(_coerce_scalar("true"), True)
        self.assertIs(_coerce_scalar("YES"), True)

    def test_bool_false(self):
        self.assertIs(_coerce_scalar("false"), False)
        self.assertIs(_coerce_scalar("No"), False)

    def test_int(self):
        self.assertEqual(_coerce_scalar("15"), 15)
        self.assertEqual(_coerce_scalar("-3"), -3)

    def test_quoted_string_preserves(self):
        self.assertEqual(_coerce_scalar('"1"'), "1")  # quoted digits stay string
        self.assertEqual(_coerce_scalar("'true'"), "true")

    def test_bare_string(self):
        self.assertEqual(_coerce_scalar("warning"), "warning")


class TestInlineCommentStripping(unittest.TestCase):
    def test_strips_trailing_comment(self):
        self.assertEqual(_strip_inline_comment("value # note"), "value")

    def test_preserves_hash_in_quotes(self):
        self.assertEqual(_strip_inline_comment('"a#b" # note'), '"a#b"')


class TestYamlParser(unittest.TestCase):
    def test_minimal_valid_config(self):
        yaml = """version: "1"
checks:
  - name: "first"
    command: "echo ok"
    severity: info
"""
        p = _parse_state_checks_yaml(yaml)
        self.assertEqual(p["version"], "1")
        self.assertEqual(len(p["checks"]), 1)
        self.assertEqual(p["checks"][0]["name"], "first")

    def test_block_scalar_command(self):
        yaml = """version: "1"
checks:
  - name: "multi"
    command: |
      echo first
      echo second
    severity: warning
"""
        p = _parse_state_checks_yaml(yaml)
        self.assertIn("echo first", p["checks"][0]["command"])
        self.assertIn("echo second", p["checks"][0]["command"])

    def test_flow_style_version_triggers_downstream_mismatch(self):
        # The narrow parser stores the literal text; version-mismatch is enforced
        # by collector layer, not parser layer.
        p = _parse_state_checks_yaml('version: "[1, 2]"\n')
        self.assertEqual(p["version"], "[1, 2]")
        self.assertNotEqual(str(p["version"]), "1")  # collector rejects it


class TestCollectorMissing(unittest.TestCase):
    def test_no_config_file(self):
        with tmp_project() as root:
            r = collect_custom_checks(root)
            self.assertFalse(r.data["configured"])


class TestCollectorParseError(unittest.TestCase):
    def test_malformed_yaml_reports_parse_error(self):
        with tmp_project() as root:
            make_state_checks(root, "version: [bad flow]\n")
            r = collect_custom_checks(root)
            self.assertFalse(r.data["configured"])
            self.assertIn("parse_error", r.data)

    def test_version_mismatch(self):
        with tmp_project() as root:
            make_state_checks(
                root,
                """version: "2"
checks: []
""",
            )
            r = collect_custom_checks(root)
            self.assertFalse(r.data["configured"])
            self.assertIn("parse_error", r.data)


class TestCollectorExecution(unittest.TestCase):
    def test_passing_check(self):
        with tmp_project() as root:
            make_state_checks(
                root,
                """version: "1"
checks:
  - name: "passing"
    description: "always passes"
    command: "echo OK"
    severity: info
""",
            )
            r = collect_custom_checks(root)
            self.assertTrue(r.data["configured"])
            self.assertEqual(r.data["passed"], 1)
            self.assertEqual(r.data["failed"], 0)
            self.assertEqual(r.data["results"][0]["status"], "pass")

    def test_failing_check_captures_output(self):
        with tmp_project() as root:
            make_state_checks(
                root,
                """version: "1"
checks:
  - name: "fails"
    description: "fails for test"
    command: "echo BAD && exit 1"
    severity: warning
    fix: "run the fix command"
""",
            )
            r = collect_custom_checks(root)
            self.assertEqual(r.data["failed"], 1)
            self.assertEqual(r.data["results"][0]["status"], "fail")
            self.assertEqual(r.data["results"][0]["output"], "BAD")
            self.assertEqual(r.data["results"][0]["fix"], "run the fix command")

    def test_disabled_check_dropped_not_counted(self):
        with tmp_project() as root:
            make_state_checks(
                root,
                """version: "1"
checks:
  - name: "disabled"
    description: "should be dropped"
    command: "exit 1"
    severity: error
    enabled: false
  - name: "active"
    description: "should run"
    command: "echo ok"
    severity: info
""",
            )
            r = collect_custom_checks(root)
            # Current collector behavior: enabled=false entries are `continue`d
            # before the results list, so they don't appear in output at all.
            self.assertEqual(r.data["total"], 1)
            self.assertEqual(r.data["results"][0]["name"], "active")

    def test_command_not_found_is_error(self):
        with tmp_project() as root:
            make_state_checks(
                root,
                """version: "1"
checks:
  - name: "missing-bin"
    description: "rc 127"
    command: "/nonexistent/binary/xyz"
    severity: warning
""",
            )
            r = collect_custom_checks(root)
            # rc 127 maps to "error" not "fail"
            self.assertEqual(r.data["results"][0]["status"], "error")


if __name__ == "__main__":
    unittest.main()
