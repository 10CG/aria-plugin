# State Scanner - 推荐规则定义

> 智能工作流推荐引擎的规则配置

## 规则概览

| 规则 ID | 优先级 | 推荐工作流 | 触发条件 | 置信度 | 自动执行? |
|---------|--------|-----------|----------|--------|----------|
| `commit_only` | 1 | C.1 only | 已暂存 + 无未暂存 | 95% | Yes — 已暂存 + 无未暂存信号明确 |
| `readme_outdated` | 1.3 | doc-update | README 版本/日期不一致 | 85% | No — 用户可能有意延后 |
| `multi_remote_drift` | 1.35 | (降级提示) | `multi_remote.overall_parity=false` | 75% | No — 非阻塞，附加 push 建议 |
| `standards_missing` | 1.4 | (建议性提示) | standards 子模块未初始化 | 80% | No — 非阻塞，仅提醒 |
| `requirements_issues` | 1.5 | requirements-check | 需求文档验证有错误 | 85% | No — 用户可能希望延后处理 |
| `architecture_missing` | 1.6 | create-architecture | PRD 存在但无 Architecture | 80% | No |
| `architecture_outdated` | 1.7 | update-architecture | Architecture 状态为 outdated | 80% | No |
| `architecture_chain_broken` | 1.8 | fix-architecture | 需求链路不完整 | 80% | No |
| `pending_followups_p1` | 1.85 | (降级提示) | UPM `## Pending Followups` 含 P1 行 | 75% | No — inter-cycle backlog 提醒 |
| `resume_in_progress_us` | 1.88 | continue-in-progress | `priority_items[]` 含 in_progress US | 80% | No — 跨 session 续作建议 |
| `audit_unconverged` | 1.9 | (建议性提示) | 最新审计报告未收敛 | 75% | No — 用户可能已知并选择接受 |
| `handoff_drift` | 1.91 | migrate-handoff-drift | `handoff.misplaced_files != []` | 95% | No — 文件迁移涉及 git mv,需用户 confirm |
| `custom_check_failed` | 1.95 | (阻断提示) | severity=error 的自定义检查失败 | 90% | No — 需用户确认修复 |
| `custom_check_warning` | 1.96 | (降级提示) | severity=warning 的自定义检查失败 | 70% | No — 非阻塞，附加 fix 建议 |
| `submodule_drift` | 1.97 | (降级提示) | 任一子模块 `tree_vs_remote == true` | 70% | No — 非阻塞，附加 update 建议 |
| `branch_behind_upstream` | 1.98 | (降级提示) | 当前分支落后 upstream >= 5 commits | 65% | No — 非阻塞，附加 pull 建议 |
| `open_blocker_issues` | 1.99 | (降级提示) | 存在 blocker/critical label 的 open issue | 70% | No — 仅 issue_scan.enabled=true 时触发 |
| `prd_draft_blocking` | 5 | review-prd | Draft PRD 且关联 ≥5 Story | 80% | No — 需 owner 拍板 |
| `quick_fix` | 2 | quick-fix | ≤3文件 + 简单修复 | 92% | Yes — ≤3 文件 + 简单类型信号清晰 |
| `feature_with_spec` | 3 | feature-dev | 有 approved OpenSpec | 88% | No — 进入开发是重大步骤 |
| `pending_stories` | 3.5 | start-implementation | 有就绪 Story 可实现 | 75% | No |
| `missing_openspec` | 3.8 | create-openspec | Story 无技术方案 | 70% | No |
| `fuzziness_requirement` | 4 | requirements-refine | 需求模糊需澄清 | 60% | No |
| `missing_prd` | 4.2 | create-prd | 无 PRD 文档 | 65% | No |
| `prd_refinement` | 4.4 | refine-prd | PRD 需细化 | 65% | No |
| `doc_only` | 5 | doc-update | 仅 *.md 文件 | 93% | Yes — 纯文档变更风险低 |
| `feature_new` | 6 | full-cycle | Level2+ 无 Spec | 70% | No — 完整循环需要规划 |
| `requirements_info` | 6.5 | (信息提示) | 需求追踪未配置 | — | No |

> **置信度评分方法**: 基于信号清晰度、风险等级、可逆性三维评估。详见 [references/confidence-scoring.md](./references/confidence-scoring.md)。
> **自动执行策略**: 仅当置信度 >90% 且项目启用 `auto_proceed` 时，推荐可自动执行而无需用户确认。

---

## 规则详情

### 1. commit_only (最高优先级)

```yaml
id: commit_only
priority: 1
description: 变更已就绪，只需提交

conditions:
  all:
    - on_feature_branch: true       # 不在 main/develop/master
    - has_staged_changes: true      # 有已暂存的文件
    - no_unstaged_changes: true     # 无未暂存的修改

recommendation:
  workflow: custom
  steps: [C.1]
  reason: "变更已暂存，只需提交"

detection:
  git_commands:
    - "git branch --show-current"   # 检查当前分支
    - "git diff --cached --name-only"  # 检查暂存区
    - "git diff --name-only"        # 检查未暂存
```

### 1.3 readme_outdated

```yaml
id: readme_outdated
priority: 1.3
description: README.md 版本号或日期与项目不一致

conditions:
  any:
    - readme_version_mismatch: true   # VERSION/plugin.json 与 README 版本不同
    - readme_date_mismatch: true      # CHANGELOG 最新日期与 README 日期不同
    - readme_skill_count_mismatch: true  # aria/skills/ 目录计数与 README "N Skills" 不同
    - readme_badge_mismatch: true     # plugin.json version 与 README badge URL 版本不同

  detection:
    version_source:
      - VERSION file
      - aria/.claude-plugin/plugin.json (version field)
    date_source:
      - CHANGELOG.md (最新条目日期, 非 wall-clock)
    readme_paths:
      - README.md (根目录)
      - aria/README.md (子模块)
    skill_count_source:
      - "ls aria/skills/ (排除 user-invocable: false)"
    badge_source:
      - "README.md badge URL 中的版本号 (正则: Plugin-v[\\d.]+)"

recommendation:
  workflow: doc-update
  steps: [update-readme]
  reason: "README.md 版本信息过时，建议更新以保持一致"
  non_blocking: true  # 不阻塞其他工作流
```

### 1.35 multi_remote_drift

```yaml
id: multi_remote_drift
priority: 1.35
description: 检测到多远程 HEAD 不一致, 存在推送遗漏风险

conditions:
  any:
    - multi_remote.overall_parity: false   # 排除 ahead (has_pending_push) 和 unknown (has_unreachable_remote)

  detection:
    method: "per-remote SHA comparison across main + submodules"
    source:
      - sync_status.multi_remote.main_repo.remotes[*].parity
      - sync_status.multi_remote.submodules[*].remotes[*].parity

recommendation:
  workflow: null
  steps: []
  reason: "检测到 HEAD 未同步到部分远程, 建议: git -C <path> push <remote> <branch>"
  non_blocking: true
```

### 1.4 standards_missing

```yaml
id: standards_missing
priority: 1.4
description: standards 子模块已注册但未初始化

conditions:
  all:
    - gitmodules_has_standards: true   # .gitmodules 有 standards 条目
    - standards_dir_empty: true        # standards/ 目录不存在或为空

  detection:
    check_1: "grep -q 'standards' .gitmodules 2>/dev/null"
    check_2: "ls standards/ 2>/dev/null | head -1"

recommendation:
  workflow: null  # 不推荐工作流，仅提示
  info: "⚠️ aria-standards 子模块已注册但未初始化"
  suggestion: "git submodule update --init standards"
  non_blocking: true  # 建议性，不阻塞
```

### 1.45 forgejo_config_missing

```yaml
id: forgejo_config_missing
priority: 1.45
description: Forgejo 远程已配置但缺少 CLAUDE.local.md 中的 API 配置

conditions:
  all:
    - forgejo_remote_detected: true
    - forgejo_config_status: "missing" | "incomplete"

  detection:
    remote_check:
      - "git remote -v | grep forgejo.10cg.pub"
    config_check:
      - "CLAUDE.local.md 存在性 + forgejo: 块检测"

recommendation:
  workflow: null  # 无自动工作流
  steps: []
  reason: "检测到 Forgejo 远程但缺少 API 配置。运行 /forgejo-sync 可引导创建 CLAUDE.local.md"
  non_blocking: true
```

### 2. quick_fix

```yaml
id: quick_fix
priority: 2
description: 简单修复，快速流程

conditions:
  all:
    - changed_files: <= 3
    - change_type:
        any: [bugfix, typo, config, format]

  change_type_detection:
    bugfix:
      - commit_intent: contains "fix", "修复", "bug"
      - file_pattern: not new files
    typo:
      - commit_intent: contains "typo", "拼写", "错字"
    config:
      - file_pattern: "*.json", "*.yaml", "*.yml", "*.toml"
    format:
      - commit_intent: contains "format", "格式"

recommendation:
  workflow: quick-fix
  phases: [B, C]
  skip_steps: [B.3]
  reason: "简单修复，使用快速流程"
```

### 3. feature_with_spec

```yaml
id: feature_with_spec
priority: 3
description: 已有 OpenSpec，跳过规划

conditions:
  all:
    - has_openspec: true
    - openspec_status: approved

  openspec_detection:
    scan_path: "openspec/changes/*"
    status_check:
      - proposal.md exists
      - status field = "approved" or "in_progress"

recommendation:
  workflow: feature-dev
  phases: [B, C]
  skip_steps: [A.1, A.2, A.3]
  conditional_skips:
    - if: no_architecture_changes
      skip: [B.3]
  reason: "已有 OpenSpec，跳过规划阶段"
```

### 4. fuzziness_requirement

```yaml
id: fuzziness_requirement
priority: 4
description: 需求描述模糊，需要澄清

conditions:
  all:
    - requirements_configured: true
    - requirement_fuzziness: high  # 需求文本含歧义关键词

  fuzziness_detection:
    indicators:
      - vague_terms: ["可能", "大概", "也许", "待定", "TBD"]
      - missing_acceptance_criteria: true
      - no_examples: true

recommendation:
  workflow: requirements-refine
  steps: [requirements-review, clarification]
  reason: "需求描述模糊，建议先澄清再实现"
```

### 4.2 missing_prd

```yaml
id: missing_prd
priority: 4.2
description: 项目无 PRD 文档

conditions:
  all:
    - requirements_configured: true
    - prd_exists: false
    - stories_total: > 0  # 有 Story 但无 PRD

  detection:
    check: "docs/requirements/prd-*.md" not exists

recommendation:
  workflow: create-prd
  steps: [prd-drafting]
  reason: "有 User Story 但缺少 PRD，建议创建产品需求文档"
```

### 4.4 prd_refinement

```yaml
id: prd_refinement
priority: 4.4
description: PRD 存在但需要细化

conditions:
  all:
    - prd_exists: true
    - prd_status: draft
    - prd_completeness: < 70%  # PRD 关键章节不完整

  completeness_check:
    required_sections:
      - objectives
      - user_stories_link
      - success_metrics
      - constraints

recommendation:
  workflow: refine-prd
  steps: [prd-review, prd-update]
  reason: "PRD 关键章节不完整，建议细化"
```

### 5. prd_draft_blocking (2026-04-23 新增, fix #18 PRD Status extraction)

<!-- 优先级 5: 低于 custom_check_failed (p=1.95) / branch_behind_upstream (p=1.98) / submodule_drift (p=1.97) / audit_unconverged (p=1.9); 高于常规开发路径 feature_with_spec (p=3) / quick_fix (p=2) -->
<!-- 与 #17 (v1.16.1 regex heading-aware) 复用 Pattern 1-5 提取 prd_files[].status -->

```yaml
id: prd_draft_blocking
priority: 5
description: "存在 Draft PRD 且关联 ≥5 Story 时, 优先推荐审阅 PRD 拍板"

conditions:
  any:
    - requirements_status.prd_files[]:
        all:
          - status: { in: ["Draft", "draft", "draft (等待用户拍板)"] }  # 大小写不敏感匹配
          - linked_stories: ">= 5"

  detection:
    source: "Phase 1.5 requirements_status.prd_files[]"
    field_check: "status case-insensitive startsWith 'draft' AND linked_stories >= 5"
    prerequisite: "requirements_status.configured == true AND prd_files 非空"

recommendation:
  workflow: null            # 不推荐开发工作流
  recommendation_id: review-prd
  title: "审阅 Draft PRD → 拍板"
  reason_template: "Draft PRD {path} 关联 {linked_stories} 个 Story. 开发前建议先拍板, 避免 PRD 范围调整后返工."
  non_blocking: false       # 阻断性降级 — 不触发常规 workflow 推荐; 用户须明确选择忽略
  degradation: true         # 降级推荐优先级, 常规 feature/fix 推荐作为备选展示

  output_example: |
    ⚠️ Draft PRD 待拍板: docs/requirements/prd-phase3-commercial-launch.md
       关联 20 个 Story. 建议先拍板, 再开始开发, 避免范围返工.
    ○ [2] 忽略 PRD 状态, 继续开发
```

### 5. doc_only (原优先级 5, 与 prd_draft_blocking 同级, 后匹配)

```yaml
id: doc_only
priority: 5
description: 仅文档变更

conditions:
  all:
    - all_files_match: "*.md"
    - no_code_changes: true

  file_type_detection:
    docs: ["*.md", "*.mdx", "*.rst"]
    code: ["*.dart", "*.py", "*.js", "*.ts", "*.java", "*.go"]

recommendation:
  workflow: doc-update
  steps: [B.3, C.1]
  reason: "仅文档变更"
```

### 6. feature_new (兜底规则)

```yaml
id: feature_new
priority: 6
description: 新功能开发，完整流程

conditions:
  all:
    - complexity: >= Level2
    - has_openspec: false

  complexity_assessment:
    Level1:
      - changed_files: <= 3
      - single_module: true
    Level2:
      - changed_files: 4-10
      - or: multi_module, new_api, new_service
    Level3:
      - changed_files: > 10
      - or: architecture_change, breaking_change

recommendation:
  workflow: full-cycle
  phases: [A, B, C, D]
  reason: "新功能开发，建议完整流程"
```

---

## 架构相关规则详情

### 1.6 architecture_missing

```yaml
id: architecture_missing
priority: 1.6
description: PRD 存在但缺少 System Architecture

conditions:
  all:
    - prd_exists: true
    - prd_status: approved
    - architecture_exists: false

  detection:
    prd_check: "docs/requirements/prd-*.md" exists and status = approved
    arch_check: "docs/architecture/system-architecture.md" not exists

recommendation:
  workflow: create-architecture
  steps: [arch-scaffolder or manual creation]
  reason: "PRD 已批准，需要创建 System Architecture"
  suggestion:
    - "参考 standards/core/documentation/system-architecture-spec.md"
    - "或使用 arch-scaffolder skill 自动生成骨架"
```

### 1.7 architecture_outdated

```yaml
id: architecture_outdated
priority: 1.7
description: Architecture 状态为 outdated，需要更新

conditions:
  all:
    - architecture_exists: true
    - architecture_status: outdated

  detection:
    arch_check: "docs/architecture/system-architecture.md"
    status_field: Status = outdated

recommendation:
  workflow: update-architecture
  steps: [arch-update]
  reason: "System Architecture 已过时，建议先更新"
  context:
    last_updated: "{architecture.last_updated}"
    prd_updated: "{prd.last_updated}"
```

### 1.8 architecture_chain_broken

```yaml
id: architecture_chain_broken
priority: 1.8
description: PRD → Architecture 链路不完整

conditions:
  all:
    - architecture_exists: true
    - chain_valid: false

  detection:
    chain_issues:
      - architecture 未引用 parent_prd
      - prd 更新时间晚于 architecture
      - parent_prd 不存在

recommendation:
  workflow: fix-architecture
  steps: [arch-update, requirements-sync]
  reason: "需求链路不完整，建议修复"
  context:
    issues: "{chain_issues}"
```

---

## Inter-cycle surfacing 相关规则详情 (2026-05-09, state-scanner-inter-cycle-surfacing G2/G3/G4)

### 1.85 pending_followups_p1

```yaml
id: pending_followups_p1
priority: 1.85
description: UPM Pending Followups 表存在 P1 行 — inter-cycle backlog 优先级提醒

conditions:
  all:
    - upm.followups exists (key present)
    - any(f.priority == "P1" for f in upm.followups)

  detection:
    snapshot_path: "upm.followups[]"
    field_check: "any row with priority == 'P1'"

recommendation:
  workflow: null  # 不强推工作流，触发降级提示
  info: "📌 UPM Pending Followups 含 {p1_count} 条 P1 项 — 跨 session backlog 待处理"
  display:
    - 前 5 条 P1 项 (item / source / tracking 摘要)
    - handoff_doc 路径 (若 upm.handoff_doc.exists=true)
  suggestion:
    - "Review UPM `## Pending Followups` 表"
    - "若指向 issue/PR, 可调 /aria:state-scanner 重新扫描"
  non_blocking: true
```

**Rationale (placement 1.85)**: 介于 architecture_chain_broken (1.8 — 项目健康) 与 audit_unconverged (1.9 — 流程健康) 之间。架构断链优先于 backlog 提醒, 但 P1 cross-cycle followup 应早于审计未收敛信号浮出 (因为它直接暗示用户该接续什么工作)。

---

### 1.88 resume_in_progress_us

```yaml
id: resume_in_progress_us
priority: 1.88
description: 存在 in_progress User Story — 推荐 inter-cycle resume 续做

conditions:
  all:
    - requirements.stories.priority_items exists
    - any(it.status_normalized == "in_progress" for it in priority_items)

  detection:
    snapshot_path: "requirements.stories.priority_items[]"
    field_check: "any item with status_normalized == 'in_progress'"

recommendation:
  workflow: continue-in-progress
  info: "🔄 续做进行中: {us_id} — {raw_status_first_line}"
  display:
    - in_progress US id + raw_status 第一行
    - 文件路径 (`docs/requirements/user-stories/{id}.md`)
  suggestion:
    - "调 /aria:phase-b-developer 续作 {us_id}"
    - "或 Read {file} 查看当前进度详情"
  non_blocking: false  # in_progress 是强信号，建议直接续做
```

**Rationale (placement 1.88)**: 紧邻 pending_followups_p1 (1.85) 之后。in_progress US 是当前 cycle 进行中的工作信号,优先级与 P1 followup 同级但稍后, 让 cross-cycle backlog 先浮出 (P1 可能是上 cycle 遗留, in_progress 是本 cycle 半成品)。

---

## 审计相关规则详情

### 1.9 audit_unconverged

```yaml
id: audit_unconverged
priority: 1.9
description: 最新审计报告未收敛，建议处理

conditions:
  all:
    - audit_enabled: true
    - has_unconverged: true           # 最新审计报告 converged == false

  detection:
    config_check: "config-loader → audit.enabled"
    report_scan: "ls .aria/audit-reports/*.md 2>/dev/null | sort | tail -1"
    frontmatter_check: "converged: false"

recommendation:
  workflow: null  # 不推荐工作流，仅提示
  info: "⚠️ 最新审计报告未收敛 ({checkpoint})"
  suggestion:
    - "查看报告: {report_path}"
    - "workflow-runner 会在对应阶段自动重新触发审计"
  non_blocking: true  # 建议性，不阻塞工作流
```

### 1.91 handoff_drift (2026-05-14 新增, H0 spec)

```yaml
id: handoff_drift
priority: 1.91
description: 检测到 handoff doc 写错位置 — .aria/handoff/*.md 存在 (canonical 是 docs/handoff/)

conditions:
  all:
    - handoff_misplaced_present: true   # snapshot.handoff.misplaced_files 非空

  detection:
    field: "snapshot.handoff.misplaced_files"
    expected: "[]"
    actual: "list of paths under .aria/handoff/*.md"

recommendation:
  workflow: migrate-handoff-drift
  steps:
    - "git mv .aria/handoff/*.md docs/handoff/"
    - "更新 docs/handoff/latest.md pointer 到迁移后的最新 doc"
    - "rmdir .aria/handoff/ (验证空 dir)"
    - "git commit -m 'chore(handoff): migrate misplaced files to canonical docs/handoff/'"
  info: "🔄 检测到 {misplaced_count} 个 handoff 文件写错位置 (.aria/handoff/, canonical 是 docs/handoff/)"
  suggestion:
    - "迁移漂移文件 (Layer 3 of 5-layer enforcement)"
    - "Convention SOT: standards/conventions/session-handoff.md"
  reason: |
    .aria/ 是机器状态 namespace (workflow-state.json / audit logs / cache 等),
    docs/ 是人类/AI 可读 prose namespace。handoff doc 是 prose,属于 docs/handoff/。
    H0 spec (Forgejo #92) ship 后,本 rule 是 5 层防漂移的 Layer 3 (推荐降级)。
  non_blocking: false       # 阻断性降级 (同 prd_draft_blocking 语义)
  degradation: true         # 降级推荐优先级, 常规 feature/fix 作为备选展示
```

**`non_blocking` 三态语义 (H1 follow-up, PR #46 audit Important-2 澄清)**:

`non_blocking` 不是布尔二态,是三态优先级 gate (与既有规则 prd_draft_blocking L335 / resume_in_progress_us L537 一致):

| 取值 | 语义 | 用例 |
|------|------|------|
| `non_blocking: true` | 建议性 — 仅提示,不改变常规推荐排序 | `audit_unconverged` (1.9), `multi_remote_drift` (1.35) |
| `non_blocking: false` (单独) | 强信号 — 该 rule 推荐优先, 但不显式抑制常规流 | `resume_in_progress_us` (1.88) |
| `non_blocking: false` + `degradation: true` | **阻断性降级** — 抑制常规 workflow 推荐, 该 rule 的修复 workflow 上位为主推荐, 用户须明确选择忽略才回到常规流 | `prd_draft_blocking` (5), **`handoff_drift` (1.91)** |
| `blocking: true` | 硬阻断 — 完全不出常规推荐, 必须先修复 | `custom_check_failed` (1.95) |

`handoff_drift` 取 `degradation` 态 (同 `prd_draft_blocking`): 不硬阻断 (用户当前仍可工作), 但 migrate-handoff-drift 上位为主推荐, 常规 feature/fix 降为备选 (因为漂移会让下次 session 漏读 handoff — H0 痛点)。

**Rationale (placement 1.91)**: 在 `audit_unconverged` (1.9 — 流程未收敛) 之后, `custom_check_failed` (1.95 — 硬阻断) 之前。审计未收敛是更紧迫的流程问题; handoff 漂移虽影响下次 session 但当前可继续工作。优先级数字大于 1.9 表示 "稍后处理 OK", 但应在常规工作流 (commit_only / quick_fix 等) **之前** surface 给 AI 看到。

**配合的其他防御层**:
- **Layer 1 (L1)**: PreToolUse hook `handoff-location-guard.sh` — 阻止新写入 `.aria/handoff/*.md`
- **Layer 2 (L2)**: scan.py `collectors/handoff.py` — 检测 misplaced_files (本 rule 的信号源)
- **Layer 3 (L3, 本 rule)**: state-scanner 推荐迁移工作流
- **Layer 4 (L4)**: `standards/conventions/session-handoff.md` — Convention SOT
- **Layer 5 (L5)**: `phase-d-closer` D.3 template hardcode 写 `docs/handoff/`

完整 spec: `openspec/changes/aria-ten-step-session-handoff-stage/`

---

## 自定义检查相关规则详情

### 1.95 custom_check_failed

```yaml
id: custom_check_failed
priority: 1.95
description: severity=error 的自定义健康检查失败，阻断推荐

conditions:
  all:
    - custom_checks_configured: true
    - custom_checks_has_error_failure: true  # 至少一个 severity=error 的检查 fail

  detection:
    config_check: ".aria/state-checks.yaml exists"
    result_scan: "custom_checks.results[].status == fail AND severity == error"

recommendation:
  workflow: null  # 阻断推荐，要求用户先修复
  info: "🔴 自定义检查失败 ({failed_check_names})"
  suggestion:
    - "修复建议: {fix_command}"
    - "跳过检查: 在 .aria/state-checks.yaml 中设置 enabled: false"
  blocking: true  # 阻断其他推荐
```

### 1.96 custom_check_warning

```yaml
id: custom_check_warning
priority: 1.96
description: severity=warning 的自定义健康检查失败，降级推荐

conditions:
  all:
    - custom_checks_configured: true
    - custom_checks_has_warning_failure: true  # 至少一个 severity=warning 的检查 fail
    - custom_checks_no_error_failure: true     # 无 severity=error 的失败 (否则由 1.95 处理)

  detection:
    config_check: ".aria/state-checks.yaml exists"
    result_scan: "custom_checks.results[].status == fail AND severity == warning"

recommendation:
  workflow: null  # 不推荐工作流，仅提示
  info: "⚠️ 自定义检查警告 ({warning_check_names})"
  suggestion:
    - "修复建议: {fix_command}"
  non_blocking: true  # 不阻塞，附加到推荐输出
```

### 1.97 submodule_drift

```yaml
id: submodule_drift
priority: 1.97
description: 子模块主仓库记录落后远程 (本地 behind remote), 建议更新后再做状态分析

conditions:
  any:
    # **关键修复 (Round 1 pre_merge audit M1)**:
    # 必须同时满足 tree_vs_remote==true AND behind_count > 0
    # 理由: behind_count==0 表示 "本地领先远程" (aria-orchestrator 场景), 此时发出
    # "git submodule update --remote" 是**破坏性**的, 会丢弃本地未推送的 commits.
    # 单独 tree_vs_remote==true 只说明 tree_commit != remote_commit, 方向未明.
    - sync_status.submodules[]:
        all:
          - drift.tree_vs_remote: true
          - drift.behind_count: "> 0"  # 必须真正落后, 不是领先
          - drift.behind_count: "!= null"

  detection:
    source: "Phase 1.12 sync_status.submodules[]"
    field_check: "drift.tree_vs_remote == true AND drift.behind_count > 0"
    prerequisite: "sync_status 存在且 has_remote: true"
    direction_guard: |
      drift.behind_count 是 "tree..remote" rev-list count,
      表示 "主仓库记录落后远程多少 commits".
      若 behind_count == 0 AND tree_vs_remote == true, 意味着本地领先远程
      (local commits 未推送), 此时**不触发**本规则, 应走 submodule_ahead_unpushed 规则
      (后续版本新增) 或仅作 info 级日志.

recommendation:
  workflow: null  # 不推荐工作流，仅降级提示
  info: "⚠️ 子模块 {path} 主仓库记录落后远程 {behind_count} commits, 建议: git submodule update --remote {path}"
  suggestion:
    - "git submodule update --remote {path}"  # 每个 drift 子模块一条
  non_blocking: true  # 降级，不阻断任何现有推荐

# === 补充规约 (Round 1 pre_merge audit M1 fix) ===
safety_note: |
  破坏性操作守卫: 本规则仅在 behind_count > 0 (真正落后) 时触发破坏性 hint.
  当 behind_count == 0 (本地领先远程) 时, 应由 state-scanner 在 output 中
  展示 "本地领先远程 N commits, 建议 git push" 的 info 级提示, 而非调用
  submodule_drift 规则. 此行为需在 references/sync-detection.md 中同步实现.
```

### 1.98 branch_behind_upstream

```yaml
id: branch_behind_upstream
priority: 1.98
description: 当前分支落后 upstream，建议先拉取再开发

conditions:
  all:
    - sync_status.current_branch.behind: ">= 5"
    - sync_status.current_branch.upstream_configured: true

  detection:
    source: "Phase 1.12 sync_status.current_branch"
    field_check: "behind >= 5"
    skip_conditions:
      - "behind == null"   # upstream 未配置或浅克隆，跳过
      - "reason != null"   # detached_head / no_upstream / shallow_clone，跳过

recommendation:
  workflow: null  # 不推荐工作流，仅降级提示
  info: "⚠️ 当前分支落后 {upstream} {behind} commits, 建议先 git pull"
  suggestion:
    - "git pull"
  non_blocking: true  # 降级，不阻断任何现有推荐
```

### 1.99 open_blocker_issues

```yaml
id: open_blocker_issues
priority: 1.99
description: 存在阻塞性 Issue，建议先 triage (v1.1.0+ 聚合所有 repo)

conditions:
  all:
    - issue_scan_enabled: true          # issue_scan.enabled == true (opt-in)
    - issue_status.source: "!= unavailable"  # 数据可用 (非离线/平台未知)
  any:
    - issue_status.items[].labels: contains "blocker"
    - issue_status.items[].labels: contains "critical"

  detection:
    source: "Phase 1.13 issue_status.items[] (aggregated flat view, v1.1.0+ 含所有 repos)"
    label_check: "any(labels contains 'blocker' OR labels contains 'critical')"
    prerequisite: "issue_status.source in [cache, live]"
    # v1.1.0+ 聚合语义:
    #   - scan_submodules=false: items 仅含主 repo, 行为与 v1.0 一致
    #   - scan_submodules=true: items 含所有 repos 的扁平化聚合, 每个 item 带 repo 字段
    # 任一 repo 的 blocker/critical 触发本规则 (不区分主 repo / submodule 的 severity)

recommendation:
  workflow: null  # 不推荐工作流，仅降级提示
  info: "⚠️ 存在 {N} 个阻塞性 Issue (blocker/critical), 跨 {M} 个 repo, 建议先 triage"
  context:
    blocker_issues:
      - "#{number} [{repo}] {title}"  # v1.1.0+: 每个匹配的 issue 一条, 含 repo 来源
  non_blocking: true  # 降级，不阻断任何现有推荐
```

### 自定义检查状态检测

```yaml
custom_checks_detection:
  config_path: ".aria/state-checks.yaml"

  step_1:
    command: "[ -f .aria/state-checks.yaml ] && echo 'EXISTS' || echo 'NOT_EXISTS'"
    result: configured (boolean)

  step_2:
    condition: configured == true
    action: "parse YAML, validate schema version == '1'"
    on_parse_error: "configured = false, parse_error = message"

  step_3:
    condition: configured == true AND checks list non-empty
    action: "串行执行每个 enabled != false 的检查"
    execution:
      working_dir: project root
      timeout_per_check: timeout_seconds (default 15, max 60)
      timeout_total: 60s
      exit_code: 0 = pass, non-zero = fail
      stdout: first line as output
      on_timeout: status = timeout, severity treated as warning
      on_command_not_found: status = error, severity treated as warning

  aggregation:
    total: count(all checks)
    passed: count(status == pass)
    failed: count(status != pass)
    has_error_failure: any(status == fail AND severity == error)
    has_warning_failure: any(status == fail AND severity == warning)
```

---

## 需求相关规则详情

### 1.5 requirements_issues (高优先级)

```yaml
id: requirements_issues
priority: 1.5
description: 需求文档存在问题，需要先修复

conditions:
  all:
    - requirements_configured: true
    - requirements_validation_errors: true

  validation_detection:
    invoke: requirements-validator (check mode)
    check: validation_result.errors > 0

recommendation:
  workflow: requirements-check
  steps: [requirements-validator, requirements-sync]
  reason: "需求文档存在问题，建议先修复"
```

### 3.5 pending_stories

```yaml
id: pending_stories
priority: 3.5
description: 有就绪 Story 可开始实现

conditions:
  all:
    - requirements_configured: true
    - stories_ready: > 0
    - no_active_development: true  # 无进行中的 Story

  stories_detection:
    scan_path: "docs/requirements/user-stories/US-*.md"
    status_field: "Status"
    ready_statuses: [ready]

recommendation:
  workflow: start-implementation
  steps: [create-branch, phase-b-developer]
  reason: "有 {n} 个就绪 Story 可开始实现"
  context:
    ready_stories: [US-001, US-002, ...]
```

### 3.8 missing_openspec

```yaml
id: missing_openspec
priority: 3.8
description: 就绪 Story 缺少技术方案

conditions:
  all:
    - requirements_configured: true
    - stories_ready: > 0
    - story_without_openspec: true

  detection:
    for_each: ready_story
    check: openspec_link is null or openspec not exists

recommendation:
  workflow: create-openspec
  steps: [openspec:proposal]
  reason: "有就绪 Story，建议创建技术方案"
  context:
    uncovered_stories: [US-001, US-003]
```

### 6.5 requirements_info (信息提示)

```yaml
id: requirements_info
priority: 6.5
description: 需求追踪未配置（仅信息提示，不阻塞）

conditions:
  all:
    - requirements_configured: false

  detection:
    check: docs/requirements/ directory not exists

recommendation:
  workflow: null  # 不推荐工作流，仅提示
  info: "提示: 如需使用需求追踪，可创建 docs/requirements/ 目录"
  suggestion:
    - "参考 standards/templates/prd-template.md 创建 PRD"
    - "或继续使用 OpenSpec 作为轻量替代"
```

---

## 条件检测方法

### Git 状态检测

```yaml
git_detection:
  current_branch:
    command: "git branch --show-current"
    is_feature_branch: not in [main, master, develop]

  staged_files:
    command: "git diff --cached --name-only"
    has_staged: output not empty

  unstaged_files:
    command: "git diff --name-only"
    has_unstaged: output not empty

  changed_files_count:
    command: "git status --porcelain | wc -l"
```

### 文件类型检测

```yaml
file_type_classification:
  code:
    mobile: ["*.dart"]
    backend: ["*.py", "*.js"]
    shared: ["*.yaml", "*.json"]

  test:
    pattern: ["*_test.dart", "*_test.py", "test_*.py", "*.spec.js"]

  docs:
    pattern: ["*.md", "ARCHITECTURE.md", "README.md"]

  config:
    pattern: ["*.yaml", "*.yml", "*.json", "*.toml", "pubspec.yaml"]

  architecture:
    pattern: ["*ARCHITECTURE*.md", "docs/architecture/**"]
```

### OpenSpec 检测

**重要**: OpenSpec 有两个不同的目录需要扫描：

1. **`openspec/changes/`** - 活跃变更（进行中的 Spec）
2. **`openspec/archive/`** - 已完成变更（已归档的 Spec）

**注意**: `standards/openspec/` 是格式定义库（Git submodule），不存储项目变更。

```yaml
openspec_detection:
  # 扫描活跃变更 (三态检测)
  changes_scan:
    path: "openspec/changes/"
    step_1: "[ -d openspec/changes/ ] && echo 'EXISTS' || echo 'NOT_EXISTS'"
    step_2: "find openspec/changes/ -name 'proposal.md' 2>/dev/null"
    states:
      not_exists: configured = false                    # 目录不存在
      exists_empty: configured = true, changes.total = 0  # 目录存在但无 proposal.md (干净状态)
      exists_with_content: configured = true, scan proposals  # 正常扫描

  # 扫描已归档变更
  archive_scan:
    path: "openspec/archive/"
    command: "ls -d openspec/archive/* 2>/dev/null || echo 'NO_ARCHIVE'"
    directory_format: "{YYYY-MM-DD}-{feature}"

  status_parsing:
    path: "openspec/changes/{id}/proposal.md"
    field: "Status"
    values: [Draft, Reviewed, Approved, In Progress, Complete]

  # 活跃 Spec 定义
  active_specs:
    filter: status in [Reviewed, Approved, In Progress]

  # 待归档检测
  pending_archive:
    condition: status == Complete AND path starts with "openspec/changes/"
    recommendation: "使用 /openspec-archive 归档"

  # 归档目录解析
  archive_parsing:
    from_directory: "{YYYY-MM-DD}-{feature}"
    extract:
      completion_date: "$1"  # YYYY-MM-DD 部分
      feature_name: "$2"      # feature 名称部分
```

### README 同步检测

```yaml
readme_detection:
  paths:
    - README.md
    - aria/README.md

  version_extraction:
    patterns:
      - "Version.*: (v?[0-9]+\\.[0-9]+\\.[0-9]+)"
      - "\\*\\*Version\\*\\*.*: (v?[0-9]+\\.[0-9]+\\.[0-9]+)"
      - "version: (v?[0-9]+\\.[0-9]+\\.[0-9]+)"

  version_source:
    primary: "cat VERSION 2>/dev/null | grep -oP '[0-9]+\\.[0-9]+\\.[0-9]+'"
    fallback: "grep '\"version\"' aria/.claude-plugin/plugin.json 2>/dev/null"

  date_extraction:
    readme_pattern: "更新.*: ([0-9]{4}-[0-9]{2}-[0-9]{2})"
    changelog_source: "head -20 CHANGELOG.md | grep -oP '[0-9]{4}-[0-9]{2}-[0-9]{2}' | head -1"

  comparison:
    version_match: readme_version == source_version
    date_match: readme_date == changelog_date
```

### Standards 子模块检测

```yaml
standards_detection:
  step_1:
    command: "grep -q 'standards' .gitmodules 2>/dev/null && echo 'REGISTERED' || echo 'NOT_REGISTERED'"
    result: registered (boolean)

  step_2:
    condition: registered == true
    command: "ls standards/ 2>/dev/null | head -1"
    result:
      empty_output: initialized = false
      has_output: initialized = true

  output:
    state_1: { registered: false }                          # 无条目 → 不提示
    state_2: { registered: true, initialized: false }       # 未初始化 → 警告
    state_3: { registered: true, initialized: true }        # 正常 → 无提示
```

### 审计状态检测

```yaml
audit_detection:
  config_check:
    source: "config-loader → audit.*"
    fields:
      enabled: boolean
      mode: "adaptive | convergence | challenge | manual"
      checkpoints: object (各检查点 off/convergence/challenge)

  active_checkpoints:
    filter: "checkpoint value != 'off'"
    adaptive_note: "adaptive 模式下无显式 checkpoints 时由 adaptive_rules + complexity_level 决定"

  last_audit_scan:
    path: ".aria/audit-reports/"
    command: "ls .aria/audit-reports/*.md 2>/dev/null | sort | tail -1"
    frontmatter_fields:
      - checkpoint
      - verdict
      - converged
      - timestamp
    on_empty: "last_audit: null"

  unconverged_check:
    condition: "last_audit.converged == false"
    output: "has_unconverged: true"
```

### 复杂度评估

```yaml
complexity_assessment:
  factors:
    - changed_files_count
    - modules_affected
    - new_files_count
    - api_changes
    - architecture_impact

  scoring:
    Level1: score < 3
    Level2: score 3-7
    Level3: score > 7

  weights:
    changed_files: 1 per 3 files
    new_module: +3
    new_api: +2
    architecture_change: +3
```

### 架构状态检测

```yaml
architecture_detection:
  primary_path:
    path: "docs/architecture/system-architecture.md"
    check: file exists

  fallback_path:
    path: "{module}/docs/ARCHITECTURE.md"
    check: file exists

  status_extraction:
    from: header
    field: "Status"
    values: [draft, active, outdated]

  last_updated_extraction:
    from: header
    field: "Last Updated"
    format: "YYYY-MM-DD"

  parent_prd_detection:
    patterns:
      - "Parent Document.*prd-"
      - "References.*prd-"
      - "Based on.*prd-"
    extract: prd_id

  chain_validation:
    checks:
      - parent_prd_exists: prd file exists
      - parent_prd_match: architecture references correct prd
      - timestamp_order: prd.created <= architecture.created
    output:
      chain_valid: boolean
      chain_issues: list
```

### 需求状态检测

```yaml
requirements_detection:
  directory_check:
    paths:
      - "docs/requirements/"           # 主项目
      - "{module}/docs/requirements/"  # 模块级
    exists: requirements_configured

  prd_scan:
    pattern: "docs/requirements/prd-*.md"
    extract:
      - file_path
      - status (from header)

  stories_scan:
    pattern: "docs/requirements/user-stories/US-*.md"
    extract:
      - story_id
      - status          # 使用多模式提取，见 SKILL.md Phase 1.5 Status 提取模式
      - priority
      - openspec_link
    status_patterns:     # 按优先级尝试，首个匹配即停止
      - /^Status:\s*(.+)/i                          # YAML-like header
      - /\*\*Status\*\*:\s*(.+)/i                   # Markdown bold
      - /\*\*状态\*\*:\s*(.+)/i                     # 中文键名
      - />\s*.*(?:Status|状态)[：:]\s*(.+)/i        # Blockquote 内嵌
      - /\|\s*(?:Status|状态)\s*\|\s*(.+?)\s*\|/i   # 表格列
    on_no_match: "unknown"  # 不报错，标记为未知
    aggregate:
      total: count(*)
      ready: count(status = 'ready')
      in_progress: count(status = 'in_progress')
      done: count(status = 'done')

  validation:
    invoke: requirements-validator (check mode)
    check: validation_result.errors
```

---

## 推荐输出格式

```yaml
recommendation_output:
  primary:
    workflow: string          # 工作流名称
    steps: list               # 要执行的步骤
    skip_steps: list          # 跳过的步骤
    reason: string            # 推荐理由

  alternatives:
    - workflow: string
      reason: string
    - workflow: string
      reason: string

  context:
    phase_cycle: string       # 当前进度
    module: string            # 活跃模块
    changed_files: list       # 变更文件
    openspec_id: string       # 关联的 OpenSpec (如有)
```

---

## 自定义规则扩展

### 添加项目特定规则

```yaml
# 在此添加项目特定规则

custom_rules:
  - id: mobile_widget_update
    priority: 2.5  # 在 quick_fix 和 feature_with_spec 之间
    conditions:
      all:
        - file_pattern: "mobile/lib/widgets/**"
        - changed_files: <= 5
    recommendation:
      workflow: quick-fix
      reason: "Widget 更新，使用快速流程"

  - id: api_contract_change
    priority: 2.8
    conditions:
      all:
        - file_pattern: "shared/contracts/**"
    recommendation:
      workflow: full-cycle
      reason: "API 契约变更，需要完整流程"
```

---

## 规则冲突处理

```yaml
conflict_resolution:
  strategy: first_match  # 按优先级，第一个匹配的规则生效

  logging:
    on_conflict: true
    format: "规则冲突: {rule1} vs {rule2}, 选择 {winner}"

  override:
    user_can_override: true
    override_syntax: "使用 {workflow} 工作流"
```

---

## 调试模式

```yaml
debug_mode:
  enabled: false  # 设为 true 开启详细日志

  output:
    - 检测到的条件值
    - 每个规则的匹配结果
    - 最终选择的规则和理由
```

---

**最后更新**: 2026-05-09

## 变更历史

### v2.11.0 (2026-05-09)

- **新增**: 规则 `pending_followups_p1` (优先级 1.85) — UPM `## Pending Followups` 表存在 P1 行时提示 inter-cycle backlog
- **新增**: 规则 `resume_in_progress_us` (优先级 1.88) — 存在 in_progress User Story 时建议续做
- **关联**: Spec `state-scanner-inter-cycle-surfacing` sub-PR (b) — G2 + G3 + G4 collectors landing in aria-plugin#38 (2026-05-09)
- **依赖**: G2 collector (`upm.followups[]`) + G4 collector (`requirements.stories.priority_items[]`); G3 `upm.handoff_doc` 由 1.85 规则附带使用
- **向后兼容**: 字段缺失时规则条件不满足，不触发；旧 snapshot (pre-TX-G2/G3/G4) 行为与 v2.10.1 一致

### v2.10.1 (2026-04-23)

- **新增**: 规则 `prd_draft_blocking` (优先级 5) — Phase 1.5 prd_files[] status 驱动; Draft PRD 关联 ≥5 Story 时阻断常规开发推荐, 建议 owner 先拍板 (fix #18)
- **依赖**: 需配合 Phase 1.5 prd_files[] 数据 (同次 fix #18 新增); prd_files 为空或 configured=false 时规则自动跳过
- **向后兼容**: prd_files 字段缺失 (旧数据) 时规则条件不满足, 不触发, 行为与 v2.10.0 一致

### v2.10.0 (2026-04-15)

- **修改**: 规则 `open_blocker_issues` (优先级 1.99) — 语义升级为**跨 repo 聚合**, 评估时遍历所有 `issue_status.items[]` (已扁平化, 每个 item 带 `repo` 字段). 任一 repo 的 blocker/critical label 触发降级, 不区分主 repo / submodule severity
- **关联**: Spec `state-scanner-submodule-issue-scan` (Level 2, 2026-04-15 Draft)
- **依赖**: 需配合 `state_scanner.issue_scan.scan_submodules=true` 才能真正看到 submodule 的 blocker; `scan_submodules=false` 时行为与 v2.9.0 一致 (仅主 repo 扫描)
- **向后兼容**: `scan_submodules=false` 默认场景下, 本规则行为与 v2.9.0 字节级一致 — 因为 `items[]` 只含主 repo items, 聚合逻辑退化为单 repo 检查

### v2.9.0 (2026-04-09)

- **新增**: 规则 `submodule_drift` (优先级 1.97) — Phase 1.12 子模块落后远程降级提示
- **新增**: 规则 `branch_behind_upstream` (优先级 1.98) — Phase 1.12 分支落后 upstream >= 5 commits 降级提示
- **新增**: 规则 `open_blocker_issues` (优先级 1.99) — Phase 1.13 blocker/critical Issue 存在降级提示 (仅 issue_scan.enabled=true 时触发)

### v2.8.0 (2026-04-03)

- **新增**: 规则 `custom_check_failed` (优先级 1.95) — severity=error 自定义检查失败阻断
- **新增**: 规则 `custom_check_warning` (优先级 1.96) — severity=warning 自定义检查降级提示
- **新增**: 自定义检查状态检测方法 (YAML 解析 + 命令执行 + 结果聚合)

### v2.7.0 (2026-03-27)

- **新增**: 规则 `audit_unconverged` (优先级 1.9) -- 未收敛审计报告提示
- **新增**: 审计状态检测方法 (config 读取 + 报告扫描 + 未收敛检查)

### v2.6.0 (2026-03-18)

- **新增**: 规则 `readme_outdated` (优先级 1.3) — README 版本/日期同步检测
- **新增**: 规则 `standards_missing` (优先级 1.4) — standards 子模块挂载检测
- **新增**: README 同步检测方法 (version + date extraction)
- **新增**: Standards 子模块检测方法 (三状态: 无条目/未初始化/正常)

### v2.5.0 (2026-03-16)

- **新增**: 置信度评分 (Confidence Scoring) — 每条规则附加置信度和自动执行标识
- **新增**: 规则 `fuzziness_requirement` (优先级 4) — 需求模糊检测
- **新增**: 规则 `missing_prd` (优先级 4.2) — 缺失 PRD 检测
- **新增**: 规则 `prd_refinement` (优先级 4.4) — PRD 细化建议
- **调整**: `doc_only` 优先级 4 → 5, `feature_new` 优先级 5 → 6, `requirements_info` 优先级 5.5 → 6.5
- **参考**: 详细评分方法见 [references/confidence-scoring.md](./references/confidence-scoring.md)

### v2.4.0 (2026-02-08)

- **新增**: OpenSpec archive 目录扫描支持
  - 区分 `openspec/changes/` 和 `openspec/archive/`
  - 添加待归档 Spec 检测
  - 明确 `standards/openspec/` 是格式定义库，不存储项目变更
