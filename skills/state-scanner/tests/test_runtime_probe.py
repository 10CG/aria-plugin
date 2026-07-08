"""TASK-011 — unit tests for the generalized runtime-invocation probe library.

Spec: openspec/changes/runtime-probe-archive-gate-integration/proposal.md
      (§What Changes ①② — DEC-20260705-001)
Task: detailed-tasks.yaml TASK-011 (this file, parent 3.1) — probe library
      tri-state × descriptor value-layer five invalid forms × text-layer
      restricted-YAML parsing. TASK-014 (falsifiable "probe 恒 pass"
      injection harness, SC-8, parent 3.4) APPENDS to this SAME file — see
      `TestFalsifiableAlwaysPassVariant` at the bottom; its class/method
      names are new (not a repurposing of any name below).

Modules under test (both new leaves added by TASK-001/002/004; zero prior
test coverage confirmed via repo-wide grep for
`_frontmatter_block|extract_runtime_probe` at authoring time):
  scripts/lib/runtime_probe.py     — validate_descriptor() / probe()
  scripts/lib/frontmatter_block.py — _frontmatter_block() / extract_runtime_probe()

Coverage map (verification bullets -> TestCase classes):
  TestValidateDescriptorValueLayer   - SC-5 value layer, 4 of the 5 invalid
                                        forms (missing required field / type
                                        error / max_age_days non-positive /
                                        partition absolute-or-escapes-repo);
                                        baseline valid + typing/tolerance.
  TestExtractRuntimeProbeTextLayer   - SC-2/SC-5 text layer: the 4 rejection
                                        forms (deeper nesting / flow-style /
                                        anchor-or-alias / multiline block
                                        scalar) + trailing-comment stripping
                                        + absent-declaration forms.
  TestOfficialExampleHermetic        - SC-2 lock: proposal.md §What 1's
                                        example block hardcoded VERBATIM
                                        (byte-for-byte, incl. trailing
                                        comments) -> full text-layer +
                                        value-layer round trip.
  TestProbeTriState                  - SC-2/SC-3: pass + the 4 warn forms
                                        (partition missing / exists-but-
                                        unreadable / all-stale / only
                                        non-production records) + tz-naive
                                        `now` normalization.
  TestProbeSkippedAndConfigTraversal - SC-4: the 2 skipped forms (switch off
                                        / config missing) + the 5th SC-5
                                        value-layer invalid form
                                        (`enabled_when` dotted-path
                                        mid-segment non-dict — only
                                        decidable here, inside probe(),
                                        against REAL config content; see
                                        runtime_probe.py's own module
                                        docstring "division of labor" note —
                                        NOT validate_descriptor()'s job).
  TestProbeParsingRobustness         - malformed JSONL lines / malformed
                                        `ts` skipped-not-fatal; custom
                                        `max_age_days` window narrows
                                        recency; `symbol` is a message label
                                        only, never a record-level filter.
  TestFalsifiableAlwaysPassVariant   - TASK-014/SC-8: anti-false-green
                                        harness — inject a "probe 恒 pass"
                                        variant via module-attribute patch
                                        and prove >=1 representative
                                        assertion goes red under it (all-
                                        stale warn + switch-off skipped),
                                        plus a structural guard confirming
                                        the patch actually reaches the call
                                        path exercised by every other test.

All fixtures are synthetic, not real corpus (feedback_gate_tracks_reality_
synthetic_fixture) — contract tests pin a controlled fixture rather than
drift with reality. Every probe()/`_scan_partition` call receives an
explicit injected `now`, so no assertion here depends on the wall clock.

House-style note on imports: this file deliberately does NOT
`from _helpers import ...` (unlike tests/test_spec_complete.py). That bare
top-level import only resolves when `tests/` itself is on sys.path — true
for `python3 tests/run_tests.py` (its `discover()` sets `top_level_dir` to
the tests dir) and for `cd tests && python3 -m unittest test_X`, but NOT for
`python3 -m unittest tests.test_runtime_probe -v` run from the skill root
(confirmed empirically while authoring this file: `from _helpers import
tmp_project, write_file` raises `ModuleNotFoundError: No module named
'_helpers'` under that exact invocation — a pre-existing, documented gap,
see `.aria/audit-reports/post_spec-R2-2026-06-13-state-scanner-git-stderr-
locale-hardening.md:44` re: `python3 -m unittest discover`). This file
instead mirrors tests/test_phase1_gate_telemetry.py's approach — a local
`tempfile.TemporaryDirectory()`-based fixture helper plus `__file__`-relative
sys.path bootstrap — so it works under every invocation style asked for in
this task's verification section.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from unittest import mock

_SKILL_ROOT = Path(__file__).resolve().parent.parent
_LIB_DIR = str(_SKILL_ROOT / "scripts" / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

# Bare top-level imports (not `lib.runtime_probe`): inserting scripts/lib
# itself onto sys.path and importing the bare module name sidesteps the
# `lib` name collision with state-scanner/lib (Layer H/L, a DIFFERENT
# package) — same discipline as coordination_probe.py's own import block.
import runtime_probe  # noqa: E402 — module object kept as a future TASK-014 (SC-8) monkeypatch target
from runtime_probe import probe, validate_descriptor  # noqa: E402
from frontmatter_block import _frontmatter_block, extract_runtime_probe  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture vocabulary
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
_PARTITION_REL = ".aria/probe-telemetry.jsonl"
_DEFAULT_SYMBOL = "demo_symbol"


@contextmanager
def _tmp_repo() -> Iterator[Path]:
    """Yield a throwaway directory standing in for a repo root. Plain
    filesystem only — no git — matching what `validate_descriptor`/`probe`
    actually need."""
    with tempfile.TemporaryDirectory(prefix="runtime-probe-test-") as td:
        yield Path(td)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _prod_record(ts: datetime, **extra) -> dict:
    rec = {"ts": _iso(ts), "source": "production"}
    rec.update(extra)
    return rec


def _write_lines(path: Path, lines: list) -> None:
    """Write a JSONL partition file. Each item is a dict (JSON-encoded) or a
    raw str (written verbatim — used to inject malformed rows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = [item if isinstance(item, str) else json.dumps(item) for item in lines]
    path.write_text("\n".join(encoded) + "\n", encoding="utf-8")


def _write_config(path: Path, config) -> None:
    """Write `.aria/config.json`. `config` is a dict (JSON-encoded) or a raw
    str (used to inject malformed JSON)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = config if isinstance(config, str) else json.dumps(config)
    path.write_text(text, encoding="utf-8")


def _descriptor(**overrides) -> dict:
    """Build an already-typed descriptor dict directly (NOT round-tripped
    through validate_descriptor()) — mirrors how coordination_probe.py's
    hardcoded `_DESCRIPTOR` constant is constructed (its comment:
    "Author-controlled and always well-formed, so it is passed straight to
    probe() without a validate_descriptor() round-trip")."""
    d = {
        "partition": _PARTITION_REL,
        "symbol": _DEFAULT_SYMBOL,
        "max_age_days": 14,
        "enabled_when": None,
    }
    d.update(overrides)
    return d


def _skip_if_root() -> None:
    """A chmod-000 unreadable-file fixture is meaningless under euid==0:
    root bypasses all POSIX permission bits, so the file stays readable and
    the fixture silently fails to exercise the IO-error branch it exists to
    test. Required guard per TASK-011 instructions."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise unittest.SkipTest(
            "running as root - chmod 000 fixture would still be readable, "
            "so the unreadable-partition IO-error branch cannot be exercised"
        )


# ---------------------------------------------------------------------------
# TASK-001 — validate_descriptor(): value layer (4 of the 5 SC-5 forms)
# ---------------------------------------------------------------------------


class TestValidateDescriptorValueLayer(unittest.TestCase):
    """The 5th SC-5 invalid form (`enabled_when` mid-segment non-dict) is
    NOT tested here — validate_descriptor() cannot decide it without the
    REAL `.aria/config.json` content, which only exists inside probe(). See
    TestProbeSkippedAndConfigTraversal.test_invalid_enabled_when_middle_segment_not_dict.
    """

    # --- baseline valid ---

    def test_valid_descriptor_all_fields_typed_correctly(self):
        with _tmp_repo() as repo:
            fields = {
                "partition": ".aria/x.jsonl",
                "symbol": "run_gate",
                "max_age_days": 7,
                "enabled_when": "a.b.c",
            }
            result = validate_descriptor(fields, repo)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            result["descriptor"],
            {
                "partition": ".aria/x.jsonl",
                "symbol": "run_gate",
                "max_age_days": 7,
                "enabled_when": "a.b.c",
            },
        )
        self.assertIsInstance(result["descriptor"]["max_age_days"], int)

    def test_valid_descriptor_defaults_max_age_days_and_enabled_when(self):
        with _tmp_repo() as repo:
            fields = {"partition": ".aria/x.jsonl", "symbol": "run_gate"}
            result = validate_descriptor(fields, repo)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["descriptor"]["max_age_days"], 14)
        self.assertIsNone(result["descriptor"]["enabled_when"])

    def test_valid_descriptor_max_age_days_numeric_string_converted(self):
        """Production contract: raw `fields` come from the text-layer parser
        as strings; this layer owns the str -> int conversion (module
        docstring)."""
        with _tmp_repo() as repo:
            fields = {"partition": ".aria/x.jsonl", "symbol": "run_gate", "max_age_days": "7"}
            result = validate_descriptor(fields, repo)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["descriptor"]["max_age_days"], 7)

    def test_valid_descriptor_tolerates_unknown_extra_keys(self):
        """Deliberate leniency (module docstring): unrecognized scalar keys
        are ignored, not treated as invalid — NOT a 6th value-layer
        rejection form."""
        with _tmp_repo() as repo:
            fields = {"partition": ".aria/x.jsonl", "symbol": "run_gate", "bogus_key": "z"}
            result = validate_descriptor(fields, repo)
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("bogus_key", result["descriptor"])

    # --- SC-5 value-layer form 1: missing required field ---

    def test_invalid_missing_required_partition(self):
        with _tmp_repo() as repo:
            result = validate_descriptor({"symbol": "run_gate"}, repo)
        self.assertEqual(result["status"], "invalid")
        self.assertIn("partition", result["reason"])

    def test_invalid_missing_required_symbol(self):
        with _tmp_repo() as repo:
            result = validate_descriptor({"partition": ".aria/x.jsonl"}, repo)
        self.assertEqual(result["status"], "invalid")
        self.assertIn("symbol", result["reason"])

    # --- SC-5 value-layer form 2: type error ---

    def test_invalid_type_error_symbol_not_string(self):
        with _tmp_repo() as repo:
            result = validate_descriptor({"partition": ".aria/x.jsonl", "symbol": 123}, repo)
        self.assertEqual(result["status"], "invalid")
        self.assertIn("symbol must be a string", result["reason"])

    # --- SC-5 value-layer form 3: max_age_days non-positive integer ---

    def test_invalid_max_age_days_zero(self):
        with _tmp_repo() as repo:
            result = validate_descriptor(
                {"partition": ".aria/x.jsonl", "symbol": "s", "max_age_days": 0}, repo
            )
        self.assertEqual(result["status"], "invalid")
        self.assertIn(">= 1", result["reason"])

    def test_invalid_max_age_days_negative(self):
        with _tmp_repo() as repo:
            result = validate_descriptor(
                {"partition": ".aria/x.jsonl", "symbol": "s", "max_age_days": -5}, repo
            )
        self.assertEqual(result["status"], "invalid")
        self.assertIn(">= 1", result["reason"])

    def test_invalid_max_age_days_bool_guard(self):
        """`bool` is an `int` subclass in Python — the implementation
        explicitly guards `max_age_days: true/false` from being silently
        accepted as 1/0 (source comment: "bool is an int subclass — guard
        first")."""
        with _tmp_repo() as repo:
            result = validate_descriptor(
                {"partition": ".aria/x.jsonl", "symbol": "s", "max_age_days": True}, repo
            )
        self.assertEqual(result["status"], "invalid")
        self.assertIn("bool", result["reason"])

    def test_invalid_max_age_days_non_numeric_string(self):
        with _tmp_repo() as repo:
            result = validate_descriptor(
                {"partition": ".aria/x.jsonl", "symbol": "s", "max_age_days": "abc"}, repo
            )
        self.assertEqual(result["status"], "invalid")
        self.assertIn("integer", result["reason"])

    # --- SC-5 value-layer form 4: partition absolute OR resolve-escapes-repo ---

    def test_invalid_partition_absolute_path(self):
        with _tmp_repo() as repo:
            result = validate_descriptor({"partition": "/etc/passwd", "symbol": "s"}, repo)
        self.assertEqual(result["status"], "invalid")
        self.assertIn("absolute", result["reason"])

    def test_invalid_partition_escapes_repo_via_dotdot(self):
        """pathlib footgun (source comment): `repo / "/abs"` would silently
        drop the repo prefix, so the absolute-path guard above is not
        sufficient on its own — a relative `..`-escape must be caught too
        via `is_relative_to`."""
        with _tmp_repo() as repo:
            result = validate_descriptor(
                {"partition": "../escaped.jsonl", "symbol": "s"}, repo
            )
        self.assertEqual(result["status"], "invalid")
        self.assertIn("outside repo", result["reason"])

    # --- bonus: enabled_when wrong type + non-mapping fields (explicit
    #     defensive guards in the source, cheap to lock) ---

    def test_invalid_enabled_when_not_string(self):
        with _tmp_repo() as repo:
            result = validate_descriptor(
                {"partition": ".aria/x.jsonl", "symbol": "s", "enabled_when": 5}, repo
            )
        self.assertEqual(result["status"], "invalid")
        self.assertIn("enabled_when", result["reason"])

    def test_invalid_fields_not_a_mapping(self):
        with _tmp_repo() as repo:
            result = validate_descriptor(None, repo)  # type: ignore[arg-type]
        self.assertEqual(result["status"], "invalid")
        self.assertIn("mapping", result["reason"])


# ---------------------------------------------------------------------------
# TASK-004 — extract_runtime_probe(): text layer (restricted YAML subset)
# ---------------------------------------------------------------------------


class TestExtractRuntimeProbeTextLayer(unittest.TestCase):
    """frontmatter_block.py's restricted-YAML-subset parser for the
    `runtime_probe:` declaration — stdlib-only, no PyYAML."""

    def test_absent_when_fm_block_is_none(self):
        result = extract_runtime_probe(None)
        self.assertEqual(result, {"status": "absent"})

    def test_absent_when_no_runtime_probe_top_key(self):
        result = extract_runtime_probe("unrelated: true\nother: 1\n")
        self.assertEqual(result, {"status": "absent"})

    def test_ok_minimal_two_required_fields(self):
        fm = "runtime_probe:\n  partition: .aria/x.jsonl\n  symbol: run_gate\n"
        result = extract_runtime_probe(fm)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["fields"], {"partition": ".aria/x.jsonl", "symbol": "run_gate"})

    def test_trailing_comment_stripped(self):
        fm = "runtime_probe:\n  partition: .aria/x.jsonl   # a trailing comment\n  symbol: run_gate\n"
        result = extract_runtime_probe(fm)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["fields"]["partition"], ".aria/x.jsonl")

    def test_hash_without_leading_space_kept_literal(self):
        """Bare-scalar semantics (module docstring): a '#' NOT preceded by a
        space is left as literal text, not treated as a comment marker."""
        fm = "runtime_probe:\n  partition: .aria/x.jsonl#nospace\n  symbol: run_gate\n"
        result = extract_runtime_probe(fm)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["fields"]["partition"], ".aria/x.jsonl#nospace")

    def test_tolerates_unknown_extra_subkey(self):
        """Deliberate leniency (module docstring): tolerated and passed
        through in `fields` — explicitly NOT a 5th textual rejection
        form."""
        fm = "runtime_probe:\n  partition: .aria/x.jsonl\n  symbol: run_gate\n  bogus_key: whatever\n"
        result = extract_runtime_probe(fm)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["fields"]["bogus_key"], "whatever")

    def test_stops_at_sibling_top_level_key(self):
        """Dedent (indent==0) ends the runtime_probe block. A realistic
        proposal.md frontmatter has other top-level keys (e.g.
        `unverified_claims`) that must not be swallowed into `fields`."""
        fm = (
            "runtime_probe:\n"
            "  partition: .aria/x.jsonl\n"
            "  symbol: run_gate\n"
            "unverified_claims:\n"
            "  - foo\n"
        )
        result = extract_runtime_probe(fm)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["fields"], {"partition": ".aria/x.jsonl", "symbol": "run_gate"})

    # --- SC-2/SC-5 text layer: the 4 rejection forms ---

    def test_rejects_deeper_nesting(self):
        fm = "runtime_probe:\n  partition: .aria/x.jsonl\n  symbol:\n    nested: oops\n"
        result = extract_runtime_probe(fm)
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["reason"], "deeper_nesting")

    def test_rejects_flow_style_mapping(self):
        fm = "runtime_probe:\n  partition: .aria/x.jsonl\n  enabled_when: {a: b}\n"
        result = extract_runtime_probe(fm)
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["reason"], "flow_style_mapping")

    def test_rejects_anchor_or_alias(self):
        fm = "runtime_probe:\n  partition: .aria/x.jsonl\n  symbol: &anchor\n"
        result = extract_runtime_probe(fm)
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["reason"], "anchor_or_alias")

    def test_rejects_multiline_block_scalar(self):
        fm = "runtime_probe:\n  partition: |\n    multi\n    line\n"
        result = extract_runtime_probe(fm)
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["reason"], "multiline_value")

    def test_frontmatter_block_requires_absolute_file_start(self):
        """`_frontmatter_block` anchors at the file's ABSOLUTE start — a
        `---` block appearing later in the prose body (e.g. a markdown
        horizontal rule) is never mistaken for a frontmatter delimiter."""
        text = "# Title\n\nSome prose.\n\n---\nnot: frontmatter\n---\n"
        self.assertIsNone(_frontmatter_block(text))

        text_ok = "---\nfoo: bar\n---\n\n# Title\n"
        self.assertEqual(_frontmatter_block(text_ok), "foo: bar")


# ---------------------------------------------------------------------------
# SC-2 lock — proposal.md §What Changes 1's official example, hardcoded
# verbatim (including trailing comments), so this test is hermetic: it does
# not read proposal.md at runtime, it pins the exact bytes as of the spec's
# approved text. Markdown's 3-space numbered-list code-fence indent has been
# stripped (that indent belongs to the surrounding prose list item, not the
# YAML content itself) — verified byte-for-byte at authoring time against
# openspec/changes/runtime-probe-archive-gate-integration/proposal.md lines
# 35-39 via `repr()` (not hand-transcribed).
# ---------------------------------------------------------------------------

_OFFICIAL_EXAMPLE_YAML = (
    "runtime_probe:\n"
    "  partition: .aria/coordination-telemetry.jsonl   # 生产 telemetry 分区路径 (必填; 必须相对路径且 resolve 后含于 repo)\n"
    "  symbol: run_gate                                # 盯的符号 (必填; 消息标签用, 不做记录级过滤)\n"
    "  max_age_days: 14                                # 新鲜度窗口 (可选, 默认 14; 必须正整数 ≥1)\n"
    "  enabled_when: state_scanner.coordination.enabled # 可选: .aria/config.json dotted-path 开关\n"
)


class TestOfficialExampleHermetic(unittest.TestCase):
    """SC-2 lock: the proposal's own §What 1 example (with trailing
    comments) must parse cleanly end-to-end through both layers, producing
    all 4 fields correctly."""

    def test_official_example_text_layer_extracts_all_four_fields_verbatim(self):
        full_text = "---\n" + _OFFICIAL_EXAMPLE_YAML + "---\n\n# Proposal body\n"
        fm_body = _frontmatter_block(full_text)
        self.assertIsNotNone(fm_body)
        result = extract_runtime_probe(fm_body)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            result["fields"],
            {
                "partition": ".aria/coordination-telemetry.jsonl",
                "symbol": "run_gate",
                "max_age_days": "14",
                "enabled_when": "state_scanner.coordination.enabled",
            },
        )

    def test_official_example_value_layer_round_trip_typed_descriptor(self):
        full_text = "---\n" + _OFFICIAL_EXAMPLE_YAML + "---\n\n# Proposal body\n"
        fields = extract_runtime_probe(_frontmatter_block(full_text))["fields"]
        with _tmp_repo() as repo:
            result = validate_descriptor(fields, repo)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            result["descriptor"],
            {
                "partition": ".aria/coordination-telemetry.jsonl",
                "symbol": "run_gate",
                "max_age_days": 14,
                "enabled_when": "state_scanner.coordination.enabled",
            },
        )


# ---------------------------------------------------------------------------
# TASK-002 — probe(): tri-state (pass / warn / skipped [/ invalid])
# ---------------------------------------------------------------------------


class TestProbeTriState(unittest.TestCase):
    """SC-2/SC-3: `pass` + the 4 `warn` forms, always against a fixed
    injected `now` (never the wall clock)."""

    def test_pass_recent_production_record_within_window(self):
        with _tmp_repo() as repo:
            _write_lines(repo / _PARTITION_REL, [_prod_record(_NOW - timedelta(days=1))])
            result = probe(_descriptor(), repo, _NOW)
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["symbol"], _DEFAULT_SYMBOL)

    def test_warn_partition_missing(self):
        with _tmp_repo() as repo:
            # partition file never written
            result = probe(_descriptor(), repo, _NOW)
        self.assertEqual(result["outcome"], "warn")
        self.assertEqual(result["count"], 0)
        self.assertIn("missing", result["reason"])

    def test_warn_partition_unreadable_io_error(self):
        """The fixed false-green edge (proposal §What 2): a partition that
        EXISTS but fails to read must warn, not silently pass (the old
        coordination_probe.py bug this generalization deliberately fixes)."""
        _skip_if_root()
        with _tmp_repo() as repo:
            partition = repo / _PARTITION_REL
            _write_lines(partition, [_prod_record(_NOW - timedelta(days=1))])
            os.chmod(partition, 0o000)
            try:
                result = probe(_descriptor(), repo, _NOW)
            finally:
                os.chmod(partition, 0o644)  # restore so tempdir cleanup can unlink it
        self.assertEqual(result["outcome"], "warn")
        self.assertIn("unreadable", result["reason"])
        self.assertIn("IO error", result["reason"])

    def test_warn_all_records_stale(self):
        with _tmp_repo() as repo:
            _write_lines(repo / _PARTITION_REL, [_prod_record(_NOW - timedelta(days=20))])
            result = probe(_descriptor(), repo, _NOW)
        self.assertEqual(result["outcome"], "warn")
        self.assertIn("all stale", result["reason"])

    def test_warn_only_nonproduction_records(self):
        with _tmp_repo() as repo:
            _write_lines(
                repo / _PARTITION_REL,
                [{"ts": _iso(_NOW - timedelta(days=1)), "source": "harness"}],
            )
            result = probe(_descriptor(), repo, _NOW)
        self.assertEqual(result["outcome"], "warn")
        self.assertEqual(result["count"], 0)

    def test_pass_with_tz_naive_now_normalized_to_utc(self):
        """`now` injected without tzinfo must be treated as UTC (module
        docstring: "tz-naive values are normalized to UTC — this exists so
        tests can inject a fixed clock deterministically")."""
        with _tmp_repo() as repo:
            _write_lines(repo / _PARTITION_REL, [_prod_record(_NOW - timedelta(days=1))])
            naive_now = _NOW.replace(tzinfo=None)
            result = probe(_descriptor(), repo, naive_now)
        self.assertEqual(result["outcome"], "pass")


# ---------------------------------------------------------------------------
# TASK-002 — probe(): skipped forms + enabled_when config traversal
# ---------------------------------------------------------------------------


class TestProbeSkippedAndConfigTraversal(unittest.TestCase):
    """SC-4 skipped forms + the 5th SC-5 value-layer invalid form
    (`enabled_when` dotted-path mid-segment non-dict) — the latter is only
    decidable here, against the REAL `.aria/config.json` content, per
    runtime_probe.py's own module docstring "division of labor" note."""

    _ENABLED_WHEN = "state_scanner.coordination.enabled"

    def test_skipped_enabled_when_switch_off(self):
        with _tmp_repo() as repo:
            _write_config(
                repo / ".aria" / "config.json",
                {"state_scanner": {"coordination": {"enabled": False}}},
            )
            result = probe(_descriptor(enabled_when=self._ENABLED_WHEN), repo, _NOW)
        self.assertEqual(result["outcome"], "skipped")
        self.assertIn("off", result["reason"])

    def test_skipped_config_file_missing(self):
        with _tmp_repo() as repo:
            # .aria/config.json never written
            result = probe(_descriptor(enabled_when=self._ENABLED_WHEN), repo, _NOW)
        self.assertEqual(result["outcome"], "skipped")
        self.assertIn("missing", result["reason"])

    def test_skipped_config_file_malformed_json(self):
        """`_load_config` collapses ANY failure (missing / unreadable /
        malformed JSON / non-object top-level) into the same conservative
        skip bucket — never warn (module docstring: "cannot confirm the
        switch should be on, so don't cry warn")."""
        with _tmp_repo() as repo:
            _write_config(repo / ".aria" / "config.json", "{not valid json")
            result = probe(_descriptor(enabled_when=self._ENABLED_WHEN), repo, _NOW)
        self.assertEqual(result["outcome"], "skipped")

    def test_skipped_enabled_when_segment_not_configured_defaults_off(self):
        """A missing key at any level means 'switch not configured' = off —
        NOT an error (contrast with the mid-segment-non-dict invalid form
        below, which IS an error)."""
        with _tmp_repo() as repo:
            _write_config(repo / ".aria" / "config.json", {"some_other_key": True})
            result = probe(_descriptor(enabled_when=self._ENABLED_WHEN), repo, _NOW)
        self.assertEqual(result["outcome"], "skipped")
        self.assertIn("off", result["reason"])

    def test_invalid_enabled_when_middle_segment_not_dict(self):
        """SC-5 value layer, 5th form: `enabled_when` dotted-path walks
        through a non-dict value mid-path in the REAL config content ->
        outcome='invalid' (per probe()'s own docstring: "only decidable
        here" — this is intentionally NOT covered by
        TestValidateDescriptorValueLayer)."""
        with _tmp_repo() as repo:
            _write_config(
                repo / ".aria" / "config.json",
                {"state_scanner": "oops-a-string-not-a-dict"},
            )
            result = probe(_descriptor(enabled_when=self._ENABLED_WHEN), repo, _NOW)
        self.assertEqual(result["outcome"], "invalid")
        self.assertIn("coordination", result["reason"])

    def test_pass_enabled_when_switch_on_falls_through_to_partition_scan(self):
        with _tmp_repo() as repo:
            _write_config(
                repo / ".aria" / "config.json",
                {"state_scanner": {"coordination": {"enabled": True}}},
            )
            _write_lines(repo / _PARTITION_REL, [_prod_record(_NOW - timedelta(days=1))])
            result = probe(_descriptor(enabled_when=self._ENABLED_WHEN), repo, _NOW)
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["count"], 1)


# ---------------------------------------------------------------------------
# TASK-002 — probe()/_scan_partition parsing robustness
# ---------------------------------------------------------------------------


class TestProbeParsingRobustness(unittest.TestCase):
    """Malformed JSONL lines and malformed `ts` never crash the scan;
    `max_age_days` is fully caller-controlled; `symbol` never filters
    records (message label only)."""

    def test_bad_json_line_skipped_not_fatal(self):
        with _tmp_repo() as repo:
            _write_lines(
                repo / _PARTITION_REL,
                ["not-json-at-all-{{{", _prod_record(_NOW - timedelta(days=1))],
            )
            result = probe(_descriptor(), repo, _NOW)
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["count"], 1)

    def test_bad_timestamp_record_skipped_counts_as_stale(self):
        """A production record whose `ts` fails to parse is never counted
        as recent — but it DOES count as 'saw a production record', so the
        outcome lands in the all-stale warn bucket, not the different
        no-production-at-all warn message."""
        with _tmp_repo() as repo:
            _write_lines(
                repo / _PARTITION_REL, [{"ts": "not-a-timestamp", "source": "production"}]
            )
            result = probe(_descriptor(), repo, _NOW)
        self.assertEqual(result["outcome"], "warn")
        self.assertEqual(result["count"], 0)
        self.assertIn("all stale", result["reason"])

    def test_custom_max_age_days_window_narrows_recency(self):
        """A record 2 days old is `pass` under the default 14d window but
        `warn` (stale) under a caller-supplied 1d window."""
        with _tmp_repo() as repo:
            two_days_ago = _NOW - timedelta(days=2)
            _write_lines(repo / _PARTITION_REL, [_prod_record(two_days_ago)])

            wide = probe(_descriptor(max_age_days=14), repo, _NOW)
            narrow = probe(_descriptor(max_age_days=1), repo, _NOW)

        self.assertEqual(wide["outcome"], "pass")
        self.assertEqual(narrow["outcome"], "warn")
        self.assertIn("all stale", narrow["reason"])

    def test_symbol_is_label_only_does_not_filter_records(self):
        """`symbol` is a message label ONLY — records carry no `symbol`
        field at all, and probing with an arbitrary/unrelated symbol string
        still counts them (module docstring: "does NOT filter records")."""
        with _tmp_repo() as repo:
            _write_lines(repo / _PARTITION_REL, [_prod_record(_NOW - timedelta(days=1))])
            result = probe(_descriptor(symbol="totally_unrelated_label"), repo, _NOW)
        self.assertEqual(result["outcome"], "pass")
        self.assertEqual(result["symbol"], "totally_unrelated_label")


# ---------------------------------------------------------------------------
# TASK-014 — falsifiable harness: "probe 恒 pass" variant injection (SC-8)
# ---------------------------------------------------------------------------


def _always_pass_variant(descriptor: dict, repo: Path, now: datetime) -> dict:
    """The SC-8 mutant: a drop-in stand-in for ``probe()`` that
    unconditionally reports ``outcome="pass"`` — no partition read, no
    staleness cutoff, no ``enabled_when`` traversal; ``descriptor``/``repo``/
    ``now`` are all ignored. This is the shape a real regression would take
    if e.g. the staleness cutoff were accidentally dropped or a warn/skipped
    branch got short-circuited to pass.

    Matches ``probe()``'s exact positional signature — the only calling
    convention used anywhere in this codebase (``coordination_probe.py``'s
    ``probe(_DESCRIPTOR, repo, now)`` and ``spec_complete.py``'s
    ``_rp_probe(validated["descriptor"], project_root, now)``) — so it is
    call-compatible everywhere the real ``probe`` is invoked.
    """
    return {
        "outcome": "pass",
        "count": 1,
        "reason": "SC-8 harness variant: constant pass, all input ignored",
        "symbol": descriptor.get("symbol", "") if isinstance(descriptor, dict) else "",
    }


class TestFalsifiableAlwaysPassVariant(unittest.TestCase):
    """SC-8 anti-false-green harness (DEC-002 tradition —
    ``test_phase1_gate_telemetry.py``'s ``TestTelemetryPartitionAntiSpoof`` /
    ``TestCoordinationProbe.test_probe_stale_production_record_fails``
    precedent of pinning "a degraded implementation must be CAUGHT", not
    merely "a correct implementation passes").

    Machine proof required by SC-8: "若实现退化为恒 pass, 测试套会红" — if
    ``probe()`` ever regresses into something behaviorally equivalent to
    ``_always_pass_variant`` above, this test suite must go red, not stay
    silently green.

    Mechanism: ``mock.patch.object(runtime_probe, "probe",
    _always_pass_variant)`` swaps the MODULE ATTRIBUTE inside a controlled
    ``with`` block — additive, test-process-only, never touches production
    ``runtime_probe.py`` on disk. Each sensitivity-point test below follows
    the same two-step shape:

      1. Sanity — assert the REAL (unpatched) implementation genuinely
         produces the non-pass outcome for this fixture. Without this step,
         "the assertion fails under the variant" could be vacuously true for
         the wrong reason (e.g. a broken fixture that never distinguished
         real-vs-variant behavior to begin with).
      2. Proof — inside the patched context, re-run the assertion used by
         the sibling representative test (same fixture, same expected
         outcome as ``TestProbeTriState``/``TestProbeSkippedAndConfigTraversal``,
         not a weakened restatement) wrapped in
         ``assertRaises(AssertionError)``: mechanically demonstrates that
         assertion goes red under the mutant.

    Two mandated sensitivity points (task verification bullet, parent 3.4):
      - warn 形态判定: 全陈旧 (all-stale) fixture, twin of
        ``TestProbeTriState.test_warn_all_records_stale``.
      - skipped 判定: ``enabled_when`` 开关关 fixture, twin of
        ``TestProbeSkippedAndConfigTraversal.test_skipped_enabled_when_switch_off``.

    Why this is not vacuous (three independent guards):
      (a) the variant is invoked through the SAME call path production code
          uses — module-attribute lookup ``runtime_probe.probe(...)`` —
          proven distinct from the bare ``from runtime_probe import probe``
          name imported at file top (used by every OTHER test in this file)
          by ``test_bare_imported_name_survives_patch`` below. If that guard
          ever failed, the two proof tests above would silently stop
          injecting the variant and pass for a meaningless reason.
      (b) the re-run assertion in each proof test targets the identical
          fixture + expected outcome as its sibling's real assertion — no
          weakened threshold, no relaxed shape check.
      (c) the sanity pre-check in step 1 fails loudly (redundantly with the
          sibling test's own coverage) if the fixture itself ever stops
          distinguishing real-vs-variant behavior.
    """

    _ENABLED_WHEN = "state_scanner.coordination.enabled"

    def test_all_stale_variant_flips_warn_assertion_to_failure(self):
        """Sensitivity point 1/2 (SC-8): 全陈旧 → pass 变体应被抓."""
        with _tmp_repo() as repo:
            _write_lines(repo / _PARTITION_REL, [_prod_record(_NOW - timedelta(days=20))])

            real_result = runtime_probe.probe(_descriptor(), repo, _NOW)
            self.assertEqual(
                real_result["outcome"],
                "warn",
                "sanity precondition failed: fixture must genuinely warn "
                "under the REAL implementation, else the demonstration "
                "below would be vacuous",
            )

            with mock.patch.object(runtime_probe, "probe", _always_pass_variant):
                patched_result = runtime_probe.probe(_descriptor(), repo, _NOW)
                with self.assertRaises(
                    AssertionError,
                    msg="HARNESS IS VACUOUS: the all-stale warn assertion "
                    "did not go red under the constant-pass variant — the "
                    "test suite would not catch a probe() regression to "
                    "always-pass",
                ):
                    self.assertEqual(patched_result["outcome"], "warn")

    def test_switch_off_variant_flips_skipped_assertion_to_failure(self):
        """Sensitivity point 2/2 (SC-8): 开关关 → pass 变体应被抓."""
        with _tmp_repo() as repo:
            _write_config(
                repo / ".aria" / "config.json",
                {"state_scanner": {"coordination": {"enabled": False}}},
            )
            real_result = runtime_probe.probe(
                _descriptor(enabled_when=self._ENABLED_WHEN), repo, _NOW
            )
            self.assertEqual(
                real_result["outcome"],
                "skipped",
                "sanity precondition failed: fixture must genuinely skip "
                "under the REAL implementation, else the demonstration "
                "below would be vacuous",
            )

            with mock.patch.object(runtime_probe, "probe", _always_pass_variant):
                patched_result = runtime_probe.probe(
                    _descriptor(enabled_when=self._ENABLED_WHEN), repo, _NOW
                )
                with self.assertRaises(
                    AssertionError,
                    msg="HARNESS IS VACUOUS: the switch-off skipped "
                    "assertion did not go red under the constant-pass "
                    "variant — the test suite would not catch a probe() "
                    "regression to always-pass",
                ):
                    self.assertEqual(patched_result["outcome"], "skipped")

    def test_bare_imported_name_survives_patch(self):
        """Structural guard underpinning guarantee (a) above:
        ``mock.patch.object(runtime_probe, "probe", ...)`` rebinds only the
        MODULE's own attribute. The bare ``probe`` name imported at file top
        (``from runtime_probe import probe``, used by every OTHER test in
        this file) is a separate binding captured at import time and is NOT
        affected — proving the two proof tests above exercise the variant
        via the intended call path, rather than accidentally testing
        nothing."""
        with _tmp_repo() as repo:
            _write_lines(repo / _PARTITION_REL, [_prod_record(_NOW - timedelta(days=20))])
            with mock.patch.object(runtime_probe, "probe", _always_pass_variant):
                bare_result = probe(_descriptor(), repo, _NOW)  # unpatched binding
                patched_result = runtime_probe.probe(_descriptor(), repo, _NOW)  # patched
        self.assertEqual(
            bare_result["outcome"], "warn", "bare imported name must still be the real probe()"
        )
        self.assertEqual(
            patched_result["outcome"], "pass", "module attribute must be the injected variant"
        )


if __name__ == "__main__":
    unittest.main()
