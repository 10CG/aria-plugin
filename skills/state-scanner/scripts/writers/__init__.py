"""writers — derived-artifact writers for state-scanner (v1.22.x+).

Writers produce machine-generated files from snapshot data.  They are
*not* called by scan.py (the collector/snapshot pipeline); they are
invoked by phase-d-closer D.3 after a session handoff decision has been
made.

Public exports:
    latest_md_writer.write_latest_md  — writes docs/handoff/latest.md
"""

from .latest_md_writer import write_latest_md

__all__ = ["write_latest_md"]
