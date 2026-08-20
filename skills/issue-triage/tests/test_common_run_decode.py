"""aria-plugin #147 — `_common._run` must survive undecodable subprocess bytes.

`_run` uses ``text=True`` (subprocess decodes stdout/stderr itself). Decode
failure raises ``UnicodeDecodeError`` — a **ValueError**, not an OSError —
so the pre-#147 ``except (TimeoutExpired, FileNotFoundError)`` pair let it
escape straight through every collector. #147 fixed the call site with
``errors="replace"`` (decode never raises; invalid bytes become U+FFFD).

These are live-subprocess tests (no monkeypatching — the decode path IS the
subject under test). They emit only fixed fake bytes; Rule #7 unaffected.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from collectors._common import _run  # noqa: E402


class TestRunSurvivesUndecodableBytes:
    def test_invalid_utf8_stdout_does_not_raise(self) -> None:
        """printf '\\xff\\xfe' is undecodable UTF-8 — pre-#147 this raised
        UnicodeDecodeError out of _run; post-#147 it must return normally."""
        rc, out, err = _run(["printf", r"\xff\xfe"], cwd=Path("."))
        assert rc == 0
        assert "�" in out, "invalid bytes must decode to U+FFFD via errors='replace'"

    def test_replacement_output_is_json_safe(self) -> None:
        """U+FFFD (unlike surrogateescape's lone surrogates) must survive
        json.dumps — the collectors serialize _run output into the report."""
        import json

        rc, out, err = _run(["printf", r"\xff"], cwd=Path("."))
        assert rc == 0
        json.dumps({"stdout": out, "stderr": err})  # must not raise

    def test_clean_utf8_unaffected(self) -> None:
        rc, out, err = _run(["printf", "plain ascii ok"], cwd=Path("."))
        assert rc == 0
        assert out == "plain ascii ok"
