#!/usr/bin/env python3
"""Regenerate the issue-groomer corpus trio from the live Forgejo API (TASK-009).

The three corpus snapshots (spec issue-groomer-p1-mvp, "语料" section) live in
the main repo's scratchpad and are deliberately NOT copied into the plugin
repo. This script is the documented recovery path ("清理即失, 靠再生成恢复"):
it re-fetches all three files from the live API and writes them back in the
SAME structure (field shapes, row order, JSON formatting) as the 2026-10-18
canonical snapshots, so tests/fixtures/corpus_loader.py keeps working.

Fetch contract (mirrors the blessed pagination walk in
state-scanner/scripts/collectors/issue_scan.py — NOT the single-page
limit=50 bug this spec exists partly to fix, aria-plugin #208):
  - issue-list AND comments endpoints are walked with FULL pagination;
  - a page is terminal only when EMPTY (a short page may be server clamping);
  - an empty page is a JSON "[]" — rc=0 with empty stdout (no content) is a
    structural violation and a hard error, never treated as an empty page;
  - page 1 omits "&page=" (byte-identical to the pre-pagination URL);
  - rows are deduplicated by number/id across pages (window shift);
  - an entire page of already-seen rows or exceeding the page ceiling is a
    hard error — a silently partial corpus must never be written;
  - issue lists carry type=issues AND a client-side PR filter
    (pull_request is a non-null dict, or URL contains "/pulls/").

Row-order contract: repo blocks in FULL_REPO_ORDER, `number` descending
within a repo (keep in sync with corpus_loader.FULL_REPO_ORDER).

Usage:
  regen_corpus.py                          # full trio -> scratchpad, dated today
  regen_corpus.py --out-dir /tmp/smoke --date 2026-10-19
  regen_corpus.py --repos Aria SilkNode    # subset smoke run
  regen_corpus.py --date 2026-10-18        # restore canonical filenames

Writes (into --out-dir, default /home/dev/Aria/scratchpad):
  issues-open-full-18repos-<date>.json     (18 repos, all open issues)
  issues-open-<date>.json                  (Aria 4 satellite repos + comments count)
  issues-sample-body-comments-<date>.json  (5 fixed targets, body head + comments shape)

Forgejo access goes through the house CLI wrapper (credential redaction +
endpoint fallback live there); stdout/stderr of subprocess calls are captured
and never printed raw (secret-hygiene Rule #7 discipline).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ORG = "10CG"
DEFAULT_FORGEJO_BIN = "/home/dev/.npm-global/bin/forgejo"
DEFAULT_OUT_DIR = Path("/home/dev/Aria/scratchpad")

PAGE_SIZE = 50          # Forgejo max page size (clamped server-side anyway)
PAGE_CEILING = 200      # safety cap per endpoint: 200*50 = 10k rows
CALL_TIMEOUT_S = 120
BODY_HEAD_LEN = 200     # sample item body_head truncation length

# Keep in sync with tests/fixtures/corpus_loader.py FULL_REPO_ORDER (SOT for
# row order; duplicated here because regen must run when the corpus is gone).
FULL_REPO_ORDER = (
    "Aria", "aria-plugin", "aria-standards", "aria-orchestrator", "Aether",
    "aether-plugin", "Kairos", "SilkNode", "ShenQuant", "shenquant-data",
    "Kino", "nexus", "truffle-hound", "truffle-hound-v2", "TurfSync",
    "todo-app", "todo-web", "10cg.local",
)
CURATED_REPO_ORDER = FULL_REPO_ORDER[:4]

# The 5 fixed sample targets of issues-sample-body-comments (repo, number).
SAMPLE_TARGETS = (
    ("Aria", 233),
    ("Aria", 213),
    ("aria-plugin", 110),
    ("Aether", 521),
    ("SilkNode", 1251),
)

# Byte-faithful to the canonical snapshot's purpose string. The circled-digit
# glyph is built via chr() so this source file carries no forbidden glyph
# literals (see memory: forbidden-glyph escapes must be assembled, not typed).
SAMPLE_PURPOSE = (
    "指纹" + chr(0x2460) + " body/comments 分量的 fixture 真形态语料 "
    "(issue detail + comments 端点)"
)


class RegenError(RuntimeError):
    """A live fetch or structural check failed; nothing is written partially."""


# ── forgejo CLI wrapper access ───────────────────────────────────────────────

class Forgejo:
    def __init__(self, bin_path: str) -> None:
        self._bin = bin_path

    def call(self, method: str, endpoint: str, payload: dict[str, Any] | None = None) -> Any:
        cmd = [self._bin, method, endpoint]
        if payload is not None:
            cmd += ["-d", json.dumps(payload, ensure_ascii=False)]
        try:
            proc = subprocess.run(  # noqa: S603 fixed house wrapper path
                cmd, capture_output=True, text=True, timeout=CALL_TIMEOUT_S
            )
        except subprocess.TimeoutExpired as exc:
            raise RegenError(f"{method} {endpoint}: wrapper timed out after {CALL_TIMEOUT_S}s") from exc
        if proc.returncode != 0:
            # stderr tail only (already redacted by the wrapper); never raw stdout.
            tail = " | ".join((proc.stderr or "").strip().splitlines()[-3:])
            raise RegenError(f"{method} {endpoint}: wrapper rc={proc.returncode}: {tail}")
        body = (proc.stdout or "").strip()
        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RegenError(f"{method} {endpoint}: response is not JSON: {exc}") from exc


# ── full-pagination walk ─────────────────────────────────────────────────────

def _paged_get(
    forgejo: Forgejo,
    build_endpoint: Callable[[int], str],
    key: str,
    expected_count: int | None = None,
) -> list[dict[str, Any]]:
    """Walk a paginated list endpoint to exhaustion.

    `build_endpoint(page)` must OMIT "&page=" for page 1. `key` is the
    per-row identity used for cross-page dedup ("number" for issues, "id"
    for comments).

    Terminal condition for issue lists (expected_count=None): an EMPTY page
    (never a short one — the server may clamp page size).

    For the comments endpoint pass `expected_count` (the issue object's
    `comments` field). Empirically (references/forgejo-behavior-notes.md,
    2026-10-19, Forgejo 11.0.16+gitea-1.22.0) that endpoint IGNORES limit/page
    and serves the full list on every page, so an out-of-range page returns
    the SAME rows instead of an empty array — the empty-page terminal never
    fires there. With `expected_count` the walk additionally stops as soon as
    the count is satisfied, and treats a whole-duplicate page as terminal
    success only when the count IS satisfied; if rows are missing (a real
    mid-list cap on a paging-ignoring server), that is a hard error — a
    silently partial corpus must never be written.
    """
    rows: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for page in range(1, PAGE_CEILING + 2):  # +1: one probe page past the ceiling
        batch = forgejo.call("GET", build_endpoint(page))
        if batch is None:
            # rc=0 + empty stdout is NOT an empty page (that would be "[]"):
            # treating no-content as a terminal empty page would silently fold
            # "the endpoint went mute" into "the repo has no rows" (A-2).
            raise RegenError(
                f"paged endpoint page={page}: rc=0 with empty body — an empty "
                "page must be a JSON '[]', not no-content"
            )
        if not isinstance(batch, list):
            raise RegenError(f"paged endpoint page={page}: expected a list, got {type(batch).__name__}")
        if not batch:
            return rows
        if page > PAGE_CEILING:
            if expected_count is not None and len(rows) >= expected_count:
                return rows
            raise RegenError(f"paged endpoint exceeded {PAGE_CEILING} pages — refusing to write a partial corpus")
        fresh = [r for r in batch if isinstance(r, dict) and r.get(key) not in seen]
        if not fresh:
            # Entire page already seen: the server ignores paging. Terminal
            # success only when the expected count is satisfied.
            if expected_count is not None and len(rows) >= expected_count:
                return rows
            raise RegenError(
                f"paged endpoint page={page}: entire page of already-seen rows with "
                f"{len(rows)}/{expected_count} rows collected — paging ignored mid-list, "
                f"refusing to write a partial corpus"
            )
        seen.update(r.get(key) for r in fresh)
        rows.extend(fresh)
        if expected_count is not None and len(rows) >= expected_count:
            return rows
    raise RegenError("unreachable: probe page always returns")  # pragma: no cover


def _issue_endpoint(repo: str) -> Callable[[int], str]:
    base = f"/repos/{ORG}/{repo}/issues?state=open&type=issues&limit={PAGE_SIZE}"
    return lambda page: base if page == 1 else f"{base}&page={page}"


def _comments_endpoint(repo: str, number: int) -> Callable[[int], str]:
    base = f"/repos/{ORG}/{repo}/issues/{number}/comments?limit={PAGE_SIZE}"
    return lambda page: base if page == 1 else f"{base}&page={page}"


def _is_pull_request(raw: dict[str, Any]) -> bool:
    """Forgejo /issues may conflate PRs even with type=issues (QA-C2 lesson)."""
    if isinstance(raw.get("pull_request"), dict):
        return True
    url = str(raw.get("html_url") or raw.get("url") or "")
    return "/pulls/" in url


# ── snapshot builders (output = canonical corpus structure) ─────────────────

def _comments_count(raw: dict[str, Any], repo: str, number: int) -> int:
    """Issue detail 的 ``comments`` 计数字段 — 必须在场且为非负 int (E-5)。

    缺席 / 非 int / bool / 负值 ⇒ RegenError, 绝不冒充 0: 该计数是
    comments 端点全量走的对账基线 (expected_count), 一个被伪造的 0 会把
    「端点哑了 / 字段形态漂了」静默折成「零评论语料」。"""
    value = raw.get("comments")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RegenError(
            f"sample {repo}#{number}: issue detail 'comments' count field absent "
            f"or not a non-negative int (got {value!r}) — refusing to fake 0"
        )
    return value


def _issue_row(repo: str, raw: dict[str, Any], with_comments_count: bool) -> dict[str, Any]:
    row: dict[str, Any] = {
        "repo": repo,
        "number": raw.get("number"),
        "title": raw.get("title") or "",
        "labels": [l.get("name") for l in (raw.get("labels") or []) if isinstance(l, dict)],
        "created": str(raw.get("created_at") or "")[:10],   # date-only, per snapshot convention
        "updated": str(raw.get("updated_at") or "")[:10],
    }
    if with_comments_count:
        row["comments"] = int(raw.get("comments") or 0)
    return row


def build_full(forgejo: Forgejo, repos: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for repo in repos:
        raws = [r for r in _paged_get(forgejo, _issue_endpoint(repo), "number") if not _is_pull_request(r)]
        rows = sorted((_issue_row(repo, r, with_comments_count=False) for r in raws),
                      key=lambda r: r["number"], reverse=True)
        print(f"  full: {repo}: {len(rows)} open issues", file=sys.stderr)
        out.extend(rows)
    return out


def build_curated(forgejo: Forgejo, repos: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for repo in repos:
        raws = [r for r in _paged_get(forgejo, _issue_endpoint(repo), "number") if not _is_pull_request(r)]
        rows = sorted((_issue_row(repo, r, with_comments_count=True) for r in raws),
                      key=lambda r: r["number"], reverse=True)
        print(f"  curated: {repo}: {len(rows)} open issues", file=sys.stderr)
        out.extend(rows)
    return out


def build_sample(forgejo: Forgejo, targets: list[tuple[str, int]], date: str) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for repo, number in targets:
        raw = forgejo.call("GET", f"/repos/{ORG}/{repo}/issues/{number}")
        if not isinstance(raw, dict) or "number" not in raw:
            raise RegenError(f"sample {repo}#{number}: issue detail fetch failed or malformed")
        count_field = _comments_count(raw, repo, number)  # E-5: 对账基线不得冒充 0
        comments = _paged_get(
            forgejo, _comments_endpoint(repo, number), "id",
            expected_count=count_field,  # this endpoint ignores paging — see notes
        )
        body = str(raw.get("body") or "")
        items.append({
            "repo": repo,
            "number": number,
            "body_len": len(body),
            "body_head": body[:BODY_HEAD_LEN],
            "comments_count_field": count_field,
            "comments_endpoint_shape": [
                {
                    "id": c.get("id"),
                    "created_at": c.get("created_at"),
                    "updated_at": c.get("updated_at"),
                    "body_len": len(str(c.get("body") or "")),
                }
                for c in comments
            ],
        })
        print(f"  sample: {repo}#{number}: {len(comments)} comments", file=sys.stderr)
    return {"sampled_at": date, "purpose": SAMPLE_PURPOSE, "items": items}


# ── output ───────────────────────────────────────────────────────────────────

def _date_str(value: str | None) -> str:
    if value:
        return value
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _write_trio(
    outputs: list[tuple[Path, Any]],
    *,
    rename_fn: Callable[[Path, Path], None] | None = None,
) -> None:
    """三文件事务化落盘 (D-3): 全部先写 ``.tmp`` (每个写完才算 staged),
    再统一 rename — 混代免疫。

    崩溃窗口语义: staging 期任一步失败 ⇒ 清掉全部 tmp, 三个目标路径保持
    旧内容 (整代旧 — 消除「逐文件写完即换」形态下第 1 个已换新、第 2 个
    写一半的写入期混代); rename 期每文件原子换已 staged 字节 (单文件结构
    上无半写字节), rename 中途失败 ⇒ 清残留 tmp 后上抛 (已换的停留新代 —
    rename 序列本身非跨文件原子, 混代窗口收窄到 rename 之间)。

    Canonical formatting: indent=1, ensure_ascii=False, no trailing newline
    (byte-parity with the 2026-10-18 trio)。``rename_fn`` 注入面仅供测试
    模拟崩溃, 生产缺省 Path.replace。"""
    rename = rename_fn if rename_fn is not None else (lambda src, dst: src.replace(dst))
    staged: list[tuple[Path, Path]] = []
    try:
        for path, payload in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            try:
                with tmp.open("w", encoding="utf-8") as fh:
                    json.dump(payload, fh, ensure_ascii=False, indent=1)
            except BaseException:
                _unlink_quiet(tmp)  # 写一半的当前 tmp 立即清 (不入 staged)
                raise
            staged.append((tmp, path))
    except BaseException:
        for tmp, _ in staged:
            _unlink_quiet(tmp)
        raise
    try:
        for tmp, path in staged:
            rename(tmp, path)
    except BaseException:
        for tmp, _ in staged:
            _unlink_quiet(tmp)  # 未换的 tmp 清掉; 已 rename 的 tmp 已不存在
        raise


# ── main ─────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                        help=f"output directory (default: {DEFAULT_OUT_DIR})")
    parser.add_argument("--date", default=None,
                        help="date stamped into filenames (default: today UTC); "
                             "pass 2026-10-18 to restore the canonical trio in place")
    parser.add_argument("--repos", nargs="*", default=None,
                        help="subset of repo names (smoke runs); default: all 18 in canonical order")
    parser.add_argument("--forgejo", default=DEFAULT_FORGEJO_BIN,
                        help=f"path to the forgejo CLI wrapper (default: {DEFAULT_FORGEJO_BIN})")
    args = parser.parse_args(argv)

    repos = [r for r in (args.repos or list(FULL_REPO_ORDER)) if r in FULL_REPO_ORDER]
    dropped = [r for r in (args.repos or []) if r not in FULL_REPO_ORDER]
    if dropped:
        print(f"unknown repo names ignored (not in canonical order): {dropped}", file=sys.stderr)
    if not repos:
        print("no valid repos selected", file=sys.stderr)
        return 1

    date = _date_str(args.date)
    forgejo = Forgejo(args.forgejo)

    try:
        print(f"regen_corpus: fetching {len(repos)} repo(s) from live API ...", file=sys.stderr)
        full = build_full(forgejo, repos)
        curated = build_curated(forgejo, [r for r in CURATED_REPO_ORDER if r in repos])
        sample = build_sample(forgejo, [t for t in SAMPLE_TARGETS if t[0] in repos], date)
    except RegenError as exc:
        print(f"regen_corpus: FAILED, nothing written: {exc}", file=sys.stderr)
        return 1

    out_full = args.out_dir / f"issues-open-full-18repos-{date}.json"
    out_curated = args.out_dir / f"issues-open-{date}.json"
    out_sample = args.out_dir / f"issues-sample-body-comments-{date}.json"
    _write_trio([(out_full, full), (out_curated, curated), (out_sample, sample)])

    print(
        f"regen_corpus: wrote 3 files to {args.out_dir} (date={date}):\n"
        f"  {out_full.name}: {len(full)} issues across {len(repos)} repo(s)\n"
        f"  {out_curated.name}: {len(curated)} issues "
        f"across {[r for r in CURATED_REPO_ORDER if r in repos]}\n"
        f"  {out_sample.name}: {len(sample['items'])} items, "
        f"{sum(len(i['comments_endpoint_shape']) for i in sample['items'])} comments"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
