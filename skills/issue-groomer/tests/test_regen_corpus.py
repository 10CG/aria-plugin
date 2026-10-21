"""Tests for scripts/regen_corpus.py — B.3 修复轮 (双席合并测试文件).

覆盖三个 B.3 条目 (A-2 = 席 A, E-5/D-3 = 席 B; 两席各自落地时先后写了
本文件, 此处合并 — 后续任一席增改请保留对方条目):

  A-2 (席 A): ``_paged_get`` 的空页终止契约只认 JSON ``[]``; rc=0 + 空
  stdout (Forgejo.call 返回 None) 是结构违规 ⇒ RegenError (语料再生绝不
  写出半份文件)。反事实: 若 None 被折成 [] (旧行为), page1 no-content 会
  静默终止游走 ⇒ 空 issues-open-full / sample 的 comments 面写盘 —
  「端点哑了」被折成「仓里没行」, 与 2026-10-18 canonical trio 字节漂移。

  E-5 (席 B): build_sample 的 issue detail ``comments`` 计数字段缺席 /
  非 int / bool / 负值 ⇒ RegenError — 绝不冒充 0。该计数是 comments 端点
  全量走的对账基线 (expected_count); 一个被伪造的 0 会把「字段形态漂了」
  静默折成「零评论语料」。

  D-3 (席 B, regen 半): 语料三件套事务化落盘 — 全部先写 ``.tmp`` (每个
  写完才算 staged) 再统一 rename。staging 期任一步失败 ⇒ 三个目标全部
  保持旧代 (无写入期混代、无半写字节); rename 期失败 ⇒ 无 ``.tmp`` 残留,
  每个目标只能是完整的旧或新 JSON。

全 fake — 零网络。FakeForgejo 路由表按 endpoint 字符串精确匹配
(None = rc=0 空 stdout)。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(_HERE), "scripts")
sys.path.insert(0, SCRIPTS)

import regen_corpus  # noqa: E402


class FakeForgejo:
    """路由 fake: endpoint → 返回值 (None = rc=0 空 stdout)。记录调用。"""

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.calls = []

    def call(self, method, endpoint, payload=None):
        self.calls.append(endpoint)
        if endpoint not in self.routes:
            raise AssertionError(f"unexpected endpoint: {method} {endpoint!r}")
        return self.routes[endpoint]


def issue_ep(page=1, repo="Aria"):
    base = f"/repos/10CG/{repo}/issues?state=open&type=issues&limit={regen_corpus.PAGE_SIZE}"
    return base if page == 1 else f"{base}&page={page}"


def detail_ep(repo="Aria", number=233):
    return f"/repos/10CG/{repo}/issues/{number}"


def comments_ep(repo="Aria", number=233):
    return f"/repos/10CG/{repo}/issues/{number}/comments?limit={regen_corpus.PAGE_SIZE}"


# ── A-2 (席 A): no-content ≠ empty page ──────────────────────────────────────


class NoContentIsNotEmptyPageTests(unittest.TestCase):
    def test_none_on_first_page_raises(self):
        forgejo = FakeForgejo({issue_ep(1): None})
        with self.assertRaises(regen_corpus.RegenError) as ctx:
            regen_corpus._paged_get(forgejo, lambda p: issue_ep(p), "number")
        self.assertIn("empty body", str(ctx.exception))
        self.assertIn("JSON '[]'", str(ctx.exception))

    def test_none_on_later_page_raises(self):
        # page1 有真数据、page2 no-content — 中途失声不得折成「正好翻完」。
        row = {"number": 1, "title": "t"}
        forgejo = FakeForgejo({issue_ep(1): [row], issue_ep(2): None})
        with self.assertRaises(regen_corpus.RegenError) as ctx:
            regen_corpus._paged_get(forgejo, lambda p: issue_ep(p), "number")
        self.assertIn("empty body", str(ctx.exception))

    def test_json_empty_page_still_terminates(self):
        # "[]" 空页仍是合法终止 — A-2 只收紧 None, 不改空页语义。
        row = {"number": 1, "title": "t"}
        forgejo = FakeForgejo({issue_ep(1): [row], issue_ep(2): []})
        rows = regen_corpus._paged_get(forgejo, lambda p: issue_ep(p), "number")
        self.assertEqual(rows, [row])


# ── E-5 (席 B): comments 计数字段不冒充 0 ────────────────────────────────────


def _detail(**overrides):
    base = {"number": 233, "title": "[tracker] sample", "body": "b" * 10,
            "comments": 2}
    base.update(overrides)
    return base


def _comment(cid):
    return {"id": cid, "body": "c", "created_at": "2026-10-15T16:58:30Z",
            "updated_at": "2026-10-15T16:58:30Z"}


class SampleCommentsCountFailClosedTests(unittest.TestCase):
    """build_sample: comments 计数字段缺席/非 int/bool/负 ⇒ RegenError
    (E-5)。反事实: 旧行为 ``int(raw.get("comments") or 0)`` 把缺席/None
    全部折成 0 — 对账基线被伪造, 静默产出零评论语料。"""

    TARGETS = [("Aria", 233)]
    DATE = "2026-10-19"

    def _sample(self, detail, comments_rows):
        forgejo = FakeForgejo({detail_ep(): detail, comments_ep(): comments_rows})
        return regen_corpus.build_sample(forgejo, self.TARGETS, self.DATE), forgejo

    def test_missing_comments_field_raises(self):
        detail = _detail()
        del detail["comments"]
        with self.assertRaisesRegex(regen_corpus.RegenError, "count field absent"):
            self._sample(detail, [_comment(1)])

    def test_none_comments_field_raises(self):
        with self.assertRaisesRegex(regen_corpus.RegenError, "refusing to fake 0"):
            self._sample(_detail(comments=None), [])

    def test_non_int_comments_field_raises(self):
        for bad in ("2", 2.0, [2], {"n": 2}):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(regen_corpus.RegenError, "refusing to fake 0"):
                    self._sample(_detail(comments=bad), [])

    def test_bool_and_negative_comments_field_raise(self):
        # bool 是 int 子类 — 无 bool 守卫会被当合法计数放行 (Python quirk)。
        for bad in (True, -1):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(regen_corpus.RegenError, "refusing to fake 0"):
                    self._sample(_detail(comments=bad), [])

    def test_valid_count_used_verbatim_for_walk_and_field(self):
        sample, forgejo = self._sample(_detail(comments=2), [_comment(1), _comment(2)])
        (item,) = sample["items"]
        self.assertEqual(item["comments_count_field"], 2)       # 字段原样, 非 int() 重铸
        self.assertEqual(len(item["comments_endpoint_shape"]), 2)  # 对账基线驱动全量走
        self.assertEqual(item["body_len"], 10)
        self.assertEqual(item["body_head"], "b" * 10)

    def test_zero_count_still_walks_endpoint(self):
        # count=0 ⇒ 对账 GET 照发 (端点返回 "[]" ⇒ 空走) — 已知取舍: 不信任
        # 计数单侧, 对账以端点全量返回为准 (SKILL.md Step 0 注)。
        sample, forgejo = self._sample(_detail(comments=0), [])
        (item,) = sample["items"]
        self.assertEqual(item["comments_count_field"], 0)
        self.assertEqual(item["comments_endpoint_shape"], [])
        self.assertIn(comments_ep(), forgejo.calls)


# ── D-3 (席 B): 三文件事务化 (先全 staged 再统一 rename) ─────────────────────


class TrioTransactionalWriteTests(unittest.TestCase):

    def _outputs(self, root):
        return [
            (root / "issues-open-full-18repos-2026-10-19.json", [{"repo": "Aria", "v": "full"}]),
            (root / "issues-open-2026-10-19.json", [{"repo": "Aria", "v": "curated"}]),
            (root / "issues-sample-body-comments-2026-10-19.json", {"items": [], "v": "sample"}),
        ]

    @staticmethod
    def _tmp_litter(root):
        return list(root.rglob("*.tmp"))

    def test_success_writes_all_three_and_leaves_no_tmp(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            regen_corpus._write_trio(self._outputs(root))
            names = sorted(p.name for p in root.iterdir())
            self.assertEqual(names, [
                "issues-open-2026-10-19.json",
                "issues-open-full-18repos-2026-10-19.json",
                "issues-sample-body-comments-2026-10-19.json",
            ])  # 三目标齐
            self.assertEqual(self._tmp_litter(root), [])
            full = json.loads((root / "issues-open-full-18repos-2026-10-19.json").read_text(encoding="utf-8"))
            self.assertEqual(full, [{"repo": "Aria", "v": "full"}])

    def test_staging_failure_leaves_whole_trio_at_old_generation(self):
        # 预置旧代; staging 第 2 个 payload 序列化失败 (不可 JSON 化对象)
        # ⇒ 三个目标全部保持旧形态 (已 staged 的第 1 个也不换 — 无写入期
        # 混代), tmp 全清。反事实: 旧 ``逐文件写完即 rename`` 形态下第 1 个
        # 已换新代 ⇒ 混代。
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            old_full = root / "issues-open-full-18repos-2026-10-19.json"
            old_full.write_text('[{"old": true}]', encoding="utf-8")
            outputs = self._outputs(root)
            outputs[1] = (outputs[1][0], {"unserializable": object()})
            with self.assertRaises(TypeError):
                regen_corpus._write_trio(outputs)
            self.assertEqual(old_full.read_text(encoding="utf-8"), '[{"old": true}]')
            self.assertFalse((root / "issues-open-2026-10-19.json").exists())
            self.assertFalse((root / "issues-sample-body-comments-2026-10-19.json").exists())
            self.assertEqual(self._tmp_litter(root), [])

    def test_staging_failure_on_first_file_leaves_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            outputs = self._outputs(root)
            outputs[0] = (outputs[0][0], object())  # 第 1 个即失败
            with self.assertRaises(TypeError):
                regen_corpus._write_trio(outputs)
            self.assertEqual(list(root.iterdir()), [])
            self.assertEqual(self._tmp_litter(root), [])

    def test_rename_failure_no_half_bytes_no_tmp_litter(self):
        # rename 期第 2 个换名崩溃: 已换的第 1 个停留新代 (rollback 非目标),
        # 未换的保持旧/缺席 — 结构保证只有「完整旧或完整新」的文件, 无半写
        # 字节, tmp 清干净。
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            old_curated = root / "issues-open-2026-10-19.json"
            old_curated.write_text('[{"old": true}]', encoding="utf-8")
            outputs = self._outputs(root)

            calls = {"n": 0}

            def crashing_rename(src, dst):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise RuntimeError("simulated crash mid-rename")
                src.replace(dst)

            with self.assertRaises(RuntimeError):
                regen_corpus._write_trio(outputs, rename_fn=crashing_rename)
            # 第 1 个: 已换新代 (完整可解析 JSON)
            full = json.loads((root / "issues-open-full-18repos-2026-10-19.json").read_text(encoding="utf-8"))
            self.assertEqual(full, [{"repo": "Aria", "v": "full"}])
            # 第 2/3 个: 旧内容 / 缺席 (完整形态, 非半写)
            self.assertEqual(old_curated.read_text(encoding="utf-8"), '[{"old": true}]')
            self.assertFalse((root / "issues-sample-body-comments-2026-10-19.json").exists())
            self.assertEqual(self._tmp_litter(root), [])


if __name__ == "__main__":
    unittest.main()
