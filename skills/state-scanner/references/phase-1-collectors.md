# Phase 1 Collectors — Detailed Reference

> 详细 collector 模块表 + Step 1.16/1.17 multi-terminal coordination 细节。从 SKILL.md §阶段 1 状态采集 提取 (iter-2, 2026-05-28)。

## 阶段 1: 状态采集 (scan.py 机械产出)

> **字段完整定义 (source-of-truth)**: [state-snapshot-schema.md](./state-snapshot-schema.md)

scan.py 按顺序执行以下子阶段, 每个子阶段对应一个 collector 模块, 产出固定 snapshot 顶层字段:

| 子阶段 | 职责 | Snapshot 顶层字段 | collector 模块 |
|--------|------|-------------------|---------------|
| **0.5** | **Remote refresh** (F3′, main spec `state-scanner-stale-refs-false-parity`) — 并行 fetch 每个 (repo, remote) leg, 跑在**所有其他 collector 之前** | `remote_refresh` | `collectors/remote_refresh.py` |
| 1      | Git / UPM / 变更 | `git` (含 `git_operation_in_progress` 子字段, additive v1.39.0+, Aria #135), `upm`, `changes` | `collectors/git.py`, `collectors/upm.py`, `collectors/changes.py` |
| 1.5    | 需求追踪 | `requirements` | `collectors/requirements.py` |
| 1.6    | OpenSpec | `openspec` (含 `carry_forward_inventory` v1.23.0+) | `collectors/openspec.py` |
| 1.7    | 架构文档 | `architecture` | `collectors/architecture.py` |
| 1.8    | README 同步 | `readme` | `collectors/readme.py` |
| 1.9    | Standards 子模块 | `standards` | `collectors/standards.py` |
| 1.10   | 审计 | `audit` | `collectors/audit.py` |
| 1.11   | 自定义检查 (opt-in) | `custom_checks` | `collectors/custom_checks.py` |
| 1.12   | 同步检测 (单 + 多远程 parity) | `sync_status` | `collectors/sync.py`, `collectors/multi_remote.py` |
| 1.13   | Issue 感知 (opt-in) | `issue_status` *(仅 `issue_scan.enabled=true` 时出现)* | `collectors/issue_scan.py` |
| 1.14   | Forgejo 配置 | `forgejo_config` | `collectors/forgejo_config.py` |
| 1.15   | Session-handoff doc | `handoff` | `collectors/handoff.py` |
| **1.15b** | **Cross-worktree handoff discovery** (single-owner, #139) | `handoff_worktrees` (additive, schema 仍 1.0 不 bump) | `collectors/handoff_worktrees.py` |
| **1.16** | **Coordination fetch** (multi-terminal) — **RETIRED as an independent fetch (F6′, Phase 1 增量 5); 现为 Phase 0.5 `remote_refresh` 的纯派生 shim**, 顺序记号 `1.16` 只为向后兼容既有引用保留, 真实执行序 = **0.5 → …→ 1.16 (派生, 零 I/O)** | `coordination_fetch` | `collectors/coordination_fetch.py` |
| **1.17** | **Cross-branch handoff track rebuild** (multi-terminal) | `tracks_multibranch` | `collectors/handoff_multibranch.py` |
| 聚合   | 失败软错误列表 | `errors` | scan.py 聚合 |

## Opt-in 阶段 (未启用则对应 snapshot 字段 `configured: false`, scan.py 不阻塞)

- **1.11 custom_checks**: 需项目根有 `.aria/state-checks.yaml`
- **1.13 issue_scan**: 默认 `false`, 需 `.aria/config.json` 设 `state_scanner.issue_scan.enabled=true`
- **1.12 sync_check**: 恒开启, 不可关闭 (F9′ 9.2 修文档: `sync.py` 从未读取过 `state_scanner.sync_check.*`
  配置, `enabled=false` 从来不是真实开关 — 它承载 US-008 方向性数据丢失护栏, 关闭它等同关闭该护栏,
  设计上不允许。历史文档曾声称"可关闭"是文档与代码不一致, 详见 `references/sync-detection.md` §7)

## Step 0.5: `remote_refresh` collector — 真 SOT, 跑在最前面 (F3′)

`collectors/remote_refresh.py` 在 `scan.py` 执行序列**最开头**调用 (先于 `collect_git_state`),
并行 fetch 每一个 enforced 的 (repo, remote) leg (主仓 + 全部已初始化子模块), per-host 限流 +
全局 deadline 兜底, 派发按 `fetched_at` 升序防饥饿。这是新鲜度信号唯一的生产者 —— "新鲜度靠获取,
不靠测量"。详见 `references/state-snapshot-schema.md` §`remote_refresh` (真 SOT) 与
`references/predicate-domain-table.md` (D16, `_should_stop_admitting` 等调度层谓词)。

Snapshot 字段: `remote_refresh` (真 SOT, Phase 0.5)。

## Step 1.16: `coordination_fetch` collector — **派生 shim, 零独立 I/O** (F6′, Phase 1 增量 5)

> ⚠️ **本 collector 不再自己 fetch。** Pre-增量5 它独立运行两条 fetch + 自己的 30s TTL 缓存
> (`.aria/cache/coordination-fetch.json`); F6′ 把这套逻辑**退役**, 全部网络 I/O 迁移到上方
> Phase 0.5 `remote_refresh`。本 collector 现在只做一件事: `derive_legacy_coordination_fetch_block`
> —— 一个**纯函数**, 从 `remote_refresh` 的 `(".", "origin")` leg 记录重算出旧 schema (byte
> 兼容), 供 `track_board.py` / `normalize_snapshot.py` 等既有消费者不改代码继续读。

历史行为回顾 (v1.46.0, #141 — 两条独立 fetch 的语义仍在, 只是执行主体换成了 Phase 0.5):
- **Fetch 1 (载重, 先跑)**: `git fetch <remote> --no-tags --prune +refs/heads/*:refs/remotes/<remote>/*` — 分支头, 必须独立成功; F3′ 增加了 `--prune` (Phase 2A gitlink-orphan 检查前提, RC-1)。
- **Fetch 2 (仅 Fetch 1 成功后, 仅 `(".", "origin")` 这一条 leg 跑)**: `git fetch origin --no-tags refs/aria/coordination` — 协调 ref; 缺失 (三重 AND benign 闸) 视为良性"未发布" (`coordination_ref_present=False`), 不报错。
- Fetch 1 失败时不崩溃: 短路不跑 Fetch 2, `success=False` + `error_kind` 由派生函数从 leg 的 `error_kind` 标签映射得出 (不再自己跑 `_classify_error`)。

Snapshot 字段: `coordination_fetch` (additive, schema v1.0+; `coordination_ref_present` 见 #141/v1.46.0; **SOT 已迁移**, 详见 `references/state-snapshot-schema.md` §`coordination_fetch` 派生映射公式 + `collectors/coordination_fetch.py` 模块 docstring)。

## Step 1.17 (TASK-004): `tracks_multibranch` collector

扫描所有 `origin/*` 分支的 `docs/handoff/*.md`, 解析 frontmatter, 重建多 track 列表。Snapshot key: `tracks_multibranch`.

## Step 1.15b (#139): `handoff_worktrees` collector — 跨 worktree 交接发现

`collectors/handoff_worktrees.py` 紧随 1.15 执行, **消费 1.15 `collect_handoff` 产出**作为当前树基准 (scan.py 注册体现 1.15 → 1.15b 依赖顺序), `git worktree list --porcelain` 枚举其余 worktree, 复用 `handoff.py` 的 H5 pointer→mtime `_resolve_latest` helper 解析各树最新 handoff, 在 epoch 域按 frontmatter `updated-at` 仲裁出**全局最新** doc, 当该 doc 落在当前树**之外**的 worktree 时由阶段 2 提示 `EnterWorktree`。只读发现零写入, 不做 claim/heartbeat。单 worktree 项目近乎 no-op (`others=[]`, `global_latest_elsewhere=null`)。Snapshot key: `handoff_worktrees` (additive, schema 仍 1.0 不 bump)。

- 配置: `state_scanner.worktree_scan.enabled` (默认 `true`, 无多 worktree 时零成本 no-op) + `state_scanner.worktree_scan.max_worktrees` (默认 **8**, env `ARIA_WORKTREE_MAX_SCANNED`, 三层 resolver 镜像 `resolve_max_branches_scanned`)。
- 软错 (走 `errors[]` + exit 10): `worktree_enumeration_failed` (git 失败 → `enumerated=false`) / `worktree_unreachable` (单树跳过, 记 path) / `worktree_scan_cap` (超上限截断, warn-only) / `handoff_canonical_scan_failed` + `handoff_pointer_target_missing` + `handoff_stat_failed` (树内失败, message **带 worktree path 前缀**)。他树**不发** #137 `handoff_frontmatter_missing` (该软错语义锚定当前树 latest, 跨树发射会污染 `errors[]` 误触 E2)。

> **与 Layer L TASK-024/025 正交互补** (反向互引, 双向闭环): Layer L TASK-024/025 (见 [layer-l-integration.md §worktree 触发条件](./layer-l-integration.md)) 覆盖 **cross_owner 创建** 独立 worktree (检测到跨 owner collision → 推荐新建 checkout); 本 1.15b 机制覆盖 **single-owner 进入** 已存在 worktree (跨自己的多 worktree 发现最新 handoff → advisory `EnterWorktree`)。**创建 vs 进入** 正交, 两者互不依赖。

## 子阶段深度参考 (实现 + schema 细节)

- Phase 1.12 同步检测 (方向性守卫 / 多远程 parity): [sync-detection.md](./sync-detection.md)
- Phase 1.13 Issue 感知 (平台检测 / 10 种 fetch_error / submodule 聚合): [issue-scanning.md](./issue-scanning.md)
- 所有字段 enum / 边界条件 / additive 演进规则: [state-snapshot-schema.md](./state-snapshot-schema.md)

## AI 阶段 1 职责

仅验证 scan.py 退出码 (0/10/20/30 语义见 SKILL.md §Step 0 表格), 读 snapshot 传入阶段 2。不得手动逐字段解析或补齐。

## Design Decision Notes (HTML-comment placeholders)

### TASK-005 integration design

阶段 2 推荐决策生成 **之前**, 若 snapshot 含 `tracks_multibranch` 且 `exists==true`, 调用 `renderers/track_board.render_track_board(snapshot)` 渲染多 track 看板并展示给用户, 再进入推荐规则匹配。当前 TASK-005 仅提供渲染函数; 集成调用点由后续 phase 指定。Renderer path: `aria/skills/state-scanner/scripts/renderers/track_board.py`。

### TASK-006 integration — DECISION (Round 6 audit closure, 2026-05-20)

`latest_md_writer` 是 **deliberately D.3-scoped** — 不在 scan.py 内自动触发, 不在 P1 内引入 production call-site。理由:

- P1 标榜 "纯读零行为变更", 自动写 latest.md 违反此承诺
- phase-d-closer D.3 step 本就负责 "session 结束写新 handoff + 更新 latest.md", writer 是 D.3 的工具, 而非 collection pipeline 的工具
- 多 track 防接错棒由 `render_track_board(snapshot)` 提供 (读全分支 frontmatter 重建看板), **不依赖** latest.md 重写
- 老 session 读 latest.md 保持向后兼容 (最近一次 D.3 写的内容仍在)

Writer path: `aria/skills/state-scanner/scripts/writers/latest_md_writer.py`。Return dict: `{action: "pointer"|"banner"|"skipped", path: str, content_lines: int}`. 依赖: `snapshot["tracks_multibranch"]["tracks"]` (TASK-004 产出)。

phase-d-closer D.3 集成实施由 TASK-029 (文档同步) 或独立 follow-up task 承担, **不阻塞 P2**。完整决策记录见 `.aria/notes/multi-terminal-coordination-p1-closeout.md §Finding #2`。
