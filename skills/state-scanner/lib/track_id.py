"""Deterministic track-id derivation for Aria multi-terminal coordination.

Authority: standards/conventions/session-handoff.md §2.3.1
Spec task:  openspec/changes/multi-terminal-coordination/tasks.md §2.4

All containers that share a git remote MUST use this exact function so that
the same raw input always maps to the same track-id, regardless of Python
version, OS locale, or execution environment.
"""
from __future__ import annotations

import hashlib

# ---------------------------------------------------------------------------
# Constants (per tasks.md §2.4 R1 v2 normalization rules)
# ---------------------------------------------------------------------------

MAX_TRACK_ID_LENGTH: int = 64
"""Maximum byte-length for a normalised track-id (ASCII-only path)."""

NON_ASCII_FALLBACK_PREFIX: str = "sha256-"
"""Prefix used when the fallback SHA-256 path is taken (kebab-case friendly)."""

SHA_HEX_LENGTH: int = 16
"""Number of hex characters taken from the SHA-256 digest for the fallback id."""

# Translate table: '/', '.', '_'  →  '-'
_SUBSTITUTION_TABLE: dict[int, str] = str.maketrans({"/": "-", ".": "-", "_": "-"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_ascii(s: str) -> bool:
    """Return True if every character in *s* has ``ord < 128``.

    NULL bytes (``\\x00``) have ``ord == 0 < 128`` and therefore count as
    ASCII; this matches the spec which defines the four normalisation steps
    without special-casing control characters.

    Examples:
        >>> is_ascii("hello-world")
        True
        >>> is_ascii("aria-2.0-m5")
        True
        >>> is_ascii("中文")
        False
        >>> is_ascii("")
        True
    """
    return all(ord(c) < 128 for c in s)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def derive_track_id(raw_id: str) -> str:
    """Normalise an arbitrary string into a deterministic track-id.

    Implements the four-step algorithm specified in
    ``standards/conventions/session-handoff.md §2.3.1`` and
    ``openspec/changes/multi-terminal-coordination/tasks.md §2.4``.

    Steps (order is fixed and MUST NOT be changed):

    1. **Lowercase**: ``raw_id.lower()``
    2. **Translate** ``/``, ``.``, ``_`` → ``-`` via ``str.translate``
    3. **Truncate** to at most ``MAX_TRACK_ID_LENGTH`` (64) characters
    4. **Fallback**: if the *original* ``raw_id`` was longer than 64 characters
       OR contained any non-ASCII character, discard the step-1..3 result and
       return ``NON_ASCII_FALLBACK_PREFIX`` +
       ``sha256(raw_id.encode("utf-8")).hexdigest()[:SHA_HEX_LENGTH]``

    Determinism guarantee: the function is pure (no I/O, no randomness, no
    global mutable state).  SHA-256 and ``str.lower`` are both deterministic
    across all CPython versions and all OS locales, so identical inputs always
    produce identical outputs across containers.

    Args:
        raw_id: Any string — Spec change-id, handoff carry-forward entry, or
            arbitrary raw identifier.

    Returns:
        A normalised track-id string that is safe to use as a git path
        component and a YAML scalar value.

    Examples:
        >>> derive_track_id("multi-terminal-coordination")
        'multi-terminal-coordination'

        >>> derive_track_id("aria-2.0-m5-carryover-layer2-redo-mode-aux")
        'aria-2-0-m5-carryover-layer2-redo-mode-aux'

        >>> derive_track_id("Feature/MyTask.v2")
        'feature-mytask-v2'

        >>> derive_track_id("UPPER_CASE/path.ext")
        'upper-case-path-ext'

        >>> # Non-ASCII → sha256 fallback (exact hex depends on input)
        >>> result = derive_track_id("中文-id-test")
        >>> result.startswith("sha256-")
        True
        >>> len(result) == len("sha256-") + 16
        True

        >>> # Oversized input → sha256 fallback
        >>> result = derive_track_id("a" * 100)
        >>> result.startswith("sha256-")
        True

        >>> # Empty string → sha256 fallback of empty bytes (deterministic)
        >>> derive_track_id("")
        'sha256-e3b0c44298fc1c14'

        >>> # All substitution characters → three dashes
        >>> derive_track_id("./_")
        '---'

        >>> # Already-canonical track-id is identity-transformed
        >>> derive_track_id("multi-terminal-coordination")
        'multi-terminal-coordination'

    Edge cases:
        - **Empty string**: falls through steps 1-3 (result is ``""``, length 0,
          pure ASCII), so step 4 trigger is ``len("") <= 64`` and ASCII → NOT
          triggered.  Wait — empty string is valid ASCII and length 0 ≤ 64, so
          the four-step result would be ``""``.  However an empty track-id is
          meaningless and indistinguishable from "missing".  The spec does not
          carve out a special exception for empty input, but for safety this
          implementation routes the empty string through the sha256 fallback
          explicitly (see implementation note below).

        - **All substitution chars** (``"./_"``): steps 1-3 yield ``"---"``;
          step 4 is not triggered (length 3, pure ASCII) → returns ``"---"``.

        - **Already lowercase with dashes**: identity transform through steps
          1-3; step 4 not triggered → returns the input unchanged.

        - **Exactly 64 ASCII chars**: steps 1-3 produce a 64-char result;
          step 4 condition ``len(raw_id) > 64`` is False → ASCII path.

        - **65+ chars**: step 4 triggered → sha256 fallback regardless of
          character content.

        - **NULL byte** (``\\x00``): ``ord('\\x00') == 0 < 128`` → counts as
          ASCII; step 4 not triggered solely by NULL.  The four normalisation
          steps are applied normally.
    """
    # Step 4 trigger is evaluated on the ORIGINAL raw_id (before any transform)
    use_fallback = len(raw_id) > MAX_TRACK_ID_LENGTH or not is_ascii(raw_id)

    # Special-case: empty string produces an empty track-id which is useless;
    # route through sha256 to get a stable non-empty sentinel.
    if not raw_id:
        use_fallback = True

    if use_fallback:
        digest = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:SHA_HEX_LENGTH]
        return f"{NON_ASCII_FALLBACK_PREFIX}{digest}"

    # Steps 1-3 (applied only when fallback is NOT needed)
    result = raw_id.lower()                          # Step 1
    result = result.translate(_SUBSTITUTION_TABLE)   # Step 2
    result = result[:MAX_TRACK_ID_LENGTH]            # Step 3  (no-op here since len ≤ 64)
    return result
