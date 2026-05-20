"""Renderers package for state-scanner.

Provides human-readable board output from snapshot data produced by collectors.

Public API:
    from renderers.track_board import render_track_board
"""

from .track_board import render_track_board

__all__ = ["render_track_board"]
