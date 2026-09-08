#!/usr/bin/env python3
"""校验 Archive Tracker issue 的 SHA 回链行 (openspec-archive Step 7 的代码宿主)。

exit 0 = 回链行存在且含 7-40 位十六进制 SHA
exit 1 = 回链行缺失, 或存在但不含 SHA
exit 2 = 取不到 issue body (fail-CLOSED: 零证据不当正证据)

为什么需要它: Step 7 的 SHA 填充由 AI 按 SKILL.md 的自然语言指令执行, 没有代码宿主。
实测 6 个 tracker issue 呈 4 种形态, 其中 #185 被替换成一句**完全不含 SHA** 的话而无人发现。
"""
import argparse, re, subprocess, sys

BACKLINK_PREFIX = "> 归档 SHA 回链:"
SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")


def fetch_body(repo: str, issue: int, body_file: str | None) -> str | None:
    if body_file:
        try:
            return open(body_file, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            # 读不了 / 非 UTF-8 都归 None ⇒ 调用方判 rc 2 (fail-CLOSED)。
            # 不可归 rc 1 —— 那是「回链确实有问题」的语义, 与「判不了」必须分开。
            return None
    try:
        p = subprocess.run(
            ["forgejo", "GET", f"/repos/{repo}/issues/{issue}"],
            capture_output=True, timeout=30,
        )
        if p.returncode != 0:
            return None
        import json
        return json.loads(p.stdout.decode("utf-8", "replace")).get("body")
    except Exception:
        return None


def verify(body: str) -> tuple[int, str]:
    lines = [ln for ln in body.splitlines() if ln.lstrip().startswith(BACKLINK_PREFIX)]
    if not lines:
        return 1, f"MISSING: 未找到以 {BACKLINK_PREFIX!r} 开头的行"
    line = lines[0]
    tail = line.split(BACKLINK_PREFIX, 1)[1]
    if not SHA_RE.search(tail):
        return 1, f"NO_SHA: 回链行存在但不含 7-40 位十六进制 SHA — {line.strip()!r}"
    return 0, f"OK: {line.strip()!r}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    ap.add_argument("--issue", type=int)
    ap.add_argument("--body-file", help="离线夹具 (单测用)")
    a = ap.parse_args()
    if not a.body_file and (not a.repo or a.issue is None):
        ap.error("需要 --repo 与 --issue (或用 --body-file 走离线夹具) —— "
                 "缺省时不发起垃圾 API 请求")
    body = fetch_body(a.repo, a.issue, a.body_file)
    if body is None:
        print("FETCH_FAIL: 取不到 issue body — fail-CLOSED, 不当作通过", file=sys.stderr)
        return 2
    rc, msg = verify(body)
    print(msg)
    return rc


if __name__ == "__main__":
    sys.exit(main())
