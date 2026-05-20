"""
identity.py — Container and session identity for multi-terminal coordination.

Provides three-segment identity per DEC-20260519-001 #3 and
standards/conventions/session-handoff.md §2.3.1:

  owner        — git user.email local-part (persistent, git-backed)
  container_id — ~/.aria/container-id short-UUID + optional label (persistent, file-backed)
  session_id   — ephemeral per-session random + start timestamp

Public API
----------
  get_owner(home_dir=None) -> str
  get_container_id(home_dir=None) -> str
  get_session_id(now=None) -> str
  get_identity(home_dir=None, now=None) -> Identity
"""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CONTAINER_ID_FILE = ".aria/container-id"
_CONTAINER_ID_TMP_SUFFIX = ".tmp"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Identity:
    """Three-segment identity for a single Aria session.

    Attributes
    ----------
    owner:
        git user.email local-part (the portion before ``@``).
        Falls back to ``"unknown"`` when git is unavailable or unconfigured.
    container_id:
        Persistent short-UUID (8 hex chars) optionally decorated with a
        human-readable label.  Loaded from ``~/.aria/container-id``; generated
        + persisted on first call; falls back to hostname when the file is
        unreadable.
    session_id:
        Ephemeral identifier for the current Claude Code session.
        Format: ``s-<4 hex chars>@<HHMM UTC>``.  Fresh on every call to
        :func:`get_identity`.
    """

    owner: str
    container_id: str
    session_id: str

    @property
    def owner_container(self) -> str:
        """Composite ``<owner>/<container_id>`` used in handoff frontmatter."""
        return f"{self.owner}/{self.container_id}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _hostname() -> str:
    """Return the machine hostname (no sanitization — accepted as-is)."""
    try:
        return socket.gethostname()
    except Exception:  # pragma: no cover — OS-level failure
        return "unknown-host"


def _aria_dir(home_dir: Optional[Path]) -> Path:
    """Resolve the ``~/.aria/`` directory path."""
    base = home_dir if home_dir is not None else Path.home()
    return base / ".aria"


def _container_id_path(home_dir: Optional[Path]) -> Path:
    return _aria_dir(home_dir) / "container-id"


def _generate_uuid() -> str:
    """Return an 8-char lowercase hex string via secrets.token_hex(4)."""
    return secrets.token_hex(4)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_container_file(text: str) -> dict:
    """Parse the simple ``key: value`` YAML subset used in container-id files.

    Returns a dict with at least ``uuid`` and ``label`` keys (both strings).
    Raises ``ValueError`` on parse failure (triggers regeneration).
    """
    result: dict = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        result[key.strip()] = value.strip()

    if "uuid" not in result:
        raise ValueError("container-id file missing 'uuid' field")
    return result


def _write_container_file(path: Path, uuid: str, label: str, created_at: str) -> None:
    """Atomically write the container-id file via a .tmp rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(_CONTAINER_ID_TMP_SUFFIX)

    label_value = label if label else ""
    content = (
        f"# Aria container identity (auto-generated {created_at})\n"
        f"# Edit the `label` line to add a human-readable tag"
        f' (e.g. "devbox-A" / "laptop")\n'
        f"uuid: {uuid}\n"
        f"label: {label_value}\n"
        f"created_at: {created_at}\n"
    )

    try:
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError as exc:
        # Clean up tmp if it was written; non-fatal — caller will fallback.
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise exc


# ---------------------------------------------------------------------------
# Public getters
# ---------------------------------------------------------------------------


def get_owner() -> str:
    """Return the git ``user.email`` local-part for the current working tree.

    Returns
    -------
    str
        The portion of ``user.email`` before ``@``.  If git is unavailable,
        unconfigured, or the address has no ``@``, returns ``"unknown"``.

    Notes
    -----
    Rule #7 compliance: git subprocess uses ``capture_output=True`` — its
    stdout/stderr never flow into the chat-visible channel.
    """
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            email = result.stdout.strip()
            if "@" in email:
                return email.split("@", 1)[0]
            # Email present but no '@' — still use it as-is? Per spec: "无 @
            # … → fallback … local-part = 'unknown'"
            return "unknown"
    except Exception:
        pass
    return "unknown"


def get_container_id(home_dir: Optional[Path] = None) -> str:
    """Return the persistent container identifier for this machine.

    Reads ``~/.aria/container-id`` (or ``<home_dir>/.aria/container-id`` for
    test injection).  On first call the file is created with a newly generated
    8-char hex UUID.  On parse failure the file is regenerated.

    Returns
    -------
    str
        ``label`` field if non-empty, otherwise ``uuid`` field value.
        Falls back to hostname when the file cannot be read *and* cannot be
        created (e.g. read-only filesystem).

    Parameters
    ----------
    home_dir:
        Override the home directory used to locate ``~/.aria/``.  Pass a
        ``tmp_path`` fixture in tests to avoid touching the real user home.
    """
    path = _container_id_path(home_dir)

    # --- Attempt to read existing file ---
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8")
            parsed = _parse_container_file(text)
            label = parsed.get("label", "").strip()
            uuid = parsed.get("uuid", "").strip()
            if not uuid:
                raise ValueError("uuid field is empty")
            return label if label else uuid
        except Exception as exc:
            print(
                f"[aria/identity] WARNING: container-id file corrupt ({exc}),"
                " regenerating.",
                file=sys.stderr,
            )
            # Fall through to regeneration.

    # --- Generate a new container-id ---
    uuid = _generate_uuid()
    created_at = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        _write_container_file(path, uuid=uuid, label="", created_at=created_at)
    except OSError as exc:
        print(
            f"[aria/identity] WARNING: cannot write container-id file ({exc}),"
            f" falling back to hostname.",
            file=sys.stderr,
        )
        return _hostname()

    return uuid


def get_session_id(now: Optional[datetime] = None) -> str:
    """Generate an ephemeral session identifier.

    Format: ``s-<4 hex chars>@<HHMM UTC>``

    Each call returns a fresh value.  Two sessions started in the same UTC
    minute are distinguished by the random hex component.

    Parameters
    ----------
    now:
        Override the current UTC time (test injection).
    """
    ts = now if now is not None else _now_utc()
    random_hex = secrets.token_hex(2)  # 4 hex chars
    hhmm = ts.strftime("%H%M")
    return f"s-{random_hex}@{hhmm}"


def get_identity(
    home_dir: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Identity:
    """Return a fully populated :class:`Identity` for the current session.

    ``session_id`` is freshly generated on every call.

    Parameters
    ----------
    home_dir:
        Forwarded to :func:`get_container_id` (test injection).
    now:
        Forwarded to :func:`get_session_id` (test injection).
    """
    return Identity(
        owner=get_owner(),
        container_id=get_container_id(home_dir=home_dir),
        session_id=get_session_id(now=now),
    )
