#!/usr/bin/env python3
"""``get_container_label()`` accessor + S1 lock-in for ``get_container_id()``.

owner-container-identity-key-and-collision-parser TASK-008 (SC-3, S1 arm).

S1 ships the read-only label accessor WITHOUT flipping ``get_container_id()``
(label still wins) — flipping early would silently turn a1-entry's SC-3
("calling get_container_id() directly must be red") permanently green.  The
lock-in below is what S2-1 (TASK-027, reserved) later inverts.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SS_ROOT = Path(__file__).resolve().parent.parent
if str(_SS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SS_ROOT))

from lib.identity import get_container_id, get_container_label  # noqa: E402  (RED on 7dd0135: ImportError)


def _write(home: Path, uuid: str, label: str) -> None:
    d = home / ".aria"
    d.mkdir(parents=True, exist_ok=True)
    (d / "container-id").write_text(
        "# Aria container identity (auto-generated 2026-09-06T00:00:00Z)\n"
        f"uuid: {uuid}\nlabel: {label}\ncreated_at: 2026-09-06T00:00:00Z\n",
        encoding="utf-8",
    )


class TestContainerLabelAccessor(unittest.TestCase):
    def test_label_returned_when_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write(home, "aaaa1111", "devbox-A")
            self.assertEqual(get_container_label(home_dir=home), "devbox-A")

    def test_empty_label_returns_empty_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write(home, "aaaa1111", "")
            self.assertEqual(get_container_label(home_dir=home), "")

    def test_missing_file_returns_empty_and_does_not_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(get_container_label(home_dir=home), "")
            self.assertFalse((home / ".aria" / "container-id").exists(), "accessor must be read-only")

    def test_corrupt_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".aria").mkdir()
            (home / ".aria" / "container-id").write_text("garbage without uuid\n", encoding="utf-8")
            self.assertEqual(get_container_label(home_dir=home), "")


class TestS1LockIn(unittest.TestCase):
    """SC-3 (仅 S1): ``get_container_id()`` STILL returns the label when set."""

    def test_get_container_id_still_prefers_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write(home, "aaaa1111", "devbox-A")
            self.assertEqual(get_container_id(home_dir=home), "devbox-A")
            self.assertEqual(get_container_label(home_dir=home), "devbox-A")

    def test_get_container_id_returns_uuid_when_label_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write(home, "aaaa1111", "")
            self.assertEqual(get_container_id(home_dir=home), "aaaa1111")


if __name__ == "__main__":
    unittest.main()
