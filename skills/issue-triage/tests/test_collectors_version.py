"""T4 — Version collector tests: 5-path fail-soft + triage_tool_version.

Covers:
  - Mid-review concern 4: 5 fixtures (each path present individually) + all-absent
  - Mid-review concern 5: standalone-repo (path 2 only) -> triage_tool_version populated
  - T1.3 fail-soft chain: first hit wins, all-absent -> unknown/null

Each path in the chain:
  1. {project_root}/aria/.claude-plugin/plugin.json  (Aria meta-repo)
  2. {project_root}/.claude-plugin/plugin.json        (Aria plugin standalone)
  3. {project_root}/VERSION                            (plain version file)
  4. {project_root}/package.json                       (JS projects)
  5. {project_root}/pyproject.toml                     (Python projects)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from collectors._version import collect_version


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class TestVersionPath1AriaMetaRepo:
    """Path 1: {root}/aria/.claude-plugin/plugin.json"""

    def test_path1_only_resolves_version(self, tmp_path: Path) -> None:
        """Path 1 present alone -> collection_status=ok, version from plugin.json.

        Mid-review concern 4: path 1 individually.
        """
        _write_json(
            tmp_path / "aria" / ".claude-plugin" / "plugin.json",
            {"name": "aria", "version": "1.19.0"},
        )
        result = collect_version(tmp_path, "", [])
        assert result.data["collection_status"] == "ok"
        assert result.data["current"] == "1.19.0"

    def test_path1_seeds_triage_tool_version(self, tmp_path: Path) -> None:
        """Path 1 also populates _triage_tool_version (for triage.py to promote).

        T1.3, R2 QA-R2-m3.
        """
        _write_json(
            tmp_path / "aria" / ".claude-plugin" / "plugin.json",
            {"name": "aria", "version": "1.18.0"},
        )
        result = collect_version(tmp_path, "", [])
        assert result.data.get("_triage_tool_version") == "1.18.0"


class TestVersionPath2StandalonePlugin:
    """Path 2: {root}/.claude-plugin/plugin.json (Aria plugin standalone repo).

    Mid-review M2 fix: path 2 ALSO seeds triage_tool_version.
    """

    def test_path2_only_resolves_version(self, standalone_plugin_repo: Path) -> None:
        """Path 2 present alone (no path 1) -> collection_status=ok.

        Mid-review concern 4: path 2 individually.
        Mid-review concern 5: standalone-repo case.
        """
        result = collect_version(standalone_plugin_repo, "", [])
        assert result.data["collection_status"] == "ok"
        assert result.data["current"] == "1.19.0"

    def test_path2_seeds_triage_tool_version(self, standalone_plugin_repo: Path) -> None:
        """Path 2 ALSO seeds _triage_tool_version (M2 fix, NOT 'unknown').

        Mid-review concern 5: triage_tool_version must NOT be 'unknown' when
        path 2 is present. This is the key regression test for the M2 fix.
        """
        result = collect_version(standalone_plugin_repo, "", [])
        ttv = result.data.get("_triage_tool_version")
        assert ttv == "1.19.0", (
            f"Expected '1.19.0' from path 2 but got {ttv!r}. "
            "This indicates the M2 fix (path 2 seeding triage_tool_version) is broken."
        )

    def test_path2_not_unknown_when_present(self, standalone_plugin_repo: Path) -> None:
        """Explicit NOT-unknown assertion: path 2 present -> triage_tool_version != 'unknown'.

        Mid-review concern 5 (regression guard).
        """
        result = collect_version(standalone_plugin_repo, "", [])
        assert result.data.get("_triage_tool_version") != "unknown"


class TestVersionPath3VersionFile:
    """Path 3: {root}/VERSION (plain text semver)."""

    def test_path3_only_resolves_version(self, tmp_path: Path) -> None:
        """VERSION file present alone -> collection_status=ok.

        Mid-review concern 4: path 3 individually.
        """
        (tmp_path / "VERSION").write_text("2.3.1\n", encoding="utf-8")
        result = collect_version(tmp_path, "", [])
        assert result.data["collection_status"] == "ok"
        assert result.data["current"] == "2.3.1"

    def test_path3_does_not_seed_triage_tool_version(self, tmp_path: Path) -> None:
        """VERSION file path does NOT seed triage_tool_version (only plugin.json paths do)."""
        (tmp_path / "VERSION").write_text("2.3.1\n", encoding="utf-8")
        result = collect_version(tmp_path, "", [])
        # _triage_tool_version should be "unknown" since no plugin.json was found
        assert result.data.get("_triage_tool_version") == "unknown"


class TestVersionPath4PackageJson:
    """Path 4: {root}/package.json."""

    def test_path4_only_resolves_version(self, tmp_path: Path) -> None:
        """package.json present alone -> collection_status=ok.

        Mid-review concern 4: path 4 individually.
        """
        _write_json(tmp_path / "package.json", {"name": "myapp", "version": "3.0.0"})
        result = collect_version(tmp_path, "", [])
        assert result.data["collection_status"] == "ok"
        assert result.data["current"] == "3.0.0"


class TestVersionPath5PyprojectToml:
    """Path 5: {root}/pyproject.toml."""

    def test_path5_only_resolves_version(self, tmp_path: Path) -> None:
        """pyproject.toml present alone -> collection_status=ok.

        Mid-review concern 4: path 5 individually.
        """
        content = '[project]\nname = "mypackage"\nversion = "0.9.1"\n'
        (tmp_path / "pyproject.toml").write_text(content, encoding="utf-8")
        result = collect_version(tmp_path, "", [])
        assert result.data["collection_status"] == "ok"
        assert result.data["current"] == "0.9.1"


class TestVersionAllAbsent:
    """All 5 paths absent -> version.current = 'unknown', gap = null.

    Mid-review concern 4: all-absent case.
    """

    def test_all_paths_absent_returns_unknown(self, tmp_path: Path) -> None:
        """Empty directory -> collection_status=error, current='unknown'.

        Mid-review concern 4: all 5 paths absent.
        """
        result = collect_version(tmp_path, "", [])
        assert result.data["collection_status"] == "error"
        assert result.data["current"] == "unknown"
        assert result.data["gap"] is None

    def test_all_absent_triage_tool_version_unknown(self, tmp_path: Path) -> None:
        """All paths absent -> _triage_tool_version = 'unknown'."""
        result = collect_version(tmp_path, "", [])
        assert result.data.get("_triage_tool_version") == "unknown"

    def test_all_absent_has_soft_error(self, tmp_path: Path) -> None:
        """All paths absent -> at least one soft error recorded."""
        result = collect_version(tmp_path, "", [])
        assert len(result.errors) >= 1


class TestVersionReportedExtraction:
    """Extract reported version from issue body / comments."""

    def test_extracts_version_from_body(self, tmp_path: Path) -> None:
        """Regex extracts 'Plugin version: 1.18.0' from issue body."""
        _write_json(
            tmp_path / "aria" / ".claude-plugin" / "plugin.json",
            {"version": "1.19.0"},
        )
        body = "## Bug Report\n\nPlugin version: 1.18.0\n\nSomething is broken."
        result = collect_version(tmp_path, body, [])
        assert result.data["reported"] == "1.18.0"

    def test_extracts_version_from_comment(self, tmp_path: Path) -> None:
        """Regex extracts version string from a comment dict."""
        _write_json(
            tmp_path / "aria" / ".claude-plugin" / "plugin.json",
            {"version": "1.19.0"},
        )
        comments = [{"body": "I'm on v1.17.2 and also seeing this."}]
        result = collect_version(tmp_path, "", comments)
        assert result.data["reported"] == "1.17.2"

    def test_no_version_in_body_reported_is_none(self, tmp_path: Path) -> None:
        """Issue body with no version string -> reported=None."""
        _write_json(
            tmp_path / "aria" / ".claude-plugin" / "plugin.json",
            {"version": "1.19.0"},
        )
        result = collect_version(tmp_path, "No version mentioned here.", [])
        assert result.data["reported"] is None
        assert result.data["gap"] is None

    def test_version_gap_behind(self, tmp_path: Path) -> None:
        """Reported version older than current -> gap='behind'."""
        _write_json(
            tmp_path / "aria" / ".claude-plugin" / "plugin.json",
            {"version": "1.19.0"},
        )
        body = "Plugin version: 1.18.0"
        result = collect_version(tmp_path, body, [])
        assert result.data["gap"] == "behind"

    def test_version_gap_same(self, tmp_path: Path) -> None:
        """Reported == current -> gap='same'."""
        _write_json(
            tmp_path / "aria" / ".claude-plugin" / "plugin.json",
            {"version": "1.19.0"},
        )
        body = "Plugin version: 1.19.0"
        result = collect_version(tmp_path, body, [])
        assert result.data["gap"] == "same"

    def test_path1_wins_over_path2(self, tmp_path: Path) -> None:
        """Path 1 present -> path 2 is not read (first-hit-wins chain).

        Verifies the fail-soft chain evaluation order is respected.
        """
        _write_json(
            tmp_path / "aria" / ".claude-plugin" / "plugin.json",
            {"version": "1.19.0"},
        )
        _write_json(
            tmp_path / ".claude-plugin" / "plugin.json",
            {"version": "2.0.0"},  # should NOT be used
        )
        result = collect_version(tmp_path, "", [])
        assert result.data["current"] == "1.19.0"  # path 1 wins
