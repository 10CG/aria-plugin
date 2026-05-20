"""Tests for collectors._common subprocess wrapper (_run).

Primary coverage target: #61 fix (Windows CJK locale crash). The `_run` wrapper
must produce UTF-8-decoded stdout regardless of OS locale, never raising
UnicodeDecodeError to the caller.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

from collectors._common import _run


class TestRunUtf8Encoding(unittest.TestCase):
    """#61 regression — _run must use UTF-8 + errors='replace'."""

    def test_utf8_cjk_roundtrip(self):
        # CJK characters must survive subprocess roundtrip (the original
        # crash was on git log output containing Chinese commit messages).
        rc, stdout, stderr = _run(
            [sys.executable, "-c", "print('中文测试')"], Path(".")
        )
        self.assertEqual(rc, 0)
        self.assertIn("中文测试", stdout)
        self.assertEqual(stderr, "")

    def test_utf8_emoji_roundtrip(self):
        # Emoji must survive (aria-standards git-commit.md 双语规范 allows
        # emoji in commit subjects).
        rc, stdout, _ = _run(
            [sys.executable, "-c", "print('feat: ship 🚀')"], Path(".")
        )
        self.assertEqual(rc, 0)
        self.assertIn("🚀", stdout)

    def test_utf8_mixed_ascii_cjk_emoji(self):
        # Realistic git log subject form
        rc, stdout, _ = _run(
            [
                sys.executable,
                "-c",
                "print('feat(deploy): 部署 M5 carryover ✅')",
            ],
            Path("."),
        )
        self.assertEqual(rc, 0)
        self.assertIn("部署", stdout)
        self.assertIn("✅", stdout)
        self.assertIn("feat(deploy)", stdout)

    def test_nonzero_exit_still_returns_cleanly(self):
        # Existing contract: non-zero rc must NOT raise
        rc, _, stderr = _run(
            [sys.executable, "-c", "import sys; sys.exit(7)"], Path(".")
        )
        self.assertEqual(rc, 7)

    def test_invalid_bytes_handled_via_errors_replace(self):
        # If a subprocess somehow emits non-UTF-8 bytes (legacy tooling),
        # errors="replace" must soften — no exception escapes _run.
        rc, stdout, _ = _run(
            [
                sys.executable,
                "-c",
                # Write raw bytes that are NOT valid UTF-8 to stdout (0xff is
                # an invalid UTF-8 start byte). With errors='replace' the
                # subprocess wrapper substitutes U+FFFD.
                "import sys; sys.stdout.buffer.write(b'\\xff\\xfeOK\\n')",
            ],
            Path("."),
        )
        self.assertEqual(rc, 0)
        # Both bytes 0xff and 0xfe replaced with U+FFFD (replacement char);
        # "OK" survives as-is
        self.assertIn("OK", stdout)
        # Critical invariant: no UnicodeDecodeError raised — we got here

    def test_command_not_found_returns_127(self):
        # Existing contract preserved
        rc, _, stderr = _run(
            ["this-command-definitely-does-not-exist-xyz123"], Path(".")
        )
        self.assertEqual(rc, 127)
        self.assertIn("command not found", stderr)


if __name__ == "__main__":
    unittest.main()
