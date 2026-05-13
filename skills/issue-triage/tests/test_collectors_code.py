"""T4 — Code collector tests: citation format parsing + dedup.

Covers:
  - Mid-review concern 6: 3+ citation formats, each with >= 1 assertion on 'format' field
  - backtick, prose_line, prose_l, md_link (remote URL), md_link_local
  - Deduplication: same (file_path, line) from multiple formats appears once
  - Issue body with no citations -> cited_paths=[] (not null), collection_status=skipped

References:
  T1.4 — Step 3 citation formats (3+ required, R1 QA-m4)
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from collectors._code import _extract_citations, collect_code


class TestCitationExtractionFormats:
    """Mid-review concern 6: each citation format produces 'format' field assertions."""

    def test_backtick_format_with_line_number(self) -> None:
        """Backtick inline with line number: `file.py:42` -> format='backtick', line=42.

        T1.4 format 1: backtick inline citation.
        """
        text = "The bug is in `scripts/collectors/_inflight.py:42` somewhere."
        citations = _extract_citations(text)
        backtick_hits = [c for c in citations if c["format"] == "backtick"]
        assert len(backtick_hits) >= 1
        hit = backtick_hits[0]
        assert hit["format"] == "backtick"
        assert hit["line"] == 42
        assert "_inflight.py" in hit["file_path"]

    def test_backtick_format_without_line_number(self) -> None:
        """Backtick without line number: `file.py` -> format='backtick', line=None."""
        text = "See `scripts/collectors/_common.py` for the base class."
        citations = _extract_citations(text)
        backtick_hits = [c for c in citations if c["format"] == "backtick"]
        assert len(backtick_hits) >= 1
        assert backtick_hits[0]["line"] is None

    def test_prose_line_format(self) -> None:
        """Prose 'line N' reference: file.py line 42 -> format='prose_line'.

        T1.4 format 2a: prose line citation.
        Mid-review concern 6: assertion on 'format' field.
        """
        text = "See collectors/_version.py line 42 for the fail-soft chain."
        citations = _extract_citations(text)
        prose_hits = [c for c in citations if c["format"] == "prose_line"]
        assert len(prose_hits) >= 1
        hit = prose_hits[0]
        assert hit["format"] == "prose_line"
        assert hit["line"] == 42

    def test_prose_l_format_colon_prefix(self) -> None:
        """Prose :L42 or :42 reference -> format='prose_l'.

        T1.4 format 2b: prose L-prefix citation.
        Mid-review concern 6: assertion on 'format' field.
        """
        text = "Relevant code at collectors/_history.py:L99."
        citations = _extract_citations(text)
        prose_l_hits = [c for c in citations if c["format"] == "prose_l"]
        assert len(prose_l_hits) >= 1
        hit = prose_l_hits[0]
        assert hit["format"] == "prose_l"
        assert hit["line"] == 99

    def test_prose_l_format_bare_colon(self) -> None:
        """Bare colon reference: file.py:42 -> format='prose_l'."""
        text = "Error occurs at scripts/collectors/_code.py:28."
        citations = _extract_citations(text)
        prose_l_hits = [c for c in citations if c["format"] == "prose_l"]
        assert len(prose_l_hits) >= 1
        assert prose_l_hits[0]["line"] == 28

    def test_md_link_remote_url_format(self) -> None:
        """Remote URL markdown link: [text](https://.../_inflight.py#L42) -> format='md_link'.

        T1.4 format 3a: markdown link with remote URL.
        Mid-review concern 6: assertion on 'format' field.
        """
        text = (
            "See [_inflight.py]"
            "(https://forgejo.10cg.pub/10CG/Aria/src/branch/master/"
            "aria/skills/issue-triage/scripts/collectors/_inflight.py#L42)"
        )
        citations = _extract_citations(text)
        md_hits = [c for c in citations if c["format"] == "md_link"]
        assert len(md_hits) >= 1
        hit = md_hits[0]
        assert hit["format"] == "md_link"
        assert hit["line"] == 42

    def test_md_link_local_path_format(self) -> None:
        """Local path markdown link: [text](path/to/file.py#L28) -> format='md_link_local'.

        T1.4 format 3b: markdown link with local relative path.
        Mid-review concern 6: assertion on 'format' field.
        """
        text = "Related: [_common.py](scripts/collectors/_common.py#L28)"
        citations = _extract_citations(text)
        local_hits = [c for c in citations if c["format"] == "md_link_local"]
        assert len(local_hits) >= 1
        hit = local_hits[0]
        assert hit["format"] == "md_link_local"
        assert hit["line"] == 28

    def test_md_link_without_anchor(self) -> None:
        """Markdown link without #L anchor -> format='md_link_local', line=None."""
        text = "See [_common.py](scripts/collectors/_common.py) for shared infrastructure."
        citations = _extract_citations(text)
        local_hits = [c for c in citations if c["format"] == "md_link_local"]
        assert len(local_hits) >= 1
        assert local_hits[0]["line"] is None


class TestCitationDeduplication:
    """Same (file_path, line) pair from multiple formats appears only once in output."""

    def test_same_path_line_deduplicated(self) -> None:
        """Same file:line appearing in two formats -> deduplicated to one entry.

        T1.4 dedup requirement.
        """
        # Both backtick and prose_l reference the same file:line
        text = (
            "Bug in `scripts/collectors/_inflight.py:42`.\n"
            "Also see scripts/collectors/_inflight.py:42 for context."
        )
        citations = _extract_citations(text)
        # Count how many times this exact (file, line) pair appears
        pairs = [(c["file_path"], c["line"]) for c in citations]
        target = next(
            (fp for fp, _ in pairs if "_inflight.py" in fp), None
        )
        assert target is not None
        count = sum(1 for fp, ln in pairs if "_inflight.py" in fp and ln == 42)
        assert count == 1, f"Expected 1 deduplicated entry but got {count}: {citations}"

    def test_same_path_different_lines_not_deduplicated(self) -> None:
        """Same file, different lines -> two separate entries."""
        text = (
            "`scripts/collectors/_inflight.py:10` and "
            "`scripts/collectors/_inflight.py:20`"
        )
        citations = _extract_citations(text)
        lines = [c["line"] for c in citations if "_inflight.py" in c["file_path"]]
        assert 10 in lines
        assert 20 in lines


class TestCollectCodeWithRealFiles:
    """collect_code() integration: verify against real filesystem."""

    def test_no_citations_returns_skipped(self, issue_body_no_citation: str, tmp_path: Path) -> None:
        """Issue body with no citations -> collection_status=skipped, cited_paths=[].

        T4 edge case: no citations.
        """
        result = collect_code(tmp_path, issue_body_no_citation, [])
        assert result.data["collection_status"] == "skipped"
        assert result.data["cited_paths"] == []
        assert result.data["cited_paths"] is not None  # must be [] not None

    def test_nonexistent_file_exists_false(self, tmp_path: Path) -> None:
        """Citation pointing to a non-existent file -> exists=False.

        T4.4: cited file does not exist.
        """
        text = "`nonexistent/path/missing.py:5`"
        result = collect_code(tmp_path, text, [])
        assert result.data["collection_status"] == "ok"
        cited = result.data["cited_paths"]
        assert len(cited) >= 1
        assert cited[0]["exists"] is False

    def test_nonexistent_file_matches_description_false(self, tmp_path: Path) -> None:
        """Cited file missing -> matches_description=False.

        T4.4: cited file does not exist -> matches_description: false.
        """
        text = "`nonexistent/path/missing.py:5`"
        result = collect_code(tmp_path, text, [])
        assert result.data["matches_description"] is False

    def test_existing_file_exists_true(self, tmp_path: Path) -> None:
        """Citation pointing to an existing file -> exists=True."""
        target = tmp_path / "scripts" / "collectors" / "_version.py"
        target.parent.mkdir(parents=True)
        target.write_text("# version stub\n" * 10, encoding="utf-8")

        text = "`scripts/collectors/_version.py:5`"
        result = collect_code(tmp_path, text, [])
        assert result.data["collection_status"] == "ok"
        cited = result.data["cited_paths"]
        existing = [c for c in cited if c.get("exists") is True]
        assert len(existing) >= 1

    def test_line_out_of_range_warning(self, tmp_path: Path) -> None:
        """Line number beyond file length -> line_in_range=False and warning set.

        T4.4: line shift -> flag warning.
        """
        target = tmp_path / "scripts" / "_short.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("line1\nline2\nline3\n", encoding="utf-8")

        text = "`scripts/_short.py:999`"
        result = collect_code(tmp_path, text, [])
        cited = result.data["cited_paths"]
        assert len(cited) >= 1
        assert cited[0]["line_in_range"] is False
        assert cited[0]["warning"] is not None

    def test_backtick_citation_format_field(self, tmp_path: Path) -> None:
        """collect_code propagates format='backtick' through to output.

        Mid-review concern 6: end-to-end format field assertion.
        """
        target = tmp_path / "scripts" / "_mod.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# stub\n" * 20, encoding="utf-8")

        text = "`scripts/_mod.py:5`"
        result = collect_code(tmp_path, text, [])
        cited = result.data["cited_paths"]
        formats = [c["format"] for c in cited]
        assert "backtick" in formats

    def test_prose_line_format_field(self, tmp_path: Path) -> None:
        """collect_code propagates format='prose_line' through to output.

        Mid-review concern 6: end-to-end format field assertion.
        """
        target = tmp_path / "scripts" / "_mod.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# stub\n" * 20, encoding="utf-8")

        text = "See scripts/_mod.py line 5 for details."
        result = collect_code(tmp_path, text, [])
        cited = result.data["cited_paths"]
        formats = [c["format"] for c in cited]
        assert "prose_line" in formats

    def test_md_link_local_format_field(self, tmp_path: Path) -> None:
        """collect_code propagates format='md_link_local' through to output.

        Mid-review concern 6: end-to-end format field assertion.
        """
        target = tmp_path / "scripts" / "_mod.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# stub\n" * 20, encoding="utf-8")

        text = "See [_mod.py](scripts/_mod.py#L5) for details."
        result = collect_code(tmp_path, text, [])
        cited = result.data["cited_paths"]
        formats = [c["format"] for c in cited]
        assert "md_link_local" in formats
