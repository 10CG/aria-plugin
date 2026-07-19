# State Scanner — 基础工作流规则

> 从 [RECOMMENDATION_RULES.md](../../RECOMMENDATION_RULES.md) 拆出。包含基础工作流 (commit_only / quick_fix / feature_with_spec 等) + 架构相关 + 需求相关规则。Total: 14 + 3 + 5 = 22 规则 (v9 新增 `has_unpublished_branch` 1.36, F9′ 9.2)。

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

> **v9 (state-scanner-stale-refs-false-parity F9′ 9.2) 改写**: 旧版把 `overall_parity: false`
> 的所有成因一律建议 `git push` —— 这本身就是一个方向性 bug (behind 场景下 push 毫无意义,
> 甚至可能诱导用户在落后状态下强推)。v9 起**按 (parity, reason, evidence_grade) 六路分派**,
> 不再对整块 `overall_parity: false` 发单一建议。**不是一律 fetch/pull** (US-008 directional
> guard 在 multi_remote 层的对应物)。
>
> **Phase 2A gitlink 交叉引用 (F10″), Phase 4 已接入**: `overall_parity` 的第七种成因是
> `gitlink_integrity[]` 里某 (R,S) 对被 `_gitlink_blocking` 判定 (`status=="orphaned"`, 或
> `orphan_unverified` 且 D18 计数达 `k_eff`)。下方 dispatch 表**已新增第七路** (task 13.3/9.2),
> 建议文案为 `git -C S push R <branch>`。注意它与前六路**正交**: 前六路在 `remotes[*]` 层逐
> remote 判定, 第七路在 `gitlink_integrity[*]` 层逐 (R,S) 对判定 —— 同一次 scan 两层可以同时命中,
> 两条建议都要出, 不是二选一。
>
> **去重/冷却 (OQ-C, tasks 1.3/9.3) — owner 已裁定 2026-07-19: 不造有状态冷却**。本规则不新增
> 任何持久化 debounce 状态; 改用 F1′ 已有的 `has_unreachable_remote` 在**建议层**降级: 该 flag 为
> true (离线 / 全 fetch 失败) 时不走 dispatch, 换一条「离线, 同步状态不可知」降级横幅 (复用
> `coordination_fetch` 现有 `degraded` 红条先例)。见下方 `degrade_when`。
>
> 裁决理由: 全 fetch 失败时 dispatch 的输入本身不可信, 逐条报 drift 是拿不可知当已知; 降级横幅
> 诚实且天然去重 (一次 scan 一条), 不需要记忆「上次提过谁」, 也就不需要新的状态面 —— 与 task
> 3.5d 退避计数器同类的持久化风险一并避开。
>
> 🔴 **降级只作用于建议层, 不作用于 `overall_parity` 裁决层**。裁决层去抖会重新引入假绿, 那正是
> 本 Spec 要根治的病; 裁决层照常 fail-CLOSED 报 false。

```yaml
id: multi_remote_drift
priority: 1.35
description: 检测到多远程 HEAD 不一致 (按成因分派, 不再单一 push 建议)

conditions:
  any:
    - multi_remote.overall_parity: false   # 触发分诊, 具体建议由下方 dispatch 表决定

  detection:
    method: "per-remote (parity, reason, evidence_grade) 分诊, 遍历 main + submodules"
    source:
      - sync_status.multi_remote.main_repo.remotes[*]  # {parity, reason, evidence_grade, behind_count, ahead_count}
      - sync_status.multi_remote.submodules[*].remotes[*]

  dispatch:  # 成因分派: v9 六路 (remotes[] 层, 一个 remote 只落一路) + Phase 4 第七路 (gitlink 层, 正交)
    - cause: "behind / diverged"
      match: "parity in (behind, diverged)"
      action: "建议 pull: git -C <path> pull <remote> <branch> (diverged 需人工 merge/rebase 决策)"
      triggers_rule: true
    - cause: "ahead"
      match: "parity == ahead"
      action: "不重复 — 已由 has_pending_push 覆盖, 本规则不再对 ahead 发建议"
      triggers_rule: false
    - cause: "benign unknown"
      match: |
        parity == unknown AND reason in (detached_head, shallow_clone, remote_branch_missing)
        OR (parity == unknown AND reason == no_local_tracking_ref AND evidence_grade == fresh)
      action: "不触发 — 复用 multi_remote._BENIGN_UNCONDITIONAL_REASONS 同源判据, 零证据不当负证据"
      triggers_rule: false
    - cause: "no_local_tracking_ref (非 benign, 即 evidence_grade != fresh)"
      match: "parity == unknown AND reason == no_local_tracking_ref AND evidence_grade != fresh"
      action: "改路由到新规则 has_unpublished_branch (见 1.36) — 不在本规则内重复建议"
      triggers_rule: false
    - cause: "not_refreshed / network_timeout / auth_failed"
      match: "parity == unknown AND reason in (not_refreshed, network_timeout, auth_failed)"
      action: "「无法验证, 请检查网络或凭据」— 不建议 pull/push (方向未知, 盲建议有害)"
      triggers_rule: true
    - cause: "其他 reason (fail-CLOSED 补集, 非正列举)"
      match: "parity == unknown AND reason not in 以上任何枚举 (含 rev_list_failed / parse_error / 未来新增枚举)"
      action: "同「网络凭据」档处理 (fail-CLOSED — 未识别的 reason 保守当作不可验证, 不建议方向性操作)"
      triggers_rule: true
    # 第七路 (task 13.3/9.2, Phase 4 接入): gitlink 层成因。上面六路都在
    # `remotes[*]` 层逐 remote 判定; 本路在 `gitlink_integrity[*]` 层逐 (R,S) 对判定,
    # 与前六路正交 —— 同一次 scan 可以同时落某个 remote 的 behind 档和某个 (R,S)
    # 对的 gitlink 档, 两条建议都要出。
    - cause: "gitlink orphaned (F10″ 第七种成因)"
      match: |
        gitlink_integrity[*] 中存在被 _gitlink_blocking 判定的对:
        status == "orphaned"  OR  (status == "orphan_unverified" AND consecutive_unverified >= k_eff)
      action: |
        「主仓在 <remote> 上引用的子模块 <submodule> commit 在 <remote> 上不存在 —
        从 <remote> clone --recursive 会断裂。修法: git -C <submodule> push <remote> <branch>」
        (方向是推子模块, 不是动主仓 gitlink —— 主仓引用是对的, 缺的是子模块那侧的镜像)
      triggers_rule: true

  # OQ-C 裁决 (owner 2026-07-19, tasks 1.3/9.3): 建议层降级, 不造有状态冷却。
  degrade_when:
    match: |
      multi_remote.has_unreachable_remote == true
      OR 所有 enforced remote 的 evidence_grade ∈ {stale_unverified, expired}
      (即: 本次 scan 没有任何一条腿拿到新鲜证据)
    behavior: |
      不走上方 dispatch, 换成一条「离线 / 远端不可达, 同步状态不可知」降级横幅
      (复用 coordination_fetch 现有 degraded 红条先例)。
    rationale: |
      没有任何新鲜证据时六路 dispatch 的输入本身就不可信 —— 逐条报 remote drift 是拿
      不可知当已知。降级横幅诚实且天然去重 (一次 scan 一条), 不需要记忆「上次提过谁」。
    🔴_why_not_has_unreachable_alone: |
      初版只写 `has_unreachable_remote == true`, 而该 flag 的实现是
      `fetch_ok == "false"` —— **离线扫描时每条腿是 `not_attempted` 而非 `false`**
      (remote_refresh 在 is_scan_offline() 下走 _not_attempted_outcome), 所以
      `has_unreachable_remote` 为 false ⇒ 降级横幅在它点名要覆盖的「离线」场景下
      永不触发, dispatch 照常在 expired 证据上逐条报 drift。三态语义 (true /
      false / not_attempted) 不能压回二值来判「能不能信」: 「没去问」和「问了失败」
      对可达性是两回事, 但对**证据是否新鲜**是同一回事 —— 所以第二个子句按
      evidence_grade 判, 而不是把 not_attempted 硬塞进 unreachable。
    scope: |
      🔴 只作用于建议层, 不作用于 `overall_parity` 裁决层。裁决层去抖会重新引入假绿 ——
      那正是本 Spec 要根治的病。裁决层照常 fail-CLOSED 报 false。

recommendation:
  workflow: null
  steps: []
  reason: "检测到多远程 HEAD 不同步 — 具体建议按上方 dispatch 表逐 remote / 逐 (R,S) 对生成 (pull / 推子模块 / 查网络凭据 / 无), 不再笼统建议 push"
  non_blocking: true
```

### 1.36 has_unpublished_branch (v9 新增, F9′ 9.2 第四路成因)

```yaml
id: has_unpublished_branch
priority: 1.36
description: 某 remote 上从未见过本地分支的 tracking ref (非「暂时未验证」, 是「大概率真的没推过」)

conditions:
  any:
    - multi_remote_remote_entry:
        parity: unknown
        reason: no_local_tracking_ref
        evidence_grade: "!= fresh"   # v9 9.2: fresh 时归 1.35 的 benign unknown 分支, 不重复触发本规则

  detection:
    source:
      - sync_status.multi_remote.main_repo.remotes[*]
      - sync_status.multi_remote.submodules[*].remotes[*]
    field_check: "parity == unknown AND reason == no_local_tracking_ref AND evidence_grade != fresh"

recommendation:
  workflow: null
  steps: []
  reason: "⚠️ {path} 在 remote {name} 上未见到本地分支的 tracking ref, 可能从未推送过 — 建议: git -C <path> push -u {name} <branch> (先确认分支名, 不要盲目假设已存在)"
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

### 2.5. emergency_hotfix (#58, v1.35.0)

> prod 紧急修复 lighter lane (advisory)。优先级数值 **1.85** (< quick_fix 2, 与 audit_unconverged 1.9 同档但更急)。**主触发 = `hotfix/*` 分支**; commit `hotfix(...)` prefix 仅 corroborating (best-effort, future commit 开发期未提交)。

```yaml
id: emergency_hotfix
priority: 1.85       # < quick_fix 2; 排序靠前 (数字越小越优先)
confidence: 85%
auto_execute: No     # 紧急但需人判断, 不自动执行
description: prod 紧急修复 lighter lane (advisory)

conditions:
  any:
    - branch: matches "hotfix/*"           # 主触发 (git.current_branch)
    - commit_intent: prefix "hotfix("       # corroborating (best-effort, git.recent_commits[0].subject)

recommendation:
  workflow: emergency-hotfix
  phases: [B, C, D]
  skip_steps: [A.1, A.2, A.3]              # commit body + Prod-Validated trailer 取代独立 spec
  reason: "prod 紧急修复, lighter lane"
  notes:
    - "B.2 单测可被 manual prod validation 替代 —— 仅当 commit 含 Prod-Validated: trailer + 根因块 (phase-b-developer 机检; 无 trailer → block 回标准 lane)"
    - "pre_merge audit (若 enabled) 降级 convergence (不 challenge)"
    - "commit 必含: 根因 + Prod-Validated: <evidence> trailer (见 standards/conventions/git-commit.md)"
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

