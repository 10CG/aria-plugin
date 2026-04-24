"""Phase 1.13 — Issue-awareness collector (opt-in).

Implements the `issue_status` snapshot section specified in
`aria/skills/state-scanner/SKILL.md` §阶段 1.13 and the companion reference
`references/issue-scanning.md` (schema v1.1, submodule-aware).

Design invariants (do not break without a snapshot_schema_version bump):
- `enabled: false` (default) → returns `{"enabled": false}` with **no**
  `issue_status` field. Caller (scan.py) is responsible for deciding whether
  to emit the section at all. Soft-error list stays empty.
- All fetch failures are fail-soft: recorded via `fetch_error` enum and
  `soft_error` on the `CollectorResult`; the scan never aborts.
- Writer ALWAYS stamps `schema_version="1.1"` (no branching on
  `scan_submodules`) — reader is the one tolerating `{"1.0","1.1"}`.
- `items[]` and `open_issues[]` are the *same list object* (reference-equal
  in the Python dict) so v1.0 consumers still work. This is stronger than
  "sync-write" because a later mutation to one updates both.
- stdlib-only: subprocess / json / os / pathlib / re / time / shutil / urllib.

The 10 `fetch_error` enums match SKILL.md §阶段 1.13 exactly:
  network_unavailable, cli_missing, auth_missing, auth_failed, rate_limited,
  not_found_or_no_access, timeout, platform_unknown, parse_error, unknown.

Submodule scan (opt-in via `scan_submodules: true`) walks `.gitmodules`,
derives `owner/repo` from each submodule's `origin` remote, and scans each
independently with its own timeout and fail-soft bucket. Results are
aggregated into `repos{}` (per-repo detail) plus the flat `items[]` view.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ._common import CollectorResult, _run, log

# ----- Constants ------------------------------------------------------------

SCHEMA_VERSION = "1.1"
SCHEMA_COMPAT = {"1.0", "1.1"}  # reader accepts both as valid cache

# fetch_error enum (10 values) — do not add to this list without a Spec update.
ERR_NETWORK_UNAVAILABLE = "network_unavailable"
ERR_CLI_MISSING = "cli_missing"
ERR_AUTH_MISSING = "auth_missing"
ERR_AUTH_FAILED = "auth_failed"
ERR_RATE_LIMITED = "rate_limited"
ERR_NOT_FOUND = "not_found_or_no_access"
ERR_TIMEOUT = "timeout"
ERR_PLATFORM_UNKNOWN = "platform_unknown"
ERR_PARSE_ERROR = "parse_error"
ERR_UNKNOWN = "unknown"

# Fail-soft placeholder errors (submodule-level, not in the 10-enum but
# documented in references/issue-scanning.md §Fail-soft 矩阵扩展).
ERR_SUBMODULE_NOT_INIT = "submodule_not_initialized"
ERR_NO_ORIGIN_REMOTE = "no_origin_remote"

DEFAULT_CONFIG = {
    "enabled": False,
    "platform": None,
    "platform_hostnames": {
        "forgejo": ["forgejo.10cg.pub"],
        "github": ["github.com"],
    },
    "cache_ttl_seconds": 900,
    "cache_path": ".aria/cache/issues.json",
    "stage_timeout_seconds": None,   # None = compute adaptively
    "api_timeout_seconds": 5,
    "limit": 20,
    "label_filter": [],
    "scan_submodules": False,
}

_HOSTNAME_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*://)?(?:[^@/]+@)?([^:/]+)")
_OWNER_REPO_RE = re.compile(r"^[^/]+/[^/]+$")
_US_REGEX = re.compile(r"(?:^|[^A-Za-z0-9])(US-\d{3,})(?:[^A-Za-z0-9]|$)")

# ----- Config loader --------------------------------------------------------


def _load_config(project_root: Path) -> dict[str, Any]:
    """Read `.aria/config.json` → `state_scanner.issue_scan` merged with defaults.

    Missing file / missing block → defaults (enabled=False, opt-in).
    """
    cfg_path = project_root / ".aria" / "config.json"
    merged: dict[str, Any] = dict(DEFAULT_CONFIG)
    # Deep-copy the nested dict so mutations don't leak across invocations.
    merged["platform_hostnames"] = {
        k: list(v) for k, v in DEFAULT_CONFIG["platform_hostnames"].items()
    }
    merged["label_filter"] = list(DEFAULT_CONFIG["label_filter"])

    if not cfg_path.is_file():
        return merged
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("issue_scan: config read/parse failed: %s", e)
        return merged

    block = (raw.get("state_scanner") or {}).get("issue_scan") or {}
    for key, default in DEFAULT_CONFIG.items():
        if key in block and block[key] is not None:
            merged[key] = block[key]
    # platform_hostnames needs a merge, not a replace, so user-provided keys
    # extend the default mapping rather than blow it away.
    hostnames = block.get("platform_hostnames")
    if isinstance(hostnames, dict):
        for k, v in hostnames.items():
            if isinstance(v, list):
                merged["platform_hostnames"][k] = list(v)
    return merged


# ----- Platform detection ---------------------------------------------------


def _extract_hostname(remote_url: str) -> str | None:
    """Return hostname from a git remote URL.

    Handles https://, ssh://, and scp-style git@host:owner/repo.git forms.
    """
    if not remote_url:
        return None
    # scp form: git@host:owner/repo.git
    if "://" not in remote_url and "@" in remote_url and ":" in remote_url:
        after_at = remote_url.split("@", 1)[1]
        host_part = after_at.split(":", 1)[0]
        return host_part or None
    m = _HOSTNAME_RE.match(remote_url)
    if not m:
        return None
    host = m.group(1)
    # Strip port if present
    if ":" in host:
        host = host.split(":", 1)[0]
    return host or None


def _extract_owner_repo(remote_url: str) -> str | None:
    """Return `owner/repo` from a git remote URL, or None on failure.

    Strips protocol, user@, hostname(:port), trailing .git, query/fragment.
    Rejects anything that isn't exactly 2 path segments.
    """
    if not remote_url:
        return None
    s = remote_url.strip()
    # 1. Strip protocol (anything://)
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s, flags=re.IGNORECASE)
    # 2. Strip user@
    s = re.sub(r"^[^@/]+@", "", s)
    # 3. Strip host (up to first `/` or `:`)
    s = re.sub(r"^[^:/]+[:/]", "", s)
    # 4. Strip trailing .git and any query/fragment
    s = re.sub(r"\.git(?:[?#/].*)?$", "", s)
    s = re.sub(r"\.git$", "", s)
    s = s.rstrip("/")
    if _OWNER_REPO_RE.match(s):
        return s
    return None


def _detect_platform(
    cfg: dict[str, Any], remote_url: str | None
) -> str | None:
    """4-level platform detection. Returns 'forgejo'|'github'|None."""
    # Level 1: explicit config
    explicit = cfg.get("platform")
    if explicit:
        return str(explicit)
    if not remote_url:
        return None
    hostname = _extract_hostname(remote_url)
    if not hostname:
        return None
    # Level 2: platform_hostnames map
    hostmap = cfg.get("platform_hostnames") or {}
    for platform, hosts in hostmap.items():
        if hostname in (hosts or []):
            return platform
    # Level 3: URL substring heuristic (lower priority than explicit map)
    low = remote_url.lower()
    if "github.com" in low:
        return "github"
    # Well-known forgejo domain fallback (matches SKILL.md example).
    if "forgejo.10cg.pub" in low:
        return "forgejo"
    # Level 4: give up
    return None


# ----- CLI detection --------------------------------------------------------


def _cli_available(platform: str) -> bool:
    if platform == "forgejo":
        return shutil.which("forgejo") is not None
    if platform == "github":
        return shutil.which("gh") is not None
    return False


# ----- Cache helpers --------------------------------------------------------


def _cache_path(project_root: Path, cfg: dict[str, Any]) -> Path:
    raw = cfg.get("cache_path") or DEFAULT_CONFIG["cache_path"]
    p = Path(raw)
    if not p.is_absolute():
        p = project_root / p
    return p


def _parse_iso8601(ts: str) -> float | None:
    """Parse ISO8601 (with or without trailing Z) → epoch seconds. None on failure."""
    if not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.timestamp()
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_cache(path: Path) -> dict[str, Any] | None:
    """Return cache dict if present & schema-compatible, else None."""
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("issue_scan: cache read failed: %s", e)
        return None
    schema = str(data.get("schema_version", "0.0"))
    if schema not in SCHEMA_COMPAT:
        # Cold cache: unknown schema → discard and re-fetch.
        log.info(
            "issue_scan: cache schema %s outside compat set %s, treating as cold",
            schema, SCHEMA_COMPAT,
        )
        return None
    return data


def _write_cache_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False, sort_keys=False)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


# ----- Error classification -------------------------------------------------

_NETWORK_KEYWORDS = (
    "could not resolve host",
    "name or service not known",
    "temporary failure in name resolution",
    "network is unreachable",
    "connection refused",
    "no route to host",
    "could not connect",
    "ssl",
    "tls",
)
_AUTH_KEYWORDS = ("unauthorized", "forbidden", "401", "403")
_RATE_KEYWORDS = ("rate limit", "429", "too many requests")
_NOT_FOUND_KEYWORDS = ("404", "not found")


def _classify_error(rc: int, stderr: str, combined: str = "") -> str:
    """Map an exit code + stderr snippet to the 10-enum fetch_error."""
    if rc == 127:
        return ERR_CLI_MISSING
    if rc == 124:
        return ERR_TIMEOUT
    lo = (stderr + " " + combined).lower()
    if any(k in lo for k in _NETWORK_KEYWORDS):
        return ERR_NETWORK_UNAVAILABLE
    if any(k in lo for k in _AUTH_KEYWORDS):
        return ERR_AUTH_FAILED
    if any(k in lo for k in _RATE_KEYWORDS):
        return ERR_RATE_LIMITED
    if any(k in lo for k in _NOT_FOUND_KEYWORDS):
        return ERR_NOT_FOUND
    return ERR_UNKNOWN


# ----- Normalization --------------------------------------------------------


def _normalize_items(raw_items: list[dict[str, Any]], platform: str) -> list[dict[str, Any]]:
    """Coerce raw Forgejo/GitHub API objects → canonical IssueItem list.

    Canonical keys: number, title, labels, url, body.
    URL falls back to `html_url` then `url`.

    QA-C2 fix (post_implementation audit R1): Forgejo conflates issues and PRs
    on the /issues endpoint. Even with `type=issues` on the URL, older Forgejo
    versions return PRs (they carry a `pull_request` sub-object). We reject any
    item that has a `pull_request` key or whose URL path segment is `/pulls/` —
    both conditions reliably identify PRs across Forgejo / Gitea variants.
    GitHub's `gh issue list` already filters PRs server-side, so the filter is
    a no-op there but harmless as a belt-and-suspenders guard.
    """
    out: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        # QA-C2: reject PRs
        if "pull_request" in raw:
            continue
        url = raw.get("html_url") or raw.get("url") or ""
        if isinstance(url, str) and "/pulls/" in url:
            continue
        labels = []
        raw_labels = raw.get("labels") or []
        for lbl in raw_labels:
            if isinstance(lbl, dict):
                name = lbl.get("name")
                if isinstance(name, str):
                    labels.append(name)
            elif isinstance(lbl, str):
                labels.append(lbl)
        out.append({
            "number": int(raw.get("number") or 0),
            "title": str(raw.get("title") or ""),
            "labels": labels,
            "url": str(url),
            "body": str(raw.get("body") or ""),
        })
    _ = platform  # reserved for future platform-specific quirks
    return out


# ----- Heuristic linking ----------------------------------------------------


def _list_openspec_changes(project_root: Path) -> list[str]:
    """Enumerate change directories under openspec/changes/."""
    base = project_root / "openspec" / "changes"
    if not base.is_dir():
        return []
    out: list[str] = []
    try:
        for entry in base.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                out.append(entry.name)
    except OSError:
        return []
    return out


def _match_us(text: str) -> str | None:
    m = _US_REGEX.search(text)
    return m.group(1) if m else None


def _match_openspec(text: str, changes: list[str]) -> str | None:
    """Word-boundary match against each change name. URL path protection via
    checking neighbouring chars aren't `[a-z0-9/-]`.
    """
    if not text or not changes:
        return None
    lower = text.lower()
    for name in changes:
        n_low = name.lower()
        n_len = len(n_low)
        pos = 0
        while True:
            idx = lower.find(n_low, pos)
            if idx < 0:
                break
            left_ok = idx == 0 or not re.match(r"[a-z0-9/\-]", lower[idx - 1])
            right_end = idx + n_len
            right_ok = right_end >= len(lower) or not re.match(
                r"[a-z0-9/\-]", lower[right_end]
            )
            if left_ok and right_ok:
                return name
            pos = idx + 1
    return None


def _apply_heuristics(
    items: list[dict[str, Any]], openspec_changes: list[str]
) -> list[dict[str, Any]]:
    """Annotate each item with linked_us / linked_openspec / heuristic=True."""
    for it in items:
        haystack = f"{it.get('title', '')} {it.get('body', '')}"
        it["linked_us"] = _match_us(haystack)
        it["linked_openspec"] = _match_openspec(haystack, openspec_changes)
        it["heuristic"] = True
        # Drop body from the output (we only used it for linking); keeps the
        # snapshot small and avoids leaking large issue bodies into state.
        it.pop("body", None)
    return items


# ----- API calls ------------------------------------------------------------


def _fetch_forgejo(owner_repo: str, limit: int, timeout: int) -> tuple[int, str, str]:
    """Call forgejo wrapper. Returns (rc, stdout, stderr).

    QA-C2 fix (post_implementation audit R1): Forgejo's /issues endpoint returns
    BOTH issues and pull requests by default. Adding `type=issues` excludes PRs
    at the API level. Client-side filter in the normalizer is the second line of
    defense (older Forgejo versions may ignore the parameter).
    """
    endpoint = f"/repos/{owner_repo}/issues?state=open&type=issues&limit={limit}"
    return _run(["forgejo", "GET", endpoint], Path.cwd(), timeout=timeout)


def _fetch_github(owner_repo: str, limit: int, timeout: int) -> tuple[int, str, str]:
    """Call gh CLI. Returns (rc, stdout, stderr)."""
    return _run(
        [
            "gh", "issue", "list",
            "--repo", owner_repo,
            "--state", "open",
            "--limit", str(limit),
            "--json", "number,title,labels,url,body",
        ],
        Path.cwd(),
        timeout=timeout,
    )


def _fetch_repo(
    platform: str,
    owner_repo: str,
    limit: int,
    label_filter: list[str],
    timeout: int,
) -> tuple[list[dict[str, Any]], str | None, str]:
    """Fetch open issues for one repo.

    Returns (normalized_items, fetch_error_or_none, source).
    source is 'live' on success, 'unavailable' on failure.
    """
    if platform == "forgejo":
        rc, out, err = _fetch_forgejo(owner_repo, limit, timeout)
    elif platform == "github":
        rc, out, err = _fetch_github(owner_repo, limit, timeout)
    else:
        return [], ERR_PLATFORM_UNKNOWN, "unavailable"

    if rc != 0:
        return [], _classify_error(rc, err, out), "unavailable"

    # Forgejo wrapper uses curl; an HTTP error body may come back as JSON with
    # a 'message' field but rc==0. Guard against that.
    try:
        parsed = json.loads(out) if out.strip() else []
    except json.JSONDecodeError:
        return [], ERR_PARSE_ERROR, "unavailable"

    if isinstance(parsed, dict):
        msg = str(parsed.get("message", "")).lower()
        if "unauthorized" in msg or parsed.get("status") in (401, 403):
            return [], ERR_AUTH_FAILED, "unavailable"
        if "not found" in msg or parsed.get("status") == 404:
            return [], ERR_NOT_FOUND, "unavailable"
        # Unknown dict response → parse error
        return [], ERR_PARSE_ERROR, "unavailable"

    if not isinstance(parsed, list):
        return [], ERR_PARSE_ERROR, "unavailable"

    items = _normalize_items(parsed, platform)

    # Client-side label filter — Forgejo wrapper path doesn't always honor
    # `labels=` query, so apply locally for consistent behaviour across
    # platforms.
    if label_filter:
        wanted = set(label_filter)
        items = [it for it in items if wanted.intersection(it.get("labels", []))]

    return items, None, "live"


# ----- Submodule enumeration ------------------------------------------------


def _enumerate_submodules(project_root: Path) -> list[str]:
    """Return ordered list of submodule paths from .gitmodules."""
    gm = project_root / ".gitmodules"
    if not gm.is_file():
        return []
    rc, out, _err = _run(
        ["git", "config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..+\.path$"],
        project_root,
    )
    if rc != 0:
        return []
    paths: list[str] = []
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            paths.append(parts[1])
    return paths


def _submodule_remote_url(project_root: Path, sub_path: str) -> str | None:
    rc, out, _err = _run(
        ["git", "remote", "get-url", "origin"], project_root / sub_path
    )
    if rc != 0:
        return None
    url = out.strip()
    return url or None


# ----- Main collector -------------------------------------------------------


def _build_empty_repo_entry(
    platform: str | None, fetch_error: str | None
) -> dict[str, Any]:
    return {
        "platform": platform,
        "source": "unavailable",
        "fetch_error": fetch_error,
        "fetched_at": None,
        "open_count": 0,
        "items": [],
    }


def _stage_budget(cfg: dict[str, Any], n_submodules: int) -> int:
    """Adaptive stage timeout per SKILL.md §阶段 1.13.

    - explicit user value → honoured verbatim
    - scan_submodules=false + no explicit → 12s (v1.0 constant)
    - scan_submodules=true + no explicit → max(20, (N+1) × api_timeout_seconds)
    """
    explicit = cfg.get("stage_timeout_seconds")
    if isinstance(explicit, int) and explicit > 0:
        return explicit
    api_t = int(cfg.get("api_timeout_seconds", 5) or 5)
    if cfg.get("scan_submodules"):
        return max(20, (n_submodules + 1) * api_t)
    return 12


def collect_issue_scan(project_root: Path) -> CollectorResult:
    """Collect Phase 1.13 `issue_status` snapshot.

    Output shape when `enabled=False`: `{"enabled": False}` (scan.py decides
    whether to emit a section in the final snapshot). Output shape when
    enabled: full `issue_status` dict matching SKILL.md §阶段 1.13 schema.

    Never raises; all failures surface as `fetch_error` + `soft_error`.
    """
    r = CollectorResult()
    cfg = _load_config(project_root)

    if not cfg.get("enabled"):
        r.data = {"enabled": False}
        return r

    stage_start = time.monotonic()
    api_timeout = int(cfg.get("api_timeout_seconds", 5) or 5)
    limit = int(cfg.get("limit", 20) or 20)
    label_filter = list(cfg.get("label_filter") or [])
    ttl = int(cfg.get("cache_ttl_seconds", 900) or 900)
    openspec_changes = _list_openspec_changes(project_root)

    # Submodule list (needed for budget calc even when disabled, to keep a
    # consistent `n_submodules=0` path).
    scan_subs = bool(cfg.get("scan_submodules"))
    submodule_paths = _enumerate_submodules(project_root) if scan_subs else []
    stage_budget = _stage_budget(cfg, len(submodule_paths))

    def _budget_left() -> float:
        return stage_budget - (time.monotonic() - stage_start)

    # ---- Main repo pass ---------------------------------------------------
    main_remote_rc, main_remote_out, _err = _run(
        ["git", "remote", "get-url", "origin"], project_root
    )
    main_remote = main_remote_out.strip() if main_remote_rc == 0 else ""
    main_platform = _detect_platform(cfg, main_remote)

    cache = _read_cache(_cache_path(project_root, cfg))

    main_entry: dict[str, Any]
    if main_platform is None:
        r.soft_error(ERR_PLATFORM_UNKNOWN, f"remote={main_remote!r}")
        main_entry = _build_empty_repo_entry(None, ERR_PLATFORM_UNKNOWN)
        main_key = _extract_owner_repo(main_remote) or "unknown/unknown"
    else:
        main_key = _extract_owner_repo(main_remote) or "unknown/unknown"
        # CLI check
        if not _cli_available(main_platform):
            r.soft_error(ERR_CLI_MISSING, f"platform={main_platform}")
            main_entry = _build_empty_repo_entry(main_platform, ERR_CLI_MISSING)
        else:
            # Cache probe (per-repo, per-schema)
            cached_entry = _lookup_cached_repo(cache, main_key, ttl) if cache else None
            if cached_entry is not None:
                main_entry = cached_entry
                main_entry["source"] = "cache"
            else:
                per_call_timeout = max(1, min(api_timeout, int(_budget_left()) or 1))
                items, ferr, source = _fetch_repo(
                    main_platform, main_key, limit, label_filter, per_call_timeout
                )
                if ferr is not None:
                    r.soft_error(ferr, f"repo={main_key}")
                    main_entry = _build_empty_repo_entry(main_platform, ferr)
                else:
                    _apply_heuristics(items, openspec_changes)
                    main_entry = {
                        "platform": main_platform,
                        "source": source,
                        "fetch_error": None,
                        "fetched_at": _now_iso(),
                        "open_count": len(items),
                        "items": items,
                    }

    repos: dict[str, dict[str, Any]] = {main_key: main_entry}

    # ---- Submodule pass ---------------------------------------------------
    warning: str | None = None
    if scan_subs:
        for sub_path in submodule_paths:
            if _budget_left() <= 0:
                warning = "stage_timeout"
                break
            sub_dir = project_root / sub_path
            if not sub_dir.is_dir() or not (sub_dir / ".git").exists():
                repos[sub_path] = _build_empty_repo_entry(None, ERR_SUBMODULE_NOT_INIT)
                r.soft_error(ERR_SUBMODULE_NOT_INIT, f"path={sub_path}")
                continue
            sub_remote = _submodule_remote_url(project_root, sub_path)
            if not sub_remote:
                repos[sub_path] = _build_empty_repo_entry(None, ERR_NO_ORIGIN_REMOTE)
                r.soft_error(ERR_NO_ORIGIN_REMOTE, f"path={sub_path}")
                continue
            sub_owner_repo = _extract_owner_repo(sub_remote)
            if not sub_owner_repo:
                repos[sub_path] = _build_empty_repo_entry(None, ERR_PARSE_ERROR)
                r.soft_error(ERR_PARSE_ERROR, f"path={sub_path} remote={sub_remote}")
                continue
            sub_platform = _detect_platform(cfg, sub_remote)
            if sub_platform is None:
                repos[sub_owner_repo] = _build_empty_repo_entry(
                    None, ERR_PLATFORM_UNKNOWN
                )
                r.soft_error(ERR_PLATFORM_UNKNOWN, f"path={sub_path}")
                continue
            if not _cli_available(sub_platform):
                repos[sub_owner_repo] = _build_empty_repo_entry(
                    sub_platform, ERR_CLI_MISSING
                )
                r.soft_error(ERR_CLI_MISSING, f"platform={sub_platform}")
                continue
            # Cache probe (per-repo)
            cached_entry = _lookup_cached_repo(cache, sub_owner_repo, ttl) if cache else None
            if cached_entry is not None:
                cached_entry["source"] = "cache"
                repos[sub_owner_repo] = cached_entry
                continue
            per_call_timeout = max(1, min(api_timeout, int(_budget_left()) or 1))
            items, ferr, source = _fetch_repo(
                sub_platform, sub_owner_repo, limit, label_filter, per_call_timeout
            )
            if ferr is not None:
                repos[sub_owner_repo] = _build_empty_repo_entry(sub_platform, ferr)
                r.soft_error(ferr, f"repo={sub_owner_repo}")
                continue
            _apply_heuristics(items, openspec_changes)
            repos[sub_owner_repo] = {
                "platform": sub_platform,
                "source": source,
                "fetch_error": None,
                "fetched_at": _now_iso(),
                "open_count": len(items),
                "items": items,
            }

    # ---- Aggregation ------------------------------------------------------
    flat_items: list[dict[str, Any]] = []
    for key, entry in repos.items():
        if entry.get("fetch_error") is not None:
            continue
        for it in entry.get("items", []) or []:
            merged = dict(it)
            merged["repo"] = key
            flat_items.append(merged)

    open_count = len(flat_items)
    label_summary: dict[str, int] = {}
    for it in flat_items:
        for lbl in it.get("labels") or []:
            label_summary[lbl] = label_summary.get(lbl, 0) + 1

    # Aggregate fetched_at: earliest non-null per-repo stamp (conservative).
    stamps = [e["fetched_at"] for e in repos.values() if e.get("fetched_at")]
    aggregate_fetched_at = min(stamps) if stamps else None

    # Aggregate source/fetch_error reflect the MAIN repo (per spec §输出 Schema).
    agg_source = main_entry.get("source") or "unavailable"
    agg_fetch_error = main_entry.get("fetch_error")
    agg_platform = main_entry.get("platform")

    issue_status: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "fetched_at": aggregate_fetched_at,
        "source": agg_source,
        "fetch_error": agg_fetch_error,
        "warning": warning,
        "platform": agg_platform,
        "open_count": open_count,
        "items": flat_items,
        # open_issues is the SAME list object as items — v1.0 consumers keep
        # working and future mutations stay consistent.
        "open_issues": flat_items,
        "label_summary": label_summary,
        "repos": repos,
    }

    # ---- Cache writeback --------------------------------------------------
    # Only persist when we actually did live work (avoid thrashing cache with
    # cached-cached results, and avoid overwriting with platform_unknown).
    did_live_work = any(
        e.get("source") == "live" for e in repos.values()
    )
    if did_live_work:
        cache_payload = {
            "schema_version": SCHEMA_VERSION,
            "fetched_at": aggregate_fetched_at,
            "ttl_seconds": ttl,
            "scan_submodules": scan_subs,
            "platform": agg_platform,
            "open_count": open_count,
            "items": flat_items,
            "open_issues": flat_items,
            "label_summary": label_summary,
            "repos": repos,
        }
        try:
            _write_cache_atomic(_cache_path(project_root, cfg), cache_payload)
        except OSError as e:
            r.soft_error("cache_write_failed", str(e))

    r.data = {"enabled": True, "issue_status": issue_status}
    return r


def _lookup_cached_repo(
    cache: dict[str, Any] | None, owner_repo: str, ttl: int
) -> dict[str, Any] | None:
    """Return a cached per-repo entry if present and within TTL, else None.

    Falls back to the top-level v1.0 structure when the cache is v1.0 (single
    repo, no `repos{}` key) by mapping `items[]` → the requested repo.
    """
    if not cache:
        return None
    now = time.time()
    repos = cache.get("repos")
    if isinstance(repos, dict) and owner_repo in repos:
        entry = repos[owner_repo]
        if not isinstance(entry, dict):
            return None
        ts = _parse_iso8601(str(entry.get("fetched_at") or ""))
        if ts is not None and (now - ts) < ttl:
            # Return a deep-enough copy so caller mutations don't leak back.
            copied = dict(entry)
            copied["items"] = [dict(i) for i in (entry.get("items") or [])]
            return copied
        return None
    # v1.0 fallback
    top_stamp = _parse_iso8601(str(cache.get("fetched_at") or ""))
    if top_stamp is None or (now - top_stamp) >= ttl:
        return None
    top_platform = cache.get("platform")
    items_src = cache.get("items")
    if not isinstance(items_src, list):
        items_src = cache.get("open_issues")
    if not isinstance(items_src, list):
        return None
    # v1.0 cache has no per-repo key; assume it belongs to the requested
    # main repo only. Return None for submodules we don't recognise.
    return {
        "platform": top_platform,
        "source": "cache",
        "fetch_error": None,
        "fetched_at": cache.get("fetched_at"),
        "open_count": len(items_src),
        "items": [dict(i) for i in items_src],
    }
