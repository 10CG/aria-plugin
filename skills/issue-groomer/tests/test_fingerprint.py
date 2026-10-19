"""Tests for lib/fingerprint.py — issue-groomer 三面指纹引擎 (TASK-004, 裁定-9).

Covers the TASK-004 verification bullets:
  1. issue 面: title/body/labels hash (labels 顺序不敏感) + comments 最新
     updated_at 三态 (值 / None-[] / "unknown"); 显式排除
     assignee/milestone/due_date (结构上不读 ⇒ 变了指纹不变)
     (IssueFaceTests / CommentsThreeStateTests / FingerprintIssuesTests).
  2. 上下文面: openspec/changes/ 全树内容级 hash (内容变/重命名/增删 ⇒ 变;
     **archive/ 改动 ⇒ 不变**) + git HEAD (变 ⇒ 变; 失败 ⇒ None) +
     handoff = latest.md pointer (指针行变 ⇒ 变; **mtime 变指针行不变 ⇒
     不变**) + labels.yaml taxonomy hash (项目级覆盖 ⇒ 变; 与
     tier_a.taxonomy_hash SOT 逐字节一致)
     (ContextChangesTreeTests / ContextGitTests / ContextHandoffTests /
     ContextTaxonomyTests / ContextFaceTests).
  3. provenance 面: 裁定门 ③ 分层采集 (harness 自报 + model_id None=适配层
     补) + canonical 拼接串 (ProvenanceFaceTests).

fixture 形态锚点 (裁定-7 防形态脱节):
  - comment 行 = TASK-001 fetch 归一形态 ``{id, created_at, updated_at,
    body}``, ISO Z 串逐字取自真语料 scratchpad/issues-sample-body-comments-
    2026-10-18.json (Aria#233 comment id=28794)。
  - ``**Latest**:`` 指针行逐字取自本仓 docs/handoff/latest.md (2026-10-18
    实际行, 含同名 Superseded 行反例 — 行首锚定不匹配)。
上下文面全 mock: tempdir 构造文件树 + git_head_fn 注入, 零真仓依赖。
stdlib-only unittest, 与 test_tier_a.py 同风格 (无网络/无真 API)。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add scripts/ to path for direct module import (house convention).
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))

from lib import fingerprint, tier_a  # noqa: E402


# ------------------------------------------------------------- 语料真形态 anchors

# 逐字取自 scratchpad/issues-sample-body-comments-2026-10-18.json (Aria#233,
# comments_count_field=1; 时间戳保持端点原样 ISO Z 精度)。
CORPUS_COMMENT_ARIA233 = {
    "id": 28794,
    "created_at": "2026-10-15T16:58:30Z",
    "updated_at": "2026-10-15T16:58:30Z",
    "body": "…(语料 body_len=9033, 此处取形态不取全文)…",
}

# 逐字取自 /home/dev/Aria/docs/handoff/latest.md (2026-10-18) — bare Latest 行
# + 同文件含 "Latest" 字样的 Superseded 行 (行首锚定的反例)。
REAL_LATEST_LINE = "**Latest**: [2026-10-18-235-cycle-done-ab-catalog-node-ids-fixed.md](./2026-10-18-235-cycle-done-ab-catalog-node-ids-fixed.md)"
REAL_SUPERSEDED_LINE = "**Superseded (前一 Latest · 199 会话收尾)**: [2026-10-17-session-close-199-v1.76.0-full-cycle-shipped.md](./2026-10-17-session-close-199-v1.76.0-full-cycle-shipped.md)"

# 有效项目级 labels.yaml (过 tier_a SC-9: canonical 唯一 / 前缀与 label 信号
# 指向已知分类键 / 无 canonical-label 矛盾)。
PROJECT_LABELS_YAML_V1 = """\
version: 1
categories:
  bug: kind/bug
title_prefixes:
  "[bug]": bug
label_signals:
  kind/bug: bug
"""
PROJECT_LABELS_YAML_V2 = """\
version: 1
categories:
  bug: kind/defect
title_prefixes:
  "[bug]": bug
label_signals:
  kind/defect: bug
"""


def _issue(**overrides):
    """fetch 层归一形态基线行 (超集字段; 显式排除字段默认缺席)。"""
    base = {
        "repo": "Aria",
        "number": 233,
        "title": "[缺陷][示例] groomer 指纹基线",
        "labels": ["kind/bug"],
        "created": "2026-10-15",
        "updated": "2026-10-18",
        "comments_count": 1,
        "body": "body v1",
        "comments": [dict(CORPUS_COMMENT_ARIA233)],
        "comments_error": None,
    }
    base.update(overrides)
    return base


def _fake_git_head_factory(mapping):
    """git_head_fn mock: root 串 → SHA; 未见过的 root → None (失败面)。"""
    def fn(root):
        return mapping.get(str(root))
    return fn


# ---------------------------------------------------------------- ① issue 面

class IssueFaceHashTests(unittest.TestCase):
    """title/body/labels hash: 变 ⇒ 变, 不变 ⇒ 不变; labels 顺序不敏感。"""

    def test_title_change_changes_face(self):
        a = fingerprint.issue_face(_issue(title="[缺陷][示例] groomer 指纹基线 v1"))
        b = fingerprint.issue_face(_issue(title="[缺陷][示例] groomer 指纹基线 v2"))
        self.assertNotEqual(a["title_hash"], b["title_hash"])
        self.assertNotEqual(fingerprint.combined_issue_key(a), fingerprint.combined_issue_key(b))

    def test_identical_issues_same_face(self):
        a = fingerprint.issue_face(_issue())
        b = fingerprint.issue_face(_issue())
        self.assertEqual(a, b)
        self.assertEqual(fingerprint.combined_issue_key(a), fingerprint.combined_issue_key(b))

    def test_body_change_changes_body_hash_only(self):
        a = fingerprint.issue_face(_issue(body="body v1"))
        b = fingerprint.issue_face(_issue(body="body v2"))
        self.assertNotEqual(a["body_hash"], b["body_hash"])
        self.assertEqual(a["title_hash"], b["title_hash"])  # 分量正交
        self.assertNotEqual(fingerprint.combined_issue_key(a), fingerprint.combined_issue_key(b))

    def test_labels_order_insensitive(self):
        a = fingerprint.issue_face(_issue(labels=["kind/bug", "area/scanner"]))
        b = fingerprint.issue_face(_issue(labels=["area/scanner", "kind/bug"]))  # 重排
        self.assertEqual(a["labels_hash"], b["labels_hash"])
        self.assertEqual(fingerprint.combined_issue_key(a), fingerprint.combined_issue_key(b))

    def test_labels_membership_change_detected(self):
        a = fingerprint.issue_face(_issue(labels=["kind/bug"]))
        b = fingerprint.issue_face(_issue(labels=["kind/bug", "area/scanner"]))  # 增
        c = fingerprint.issue_face(_issue(labels=[]))  # 删空
        self.assertNotEqual(a["labels_hash"], b["labels_hash"])
        self.assertNotEqual(a["labels_hash"], c["labels_hash"])
        self.assertNotEqual(b["labels_hash"], c["labels_hash"])

    def test_labels_duplicate_not_silently_deduped(self):
        # 重复项是真实差异 — 静默去重会磨掉它 (labels_hash 实现退化检测点)。
        a = fingerprint.issue_face(_issue(labels=["kind/bug"]))
        b = fingerprint.issue_face(_issue(labels=["kind/bug", "kind/bug"]))
        self.assertNotEqual(a["labels_hash"], b["labels_hash"])

    def test_labels_missing_normalized_to_empty(self):
        issue = _issue()
        del issue["labels"]
        self.assertEqual(fingerprint.issue_face(issue)["labels_hash"],
                         fingerprint.issue_face(_issue(labels=[]))["labels_hash"])

    def test_labels_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            fingerprint.issue_face(_issue(labels="kind/bug"))

    def test_title_body_none_normalized(self):
        a = fingerprint.issue_face(_issue(title=None, body=None))
        b = fingerprint.issue_face(_issue(title="", body=""))
        self.assertEqual(a, b)


class CommentsThreeStateTests(unittest.TestCase):
    """comments 最新 updated_at 三态: 值 / None-零评论([]) / "unknown"。"""

    def test_state_value_max_over_updated_at(self):
        # max 自取, 不依赖上游顺序; 语料真形态行 (Aria#233 id=28794) + 第二条。
        comments = [
            {"id": 28795, "created_at": "2026-10-16T01:02:03Z",
             "updated_at": "2026-10-16T01:02:03Z", "body": "b"},
            dict(CORPUS_COMMENT_ARIA233),  # updated 2026-10-15T16:58:30Z (最旧在后)
        ]
        face = fingerprint.issue_face(_issue(comments=comments))
        self.assertEqual(face["comments_latest_updated_at"], "2026-10-16T01:02:03Z")

    def test_state_value_edit_discrimination(self):
        # ⑩-mandate 方向: 评论编辑判别 = max(updated_at), 非 max(created_at)/
        # id/末行代理 — 最新 updated_at 的行其 created_at 与 id 都**不是**最大。
        comments = [
            {"id": 1, "created_at": "2026-10-01T00:00:00Z",
             "updated_at": "2026-10-01T00:00:00Z", "body": "old"},       # 最早
            {"id": 2, "created_at": "2026-10-20T00:00:00Z",              # created 最大
             "updated_at": "2026-10-19T00:00:00Z", "body": "later"},     # id 最大
            {"id": 3, "created_at": "2026-10-02T00:00:00Z",
             "updated_at": "2026-10-21T00:00:00Z", "body": "edited"},    # updated 最大
        ]
        face = fingerprint.issue_face(_issue(comments=comments))
        self.assertEqual(face["comments_latest_updated_at"], "2026-10-21T00:00:00Z")

    def test_state_none_empty_list_zero_comments(self):
        face = fingerprint.issue_face(_issue(comments=[], comments_count=0))
        self.assertIsNone(face["comments_latest_updated_at"])

    def test_state_unknown_comments_is_none(self):
        face = fingerprint.issue_face(_issue(comments=None))
        self.assertEqual(face["comments_latest_updated_at"], fingerprint.COMMENTS_UNKNOWN)
        self.assertEqual(face["comments_latest_updated_at"], "unknown")

    def test_state_unknown_fetch_error_overrides_everything(self):
        # comments_error 非 None ⇒ unknown, 即便 comments 是 [] (失败不冒充零评论)
        # 或带着完整数据 (错误面是权威)。
        for comments in ([], [dict(CORPUS_COMMENT_ARIA233)], None):
            with self.subTest(comments=comments):
                face = fingerprint.issue_face(_issue(
                    comments=comments, comments_error="count reconciliation mismatch"))
                self.assertEqual(face["comments_latest_updated_at"], "unknown")

    def test_state_unknown_comment_row_missing_updated_at(self):
        # 单条 updated_at 缺席 ⇒ 最新值无法诚实判定 ⇒ unknown (不猜/不跳过)。
        comments = [
            {"id": 1, "created_at": "2026-10-01T00:00:00Z",
             "updated_at": "2026-10-01T00:00:00Z", "body": "ok"},
            {"id": 2, "created_at": "2026-10-02T00:00:00Z", "body": "no ts"},
        ]
        face = fingerprint.issue_face(_issue(comments=comments))
        self.assertEqual(face["comments_latest_updated_at"], "unknown")

    def test_three_states_mutually_distinct_at_key_level(self):
        # 三态在 face 与 combined key 两层都互异 — 任一态塌缩成另一态必红。
        face_value = fingerprint.issue_face(_issue(comments=[dict(CORPUS_COMMENT_ARIA233)]))
        face_zero = fingerprint.issue_face(_issue(comments=[]))
        face_unknown = fingerprint.issue_face(_issue(comments=None))
        values = {face_value["comments_latest_updated_at"],
                  face_zero["comments_latest_updated_at"],
                  face_unknown["comments_latest_updated_at"]}
        self.assertEqual(len(values), 3)
        keys = {fingerprint.combined_issue_key(f) for f in (face_value, face_zero, face_unknown)}
        self.assertEqual(len(keys), 3)

    def test_comments_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            fingerprint.issue_face(_issue(comments={"id": 1}))

    def test_comment_row_not_a_dict_raises(self):
        with self.assertRaises(ValueError):
            fingerprint.issue_face(_issue(comments=["not-a-dict"]))


class ExcludedFieldsTests(unittest.TestCase):
    """显式排除集 (裁定-9): assignee/milestone/due_date 变 ⇒ 指纹不变。"""

    def test_excluded_fields_do_not_affect_face(self):
        base = fingerprint.issue_face(_issue())
        for field, value in (
            ("assignee", {"login": "simonfishgit", "id": 42}),
            ("milestone", {"title": "v2.1", "due_on": "2026-12-01T00:00:00Z"}),
            ("due_date", "2026-12-31"),
        ):
            varied = fingerprint.issue_face(_issue(**{field: value}))
            self.assertEqual(base, varied, f"{field} 变化不得影响 issue 面")
            self.assertEqual(fingerprint.combined_issue_key(base),
                             fingerprint.combined_issue_key(varied))
        # 组合出现 + 再变化同样不影响 (读取面封闭 ⇒ 任意值形态都进不了指纹)。
        loaded = _issue(assignee={"login": "other"}, milestone={"title": "M7"},
                        due_date="2027-01-01")
        self.assertEqual(base, fingerprint.issue_face(loaded))


class FingerprintIssuesTests(unittest.TestCase):
    """fingerprint_issues 键形态 + 身份校验; combined_issue_key 基元。"""

    def test_key_format_repo_hash_number(self):
        faces = fingerprint.fingerprint_issues([_issue(), _issue(repo="aria-plugin", number=219)])
        self.assertEqual(set(faces), {"Aria#233", "aria-plugin#219"})

    def test_duplicate_identity_raises(self):
        with self.assertRaises(ValueError):
            fingerprint.fingerprint_issues([_issue(), _issue(body="dup identity")])

    def test_missing_identity_raises(self):
        issue = _issue()
        del issue["repo"]
        with self.assertRaises(ValueError):
            fingerprint.fingerprint_issues([issue])
        issue = _issue()
        del issue["number"]
        with self.assertRaises(ValueError):
            fingerprint.fingerprint_issues([issue])

    def test_combined_key_sensitive_to_each_component(self):
        base = fingerprint.issue_face(_issue())
        base_key = fingerprint.combined_issue_key(base)
        variants = (
            fingerprint.issue_face(_issue(title="changed")),
            fingerprint.issue_face(_issue(body="changed")),
            fingerprint.issue_face(_issue(labels=["kind/feature"])),
            fingerprint.issue_face(_issue(comments=None)),           # 值 → unknown
            fingerprint.issue_face(_issue(comments=[])),             # 值 → None
        )
        for v in variants:
            self.assertNotEqual(base_key, fingerprint.combined_issue_key(v))

    def test_combined_key_independent_of_face_construction_order(self):
        a = fingerprint.issue_face(_issue())
        b = {k: a[k] for k in reversed(list(a))}  # 同值逆序构造
        self.assertEqual(fingerprint.combined_issue_key(a), fingerprint.combined_issue_key(b))

    def test_combined_key_missing_field_raises(self):
        with self.assertRaises(ValueError):
            fingerprint.combined_issue_key({"title_hash": "x", "body_hash": "y"})


# --------------------------------------------------------------- ③ provenance 面

class ProvenanceFaceTests(unittest.TestCase):
    """裁定门 ③ 分层采集: harness 自报 + model_id 适配层补 (None=未知)。"""

    def test_harness_self_reported_model_id_default_none(self):
        self.assertEqual(fingerprint.provenance_face("claude-code"),
                         {"harness": "claude-code", "model_id": None})

    def test_model_id_filled_by_adapter(self):
        face = fingerprint.provenance_face("groom-runner", model_id="glm-5.2")
        self.assertEqual(face, {"harness": "groom-runner", "model_id": "glm-5.2"})

    def test_empty_harness_rejected(self):
        for bad in ("", "   ", None, 42):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    fingerprint.provenance_face(bad)

    def test_blank_model_id_rejected(self):
        with self.assertRaises(ValueError):
            fingerprint.provenance_face("claude-code", model_id="  ")

    def test_combined_provenance_key_changes_on_either_component(self):
        base = fingerprint.combined_provenance_key(fingerprint.provenance_face("h1", "m1"))
        same = fingerprint.combined_provenance_key(fingerprint.provenance_face("h1", "m1"))
        harness_changed = fingerprint.combined_provenance_key(fingerprint.provenance_face("h2", "m1"))
        model_changed = fingerprint.combined_provenance_key(fingerprint.provenance_face("h1", "m2"))
        model_unknown = fingerprint.combined_provenance_key(fingerprint.provenance_face("h1", None))
        self.assertEqual(base, same)
        for other in (harness_changed, model_changed, model_unknown):
            self.assertNotEqual(base, other)


# ---------------------------------------------------------------- ② 上下文面

class _TempProjectMixin(unittest.TestCase):
    """tempdir 项目树构造 (全 mock 文件系统, 零真仓依赖)。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.changes = self.root / "openspec" / "changes" / "demo-spec"
        self.changes.mkdir(parents=True)
        (self.changes / "proposal.md").write_text("proposal v1\n", encoding="utf-8")
        (self.changes / "tasks.md").write_text("tasks v1\n", encoding="utf-8")
        self.archive = self.root / "openspec" / "archive" / "old-spec"
        self.archive.mkdir(parents=True)
        (self.archive / "proposal.md").write_text("archived v1\n", encoding="utf-8")
        (self.root / "docs" / "handoff").mkdir(parents=True)
        (self.root / "docs" / "handoff" / "latest.md").write_text(
            "# Latest Session Handoff\n\n" + REAL_LATEST_LINE + "\n", encoding="utf-8"
        )
        self.git_fn = _fake_git_head_factory({str(self.root): "a" * 40})

    def tearDown(self):
        self._tmp.cleanup()

    def context(self, **kwargs):
        kwargs.setdefault("git_head_fn", self.git_fn)
        kwargs.setdefault("taxonomy", tier_a.resolve_taxonomy(self.root))
        return fingerprint.context_fingerprint(self.root, [self.root], **kwargs)


class ContextChangesTreeTests(_TempProjectMixin):
    """openspec/changes/ 全树内容级 hash: 内容/重命名/增删 ⇒ 变; archive 不变。"""

    def test_content_change_changes_hash(self):
        before = fingerprint.openspec_changes_hash(self.root)
        (self.changes / "proposal.md").write_text("proposal v2\n", encoding="utf-8")
        after = fingerprint.openspec_changes_hash(self.root)
        self.assertNotEqual(before, after)

    def test_rename_changes_hash(self):
        # 同内容改名: 相对路径是 hash payload 的一部分 ⇒ 文件名级变化也可见。
        before = fingerprint.openspec_changes_hash(self.root)
        (self.changes / "tasks.md").rename(self.changes / "design.md")
        after = fingerprint.openspec_changes_hash(self.root)
        self.assertNotEqual(before, after)

    def test_add_and_remove_change_hash(self):
        before = fingerprint.openspec_changes_hash(self.root)
        new = self.changes / "specs" / "delta.md"
        new.parent.mkdir()
        new.write_text("delta\n", encoding="utf-8")
        added = fingerprint.openspec_changes_hash(self.root)
        self.assertNotEqual(before, added)
        new.unlink()
        removed = fingerprint.openspec_changes_hash(self.root)
        self.assertEqual(before, removed)  # 回到原树 ⇒ 原 hash (确定性)

    def test_archive_changes_keep_hash(self):
        # 显式排除不变量的行为钉死: 若未来重构把 walk root 上移到 openspec/,
        # 本测试转红 (archive 内容静默进入 hash)。
        before = fingerprint.openspec_changes_hash(self.root)
        (self.archive / "proposal.md").write_text("archived v2 — 历史修订\n", encoding="utf-8")
        (self.archive / "extra.md").write_text("新增历史文件\n", encoding="utf-8")
        after = fingerprint.openspec_changes_hash(self.root)
        self.assertEqual(before, after)

    def test_missing_changes_dir_is_stable_constant(self):
        other = Path(tempfile.mkdtemp())
        try:
            h1 = fingerprint.openspec_changes_hash(other)
            h2 = fingerprint.openspec_changes_hash(other)
            self.assertEqual(h1, h2)
            (other / "openspec" / "changes").mkdir(parents=True)  # 空树 = 缺席同值
            self.assertEqual(h1, fingerprint.openspec_changes_hash(other))
        finally:
            import shutil
            shutil.rmtree(other, ignore_errors=True)


class ContextGitTests(_TempProjectMixin):
    """git HEAD 分量: 变 ⇒ 变; 失败 ⇒ None (可区分降级); 键 = 传入串原样。"""

    def test_head_change_changes_context(self):
        before = self.context()
        self.git_fn = _fake_git_head_factory({str(self.root): "b" * 40})
        after = self.context()
        self.assertNotEqual(before["git_heads"], after["git_heads"])

    def test_multiple_roots_keyed_verbatim(self):
        heads = self.context(git_head_fn=_fake_git_head_factory({
            str(self.root): "a" * 40, "/srv/satellite": "c" * 40}))
        self.assertEqual(set(heads["git_heads"]), {str(self.root)})
        full = fingerprint.context_fingerprint(
            self.root, [self.root, "/srv/satellite"],
            git_head_fn=_fake_git_head_factory({str(self.root): "a" * 40, "/srv/satellite": "c" * 40}),
            taxonomy=tier_a.resolve_taxonomy(self.root))
        self.assertEqual(set(full["git_heads"]), {str(self.root), "/srv/satellite"})

    def test_git_failure_yields_none_not_fabricated_sha(self):
        # root 不在映射表 (mock 失败面) ⇒ None — 与任何 SHA 结构可区分。
        face = self.context(git_head_fn=_fake_git_head_factory({}))
        self.assertIsNone(face["git_heads"][str(self.root)])

    def test_default_git_head_non_repo_returns_none(self):
        # 真 subprocess 路径的失败面: 不存在的路径 rc!=0 ⇒ None (stdout 不透传)。
        self.assertIsNone(fingerprint._default_git_head(str(self.root / "no-such-dir")))

    def test_git_failure_changes_face_against_sha_state(self):
        # None 降级在 face 层与任何 SHA 态互异 ⇒ 下轮比较必判变 (fail-closed 方向)。
        before = self.context()  # git_fn ⇒ "a"*40
        after = self.context(git_head_fn=_fake_git_head_factory({}))  # 同 root 失败 ⇒ None
        self.assertNotEqual(before, after)


class ContextHandoffTests(_TempProjectMixin):
    """handoff 权威 = latest.md 指针行目标文件名 (非 mtime)。"""

    def test_extracts_real_pointer_line_target(self):
        # 真 latest.md 行逐字 fixture (2026-10-18): 目标文件名, 剥 ./。
        self.assertEqual(
            fingerprint.handoff_pointer(self.root),
            "2026-10-18-235-cycle-done-ab-catalog-node-ids-fixed.md")

    def test_pointer_line_change_changes_context(self):
        before = self.context()
        latest = self.root / "docs" / "handoff" / "latest.md"
        latest.write_text(
            "# Latest Session Handoff\n\n"
            "**Latest**: [2026-10-19-next-handoff.md](./2026-10-19-next-handoff.md)\n",
            encoding="utf-8")
        after = self.context()
        self.assertNotEqual(before["handoff_pointer"], after["handoff_pointer"])

    def test_mtime_change_pointer_intact_keeps_whole_context(self):
        # mtime 变而指针行不变 ⇒ 整个上下文面逐字节不变 (非 mtime 纪律的行为钉)。
        before = self.context()
        latest = self.root / "docs" / "handoff" / "latest.md"
        os.utime(latest, (2000000000, 2000000000))  # mtime 推到 2033 年
        after = self.context()
        self.assertEqual(before, after)

    def test_superseded_lines_do_not_match(self):
        # 含 "Latest" 字样的 Superseded 行不是 bare Latest 行 (行首锚定)。
        latest = self.root / "docs" / "handoff" / "latest.md"
        latest.write_text("# H\n\n" + REAL_SUPERSEDED_LINE + "\n", encoding="utf-8")
        self.assertIsNone(fingerprint.handoff_pointer(self.root))

    def test_no_pointer_line_degrades_to_none(self):
        latest = self.root / "docs" / "handoff" / "latest.md"
        latest.write_text("# 没有指针行的 handoff\n正文…\n", encoding="utf-8")
        self.assertIsNone(fingerprint.handoff_pointer(self.root))

    def test_missing_latest_md_degrades_to_none(self):
        (self.root / "docs" / "handoff" / "latest.md").unlink()
        self.assertIsNone(fingerprint.handoff_pointer(self.root))

    def test_link_target_wins_over_display_text(self):
        latest = self.root / "docs" / "handoff" / "latest.md"
        latest.write_text("**Latest**: [display-name.md](./actual-target.md)\n", encoding="utf-8")
        self.assertEqual(fingerprint.handoff_pointer(self.root), "actual-target.md")

    def test_first_matching_line_wins(self):
        latest = self.root / "docs" / "handoff" / "latest.md"
        latest.write_text(
            "**Latest**: [first.md](./first.md)\n**Latest**: [second.md](./second.md)\n",
            encoding="utf-8")
        self.assertEqual(fingerprint.handoff_pointer(self.root), "first.md")


class ContextTaxonomyTests(_TempProjectMixin):
    """labels.yaml taxonomy hash: 项目级覆盖 ⇒ 变; 与 tier_a SOT 一致。"""

    def test_project_override_changes_taxonomy_hash(self):
        # 裁定-1 覆盖语义进指纹: 项目文件出现 (整体覆盖内置层) ⇒ hash 变。
        before = self.context(taxonomy=None)  # 无项目文件 → 内置层
        self.assertEqual(
            before["taxonomy_hash"],
            tier_a.taxonomy_hash(tier_a.resolve_taxonomy(self.root)))  # SOT 对账
        (self.root / ".aria").mkdir()
        (self.root / ".aria" / "labels.yaml").write_text(PROJECT_LABELS_YAML_V1, encoding="utf-8")
        overridden = self.context(taxonomy=None)
        self.assertNotEqual(before["taxonomy_hash"], overridden["taxonomy_hash"])
        self.assertEqual(
            overridden["taxonomy_hash"],
            tier_a.taxonomy_hash(tier_a.resolve_taxonomy(self.root)))  # SOT 对账

    def test_project_file_content_change_propagates(self):
        (self.root / ".aria").mkdir()
        (self.root / ".aria" / "labels.yaml").write_text(PROJECT_LABELS_YAML_V1, encoding="utf-8")
        v1 = self.context(taxonomy=None)
        (self.root / ".aria" / "labels.yaml").write_text(PROJECT_LABELS_YAML_V2, encoding="utf-8")
        v2 = self.context(taxonomy=None)
        self.assertNotEqual(v1["taxonomy_hash"], v2["taxonomy_hash"])

    def test_broken_project_taxonomy_fails_closed(self):
        (self.root / ".aria").mkdir()
        (self.root / ".aria" / "labels.yaml").write_text(
            "version: 1\ncategories:\n  bug: kind/bug\ntitle_prefixes:\n  \"[bug]\": nope\n"
            "label_signals:\n  kind/bug: bug\n", encoding="utf-8")  # 前缀指向未知分类键
        with self.assertRaises(ValueError):
            self.context(taxonomy=None)


class ContextFaceTests(_TempProjectMixin):
    """上下文面整体: 恰四键 + 跨调用确定性 + 全链判变。"""

    def test_face_has_exactly_four_keys(self):
        face = self.context()
        self.assertEqual(
            set(face),
            {"openspec_changes_hash", "git_heads", "handoff_pointer", "taxonomy_hash"})

    def test_deterministic_across_calls(self):
        self.assertEqual(self.context(), self.context())

    def test_no_change_no_diff_any_component(self):
        # 综合反事实: 树 / git / handoff / taxonomy 四分量各动一处 ⇒ face 必变。
        before = self.context()
        # ① changes 内容
        (self.changes / "proposal.md").write_text("proposal v2\n", encoding="utf-8")
        self.assertNotEqual(before, self.context())
        # 还原后动 ② git HEAD
        (self.changes / "proposal.md").write_text("proposal v1\n", encoding="utf-8")
        self.assertEqual(before, self.context())  # 还原 = 复原 (确定性)
        self.git_fn = _fake_git_head_factory({str(self.root): "d" * 40})
        self.assertNotEqual(before, self.context())
        # 还原后动 ③ handoff 指针
        self.git_fn = _fake_git_head_factory({str(self.root): "a" * 40})
        latest = self.root / "docs" / "handoff" / "latest.md"
        latest.write_text("**Latest**: [another.md](./another.md)\n", encoding="utf-8")
        self.assertNotEqual(before, self.context())
        # 还原后动 ④ taxonomy (注入不同已解析 taxonomy)
        latest.write_text("# Latest Session Handoff\n\n" + REAL_LATEST_LINE + "\n", encoding="utf-8")
        self.assertEqual(before, self.context())
        mutated_tax = {"version": 1, "categories": {"bug": "kind/other"},
                       "title_prefixes": {}, "label_signals": {}}
        self.assertNotEqual(before, self.context(taxonomy=mutated_tax))


class ContextKeyTests(_TempProjectMixin):
    """context_key (DEC 裁定-9): 上下文面四分量 → canonical 单键 — Tier B
    上下文门的比对基元。

    反事实: 若 context_key 退化成常量 (或漏分量), 「分量变 ⇒ key 必变」
    断言必红 — 门失去判变面, #110 类静默陈旧复活; 若非 canonical (键序
    敏感), 确定性断言必红 (跨运行假判变)。
    """

    def test_key_is_sha256_hex_and_deterministic(self):
        key = fingerprint.context_key(self.context())
        self.assertEqual(len(key), 64)
        int(key, 16)  # hex 形态
        self.assertEqual(key, fingerprint.context_key(self.context()))

    def test_key_ignores_dict_construction_order(self):
        # canonical 化: 外层与 git_heads 内层键序都不影响 key (sort_keys 递归)。
        face = self.context()
        reordered = {k: face[k] for k in reversed(list(face))}
        self.assertEqual(
            fingerprint.context_key(face), fingerprint.context_key(reordered)
        )
        two_roots = {**face, "git_heads": {"/repo/a": "a" * 40, "/repo/b": "b" * 40}}
        two_roots_swapped = {**face, "git_heads": {"/repo/b": "b" * 40, "/repo/a": "a" * 40}}
        self.assertEqual(
            fingerprint.context_key(two_roots), fingerprint.context_key(two_roots_swapped)
        )

    def test_each_component_change_changes_key(self):
        before = fingerprint.context_key(self.context())
        # ① openspec 树内容
        (self.changes / "proposal.md").write_text("proposal v2\n", encoding="utf-8")
        self.assertNotEqual(before, fingerprint.context_key(self.context()))
        (self.changes / "proposal.md").write_text("proposal v1\n", encoding="utf-8")
        # ② git HEAD
        self.git_fn = _fake_git_head_factory({str(self.root): "d" * 40})
        self.assertNotEqual(before, fingerprint.context_key(self.context()))
        self.git_fn = _fake_git_head_factory({str(self.root): "a" * 40})
        # ③ handoff 指针
        latest = self.root / "docs" / "handoff" / "latest.md"
        latest.write_text("**Latest**: [another.md](./another.md)\n", encoding="utf-8")
        self.assertNotEqual(before, fingerprint.context_key(self.context()))
        latest.write_text("# Latest Session Handoff\n\n" + REAL_LATEST_LINE + "\n",
                          encoding="utf-8")
        # ④ taxonomy
        self.assertEqual(before, fingerprint.context_key(self.context()))  # 还原 = 复原
        mutated_tax = {"version": 1, "categories": {"bug": "kind/other"},
                       "title_prefixes": {}, "label_signals": {}}
        self.assertNotEqual(
            before, fingerprint.context_key(self.context(taxonomy=mutated_tax))
        )

    def test_missing_component_raises(self):
        face = self.context()
        for drop in ("openspec_changes_hash", "git_heads", "handoff_pointer",
                     "taxonomy_hash"):
            with self.subTest(drop=drop):
                partial = {k: v for k, v in face.items() if k != drop}
                with self.assertRaises(ValueError):
                    fingerprint.context_key(partial)

    def test_non_dict_raises(self):
        for bad in (None, "face", [("a", 1)]):
            with self.subTest(bad=type(bad).__name__):
                with self.assertRaises(ValueError):
                    fingerprint.context_key(bad)

    def test_degradation_marker_values_distinct(self):
        # git_heads 失败降级 None (与 SHA 结构可区分) ⇒ key 必变 — 降级方向
        # = 多判变, 不误稳 (fail-closed 在 key 层保持)。
        face = self.context()
        degraded = {**face, "git_heads": {str(self.root): None}}
        self.assertNotEqual(
            fingerprint.context_key(face), fingerprint.context_key(degraded)
        )


if __name__ == "__main__":
    unittest.main()
