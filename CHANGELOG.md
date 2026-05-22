# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.23.1] - 2026-05-22

### Fixed — state-scanner `_status` lifecycle-head extraction range (aria-plugin #50)

Spec `state-scanner-status-extraction-range` (Forgejo aria-plugin #50). `_extract_status` 抓取 `> **Status**: ...` 单行时**对单行长度无上限**。大型 spec 把 Status 字段当 mini-changelog 写成 1500+ chars 一长行时,`_normalize_status` 的 `done`/`complete` fallback 会 word-boundary 命中埋在子任务叙述里的 token,把仍 archival-blocked 的 spec 错归 `done` → 错放进 `openspec.pending_archive[]`,污染归档推荐。与已修的 #101 (substring-shadow) 同源不同面 —— #101 修了匹配方式,#50 修提取范围。

- **`_status_lifecycle_head(raw)`** — 新 helper,把 raw Status 截到第一个文档化分隔符 (em-dash `—` / en-dash `–` / 空格包围 ASCII hyphen ` - ` / 半全角分号 `;` `；` / 全角句号 `。`) 前的 lifecycle 头段;逗号 `,` 与 ASCII 句号 `.` 刻意排除 (保护 `Approved, revised` / `v2.0`)。`_normalize_status` 改在头段上分类,签名 `(raw) -> str` 不变。
- **`_status_field_overlong(raw)`** — 新瘦谓词;头段无分隔符且超 200 字符时,`openspec.py` + `requirements.py` collector 发 `status_field_truncated` soft_error (经 scan.py 聚合进 snapshot `errors[]`,exit 10 路径)。
- **token 字典扩展** — `delivered` / `shipped` 加入 `implemented` 分支 (post-merge 已交付语义)。
- `_extract_status` 本身不变 —— `raw_status` 字段仍保留完整 Status 叙述供人类展示 (`raw_status` full / `status` from-head 职责分离)。
- 23 个 regression test (`TestStatusExtractionRangeIssue50Fix` 20 + 2 e2e + 1 requirements e2e);#101 (13) + #73 (8) 既有 regression 全过,0 regression。
- post_spec audit 5-agent convergence R1 (1 Critical + ~10 Important) → R2 → R3 CONVERGED。

## [1.23.0] - 2026-05-20

### Added — state-scanner Phase 1.6.1 inline carry-forward surfacing

Spec `state-scanner-inline-carry-forward-surfacing`(Forgejo Aria #90 primary + #89 superset variant B):state-scanner Phase 1.6 OpenSpec collector 之前**仅**输出 active changes 的 status / id / path 而**完全不识别** `openspec/changes/*/tasks.md` 内累积的 inline `[carry-forward|TODO|defer(red)?|known[ -]gap|PASS-with-note]` 注释。Multi-session AI 接手时对该 backlog blind。

#### Collector enhancement

- **`scripts/collectors/openspec.py`** 新 helper `_extract_carry_forward_annotations(tasks_md_content) -> list[str]`:
  - Pattern: `r'\[(?:carry-forward|TODO|defer(?:red)?|known[ -]gap|PASS-with-note)\b[\s\S]*?\]'`
  - Positional anchoring(token 紧贴 `[`)+ token-end `\b`(防 substring extension `[carry-forwarded-stuff]`)+ `[\s\S]*?` 非贪婪跨行
  - Multi-line normalization:`\r\n` + `\n` + `\r` → single space(CRLF + LF + 单 CR 全 multi-platform)
  - INCLUDE annotations 在 ```` ``` ```` code blocks 和 `<!-- ... -->` HTML 注释内
- `collect_openspec` 集成:per-active-change scan tasks.md(missing OK,silently skip),累积到顶层新字段 `openspec.carry_forward_inventory = {total, active_change_count, by_change}`,empty 时 `total=0` field always present
- Scope:**仅** `openspec/changes/*/tasks.md`(active only,archive 严格不扫,`proposal.md` 不扫)

#### 2-tier recommendation rules

- **`RECOMMENDATION_RULES.md`** 新 §1.89 + §1.895(2-tier 避免 silent floor):
  - `carry_forward_info`(INFO,priority 1.89,1≤total<5,non-blocking)
  - `carry_forward_pile`(WARNING,priority 1.895,total≥5,non-blocking)

#### Tests + dogfood

- **16 unit tests** `tests/test_openspec.py::TestCarryForwardInventory`:9 core + 7 R1-audit gap fills(empty tasks.md / missing tasks.md / proposal.md negative scope / CRLF / nested brackets / archive substring / code-block + HTML comment INCLUDE)
- Full regression: **584/584 tests PASS**
- **Live dogfood**(B.6): baseline 4 → inject 5 → 9 exact match → cleanup → 4 baseline restored,atomicity verified(git diff 0 lines)
- **Rule #6 structural deterministic benchmark**: `aria-plugin-benchmarks/structural/state-scanner-carry-forward/README.md` — AUTO_GATE=true via binary verification per `feedback_rule6_framing_differs_by_skill_type`

#### Schema + docs

- `references/state-snapshot-schema.md` adds `openspec.carry_forward_inventory` schema(additive,schema_version 仍 1.0)
- `SKILL.md` Phase 1.6 表格标注 `carry_forward_inventory` v1.23.0+

#### Audit history

- R1(post_spec): all REVISE,0 critical / ~5 majors / ~12 minors;multi-agent 共识 3/3 Q1 dispatcher + 2/3 regex word-boundary + threshold tier
- R2: all PASS_WITH_WARNINGS,all R1 majors ADDRESSED + 0 new critical/major
- Convergence per `feedback_post_spec_audit_pragmatic_convergence`:unanimous PASS-tier + verdict 改善 + 无振荡 + 0 critical/major

#### Forgejo issues

- Closes #90(primary) + #89(superset variant B per close-by-reference selection table in proposal §Success Criteria)

## [1.22.1] - 2026-05-20

### Fixed — Zero-day dogfood bugs in v1.22.0 handoff collector

3 production bugs surfaced at first dogfood use(同日 v1.22.0 ship 后立即手动跑
`collect_handoff_multibranch` 验证 Layer H 多 track 看板时发现,符合 P2 closeout
Round 8 tech-lead Finding #4 + 新 datetime bug,两 terminals 的 frontmatter 都被误标 legacy):

- **`scripts/collectors/handoff.py::parse_handoff_frontmatter`**:
  YAML 自动把 ISO 8601 timestamp(`updated-at: 2026-05-20T04:50:34Z`)解析为
  `datetime.datetime` 对象,parser `isinstance(val, str)` 类型守卫返回 None →
  全部 v1.22.0+ handoff 被误标 legacy。**Fix**: coerce `datetime.datetime` 或
  `datetime.date` 为规范化 ISO 8601 string (UTC + 'Z' suffix) 后再做 type guard。

- **`scripts/collectors/handoff_multibranch.py::_list_origin_branches`**:
  `git for-each-ref` sort 用 `--sort=-committerdate`(本 hotfix 加),但函数末尾
  `return sorted(branches), None` **再 sort 一次撤销 git 排序** → 20-branch cap 仍
  按字典序选 archive/* + bugfix/* 而非 master/feature/*。Round 8 tech-lead Finding #4
  实质未 fix(那次 fix 只改了 git 命令但漏掉 Python re-sort)。**Fix**: 移除
  `sorted()` 保留 git committerdate desc 顺序;cap 现在按 committerdate 倒序取 top 20。

- **(配套)** Stale "lexicographic order" 错误消息文本更新为 "most-recent by committerdate"。

### Verified

- 双终端实测:`multi-terminal-coordination` (simonfish/dev-claude2, D.3, done) +
  `aria-2-0-m5-replay-reconciler-drift-review-loop-audit` (simonfish/dev-claude, D.3, active)
  都正确出现在 NON-LEGACY tracks 列表
- 108 tests still PASS(无回归)
- 直接 hotfix branch(small isolated patch,不另开 spec)

### Meta dogfood note

3 个 bugs 在 v1.22.0 ship 后 5 分钟内、同日 dogfood 暴露 + 即时修复 ship — spec ship
过程中 5 次真实 race events + 3 次 production bugs 立即可见,**solution validates
itself by being needed AND fixing itself during its own day-zero use**。Memory entry
`feedback_meta_dogfood_solution_validates_self_mid_ship` 沉淀此 pattern。

---

## [1.22.0] - 2026-05-20

### Added — Multi-terminal coordination (Layer H + Layer L + Design A)

Per OpenSpec change `multi-terminal-coordination` (Approved 2026-05-19, per DEC-20260519-001).
Methodology extension addressing multi-terminal concurrent development including **cross-container** (no shared filesystem) scenarios. Real-world race events observed during this ship cycle motivated all three layers (接错棒 / 重复劳动 / 工作树污染).

**Implementation** (3 layers, advisory + 最终一致, pure git remote 不绑 Forgejo):

- **Layer H — Handoff frontmatter schema (Rule #9 §2.3 extension)**:
  - 5 字段机读 frontmatter (`track-id` / `owner-container` / `phase` / `status` / `updated-at`)
  - state-scanner Phase 1 跨分支 fetch + 重建多 track 看板 → 根除单写者 `latest.md` siloing
  - `standards/conventions/session-handoff.md` v1.0.0 → v1.1.0 (additive)
  - `aria/templates/session-handoff.md` frontmatter head + 字段填充指引
  - Backward-compatible: existing handoffs without frontmatter → graceful legacy fallback per mtime + filename

- **Layer L — Orphan ref + claim + reconcile + 急切认领**:
  - `refs/aria/coordination` orphan ref (history-isolated)
  - claim YAML schema v1 (10 fields incl `schema_version` + `superseded_from`)
  - file-per-writer partitioning (`claims/<container-id>/<session-id>.yaml`) → push 永不写他人文件
  - reconcile 4-rule deterministic protocol (early `claimed_at` / done takeover / `stale_ttl` takeover / lex tiebreak / `clock_skew` CONFLICT downgrade)
  - `scripts/phase1_gate.py` 9-step 急切认领 (fetch → reconcile → push claim → release to Phase B)
  - 7-case `failure_handlers.py` (non-ff retry / `auth_failed` no-retry / `disk_full` / partial fetch / orphan bootstrap / `user_decision` callback)
  - claim lifecycle (acquire / heartbeat 10min / release / `stale_ttl` 30min / GC archive)

- **Design A — Conditional worktree** (per-container concurrent ≥2 tracks):
  - `lib/concurrent_tracks.py`: `count_concurrent_tracks` 检测 `needs_worktree`
  - `lib/worktree_manager.py`: create / list / remove / cleanup_on_release / auto_cleanup_done_tracks
  - Submodule independent checkout via `git worktree add` semantics
  - 误用保护: dirty worktree default refuses cleanup; archive mode preserves history

**New files** (10 lib modules + 2 scripts + 1 doc + 3 tests):
- `aria/skills/state-scanner/lib/` — claim_schema / identity / track_id / coordination_ref / constants / claim_lifecycle / gc / reconcile / failure_handlers / concurrent_tracks / worktree_manager
- `aria/skills/state-scanner/scripts/phase1_gate.py`
- `aria/skills/state-scanner/scripts/renderers/track_board.py` (P1 + collision/clock-skew upgrade)
- `aria/skills/state-scanner/scripts/writers/latest_md_writer.py`
- `aria/skills/state-scanner/docs/rule9-5layer-matrix.md`
- `aria/skills/state-scanner/tests/test_p1_layer_h.py` + `test_reconcile_golden_table.py` + `test_race_window.py` + `test_failure_injection.py` (108 tests total)

**5-layer enforcement matrix** (Rule #9 全覆盖):
- L1 hook `handoff-location-guard.sh` 文档化 "无需改动 — 仅检查路径不检查内容"
- L2 collector `handoff.py` 加 `parse_handoff_frontmatter` helper + frontmatter-aware
- L3 state-scanner: Phase 1.16 `coordination_fetch` + Phase 1.17 `handoff_multibranch` + multi-track board
- L4 规约 SOT: `standards/conventions/session-handoff.md` §2.3
- L5 D.3 template: `aria/templates/session-handoff.md` frontmatter head

**CLAUDE.md Rule #9 Extension** (Aria 主仓): 引用本 v1.22.0 Spec + DEC-20260519-001

**Audit trajectory**:
- post_spec R1 (5 agents convergence): PASS_WITH_WARNINGS 5/5, 13 major dedupe
- post_spec R2 (v2 fixes verify): 4 PASS + 1 PASS_WITH_WARNINGS (全 minor) → 实质 unanimous PASS, 0 critical / 0 major
- post_implementation R8 (P2 final, informal): tech-lead **READY_TO_MERGE** + code-reviewer **SHIP_NOW** (15 minor, all `blocks_merge: no`)

**Rule #6 structural benchmark**: `aria-plugin-benchmarks/ab-suite/multi-terminal-coordination/benchmark.yaml` + result `ab-results/2026-05-20T042320Z-multi-terminal-coordination/` with AUTO_GATE=true (4 metrics, 所有 delta > 0,所有 threshold 满足);human_review pending per Rule #6 framing.

**Dogfood**: `.aria/dogfood-reports/multi-terminal-coordination-2026-05-20.md` 含本 session 真实 race 实证 (3 organic events: wrong-baton / push-reject / submodule-detach) + counterfactual analysis;真实 metric 数值待 master merge 后 `.aria/scripts/dogfood/measure_multi_terminal.py` 运行收集 (pending verdict)。

**Refs**:
- Spec: `openspec/changes/multi-terminal-coordination/` (Approved)
- Decision: `docs/decisions/DEC-20260519-001-multi-terminal-coordination.md`
- Closeout notes: `.aria/notes/multi-terminal-coordination-{p1,p2}-closeout.md`

---

## [1.21.4] - 2026-05-20

### Fixed — state-scanner sister-bug bundle: locale crash + transitional status

- **`skills/state-scanner/scripts/collectors/_common.py:_run`** (Aria #61):
  Windows CJK locale crash. `subprocess.run(..., text=True)` was falling back
  to `locale.getpreferredencoding()` (GBK on Chinese Windows) and crashing on
  UTF-8 git output (CJK commit messages / emoji per aria-standards
  git-commit.md 双语规范). 100% of `scan.py` runs failed on Chinese Windows
  with `UnicodeDecodeError: 'gbk' codec can't decode byte 0xaf` → exit 30.
  Fix: explicit `encoding="utf-8", errors="replace"` + defensive
  `UnicodeDecodeError` catch returning rc=125 (mirrors `TimeoutExpired` /
  `FileNotFoundError` softening — `_run` contract preserved: never raises).

- **`skills/state-scanner/scripts/collectors/_status.py:_normalize_status`**
  (Aria #73): transitional status `Implementation-Complete-Pending-Obs`
  mis-classified. Original v3.0 bug ("→ done", false-positive
  `pending_archive`) was incidentally migrated to "→ pending" by v1.20.0
  #101 fix, which wrongly surfaced the spec as a "待启动" item via
  `requirements.py:56` priority_items filter
  (`status ∈ {in_progress, ready, pending}`). Aether 2026-05-04 real-world
  hit: `migrate-docker-data-root-to-local-ssd` Spec with 24h obs window.
  Fix: new transitional family ahead of pending — hyphenated phrases
  `implementation-complete` / `implementation-done` route to `implemented`
  (the canonical lifecycle slot for "post-merge, awaiting verify/archive"
  per SKILL.md token dictionary). No new state introduced.

### Tests

- **`tests/test_common.py`** (NEW, 6 tests in `TestRunUtf8Encoding`):
  CJK roundtrip / emoji roundtrip / mixed ascii+CJK+emoji / non-zero rc /
  invalid-bytes errors=replace / command-not-found rc=127. Covers `_run`
  contract end-to-end.
- **`tests/test_openspec.py::TestStatusNormalizationIssue73Fix`** (NEW, 8 tests):
  primary case / alternate spelling / narrative form / no-pending-collision /
  no-done-collision / archived-precedence / unimplemented-shadow-guard /
  phrase-anywhere.
- **Suite**: 460/460 PASS (+14 new). Smoke importlib benchmark: 15/15 PASS.

### Closes

- Forgejo Aria #61
- Forgejo Aria #73

### Spec

- `openspec/changes/state-scanner-bugfix-locale-and-transitional-status/`
  → archived to `openspec/archive/2026-05-20-...` at release ship

---

## [1.21.3] - 2026-05-17

### Fixed — issue-triage D3 schema conformance (H3 iteration-2 + iteration-3)

- **`skills/issue-triage/SKILL.md` v1.0.0 → v1.2.0**:
  - **iteration-2** (anti-hand-author): Step 0 🚫 prominent block + Stage 1
    mechanical gate. *Benchmark-disproven as the D3 cause* — kept as
    defense-in-depth (0 regression, valid for weaker models / future drift).
  - **iteration-3** (the real D3 fix): Stage 3 now inlines the exact schema
    enums verbatim — verdict (7), severity (4, no "medium"),
    recommended_action (4, no "schedule") — at the fill point instead of
    deferring to a separate conventions file. Step 6 inlines ReproCase
    required fields (case_id was the #1 omission). New Stage 3.5 best-effort
    `jsonschema` self-check before comment synthesis.

- **Root cause** (corrected): the 2026-05-13 benchmark misdiagnosed D3 0/3
  as hand-authoring. Re-benchmark proved `script_produced 8/8` (zero
  hand-authoring on Opus 4.7); real cause = AI free-texts schema-enum
  fields with plausible-but-invalid values when enums aren't inlined.

- **Benchmark** (`aria-plugin-benchmarks/ab-results/2026-05-17-issue-triage-iter2/`):
  D3 with_skill **0/4 → 4/4** (iter-1 v1.1.0 → iter-2 v1.2.0), baseline
  v1.0.0 stays 1/4 — causal, baseline-controlled delta. Rule #6 PASS
  (capability-type Skill, 不可协商, full LLM AB — deterministic-substitute
  not applicable).

---

## [1.21.2] - 2026-05-17

### Docs/clarity — H1 follow-up (PR #46 + #4 audit Important items)

- **`hooks/handoff-location-guard.sh`**: added NOTE clarifying `set -e` is
  NOT the safety mechanism — the `DECISION=$(...)` command substitution masks
  python exit codes; safe behavior is the explicit fail-open PASS fallthrough
  (PR #46 audit Important-1; comment-only, behavior unchanged)
- **`RECOMMENDATION_RULES.md`**: `handoff_drift` rule clarified — added
  `degradation: true` flag + tri-state `non_blocking` semantics table
  (`non_blocking:true` advisory / `non_blocking:false` strong-signal /
  `+degradation:true` blocking-degradation / `blocking:true` hard-block),
  aligning handoff_drift with established `prd_draft_blocking` precedent
  (PR #46 audit Important-2)
- **`references/state-snapshot-schema.md`**: added explicit note that
  `latest.md` (pointer) is never itself a candidate handoff doc —
  excluded from `latest_path`/`exists`/`misplaced_files`; dir with only
  `latest.md` → `exists=false` (PR #46 audit Important-3)
- **(`standards/conventions/session-handoff.md`)**: `{archive-date}`
  placeholder filled to `2026-05-15` (real H0 archive date) — PR #4 audit
  Minor m5, companion aria-standards PR

No behavior change — documentation/clarity only. 446/446 suite + 10/10
hook smoke pass (pre-existing issue-cache-freshness flake unrelated).
Level 1 quick-fix per `feedback_closeout_found_bug_level1_hotfix`.

---

## [1.21.1] - 2026-05-16

### Fixed — H5 handoff collector mtime/pointer divergence (post-H0 closeout finding)

- **`collectors/handoff.py`**: `latest_path` now prefers `docs/handoff/latest.md`
  pointer target (human-maintained semantic "Latest") over raw mtime-max.
  mtime is fallback only (pointer absent / unparseable / stale target).
  - New `_parse_latest_pointer()` helper (regex on `**Latest**:` line)
  - New additive `latest_source` field: `"pointer"` | `"mtime"` | `null`
  - New `soft_error("handoff_pointer_target_missing")` for stale pointer
  - Schema stays `"1.0"` (additive)
- **Why**: discovered at H0 closeout — an H0 handoff edited post-hoc (rebase/
  closeout finalize) got newest mtime and shadowed the newer US-025 handoff;
  collector reported wrong "latest", defeating H0's anti-miss purpose.
  Memory: `feedback_handoff_mtime_vs_pointer_divergence`.
- **Tests**: +4 (TestLatestPointerPriority: pointer-wins / no-pointer-mtime /
  stale-pointer-soft-error / self-ref-ignored). 446/446 suite pass.
- **Docs synced** (Rule #3): schema doc + SKILL.md handoff-awareness +
  standards/conventions/session-handoff.md §3.2

---

## [1.21.0] - 2026-05-14

### Added — Ten-step cycle Phase D.3 session-handoff stage (Spec: aria-ten-step-session-handoff-stage, Forgejo Aria #92)

- **New Phase 1.15 `handoff` collector** (`skills/state-scanner/scripts/collectors/handoff.py`):
  - Scans `docs/handoff/*.md` by mtime DESC for latest handoff doc
  - Excludes `latest.md` pointer file (real handoff docs only)
  - Detects misplaced `.aria/handoff/*.md` files → `misplaced_files` field
  - Emits soft_error on permission-denied / stat-failure paths
  - Adds top-level `handoff` field to snapshot (schema 1.0 additive — no version bump)
  - 11 unit tests covering mtime sort, age_hours, schema, edge cases, latest.md exclusion, permission errors

- **New phase-d-closer §D.3 session-handoff step** (`skills/phase-d-closer/SKILL.md`, version 1.0.0 → 1.1.0):
  - Trigger: 4-level fallback (workflow-state.json::session.started_at > 4h → cycles shipped ≥ 2 → phase markers ≥ 2 → user prompt with default yes)
  - Output path **hardcoded** `docs/handoff/{YYYY-MM-DD}-{slug}.md` (L5 enforcement)
  - Auto-updates `docs/handoff/latest.md` pointer
  - Cross-platform stat hint (Linux/macOS/portable Python)

- **New 9-section handoff template** (`templates/session-handoff.md`):
  - §0 入口 / §1 已完成 / §2 carry-forward / §3 风险 / §4 实战教训
  - §5 多维度同步 / §6 next session 入口 / §7 提交清单 / §8 Memory entries

- **New PreToolUse hook `handoff-location-guard.sh`** (`hooks/handoff-location-guard.sh`):
  - Blocks Write/Edit/NotebookEdit to `.aria/handoff/*.md`
  - Cross-platform regex (POSIX `/` + Windows `\` separator char class)
  - Resolves symlinks via `Path.resolve()` to defeat circumvention
  - JSON deny payload (preferred) + exit-2 fallback (`ARIA_HOOK_DENY_MODE=exit2`)
  - 10 shell smoke test cases (run_tests.py 集成 via subprocess wrapper)

- **New state-scanner recommendation rule `handoff_drift`** (priority 1.91, between `audit_unconverged` 1.9 and `custom_check_failed` 1.95):
  - Trigger: `snapshot.handoff.misplaced_files != []`
  - Workflow: `migrate-handoff-drift` (4-step bash: git mv + update latest.md + rmdir + commit)
  - Confidence 95%, not auto-execute (file move 涉及 git history,需用户 confirm)

- **New convention SOT `standards/conventions/session-handoff.md`** (`aria-standards`):
  - Mirrors Rule #7 secret-hygiene structure
  - 5-layer enforcement matrix documented
  - Migration notes for downstream projects
  - Source incidents (4 dogfood)

- **CLAUDE.md Rule #9 ship-time 激活**:
  - Position: after Rule #8 pre-merge gate
  - Mirrors Rule #7 structure (要点 / 触发场景 / Source incidents / Exception / 详细规范 ref)
  - 4 dogfood evidence > Rule #7/#8 (no observation period needed)

- **Aria self migration**: 6 `.aria/handoff/*.md` files migrated to `docs/handoff/` via `git mv` (100% similarity preserved). `docs/handoff/latest.md` pointer corrected to truly newest doc.

### Quality

- pre_merge audit R1 SCOPE_OK_R1 — 3 agents convergence (backend / knowledge / qa), 0 Critical, 5 Major inline-fixed (collector double stat / macOS stat / silent permission-denied / latest.md wins mtime / hook test discovery)
- 442 Python unit tests + 10 shell hook smoke tests (100% pass, no regression)
- 4 dogfood incidents (SilkNode 2026-05-09 + Aria self 2026-05-13 ×3 含 H0 spec 起草本 session)

### Forgejo Issues

- Closes #92 (ten-step cycle session-handoff stage proposal)

---

## [1.20.0] - 2026-05-13

### Added — `issue-triage` Skill (Spec: aria-issue-triage-sop, Forgejo Aria #101)

- **New Skill `issue-triage`** (`skills/issue-triage/`):
  - 6-step standard SOP for triaging issues filed against Aria-managed projects
  - `scripts/triage.py` (stdlib-only Python) + 6 sub-collectors (Step 1-5
    mechanical) + JSON schema with `partial-repro` conditional (`if verdict ==
    "partial-repro" then deviation_note required`)
  - 7-verdict dictionary including **`partial-repro`** (new — captures cases
    where issue self-report differs from actual reproduction; born from #101
    where issue claimed 4/4 hit rate but actual was 2/4 primary + 2/4 secondary)
  - Orthogonal fields: `severity` (critical/major/minor/trivial) +
    `recommended_action` (hotfix/next-cycle/backlog/close)
  - Step 6 (reproduction) supports 3 exit modes: `auto` / `pause` / `skip`
  - Cross-repo support: 5-path fail-soft version chain
    (plugin.json → .claude-plugin/plugin.json → VERSION → package.json → pyproject.toml)
  - Rule #7 secret-hygiene compliant: single subprocess chokepoint with
    `capture_output=True`, AST-verified zero leaks
  - 115 unit tests + CI workflow YAML, full schema validation gate

- **Truth-source convention** (`aria-standards`):
  - New SOT doc `standards/conventions/issue-triage.md` (464 lines) — 6-step
    SOP definition, verdict dictionary, exception template
  - SKILL.md references SOT (no duplication) — mirrors Rule #7
    secret-hygiene.md pattern

- **Skill count**: 30 user-facing → **31 user-facing** (6 internal unchanged)

### Fixed — state-scanner `_normalize_status` (Spec: aria-issue-101-status-normalize, Forgejo Aria #101)

- **Bug 1 — substring shadow class**: `done` / `complete` / etc. token checks
  used `if X in low` which matched substrings. Status strings like
  `"Approved (Rev2 CONVERGED) — Phase A done"` matched `done` and returned
  `status=done` before reaching `approved`, causing `pending_archive` false
  positives → silent risk of WIP spec moved to archive on user accept of
  state-scanner recommendation.

- **Bug 2 — missing `implemented` token**: Status values like
  `"Implemented (Phase B PR-A merged) — post-deploy 验证后归档"` returned
  `unknown` (not in token dictionary). Caused state-scanner to drop legitimate
  Implemented specs from active classification.

- **Fix — word-boundary regex** (`\b<token>\b` via new `_has_token` helper):
  - Root-causes the entire substring-shadow class
  - Bonus pre-existing bug fixes: `inactive` no longer matches `active`,
    `incomplete` no longer matches `complete`
  - Prevents would-be regression: `unimplemented` does not match `implemented`

- **Priority chain refined** per R1 audit BA-M2:
  - Terminal (archived/deprecated) → pending family → in_progress family →
    **approved → implemented** (gatekeeping state before post-merge state) →
    reviewed/active/ready → done/complete (LAST fallback)

- **New lifecycle state `implemented`**: Post-merge state, between `approved`
  and `done`. For specs with code merged but awaiting post-deploy verify /
  monitoring / archive trigger.

- **state-scanner SKILL.md** adds "Status 字段最佳实践" section: supported
  token table with priority order + recommended format examples + anti-pattern
  educational notes (historical shadow traps now safe under word-boundary).

- **Tests**: New `TestStatusNormalizationIssue101Fix` class with 13 cases
  (4 #101 真实 strings + 4 shadow guards + 5 positive regression). Full
  state-scanner test suite: 414 → 427, **0 regression**.

- **Live verify**: Aria itself `pending_archive` false positives **4 → 0**
  on current active specs.

### Methodology

- **Two cycles single-day completion** demonstrating triage SOP value:
  1. `aria-issue-triage-sop` (Phase A+B+C+D, 8 task groups, 3 repos) —
     2 audits (R1+R2 post_spec SCOPE_OK_R2), T5 dogfood PASS, T8 Rule #6
     benchmark +21.8pp overall / +53.3pp structural
  2. `aria-issue-101-status-normalize` (Phase A+B+C+D, deterministic bug fix) —
     post_spec R1 SCOPE_OK_R1, Rule #6 deterministic AB +77pp (pre 3/13 vs
     post 13/13), 0 regression
- **Public dogfood evidence**:
  - Manual triage: https://forgejo.10cg.pub/10CG/Aria/issues/101#issuecomment-5972
  - AI dogfood: https://forgejo.10cg.pub/10CG/Aria/issues/101#issuecomment-6019
- **Decision memo**: `docs/decisions/2026-05-13-rule-9-deferral.md` (main
  Aria repo) — Rule #9 (issue triage enforcement) deferred, requires
  ≥3 dogfood + 1 missed-triage incident before reconsidering

### References

- Spec archive: `openspec/archive/2026-05-13-aria-issue-triage-sop/`
- Spec archive: `openspec/archive/2026-05-13-aria-issue-101-status-normalize/`
- Audit reports: `.aria/audit-reports/post_spec-{R1,R2}-2026-05-13-*.md`
- Benchmark archive: `aria-plugin-benchmarks/ab-results/2026-05-13-issue-triage/`
- Benchmark archive: `aria-plugin-benchmarks/ab-results/2026-05-13-state-scanner-issue-101-fix/`
- Closes: Forgejo Aria #101

---

## [1.19.0] - 2026-05-10

### Added — phase-c-integrator pre-merge gate (Spec: phase-c-integrator-pre-merge-gate, Forgejo Issue #60)

- **D1 — phase-c-integrator C.2.4 Pre-Merge Precondition Gate** (`skills/phase-c-integrator/`):
  - SKILL.md version 1.2.0 → 1.3.0; new sub-step C.2.4 inserted between PR
    creation and C.2.5 multi-remote push.
  - Consume aether `--in-flight` primitive (aether-cli #116, SHA `f29abee`
    2026-05-06). aria-side verdict computation (P0-B `aether-pre-merge-check`
    skill never shipped).
  - Three-state verdict: `green` (passing + no in-flight) / `wait` (passing +
    in-flight OR pending) / `fail` (failing OR primitive error).
  - 8 new config keys under `phase_c_integrator.pre_merge_gate.*`: `enabled`,
    `primitive_preference`, `no_aether_fallback`, `wait_timeout_seconds`,
    `wait_check_intervals`, `primitive_call_timeout_seconds`, `poll_chunk_seconds`,
    `user_escape_hatch`.
  - Helper `scripts/pre_merge_gate.py` (~290 lines, stdlib + subprocess only)
    + 20 unit tests (`tests/test_pre_merge_gate.py`).
  - Subprocess hardening: `subprocess.run(timeout=N)` + max 3 retry attempts
    (5s/15s/45s backoff); aether binary version pre-flight check (greps
    `--in-flight` in `aether ci status --help`).
  - Naming clarification: phase-c-integrator-tier C.2.4 (orchestrator) ≠
    branch-manager-internal C.2.4 (`等待审批`); independent label namespaces.
- **D2 — workflow-runner `wait_recoverable` error type + `gate_state` schema**
  (`skills/workflow-runner/`):
  - SKILL.md version 2.2.0 → 2.3.0; new §Pre-Action Gate State + §wait_recoverable
    error type + §Ctrl-C 检测机制 + §Resume 语义 sections.
  - workflow-state-schema.md `format_version: 1.0 → 1.1` (additive only); new
    `gate_state` top-level optional block with field descriptions and migration
    table entry (v1.0 → v1.1: gate_state default null).
  - Defensive access pattern: `state.get("gate_state") or {}` documented.
  - Reference impl `scripts/gate_state_helper.py` (~190 lines, stdlib only)
    + 22 unit tests (`tests/test_gate_state_helper.py`): lifecycle (create /
    increment / clear) + corruption recovery + interrupt flag-file lifecycle
    (clear / set / detect / latest-wins) + polling sleep chunk with mid-sleep
    interrupt detection (injectable `sleep_func` for deterministic tests).
- **config-loader/SKILL.md**: 7 validation rules for new
  `phase_c_integrator.pre_merge_gate.*` block.

### Background

2026-05-02 SilkNode incident: PR-321 merge cancelled PR-322 main CI Run #3161
(459s deployment observability lost). Root cause: Forgejo Actions concurrency
rule + Nomad single-job topology + missing pre-merge in-flight CI check in aria
workflow. Spec passed post_spec audit R1+R2 (4 Critical → 0, unanimous
PASS_WITH_WARNINGS). T1.0 spike revised D1 design after discovering the
upstream `aether-pre-merge-check` skill was never shipped — only the underlying
`aether ci status --in-flight` query primitive exists.

### Tests

42 new unit tests, all pass (20 D1 pre_merge_gate.py + 22 D2 gate_state_helper.py).

### Backward compatibility

- `pre_merge_gate.enabled: false` config preserves v1.18.0 behavior bit-for-bit
  (gate skipped entirely).
- `.aria/config.json` without `pre_merge_gate` block → config-loader fills
  defaults (`enabled: true`); workflow infrastructure invokes gate.
- Projects without aether plugin: `no_aether_fallback: skip_with_warning`
  default emits a workflow-report warning but does not block.
- workflow-state.json v1.0 files migrate transparently to v1.1 on read with
  `gate_state: null` default.

## [1.18.0] - 2026-05-09

### Added — state-scanner inter-cycle surfacing (Spec: state-scanner-inter-cycle-surfacing)

- **G2 — UPM `## Pending Followups` markdown table parser** (`collectors/upm.py`):
  column normalization (English + Chinese aliases), pipe-escape handling,
  priority normalization (P0..P3 case-insensitive or `unknown`), BA-10 fullwidth
  U+3000 rejection in heading regex.
- **G3 — handoff_doc pointer detection** (`collectors/upm.py`): primary regex
  with explicit Chinese/English/Emoji enumeration + R2-converged fallback (BA-02
  form, no standalone `入口`); three-state path resolution (URL / absolute /
  relative) with fail-soft `unsupported_path_format` + `handoff_path_escapes_project`
  soft_errors.
- **G4 — in-progress US `priority_items[]` derived view** (`collectors/requirements.py`):
  filtered + sorted view of `items[]` (no fs re-glob); 3-level stable sort
  (status_order ASC → mtime DESC → path LEX ASC); configurable limit via
  `state_scanner.priority_items_limit` (default 5).
- **TX.0 — `git.status_clean` derived bool** (`collectors/git.py`): `staged_files == []
  AND unstaged_files == []`; untracked excluded by design; fail-soft `False`.
- **RECOMMENDATION_RULES.md v2.11.0**: 2 new rules — `pending_followups_p1`
  (priority 1.85) + `resume_in_progress_us` (priority 1.88).
- **state-snapshot-schema.md**: 4 nested-field sections + backward-compat contract
  + `errors[]` enum (`unsupported_path_format` + `handoff_path_escapes_project`).
  Schema version stays `"1.0"` (additive only).
- **`normalize_snapshot.py` DROP_KEYS**: `raw_row` + `raw_match` to stabilize
  canonical form against upstream markdown drift.

### Changed
- **state-scanner SKILL.md T5 兜底降级**: 阶段 2 "完整性兜底" 段从 17 行 (4 触发
  条件 + 3 AI 主动 Read/Grep + 过渡说明) 缩减为 ~9 行 sanity check (collector
  字段缺失检测 → soft warn). T5 inline AI guidance 由机械化 collector 字段替代.

### Fixed (sub-PR (b) R2 audit corrections)
- **upm.py error-path schema contract**: 3 error paths (no-UPM-file / read-error /
  block-not-found) now correctly OMIT `handoff_doc` key per schema §upm L160 contract
  (was emitting `handoff_doc: null`, conflating "scanner ran no match" with "no UPM
  to scan"). Pre_merge backend-architect Major closed.
- **schema.md "planned for TX-G2/G3/G4" labels**: replaced with "shipped sub-PR (b)
  2026-05-09" + Implementation history blockquotes. CLAUDE.md rule #3 violation
  closed (knowledge-manager R1+R2 Major).

### Tests
**+39 net-new tests** (372 baseline → 414 on aria submodule master):
- sub-PR (a) aria-plugin#37: +5 (status_clean derived + fail-soft + 4 normalize rules)
- sub-PR (b) aria-plugin#38: +32 (24 initial G2/G3/G4 + 8 R2 corrections)
- sub-PR (c) (this PR): +4 backward-compat verify (TX.6)

### Pre-merge audits (multi-agent convergence loop, 4 agents per round)
- sub-PR (a) aria-plugin#37: 4 rounds, R3==R4 converged, 4/4 PASS, 0 Critical/Major
- sub-PR (b) aria-plugin#38: 5 rounds, R4==R5 converged after 8 R2 corrections
- sub-PR (c) (this PR): see PR description

### Refs
- Spec: `openspec/changes/state-scanner-inter-cycle-surfacing/proposal.md`
- Sub-PR sequence: aria-plugin#37 (a, prereq) → aria-plugin#38 (b, collectors) →
  this PR (c, cleanup + version bump)
- Issue: 10CG/Aria#85 (SilkNode inter-cycle surfacing gap forcing function)

### Marketplace.json sync
- 修复 `marketplace.json` 自 v1.17.6 起的版本漂移 (相对 plugin.json 落后 1 minor).
  本次同步至 v1.18.0 闭环.

## [1.17.7] - 2026-04-28

### Fixed

- **state-scanner issue_scan _normalize_items silent bug** — 现代 Forgejo (≥1.21) 给 `/issues` endpoint 的每个 issue payload 都附加 `"pull_request": null` 字段 (与 PR 共用 schema). 旧实现用 `if "pull_request" in raw: continue` 仅检查 key 存在性, 把**所有真实 issue** 误判为 PR 静默过滤掉 → `open_count=0`, 无 `fetch_error`, `source="live"` (genuinely successful fetch but completely wrong filter result).

#### Repro & evidence

- 实测案例: Aether 项目 (10CG/Aether) 有 24 个 open issues, 但 state-scanner 报告 `issue_status.open_count=0`. recommendation engine 在 issue 通道完全失明, 无法推荐任何 issue-driven 工作.
- forgejo CLI 直接 `GET /issues?type=issues` 返回 20 issues 但 `_normalize_items` 输出 0.

#### Fix

- **File**: `aria/skills/state-scanner/scripts/collectors/issue_scan.py:336`
- 改用值类型检查: `if isinstance(raw.get("pull_request"), dict): continue`
- PRs 携带嵌套 dict (含 `merged`, `state` 等); issues 携带 `None` 或 key 缺失. 检查值类型而非 key 存在与否.
- URL `/pulls/` 第二条 belt-and-suspenders guard 保留 (兼容旧 Forgejo / corner case).

#### Test

- 旧 `test_qa_c2_pull_request_filter` 用 `pull_request: {}` (空 dict) 模拟 PR, 没覆盖现代 Forgejo 的 `null` 情形 → 测试通过 production 漏 → 漏修.
- 新增回归测试 `test_modern_forgejo_pull_request_null_on_issues`: 3 个 mixed item (2 个 `pull_request: None` issue + 1 个 `pull_request: {merged: False}` PR), 期望保留 2 个 issue.
- 86 tests 全绿 (新增 1 + 已有 85 不变).

### Bug 来源

- **upstream Forgejo 1.21+ 的 schema unification**: 新版本统一 issue/PR payload schema, 给 issue 也附 `pull_request: null` 标识 "非 PR". 旧 `_normalize_items` 写于该变更之前, presence-only check 的隐式假设 (PRs 才有 pull_request key) 失效.
- **测试盲区**: 既有测试用 `pull_request: {}` 假 PR, 与现代 Forgejo 的 null issue 形态完全不同, 无法触发 bug.
- 影响: 任何接 aria-plugin 1.17.6 及以下版本到 Forgejo ≥1.21 的项目, recommendation engine 都看不到 issue.

### 跨项目影响

下游 (e.g. Aether) 升级到 1.17.7 后建议:
- 删 `.aria/cache/issues.json` 让 scan 重新 fetch
- 确认 `state-scanner` `issue_status.open_count` 与 `forgejo GET /repos/<owner>/<repo>/issues?state=open` 实测一致
- 可能需要把 `.aria/config.json` `state_scanner.issue_scan.limit` 调高 (默认 20, Aether 24 个 open 时已超出)

## [1.17.6] - 2026-04-26

### Added

- **verify_post_push.py SHA prefix-match (Spec `verify-post-push-sha-prefix-match`)** — Round-2 audit P2.2 spike-verified real bug

#### Script changes

- **File**: `aria/skills/git-remote-helper/scripts/verify_post_push.py`
- 新增 `_sha_match(actual, expected) -> bool` 辅助函数 + `_MIN_SHA_PREFIX = 7` 常量
- 第 147 行 `if sha == expected_sha:` 改为 `if _sha_match(sha, expected_sha):`
- 语义: `actual.startswith(expected.lower()) AND len(expected) >= 7`
- 短于 7 字符 → reject as False (避免 collision 假阳性)
- full 40-char happy path 字节级一致 (40-char.startswith(40-char) ⇔ ==)

#### Doc changes

- `aria/skills/git-remote-helper/SKILL.md:101`: 示例 `--expected-sha=19f2861` → full 40-char
- `aria/skills/git-remote-helper/references/api.md`: 4 处示例 `19f2861a3b4c5d6e7f8a9b0c` (24-char) → full 40-char; `--expected-sha` 字段说明追加 prefix 兼容性

#### Bug 来源

- doc 自爆: SKILL.md/api.md 示例本身用短 SHA, 用户照抄触发 script 严格 `==` mismatch
- production safety: Aria phase-c-integrator C.2.5 调用流程用 `git rev-parse HEAD` (full 40-char), happy path 不触发, 但新用户 onboarding 是 trap

### P2.1 closed as FALSE POSITIVE

- Round-2 catalog P2.1 (verify_post_push.py 早退 vs all_match) 经 spike 证伪
- script line 147 早退在 per-remote retry loop (line 138) 内, 不跨 outer `target_remotes` loop (line 186); line 198 `all_match=all(...)` 正确聚合
- catalog 自标 verifiability=LOW, spike 闭环

### Changed

- 单 Spec patch (sister-bug bundle 因 P2.1 证伪缩水到单 Spec, 适用 `feedback_level2_patch_no_benchmark.md`)
- 100% 向后兼容 (full SHA happy path 字节级不变; 仅放宽 short prefix 接受度)

### Migration

- 现有 caller 用 full 40-char SHA → 行为不变
- 新 caller 可用 ≥7-char prefix (与 `git show`/`git checkout` 习惯一致)
- 现有 caller 用 <7-char SHA → **会变为 reject**, 需升级到 ≥7-char (实际上 Aria 流程没人这么传)

## [1.17.5] - 2026-04-26

### Added

- **Round-2 audit P1.3 + P2.3 sister-bug bundling** — 双 Level 2 micro-Spec 打包发版, audit-engine 子系统第二批 sister-bug (前批 v1.17.4 P0.2 文件名 uniqueness)

#### P1.3: audit-engine finding ID determinism

- **File**: `aria/skills/audit-engine/SKILL.md` 第 220-233 行 + `references/convergence-algorithm.md` 第 28-42 行
- **改动**: finding `id` 字段从 prose 占位符 `"auto-generated-hash"` 显式规范化为 `sha256(category:scope:severity:type)[:8]` 8-char hex prefix; 与 4-tuple `comparison_key` 同步 (4-tuple 相等 ⇔ ID 相等)
- **跨轮稳定性**: 同 finding 在 R1/R2/RN 由不同 agent 报告 → 同 ID; severity 升级 → ID 改变 (符合 comparison_key 不收敛逻辑)
- **触发**: 2026-04-26 Round-2 latent-bug audit P1.3 (catalog `openspec/archive/2026-04-25-round-2-latent-bug-audit-findings/proposal.md`)
- **价值**: audit-driven fix inline 注释 `R1-a3f2c9b1 fix:` 跨轮稳定可追溯; 4 agent 同时报相同 finding 不重复计数

#### P2.3: audit-engine 0-finding stability gate

- **File**: `aria/skills/audit-engine/references/convergence-algorithm.md` 第 44-52 行边界条件表
- **Spike Result**: 真 bug 验证 ✓ — 文档 line 48 "空结论集 (两轮都无结论) | 视为收敛" 与 memory `feedback_audit_convergence_pattern.md` + `project_premerge_iteration_pattern.md` 实战教训冲突
- **改动**: 边界条件表加 stability gate 行: 首轮 0-finding 不视为收敛, 必须进入 Round 2 作 stability confirmation. 等价表达式 `converged = (current_set == previous_set) AND (current_set != ∅ OR round_number >= 2)`
- **经验来源**: aria-plugin v1.16.0 trajectory 24→2→1→0→0 (R5=∅ 后仍跑 R6=∅ 才声称收敛)
- **触发**: Round-2 audit P2.3 spike-first 调查 (符合 `feedback_spike_first_for_data_hypotheses.md`)
- **价值**: 消除 agent context 异常导致首轮 0-finding 假阴性收敛风险

### Changed

- 双 doc-only 改动 (无 scripts 修改), 100% 向后兼容
- audit-engine 子系统连续两批 sister-bug bundling (v1.17.4 文件名 + v1.17.5 ID/stability), 验证 sister-bug 模式在同子系统多 micro-bug 场景的可重复性

### Migration

- 现有 audit 报告: 旧 finding `id` 字段保留, 不强制重新计算 (向后兼容); 新报告按 sha256 规范生成
- 现有 0-finding 收敛历史: 已成功收敛的 audit 不回溯; 新 audit 按 stability gate 规则执行

## [1.17.4] - 2026-04-25

### Added

- **Round-2 audit P0 sister-bug bundling** — 双 Level 2 micro-Spec 打包发版 (`requirements-validator-status-i18n-alignment` + `audit-engine-report-filename-uniqueness`)

#### P0.1: requirements-validator Status i18n alignment

- **File**: `aria/skills/requirements-validator/SKILL.md`
- **改动**: 第 100-148 行 PRD/Architecture/User Story 的 `version_header.required_fields` 与 `header_fields.Status` 引用 6-pattern union form; 新增独立章节 "Status 字段提取规范 (i18n alignment)" 文档化 6 个模式 + i18n 全角冒号支持 + Negative case
- **SoT**: `aria/skills/state-scanner/references/state-snapshot-schema.md` 第 142-153 行 `_STATUS_PATTERNS` (与 collector 机械等价)
- **触发**: 2026-04-25 Round-2 latent-bug audit P0.1 (catalog `openspec/archive/2026-04-25-round-2-latent-bug-audit-findings/proposal.md`); 教训作为 lint 标准的跨 Skill 第三次应用 (前两次: state-scanner v1.17.2 i18n + v1.17.3 regex-hardening)
- **价值**: 中文项目 (Kairos 等中文 adopter) 用全角冒号或 heading-prefix 形式不再被 validator 误判 Status missing

#### P0.2: audit-engine 报告文件名唯一性

- **File**: `aria/skills/audit-engine/SKILL.md` 第 429 行
- **改动**: 文件名 schema 从 `{checkpoint}-{timestamp}.md` 升级为 `{checkpoint}-R{round}-{timestamp_ms}-{spec_id}-{agent_role}.md`; 加入字段定义表 + 完整示例 + 碰撞防护设计 + 向后兼容 reader 行为
- **碰撞防护**: 4-agent 并行 dispatch (qa-engineer / code-reviewer / backend-architect / tech-lead) 同毫秒落盘不冲突; 旧文件名作为 R1/legacy 仍能被 reader 处理
- **触发**: Round-2 audit P0.2; 历史样本时间戳粒度仅到分钟/秒, strict 模式收敛比较丢 finding
- **价值**: `R_N == R_{N-1}` 收敛判定基础完整, 不再因文件名碰撞丢 agent 输出

### Changed

- 双 doc-only 改动 (无 scripts 修改), 100% 向后兼容

### Migration

- audit-engine 旧文件名 reader 自动归类 R1/legacy, 用户无需手动迁移



### Added

- **state-scanner collector field-extractor 正则鲁棒性补强** (Spec `state-scanner-collector-regex-hardening`, Level 2 patch)
  - **architecture.py** 3 patterns (`Status` / `Last Updated` / `Parent PRD`): 加 heading prefix `(?:#{1,6}\s+)?` + fullwidth colon `[：:]` + optional bold `(?:\*\*)?`. 现在支持所有形式: `**Status**: A` / `**Status**：A` / `## Status: A` / `> **Status**: A` / `## **Status**: A`
  - **forgejo_config.py** 2 patterns: `_FORGEJO_YAML_KEY` 加 fullwidth colon + blockquote prefix; `_FORGEJO_HEADING` 加 blockquote prefix
  - **readme.py** `_VERSION_PAT`: 加 heading prefix + optional bold (i18n fullwidth 已在 v1.17.1 fix)
  - 100% 向后兼容 (regex 字符类 + optional prefix 都是严格超集)
  - 触发: 2026-04-25 主动 latent bug audit (3 个并行 Explore agent dispatch). 复合应用 v1.17.1 anchor narrowness + v1.17.2 i18n fullwidth colon 教训作为 lint 标准

- **9 新单元测试**:
  - `test_architecture.py::TestRegexHardening` (6 tests): fullwidth colon × 3 fields, heading prefix × 3 fields, heading + bold combined, blockquote + fullwidth, baseline regression
  - `test_forgejo_config.py::TestRegexHardening` (2 tests): fullwidth colon + blockquote prefix
  - `test_readme.py::TestRegexHardeningHeading` (1 test): `## Version: v1.2.3` 形式

- **`references/state-snapshot-schema.md`** 新增 architecture / forgejo_config / readme 三段落各加 union form 文档 + Spec ID 引用 (v3.0 SoT 同步)

### Changed

- 3 collector 模块 docstring 注明 i18n + heading hardening Spec 引用
- `state-scanner/SKILL.md` **不变** (mechanical-mode 后 prose 已最小化, 仅指向 schema.md)

### Acceptance verified

- 371/371 stdlib unittest PASS (was 362, +9 net)
- Smoke benchmark: 12/12 (100%) PASS — `aria-plugin-benchmarks/ab-results/2026-04-25-state-scanner-regex-hardening-v1.17.3/`
- Kairos cross-project retest: zero regression (parity preserved, 7/15 stories still resolve)
- 100% backward compatible

### Why patch instead of minor

- 跨 collector 共享 lint rule, 3 文件 ~30 行 regex + 9 unit tests + schema doc
- 实施工时 ~1.5h, 与 Spec 估时一致
- 与 v1.16.2/3/4 + v1.17.1 + v1.17.2 patch 模式一致 (`feedback_smoke_vs_full_ab_benchmark.md`)
- 主动 latent bug audit 路径,无外部 issue 触发

---

## [1.17.2] - 2026-04-25

### Added

- **state-scanner i18n Status 正则增强** (Spec `state-scanner-i18n-status-regex`, Level 2 patch)
  - Patterns 1-4 加 fullwidth colon `[：:]` 字符类 — 中文 IME 默认产生全角冒号 `：` (U+FF1A), 之前仅匹配半角 `:`
  - Pattern 6 NEW: inline blockquote 多 meta 匹配 — `> **优先级**：P0 | **状态**：pending` 中 status 不在行内首键的情形
  - Pattern 5 (table) 已支持 `[：:]`, 不变
  - 100% 向后兼容 (regex 字符类扩展是严格超集)
  - 触发: 2026-04-25 state-scanner-mechanical-enforcement T8 Kairos 跨项目验证发现, Kairos `US-009-tts-voice-clone.md` 用 `> **优先级**：P0 | **里程碑**：M3 | **状态**：pending` 格式被漏检

- **7 新单元测试**:
  - `test_requirements.py::TestI18nStatusRegex` (5 tests): fullwidth colon CN / Kairos US-009 实样 / inline blockquote at-end / inline blockquote middle EN / 负样 prose 不匹配
  - `test_openspec.py` (2 tests): _extract_status 共享模块 i18n 跨 collector 传播验证

- **`references/state-snapshot-schema.md`** 新增 "Status extraction patterns" 表 (6 patterns × Sample) + i18n note. 文档落到 schema.md (v3.0 SoT, AD-SSME-6) 而非 SKILL.md, 避免 mechanical-mode Spec 已消除的 prose-vs-code 重复定义

### Changed

- `collectors/_status.py` 模块 docstring 注明 i18n enhancement Spec 引用 + 6 patterns 设计
- `state-scanner/SKILL.md` **不变** (mechanical-mode 后 Phase 1.5 prose 已最小化, 仅指向 schema.md)

### Acceptance verified

- 362/362 stdlib unittest PASS (was 355, +7 net)
- Smoke regex 测试: 12/12 cases (P1-P5 × halfwidth/fullwidth + P6 NEW + 1 negative prose). 见 `aria-plugin-benchmarks/ab-results/2026-04-25-state-scanner-i18n-v1.17.2/`
- Kairos T8 retest: US-009 `raw_status: null → "pending"` ✅; 7/15 stories 现可解析 (was 0/15)
- 100% backward compatible

### Why patch instead of minor

- 跨 collector 共享模块 (_status.py) 单文件 ~25 行 regex 改动 + tests + schema doc
- 实施工时实测 ~45 min vs Spec 估时 ~1h
- 与 v1.16.2/3/4 + v1.17.1 patch 模式一致 (`feedback_smoke_vs_full_ab_benchmark.md`)
- aria:code-reviewer 单轮 MERGE_NOW + 2 Important + 3 Minor 全数已修

---

## [1.17.1] - 2026-04-25

### Fixed

- **state-scanner readme.py blockquote regex** (Level 1 hygiene patch, 3-agent parallel review)
  - `_VERSION_PAT` 锚点 `^\s*\*\*` 不允许 `>` 字符, 导致 `> **Version**: ...` 形式 (实际 aria/README.md L5 + root README.md 都用此形式) 无法匹配
  - 后果: `readme.submodules.aria.version_match` 自 v1.16.0 起静默 None, 即便版本完全一致
  - 修复: 改为 `^>?\s*\*\*` 与 `architecture.py` 风格一致 (允许可选 blockquote 前缀)
  - 漏测原因: smoke benchmark eval-3 仅验证字段存在, 未验证 truthiness (field-presence-only false-pass pattern)

### Added

- **6 regression tests in `test_readme.py::TestVersionPatternBlockquote`**:
  - blockquote + match 检测
  - blockquote + mismatch 检测
  - 无 prefix 形式 regression baseline
  - blockquote + v-prefix 组合
  - blockquote + 中文 key
  - field-presence-only false-pass guard (catches the v1.17.0 missed-bug pattern)

### Why patch instead of minor

- 单行 collector 正则 fix, 零 API 变更, 零 schema 变更 (Level 1 hygiene)
- 3-agent (backend-architect / qa-engineer / code-reviewer) 并行 1 轮 APPROVE_WITH_NOTES
- v1.17.0 latent bug 不能等到 next minor (`version_match` 已静默错误数月)
- 与 v1.16.2/3/4 patch 模式一致 (`feedback_smoke_vs_full_ab_benchmark.md`)

---

## [1.17.0] - 2026-04-25

### Added — state-scanner v3.0.0 机械化模式 (state-scanner-mechanical-enforcement Spec)

- **Step 0 hard constraint** (SKILL.md L63-95): Phase 1 数据采集只能通过 `python3 scripts/scan.py --output .aria/state-snapshot.json`. AI 不得用 Bash/Grep 逐字段重建状态. 退出码契约 0/10/20/30 (见 schema.md §Exit code consumer contract)
- **17 collectors 包** (`scripts/collectors/`, stdlib-only Python):
  - Phase 0: interrupt
  - Phase 1: git, upm, changes
  - Phase 1.5-1.10: requirements, openspec, architecture, readme, standards, audit
  - Phase 1.11-1.14 (opt-in): custom_checks, sync, multi_remote, issue_scan, forgejo_config
- **JSON snapshot schema v1.0**: 17 顶层字段, source-of-truth = `references/state-snapshot-schema.md`, validator = `scripts/validate_schema_doc.py` 断言 doc/code 一致
- **Canonical normalizer** (T7.0): `scripts/normalize_snapshot.py` (10 rules) + `references/json-diff-normalizer.md`. T7.2 live dogfood DIFF_EXIT=0 (两次 scan.py + normalize 字节级一致)
- **Stdlib unittest test suite** (T6): 215 tests, 1.6s runtime, 0 third-party deps. 9 collectors ≥70% coverage; 6 I/O-heavy <70% (T6.5-followup tracked)
- **Migration guide** (`references/migration-v2.9-to-v3.0.md`): Why / Step 0 contract / D1-D5 / opt-out lifecycle / upgrade checklist / rollback
- **Golden baseline fixture**: `tests/fixtures/reference-snapshot-aria.json` (722 行 normalized snapshot of Aria master 2026-04-25)

### D1-D5 Intentional Divergences (preserved as v2.9 → v3.0 fixes)

- **D1**: `Status: Approved` → `approved` (NOT collapsed to `ready`)
- **D2**: `Status: Reviewed` → `reviewed` (NOT collapsed to `pending`)
- **D3**: `Parent PRD: TBD/(pending)/N/A` → `chain_valid: false` (NOT silently true)
- **D4**: YAML `key: |` block scalar → `None` (NOT literal `"|"`)
- **D5**: `Active/Deprecated/Archived` → 3 distinct states (NOT all `unknown`)

每条都有专门 regression test 守护 (test_openspec/_architecture/_upm).

### Changed — SKILL.md condensed (1178 → 454 lines, -724 net)

- Phase 1.x 14 子阶段 prose 合并为 collector 职责表 (语义委托 schema.md)
- Phase 2 入口断言: snapshot 缺失 / `snapshot_schema_version != "1.0"` 直接 abort
- Step 0 + AI 禁区表 (✅/❌ 矩阵) 强约束机械路径

### Deprecated

- **prose path opt-out** (`.aria/config.json` 设 `state_scanner.mechanical_mode: false`): 仍受支持, 但 v1.18.0 移除 (AD-SSME-5). v1.17.x cycle 监测使用量, 零告警 = 安全移除信号

### Quality Gates Met

- T6 stdlib unittest: **215/215 PASS**, 1.6s
- T7 stability dogfood: **DIFF_EXIT=0** (字节级)
- Smoke benchmark v1.17.0: **35/35 (100%) structural assertions** across 11 ab-suite eval cases (`ab-plugin-benchmarks/ab-results/2026-04-25-state-scanner-v1.17.0/benchmark.md`)
- 8 audit reports across T1-T9 (4-agent × 4-round → 1-agent × 1-round proportionality 实证)
- 9 partial-merge cycles all 4-remote parity 同步

### Migration

升级路径见 `aria/skills/state-scanner/references/migration-v2.9-to-v3.0.md`. TL;DR:
- Python 3.8+ 必需 (AD-SSME-1)
- 添加 `.aria/state-snapshot.json` 到 `.gitignore` (session artifact)
- 跨项目消费者: 从读取 AI narrative 切换为读 `.aria/state-snapshot.json`
- 临时回退: 设 `state_scanner.mechanical_mode: false` (v1.18.0 失效)

---

## [1.16.4] - 2026-04-23

### Added

- **phase-c-integrator C.2.6 — UPM Milestone Sub-progress Append** (Forgejo #22, opt-in)
  - Config `upm.milestone_driven: false` (默认关闭, opt-in 设为 true)
  - 启用时在 C.2.5 push 完成后追加 UPM sub-bullet: `YYYY-MM-DD: {sha} — {title} ({PR_URL})`, `[ ]` → `[~]`
  - 解决 multi-PR cycle (e.g., schema expand-migrate-contract 3 PR) 下 D.1 前的 1-2 周信息盲区
  - phase-d-closer D.1 新增 "Milestone-driven Mode" 子节: 启用时 D.1 只需 finalize (`[~]` → `[x]` + archive 路径)
  - 源于 M1 closeout (2026-04-23) single-D.1 update 85 tasks 实际痛点 + silknode US-074 multi-PR migration 场景
  - standards `phase-c-integration.md` + `phase-d-closure.md` 同步说明

### Fixed

- **aria-dashboard 3 Major bugs** (Forgejo #23)
  - **M1 Archived spec duration "—"**: Created date 5-step fallback chain (frontmatter strict regex → frontmatter loose regex → git log 首次 commit → archive dir 前缀 YYYY-MM-DD → null)
  - **M2 Audit verdict CSS mislabeling**: 增加 `verdict-warning` (黄色, 覆盖 PASS_WITH_*) + `verdict-neutral` (灰色, 未知 verdict), 修正既有 verdict-revise 色彩; 解析优先读 audit-engine frontmatter `verdict:` 字段
  - **M3 无 Carry-forward 可视化**: 新增 `Carry-forward` HTML section, 数据源为 audit-reports frontmatter + proposal Out of Scope, 按 `target_release` 分组, 对 polish-heavy 工作流关键信息补齐
  - **Minor 4-9 延期** 到 v1.17.x (归档 spec 元信息薄 / 双仓库感知 / docs/decisions 展示 / 审计表截断 / spec 链接 / banner fallback)
  - 真实案例 (truffle-hound v0.2.1 dashboard): `PASS_WITH_POLISH` 不再误染红; v0.2.1 carry-forward 10 条不再丢失

### Level 2 Patch Release 说明

涉及 phase-c-integrator + phase-d-closer + aria-dashboard 3 个 Skill 逻辑变更. 延续 smoke benchmark 模式, full AB deferred.

### Related

- v1.16.4 完成 Phase D.1 milestone-driven 支持 + aria-dashboard Major bug cleanup
- 本 session v1.16.1-v1.16.4 累计修复 8 个 Forgejo Issue

---

## [1.16.3] - 2026-04-23

### Fixed

- **state-scanner Phase 1.5 PRD Status 提取 + `prd_draft_blocking` 推荐规则** (Forgejo #18)
  - Phase 1.5 新增 `prd_files[]` schema: `path` / `status` / `linked_stories` / `launch_date`
  - Status 提取复用 v1.16.1 #17 修复的 Pattern 1-5 (heading-aware, case-insensitive)
  - `linked_stories` 扫描 User Story 文件 `parent_prd:` frontmatter 或 `prd-{basename}` 引用
  - 推荐规则新增 `prd_draft_blocking` (priority 5): Draft PRD + linked_stories ≥ 5 → 优先 "review-prd" 而非开发
  - 输出格式新增 ⚠️ 标注, 无 Draft PRD 时 fallback 原格式 (backward-compat)
  - 真实案例 (silknode Phase 3 Commercial Launch): 20 Story 阻塞不再静默

### Documentation

- **OpenSpec 与 Fission-AI upstream 分叉声明** (Forgejo #25, `standards/openspec/*`)
  - `standards/openspec/VALIDATION.md`: 标记 `@openspec/cli` + `validate --sync/--numbering` 为 DEPRECATED, 指向 `aria:audit-engine` 原生 validator
  - `standards/openspec/project.md`: 新增 "与 Fission-AI OpenSpec 的关系" 章节 (6 维对比表 + 4 条不跟随理由 + 3 类选型指南)
  - `standards/openspec/templates/README.md`: 内联引用 project.md 分叉章节
  - 核心陈述: aria 双层任务架构 (proposal.md + tasks.md + detailed-tasks.yaml) 与 upstream delta-based workflow 结构性不兼容, aria 不跟随 upstream
  - Backward-compat: 所有现有 `openspec/changes/*` + `openspec/archive/*` 保持合法

### Level 2 Patch Release 说明

本 patch 涉及 state-scanner Skill 逻辑变更 (新增 schema + rule) → 延续 v1.16.1/v1.16.2 smoke benchmark 模式, full AB deferred.

### Related

- v1.16.1 + v1.16.2 (2026-04-23 同日): #17 regex / #24 命名约定 / #27 change_id validation / #26 checkpoint gate
- v1.16.3 完成 state-scanner Phase 1.5 post-m0 bug 系列 (#17 + #18 两个 sister bug)
- v1.16.3 完成 OpenSpec standards 文档同步 (#24 + #25 两个 sister issue)

---

## [1.16.2] - 2026-04-23

### Fixed

- **audit-engine pre_merge checkpoint 报告完整性 gate** (Forgejo #26)
  - pre_merge audit 运行时新增 Checkpoint Report Completeness Gate
  - 对 `audit.checkpoints.*: "on"` 的每个 checkpoint, 校验 `.aria/audit-reports/{checkpoint}-*.md` 必须存在 (`post_closure` 除外, post-hoc 审计)
  - 缺失时拒绝 pre_merge 通过, 输出 ERROR 附 3 条修复路径
  - 配置 `audit.allow_incomplete_checkpoints: false` (默认) 提供显式豁免, 豁免时强制 `[WARN] incomplete checkpoint gate bypassed: missing={names}` audit trail
  - 与 Forgejo #27 (v1.16.1 修复) 互补: #26 = 横向完整性 (该跑的都跑了), #27 = 纵向真实性 (报告引的都真)
  - 真实案例 (truffle-hound v0.3.0 2026-04-22): Claude + 用户跳过 Phase A, audit 链条静默断, 发版后 state-scanner 才发现

### Level 2 Patch Release 说明

本 patch 涉及 audit-engine 逻辑变更 (新增 gate) → Phase [2] benchmark 覆盖 #26 + #27 联合验证.

### Related

- v1.16.1 (2026-04-23) 同日发布, 含 #17 state-scanner regex + #27 audit-engine change_id validation + #24 openspec 命名约定
- v1.16.2 是 v1.16.1 的 sister-bug 补丁, 同审计肌理完成

---

## [1.16.1] - 2026-04-23

### Fixed

- **state-scanner Phase 1.5 Status heading regex** (Forgejo #17)
  - Pattern 1 放宽为 `^(?:#{1,6}\s+)?Status:\s*(.+)` 支持 Markdown heading 前缀 (`## Status:`)
  - Pattern 3 中文 `状态` 统一为 `^(?:#{1,6}\s+)?\*{0,2}状态\*{0,2}[：:]\s*(.+)` 覆盖 heading + bold + plain
  - 影响: SilkNode 项目 13/77 Story 由 "unknown" 正确识别为实际状态

- **audit-engine change_id 锚点校验** (Forgejo #27)
  - 写盘前新增 Pre-write validation: change_id 必须对应 `openspec/changes/{id}/proposal.md` 或 `openspec/archive/*-{id}/proposal.md`
  - 配置 `audit.allow_dangling_change_ids: false` (默认) 提供显式豁免路径, 豁免时强制记录 `[WARN]` audit trail
  - 与 Forgejo #26 FR-1 (checkpoint 报告完整性 gate, 待修) 互补
  - 真实案例 (truffle-hound v0.3.0 2026-04-22): change_id 从未有 proposal 背书, 两份 audit 报告 dangling reference

### Documentation

- **OpenSpec change id 命名约定** (Forgejo #24, `standards/openspec/templates/README.md`)
  - 新增章节覆盖 5 维度: version 前缀 / topic 串联 / descriptor tail 枚举 / slug 长度 (硬 60, 软 40) / 多 feature 聚合
  - 引用 truffle-hound 真实 drift 样例作对照
  - 为 brainstorm / spec-drafter / state-scanner 消费者提供统一决策锚点

### Level 2 Patch Release 说明

本 patch 豁免自 `/skill-creator` 全量 benchmark (per `feedback_level2_patch_no_benchmark.md`),
但 state-scanner + audit-engine 修改涉及 Skill 逻辑 → 本 session 后续 Phase [2] 补跑这 2 个 Skill 的针对性 benchmark。

### Related

- M1 MVP closeout (aria-2.0-m1-mvp) 同日完成, 归档位置: `openspec/archive/2026-04-23-aria-2.0-m1-mvp/`

---

## [1.16.0] - 2026-04-15

### Added

- **state-scanner Phase 1.13 `scan_submodules` opt-in** (Spec: `state-scanner-submodule-issue-scan`, PR #19)
  - 新增配置项 `state_scanner.issue_scan.scan_submodules` (boolean, 默认 `false`)
  - 启用时递归扫描 `.gitmodules` 中所有 submodule 的 Forgejo/GitHub issues, 每个 submodule 独立 fail-soft
  - 新增 `issue_status.repos[]` 分组视图 + `schema_version` 字段 (v1.0 / v1.1)
  - `items[]` / `open_issues[]` 同步双写, 保持对 v1.0 消费者的向后兼容
  - 支持 meta-repo 模式 (如 Aria 主 repo + aria-plugin / aria-orchestrator / aria-standards submodule)
- **state-scanner Phase 1.13 `stage_timeout_seconds` 自适应**:
  - `scan_submodules=false` → **12s (不变, 向后兼容)**
  - `scan_submodules=true` → `max(20, (N_submodules+1) × api_timeout_seconds)` 按 submodule 数自动扩展
  - 用户显式设置时尊重覆盖值
- **state-scanner cache schema_version 守卫**: reader 识别 pre-v1.1 旧缓存 → 一次性 cold re-fetch, 避免 silent schema corruption

### Changed

- **state-scanner SKILL.md 版本**: 2.9.0 → **2.10.0**
- **state-scanner references/issue-scanning.md 版本**: 1.0.0 → **1.1.0**
- **open_blocker_issues 推荐规则**: 语义升级为跨 repo 聚合 — 任一 repo (主 + submodule) 的 blocker/critical label 触发降级推荐, 扁平化 items[] 聚合

### Backward Compatibility

- **`scan_submodules=false` (默认)** 场景行为与 v1.15.2 字节级一致 — 相同 12s 超时 + 单 repo 扫描 + 相同输出 schema (不含 `repos` 字段)
- **缓存 schema 迁移**: pre-v1.1 缓存文件被识别为 cold cache, 首次 v1.16.0 run 将一次性 re-fetch 所有 repo (无用户干预)
- **输出 schema**: items[] 新增同步写入 open_issues[] 作为别名, v1.0 消费者不受影响

### Related

- Spec: `openspec/changes/state-scanner-submodule-issue-scan/proposal.md` (Level 2 Draft)
- Parent Spec: `state-scanner-issue-awareness` (2026-04-09 archived) — 本 v1.16.0 扩展其 D6 决策, 不否定原决策
- Sister Spec: `state-scanner-mechanical-enforcement` (Draft) — 独立关注"执行纪律", 单一焦点分离
- Benchmark: `aria-plugin-benchmarks/ab-results/2026-04-15-state-scanner-submodule-issue-scan/` (+41.7pp pass rate)

## [1.15.2] - 2026-04-12

### Fixed

- **check_parity.sh shell injection 防护** — Python heredoc 内的 `$REPO` / `$REMOTE` / `$BRANCH` / `$TIMEOUT_SECONDS` 直接注入改为环境变量传参 + 单引号 heredoc (`<<'PYEOF'`), 防止路径含引号/反斜杠/换行时脚本破坏
- **check_parity.sh 死代码清理** — 删除未使用的 TIMEOUT_CMD 变量构造 (L68-86), timeout 检测已在 ls_remote 调用处内联实现

### Changed

- **verify_post_push.py `--max-retries` 注释增强** — 明确指出 max_retries=3 产生 4 总 attempts (1 initial + 3 retries), 避免命名歧义
- **fallback 路径可移植性文档** — state-scanner / phase-c-integrator / sync-detection.md 中的 `test -f aria/skills/...` 统一为 `test -f "${ARIA_PLUGIN_ROOT:-aria}/skills/..."`, 支持跨项目场景 (非 Aria 主项目时通过环境变量指定路径)

### Notes

- v1.15.2 为 Phase B Code Review 遗留 MINOR 项的集中清理, 无功能变更
- Dogfood 闭环完整: v1.15.0 实施 → v1.15.1 timeout 调优 → v1.15.2 cleanup

## [1.15.1] - 2026-04-12

### Fixed

- **git-remote-helper timeout 默认值** (dogfood 发现) — 从 5s 提升为 15s
  - Forgejo SSH over Cloudflare Access 实测 ls-remote ~8s, 5s 默认 4 次 attempt 全部超时
  - `check_parity.sh --timeout` 默认: 5 → 15
  - `verify_post_push.py --timeout` 默认: 5.0 → 15.0
  - `config.state_scanner.multi_remote.timeout_seconds`: 5 → 15
  - `config.phase_c_integrator.multi_remote_push.post_push_verify`: 新增 `timeout_seconds: 15` + `max_per_remote_seconds: 34 → 74`
  - 快速网络可设 `--timeout=5` 回到 v1.15.0 的 34s 上界
- 更新 schema.md / api.md / SKILL.md 中的 per-remote 时间上界描述 (34s → 74s)

### Notes

- v1.15.1 dogfooding 验证: 双仓库 (aria + 主) × 双远程 (origin + github) 全部 match, attempts=1 (15s 足够 1 次命中)

## [1.15.0] - 2026-04-12

### Added

- **git-remote-helper (US-012, Layer 3)** — 新 internal skill, 提供 Git 多远程 parity 检测与 push 验证的共享基础设施
  - `check_parity` 指令块: per-remote SHA 对比 + shallow/detached/未 fetch refs 守卫
  - `push_all_remotes` 指令块: 严格 post-push SHA 验证 (不依赖 "Everything up-to-date" message)
  - `verify_parity_post_push` 指令块: Python 实现指数退避 [0, 2, 4, 8]s, 上界 34s/remote
  - JSON schema canonical source, 跨平台兼容 (timeout/gtimeout/Python wrapper)

- **state-scanner Phase 1.12 多远程扩展 (US-012, Layer 1)** — 原地扩展, 不消耗 D8 配额
  - `sync_status.multi_remote.*` 新字段: 主仓库 + 子模块 per-remote parity
  - `overall_parity` 精确定义: 排除 `ahead` (正常待推送) 和 `unknown` (网络故障)
  - `multi_remote_drift` 推荐规则 (priority 1.35, warning 非阻塞)
  - 向后兼容: `submodules[]` 现有字段保留, `remote_commit` = origin 的 remote_head

- **phase-c-integrator C.2.5 Multi-Remote Push Enforcement (US-012, Layer 2)** — 合并 PR 后自动推送所有远程 + SHA 验证
  - Per-Remote Matrix Gating: 子模块推 X 失败仅阻断主仓库推 X, 其他 remote 不受影响
  - 失败优先级: `read_only_remotes` > `fail_on_partial_push` > 默认阻断
  - 配置: `.aria/config.json` 顶层 `multi_remote.*` + skill 级 null 继承

### Fixed

- **2026-04-12 v1.14.0 发版事故根因修复** — aria 子模块推 origin 但遗漏 GitHub 的场景, 现由 C.2.5 post-push SHA 验证彻底阻断

### Changed

- `branch-manager` 与 `phase-c-integrator` 边界明确: branch-manager 仍仅推 origin (PR 阶段), 多远程语义在 C.2.5 合并后生效

### AB Benchmark

- eval-10 `multi-remote-parity-drift`: Layer 1 多远程漂移检测 (state-scanner)
- eval-11 `submodule-push-github-sync-miss`: Layer 1 本次事件回归测试
- eval-hlp-1~4: Layer 3 helper (parity check / push / verify retry)
- eval-int-1: Layer 2 integrator (多远程合并推送)

## [1.14.0] - 2026-04-12

### Added

- **state-scanner Phase 1.8 扩展 (aria-plugin#9, PR #11)** — README 检查增强
  - 子模块 `aria/README.md` 版本号 vs `plugin.json` 检测
  - Skill 数量一致性 (排除 `user-invocable: false`, 当前 5 个内部 Skill)
  - Skill 列表完整性 (info 级)
  - Plugin badge 版本检测
  - `readme_outdated` 规则扩展: `readme_skill_count_mismatch` + `readme_badge_mismatch`

- **state-scanner Phase 1.14 (aria-plugin#10, PR #11)** — Forgejo 配置检测
  - 检测 Forgejo remote + `CLAUDE.local.md` 配置状态 (missing/incomplete/configured)
  - `forgejo_config_missing` 推荐规则 (priority 1.45, non-blocking)

- **forgejo-sync PRE_CHECK Step 0 (aria-plugin#10, PR #11)** — 主动引导创建 `CLAUDE.local.md`
  - SSH/HTTPS remote URL 解析, owner/repo 推断
  - 用户确认 [y/N] 后创建/追加, 无状态设计

### Fixed

- **Skill 数量修正**: 33+3=36 → 30+5=35 (agent-router, agent-team-audit 为 user-invocable: false)

### AB Benchmark

- 2 新 eval (readme-skill-count-badge + forgejo-config-detection): avg delta +46.7% (POSITIVE)

## [1.13.0] - 2026-04-11

### Added

- **project-analyzer Skill (US-011, PR #8)** — 扫描项目技术栈/框架/工作模式, 输出 project-profile.yaml
  - Glob + Read 识别 7+ 技术栈 (Node.js/Python/Go/Flutter/Rust/Java/C++)
  - monorepo 子包检测, 工具链识别 (CI/CD/ORM/测试)
  - 降级: 无法识别时输出 unknown + 提示手工补充

- **agent-gap-analyzer Skill (US-011, PR #8)** — 对比项目需求 vs Agent capabilities, 输出覆盖度报告
  - capabilities 标签确定性匹配 (非 LLM 解析)
  - capabilities-taxonomy.yaml 同义词规范化
  - match_rate 标签重合率计算

- **agent-creator Skill (US-011, PR #8)** — 基于缺口分析生成项目级 Agent 配置
  - few-shot exemplar 生成 STCO frontmatter + capabilities + body
  - 确认机制: 交互预览 / --dry-run / --confirm
  - 同名覆盖保护 + 5 技术栈模板 (Node.js/Python/Go/Flutter/generic)

- **capabilities 机读字段** — 11 Agent frontmatter 新增 capabilities 标签列表
- **capabilities-taxonomy.yaml** — 54 个标签 + 同义词映射
- **agent-router v1.1.0** — 运行时注入 .aria/agents/ 项目级 Agent (非 Plugin 静态注册)

### AB Benchmark

- 3 新 Skill with/without 对比: avg delta +0.15 (POSITIVE)
  - project-analyzer: +0.00 (baseline 也能分析, Skill 提供标准 schema)
  - agent-gap-analyzer: +0.25 (确定性匹配 vs 主观评分)
  - agent-creator: +0.20 (dry-run + STCO 强制)

## [1.11.2] - 2026-04-11

### Changed

- **STCO Agent Description 模式 (US-010, PR #6)** — 11 Agent description 重写为 Scope-Trigger-Contract-Output 四要素
  - 6 消歧对: tech-lead↔backend-architect, code-reviewer↔qa-engineer, knowledge-manager↔context-manager
  - PromptX 三段式启发, 自然语言投射 (非 Gherkin 语法)

### Added

- **Handoff Contract v1.0 (US-010, PR #6)** — Agent 间结构化上下文传递协议
  - `subagent-driver/references/handoff-contract.md`
  - 预留 `agent_source: plugin|project` 支持 Layer 2 项目级 Agent

### Fixed

- **legal-advisor 三类行为异常 (Aria#10, PR #7)**
  - 新增 Multi-Round Protocol (修复拒绝承认历史立场)
  - 新增 Output Format YAML verdict 模板 (修复格式不遵循)
  - 新增 Critical Constraints "DO NOT write files" (修复未授权文件写入)

## [1.11.1] - 2026-04-10

### Added

- **Dual Delta Reporting Tool** (`aria-plugin-benchmarks/tools/calc_dual_delta.py`)
  定型自 Aria#8 spike (2026-04-10), 从 prototype 升格为正式 reporting 工具.
  - 计算 `internal_delta` + `cross_project_delta` + `inflation_ratio` 的报告工具
  - 支持 3 种 eval_metadata 格式 + 2 种 grading 字段名
  - 通过 `category` 字段 (可选) 区分 aria_convention / generic_capability / behavior_contract assertions
  - **不是 gate**: Rule #6 不变, 仅 informational
  - 集成 `INFLATION_CAP_UPPER=1.0` 守卫, 病理性负 cross 自动 clamp + warning
  - user-friendly 错误处理 (FileNotFoundError / JSONDecodeError / 格式校验)
  - 9 个 pytest unit tests, 包含 cap 分支 + None 分支真实覆盖
- **ASSERTION_CATEGORY_GUIDE.md** (`aria-plugin-benchmarks/`)
  Category 字段标注指南, 3 个 enum 值 + 5 正反例 + 歧义默认规则
- **HISTORICAL_CAVEATS.md** (`aria-plugin-benchmarks/`)
  Skills 的 dual delta 实测数据存档. 透明度补充, 非警告:
  - state-scanner v2.9.0: inflation 4.9% (VALIDATED)
  - commit-msg-generator v2.0.1: inflation 11.3% (MOSTLY VALIDATED)
- **AB_TEST_OPERATIONS.md "Dual Delta Reporting" 章节** — 两步运行示例 + inflation 解读指南 + 非 gate 声明

### Changed

- **aria-plugin**: v1.11.0 → **v1.11.1** (patch release, transparency enhancement)
- CHANGELOG 注明: **无 breaking change**, 无 Rule #6 变更, 无发版门禁变更

### Background (Why only a patch)

Aria#8 原 RCA 基于纸面估算 ("state-scanner ~50% 虚高" / "commit-msg 100% 虚高") 立了 3 个 Level 3 Spec 计划 Rule #6 重构 + Release Gate 2.0 + Escape Valve. Spike (2026-04-10) 实测**证伪原假说**:

- state-scanner v2.9.0 实测 inflation **4.9%** (噪音级别, 非 ~50%)
- commit-msg-generator v2.0.1 实测 inflation **11.3%** (非 100%)
- 3 个 Level 3 Spec 降级为 1 个 Level 2 Spec

因此 v1.11.1 仅包含透明度工具, **不改变任何发版决策**. 见 `docs/analysis/spike-report-2026-04-10.md`.

### Audit Process

两个独立的审计流程都已通过:

1. **post_spec convergence audit** (Phase A.1, 3 rounds, 4 agents):
   - Agents: tech-lead + knowledge-manager + qa-engineer + code-reviewer
   - Round 1: 1 PASS + 3 REVISE (35 findings: 1 CRITICAL + 13 major + 21 minor)
   - Round 2: 4 PASS (3 new minor: km_n1 标签歧义 + qa nf_01/nf_02 test fixture)
   - Round 3: 4 PASS (0 new findings, **严格收敛** ✅)

2. **Phase B.2 Final Review** (code-reviewer 单 agent 两阶段审查):
   - Phase 1 Spec Compliance: PASS (AC1-AC9 全部验证)
   - Phase 2 Quality: PASS (0 critical, 0 important)
   - Final Vote: **PASS, 0 blockers**

### 已知偏差 (non-blocker, 透明度披露)

- **ASSERTION_CATEGORY_GUIDE.md**: 实际 134 行, Spec AC3 原约束 "≤ 100 行".
  超出的 34 行是 "External category_map files" 和 "How to add categories" JSON 示例,
  显著提升文档实用性. code-reviewer Final Review 接受为 **non-blocking**,
  将在 D.2 归档时 Spec AC3 追认上限为 "≤ 140 行".

### Meta-Lesson

`meta_lesson_spike_first`: 数据驱动的量化假说必须 spike-first 实测验证再立 Spec. 本次避免了 ~1600 行无用工作. 已沉淀到 `MEMORY.md` → `feedback_spike_first_for_data_hypotheses.md`.

### References

- Spec: `openspec/changes/benchmark-transparency-enhancement/proposal.md`
- Spike: `docs/analysis/spike-report-2026-04-10.md`
- Parent Issue: Forgejo Aria#8

---

## [1.11.0] - 2026-04-09

### Added

- **state-scanner v2.9.0** — 两个新子阶段扩展状态感知能力 (Forgejo Issue #6)
  - **Phase 1.12 — 本地/远程同步检测** (`state_scanner.sync_check.*`, 默认开启)
    - 主分支 upstream ahead/behind 计算 (修复 upstream 未配置场景 exit ≠ 0)
    - Submodule 四级 fallback 链 (origin/HEAD → ls-remote → config_default → unavailable)
    - 浅克隆检测 (git ≥ 2.15 `--is-shallow-repository` + `.git/shallow` 兼容 fallback)
    - FETCH_HEAD 跨平台时间戳读取 (`git log -1 --format=%cr`)
    - 不主动 `git fetch` (Tier 2 `ls-remote` 5s 超时例外)
    - 新增推荐规则: `submodule_drift` + `branch_behind_upstream` (降级非阻断)
  - **Phase 1.13 — Issue 感知扫描** (`state_scanner.issue_scan.*`, 默认关闭 opt-in)
    - 平台检测 4 级优先级 (显式 config → hostname 映射 → URL 推断 → 兜底)
    - Forgejo + GitHub CLI 适配 (复用 `forgejo` / `gh` wrapper, 不管理 token)
    - IssueItem normalize 映射 (Forgejo `.labels[].name` vs GitHub `.labels[].name`)
    - 启发式关联 US-NNN 和 OpenSpec change 名 (单词边界正则 + URL 保护)
    - 10 个 `fetch_error` 枚举值统一 (network_unavailable / cli_missing / auth_missing / auth_failed / rate_limited / not_found_or_no_access / timeout / platform_unknown / parse_error / unknown)
    - 15 分钟缓存 TTL (`.aria/cache/issues.json`) + 同步 refresh + 旧缓存 fallback
    - 总阶段超时 12s (Forgejo + CF Access TLS 余量) + API 超时 5s
    - 新增推荐规则: `open_blocker_issues` (降级非阻断)
  - **SKILL.md 阶段数量上限规约** (D8): 当前 13/15 阶段，超过 15 必须重构为分组
- **config-loader v2.9** — 13 个新字段 (sync_check 4 + issue_scan 9) 默认值与验证规则
- **references/sync-detection.md** (新建) — Phase 1.12 完整实现逻辑
- **references/issue-scanning.md** (新建) — Phase 1.13 完整实现逻辑

### Changed

- **state-scanner**: v2.8.0 → v2.9.0 (新增 2 个子阶段, 11 → 13)
- **config.template.json**: 新增 `state_scanner.sync_check` 和 `state_scanner.issue_scan` 完整 block
- **.gitignore**: 新增 `.aria/cache/` 和 `.aria/heartbeat-scan.json` 运行时目录/文件
- **Skill 数量**: 33 (state-scanner 功能扩展，非新增 Skill)

### Fixed

- state-scanner 过去无法检测本地与远程的 sync 状态，容易在陈旧代码上做错推荐
- state-scanner 过去无法感知 open issues，用户需手动轮询平台

### Audit Process

- **post_spec 检查点**: 2 轮 convergence 审计 (Round 1 REVISE 22 issues → Round 2 PASS 收敛)
- **审计报告**: `.aria/audit-reports/post_spec-2026-04-09T1240Z.md` + `post_spec-2026-04-09T1315Z.md`
- **OpenSpec 并行发布**:
  - `openspec/changes/state-scanner-remote-sync-check/` (Level 2)
  - `openspec/changes/state-scanner-issue-awareness/` (Level 3)

---

## [1.10.0] - 2026-04-03

### Added

- **aria-dashboard Skill** — 项目进度看板生成器
  - 5 数据解析器: UPM, User Stories, OpenSpec, Audit Reports, AB Benchmark
  - 单文件自包含 HTML 模板 (深色主题, 响应式, 零 CDN)
  - 跨项目兼容: UPM 双格式 (HTML 注释 + YAML 代码块), Story 中英文字段
  - Issue 存储适配器设计 (Git 原生 + GitHub/Forgejo API 双模式)
  - Phase 1 完整看板交付, Phase 2-3 (Issue 提交 + 心跳 Agent) 待实施

### Changed

- **Skills 总数**: 32 → 33 (29 → 30 user-facing)

---

## [1.9.0] - 2026-04-02

### Added

- **audit-engine Skill** — 多轮收敛/挑战审计编排器
  - convergence 模式: 全员讨论 → 结论提取 → 四元组收敛判定
  - challenge 模式: 讨论组/挑战组对抗 → objections resolved 判定
  - 结构化结论 schema `{type, severity, category, scope, summary}`
  - 汇总引擎 (合并 + 去重 + 冲突标记)
  - 振荡检测 + 未收敛三路径降级策略
  - 审计报告生成 (含 Verdict 计算)
  - AB benchmark: delta +0.5 (WITH_BETTER)
- **7 个审计检查点** — 覆盖十步循环全流程
  - 已有升级: post_spec, post_implementation, pre_merge → audit-engine
  - 新增: post_brainstorm, post_planning, mid_implementation, post_closure
- **config-loader 审计兼容层** — experiments.agent_team_audit 自动映射到 audit.*
- **完整审计配置模板** — 11 Agents x 7 检查点默认分组
- **state-scanner v2.7.0** — 审计状态扫描 + adaptive 路由 + audit_unconverged 推荐规则

### Changed

- **Skills 总数**: 29 → 31 (28 → 29 user-facing, 2 → 3 internal: +audit-engine)
- **state-scanner** — 新增 Phase 1.10 审计状态扫描, Phase 4 adaptive 上下文传递
- **config-loader** — 新增 audit 配置块默认值, 旧配置兼容映射

---

## [1.8.0] - 2026-03-27

### Added

- **aria-report Skill** — 向 Aria 维护团队报告 Bug、提交功能建议或提问
  - 三种 Issue 类型: Bug Report / Feature Request / Question
  - 自动收集环境信息 (Plugin 版本、Skills 数量、OS、配置状态)
  - 隐私审查: 提交前必须用户确认完整内容
  - 三级提交路由: Forgejo (内部) → GitHub API → GitHub Pre-filled URL (降级)
  - 目标仓库: Forgejo `10CG/Aria` / GitHub `10CG/aria-plugin`
  - 与 state-scanner、agent-team-audit 集成建议

### Changed

- **Skills 总数**: 28 → 29 (27 → 28 user-facing)

---

## [1.7.2] - 2026-03-20

### Fixed

- **hooks 重复加载错误** — 删除 plugin.json 中的 `"hooks"` 字段和冗余的 `.claude-plugin/hooks.json`。`hooks/hooks.json` 由 Claude Code 自动加载，无需手动引用

---

## [1.7.1] - 2026-03-19

### Fixed

- **hooks.json 路径解析** — `plugin.json` 中的 hooks 路径从 `./hooks/hooks.json` 改为 `./hooks.json`，hooks.json 移至 `.claude-plugin/` 目录，修复 Claude Code 无法找到 hooks 配置的问题
- **hooks.json 格式修正** — 添加 plugin 专用 `"hooks"` 包装对象和 `"matcher"` 字段

---

## [1.7.0] - 2026-03-19

### Added

- **项目级配置基础设施** (`.aria/config.json`)
  - 新增 `config-loader` 内部 Skill — 统一配置加载、验证、默认值合并
  - `config.template.json` 模板文件，含完整 schema 注释
  - 6 个核心 Skills 集成配置读取 (state-scanner, workflow-runner, tdd-enforcer, branch-finisher, phase-c-integrator, phase-b-developer)
  - 配置优先级: `.aria/config.json` > `.claude/tdd-config.json` > Skill 默认值
- **state-scanner README 同步检查** (阶段 1.8)
  - 检测 README.md 版本号与 VERSION/plugin.json 是否一致
  - 检测最后更新日期与 CHANGELOG 最新条目是否一致
  - 新增推荐规则: `readme_outdated` (优先级 1.3)
- **state-scanner 插件依赖检测** (阶段 1.9)
  - 三状态检测: 无条目 / 未初始化 / 正常
  - 新增推荐规则: `standards_missing` (优先级 1.4, 建议性, 非阻塞)
- **Agent Team 集体审计** (实验功能, 默认关闭)
  - 新增 `agent-team-audit` Skill (experimental)
  - 三个审计触发点: pre_merge, post_implementation, post_spec
  - Verdict 系统: PASS / PASS_WITH_WARNINGS / FAIL
  - 问题去重算法 (category + affected_file)
  - 并发控制: max 2 parallel agents, 120s/300s 超时
  - 集成到 phase-c-integrator (pre_merge) 和 phase-b-developer (post_implementation)

### Changed

- **state-scanner** v2.6.0 — 新增配置加载、README 同步、标准依赖检测
- **RECOMMENDATION_RULES.md** v2.6.0 — 新增 readme_outdated + standards_missing 规则和检测方法
- **.gitignore** — 新增 `.aria/` 运行时文件排除

### Technical Debt (记录)

- state-scanner 阶段号膨胀 (1.0 到 1.9)
- `.claude/tdd-config.json` 与 `.aria/config.json` 长期并存需统一

---

## [1.6.0] - 2026-03-18

### Added

- **workflow-runner auto-proceed 模式** - Phase 间自动推进，减少手动确认步骤
  - 工作流状态持久化 (`.aria/workflow-state.json`)
  - Gate 1 (Spec 审批) 和 Gate 2 (Main Merge) 不可跳过
  - 失败时自动回退到手动模式
- **state-scanner 置信度评分** - 基于三维模型 (信号清晰度/风险等级/可逆性) 量化推荐可信度
  - 高置信度 (>90%) + auto_proceed 时可自动执行 (commit_only/quick_fix/doc_only)
  - 审计日志记录所有自动执行操作
- **SessionStart 中断恢复** - 检测未完成工作流并提示恢复/放弃/检查

### Changed

- **state-scanner** v2.5.0 - 新增置信度评分、自动执行策略、中断检测
- **workflow-runner** - 新增 auto-proceed 模式、状态持久化、Gate 强制机制

### Fixed

- **state-scanner** - 修复置信度评分导致编号选项格式回归的问题
  - 强制默认行为: 必须展示编号选项并等待用户选择
  - 自动执行仅在 `.aria/config.json` 明确配置时触发

### AB Test Verification

- state-scanner: delta +0.165 (WITH_BETTER) — 修复后验证通过
- workflow-runner: delta +0.33 (WITH_BETTER) — 新功能验证通过
- 基线数据: aria-plugin-benchmarks/ab-results/2026-03-18-verification/

---

## [1.5.1] - 2026-02-08

### Fixed

- **state-scanner OpenSpec 检测逻辑** - 修复只扫描 changes 目录，未扫描 archive 目录的问题
  - 新增 `openspec/archive/` 目录扫描支持
  - 明确区分 `standards/openspec/` (格式定义库) 和项目 `openspec/` (工作区)
  - 新增待归档 Spec 检测 (Status=Complete 但仍在 changes/)
  - 新增 OpenSpec 状态输出格式（活跃变更、已归档、待归档）

---

## [1.5.0] - 2026-02-08

### Added

- **openspec-archive Skill** - 归档已完成的 OpenSpec 变更
  - 自动验证 Spec 完成状态
  - 执行 openspec archive CLI 命令
  - **自动修正 CLI 归档位置 bug** (openspec/changes/archive/ → openspec/archive/)
  - 清理空目录并验证最终结果
  - 更新 phase-d-closer 引用新的 openspec-archive skill

### Changed

- **Cloudflare Access 自动处理重构** - 彻底解决 AI 不自动使用 CF Access 配置的问题
  - 新增 `FORGEJO_API_PRE_CHECK.md` - 统一的前置检查规范，作为所有 Forgejo API 调用的唯一真理来源
  - **branch-manager/SKILL.md** - 将前置检查嵌入执行流程 C.2.3，不再作为文档说明
  - **forgejo-sync/SKILL.md** - 引用统一检查规范文档
  - **phase-c-integrator/SKILL.md** - 更新引用统一规范

### Design Philosophy

```yaml
v1.4.1 问题:
  - 检查规则放在文档章节，AI 需要主动理解
  - 配置在 forgejo-sync，但 PR 创建在 branch-manager
  - 没有强制执行点

v1.5.0 解决方案:
  - 创建统一的 FORGEJO_API_PRE_CHECK.md
  - 检查规则嵌入执行流程步骤中
  - AI 按步骤执行时强制检查
  - 所有 Skills 引用同一规范
```

### Fixed

- **AI 自动检测 Cloudflare Access** - 前置检查成为执行流程的一部分，AI 必须执行

---

## [1.4.1] - 2026-02-07

### Added

- **Cloudflare Access AI 自动处理** - AI 主动识别和处理 Forgejo 的 Cloudflare Access 保护
  - 新增 `cloudflare_access` 配置项 - 控制 AI 是否使用 CF Access 模式
  - 新增 `API_CALL_PATTERN.md` - 统一的 Forgejo API 调用模式文档
  - AI 执行前检查规则 - API 调用前自动检测 `cloudflare_access.enabled`
  - 错误自动检测 - API 返回 403/CF 错误时自动提示配置
  - 自动配置提示模板 - 检测到 CF 保护时输出配置示例

### Changed

- **forgejo-sync SKILL.md** - 新增 "AI 执行前检查 (不可协商规则)" 章节
- **branch-manager SKILL.md** - 更新 Forgejo API 调用，支持 CF Access 头部
- **phase-c-integrator SKILL.md** - 添加 Cloudflare Access 引用
- **forgejo-sync 规范 (standards)** - 新增 Cloudflare Access 支持要求

---

## [1.4.0] - 2026-02-07

### Added

- **两阶段代码审查** - Superpowers 风格的代码审查机制
  - 新增 `aria:code-reviewer` Agent - 执行 Phase 1 (规范合规性) + Phase 2 (代码质量) 检查
  - 新增 `requesting-code-review` Skill - 用户可调用入口，自动填充模板并启动审查
  - **subagent-driver** 集成两阶段审查 - 新增 `enable_two_phase` 参数 (默认: true)
  - 审查结果分类: Critical (必须修复) / Important (应该修复) / Minor (建议修复)
  - 支持无计划降级模式 - 无 detailed-tasks.yaml 时仅执行 Phase 2
  - 中英双语支持 - 审查结果可用中文或英文输出
  - 7 个完整示例场景 - 覆盖 PASS/FAIL/WARN/Fallback/分批/调用等场景

### Changed

- **subagent-driver** v1.3.0
  - 新增 `enable_two_phase` 参数控制两阶段审查开关
  - 新增两阶段审查流程图和文档说明
  - 审查模式对比: 传统模式 vs 两阶段模式

- **Skills 总数**: 25 → 26
- **Agents 总数**: 10 → 11

### Design Philosophy

```yaml
两阶段代码审查:
  Phase 1: 规范合规性检查 (Specification Compliance)
    - 验证实现与计划一致
    - 检查功能完整性
    - 检测范围变更
    - 阻塞性: FAIL 终止审查

  Phase 2: 代码质量检查 (Code Quality)
    - 检查代码风格
    - 检查测试覆盖
    - 检查安全性
    - 检查架构设计
    - 阻塞性: 仅 Critical 阻塞

参考实现:
  - obra/superpowers requesting-code-review
  - Superpowers Code Review 最佳实践
```

## [1.3.2] - 2026-02-06

### Changed

- **brainstorm** - v2.0.0 重大重构：基于 Superpowers 最佳实践简化对话流程
  - 移除复杂的 6 状态机 (INIT/CLARIFY/EXPLORE/CONVERGE/SUMMARY/COMPLETE)
  - 采用简洁的 3 阶段流程 (Understanding → Exploring → Presenting)
  - 新增"不可协商规则"强制对话控制
  - SKILL.md 精简 (357 → 262 行, -27%)
  - 新增 `references/principles.md` - 核心原则详解
  - 新增 `references/question-patterns.md` - 提问模式库

### Fixed

- **brainstorm** - 修复 AI 跳过对话直接生成 User Stories 的问题
  - 添加"每次只能问 1 个问题"强制约束
  - 添加"禁止一次性生成所有 User Stories"规则
  - 添加"分段验证"机制 (200-300 词/段)

## [1.3.1] - 2026-02-06

### Fixed

- **state-scanner** - 修复 Windows 环境下 Bash 命令兼容性问题
  - Claude Code 在 Windows 上使用 Git Bash/WSL，而非 Windows CMD
  - 添加跨平台命令对照表 (正确/错误语法对比)
  - 新增 `references/cross-platform-commands.md` 详细参考文档
  - 采用 Progressive Disclosure 最佳实践 (SKILL.md 精简至 1,362 词)

### Changed

- **state-scanner** v2.3.0
  - 精简 SKILL.md 中的实现注意事项章节
  - 将详细命令示例移至 references/cross-platform-commands.md
  - 更新相关文档章节结构，分类更清晰

## [1.3.0] - 2026-02-06

### Changed

- **版本规范化** - 统一所有配置文件版本信息
  - 更新 `marketplace.json` 版本: 1.1.1 → 1.3.0
  - 更新 `hooks.json` 版本: 1.1.0 → 1.3.0
  - 新增 `VERSION` 文件作为人类可读版本快照
  - Skills 数量: 24 → 25

- **tdd-enforcer** - v2.0 重大重构：从代码驱动设计改为**文档驱动设计**
  - 参考 Superpowers 的实现方式，AI 读取文档理解并执行 TDD 规则
  - 移除所有 Python 实现文件 (17+ 模块: test_runners/, validators/, hooks/, tests/)
  - 重写 SKILL.md (798 → 355 行)，采用 Progressive Disclosure 架构
  - 新增 references/ 目录包含 4 个详细参考文档
  - 配置格式变更: `strict_mode` → `strictness` (advisory|strict|superpowers)

- **brainstorm** - v1.1.0 结构优化完成
  - SKILL.md 优化 (1723 → 357 行, -79%)
  - 完整实现 Phase 1-4 核心框架

### Removed

- tdd-enforcer Python 实现:
  - `cache.py`, `config.py`, `diff_analyzer.py`
  - `state_persistence.py`, `state_tracker.py`
  - `test_runners/`, `validators/`, `hooks/`, `tests/` 目录

### Design Philosophy

```yaml
v1.x (错误):
  问题: 把 Skill 当作 Python 包来开发
  - 创建大量 Python 模块
  - 实现复杂的类继承结构
  - 编写单元测试
  根本问题: Claude Code 不会导入执行这些 Python 代码

v2.0 (正确):
  方案: 参考 Superpowers，文档驱动设计
  - SKILL.md 描述工作流
  - AI 读取并理解流程
  - AI 按流程执行检查
  优势: 符合 Agent Skills 设计原则
```

## [1.2.0] - 2026-02-05

### Added

- **brainstorm** Skill - AI-DDD 协作思考引擎，通过多轮对话澄清需求、记录设计决策
  - 三种工作模式: `problem` (问题空间探索), `requirements` (需求分解), `technical` (技术方案设计)
  - 对话状态机: INIT → CLARIFY → EXPLORE → CONVERGE → SUMMARY → COMPLETE
  - 决策记录系统: 结构化记录"为什么选 A 而非 B"
  - 约束管理: 支持 business/technical/team 三类约束
  - 与 state-scanner/spec-drafter 深度集成

- **state-scanner 增强** - 新增头脑风暴推荐规则
  - `fuzziness_requirement`: 检测模糊需求，推荐 problem 模式
  - `missing_prd`: 复杂功能变更，推荐创建 PRD
  - `prd_refinement`: PRD 需要细化，推荐 requirements 模式
  - `tech_design_needed`: 有就绪 Story 无 OpenSpec，推荐 technical 模式

- **spec-drafter 增强** - 内置头脑风暴流程
  - PRD 创建时自动触发 requirements 模式
  - OpenSpec 创建时自动触发 technical 模式
  - 基于讨论结果预填充 proposal.md
  - 决策引用系统，支持完整追溯链

### Changed

- **workflow-runner** - 新增 A.0.5 步骤 (问题空间头脑风暴)
- **Skills 总数**: 24 → 25
- **Progressive Disclosure**: brainstorm SKILL.md 采用三层加载架构 (357 行主文件 + 按需引用)

### Fixed

- 优化 SKILL.md 文件大小 (1723 → 357 行, -79%)，符合最佳实践

## [1.1.1] - 2026-01-28

### Fixed

- **Skills 调用链配置优化** - 修复 `disable-model-invocation` 配置可能阻断 skill-to-skill 嵌套调用的问题

### Changed

- 采用分层控制策略，所有 24 个 skills 显式配置 `disable-model-invocation` 参数
- **入口层 (3个)** - 保持 `disable-model-invocation: true`
  - `workflow-runner` - 十步循环总入口
  - `api-doc-generator` - 独立功能，需用户指定框架
  - `arch-scaffolder` - 独立功能，需用户指定 PRD 路径
- **功能层 (21个)** - 改为 `disable-model-invocation: false`，允许被其他 skills 调用
  - Phase 阶段: phase-a-planner, phase-b-developer, phase-c-integrator, phase-d-closer
  - 核心功能: spec-drafter, task-planner, branch-manager, subagent-driver, commit-msg-generator, progress-updater, arch-update, branch-finisher, strategic-commit-orchestrator
  - 验证/扫描: state-scanner, requirements-validator, tdd-enforcer
  - 同步/搜索: forgejo-sync, requirements-sync, arch-search
  - 内部工具: agent-router, arch-common
- `agent-router` 和 `arch-common` 设置 `user-invocable: false`（内部工具，用户不需要直接调用）

## [1.1.0] - 2026-01-26

### Added

- 初始版本发布
- 24 个 Skills
- 10 个 Agents
- Hooks 系统 (SessionStart, SessionEnd, PreToolUse)
