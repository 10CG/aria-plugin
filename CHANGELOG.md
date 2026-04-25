# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
