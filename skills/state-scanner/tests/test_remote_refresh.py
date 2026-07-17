"""P3 (main spec state-scanner-stale-refs-false-parity, F3′) — remote_refresh
collector tests.

Covers the blueprint's P3 red-test pair (R5-C-C: per-host limiting + deadline
three-state + anti-starvation) RE-SCOPED to what `remote_refresh` itself owns —
it produces `fetched_at`/`fetch_ok`/generation bookkeeping, NOT `overall_parity`
(that verdict is F1′/F4′'s job in `multi_remote.py`, wired in a later increment):

  - health fixture: 8 legs / 2 hosts — none get spuriously cut when the deadline
    is generous; when a budget DOES cut some, the cut legs' prior `fetched_at` is
    preserved (not reset to null) — "被砍腿不拖倒它已有的证据".
  - fault fixture (b1): a failed fetch never manufactures false freshness —
    `fetched_at` stays at its (possibly very stale) prior value.
  - fault fixture (b2): anti-starvation — across N sequential scan rounds with a
    tight per-round budget, every leg gets fetched at least once within
    ⌈total/budget⌉ rounds. A fixed/declaration-order (FIFO) scheduler would fail
    this (the same head legs win every round; the tail never advances).
  - budget-seam convergence: the `ARIA_SCAN_FETCH_BUDGET` test seam and a
    monotonic-clock-driven "real" deadline cut produce IDENTICAL dispatched/
    skipped shapes, proving both trigger sources funnel through the same
    `_should_stop_admitting` → shutdown → cache-writeback path.
  - Rule #7: a credential embedded in a remote URL (both the get-url output and a
    failed fetch's stderr) never survives into any output field.
  - `per_host_fetch_limit=0` (and other bad config values) clamp to >=1 instead
    of crashing (`ThreadPoolExecutor(max_workers=0)` raises `ValueError`).

Run: PYTHONPATH="<state-scanner>/tests:<state-scanner>/scripts" \
     python3 -m unittest tests.test_remote_refresh
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from _helpers import make_config, tmp_repo, write_file  # noqa: E402

from collectors import _common  # noqa: E402
from collectors import multi_remote  # noqa: E402
from collectors import remote_refresh  # noqa: E402
from collectors.remote_refresh import (  # noqa: E402
    _leg_key,
    _should_stop_admitting,
    collect_remote_refresh,
)


def _make_run(table):
    def fake(cmd, cwd, timeout=5):
        key = tuple(cmd)
        if key in table:
            return table[key]
        return (1, "", f"unmocked: {' '.join(cmd)}")

    return fake


class _AllRunPatched:
    """Patches `_run` everywhere `remote_refresh`'s call graph reaches it:
    `remote_refresh._run` (Fetch 1 / Fetch 2), `multi_remote._run` (`_list_remotes`),
    and `_common._run` (`resolve_remote_host`'s internal `git remote get-url`).
    `git._run` is deliberately NOT patched — no `.gitmodules` exists in these
    fixtures, so `_enumerate_submodule_paths` short-circuits before calling it.
    """

    def __init__(self, table):
        self._fn = _make_run(table)
        self._patches = []

    def __enter__(self):
        for target in (remote_refresh, multi_remote, _common):
            p = mock.patch.object(target, "_run", side_effect=self._fn)
            p.start()
            self._patches.append(p)
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


def _fetch1_cmd(remote: str) -> tuple:
    return ("git", "fetch", remote, "--no-tags", "--prune", f"+refs/heads/*:refs/remotes/{remote}/*")


def _fetch2_cmd(remote: str) -> tuple:
    return ("git", "fetch", remote, "--no-tags", "refs/aria/coordination")


def _remotes_cmd() -> tuple:
    return ("git", "remote")


def _get_url_cmd(remote: str) -> tuple:
    return ("git", "remote", "get-url", remote)


def _n_remote_names(n: int) -> list[str]:
    return [f"r{i}" for i in range(n)]


def _build_table_for_remotes(
    remotes: list[str], host_of: dict, fetch1_ok: bool = True, coord_ok: bool = True
) -> dict:
    table = {_remotes_cmd(): (0, "\n".join(remotes) + "\n", "")}
    for remote in remotes:
        table[_get_url_cmd(remote)] = (0, f"https://{host_of[remote]}/x/{remote}.git\n", "")
        if fetch1_ok:
            table[_fetch1_cmd(remote)] = (0, "", "")
        else:
            table[_fetch1_cmd(remote)] = (1, "", "fatal: could not read from remote")
        if remote == "origin":
            if coord_ok:
                table[_fetch2_cmd(remote)] = (0, "", "")
            else:
                table[_fetch2_cmd(remote)] = (
                    128,
                    "",
                    "fatal: couldn't find remote ref refs/aria/coordination",
                )
    return table


class TestShouldStopAdmittingPredicate(unittest.TestCase):
    """Pure-function truth table for the shared stop-admitting gate."""

    def test_budget_none_uses_elapsed(self):
        self.assertFalse(_should_stop_admitting(3, 1.0, 15.0, None))
        self.assertTrue(_should_stop_admitting(3, 15.0, 15.0, None))
        self.assertTrue(_should_stop_admitting(3, 16.0, 15.0, None))

    def test_budget_set_ignores_elapsed(self):
        # elapsed is huge but budget governs — real clock is irrelevant once a
        # budget override is present (test seam replaces the trigger source).
        self.assertFalse(_should_stop_admitting(2, 999.0, 15.0, 3))
        self.assertTrue(_should_stop_admitting(3, 0.0, 15.0, 3))
        self.assertTrue(_should_stop_admitting(4, 0.0, 15.0, 3))


class TestPerHostLimitClamp(unittest.TestCase):
    def test_zero_clamps_to_one_and_does_not_crash(self):
        with tmp_repo() as repo:
            make_config(
                repo,
                {
                    "state_scanner": {
                        "multi_remote": {
                            "enforced_remotes": ["origin"],
                            "per_host_fetch_limit": 0,
                        }
                    }
                },
            )
            table = _build_table_for_remotes(["origin"], {"origin": "example.com"})
            with _AllRunPatched(table):
                result = collect_remote_refresh(repo)
        self.assertEqual(len(result.data["legs"]), 1)
        self.assertEqual(result.data["legs"][0]["fetch_ok"], "true")

    def test_negative_and_non_numeric_also_clamp(self):
        for bad in (-5, "not-a-number", None):
            with tmp_repo() as repo:
                make_config(
                    repo,
                    {
                        "state_scanner": {
                            "multi_remote": {
                                "enforced_remotes": ["origin"],
                                "per_host_fetch_limit": bad,
                            }
                        }
                    },
                )
                table = _build_table_for_remotes(["origin"], {"origin": "example.com"})
                with _AllRunPatched(table):
                    result = collect_remote_refresh(repo)
            self.assertEqual(result.data["legs"][0]["fetch_ok"], "true", bad)


class TestPruneAndTwoFetch(unittest.TestCase):
    def test_fetch1_carries_prune_flag(self):
        # Implicit but load-bearing: `_make_run`'s exact-tuple match means a
        # missing `--prune` would make Fetch 1 land on the "unmocked" fallback
        # (rc=1) instead of the mocked success — this assertion makes that
        # implicit contract explicit.
        with tmp_repo() as repo:
            make_config(repo, {"state_scanner": {"multi_remote": {"enforced_remotes": ["origin"]}}})
            table = _build_table_for_remotes(["origin"], {"origin": "example.com"})
            with _AllRunPatched(table):
                result = collect_remote_refresh(repo)
        self.assertEqual(result.data["legs"][0]["fetch_ok"], "true")

    def test_coordination_fetch_only_on_main_origin_leg(self):
        with tmp_repo() as repo:
            make_config(
                repo,
                {"state_scanner": {"multi_remote": {"enforced_remotes": ["origin", "github"]}}},
            )
            table = _build_table_for_remotes(
                ["origin", "github"], {"origin": "forgejo.example", "github": "github.com"}
            )
            call_log = []
            real_fake = _make_run(table)

            def spy(cmd, cwd, timeout=5):
                call_log.append(tuple(cmd))
                return real_fake(cmd, cwd, timeout)

            with mock.patch.object(remote_refresh, "_run", side_effect=spy), mock.patch.object(
                multi_remote, "_run", side_effect=_make_run(table)
            ), mock.patch.object(_common, "_run", side_effect=_make_run(table)):
                result = collect_remote_refresh(repo)

            origin_leg = next(l for l in result.data["legs"] if l["remote"] == "origin")
            github_leg = next(l for l in result.data["legs"] if l["remote"] == "github")
            self.assertIsNotNone(origin_leg["coordination_ref_present"])
            self.assertIsNone(github_leg["coordination_ref_present"])
            self.assertEqual(call_log.count(_fetch1_cmd("origin")), 1)
            self.assertEqual(call_log.count(_fetch2_cmd("origin")), 1)
            self.assertEqual(call_log.count(_fetch1_cmd("github")), 1)
            # github must NEVER attempt Fetch 2 (tasks 3.15 backend m-2)
            self.assertNotIn(_fetch2_cmd("github"), call_log)

    def test_benign_absent_coordination_ref_does_not_fail_the_leg(self):
        with tmp_repo() as repo:
            make_config(repo, {"state_scanner": {"multi_remote": {"enforced_remotes": ["origin"]}}})
            table = _build_table_for_remotes(["origin"], {"origin": "example.com"}, coord_ok=False)
            with _AllRunPatched(table):
                result = collect_remote_refresh(repo)
        leg = result.data["legs"][0]
        self.assertEqual(leg["fetch_ok"], "true")
        self.assertFalse(leg["coordination_ref_present"])


class TestHealthRotationFixture(unittest.TestCase):
    """P3 health fixture: 8 legs / 2 hosts, 4 each."""

    def _setup(self, repo):
        remotes = _n_remote_names(8)
        host_of = {r: ("hostA.example" if i % 2 == 0 else "hostB.example") for i, r in enumerate(remotes)}
        make_config(repo, {"state_scanner": {"multi_remote": {"enforced_remotes": remotes}}})
        return remotes, host_of

    def test_generous_deadline_no_legs_cut(self):
        with tmp_repo() as repo:
            remotes, host_of = self._setup(repo)
            table = _build_table_for_remotes(remotes, host_of)
            with _AllRunPatched(table):
                result = collect_remote_refresh(repo)
        self.assertEqual(len(result.data["legs"]), 8)
        self.assertEqual(result.data["skipped_count"], 0)
        for leg in result.data["legs"]:
            self.assertEqual(leg["fetch_ok"], "true")

    def test_budget_cut_legs_preserve_prior_fetched_at(self):
        """Legs the scheduler never gets to keep whatever fetched_at they already
        had — being cut this round must not erase existing evidence."""
        with tmp_repo() as repo:
            remotes, host_of = self._setup(repo)
            # Pre-seed the cache: all 8 legs already fetched "recently" in a prior
            # round, at DIFFERENT generations so ordering is deterministic (r0
            # oldest .. r7 newest — the 4 oldest get re-dispatched first).
            cache_legs = {}
            for i, r in enumerate(remotes):
                cache_legs[_leg_key(".", r)] = {
                    "fetched_at": f"2026-07-1{i}T00:00:00+00:00",
                    "fetch_ok": "true",
                    "error_kind": None,
                    "generation_fetched": 1,
                    "consecutive_unverified": 0,
                    "coordination_ref_present": True if r == "origin" else None,
                }
            write_file(
                repo / ".aria" / "cache" / "remote-refresh.json",
                json.dumps({"scan_generation": 1, "legs": cache_legs}),
            )
            table = _build_table_for_remotes(remotes, host_of)
            with mock.patch.object(remote_refresh, "fetch_budget_override", return_value=4):
                with _AllRunPatched(table):
                    result = collect_remote_refresh(repo)

        self.assertEqual(result.data["skipped_count"], 4)
        by_remote = {leg["remote"]: leg for leg in result.data["legs"]}
        cut = [leg for leg in result.data["legs"] if leg["fetch_ok"] == "not_attempted"]
        self.assertEqual(len(cut), 4)
        for leg in cut:
            # not_attempted legs must retain their prior fetched_at — being cut
            # this round does not erase existing evidence.
            self.assertIsNotNone(leg["fetched_at"])
        dispatched = [leg for leg in result.data["legs"] if leg["fetch_ok"] == "true"]
        self.assertEqual(len(dispatched), 4)
        # anti-starvation: the 4 OLDEST (r0..r3) are the ones re-dispatched.
        self.assertEqual({leg["remote"] for leg in dispatched}, {"r0", "r1", "r2", "r3"})
        self.assertEqual({leg["remote"] for leg in cut}, {"r4", "r5", "r6", "r7"})
        del by_remote  # unused beyond sanity — kept for readability of intent


class TestExpiredHonesty(unittest.TestCase):
    """Fault fixture (b1): a failed fetch never manufactures false freshness."""

    def test_failed_fetch_keeps_stale_fetched_at_honest(self):
        with tmp_repo() as repo:
            make_config(repo, {"state_scanner": {"multi_remote": {"enforced_remotes": ["origin"]}}})
            write_file(
                repo / ".aria" / "cache" / "remote-refresh.json",
                json.dumps(
                    {
                        "scan_generation": 3,
                        "legs": {
                            _leg_key(".", "origin"): {
                                "fetched_at": "2026-07-09T00:00:00+00:00",  # 8 days stale
                                "fetch_ok": "true",
                                "error_kind": None,
                                "generation_fetched": 3,
                                "consecutive_unverified": 0,
                                "coordination_ref_present": True,
                            }
                        },
                    }
                ),
            )
            table = _build_table_for_remotes(["origin"], {"origin": "example.com"}, fetch1_ok=False)
            with _AllRunPatched(table):
                result = collect_remote_refresh(repo)

        leg = result.data["legs"][0]
        self.assertEqual(leg["fetch_ok"], "false")
        self.assertEqual(leg["fetched_at"], "2026-07-09T00:00:00+00:00")  # unchanged, not advanced
        self.assertEqual(leg["generation_fetched"], 3)  # unchanged too


class TestConsecutiveUnverified(unittest.TestCase):
    """D18 counter is owned HERE (fetch_ok-driven), not F1′/F4′: reset to 0 on a
    leg's own true fetch, +1 on any non-true ONLINE outcome (failed / deadline-cut),
    frozen offline. Regression guard: it used to be a dead pass-through, so the D18
    exemption-expiry guard in _exemption_eligible silently never fired."""

    def _preseed(self, repo, prior_cu, gen=3):
        write_file(
            repo / ".aria" / "cache" / "remote-refresh.json",
            json.dumps({"scan_generation": gen, "legs": {
                _leg_key(".", "origin"): {
                    "fetched_at": "2026-07-16T00:00:00+00:00",
                    "fetch_ok": "true", "error_kind": None,
                    "generation_fetched": gen, "consecutive_unverified": prior_cu,
                    "coordination_ref_present": True,
                }}}),
        )

    def _cfg(self, repo):
        make_config(repo, {"state_scanner": {"multi_remote": {"enforced_remotes": ["origin"]}}})

    def test_true_fetch_resets_to_zero(self):
        with tmp_repo() as repo:
            self._cfg(repo)
            self._preseed(repo, prior_cu=2)
            with _AllRunPatched(_build_table_for_remotes(["origin"], {"origin": "example.com"})):
                result = collect_remote_refresh(repo)
        leg = result.data["legs"][0]
        self.assertEqual(leg["fetch_ok"], "true")
        self.assertEqual(leg["consecutive_unverified"], 0)

    def test_failed_fetch_increments(self):
        with tmp_repo() as repo:
            self._cfg(repo)
            self._preseed(repo, prior_cu=2)
            table = _build_table_for_remotes(["origin"], {"origin": "example.com"}, fetch1_ok=False)
            with _AllRunPatched(table):
                result = collect_remote_refresh(repo)
        leg = result.data["legs"][0]
        self.assertEqual(leg["fetch_ok"], "false")
        self.assertEqual(leg["consecutive_unverified"], 3)  # 2 + 1

    def test_offline_freezes_counter(self):
        with tmp_repo() as repo:
            self._cfg(repo)
            self._preseed(repo, prior_cu=2)
            # offline skips the network FETCH but still enumerates remotes + resolves
            # hosts locally (git remote / get-url), so those local calls still need
            # the mock table; the fetch entries in it are simply never invoked.
            table = _build_table_for_remotes(["origin"], {"origin": "example.com"})
            with mock.patch.object(remote_refresh, "is_scan_offline", return_value=True):
                with _AllRunPatched(table):
                    result = collect_remote_refresh(repo)
        leg = result.data["legs"][0]
        self.assertEqual(leg["fetch_ok"], "not_attempted")
        self.assertEqual(leg["consecutive_unverified"], 2)  # frozen, NOT incremented


class TestAntiStarvation(unittest.TestCase):
    """Fault fixture (b2): across N sequential scan rounds with a tight per-round
    budget, every leg is fetched at least once within ⌈total/budget⌉ rounds. A
    fixed/declaration-order (FIFO) scheduler fails this — the same head legs win
    every single round and the tail never advances."""

    def test_all_legs_covered_within_rotation_rounds(self):
        with tmp_repo() as repo:
            remotes = _n_remote_names(6)
            host_of = {r: "example.com" for r in remotes}
            make_config(repo, {"state_scanner": {"multi_remote": {"enforced_remotes": remotes}}})
            table = _build_table_for_remotes(remotes, host_of)

            fetched_ever: set[str] = set()
            rotation_rounds = 2  # ceil(6 / 3)
            with mock.patch.object(remote_refresh, "fetch_budget_override", return_value=3):
                for _round in range(rotation_rounds):
                    with _AllRunPatched(table):
                        result = collect_remote_refresh(repo)
                    round_dispatched = {
                        leg["remote"]
                        for leg in result.data["legs"]
                        if leg["fetch_ok"] == "true"
                    }
                    self.assertEqual(len(round_dispatched), 3)
                    # anti-starvation invariant: no repeats until every leg has
                    # been covered once — a FIFO scheduler would dispatch the
                    # SAME 3 legs both rounds, violating this.
                    self.assertEqual(
                        round_dispatched & fetched_ever,
                        set(),
                        f"round {_round} re-fetched a leg already covered — starvation bug",
                    )
                    fetched_ever |= round_dispatched

        self.assertEqual(fetched_ever, set(remotes))


class TestBudgetSeamConvergence(unittest.TestCase):
    """The `ARIA_SCAN_FETCH_BUDGET` seam and a monotonic-clock-driven deadline
    cut must produce the SAME dispatched/skipped shape — both funnel through
    `_should_stop_admitting` → shutdown → cache-writeback, never two parallel
    implementations (memory
    feedback_noop_in_test_env_hardening_needs_mechanism_assertion)."""

    def _fixture(self):
        remotes = _n_remote_names(6)
        host_of = {r: "example.com" for r in remotes}  # single host: no queuing ambiguity
        table = _build_table_for_remotes(remotes, host_of)
        return remotes, host_of, table

    def test_budget_seam_path(self):
        with tmp_repo() as repo:
            remotes, _host_of, table = self._fixture()
            make_config(repo, {"state_scanner": {"multi_remote": {"enforced_remotes": remotes}}})
            with mock.patch.object(remote_refresh, "fetch_budget_override", return_value=3):
                with _AllRunPatched(table):
                    result = collect_remote_refresh(repo)
        dispatched = sum(1 for leg in result.data["legs"] if leg["fetch_ok"] == "true")
        skipped = result.data["skipped_count"]
        self.assertEqual((dispatched, skipped), (3, 3))

    def test_monotonic_deadline_path_converges_to_same_shape(self):
        """No budget override — the REAL `elapsed >= deadline_seconds` branch is
        exercised, with `time.monotonic` deterministically stepped past the
        deadline exactly at leg index 3 (avoids real-sleep flakiness while still
        driving the production trigger, not a parallel test-only branch)."""
        with tmp_repo() as repo:
            remotes, _host_of, table = self._fixture()
            make_config(
                repo,
                {
                    "state_scanner": {
                        "multi_remote": {
                            "enforced_remotes": remotes,
                            "refresh_deadline_seconds": 15,
                        }
                    }
                },
            )
            # calls: start, leg0, leg1, leg2 (all elapsed=0 -> dispatch),
            # leg3 (elapsed jumps to 100 >= 15 -> stop, break).
            clock_values = iter([100.0, 100.0, 100.0, 100.0, 200.0])
            with mock.patch.object(remote_refresh, "fetch_budget_override", return_value=None):
                with mock.patch.object(
                    remote_refresh.time, "monotonic", side_effect=lambda: next(clock_values)
                ):
                    with _AllRunPatched(table):
                        result = collect_remote_refresh(repo)
        dispatched = sum(1 for leg in result.data["legs"] if leg["fetch_ok"] == "true")
        skipped = result.data["skipped_count"]
        self.assertEqual((dispatched, skipped), (3, 3))
        for leg in result.data["legs"]:
            if leg["fetch_ok"] == "not_attempted":
                self.assertEqual(
                    next(s for s in result.data["skipped_remotes"] if s["remote"] == leg["remote"])[
                        "reason"
                    ],
                    "deadline",
                )


class TestRule7HostCredentialLeak(unittest.TestCase):
    """A credential embedded in a remote URL — via `git remote get-url` output OR
    a failed fetch's stderr — must never survive into ANY output field."""

    def test_credential_never_leaks_via_host_or_error_fields(self):
        with tmp_repo() as repo:
            make_config(repo, {"state_scanner": {"multi_remote": {"enforced_remotes": ["origin"]}}})
            table = {
                _remotes_cmd(): (0, "origin\n", ""),
                _get_url_cmd("origin"): (
                    0,
                    "https://x-token-auth:LEAKTOKEN111@forgejo.example/x/y.git\n",
                    "",
                ),
                _fetch1_cmd("origin"): (
                    1,
                    "",
                    "fatal: unable to access "
                    "'https://x-token-auth:LEAKTOKEN111@forgejo.example/x/y.git/': "
                    "Failed to connect to forgejo.example port 443",
                ),
            }
            with _AllRunPatched(table):
                result = collect_remote_refresh(repo)

        leg = result.data["legs"][0]
        self.assertEqual(leg["host"], "forgejo.example")
        blob = json.dumps(result.data)
        self.assertNotIn("LEAKTOKEN111", blob)
        self.assertNotIn("x-token-auth", blob)
        for err in result.errors:
            self.assertNotIn("LEAKTOKEN111", json.dumps(err))


class TestOfflineFreeze(unittest.TestCase):
    def test_offline_all_not_attempted_and_generation_untouched(self):
        with tmp_repo() as repo:
            make_config(repo, {"state_scanner": {"multi_remote": {"enforced_remotes": ["origin"]}}})
            write_file(
                repo / ".aria" / "cache" / "remote-refresh.json",
                json.dumps(
                    {
                        "scan_generation": 7,
                        "legs": {
                            _leg_key(".", "origin"): {
                                "fetched_at": "2026-07-10T00:00:00+00:00",
                                "fetch_ok": "true",
                                "error_kind": None,
                                "generation_fetched": 7,
                                "consecutive_unverified": 0,
                                "coordination_ref_present": True,
                            }
                        },
                    }
                ),
            )
            table = _build_table_for_remotes(["origin"], {"origin": "example.com"})
            with mock.patch.object(remote_refresh, "is_scan_offline", return_value=True):
                with _AllRunPatched(table):
                    result = collect_remote_refresh(repo)
                    cache_after = json.loads(
                        (repo / ".aria" / "cache" / "remote-refresh.json").read_text()
                    )

        leg = result.data["legs"][0]
        self.assertEqual(leg["fetch_ok"], "not_attempted")
        self.assertEqual(leg["fetched_at"], "2026-07-10T00:00:00+00:00")
        self.assertEqual(leg["scan_generation"], 7)  # not incremented
        self.assertEqual(cache_after["scan_generation"], 7)  # cache untouched


if __name__ == "__main__":
    unittest.main()
