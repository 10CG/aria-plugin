# State Scanner - 推荐规则定义

> 智能工作流推荐引擎的规则配置

## 规则概览

| 规则 ID | 优先级 | 推荐工作流 | 触发条件 | 置信度 | 自动执行? |
|---------|--------|-----------|----------|--------|----------|
| `git_operation_in_progress` | 0.5 | (阻断提示) resolve-git-operation | `git.git_operation_in_progress.operation != "none"` | 90% | No — 须先 `git <op> --continue`/`--abort`,降级/阻止含 checkout·分支操作的常规推荐;`has_conflicts=true` 措辞升级 (Aria #135) |
| `commit_only` | 1 | C.1 only | 已暂存 + 无未暂存 | 95% | Yes — 已暂存 + 无未暂存信号明确 |
| `readme_outdated` | 1.3 | doc-update | README 版本/日期不一致 | 85% | No — 用户可能有意延后 |
| `multi_remote_drift` | 1.35 | (降级提示) | `multi_remote.overall_parity=false`, 按 (parity,reason,evidence_grade) 六路分派 (v9); `gitlink_integrity[]` blocking (F10″, Phase 2A) 是第七种成因,尚未接入本表 dispatch — 见 basic-rules.md §1.35 已知缺口 | 75% | No — 非阻塞，behind/diverged→pull；ahead 不重复(见 has_pending_push)；benign unknown 不触发；no_local_tracking_ref 非 fresh→改路由 1.36；not_refreshed/network/auth/其他→查网络凭据，不建议方向性操作 |
| `has_unpublished_branch` | 1.36 | (降级提示) | 某 remote `parity=unknown, reason=no_local_tracking_ref, evidence_grade!=fresh` (v9 新增) | 60% | No — 非阻塞，附加 `push -u` 建议 |
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
| `multi_terminal_follower_detected` | 1.51 | standby-observer | 本 container 在 `tracks_multibranch` 无 active owned track, 其他 container 有 | 90% | No — 仅信息提示, 不强制行为 |
| `follower_safe_tasks_suggested` | 1.52 | (信息提示) | Rule 1 触发, 推荐 non-conflict 候选 task | 85% | No — 候选清单仅供参考 |
| `multi_terminal_handoff_dual` | 1.53 | phase-d-closer-follower | D.3 阶段 + 多 track + leader pointer 仍在 latest.md | 88% | No — phase-d-closer 阶段建议 |
| `concurrent_churn_detected` | 1.54 | (降级提示) | `tracks_multibranch.collision.kind != none` 且 config `coordination.enabled == false` (显式 opt-out 才触发 — Part A1 起默认 true, 缺省走 phase1_gate 不走本 rule) | 75% | No — advisory, 不 auto-enable (#133) |
| `prd_draft_blocking` | 5 | review-prd | Draft PRD 且关联 ≥5 Story | 80% | No — 需 owner 拍板 |
| `emergency_hotfix` | 1.85 | emergency-hotfix | `hotfix/*` 分支 (主) / commit `hotfix(` prefix (corroborating) | 85% | No — 紧急但需人判断 (#58, 详见 references/rules/basic-rules.md) |
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

> **Cross-ref — cross-worktree advisory (非优先级表规则, #139)**: 跨 worktree handoff 发现的 advisory **不进上方优先级数值表**, 它是 [references/recommendation-stages.md](./references/recommendation-stages.md) §handoff awareness 集成的新增分支 (触发时序在所有表内规则之前, 与既有 handoff awareness 分支同位, 无 priority 数值)。触发条件: `handoff_worktrees.global_latest_elsewhere != null && handoff_worktrees.global_latest_elsewhere.status == "active"` → 警示 + 编号选项 `[1] EnterWorktree / [2] 留在当前 worktree / [3] 先看该 handoff` (advisory-over-hardlock, 用户选 [1] 才切)。数据来自 Phase 1.15b `handoff_worktrees` collector。

---


## 规则详情 (分类拆分, v1.32.0 起)

> RECOMMENDATION_RULES.md v1.32.0 起按 category 拆 3 子文件 (progressive disclosure, 单文件 1523 行 → main 120 行 + 3 子文件)。AI 按 trigger condition 优先级匹配规则, 命中后查阅对应子文件细节。

### 基础规则 (21 条)

工作流类 (commit_only / quick_fix / feature_with_spec / fuzziness_requirement / doc_only / feature_new 等) + 架构类 (architecture_missing / outdated / chain_broken) + 需求类 (requirements_issues / pending_stories / missing_openspec / missing_prd / prd_refinement)。详见 [references/rules/basic-rules.md](./references/rules/basic-rules.md)。

### 进阶规则 (16 条)

Inter-cycle surfacing (pending_followups / resume_in_progress_us / carry_forward_info+pile) + 审计 (audit_unconverged / handoff_drift) + 自定义检查 (custom_check_failed / warning / submodule_drift / branch_behind / open_blocker_issues) + Multi-Terminal 协调 (follower_detected / safe_tasks_suggested / handoff_dual)。详见 [references/rules/advanced-rules.md](./references/rules/advanced-rules.md)。

### 操作元数据

条件检测方法 (自定义检查状态检测 / 同步检测 / Issue 感知 / handoff awareness 等) + 推荐输出格式 + 自定义规则扩展 + 规则冲突处理 + 调试模式。详见 [references/rules/operations.md](./references/rules/operations.md)。

---

## 变更历史

### v2.12.0 (2026-06-05)

- **新增**: 规则 `git_operation_in_progress` (优先级 0.5, 最高) — `git.git_operation_in_progress.operation != "none"` (rebase/merge/cherry_pick/revert/bisect 暂停态) 时降级/阻止含 checkout·分支操作的常规推荐, 引导先 `git <op> --continue`/`--abort`; `has_conflicts=true` 措辞升级
- **关联**: Spec `state-scanner-git-operation-awareness` / Forgejo Aria #135 — git.py `_detect_git_operation` collector 字段 (additive)
- **依赖**: `git.git_operation_in_progress` 字段 (TG-A); 与 `interrupt.status` 正交, 不篡改既有中断恢复语义
- **向后兼容**: 字段为 `none` 形态或缺失时规则不触发, clean 仓库行为与 v2.11.0 一致

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
