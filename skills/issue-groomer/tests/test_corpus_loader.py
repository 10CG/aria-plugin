"""TASK-009 — corpus_loader tests against the REAL scratchpad corpus.

Counts asserted here (378 / 150 / 5 items + 6 comments) pin the canonical
2026-10-18 snapshots referenced by spec issue-groomer-p1-mvp. The corpus is
NOT copied into the repo (accepted single-point scratchpad risk): when the
scratchpad trio is absent these tests SKIP loudly with the regeneration
command in the skip reason — recovery is `scripts/regen_corpus.py`, which
re-fetches from the live API and writes the same structure.

The comment-edit synthesis tests need no corpus file (deterministic shapes)
except the one real-shape round-trip, which is corpus-guarded too.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
if str(_FIXTURES_DIR) not in sys.path:
    sys.path.insert(0, str(_FIXTURES_DIR))

import corpus_loader as cl  # noqa: E402

_HAS_CORPUS = all(
    (cl.DEFAULT_CORPUS_DIR / name).is_file()
    for name in (cl.FULL_FILENAME, cl.CURATED_FILENAME, cl.SAMPLE_FILENAME)
)

requires_corpus = pytest.mark.skipif(
    not _HAS_CORPUS,
    reason="scratchpad corpus trio absent (accepted single-point risk; spec "
           "issue-groomer-p1-mvp) — regenerate with: python3 "
           "aria/skills/issue-groomer/scripts/regen_corpus.py --date 2026-10-18",
)


def _repo_blocks(rows: list[dict]) -> list[str]:
    seq: list[str] = []
    for row in rows:
        if not seq or seq[-1] != row["repo"]:
            seq.append(row["repo"])
    return seq


def _repo_numbers(rows: list[dict], repo: str) -> list[int]:
    return [row["number"] for row in cl.by_repo(rows, repo)]


# ── counts against the real corpus (378 / 150 / 5+6) ────────────────────────

class TestCorpusCounts:

    @requires_corpus
    def test_full_snapshot_is_378_rows(self):
        assert len(cl.load_full()) == 378

    @requires_corpus
    def test_curated_snapshot_is_150_rows(self):
        assert len(cl.load_curated()) == 150

    @requires_corpus
    def test_sample_is_5_items_6_comments(self):
        doc = cl.load_sample()
        assert len(doc["items"]) == 5
        assert cl.sample_comments_total(doc) == 6

    @requires_corpus
    def test_full_covers_18_repos(self):
        assert len(set(row["repo"] for row in cl.load_full())) == 18

    @requires_corpus
    def test_curated_repo_set_is_the_four_aria_satellites(self):
        assert set(row["repo"] for row in cl.load_curated()) == set(cl.CURATED_REPO_ORDER)

    @requires_corpus
    def test_per_repo_spot_counts(self):
        full = cl.load_full()
        assert len(cl.by_repo(full, "Aether")) == 97
        assert len(cl.by_repo(full, "aria-plugin")) == 92
        assert len(cl.by_repo(full, "SilkNode")) == 63
        assert len(cl.by_repo(full, "Aria")) == 51

    @requires_corpus
    def test_sample_counts_field_matches_fetched_comments(self):
        for item in cl.load_sample()["items"]:
            assert item["comments_count_field"] == len(item["comments_endpoint_shape"])


# ── corpus shape contracts (the structure regen_corpus.py must reproduce) ────

class TestCorpusShape:

    @requires_corpus
    def test_issue_rows_have_date_only_timestamps(self):
        import re
        for rows in (cl.load_full(), cl.load_curated()):
            for row in rows:
                for key in ("created", "updated"):
                    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row[key]), (row["repo"], row["number"], key)

    @requires_corpus
    def test_labels_are_lists_of_names(self):
        for rows in (cl.load_full(), cl.load_curated()):
            for row in rows:
                assert isinstance(row["labels"], list)
                assert all(isinstance(name, str) for name in row["labels"])

    @requires_corpus
    def test_curated_has_integer_comment_counts(self):
        for row in cl.load_curated():
            assert isinstance(row["comments"], int) and row["comments"] >= 0

    @requires_corpus
    def test_row_order_repo_blocks_then_number_desc(self):
        full = cl.load_full()
        assert _repo_blocks(full) == list(cl.FULL_REPO_ORDER)
        for repo in cl.FULL_REPO_ORDER:
            numbers = _repo_numbers(full, repo)
            assert numbers == sorted(numbers, reverse=True), repo

    @requires_corpus
    def test_sample_item_and_comment_key_sets(self):
        item_keys = {"repo", "number", "body_len", "body_head", "comments_count_field", "comments_endpoint_shape"}
        comment_keys = {"id", "created_at", "updated_at", "body_len"}
        for item in cl.load_sample()["items"]:
            assert set(item) == item_keys
            assert len(item["body_head"]) <= cl.BODY_HEAD_LEN
            for comment in item["comments_endpoint_shape"]:
                assert set(comment) == comment_keys

    @requires_corpus
    def test_real_corpus_has_no_edited_comment_justifying_synthesis(self):
        # Evidence that the state-10 (comment-edit) fixture MUST come from
        # synthesis: no real edited comment exists in the canonical sample.
        doc = cl.load_sample()
        edited = [c for item in doc["items"] for c in item["comments_endpoint_shape"] if cl.comment_is_edited(c)]
        assert edited == []


# ── repo filter ──────────────────────────────────────────────────────────────

class TestRepoFilter:

    @requires_corpus
    def test_by_repo_returns_only_that_repo_in_corpus_order(self):
        full = cl.load_full()
        subset = cl.by_repo(full, "Aria")
        assert subset and all(row["repo"] == "Aria" for row in subset)
        numbers = [row["number"] for row in subset]
        assert numbers == sorted(numbers, reverse=True)

    @requires_corpus
    def test_by_repo_unknown_name_is_empty(self):
        assert cl.by_repo(cl.load_full(), "no-such-repo") == []

    @requires_corpus
    def test_sample_lookup_and_missing(self):
        doc = cl.load_sample()
        comments = cl.sample_comments(doc, "aria-plugin", 110)
        assert len(comments) == 3
        with pytest.raises(KeyError):
            cl.sample_item(doc, "aria-plugin", 999999)


# ── comment-edit synthesis (state-10 discriminating raw material) ───────────

class TestEditSynthesis:

    def test_plain_set_has_no_edits(self):
        rows = cl.synth_comment_set(n=3)
        assert len(rows) == 3
        assert all(row["updated_at"] == row["created_at"] for row in rows)
        assert not any(cl.comment_is_edited(row) for row in rows)

    def test_edit_on_oldest_discriminates_max_updated_from_proxies(self):
        rows = cl.synth_comment_set(n=3, edit_index=0)
        # count unchanged
        assert len(rows) == 3
        # exactly one edited row, and it is the OLDEST by creation
        edited = [i for i, r in enumerate(rows) if cl.comment_is_edited(r)]
        assert edited == [0]
        # max(updated_at) now diverges from max(created_at) — count-based and
        # max(created_at)-based proxies both miss the edit
        max_created = max(r["created_at"] for r in rows)
        max_updated = max(r["updated_at"] for r in rows)
        assert max_updated > max_created
        # the row carrying max(updated_at) is NOT the newest comment by creation
        newest = max(rows, key=lambda r: r["created_at"])
        assert not cl.comment_is_edited(newest)
        assert max(r["updated_at"] for r in rows if r is not newest) == max_updated

    def test_synthetic_edit_beats_every_existing_timestamp(self):
        rows = cl.synth_comment_set(n=4, start="2026-01-01T00:00:00Z", step_s=86400, edit_index=2)
        edited_row = rows[2]
        assert edited_row["updated_at"] > max(r["created_at"] for r in rows)
        # strictly after every original updated_at too, so it is the unique max

    def test_with_synthetic_edit_does_not_mutate_input(self):
        original = cl.synth_comment_set(n=3)
        snapshot = [dict(r) for r in original]
        cl.with_synthetic_edit(original, index=1)
        assert original == snapshot

    def test_with_synthetic_edit_preserves_key_set_of_real_shapes(self):
        rows = [
            {"id": 1, "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-01T00:00:00Z", "body_len": 10},
            {"id": 2, "created_at": "2026-10-02T00:00:00Z", "updated_at": "2026-10-02T00:00:00Z", "body_len": 20},
        ]
        out = cl.with_synthetic_edit(rows, index=0)
        assert out[0]["id"] == 1 and out[0]["body_len"] == 10
        assert set(out[0]) == {"id", "created_at", "updated_at", "body_len"}
        assert cl.comment_is_edited(out[0]) and not cl.comment_is_edited(out[1])

    @requires_corpus
    def test_real_corpus_shape_roundtrip(self):
        comments = cl.sample_comments(cl.load_sample(), "aria-plugin", 110)
        out = cl.with_synthetic_edit(comments, index=0)
        assert len(out) == len(comments) == 3
        assert cl.comment_is_edited(out[0])
        assert not any(cl.comment_is_edited(r) for r in out[1:])
        # input untouched
        assert all(not cl.comment_is_edited(r) for r in comments)

    def test_empty_list_raises(self):
        with pytest.raises(ValueError):
            cl.with_synthetic_edit([], index=0)

    def test_out_of_range_index_raises(self):
        rows = cl.synth_comment_set(n=2)
        with pytest.raises(IndexError):
            cl.with_synthetic_edit(rows, index=2)

    def test_invalid_n_raises(self):
        with pytest.raises(ValueError):
            cl.synth_comment_set(n=0)
