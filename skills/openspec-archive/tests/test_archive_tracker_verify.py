#!/usr/bin/env python3
"""Tests for openspec-archive/scripts/archive_tracker_verify.py (Part C2)。

全部用**冻结夹具**跑, 不实时抓 API —— 夹具是真语料快照 (`fixtures/issue-*.md`, 首行注明
来源与抓取时刻) 加一份合成件 (`synth-short.md`)。

每条测试都能答「它怎么会红?」:
  - test_ok_real:        #201 真有合法 SHA ⇒ 若 verify 退化成「只要有回链行就过」仍绿, 但
                         test_no_sha_real 会红 ⇒ 两条合起来才有鉴别力
  - test_no_sha_real:    #185 回链行在但被替换成一句中文 ⇒ 挡「只查行存在」这个坏实现
  - test_missing_real:   #186 根本没有回链行 ⇒ 挡「找不到行就当通过」
  - test_short_sha_synth: 合成件 SHA 只有 3 位 ⇒ 挡「[0-9a-f]+ 无长度下限」。**真语料证不了
                         这一条** (#185 尾部纯中文, 零 ASCII 十六进制, 无长度下限的实现在它
                         上面也红) —— 这就是必须有合成夹具的理由
  - test_fetch_fail_closed: 取不到 body 时 rc 2, 零证据不当正证据

Run:
    python3 -m pytest tests/test_archive_tracker_verify.py -v
    python3 tests/test_archive_tracker_verify.py          # fallback: plain asserts
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from archive_tracker_verify import verify, fetch_body  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"


def _body(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_ok_real():
    rc, msg = verify(_body("issue-201.md"))
    assert rc == 0, msg
    assert msg.startswith("OK:"), msg


def test_no_sha_real():
    """#185: 回链行存在但被替换成一句不含 SHA 的话 —— 挡「只查行存在」。"""
    rc, msg = verify(_body("issue-185.md"))
    assert rc == 1, msg
    assert "NO_SHA" in msg, msg


def test_missing_real():
    """#186: 完全没有回链行。"""
    rc, msg = verify(_body("issue-186.md"))
    assert rc == 1, msg
    assert "MISSING" in msg, msg


def test_short_sha_synth():
    """合成件: SHA 只有 3 位 —— 挡「无长度下限」。真语料证不了这一条。"""
    rc, msg = verify(_body("synth-short.md"))
    assert rc == 1, msg
    assert "NO_SHA" in msg, msg


def test_fetch_fail_closed(tmp_path=None):
    """取不到 body ⇒ None ⇒ 调用方判 rc 2 (fail-CLOSED)。"""
    assert fetch_body("10CG/Aria", 1, str(FIX / "does-not-exist.md")) is None


def test_prefix_must_be_line_start():
    """回链前缀出现在行中间不算 —— 防子串误命中。"""
    rc, msg = verify("正文里提到 > 归档 SHA 回链: deadbeef 但不是行首\n")
    assert rc == 1, msg
    assert "MISSING" in msg, msg


def test_non_utf8_body_file_is_undecidable():
    """非 UTF-8 的 --body-file ⇒ fetch_body 返回 None ⇒ 调用方判 rc 2 (fail-CLOSED)。

    回归锁 (发布前验证席): 该分支此前只捕 OSError, UnicodeDecodeError 会裸抛,
    Python 默认退出码 1 恰好落进「回链确实有问题」那个桶 —— 与 rc 契约冲突。
    「判不了」与「有问题」必须分开。
    """
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        f.write(b"\xff\xfe not utf-8")
        bad = f.name
    try:
        assert fetch_body("10CG/Aria", 1, bad) is None
    finally:
        Path(bad).unlink(missing_ok=True)


def test_missing_repo_or_issue_exits_before_any_request():
    """缺 --repo/--issue 且无 --body-file ⇒ argparse.error 立即退出 (rc 2), 不发垃圾请求。

    回归锁: 此前两个参数都非必填, 缺省时会真的发起一次 forgejo 调用才失败。
    """
    import subprocess, sys as _sys
    script = Path(__file__).resolve().parent.parent / "scripts" / "archive_tracker_verify.py"
    p = subprocess.run([_sys.executable, "-B", str(script)], capture_output=True, text=True)
    assert p.returncode == 2, "argparse.error 应给 rc 2, 实得 %d" % p.returncode
    assert "--repo" in p.stderr and "--issue" in p.stderr, p.stderr


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f()
        print("  ok", f.__name__)
    print("Ran %d tests OK" % len(fns))
