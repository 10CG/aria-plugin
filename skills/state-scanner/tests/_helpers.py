"""Test fixture factory helpers — stdlib-only.

Provides `make_git_repo()` and `make_fake_project()` context managers
that build on-disk throwaway repos for collector integration tests.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

# Ensure collectors package is importable when tests are run directly.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command inside `repo` with deterministic identity."""
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        }
    )
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        check=check,
    )


def init_git_repo(root: Path, branch: str = "master") -> Path:
    """Initialize a git repo at `root` with an initial empty commit on `branch`."""
    root.mkdir(parents=True, exist_ok=True)
    run_git(root, "init", "-q", f"--initial-branch={branch}")
    (root / "README.md").write_text("# test\n", encoding="utf-8")
    run_git(root, "add", "README.md")
    run_git(root, "commit", "-q", "-m", "initial")
    return root


@contextmanager
def tmp_repo(branch: str = "master") -> Iterator[Path]:
    """Yield a temporary git repo. Cleans up on exit."""
    with tempfile.TemporaryDirectory(prefix="ss-test-") as tmp:
        yield init_git_repo(Path(tmp), branch=branch)


@contextmanager
def tmp_project() -> Iterator[Path]:
    """Yield a tempdir without git — for pure-file collector tests."""
    with tempfile.TemporaryDirectory(prefix="ss-proj-") as tmp:
        yield Path(tmp)


def write_file(path: Path, content: str) -> Path:
    """Write `content` to `path` creating parents; return path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def make_openspec(root: Path, specs: list[tuple[str, str]] | None = None) -> Path:
    """Create an `openspec/` dir with the given (spec_id, status) pairs.

    Each spec becomes `openspec/changes/<id>/proposal.md` with a standard header.
    """
    specs = specs or []
    for spec_id, status in specs:
        write_file(
            root / "openspec" / "changes" / spec_id / "proposal.md",
            f"# {spec_id}\n\n> **Status**: {status}\n\n## Why\ntest\n",
        )
    (root / "openspec" / "archive").mkdir(parents=True, exist_ok=True)
    return root / "openspec"


def make_audit_report(
    root: Path,
    checkpoint: str,
    verdict: str,
    converged: bool = True,
    timestamp: str = "2026-04-24T1000Z",
    spec_id: str = "test-spec",
) -> Path:
    """Create a fake audit report in `.aria/audit-reports/`."""
    name = f"{checkpoint}-R1-{timestamp}-{spec_id}.md"
    return write_file(
        root / ".aria" / "audit-reports" / name,
        f"---\ncheckpoint: {checkpoint}\nverdict: {verdict}\nconverged: {str(converged).lower()}\ntimestamp: {timestamp}\n---\n\n# audit\n",
    )


def make_config(root: Path, config: dict[str, Any]) -> Path:
    """Write `.aria/config.json`."""
    import json

    return write_file(
        root / ".aria" / "config.json", json.dumps(config, indent=2) + "\n"
    )


def make_state_checks(root: Path, yaml_content: str) -> Path:
    """Write `.aria/state-checks.yaml`."""
    return write_file(root / ".aria" / "state-checks.yaml", yaml_content)
