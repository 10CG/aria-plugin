#!/usr/bin/env python3
# verify_post_push.py — Post-push SHA verification with exponential backoff
#
# Verifies that remote(s) have received the expected commit SHA after push.
# Handles Forgejo/GitHub replication delays (10-30s) via retry with backoff.
#
# Usage:
#   python3 verify_post_push.py \
#     --repo=<path> --branch=<name> --expected-sha=<sha> \
#     [--max-retries=3] [--initial-backoff=2] [--timeout=15] \
#     [--remotes=origin,github]
#
# Output: JSON (see references/schema.md for verify_parity_post_push schema)
#
# Retry schedule (default): [0, 2, 4, 8] seconds before each attempt
# Per-remote time upper bound: 4 attempts x 15s timeout + 14s sleep = 74s (v1.15.1 default)
# Rationale: Forgejo SSH over Cloudflare Access ~8s ls-remote latency (dogfood 2026-04-12).
# For LAN/direct setups, override via --timeout=5 → bound 34s.
#
# Make executable: chmod +x verify_post_push.py

import argparse
import json
import subprocess
import sys
import time


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify remote(s) received expected SHA after push"
    )
    parser.add_argument("--repo", required=True, help="Git repository path")
    parser.add_argument("--branch", required=True, help="Branch name to verify")
    parser.add_argument(
        "--expected-sha", required=True, dest="expected_sha",
        help="Expected commit SHA (snapshot of local HEAD before push)"
    )
    parser.add_argument(
        "--max-retries", type=int, default=3, dest="max_retries",
        help=(
            "Number of retries after initial attempt (default: 3). "
            "IMPORTANT: Total attempts = 1 initial + max_retries, so "
            "max_retries=3 produces 4 attempts (schedule: 0s, 2s, 4s, 8s)."
        )
    )
    parser.add_argument(
        "--initial-backoff", type=float, default=2.0, dest="initial_backoff",
        help="Initial backoff seconds, doubles each retry (default: 2)"
    )
    parser.add_argument(
        "--timeout", type=float, default=15.0,
        help="Timeout per ls-remote call in seconds (default: 15, v1.15.1+)"
    )
    parser.add_argument(
        "--remotes", default="",
        help="Comma-separated remote names (default: all configured remotes)"
    )
    return parser.parse_args()


def get_configured_remotes(repo: str) -> list[str]:
    """Return list of configured remote names, sorted."""
    try:
        result = subprocess.run(
            ["git", "-C", repo, "remote"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return []
        return sorted(r.strip() for r in result.stdout.splitlines() if r.strip())
    except (subprocess.TimeoutExpired, OSError):
        return []


def ls_remote(
    repo: str, remote: str, branch: str, timeout: float
) -> tuple[str | None, str | None]:
    """
    Query remote for branch HEAD SHA via git ls-remote.

    Returns: (sha_or_None, error_reason_or_None)
    - (sha, None)              — success, sha may be None if branch not found
    - (None, "network_timeout") — subprocess.TimeoutExpired
    - (None, "auth_failed")    — returncode 128
    - (None, "error")          — other non-zero returncode
    """
    try:
        result = subprocess.run(
            ["git", "-C", repo, "ls-remote", remote, f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 128:
            return None, "auth_failed"
        if result.returncode != 0:
            return None, "error"
        # ls-remote output format: "<sha>\t<ref>" or empty if branch not found
        output = result.stdout.strip()
        if not output:
            return None, None  # branch not found on remote
        first_line = output.splitlines()[0]
        sha = first_line.split("\t")[0].strip()
        return (sha if sha else None), None
    except subprocess.TimeoutExpired:
        return None, "network_timeout"
    except OSError:
        # Normalize OSError (git binary missing, permission denied, etc.)
        # to canonical "error" enum value. Details logged via stderr by subprocess.
        return None, "error"


def verify_remote(
    repo: str,
    remote: str,
    branch: str,
    expected_sha: str,
    max_retries: int,
    initial_backoff: float,
    timeout: float,
) -> dict:
    """
    Verify that `remote` has `expected_sha` as the HEAD of `branch`.

    Retry schedule: [0] + [initial_backoff * 2^i for i in range(max_retries)]
    Default (max_retries=3, initial_backoff=2): [0, 2, 4, 8] seconds
    Per-remote upper bound: 4 * timeout + sum(schedule[1:]) seconds
    """
    # Build retry schedule: [0, 2, 4, 8] by default
    schedule = [0.0] + [initial_backoff * (2 ** i) for i in range(max_retries)]

    attempts = 0
    start_time = time.monotonic()
    actual_sha: str | None = None
    last_reason: str | None = None

    for sleep_seconds in schedule:
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

        attempts += 1
        sha, err = ls_remote(repo, remote, branch, timeout)
        actual_sha = sha
        last_reason = err

        if sha == expected_sha:
            # Early exit on match
            total_seconds = round(time.monotonic() - start_time, 2)
            return {
                "remote": remote,
                "actual_sha": sha,
                "match": True,
                "attempts": attempts,
                "total_seconds": total_seconds,
            }

    # All attempts exhausted without match
    total_seconds = round(time.monotonic() - start_time, 2)
    reason = last_reason or "sha_mismatch"
    return {
        "remote": remote,
        "actual_sha": actual_sha,
        "match": False,
        "attempts": attempts,
        "total_seconds": total_seconds,
        "reason": reason,
    }


def main() -> None:
    args = parse_args()

    # Resolve target remotes
    if args.remotes:
        target_remotes = [r.strip() for r in args.remotes.split(",") if r.strip()]
    else:
        target_remotes = get_configured_remotes(args.repo)

    # Build retry schedule for output metadata
    retry_schedule = [0.0] + [
        args.initial_backoff * (2 ** i) for i in range(args.max_retries)
    ]

    results = []
    for remote in target_remotes:
        result = verify_remote(
            repo=args.repo,
            remote=remote,
            branch=args.branch,
            expected_sha=args.expected_sha,
            max_retries=args.max_retries,
            initial_backoff=args.initial_backoff,
            timeout=args.timeout,
        )
        results.append(result)

    all_match = all(r["match"] for r in results)

    output = {
        "repo_path": args.repo,
        "branch": args.branch,
        "expected_sha": args.expected_sha,
        "max_retries": args.max_retries,
        "retry_schedule_seconds": retry_schedule,
        "results": results,
        "all_match": all_match,
    }

    print(json.dumps(output, indent=2))
    sys.exit(0 if all_match else 1)


if __name__ == "__main__":
    main()
