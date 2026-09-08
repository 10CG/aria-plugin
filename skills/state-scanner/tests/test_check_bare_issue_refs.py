"""check_bare_issue_refs.py — 封闭豁免集边界 + rc 契约 + 允许清单 I/O。

该探针守「文档里的 issue 引用必须带 `<org>/<repo>` 限定」这条纪律。它在
2026-09-08 的 cycle 里被**重写两次** (先改 fail-CLOSED + 外置允许清单, 再修
CJK 左边界 + cwd 依赖), 而交付时零测试覆盖 —— 发布前验证席把这一点判为 Major。
本文件补上。

判据是 **fail-CLOSED**: 先假定每个 `#<n>` 都违规, 只有落进封闭豁免集才放过。
封闭豁免集仅三类:
  (a) 全限定 `<org>/<repo>#<n>` —— 恰一个 `/`, repo 段不含 `.`
  (b) `Rule #N` / `规则 #N`
  (c) 落在允许清单某条字面**覆盖的字符区间内**的 `#<n>`

rc 契约: 0 = 零违规 / 1 = 有违规 / 2 = 判不了 (fail-CLOSED, 与「有违规」分开)。

每条测试都能答「它怎么会红?」—— 每个「该豁免」的形态都配了一个同轴的
「该违规」兄弟 (memory `adversarial-fixture`: 验拒绝能力而非当前取值)。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_bare_issue_refs as probe  # type: ignore[import]  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_bare_issue_refs.py"


def _run(args, cwd=None):
    """跑真 CLI, 返回 (rc, stdout, stderr) —— rc 契约必须端到端验, 不能只验 scan()。"""
    p = subprocess.run(
        [sys.executable, "-B", str(SCRIPT)] + args,
        capture_output=True, text=True, cwd=str(cwd) if cwd else None,
    )
    return p.returncode, p.stdout, p.stderr


class ExemptionBoundaries(unittest.TestCase):
    """封闭豁免集的三类边界, 每类配一个同轴反例。"""

    def _scan_one(self, text, allowlist=None):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "t.md"
            f.write_text(text, encoding="utf-8")
            return probe.scan(str(f), allowlist or [])

    # --- (a) 全限定 ---
    def test_fully_qualified_is_exempt(self):
        self.assertEqual(self._scan_one("见 10CG/Aria#195\n"), [])

    def test_half_qualified_is_violation(self):
        """只有仓名没有 org ⇒ 跨仓歧义, 必须报。"""
        self.assertEqual(len(self._scan_one("见 Aria#195\n")), 1)

    def test_path_disguise_is_violation(self):
        """多级路径 + 扩展名 + #n 不是 issue 引用形态, 旧版单字符前瞻会放行它。"""
        self.assertEqual(len(self._scan_one("见 docs/handoff/x.md#123\n")), 1)

    def test_cjk_adjacent_qualified_is_exempt(self):
        """左边界用 `\\w` 会把 CJK 当单词字符 ⇒ 中文紧邻的全限定引用被误报。"""
        self.assertEqual(self._scan_one("参见10CG/Aria#195 那条\n"), [])

    # --- (b) 规则编号 ---
    def test_rule_number_is_exempt(self):
        self.assertEqual(self._scan_one("按 Rule #6 处置\n"), [])
        self.assertEqual(self._scan_one("按 规则 #10 处置\n"), [])

    def test_bare_number_is_violation(self):
        self.assertEqual(len(self._scan_one("见 #777\n")), 1)

    # --- (c) 允许清单按区间而非按行 ---
    def test_allowlist_covers_only_its_own_span(self):
        """同一行后面追加的新裸引用**不得**被连带放行 (旧版按行豁免的缺陷)。"""
        lit = "| D.2 | Spec 归档 (**#95 完成度**) |"
        hits = self._scan_one(lit + " 尾巴 #888\n", allowlist=[lit])
        self.assertEqual([h[1] for h in hits], ["#888"])

    def test_backtick_alone_is_not_exempt(self):
        """反引号本身不构成豁免 —— 只有全限定或清单命中才算。"""
        self.assertEqual(len(self._scan_one("见 `#199`\n")), 1)


class RcContract(unittest.TestCase):
    """0 / 1 / 2 三态互斥, 且「判不了」不得落进「有违规」那个桶。"""

    def test_rc0_when_clean(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "t.md"
            f.write_text("见 10CG/Aria#195\n", encoding="utf-8")
            rc, out, _ = _run([str(f)])
            self.assertEqual(rc, 0)
            self.assertIn("裸 issue 引用: 0", out)

    def test_rc1_when_violations(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "t.md"
            f.write_text("见 #777\n", encoding="utf-8")
            rc, out, _ = _run([str(f)])
            self.assertEqual(rc, 1)
            self.assertIn("#777", out)

    def test_rc2_when_target_unreadable(self):
        rc, _, err = _run(["/nonexistent/nope.md"])
        self.assertEqual(rc, 2)
        self.assertIn("UNDECIDABLE", err)

    def test_rc2_when_allowlist_not_utf8(self):
        """非 UTF-8 允许清单 ⇒ 判不了 (rc 2), **不是** rc 1。

        回归锁: 该路径此前只捕 OSError, UnicodeDecodeError 会裸抛 traceback,
        Python 默认退出码 1 恰好落进「有违规」那个桶 —— 与自己 docstring 的
        rc 契约直接冲突 (发布前验证席 Critical)。
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".aria").mkdir()
            (root / ".aria" / "bare-issue-ref-allowlist.txt").write_bytes(b"#c\n\xff\xfe bad\n")
            f = root / "t.md"
            f.write_text("见 10CG/Aria#195\n", encoding="utf-8")
            rc, _, err = _run([f"--repo-root={root}", str(f)])
            self.assertEqual(rc, 2, "非 UTF-8 清单必须落 rc 2, 不能落 rc 1")
            self.assertIn("UNDECIDABLE", err)

    def test_rc2_when_no_targets(self):
        rc, _, err = _run([])
        self.assertEqual(rc, 2)
        self.assertIn("usage:", err)


class AllowlistResolution(unittest.TestCase):
    """清单定位与 cwd 解耦 —— 否则换个目录跑自检就红出假阳性。"""

    def test_missing_allowlist_is_empty_not_error(self):
        """缺失 ⇒ 空清单 (最严格), 不是崩溃。"""
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(probe.load_allowlist(Path(td)), [])

    def test_found_by_walking_up_from_scanned_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".aria").mkdir()
            (root / ".aria" / "bare-issue-ref-allowlist.txt").write_text(
                "# 注释行\n目标行含 #95 的字面\n", encoding="utf-8")
            deep = root / "a" / "b"
            deep.mkdir(parents=True)
            f = deep / "t.md"
            f.write_text("目标行含 #95 的字面\n", encoding="utf-8")
            found = probe._find_allowlist(str(f))
            self.assertIsNotNone(found)
            # 从一个**无关的 cwd** 跑, 仍应 rc 0
            with tempfile.TemporaryDirectory() as other:
                rc, _, _ = _run([str(f)], cwd=other)
                self.assertEqual(rc, 0, "清单定位必须与 cwd 无关")

    def test_comment_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".aria").mkdir()
            (root / ".aria" / "bare-issue-ref-allowlist.txt").write_text(
                "# 这是注释, 不该成为豁免字面\n真字面 #95\n", encoding="utf-8")
            self.assertEqual(probe.load_allowlist(root), ["真字面 #95"])


if __name__ == "__main__":
    unittest.main()
