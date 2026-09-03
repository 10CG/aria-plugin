#!/usr/bin/env python3
"""sibling_spec_probe — per-round competitor-Spec probe (audit-engine, advisory).

OpenSpec SOT: openspec/changes/sibling-spec-probe/proposal.md (all semantics —
this docstring is a pointer, not a duplicate). Interface pinned in the shared
implementer/tester contract (2026-09-03 BRIEF-interface.md).

It never writes or reads coordination claims, never touches the shared
remote-tracking namespace, and never produces a ``--linked-issue`` argument
for the primary claim mechanism — layer-2 URL fallback (below) is a
read-only comparison surface only (proposal §3 layer 2).

CLI usage
---------
    python3 skills/audit-engine/scripts/sibling_spec_probe.py \\
        --own-spec-dir <own-spec-dir-name> --repo-path <repo-root>

``--own-spec-dir`` is this track's own OpenSpec directory name (under
``<repo-path>/openspec/changes/``) — it doubles as the self-hit exclusion
key. ``--repo-path`` is the repo root; no git call assumes ``cwd``.

Twelve stdout fields (§7 — exactly one JSON object on stdout, nothing else)
---------------------------------------------------------------------------
    schema_version, probe, status, reason, verdict, own_spec_dir, own_layer,
    own_keys, remotes, hits, caps_applied, elapsed_ms

Exit code tri-partition (§7)
-----------------------------
    0      — a defined verdict was produced (hit / no-hit / degraded /
             skipped are ALL 0; a hit is not an error).
    non-0  — the probe itself failed (bad arguments, unreadable repo,
             sister module not importable, or an internal exception).
             stdout is NOT guaranteed to be valid JSON in this case.
             Consumers MUST treat any non-zero exit, or stdout that fails to
             parse as JSON, or an unrecognized schema_version, as
             ``not_established`` — never as "no sibling".

SC-19 constant blacklist — same-source obligation
--------------------------------------------------
``_RAW_KEY_BLACKLIST`` below (and the sentinel test reached via the
imported ``is_sentinel``) are the SAME-SOURCE contract as sister Spec
``linked-issue-field-availability``: its §2 sentinel set (``none`` /
``无``) and its §3 SOT-template placeholder default
(``{<org>/<repo>#<n>}``). Any edit to either side's constants MUST land in
the same batch as the other — see proposal §3, the ``BAD_TOKEN`` row.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# §3 — the ONE cross-skill import block in this file (proposal §3 "跨 skill
# import 的可运行模式", pinned verbatim; order is load-bearing — the LAST
# path inserted ends up FIRST on the module search path). Nowhere else in
# this module does a `from lib.` / `from collectors.` statement, or a call
# to insert onto that search path, appear — this loop is the only one.
# ---------------------------------------------------------------------------
_SS_ROOT = str(Path(__file__).resolve().parents[2] / "state-scanner")
_SS_SCRIPTS = str(Path(__file__).resolve().parents[2] / "state-scanner" / "scripts")
for _p in (_SS_SCRIPTS, _SS_ROOT):  # _SS_ROOT inserted last -> sits first
    if _p not in sys.path:
        sys.path.insert(0, _p)
try:
    from lib.collision import normalize_linked_issue
    from lib.linked_issue_field import extract_linked_issue_field, is_sentinel
    from collectors.multi_remote import resolve_enforced_remotes

    _IMPORT_ERROR: Optional[BaseException] = None
except ImportError as _exc:  # sister Spec's module absent — proposal §3 "未
    # ship 时: 不定义" — surfaced by main() as a non-0 exit, no transitional
    # replica of E0-E6 is written here (proposal §3 "⛔ 不得内含第二份抽取实现").
    normalize_linked_issue = None  # type: ignore[assignment]
    extract_linked_issue_field = None  # type: ignore[assignment]
    is_sentinel = None  # type: ignore[assignment]
    resolve_enforced_remotes = None  # type: ignore[assignment]
    _IMPORT_ERROR = _exc

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------
SCHEMA_VERSION = "1"
PROBE_NAME = "sibling_spec_probe"
GIT_TIMEOUT_S = 30                 # every git subprocess, independent budget
MAX_PROPOSALS_SCANNED = 1000       # per remote: UNIQUE blobs across all its refs (Amendment A1, 2026-09-03)
MAX_REFS_SCANNED = 100             # per remote, non-default refs only
PRIVATE_NS = "refs/aria/sibling-probe"
TIMEOUT_RC = -124                  # sentinel rc a runner may use for a timeout
_RAW_KEY_BLACKLIST = frozenset({"{<org>/<repo>#<n>}"})  # + is_sentinel(t) also excluded
LAYERS = (
    "canonical",
    "none_sentinel",
    "url_fallback",
    "no_token_no_url",
    "no_field",
    "bad_token_union",
)

_URL_TOKEN_RE = re.compile(r"/([^/\s]+)/([^/\s]+)/issues/(\d+)")
_PROPOSAL_PATH_RE = re.compile(r"^openspec/(changes|archive)/[^/]+/proposal\.md$")


# ---------------------------------------------------------------------------
# git runner (injectable)
# ---------------------------------------------------------------------------
def default_runner(args: list, cwd: Path, timeout: int) -> tuple:
    """Default git runner: ``git -C <cwd> <args>``, text-mode, UTF-8 replace.

    A `subprocess.TimeoutExpired` is caught here and mapped to
    ``(TIMEOUT_RC, "", "timeout")`` — callers never see the exception from
    this implementation. `_call_runner` below applies the same mapping for
    an *injected* runner that raises the exception itself.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return TIMEOUT_RC, "", "timeout"


def _call_runner(runner, args: list, cwd: Path, timeout: int) -> tuple:
    """Call `runner(args, cwd, timeout)`, normalizing a raised
    `subprocess.TimeoutExpired` (as an injected test double may do) to the
    same `(TIMEOUT_RC, "", "timeout")` shape `default_runner` returns."""
    try:
        return runner(args, cwd, timeout)
    except subprocess.TimeoutExpired:
        return TIMEOUT_RC, "", "timeout"


def log(msg: str) -> None:
    """Human-readable stderr log line. Never receives raw git stderr
    (Rule #7 — remote URLs can embed credentials); only stable, non-secret
    values (remote names, branch names, `error_kind`, paths, counts)."""
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# §3 — pure classification (no I/O)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Classification:
    layer: str          # one of LAYERS
    keys: frozenset      # elements are ("k", basename, n) or ("r", raw)
    field_line: Optional[int]  # FieldVerdict.line_no; None for NO_FIELD


@dataclass(frozen=True)
class CorpusEntry:
    remote: str
    ref_label: str        # "R/<branch>", e.g. "origin/master"
    branch: str
    corpus: str            # "changes" | "archive"
    spec_dir: str           # third path segment
    path: str
    classification: Classification


def make_key(token: str) -> Optional[tuple]:
    """§3 key construction. Blacklist/sentinel tokens never produce ANY key
    (not even a raw-string key) — SC-19. Otherwise `normalize_linked_issue`
    resolves a canonical key when possible; unparseable tokens fall back to
    a raw-string key (fail-toward-reporting — only ever equal a
    byte-identical raw string, never a canonical key: first element differs).
    """
    if token in _RAW_KEY_BLACKLIST:
        return None
    if is_sentinel is not None and is_sentinel(token):
        return None
    k = normalize_linked_issue(token)
    if k is not None:
        return ("k", k[0], k[1])
    return ("r", token)


def url_tokens(line: str) -> list:
    """§3 layer-2 extraction: every ``/<org>/<repo>/issues/<n>`` fragment on
    the given line, order-preserving de-duplicated, as ``<org>/<repo>#<n>``
    strings."""
    seen = set()
    out = []
    for org, repo, num in _URL_TOKEN_RE.findall(line):
        token = f"{org}/{repo}#{num}"
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _field_line_text(text: str, line_no: Optional[int]) -> Optional[str]:
    """The 1-based `line_no` line of `text`, indexed via `text.splitlines()`
    (matches `FieldVerdict.line_no`'s documented indexing)."""
    if line_no is None:
        return None
    lines = text.splitlines()
    idx = line_no - 1
    if 0 <= idx < len(lines):
        return lines[idx]
    return None


def classify_proposal(text: str) -> Classification:
    """§3 four-state dispatch (sister `extract_linked_issue_field` is the
    SOT for E0-E6; this function only maps its verdict to a layer + key
    set — proposal §3's "层 1 分派" table, cell by cell, in fixed order)."""
    fv = extract_linked_issue_field(text)

    if fv.verdict == "NO_FIELD":
        return Classification("no_field", frozenset(), None)

    if fv.verdict == "NO_TOKEN":
        line = _field_line_text(text, fv.line_no)
        toks = url_tokens(line) if line is not None else []
        keys = frozenset(k for k in (make_key(t) for t in toks) if k is not None)
        layer = "url_fallback" if keys else "no_token_no_url"
        return Classification(layer, keys, fv.line_no)

    if fv.verdict == "BAD_TOKEN":
        line = _field_line_text(text, fv.line_no)
        url_toks = url_tokens(line) if line is not None else []
        elem_keys = [make_key(t) for t in fv.token_elements]
        url_keys = [make_key(t) for t in url_toks]
        keys = frozenset(k for k in elem_keys + url_keys if k is not None)
        return Classification("bad_token_union", keys, fv.line_no)

    # fv.verdict == "OK"
    if is_sentinel(fv.token_str):  # judged against the raw (unstripped) E3 string
        return Classification("none_sentinel", frozenset(), fv.line_no)
    keys = frozenset(k for k in (make_key(t) for t in fv.token_elements) if k is not None)
    return Classification("canonical", keys, fv.line_no)


def key_to_json(key: tuple) -> list:
    return list(key)


def _key_sort_key(key: tuple) -> tuple:
    """Deterministic ordering for a set of keys, independent of Python's
    (hash-randomized) frozenset iteration order."""
    return (key[0],) + tuple(str(x) for x in key[1:])


def sort_proposal_paths(paths: Iterable[str]) -> list:
    """§6 decisive ordering: filter to single-level
    ``openspec/{changes,archive}/<spec_dir>/proposal.md`` paths; `changes/`
    entries first (byte-sorted), then `archive/` entries (byte-sorted) —
    independent of locale."""
    changes = []
    archive = []
    for p in paths:
        m = _PROPOSAL_PATH_RE.match(p)
        if not m:
            continue
        (changes if m.group(1) == "changes" else archive).append(p)
    changes.sort(key=lambda p: p.encode("utf-8"))
    archive.sort(key=lambda p: p.encode("utf-8"))
    return changes + archive


def is_stale_copy(spec_dir: str, default_ref_paths: Iterable[str]) -> bool:
    """True iff the default ref already carries an archived copy of
    `spec_dir` at ``openspec/archive/YYYY-MM-DD-<spec_dir>/proposal.md``
    (exact 10-char date + single hyphen + byte-exact `spec_dir`, never a
    prefix/suffix match — a `*-<spec_dir>` glob would misfire on an
    unrelated archive entry that merely ends with the same suffix)."""
    pattern = re.compile(
        r"^openspec/archive/\d{4}-\d{2}-\d{2}-" + re.escape(spec_dir) + r"/proposal\.md$"
    )
    return any(pattern.match(p) for p in default_ref_paths)


def classify_error(rc: int, stderr: str) -> str:
    """Stable non-secret error_kind enum. `timeout` first (covers both this
    module's `TIMEOUT_RC` sentinel and a runner that reports "timeout"
    literally); the remaining five values replicate (not import)
    `phase-d-closer/scripts/fetch_gate.py`'s `_classify_error` shape — raw
    stderr is intentionally never returned (Rule #7: remote URLs may embed
    credentials)."""
    if rc == TIMEOUT_RC or stderr == "timeout":
        return "timeout"
    s = (stderr or "").lower()
    if "could not resolve host" in s or "timed out" in s or "connection" in s:
        return "network"
    if "403" in s or "authentication failed" in s or "permission denied" in s:
        return "auth_403"
    if "non-fast-forward" in s or "rejected" in s:
        return "non_ff"
    if "not found" in s or "does not appear to be a git repo" in s:
        return "git_missing"
    return "other"


def parse_symref(stdout: str) -> tuple:
    """§4 step 2: the first line starting with ``ref: `` is split on a tab;
    the first segment (prefix stripped) must start with ``refs/heads/``.

    Returns ``(branch, None)`` on success, ``(None, "no_symref")`` when no
    such line exists, ``(None, "bad_symref_prefix")`` when the prefix
    doesn't hold — never guesses a fallback branch name."""
    for line in stdout.splitlines():
        if line.startswith("ref: "):
            first = line.split("\t", 1)[0]
            ref = first[len("ref: "):]
            if ref.startswith("refs/heads/"):
                return ref[len("refs/heads/"):], None
            return None, "bad_symref_prefix"
    return None, "no_symref"


def assemble_hits(own_keys: frozenset, own_spec_dir: str, entries: list) -> list:
    """§3 set-intersection + §7 hit assembly. `entries` must already be in
    enumeration order (default ref first, remaining refs byte-sorted; within
    a ref, `sort_proposal_paths` order) — the caller (`run_probe`/
    `_scan_remote`) guarantees this. A `spec_dir == own_spec_dir` entry is
    skipped regardless of remote/corpus/ref (self-hit exclusion, SC-5).
    Duplicate (remote, corpus, spec_dir, key) rows across refs are merged
    into one hit with a de-duplicated, byte-sorted `refs` list; every other
    field is taken from the FIRST (enumeration-order) matching entry.
    """
    seen: dict = {}
    order: list = []
    for entry in entries:
        if entry.spec_dir == own_spec_dir:
            continue
        common = own_keys & entry.classification.keys
        if not common:
            continue
        for key in sorted(common, key=_key_sort_key):
            dedup_key = (entry.remote, entry.corpus, entry.spec_dir, key)
            if dedup_key not in seen:
                seen[dedup_key] = {
                    "remote": entry.remote,
                    "branch": entry.branch,
                    "corpus": entry.corpus,
                    "spec_dir": entry.spec_dir,
                    "path": entry.path,
                    "field_line": entry.classification.field_line,
                    "key": key_to_json(key),
                    "layer": entry.classification.layer,
                    "_refs": [entry.ref_label],
                }
                order.append(dedup_key)
            elif entry.ref_label not in seen[dedup_key]["_refs"]:
                seen[dedup_key]["_refs"].append(entry.ref_label)

    hits = []
    for dedup_key in order:
        item = seen[dedup_key]
        item["refs"] = sorted(item.pop("_refs"), key=lambda s: s.encode("utf-8"))
        hits.append(item)
    return hits


# ---------------------------------------------------------------------------
# I/O layer
# ---------------------------------------------------------------------------
def load_remote_policy(repo: Path) -> tuple:
    """Read ``<repo>/.aria/config.json`` -> `state_scanner.multi_remote.
    {enforced_remotes, read_only_remotes}`; a `None`/absent skill-level
    value inherits the top-level `multi_remote.*` block (a2_discretions (d)
    — mirrors `multi_remote.py::_resolve_remote_policy`'s inheritance rule,
    NOT its private function). Missing file / malformed JSON -> `(None, ())`.
    """
    cfg_path = repo / ".aria" / "config.json"
    if not cfg_path.exists():
        return None, ()
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None, ()
    ss = raw.get("state_scanner") or {}
    skill_block = ss.get("multi_remote") or {}
    top_level = raw.get("multi_remote") or {}
    enforced = skill_block.get("enforced_remotes")
    if enforced is None:
        enforced = top_level.get("enforced_remotes")
    read_only = skill_block.get("read_only_remotes")
    if read_only is None:
        read_only = top_level.get("read_only_remotes")
    return enforced, tuple(read_only or ())


def resolve_default_branch(remote: str, repo: Path, runner) -> tuple:
    """§4 steps 2-3: default branch ONLY via a live ``ls-remote --symref``
    answer — fail-closed, never guesses a literal branch name."""
    rc, out, err = _call_runner(runner, ["ls-remote", "--symref", remote, "HEAD"], repo, GIT_TIMEOUT_S)
    if rc != 0:
        return None, None, classify_error(rc, err)
    branch, err_kind = parse_symref(out)
    if branch is None:
        return None, None, err_kind
    return branch, "ls_remote_symref", None


def fetch_remote(remote: str, repo: Path, runner) -> Optional[str]:
    """§5(f)/P8: fetch the remote's entire branch namespace into this
    probe's private ref namespace. Up to 2 attempts (1 retry, matching S2's
    transient-SSH-failure observation); never touches the shared
    remote-tracking namespace, never reads FETCH_HEAD."""
    refspec = f"+refs/heads/*:{PRIVATE_NS}/{remote}/*"
    args = ["fetch", "--no-tags", "--prune", remote, refspec]
    rc, _out, err = _call_runner(runner, args, repo, GIT_TIMEOUT_S)
    if rc == 0:
        return None
    rc2, _out2, err2 = _call_runner(runner, args, repo, GIT_TIMEOUT_S)
    if rc2 == 0:
        return None
    return classify_error(rc2, err2)


def _scan_remote(remote: str, repo_path: Path, runner, caps_applied: list) -> dict:
    """§5 "每 remote 流程 (顺序固定)" steps 1-6 for one enforced remote."""
    default_branch, resolved_by, err_kind = resolve_default_branch(remote, repo_path, runner)
    if default_branch is None:
        log(f"{remote}: default branch unresolved ({err_kind})")
        return {
            "remote_entry": {
                "name": remote, "default_branch": None, "resolved_by": None,
                "error_kind": err_kind, "scanned": 0, "capped": False,
                "refs_scanned": 0, "stale_skipped": 0,
            },
            "entries": [], "unresolved": True, "fetch_failed": False, "capped": False,
        }

    log(f"{remote}: default_branch={default_branch}")
    fetch_err = fetch_remote(remote, repo_path, runner)
    if fetch_err is not None:
        log(f"{remote}: fetch failed ({fetch_err})")
        return {
            "remote_entry": {
                "name": remote, "default_branch": default_branch, "resolved_by": resolved_by,
                "error_kind": fetch_err, "scanned": 0, "capped": False,
                "refs_scanned": 0, "stale_skipped": 0,
            },
            "entries": [], "unresolved": False, "fetch_failed": True, "capped": False,
        }
    log(f"{remote}: fetch ok")

    prefix = f"{PRIVATE_NS}/{remote}/"
    default_ref_name = prefix + default_branch
    rc, out, _err = _call_runner(
        runner, ["for-each-ref", "--format=%(refname)", prefix], repo_path, GIT_TIMEOUT_S
    )
    refnames = [line.strip() for line in out.splitlines() if line.strip()] if rc == 0 else []

    non_default = sorted((r for r in refnames if r != default_ref_name), key=lambda s: s.encode("utf-8"))
    refs_total = len(non_default)
    remote_capped = False
    if refs_total > MAX_REFS_SCANNED:
        dropped_refname = non_default[MAX_REFS_SCANNED]
        dropped_label = remote + "/" + dropped_refname[len(prefix):]
        caps_applied.append({
            "remote": remote, "kind": "refs", "total": refs_total,
            "kept": MAX_REFS_SCANNED, "dropped_from": dropped_label,
        })
        log(f"{remote}: refs cap total={refs_total} kept={MAX_REFS_SCANNED} dropped_from={dropped_label!r}")
        non_default = non_default[:MAX_REFS_SCANNED]
        remote_capped = True

    scan_refs = ([default_ref_name] if default_ref_name in refnames else []) + non_default
    refs_scanned = len(scan_refs)

    default_ref_paths: list = []
    remote_entries: list = []
    stale_skipped = 0
    # Amendment A1 (2026-09-03): the proposals cap counts UNIQUE BLOBS per remote,
    # not (ref, path) rows -- the same proposal.md on 9 branches is one blob and
    # classifies once; counting it 9 times made the cap fire on this very repo
    # (1097 rows vs 165 blobs) and turned every round into not_established.
    blob_class: dict = {}          # sha -> Classification (kept blobs)
    dropped_blobs: set = set()     # sha -> dropped at first sight (cap)
    first_dropped_path = None

    for refname in scan_refs:
        is_default = refname == default_ref_name
        branch_name = refname[len(prefix):]
        rc, out, _err = _call_runner(
            runner,
            ["ls-tree", "-r", refname, "--", "openspec/changes", "openspec/archive"],
            repo_path, GIT_TIMEOUT_S,
        )
        # default ls-tree format: "<mode> <type> <sha>\t<path>"; a bare path line
        # (no tab) is tolerated as a sha-less row (unique per ref+path).
        sha_of: dict = {}
        if rc == 0:
            for line in out.splitlines():
                if "\t" in line:
                    meta, path = line.split("\t", 1)
                    parts = meta.split()
                    sha_of[path] = parts[2] if len(parts) >= 3 else None
                elif line.strip():
                    sha_of[line.strip()] = None
        sorted_paths = sort_proposal_paths(sha_of.keys())
        if is_default:
            default_ref_paths = sorted_paths

        for path in sorted_paths:
            _root, corpus, spec_dir, _leaf = path.split("/")
            if not is_default and corpus == "changes" and is_stale_copy(spec_dir, default_ref_paths):
                stale_skipped += 1
                continue
            sha = sha_of.get(path) or f"{refname}:{path}"
            if sha in dropped_blobs:
                continue
            classification = blob_class.get(sha)
            if classification is None:
                if len(blob_class) >= MAX_PROPOSALS_SCANNED:
                    if first_dropped_path is None:
                        first_dropped_path = path
                    dropped_blobs.add(sha)
                    continue
                rc2, blob, _err2 = _call_runner(runner, ["show", f"{refname}:{path}"], repo_path, GIT_TIMEOUT_S)
                text = blob if rc2 == 0 else ""
                classification = classify_proposal(text)
                blob_class[sha] = classification
            remote_entries.append(CorpusEntry(
                remote=remote, ref_label=f"{remote}/{branch_name}", branch=branch_name,
                corpus=corpus, spec_dir=spec_dir, path=path, classification=classification,
            ))

    proposals_capped = first_dropped_path is not None
    proposals_total = len(blob_class) + len(dropped_blobs)
    if proposals_capped:
        caps_applied.append({
            "remote": remote, "kind": "proposals", "total": proposals_total,
            "kept": MAX_PROPOSALS_SCANNED, "dropped_from": first_dropped_path,
        })
        log(
            f"{remote}: proposals cap total={proposals_total} "
            f"kept={MAX_PROPOSALS_SCANNED} dropped_from={first_dropped_path!r}"
        )

    capped = remote_capped or proposals_capped
    return {
        "remote_entry": {
            "name": remote, "default_branch": default_branch, "resolved_by": resolved_by,
            "error_kind": None, "scanned": len(blob_class), "capped": capped,
            "refs_scanned": refs_scanned, "stale_skipped": stale_skipped,
        },
        "entries": remote_entries, "unresolved": False, "fetch_failed": False, "capped": capped,
    }


def _read_own_proposal(repo_path: Path, own_spec_dir: str) -> str:
    """Own proposal is read from the WORKING TREE (a2_discretions (a)) —
    this track's own in-progress content, not any ref this probe scans."""
    path = repo_path / "openspec" / "changes" / own_spec_dir / "proposal.md"
    return path.read_text(encoding="utf-8", errors="replace")


def _build_result(
    *, status, reason, verdict, own_spec_dir, own_layer, own_keys,
    remotes, hits, caps_applied, elapsed_ms,
) -> dict:
    sorted_keys = sorted(own_keys, key=_key_sort_key)
    return {
        "schema_version": SCHEMA_VERSION,
        "probe": PROBE_NAME,
        "status": status,
        "reason": reason,
        "verdict": verdict,
        "own_spec_dir": own_spec_dir,
        "own_layer": own_layer,
        "own_keys": [key_to_json(k) for k in sorted_keys],
        "remotes": remotes,
        "hits": hits,
        "caps_applied": caps_applied,
        "elapsed_ms": elapsed_ms,
    }


def run_probe(repo_path: Path, own_spec_dir: str, runner=default_runner) -> dict:
    """§4-§7: full probe run. Returns the §7 twelve-field dict."""
    t0 = time.monotonic()

    own_text = _read_own_proposal(repo_path, own_spec_dir)
    own_classification = classify_proposal(own_text)
    own_layer = own_classification.layer
    own_keys = own_classification.keys

    configured, read_only = load_remote_policy(repo_path)
    rc, out, _err = _call_runner(runner, ["remote"], repo_path, GIT_TIMEOUT_S)
    actual_remotes = [line.strip() for line in out.splitlines() if line.strip()] if rc == 0 else []
    enforced, _no_matching = resolve_enforced_remotes(configured, actual_remotes, read_only)

    if not enforced:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return _build_result(
            status="skipped", reason="no_enforced_remote", verdict="not_established",
            own_spec_dir=own_spec_dir, own_layer=own_layer, own_keys=own_keys,
            remotes=[], hits=[], caps_applied=[], elapsed_ms=elapsed_ms,
        )

    remotes_out: list = []
    caps_applied: list = []
    entries: list = []
    any_unresolved = False
    any_fetch_failed = False
    any_cap = False

    for remote in enforced:
        scan = _scan_remote(remote, repo_path, runner, caps_applied)
        remotes_out.append(scan["remote_entry"])
        entries.extend(scan["entries"])
        any_unresolved = any_unresolved or scan["unresolved"]
        any_fetch_failed = any_fetch_failed or scan["fetch_failed"]
        any_cap = any_cap or scan["capped"]

    hits = assemble_hits(own_keys, own_spec_dir, entries)

    if any_unresolved:
        reason = "remote_unresolved"
    elif any_fetch_failed:
        reason = "fetch_failed"
    elif any_cap:
        reason = "cap_applied"
    elif not own_keys:
        reason = "own_token_absent"
    else:
        reason = None

    status = "degraded" if (any_unresolved or any_fetch_failed or any_cap) else "ok"

    if hits:
        verdict = "sibling_found"
    elif status == "ok" and own_keys:
        verdict = "no_sibling_found"
    else:
        verdict = "not_established"

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return _build_result(
        status=status, reason=reason, verdict=verdict,
        own_spec_dir=own_spec_dir, own_layer=own_layer, own_keys=own_keys,
        remotes=remotes_out, hits=hits, caps_applied=caps_applied, elapsed_ms=elapsed_ms,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog=PROBE_NAME, description="per-round sibling-Spec probe")
    parser.add_argument("--own-spec-dir", required=True, help="this track's own OpenSpec directory name")
    parser.add_argument("--repo-path", required=True, help="repo root (no git call assumes cwd)")
    args = parser.parse_args(argv)

    repo_path = Path(args.repo_path)
    if not (repo_path / ".git").exists():
        log(f"not a git repository: {repo_path}")
        return 2

    own_proposal_path = repo_path / "openspec" / "changes" / args.own_spec_dir / "proposal.md"
    if not own_proposal_path.exists():
        log(f"own proposal not found: {own_proposal_path}")
        return 2

    if _IMPORT_ERROR is not None:
        log(f"extract_linked_issue_field 不可导入: {_IMPORT_ERROR}")
        return 3

    try:
        result = run_probe(repo_path, args.own_spec_dir)
    except Exception:  # probe's own failure — §7 non-0, stdout not guaranteed JSON
        traceback.print_exc(file=sys.stderr)
        return 1

    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
