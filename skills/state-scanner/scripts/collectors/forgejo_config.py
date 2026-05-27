"""Phase 1.14 — Forgejo configuration detection collector.

Detects whether the current project uses a known Forgejo instance (by inspecting
the `origin` git remote URL), and if so, whether `CLAUDE.local.md` contains a
`forgejo:` configuration block.

Fail-soft contract: any git or filesystem failure collapses to the conservative
`{"forgejo_remote_detected": false}` result — this collector never aborts scan.

Output schema (exactly one of four states, matches SKILL.md §1.14):
  state 1 (non-Forgejo remote):
    {"forgejo_remote_detected": false}
  state 2 (Forgejo remote, CLAUDE.local.md missing):
    {"forgejo_remote_detected": true, "instance": "<host>",
     "config_status": "missing",
     "suggestion": "运行 /forgejo-sync 可引导创建配置 (需确认)"}
  state 3 (Forgejo remote, file present, no forgejo: block):
    {"forgejo_remote_detected": true, "instance": "<host>",
     "config_status": "incomplete",
     "suggestion": "运行 /forgejo-sync 可引导追加配置 (需确认)"}
  state 4 (Forgejo remote, forgejo: block present):
    {"forgejo_remote_detected": true, "instance": "<host>",
     "config_status": "configured"}
"""

from __future__ import annotations

import re
from pathlib import Path

from ._common import CollectorResult, _run, resolve_forgejo_hosts

# Forgejo hostnames now resolved per-call via _common.resolve_forgejo_hosts(project_root).
# Precedence: ARIA_FORGEJO_HOSTS env > .aria/config.json > legacy ("forgejo.10cg.pub",).
# Per OpenSpec aria-forgejo-hosts-parameterization (v1.30.0).

# Matches, in order:
#   1. YAML top-level key:     ^forgejo:                  (or fullwidth `：`)
#   2. Markdown heading:       ^#{1,3} forgejo            (case-insensitive)
#   3. Fenced YAML line:       ^forgejo:                  (same as #1; substring via MULTILINE)
#   4. Blockquote-prefixed:    ^> forgejo:                (Chinese-author docs habit)
# i18n hardening (Spec `state-scanner-collector-regex-hardening`, 2026-04-25):
# - YAML key accepts BOTH halfwidth `:` (U+003A) and fullwidth `：` (U+FF1A)
#   via `[：:]` — fullwidth is Chinese IME default
# - Optional `>?` blockquote prefix allows config to live inside markdown blockquotes
_FORGEJO_YAML_KEY = re.compile(r"^\s*>?\s*forgejo\s*[：:]", re.MULTILINE)
_FORGEJO_HEADING = re.compile(r"^\s*>?\s*#{1,3}\s+forgejo\b", re.MULTILINE | re.IGNORECASE)
_FENCED_BLOCK = re.compile(r"```[\s\S]*?```", re.MULTILINE)


def _detect_forgejo_host(remote_url: str, known_hosts: tuple[str, ...]) -> str | None:
    """Return the matched Forgejo hostname if `remote_url` references a known
    instance; otherwise None. Matches both SSH-style
    (`ssh://git@<host>/...`, `git@<host>:...`) and HTTPS (`https://<host>/...`).

    `known_hosts` is param-injected by `collect_forgejo_config()` so the resolver
    (env / .aria/config.json / legacy fallback) controls what's "known".
    """
    if not remote_url:
        return None
    for host in known_hosts:
        if host in remote_url:
            return host
    return None


def _has_forgejo_block(text: str) -> bool:
    """Heuristic: a `forgejo:` YAML key OR a `# forgejo` markdown heading
    anywhere in the file counts as "configured". Case-insensitive for headings,
    case-sensitive for YAML keys (YAML is case-sensitive).

    QA-I3 fix (post_implementation audit R1): `forgejo:` appearing inside a
    fenced code block (e.g., a documentation example showing what the real
    config should look like) must NOT count as a real config. Users who paste
    sample YAML into CLAUDE.local.md would otherwise see `config_status:
    configured` and lose the /forgejo-sync remediation hint. We mask fenced
    blocks (```…```) before running the heuristics.
    """
    stripped = _FENCED_BLOCK.sub("", text)
    if _FORGEJO_YAML_KEY.search(stripped):
        return True
    if _FORGEJO_HEADING.search(stripped):
        return True
    return False


def collect_forgejo_config(project_root: Path) -> CollectorResult:
    """Phase 1.14 entry point. Returns one of 4 states defined in SKILL.md §1.14:

    1. Non-Forgejo remote → `{forgejo_remote_detected: false}`
    2. Forgejo remote + no CLAUDE.local.md → `config_status: missing`
    3. Forgejo remote + CLAUDE.local.md without forgejo block → `incomplete`
    4. Forgejo remote + CLAUDE.local.md with forgejo block → `configured`

    Fail-soft: any git error, OS error, or unknown host collapses to state 1.
    """
    r = CollectorResult()

    # Step 1: inspect origin remote. Fail-soft: any git error → state 1.
    rc, stdout, stderr = _run(
        ["git", "remote", "get-url", "origin"], cwd=project_root, timeout=5
    )
    if rc != 0:
        # No remote, not a git repo, timeout, or git missing — treat as not Forgejo.
        r.data = {"forgejo_remote_detected": False}
        return r

    known_hosts = resolve_forgejo_hosts(project_root)
    host = _detect_forgejo_host(stdout.strip(), known_hosts)
    if host is None:
        r.data = {"forgejo_remote_detected": False}
        return r

    # Step 2 + 3: inspect CLAUDE.local.md.
    local_md = project_root / "CLAUDE.local.md"
    if not local_md.is_file():
        r.data = {
            "forgejo_remote_detected": True,
            "instance": host,
            "config_status": "missing",
            "suggestion": "运行 /forgejo-sync 可引导创建配置 (需确认)",
        }
        return r

    try:
        text = local_md.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        # File exists but unreadable — treat as incomplete so the user gets
        # actionable guidance rather than silent success.
        r.soft_error("claude_local_md_read_failed", str(e))
        r.data = {
            "forgejo_remote_detected": True,
            "instance": host,
            "config_status": "incomplete",
            "suggestion": "运行 /forgejo-sync 可引导追加配置 (需确认)",
        }
        return r

    if _has_forgejo_block(text):
        r.data = {
            "forgejo_remote_detected": True,
            "instance": host,
            "config_status": "configured",
        }
    else:
        r.data = {
            "forgejo_remote_detected": True,
            "instance": host,
            "config_status": "incomplete",
            "suggestion": "运行 /forgejo-sync 可引导追加配置 (需确认)",
        }
    return r
