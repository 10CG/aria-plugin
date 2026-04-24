"""state-scanner scan.py test suite.

Design decision (T6.1): stdlib `unittest` not pytest.

Rationale:
- scan.py itself is stdlib-only by Spec constraint (proposal.md §Constraints)
- Tests should match the deploy-target constraint: if a CI box can run scan.py
  it must be able to run the tests too
- Current target environments (Aria dev containers, Aether light nodes) lack pip
  and do not have pytest pre-installed
- unittest is in Python 3.11+ stdlib → zero dependency

Run all tests:
    python3 -m unittest discover -s aria/skills/state-scanner/tests -v

Run with coverage (stdlib trace):
    python3 tests/run_tests.py --coverage
"""
