#!/usr/bin/env python3
"""Stdlib test runner with optional coverage report.

Usage:
    python3 tests/run_tests.py              # run all tests
    python3 tests/run_tests.py --coverage   # run with coverage via stdlib trace
    python3 tests/run_tests.py test_git     # run a single module

Coverage mode uses the stdlib `trace` module (no pytest-cov / coverage.py).
Output is a per-collector line-hit summary printed after the unittest run.
"""

from __future__ import annotations

import argparse
import sys
import trace
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
COLLECTORS_DIR = TESTS_DIR.parent / "scripts" / "collectors"


def _discover(pattern: str | None) -> unittest.TestSuite:
    loader = unittest.TestLoader()
    if pattern:
        if not pattern.startswith("test_"):
            pattern = f"test_{pattern}"
        return loader.discover(str(TESTS_DIR), pattern=f"{pattern}.py")
    return loader.discover(str(TESTS_DIR), pattern="test_*.py")


def _run_plain(pattern: str | None, verbosity: int) -> int:
    suite = _discover(pattern)
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


def _run_coverage(pattern: str | None, verbosity: int) -> int:
    tracer = trace.Trace(
        count=True,
        trace=False,
        ignoredirs=[sys.prefix, sys.exec_prefix],
        ignoremods=["unittest", "trace", "subprocess", "_helpers"],
    )

    def _runit() -> int:
        return _run_plain(pattern, verbosity)

    exit_code = tracer.runfunc(_runit)

    results = tracer.results()
    counts = results.counts

    print("\n" + "=" * 70)
    print("COVERAGE (lines hit per collector)")
    print("=" * 70)

    collectors = sorted(COLLECTORS_DIR.glob("*.py"))
    for cf in collectors:
        if cf.name.startswith("_") or cf.name == "__init__.py":
            continue
        total_lines = sum(
            1
            for ln in cf.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        )
        hit = sum(1 for (fn, _lineno), _c in counts.items() if fn == str(cf))
        pct = (hit / total_lines * 100) if total_lines else 0
        bar = "█" * int(pct // 5) + "·" * (20 - int(pct // 5))
        print(f"  {cf.stem:<22} {bar} {pct:5.1f}% ({hit}/{total_lines})")

    return exit_code


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("pattern", nargs="?", help="single test module (e.g. git)")
    p.add_argument("--coverage", action="store_true", help="enable stdlib trace coverage")
    p.add_argument("-v", "--verbose", action="count", default=1)
    args = p.parse_args(argv)
    if args.coverage:
        return _run_coverage(args.pattern, args.verbose)
    return _run_plain(args.pattern, args.verbose)


if __name__ == "__main__":
    sys.exit(main())
