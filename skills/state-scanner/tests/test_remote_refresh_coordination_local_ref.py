"""aria-plugin#197 — Fetch 2 must advance the LOCAL `refs/aria/coordination`.

Before the fix, Fetch 2 ran `git fetch origin --no-tags refs/aria/coordination`
(source only, no destination). git then writes ONLY `FETCH_HEAD`: the local ref
never moves, yet the leg reported `coordination_ref_present=True`, so the
documented freshness predicate (`coordination_fetch.success AND
coordination_ref_present`, references/layer-l-integration.md) passed on a local
view that was days old (2026-09-12: 7 commits / 3 days behind origin). Readers of
the local ref — `--heartbeat-only` (no fetch of its own) and humans running
`git show refs/aria/coordination:...` — then act on stale claims.

These tests drive REAL git against a local bare remote (no `_run` mock): the bug
is exactly a mismatch between what git does and what the collector believes, so
mocking git away would hide it.

Cases (old code → new code):
  remote ahead of local      RED → local fast-forwarded, present=True
  local ref absent           RED → local created,        present=True
  local ahead of remote      RED → local NOT clobbered,  present=None + non_ff
  diverged                   RED → local NOT clobbered,  present=None + non_ff
  already equal              guard (green on both)
  remote ref absent          guard (benign-absent path must stay benign)

Run: PYTHONPATH="<state-scanner>/tests:<state-scanner>/scripts" \
     python3 -m unittest tests.test_remote_refresh_coordination_local_ref
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from collectors import remote_refresh  # noqa: E402
from collectors.coordination_fetch import COORDINATION_REF  # noqa: E402

# Isolate from the host's git config (a host-level setting must not decide the
# outcome) and give commit-tree a fixed identity.
_HERMETIC_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, **_HERMETIC_ENV, "LC_ALL": "C"}
    r = subprocess.run(
        ["git", *args], cwd=cwd, env=env, input="", capture_output=True, text=True
    )
    if r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed (rc={r.returncode}): {r.stderr}")
    return r.stdout.strip()


def _rev(cwd: Path, ref: str) -> str | None:
    env = {**os.environ, **_HERMETIC_ENV}
    r = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref],
        cwd=cwd, env=env, input="", capture_output=True, text=True,
    )
    return r.stdout.strip() or None


class _Fixture:
    """bare `remote.git` + `seed` (writes the remote) + `work` (repo under test)."""

    def __init__(self, root: Path):
        self.remote = root / "remote.git"
        self.seed = root / "seed"
        self.work = root / "work"
        _git(root, "init", "-q", "--bare", str(self.remote))
        self.seed.mkdir()
        _git(self.seed, "init", "-q")
        _git(self.seed, "commit", "-q", "--allow-empty", "-m", "base")
        # Fetch 1 needs at least one branch head on the remote.
        _git(self.seed, "push", "-q", str(self.remote), "HEAD:refs/heads/master")
        self.work.mkdir()
        _git(self.work, "init", "-q")
        _git(self.work, "remote", "add", "origin", str(self.remote))

    @staticmethod
    def _commit(repo: Path, msg: str, parent: str | None = None) -> str:
        tree = _git(repo, "hash-object", "-t", "tree", "-w", "--stdin")
        args = ["commit-tree", tree, "-m", msg]
        if parent:
            args += ["-p", parent]
        return _git(repo, *args)

    def push_remote(self, msg: str, parent: str | None = None) -> str:
        sha = self._commit(self.seed, msg, parent)
        _git(self.seed, "push", "-q", "-f", str(self.remote), f"{sha}:{COORDINATION_REF}")
        return sha

    def pull_local_directly(self) -> None:
        """Set up the local ref to match the remote WITHOUT going through the collector."""
        _git(self.work, "fetch", "-q", "origin", f"{COORDINATION_REF}:{COORDINATION_REF}")

    def commit_local(self, msg: str) -> str:
        parent = _rev(self.work, COORDINATION_REF)
        sha = self._commit(self.work, msg, parent)
        _git(self.work, "update-ref", COORDINATION_REF, sha)
        return sha

    def delete_remote_ref(self) -> None:
        _git(self.remote, "update-ref", "-d", COORDINATION_REF)

    def local(self) -> str | None:
        return _rev(self.work, COORDINATION_REF)

    def run_leg(self):
        leg = remote_refresh._Leg(
            repo=".",
            remote="origin",
            repo_dir=self.work,
            prior_fetched_at=None,
            prior_generation_fetched=None,
            prior_consecutive_unverified=0,
            run_coordination_fetch=True,
        )
        with mock.patch.dict(os.environ, _HERMETIC_ENV):
            return remote_refresh._do_fetch_leg(leg, 30)


class TestFetch2AdvancesLocalCoordinationRef(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ss-197-")
        self.fx = _Fixture(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_remote_ahead_fast_forwards_local_ref(self):
        c1 = self.fx.push_remote("c1")
        self.fx.pull_local_directly()
        c2 = self.fx.push_remote("c2", parent=c1)
        self.assertEqual(self.fx.local(), c1)  # precondition: local is behind

        out = self.fx.run_leg()

        self.assertEqual(out.fetch_ok, "true")
        self.assertEqual(self.fx.local(), c2, "local coordination ref must be fast-forwarded")
        self.assertIs(out.coordination_ref_present, True)
        self.assertIsNone(out.coordination_soft_error)

    def test_absent_local_ref_is_created(self):
        c1 = self.fx.push_remote("c1")
        self.assertIsNone(self.fx.local())  # precondition

        out = self.fx.run_leg()

        self.assertEqual(self.fx.local(), c1)
        self.assertIs(out.coordination_ref_present, True)
        self.assertIsNone(out.coordination_soft_error)

    def test_local_ahead_is_not_clobbered_and_not_reported_fresh(self):
        self.fx.push_remote("c1")
        self.fx.pull_local_directly()
        mine = self.fx.commit_local("unpushed local claim")

        out = self.fx.run_leg()

        self.assertEqual(self.fx.local(), mine, "local-only claim commit must survive")
        self.assertIsNone(
            out.coordination_ref_present,
            "a local view that could not be brought level with the remote is NOT verified fresh",
        )
        self.assertEqual(out.coordination_soft_error, "non_ff")
        self.assertEqual(out.fetch_ok, "true")  # Fetch 1 (branch heads) is unaffected

    def test_diverged_is_not_clobbered_and_not_reported_fresh(self):
        c1 = self.fx.push_remote("c1")
        self.fx.pull_local_directly()
        mine = self.fx.commit_local("unpushed local claim")
        self.fx.push_remote("someone else's claim", parent=c1)

        out = self.fx.run_leg()

        self.assertEqual(self.fx.local(), mine)
        self.assertIsNone(out.coordination_ref_present)
        self.assertEqual(out.coordination_soft_error, "non_ff")

    def test_already_equal_stays_quiet(self):
        c1 = self.fx.push_remote("c1")
        self.fx.pull_local_directly()

        out = self.fx.run_leg()

        self.assertEqual(self.fx.local(), c1)
        self.assertIs(out.coordination_ref_present, True)
        self.assertIsNone(out.coordination_soft_error)

    def test_remote_ref_absent_stays_benign(self):
        self.fx.push_remote("c1")
        self.fx.pull_local_directly()
        self.fx.delete_remote_ref()

        out = self.fx.run_leg()

        self.assertIs(out.coordination_ref_present, False)
        self.assertIsNone(out.coordination_soft_error)
        self.assertEqual(out.fetch_ok, "true")


if __name__ == "__main__":
    unittest.main()
