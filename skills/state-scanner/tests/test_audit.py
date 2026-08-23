"""Phase 1.10 audit collector tests."""

from __future__ import annotations

import os
import unittest

from _helpers import make_audit_report, tmp_project, write_file
from collectors.audit import collect_audit


# --- #149 fixture builders --------------------------------------------------
# `make_audit_report()` (in _helpers.py) emits the real on-disk aggregate
# filename shape (`...-aggregated.md`), but always with round `R1` and a
# single spec. These local builders mirror the OTHER shapes the #149 fix
# needs to discriminate between — arbitrary round numbers, single-seat
# reports, and deliberately malformed/tokenless names:
#   aggregate:   <checkpoint>-R<N>-<ts>-<spec>-aggregated.md  (or -aggregate.md, legacy)
#   single-seat: <checkpoint>-R<N>-<ts>-<spec>-<agent>.md
# `<ts>` may be a pure-digit epoch-ms token (>=12 digits) or an ISO-ish
# `YYYY-MM-DD[THHMM[SS][-mmm]Z]` token — both are real on-disk shapes per
# `references/audit-engine/report-storage.md`.


def _write_report(root, filename, *, checkpoint, verdict, converged, timestamp="2026-04-24T1000Z"):
    """Write an audit report with standard 4-field frontmatter under an
    explicit caller-chosen filename (bypasses make_audit_report's fixed
    `R1` round + spec_id)."""
    body = (
        "---\n"
        f"checkpoint: {checkpoint}\n"
        f"verdict: {verdict}\n"
        f"converged: {str(converged).lower()}\n"
        f"timestamp: {timestamp}\n"
        "---\n\n# audit\n"
    )
    return write_file(root / ".aria" / "audit-reports" / filename, body)


def _agg_name(checkpoint, r, ts, spec, suffix="aggregated"):
    """Aggregate-report filename, e.g. post_spec-R5-1786272000000-feat-x-aggregated.md."""
    return f"{checkpoint}-R{r}-{ts}-{spec}-{suffix}.md"


def _seat_name(checkpoint, r, ts, spec, agent):
    """Single-seat report filename, e.g. post_spec-R5-1786272000000-feat-x-tech-lead.md."""
    return f"{checkpoint}-R{r}-{ts}-{spec}-{agent}.md"


def _set_mtime(path, seconds_from_epoch):
    os.utime(path, (seconds_from_epoch, seconds_from_epoch))


class TestAuditAbsent(unittest.TestCase):
    def test_no_audit_dir(self):
        """#149 round-2 反驳席点名的早退分支之一 (M3): absent-dir 分支必须仍
        产出 `last_audit_selection.method == "none"`, 不能省略整个字段。"""
        with tmp_project() as root:
            r = collect_audit(root)
            self.assertIsNone(r.data["enabled"])
            self.assertIsNone(r.data["last_audit"])
            sel = r.data.get("last_audit_selection")
            self.assertIsNotNone(sel)
            self.assertEqual(sel.get("method"), "none")
            self.assertIsNone(sel.get("tie_break"))

    def test_empty_audit_dir(self):
        """#149 round-2 反驳席点名的早退分支之二 (M3): empty-dir 分支同样必须
        产出 `last_audit_selection.method == "none"`。"""
        with tmp_project() as root:
            (root / ".aria" / "audit-reports").mkdir(parents=True)
            r = collect_audit(root)
            self.assertTrue(r.data["enabled"])
            self.assertIsNone(r.data["last_audit"])
            sel = r.data.get("last_audit_selection")
            self.assertIsNotNone(sel)
            self.assertEqual(sel.get("method"), "none")
            self.assertIsNone(sel.get("tie_break"))


class TestAuditFrontmatter(unittest.TestCase):
    def test_simple_frontmatter_parsing(self):
        with tmp_project() as root:
            make_audit_report(
                root,
                checkpoint="post_spec",
                verdict="PASS",
                converged=True,
                timestamp="2026-04-24T1000Z",
            )
            r = collect_audit(root)
            self.assertEqual(r.data["last_audit"]["checkpoint"], "post_spec")
            self.assertEqual(r.data["last_audit"]["verdict"], "PASS")
            # R1-I6: boolean coercion
            self.assertIs(r.data["last_audit"]["converged"], True)

    def test_r1_i6_boolean_coercion(self):
        """R1-I6 regression: 'false' string must coerce to False, not stay 'false'."""
        with tmp_project() as root:
            make_audit_report(root, "pre_merge", "FAIL", converged=False)
            r = collect_audit(root)
            self.assertIs(r.data["last_audit"]["converged"], False)


class TestAuditLatestSelection(unittest.TestCase):
    def test_picks_most_recent_by_filename_timestamp_not_mtime(self):
        """#149 round 2: selection must key off the filename-embedded
        timestamp, never off mtime — mtimes are set REVERSED here (the
        filename-older report gets the newer mtime and vice versa) so an
        mtime-driven implementation picks the wrong one."""
        with tmp_project() as root:
            old = make_audit_report(
                root, "post_spec", "OLD", timestamp="2026-01-01T0000Z"
            )
            new = make_audit_report(
                root, "pre_merge", "LATEST", timestamp="2026-04-24T1000Z"
            )
            _set_mtime(old, 9000)  # newer mtime — must NOT win
            _set_mtime(new, 1000)  # older mtime — must still win (later filename ts)

            r = collect_audit(root)

            self.assertEqual(r.data["last_audit"]["verdict"], "LATEST")
            sel = r.data.get("last_audit_selection")
            self.assertEqual(sel.get("method"), "aggregated-filename")
            self.assertEqual(sel.get("ordering"), "filename-timestamp")
            self.assertEqual(sel.get("candidates_scanned"), 2)
            self.assertEqual(sel.get("aggregate_candidates"), 2)
            self.assertEqual(sel.get("unparsed_timestamp"), 0)
            self.assertEqual(sel.get("selected"), new.name)
            self.assertIsNone(sel.get("tie_break"))  # ts's differ — no tie to break


class TestAuditMalformed(unittest.TestCase):
    def test_no_frontmatter(self):
        """Fixture filename must be aggregate-shaped (#149) — a stray-shaped
        file wouldn't be a candidate at all and `last_audit` would come back
        None outright, which is a different case from "candidate selected,
        but its body has no frontmatter" (covered here)."""
        with tmp_project() as root:
            write_file(
                root / ".aria" / "audit-reports" / "post_spec-R1-2026-04-24T1000Z-orphan-aggregated.md",
                "# Just a heading\nno frontmatter\n",
            )
            r = collect_audit(root)
            # Still returns last_audit, but fields are None
            self.assertIsNone(r.data["last_audit"]["checkpoint"])


class TestAuditAggregateOnlySelection(unittest.TestCase):
    """#149: latest-audit selection must key off aggregate-shaped filenames
    and their embedded timestamp token (never raw mtime, never round number
    `R<N>` — round numbers are only meaningful within one spec's own
    convergence loop), and must never fall back to a single-seat report when
    no aggregate candidate exists."""

    def test_no_aggregate_shaped_file_returns_none_not_latest_mtime_file(self):
        """今日现场复刻: 目录里只有非-aggregate 文件 —— 一份无 frontmatter 的
        杂项 audit-trail md (对应仓内真实的
        `linked-issue-normalization-audit-trail.md`), 一份带合法 frontmatter
        但文件名是单席形态的报告。mtime 最新的是杂项文件。

        它怎么会红: 若实现纯按 mtime 排序取 `reports[-1]`, 会把杂项文件当
        `last_audit` 返回 (一个 4 字段皆 None 的 dict, 而非 None 本身) ——
        `assertIsNone(last_audit)` 断言失败; `last_audit_selection` 字段若
        不产出, 第二个断言必红。"""
        with tmp_project() as root:
            seat = _write_report(
                root,
                _seat_name("post_spec", 5, 1786222696514, "noise-spec", "tech-lead"),
                checkpoint="post_spec",
                verdict="PASS",
                converged=True,
            )
            stray = write_file(
                root / ".aria" / "audit-reports" / "linked-issue-normalization-audit-trail.md",
                "# 审计轨\n\n> append-only 杂项笔记, 无 frontmatter\n",
            )
            _set_mtime(seat, 1000)
            _set_mtime(stray, 2000)  # newest — would win under mtime-only logic

            r = collect_audit(root)

            self.assertIsNone(r.data["last_audit"])
            self.assertEqual(
                r.data.get("last_audit_selection"),
                {
                    "method": "none",
                    "ordering": None,
                    "candidates_scanned": 2,
                    "aggregate_candidates": 0,
                    "unparsed_timestamp": 0,
                    "selected": None,
                    "tie_break": None,
                    "reason": "no aggregated report in .aria/audit-reports/",
                },
            )

    def test_selects_sole_aggregate_amid_stray_and_seat_noise(self):
        """负控: 证明修复不矫枉过正 —— 目录里混着无 frontmatter 的杂项文件、
        一份单席报告、以及唯一一份真正的 aggregate, 且 aggregate mtime 全场
        最旧。

        它怎么会红: 若实现按 mtime 取 `reports[-1]`, 会挑中 mtime 最新的
        杂项文件; 即便强制 aggregate mtime 最新也测不出「按文件名结构选」
        这件事本身 —— 所以本测试反其道把 aggregate 设成 mtime 最旧, 专门
        排除「侥幸靠 mtime 蒙对」。"""
        with tmp_project() as root:
            stray = write_file(
                root / ".aria" / "audit-reports" / "unrelated-notes.md",
                "# 笔记\n\n无 frontmatter, 也不是 aggregate 命名\n",
            )
            seat = _write_report(
                root,
                _seat_name("post_spec", 5, 1786272000000, "noise-spec", "tech-lead"),
                checkpoint="post_spec",
                verdict="SEAT_WRONG_VERDICT",
                converged=True,
            )
            agg = _write_report(
                root,
                _agg_name("post_spec", 5, 1786272000000, "noise-spec"),
                checkpoint="post_spec",
                verdict="AGGREGATE_TRUE_VERDICT",
                converged=False,
            )
            _set_mtime(agg, 1000)  # oldest
            _set_mtime(seat, 2000)
            _set_mtime(stray, 3000)  # newest — would win under mtime-only logic

            r = collect_audit(root)

            self.assertEqual(r.data["last_audit"]["verdict"], "AGGREGATE_TRUE_VERDICT")
            self.assertIs(r.data["last_audit"]["converged"], False)
            self.assertEqual(
                r.data.get("last_audit_selection"),
                {
                    "method": "aggregated-filename",
                    "ordering": "filename-timestamp",
                    "candidates_scanned": 3,
                    "aggregate_candidates": 1,
                    "unparsed_timestamp": 0,
                    "selected": agg.name,
                    "tie_break": None,
                },
            )

    def test_aggregate_beats_single_seat_regardless_of_mtime(self):
        """一份 aggregate (mtime 更旧) + 一份单席报告 (mtime 被强制更新)。

        它怎么会红: 若实现按 `reports[-1]` (mtime 最大) 取, 会选中单席
        文件, `verdict` 断言拿到单席的 "PASS_WITH_WARNINGS" 而非 aggregate
        的 "FAIL"。"""
        with tmp_project() as root:
            agg = _write_report(
                root,
                _agg_name("pre_merge", 3, 1786272000000, "feat-x"),
                checkpoint="pre_merge",
                verdict="FAIL",
                converged=False,
            )
            seat = _write_report(
                root,
                _seat_name("pre_merge", 3, 1786272000001, "feat-x", "qa-engineer"),
                checkpoint="pre_merge",
                verdict="PASS_WITH_WARNINGS",
                converged=True,
            )
            _set_mtime(agg, 1000)
            _set_mtime(seat, 5000)

            r = collect_audit(root)

            self.assertEqual(r.data["last_audit"]["verdict"], "FAIL")
            self.assertIs(r.data["last_audit"]["converged"], False)
            sel = r.data.get("last_audit_selection")
            self.assertIsNotNone(sel)
            self.assertEqual(sel.get("method"), "aggregated-filename")
            self.assertEqual(sel.get("ordering"), "filename-timestamp")
            self.assertEqual(sel.get("candidates_scanned"), 2)
            self.assertEqual(sel.get("aggregate_candidates"), 1)
            self.assertEqual(sel.get("unparsed_timestamp"), 0)
            self.assertEqual(sel.get("selected"), agg.name)
            self.assertIsNone(sel.get("tie_break"))  # only one candidate — no tie

    def test_higher_round_number_with_earlier_timestamp_is_not_selected(self):
        """#149 round-2 critical (反驳席): round number `R<N>` must NEVER be
        used for ordering — it is only meaningful within one spec's own
        convergence loop, not across specs/audits. `R10` here carries an
        EARLIER filename timestamp than `R2`; mtime is also set the wrong
        way round (R10 newer, R2 older) to jointly rule out both "picks
        bigger R" and "picks newer mtime" as the true selection rule —
        leaving "picks the later filename timestamp" as the only rule that
        can pass this test.

        它怎么会红: 若实现按 R<N> 排序 (旧一轮方案的核心错误), 会选中
        R10 (verdict "R10_EARLIER_VERDICT"); 若按 mtime 排序, 同样会选中
        R10 (mtime 更新)。两条路径下 `assertEqual(..., "R2_LATER_VERDICT")`
        均红。"""
        with tmp_project() as root:
            r10 = _write_report(
                root,
                _agg_name("post_spec", 10, 1786272000000, "feat-y"),  # 2026-08-09
                checkpoint="post_spec",
                verdict="R10_EARLIER_VERDICT",
                converged=True,
            )
            r2 = _write_report(
                root,
                _agg_name("post_spec", 2, 1787435452341, "feat-y"),  # 2026-08-22, later
                checkpoint="post_spec",
                verdict="R2_LATER_VERDICT",
                converged=False,
            )
            _set_mtime(r10, 9000)  # newer mtime — must NOT win
            _set_mtime(r2, 1000)  # older mtime — must still win (later filename ts)

            r = collect_audit(root)

            self.assertEqual(r.data["last_audit"]["verdict"], "R2_LATER_VERDICT")
            sel = r.data.get("last_audit_selection")
            self.assertEqual(sel.get("ordering"), "filename-timestamp")
            self.assertEqual(sel.get("selected"), r2.name)
            self.assertIsNone(sel.get("tie_break"))  # ts's differ — round never even compared

    def test_tied_round_number_across_specs_breaks_by_filename_timestamp(self):
        """两个不同 spec 各有一份 R5 aggregate (轮次号打平, 且轮次号本就不该
        参与排序)。ts 更小的那份被强制成 mtime 更新、且其 spec 名
        (`zzz-spec`) 字母序排在 ts 更大那份 (`aaa-spec`) 后面 —— 同时排除
        「mtime 优先」与「spec 名字母序优先」两种误判, 只留「filename
        timestamp 更大者胜」这一条真规则。

        它怎么会红: 若实现按 mtime 选, 会选中 mtime 更新、ts 更小的那份,
        verdict 断言拿到 "LOWER_TS_VERDICT" 而非 "HIGHER_TS_VERDICT"。"""
        with tmp_project() as root:
            lower_ts = _write_report(
                root,
                _agg_name("post_spec", 5, 1786272000000, "zzz-spec"),
                checkpoint="post_spec",
                verdict="LOWER_TS_VERDICT",
                converged=True,
            )
            higher_ts = _write_report(
                root,
                _agg_name("post_spec", 5, 1786272000001, "aaa-spec"),
                checkpoint="post_spec",
                verdict="HIGHER_TS_VERDICT",
                converged=False,
            )
            _set_mtime(higher_ts, 1000)  # older mtime
            _set_mtime(lower_ts, 9000)  # newer mtime — must NOT win

            r = collect_audit(root)

            self.assertEqual(r.data["last_audit"]["verdict"], "HIGHER_TS_VERDICT")
            sel = r.data.get("last_audit_selection")
            self.assertEqual(sel.get("unparsed_timestamp"), 0)
            self.assertEqual(sel.get("selected"), higher_ts.name)
            self.assertIsNone(sel.get("tie_break"))  # ts's differ (by 1ms) — not a real tie

    def test_candidate_missing_round_or_timestamp_token_counts_as_unparsed_and_loses(self):
        """#149 round-2 反驳席点名缺口: 一份候选文件名以 `-aggregated.md`
        结尾但完全不带 `-R<N>-` 标记 (因而也就没有可解析的 timestamp
        token), 与一份形态完整、timestamp 可解析的候选并存。tokenless 那份
        被强制成更新 mtime, 用来同时排除「侥幸靠 mtime 蒙对」。

        它怎么会红: 若实现对「候选存在但 token 缺失」没有专门分支 (例如
        误用 -1/空串当排序键退化成最大值), tokenless 文件反而可能被选中;
        `unparsed_timestamp` 计数若未实现, 断言直接因缺键 (None != 1) 落
        空。"""
        with tmp_project() as root:
            valid = _write_report(
                root,
                _agg_name("post_spec", 3, 1786272000000, "feat-z"),
                checkpoint="post_spec",
                verdict="VALID_TS_VERDICT",
                converged=True,
            )
            tokenless = _write_report(
                root,
                "post_spec-orphan-notoken-aggregated.md",
                checkpoint="post_spec",
                verdict="TOKENLESS_VERDICT",
                converged=False,
            )
            _set_mtime(valid, 1000)
            _set_mtime(tokenless, 9000)  # newer mtime — must NOT win (a parsed rival exists)

            r = collect_audit(root)

            self.assertEqual(r.data["last_audit"]["verdict"], "VALID_TS_VERDICT")
            sel = r.data.get("last_audit_selection")
            self.assertEqual(sel.get("method"), "aggregated-filename")
            self.assertEqual(sel.get("ordering"), "filename-timestamp-partial")
            self.assertEqual(sel.get("candidates_scanned"), 2)
            self.assertEqual(sel.get("aggregate_candidates"), 2)
            self.assertEqual(sel.get("unparsed_timestamp"), 1)
            self.assertEqual(sel.get("selected"), valid.name)
            self.assertIsNone(sel.get("tie_break"))  # the parsed candidate uniquely tops has_ts

    def test_all_candidates_unparsed_falls_back_to_mtime(self):
        """全部候选文件名都缺 `-R<N>-timestamp` token 时, 唯一诚实可用的信号
        只剩 mtime —— 必须显式退回 mtime, 且 `ordering` 必须标成
        `"mtime-fallback"` 而不是悄悄冒充 `"filename-timestamp"`。

        它怎么会红: 若「解析失败排最后」被实现成让 unparsed 候选永远选不中
        (而不是在全体 unparsed 时退回 mtime), 两份候选都拿不到 last_audit
        (None), `assertIsNotNone` 或 verdict 断言落空; `ordering` 若被错误
        标成 "filename-timestamp" 或干脆不出现, 对应断言落空。"""
        with tmp_project() as root:
            alpha = _write_report(
                root,
                "post_spec-alpha-notoken-aggregated.md",
                checkpoint="post_spec",
                verdict="ALPHA_VERDICT",
                converged=True,
            )
            beta = _write_report(
                root,
                "post_spec-beta-notoken-aggregated.md",
                checkpoint="post_spec",
                verdict="BETA_VERDICT",
                converged=False,
            )
            _set_mtime(alpha, 1000)
            _set_mtime(beta, 9000)  # newer mtime — must win (mtime is the only signal left)

            r = collect_audit(root)

            self.assertEqual(r.data["last_audit"]["verdict"], "BETA_VERDICT")
            sel = r.data.get("last_audit_selection")
            self.assertEqual(sel.get("method"), "aggregated-filename")
            self.assertEqual(sel.get("ordering"), "mtime-fallback")
            self.assertEqual(sel.get("candidates_scanned"), 2)
            self.assertEqual(sel.get("aggregate_candidates"), 2)
            self.assertEqual(sel.get("unparsed_timestamp"), 2)
            self.assertEqual(sel.get("selected"), beta.name)
            # both candidates are tied at (has_ts=False) AND neither carries
            # a round marker (round_num=-inf for both) — mtime is the only
            # level left to discriminate, hence "mtime" not "round"/None.
            self.assertEqual(sel.get("tie_break"), "mtime")


class TestAuditAggregateSpellingCompat(unittest.TestCase):
    """负控组: 证明 filename-structure 判据既不漏检合法拼写, 也不误伤唯一
    合法候选存在时的正常路径 —— 修复只该收紧「谁能当候选」, 不该在候选
    确定之后把既有解析行为改错。"""

    def test_canonical_aggregated_spelling_selected_with_all_fields_intact(self):
        """#149 明确要求「有 aggregate 时仍选对」: 唯一一份合法 `-aggregated.md`
        报告存在时, 既有 4 个字段 + path 必须照旧被正确解析, 同时新增的
        `last_audit_selection` 字段必须完整出现。"""
        with tmp_project() as root:
            agg = _write_report(
                root,
                _agg_name("post_spec", 2, 1786272000000, "only-spec"),
                checkpoint="post_spec",
                verdict="PASS",
                converged=True,
                timestamp="2026-08-01T0000Z",
            )
            r = collect_audit(root)

            self.assertEqual(r.data["last_audit"]["checkpoint"], "post_spec")
            self.assertEqual(r.data["last_audit"]["verdict"], "PASS")
            self.assertIs(r.data["last_audit"]["converged"], True)
            self.assertEqual(r.data["last_audit"]["timestamp"], "2026-08-01T0000Z")
            self.assertEqual(r.data["last_audit"]["path"], str(agg.relative_to(root)))
            self.assertEqual(
                r.data.get("last_audit_selection"),
                {
                    "method": "aggregated-filename",
                    "ordering": "filename-timestamp",
                    "candidates_scanned": 1,
                    "aggregate_candidates": 1,
                    "unparsed_timestamp": 0,
                    "selected": agg.name,
                    "tie_break": None,
                },
            )

    def test_legacy_aggregate_spelling_without_trailing_d_still_recognized(self):
        """兼容旧拼写: 仓内大量既存文件用 `-aggregate.md` (无尾 d), 例如
        `premerge-gate-mainbranch-failclosed-aggregate.md`。唯一文件即是这种
        旧拼写时, 必须仍被当 aggregate 候选选中, 不能因为新判据只认
        `-aggregated.md` 而漏检退化成 `last_audit=None`。"""
        with tmp_project() as root:
            agg = _write_report(
                root,
                _agg_name("post_spec", 4, 1786272000000, "legacy-spec", suffix="aggregate"),
                checkpoint="post_spec",
                verdict="FAIL",
                converged=False,
            )
            r = collect_audit(root)

            self.assertIsNotNone(r.data["last_audit"])
            self.assertEqual(r.data["last_audit"]["verdict"], "FAIL")
            sel = r.data.get("last_audit_selection")
            self.assertIsNotNone(sel)
            self.assertEqual(sel.get("method"), "aggregated-filename")
            self.assertEqual(sel.get("ordering"), "filename-timestamp")
            self.assertEqual(sel.get("selected"), agg.name)
            self.assertIsNone(sel.get("tie_break"))  # only one candidate — no tie

    def test_aggregate_suffix_requires_leading_dash_negative_controls(self):
        """#149 round-3 反驳席点名缺口 (M3 负控): 候选判据 = 文件名以
        `-aggregated.md` 或 `-aggregate.md` **结尾** (含前导 `-`)。三个近似但
        不合格的文件名混入同目录, 都不该被计入 `aggregate_candidates`:
        - `my-aggregate-notes.md`: 含 "aggregate" 子串, 但真正的结尾是
          `-notes.md`;
        - `aggregated-summary.md`: 以 "aggregated" 开头, 但结尾是
          `-summary.md`;
        - `aggregate.md`: 文件名本身就是 "aggregate.md", 结尾字符串
          "aggregate.md" 比 "-aggregate.md" 短一位, 没有前导 `-`。

        它怎么会红: 若判据退化成纯子串匹配 (`"aggregate" in name`) 或漏掉
        前导 `-` 要求, 这三份文件会被误记入 `aggregate_candidates`
        (从 1 变成 4), `candidates_scanned` 断言仍对但
        `aggregate_candidates`/`selected` 断言落空。"""
        with tmp_project() as root:
            write_file(
                root / ".aria" / "audit-reports" / "my-aggregate-notes.md",
                "# 笔记\n\n不是候选\n",
            )
            write_file(
                root / ".aria" / "audit-reports" / "aggregated-summary.md",
                "# 摘要\n\n不是候选\n",
            )
            write_file(
                root / ".aria" / "audit-reports" / "aggregate.md",
                "# 无前导 dash\n\n不是候选\n",
            )
            real = _write_report(
                root,
                _agg_name("post_spec", 1, 1786272000000, "feat-neg"),
                checkpoint="post_spec",
                verdict="REAL_AGGREGATE_VERDICT",
                converged=True,
            )

            r = collect_audit(root)

            self.assertEqual(r.data["last_audit"]["verdict"], "REAL_AGGREGATE_VERDICT")
            sel = r.data.get("last_audit_selection")
            self.assertEqual(sel.get("candidates_scanned"), 4)
            self.assertEqual(sel.get("aggregate_candidates"), 1)
            self.assertEqual(sel.get("selected"), real.name)


class TestAuditTimestampTokenShapes(unittest.TestCase):
    """#149 round 3 (M1/M3): timestamp-token parsing is no longer anchored
    on `-R<N>-`. These tests target the scanning/parsing rules directly —
    ISO date+time precision, epoch/ISO compared on one timeline, the exact
    13-digit epoch threshold, graceful degradation on a malformed time
    part, and the three non-bare-integer round-marker shapes the round-2
    challenger seat pointed out weren't covered (`FINAL`, `R5.5`,
    `R1-R2` merged)."""

    def test_iso_date_and_time_ordering_same_day_different_time(self):
        """两份候选同日不同时 (`2026-07-12T1000Z` vs `T2200Z`), 轮次号相同
        (都是 R1) 以隔离出"仅比较日期"这一种坏实现。mtime 反向设置。

        它怎么会红: 若实现只解析出日期部分丢弃时间 (`_ISO_DATE` 类正则未真正
        消费/比较 time part), 两个候选会被判定"时间相同"从而落到 round
        (相同, R1) 再落到 mtime —— mtime 更新的 EARLY 候选会被选中,
        `assertEqual(..., "LATE_VERDICT")` 落空。"""
        with tmp_project() as root:
            early = _write_report(
                root,
                "post_spec-R1-2026-07-12T1000Z-feat-daytime-aggregated.md",
                checkpoint="post_spec",
                verdict="EARLY_VERDICT",
                converged=True,
            )
            late = _write_report(
                root,
                "post_spec-R1-2026-07-12T2200Z-feat-daytime-aggregated.md",
                checkpoint="post_spec",
                verdict="LATE_VERDICT",
                converged=False,
            )
            _set_mtime(early, 9000)  # newer mtime — must NOT win
            _set_mtime(late, 1000)  # older mtime — must still win (later time-of-day)

            r = collect_audit(root)

            self.assertEqual(r.data["last_audit"]["verdict"], "LATE_VERDICT")
            sel = r.data.get("last_audit_selection")
            self.assertEqual(sel.get("unparsed_timestamp"), 0)
            self.assertEqual(sel.get("selected"), late.name)
            self.assertIsNone(sel.get("tie_break"))  # real ts's differ by time-of-day

    def test_epoch_and_iso_candidates_compared_on_one_timeline_not_bucketed(self):
        """一份 epoch-ms 候选 (2026-08-22) 与一份 ISO 候选 (2026-01-01) 混排,
        epoch 候选是真正更晚的一方; mtime 反向设置排除侥幸命中。

        它怎么会红: 若实现把两种 token 形态"分桶"各自处理 (例如各自
        `max()` 一次再任意合并/优先某一桶), 而不是解析成同一 UTC 时间轴
        比较, ISO 候选可能因为其桶被优先或因反向 mtime 生效而胜出,
        `assertEqual(..., "EPOCH_LATE_VERDICT")` 落空。"""
        with tmp_project() as root:
            iso_early = _write_report(
                root,
                "post_spec-R1-2026-01-01T0000Z-feat-mix-aggregated.md",
                checkpoint="post_spec",
                verdict="ISO_EARLY_VERDICT",
                converged=True,
            )
            epoch_late = _write_report(
                root,
                "post_spec-R1-1787435452341-feat-mix-aggregated.md",  # 2026-08-22
                checkpoint="post_spec",
                verdict="EPOCH_LATE_VERDICT",
                converged=False,
            )
            _set_mtime(iso_early, 9000)  # newer mtime — must NOT win
            _set_mtime(epoch_late, 1000)  # older mtime — must still win (later real ts)

            r = collect_audit(root)

            self.assertEqual(r.data["last_audit"]["verdict"], "EPOCH_LATE_VERDICT")
            sel = r.data.get("last_audit_selection")
            self.assertEqual(sel.get("unparsed_timestamp"), 0)
            self.assertEqual(sel.get("selected"), epoch_late.name)

    def test_epoch_13_digit_threshold_rejects_12_and_14_digit_tokens(self):
        """#149 round-3 明确要求的门槛测试: 12 位 (`123456789012`) 与 14 位
        紧凑日期 (`20260714123456`) 两个 token 都**不算** epoch —— 只有恰好
        13 位才算。第三份候选携带真正的 13 位 epoch (2026 年代), mtime 全部
        设成比它更新, 专门排除"侥幸靠 mtime 蒙对"。

        它怎么会红: 若实现沿用旧一轮 `≥12` 门槛 (`\\d{12,}`, 贪婪匹配),
        14 位串会被整体吃下解析成 2612 年前后的日期, 从而在时间轴上"胜过"
        所有 2026 年代的候选 —— `selected` 断言落空; 12 位串同样会被
        误吃解析成 1973 年前后的日期 (虽不会赢, 但会被算作"已解析"), 二者
        任一被算作已解析都会让 `unparsed_timestamp` 从期望的 2 掉到 <2,
        断言落空。"""
        with tmp_project() as root:
            valid = _write_report(
                root,
                "post_spec-R1-1786272000000-feat-thresh-aggregated.md",  # 13 digits, real 2026 ts
                checkpoint="post_spec",
                verdict="VALID_13_VERDICT",
                converged=True,
            )
            twelve = _write_report(
                root,
                "post_spec-R1-123456789012-feat-thresh-aggregated.md",  # 12 digits
                checkpoint="post_spec",
                verdict="TWELVE_DIGIT_VERDICT",
                converged=False,
            )
            fourteen = _write_report(
                root,
                "post_spec-R1-20260714123456-feat-thresh-aggregated.md",  # 14 digits — compact date
                checkpoint="post_spec",
                verdict="FOURTEEN_DIGIT_VERDICT",
                converged=False,
            )
            _set_mtime(valid, 1000)
            _set_mtime(twelve, 9000)  # newer mtime — must NOT matter, must NOT parse as epoch
            _set_mtime(fourteen, 9500)  # newer mtime — must NOT matter, must NOT parse as epoch

            r = collect_audit(root)

            self.assertEqual(r.data["last_audit"]["verdict"], "VALID_13_VERDICT")
            sel = r.data.get("last_audit_selection")
            self.assertEqual(sel.get("aggregate_candidates"), 3)
            self.assertEqual(sel.get("unparsed_timestamp"), 2)
            self.assertEqual(sel.get("selected"), valid.name)

    def test_malformed_time_part_after_valid_date_degrades_to_date_precision_not_none(self):
        """`2026-05-17T03Z` 的 `T03Z` 既非 4 位也非 6 位紧凑时间, 但日期部分
        `2026-05-17` 本身合法 —— 定稿要求退化为当日 00:00 精度, 不是整体
        判 None。另一候选是纯日期 `2026-01-01` (更早), mtime 反向设置。

        它怎么会红: 若实现让时间段解析失败连累整个 token 判 None, 该候选会
        沦为 unparsed (`unparsed_timestamp` 从期望的 0 变成 1), 且因
        unparsed 天然排在任何已解析候选之后, 会被 2026-01-01 那份比下去
        (尽管其 mtime 更旧) —— `selected`/`unparsed_timestamp` 断言均落空。"""
        with tmp_project() as root:
            degraded = _write_report(
                root,
                "post_spec-R1-2026-05-17T03Z-feat-degrade-aggregated.md",
                checkpoint="post_spec",
                verdict="DEGRADED_DATE_VERDICT",
                converged=True,
            )
            earlier = _write_report(
                root,
                "post_spec-R1-2026-01-01-feat-degrade-aggregated.md",
                checkpoint="post_spec",
                verdict="EARLIER_DATE_VERDICT",
                converged=False,
            )
            _set_mtime(degraded, 1000)  # older mtime — must still win (later date, once parsed)
            _set_mtime(earlier, 9000)  # newer mtime — must NOT win

            r = collect_audit(root)

            self.assertEqual(r.data["last_audit"]["verdict"], "DEGRADED_DATE_VERDICT")
            sel = r.data.get("last_audit_selection")
            self.assertEqual(sel.get("unparsed_timestamp"), 0)
            self.assertEqual(sel.get("selected"), degraded.name)

    def test_final_r5point5_and_merged_round_markers_all_parse_to_a_timestamp(self):
        """#149 round-2 反驳席点名的三种真实仓文件名形态 (M1): `FINAL`
        (无数字轮次)、`R5.5` (小数轮次)、`R1-R2` (合并轮, 本身含一个
        `-R1-`形态的子串) —— round 3 要求这三种候选的文件名时间戳**全部**
        必须被解析到 (不计入 `unparsed_timestamp`), 因为解析不再以
        `-R<N>-` 定位, 而是独立扫描 token 形态本身。

        它怎么会红: 若实现仍然像 round 2 一样先找 `-R<N>-` 再从其后开始扫
        timestamp, `FINAL`/`R5.5`/`R1-R2` 三种情形至少有一种会定位失败
        (FINAL 无 `-R<N>-` 可匹配; R1-R2 的第一个 `-R1-` 后紧跟的是 "R2"
        不是 timestamp) 从而落 `unparsed_timestamp > 0`, 断言落空。"""
        with tmp_project() as root:
            final_file = _write_report(
                root,
                "post_spec-FINAL-1783602519132-feat-shapes-a-aggregated.md",  # 2026-07-09
                checkpoint="post_spec",
                verdict="FINAL_VERDICT",
                converged=True,
            )
            r5_5_file = _write_report(
                root,
                "post_spec-R5.5-1786276800000-feat-shapes-b-aggregated.md",  # 2026-08-09, latest
                checkpoint="post_spec",
                verdict="R5POINT5_VERDICT",
                converged=False,
            )
            merged_file = _write_report(
                root,
                "post_spec-R1-R2-2026-07-12T1850Z-feat-shapes-c-aggregated.md",  # 2026-07-12
                checkpoint="post_spec",
                verdict="MERGED_VERDICT",
                converged=True,
            )

            r = collect_audit(root)

            sel = r.data.get("last_audit_selection")
            self.assertEqual(sel.get("aggregate_candidates"), 3)
            self.assertEqual(sel.get("unparsed_timestamp"), 0)
            # 2026-08-09 (R5.5) is chronologically latest among the three.
            self.assertEqual(r.data["last_audit"]["verdict"], "R5POINT5_VERDICT")
            self.assertEqual(sel.get("selected"), r5_5_file.name)


class TestAuditTieBreak(unittest.TestCase):
    """#149 round 3 (M2): same-timestamp ties now break by round number
    BEFORE mtime — the three-tier `(parsed_ts, round_num, mtime)` sort key
    — and `last_audit_selection.tie_break` records which tier actually
    discriminated the winner."""

    def test_same_timestamp_seven_way_tie_breaks_by_round_number_not_mtime(self):
        """现场复刻: 真实仓 `pre-merge-gate-no-run-for-branch` 审计的 7 份
        aggregate (R1..R7) 共享同一文件名 timestamp (`1787379154696`),
        R7 是收敛通过的那份。mtime 被强制**反向**设置 (R1 最新, R7 最旧)
        专门排除"侥幸靠 mtime 蒙对"。

        它怎么会红: 若 tie 仍直接落到 mtime (round 2 的行为), 会选中 R1
        (mtime 最新), `assertEqual(..., "CONVERGED_VERDICT")` 落空;
        `tie_break` 若不是 `"round"` 也说明三级排序键未真正生效。"""
        with tmp_project() as root:
            files = {}
            for n in range(1, 8):
                verdict = "CONVERGED_VERDICT" if n == 7 else f"R{n}_VERDICT"
                files[n] = _write_report(
                    root,
                    f"post_spec-R{n}-1787379154696-pre-merge-gate-no-run-for-branch-aggregated.md",
                    checkpoint="post_spec",
                    verdict=verdict,
                    converged=(n == 7),
                )
                # R1 newest mtime .. R7 oldest mtime — the reverse of round order.
                _set_mtime(files[n], (8 - n) * 1000)

            r = collect_audit(root)

            self.assertEqual(r.data["last_audit"]["verdict"], "CONVERGED_VERDICT")
            self.assertIs(r.data["last_audit"]["converged"], True)
            sel = r.data.get("last_audit_selection")
            self.assertEqual(sel.get("aggregate_candidates"), 7)
            self.assertEqual(sel.get("unparsed_timestamp"), 0)
            self.assertEqual(sel.get("selected"), files[7].name)
            self.assertEqual(sel.get("tie_break"), "round")

    def test_full_tie_on_timestamp_and_round_breaks_by_mtime(self):
        """两份候选 timestamp 与 round 都相同 (不同 spec 名下的巧合平手),
        只有 mtime 不同 —— 这是 mtime 真正该出场的唯一层级, 与"全体 unparsed
        退回 mtime" (`mtime-fallback`) 是不同的分支: 这里 ts 本身是可解析
        的, `ordering` 必须仍是 `"filename-timestamp"`。

        它怎么会红: 若 `tie_break` 计算把"round 也打平"错误地当成
        `"round"` 而非继续下探 mtime, 断言 `tie_break == "mtime"` 落空;
        若 `ordering` 被误标成 `"mtime-fallback"` (与 ts 全部 unparsed 的
        情形混淆), 对应断言落空。"""
        with tmp_project() as root:
            older = _write_report(
                root,
                "post_spec-R3-1786272000000-feat-tieA-aggregated.md",
                checkpoint="post_spec",
                verdict="OLDER_MTIME_VERDICT",
                converged=True,
            )
            newer = _write_report(
                root,
                "post_spec-R3-1786272000000-feat-tieB-aggregated.md",
                checkpoint="post_spec",
                verdict="NEWER_MTIME_VERDICT",
                converged=False,
            )
            _set_mtime(older, 1000)
            _set_mtime(newer, 9000)

            r = collect_audit(root)

            self.assertEqual(r.data["last_audit"]["verdict"], "NEWER_MTIME_VERDICT")
            sel = r.data.get("last_audit_selection")
            self.assertEqual(sel.get("ordering"), "filename-timestamp")
            self.assertEqual(sel.get("selected"), newer.name)
            self.assertEqual(sel.get("tie_break"), "mtime")


if __name__ == "__main__":
    unittest.main()


class TestAuditRound3Residuals(unittest.TestCase):
    """#149 round-3 rebuttal residuals: each design item that had code but no
    test now has one with rejection power (a bad implementation that drops
    the feature goes red). How each goes red is stated per test."""

    def test_ordering_is_partial_when_some_candidates_unparsed(self):
        """Mixed pool (1 parsed + 1 unparsed) -> "filename-timestamp-partial".
        How it goes red: round-2's two-state ordering reports plain
        "filename-timestamp"."""
        with tmp_project() as root:
            _write_report(root, _agg_name("post_spec", 1, "1786272000000", "x"), checkpoint="post_spec", verdict="PASS", converged=True)
            _write_report(root, "post_spec-R2-no-token-here-x-aggregated.md", checkpoint="post_spec", verdict="FAIL", converged=False)
            sel = collect_audit(root).data["last_audit_selection"]
            self.assertEqual(sel["unparsed_timestamp"], 1)
            self.assertEqual(sel["ordering"], "filename-timestamp-partial")
            self.assertEqual(sel["selected"], _agg_name("post_spec", 1, "1786272000000", "x"))

    def test_final_round_marker_beats_numbered_round_on_same_timestamp(self):
        """Same token, `FINAL` vs `R9`: FINAL (= +inf round) wins with mtime
        reversed. How it goes red: treating FINAL as "no marker" (-inf) lets
        R9 win."""
        with tmp_project() as root:
            ts = "1786272000000"
            r9 = _write_report(root, _agg_name("post_spec", 9, ts, "x"), checkpoint="post_spec", verdict="FAIL", converged=False)
            fin = _write_report(root, f"post_spec-FINAL-{ts}-x-aggregated.md", checkpoint="post_spec", verdict="PASS", converged=True)
            _set_mtime(fin, 1_000_000); _set_mtime(r9, 2_000_000)
            d = collect_audit(root).data
            self.assertEqual(d["last_audit_selection"]["selected"], fin.name)
            self.assertEqual(d["last_audit"]["verdict"], "PASS")
            self.assertEqual(d["last_audit_selection"]["tie_break"], "round")

    def test_fractional_round_marker_orders_numerically(self):
        """Same token, `R5.5` vs `R5`: 5.5 > 5 wins with mtime reversed. How it
        goes red: an integer-only round regex parses R5.5 as -inf."""
        with tmp_project() as root:
            ts = "1786272000000"
            r5 = _write_report(root, _agg_name("post_spec", 5, ts, "x"), checkpoint="post_spec", verdict="FAIL", converged=False)
            r55 = _write_report(root, f"post_spec-R5.5-{ts}-x-aggregated.md", checkpoint="post_spec", verdict="PASS", converged=True)
            _set_mtime(r55, 1_000_000); _set_mtime(r5, 2_000_000)
            d = collect_audit(root).data
            self.assertEqual(d["last_audit_selection"]["selected"], r55.name)
            self.assertEqual(d["last_audit"]["verdict"], "PASS")

    def test_six_digit_time_and_milliseconds_participate_in_ordering(self):
        """Same day: `T220340-999Z` beats `T220340-100Z` and `T2203Z`. How it
        goes red: a parser reading only HHMM (or dropping `-mmm`) ties them and
        falls to round (equal) then mtime — which favours the EARLIEST file."""
        with tmp_project() as root:
            early = _write_report(root, "post_spec-R1-2026-07-12T2203Z-x-aggregated.md", checkpoint="post_spec", verdict="FAIL", converged=False)
            mid = _write_report(root, "post_spec-R1-2026-07-12T220340-100Z-y-aggregated.md", checkpoint="post_spec", verdict="FAIL", converged=False)
            late = _write_report(root, "post_spec-R1-2026-07-12T220340-999Z-z-aggregated.md", checkpoint="post_spec", verdict="PASS", converged=True)
            _set_mtime(late, 1_000_000); _set_mtime(mid, 2_000_000); _set_mtime(early, 3_000_000)
            d = collect_audit(root).data
            self.assertEqual(d["last_audit_selection"]["selected"], late.name)
            self.assertIsNone(d["last_audit_selection"]["tie_break"])

