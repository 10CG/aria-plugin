# Rule #9 Session Handoff — 5-Layer Enforcement Matrix

> **Status**: Active (multi-terminal-coordination v1.22.x+)
> **Origin**: Rule #9 (`CLAUDE.md`) + `standards/conventions/session-handoff.md §3`
> **Extension**: OpenSpec `multi-terminal-coordination` §1.9 + §3.7 — adds frontmatter schema
>   compatibility audit across all 5 layers
> **Task coverage**: TASK-009 (a)(b)(e) in
>   `openspec/changes/multi-terminal-coordination/tasks.md §1.9`
> **Cross-ref**: `standards/conventions/session-handoff.md §3` (原始 enforcement matrix SOT)

---

## 总览表

| Layer | 职责 | 实施状态 | 实施位置 | 引用 Task |
|-------|------|---------|---------|-----------|
| **L1 hook** | 阻断 `.aria/handoff/*.md` 写入 (PreToolUse) | ✅ **不需要改动** — 仅检查路径,P2 frontmatter 不影响此层 | `aria/hooks/handoff-location-guard.sh` | TASK-009 (a) 文档化 |
| **L2 collector** | 检测 misplaced files + 解析 frontmatter | ✅ **已完成** — TASK-009(b) helper ship; TASK-004 consume | `aria/skills/state-scanner/scripts/collectors/handoff.py` + `collectors/handoff_multibranch.py` | TASK-009 (b); TASK-004 |
| **L3 state-scanner** | 推荐 `migrate-handoff-drift` / 多 track 看板渲染 + claim 闸门 | ✅ **P1+P2 全部 ship** — Phase 1.16 fetch + 1.17 multibranch + renderers + writers + phase1_gate + lib/ 9 modules | `aria/skills/state-scanner/` (collectors / renderers / writers / scripts / lib) | TASK-003~007 (P1); TASK-010~022 (P2) |
| **L4 规约 SOT** | `session-handoff.md §2.3` frontmatter schema 权威定义 | ✅ **已完成** — TASK-001 ship (commit `03ddfd0`) | `standards/conventions/session-handoff.md` | TASK-001 |
| **L5 D.3 template** | 写出含 frontmatter 的 handoff doc (硬编码输出路径) | ✅ **已完成** — TASK-002 ship (commit `6cb110f`) | `aria/templates/session-handoff.md` | TASK-002 |

---

## 실施完成度 (P2 ship 後状態, 2026-05-20)

> P1 (Layer H, TASK-001~009) + P2 (Layer L, TASK-010~022) 全部 ship 後の実装状態を記録する。
> P3 (TASK-023~030) は Design A 条件触发 + Rule #6 benchmark + Dogfood の 3 フェーズ。

### P2 ship 後 Layer 实施状態

| Layer | 实施状态 | P1 deliverable | P2 deliverable | P3 remaining |
|-------|---------|----------------|----------------|--------------|
| **L1 hook** | ✅ 完整 (TASK-009a) | `handoff-location-guard.sh` 不修改确认 + 注释文档化 | — (不需要 P2 修改) | — |
| **L2 collector** | ✅ 完整 (TASK-009b + TASK-004) | `parse_handoff_frontmatter()` helper 新增 | TASK-004 consume: `collectors/handoff_multibranch.py` 使用 helper 解析全分支 frontmatter | — |
| **L3 state-scanner** | ✅ P1+P2 ship (TASK-003/004/005/006/007 + TASK-010~022) | Phase 1.16 coordination_fetch + 1.17 handoff_multibranch + renderers/track_board + writers/latest_md_writer + scripts/phase1_gate | lib/ 9 modules: claim_schema, identity, track_id, coordination_ref, orphan_ref_bootstrap, claim_lifecycle, reconcile, failure_handlers, constants | TASK-023 同容器并发检测; TASK-024 worktree 触发流程入口; TASK-025 worktree 生命周期 |
| **L4 规约 SOT** | ✅ 完整 (TASK-001) | `standards/conventions/session-handoff.md` v1.1.0 §2.3 frontmatter schema | — (不需要 P2 修改) | — |
| **L5 D.3 template** | ✅ 完整 (TASK-002) | `aria/templates/session-handoff.md` frontmatter head | — (不需要 P2 修改) | — |

### P2 Layer L ship 详情

| Task | 模块 | 交付物 | 测试 |
|------|------|--------|------|
| TASK-010 | `lib/claim_schema.py` | claim YAML schema v1 (8 字段) + schema_version 前向兼容 | — |
| TASK-011 | `lib/identity.py` | owner/container/session identity 生成 + `~/.aria/container-id` 持久化 | — |
| TASK-014 | `lib/track_id.py` | 确定性 track-id 派生函数 (normalization + SHA256 fallback) | — |
| TASK-012 | `lib/orphan_ref_bootstrap.py` | orphan ref `refs/aria/coordination` 初始化 | — |
| TASK-013 | `lib/coordination_ref.py` | claim CRUD + push/fetch (file-per-writer) | — |
| TASK-018 | `lib/claim_lifecycle.py` + `lib/constants.py` | lifecycle FSM + GC (Finding #3 resolved: constants 迁移完成) | — |
| TASK-015 | `lib/reconcile.py` | 4-rule deterministic reconcile protocol (6-rule final: sole_active + stale_takeover + conflict + all_terminal + no_claims + unknown_sentinel) | TASK-020 55 golden tests |
| TASK-019 | `lib/failure_handlers.py` | 7-case resilient wrapper | TASK-022 23 tests |
| TASK-016 | `scripts/phase1_gate.py` | 9-step 急切认领闸门 | — |
| TASK-017 | `scripts/renderers/track_board.py` | collision render upgrade (reconcile-based collision detection) | — |
| TASK-020 | `tests/test_reconcile_golden.py` | reconcile golden table tests (55 cases) | 55 PASS |
| TASK-021 | `tests/test_race_window.py` | race window tests (12, threading.Barrier zero-sleep) | 12 PASS |
| TASK-022 | `tests/test_failure_injection.py` | failure injection tests (23, 7-case mock.patch) | 23 PASS |

**P2 cumulative**: 90 tests PASS (55 golden + 12 race + 23 failure) + P1 18 tests = **108 total PASS in 1.381s**。

### Round 8 audit 主要结论

- tech-lead: **READY_TO_MERGE** — "P2 Layer L 13 atomic ship 构成完整、内聚的协调机制"
- code-reviewer: **SHIP_NOW** — "Rule #7 audit clean / Rule #9 frontmatter ↔ claim YAML schema alignment verified"
- 6-rule reconcile 含 `sole_active + stale_takeover_eligible` 优雅边角 + clock-skew CONFLICT 不静默

---

## L1 — Hook: handoff-location-guard.sh

### 职责

`aria/hooks/handoff-location-guard.sh` 是 Claude Code PreToolUse hook,在 AI 发出
`Write` / `Edit` / `NotebookEdit` 工具调用时拦截,若目标路径匹配
`.aria/handoff/*.md` 则阻断并返回 JSON deny payload,引导重写到 `docs/handoff/`。

### 不需要改动 — 判定理由

OpenSpec `multi-terminal-coordination` 在 handoff doc 顶部添加 YAML frontmatter
(§2.3.1 schema: `track-id` / `owner-container` / `phase` / `status` / `updated-at`)。
该 frontmatter 写入的目标路径仍是 `docs/handoff/{date}-{slug}.md` (canonical)。

Hook 的守卫逻辑是**纯路径匹配**:

```python
FORBIDDEN_RE = re.compile(
    r"(?:^|[/\\])\.aria[/\\]handoff[/\\][^/\\]+\.md$",
    re.IGNORECASE,
)
```

- `docs/handoff/` 路径不匹配 → pass-through (exit 0,无阻断)。
- frontmatter 内容是写入 `docs/handoff/` 的 canonical 文件内的一段 YAML,
  hook 不解析文件内容,也不关心内容结构。
- L5 template (`aria/templates/session-handoff.md`) 现在输出含 frontmatter 的文档,
  写入目标始终是 `docs/handoff/`,hook 对此场景天然放行。
- Fail-open 设计保持不变:hook 崩溃时 `exit 0` 放行,永远不会阻断向
  `docs/handoff/` 的合法写入。

**结论:L1 hook 零修改,仅在代码中加注释文档化此判定。**

### 相关注释位置

注释已加入 `aria/hooks/handoff-location-guard.sh` 顶部 header 区 (TASK-009 (a) block),
引用本文件路径与 tasks.md §1.9 task ID。

---

## L2 — Collector: collectors/handoff.py

### 职责

`collect_handoff()` 收集 `docs/handoff/` 状态快照(存在性 / 最新文件 / misplaced
检测),输出到 state-scanner snapshot 的 `handoff` 顶层字段 (schema 1.0)。

### 需要改动 — 加 frontmatter-aware helper

TASK-004 (state-scanner Phase 1 跨分支重建多 track 看板) 需要解析每个远程
`docs/handoff/*.md` 的机读 frontmatter 以重建 track 列表。`collect_handoff()`
主流程不感知 frontmatter (它只返回 `latest_path` 等 schema 1.0 字段),TASK-004
需要一个专用 helper 函数。

### 改动范围

**仅新增** `parse_handoff_frontmatter(content: str) -> dict | None` 纯函数。
`collect_handoff()` 主流程**不变** — 向后兼容现有所有 snapshot consumer。

### 函数签名

```python
def parse_handoff_frontmatter(content: str) -> Optional[dict]:
```

- **输入**: handoff doc 全文 (caller 已 `read_text()`)
- **输出**: `dict` 含 5 键 (`track-id` / `owner-container` / `phase` / `status` /
  `updated-at`) 当 frontmatter 完整有效;否则 `None`
- **字段权威**: `standards/conventions/session-handoff.md §2.3.1`

### Edge cases / 容错一览

| 场景 | 返回值 | 处理方式 |
|------|--------|---------|
| 空字符串 | `None` | 直接 return None |
| 无 `---` frontmatter fence (legacy doc) | `None` | regex 不匹配 → legacy fallback per §2.3.4 |
| YAML 解析失败 (`yaml.YAMLError`) | `None` | except Exception → None |
| `yaml` 未安装 (`ImportError`) | `None` | except Exception → None (lazy import) |
| 解析结果不是 `dict` (bare scalar/list) | `None` | isinstance 检查 |
| 5 个必填键有缺失 | `None` | set subset 检查 |
| 某字段值不是字符串 (YAML 类型强制,如 `status: true`) | `None` | isinstance per-key 检查 |
| 完整有效 frontmatter | `dict` (5 键) | 正常路径 |

所有失败场景均静默返回 `None`;错误发出 (soft_error) 由 TASK-004 caller 负责,
本 helper 不修改 `CollectorResult`。

### 向后兼容保证

现有的 `collect_handoff()` 调用方 (state-scanner scan.py) 不感知本 helper 存在,
schema 1.0 `handoff` snapshot 字段结构完全不变。

---

## L3 — state-scanner skill (Phase 1 大改)

### 职责 (v1.22.x+ 目标状态)

state-scanner Phase 1 在推荐前先执行:

1. `git fetch origin refs/heads/* refs/aria/coordination` (有时间戳缓存,< 30s 跳过)
2. 扫描所有 `origin/**/docs/handoff/*.md`,调用 `parse_handoff_frontmatter()` 解析
3. 重建多 track 看板 (TRACK / OWNER/容器 / PHASE / HANDOFF / LAST-PING / STATUS)
4. 检测 collision (cross-owner 强提示 / self-multi-container soft hint per §2.3.5)
5. 急切认领闸门:推荐 → 用户确认 → 二次 fetch → push claim → 放行 Phase B

### 实施范围 (跨多个 Task — P1 + P2 全部 ship)

**P1 Layer H (Phase 1 scan + 看板渲染)**:

| Task | 内容 | 状态 |
|------|------|------|
| TASK-003 | `collectors/coordination_fetch.py` — fetch + 30s TTL 缓存 | ✅ ship |
| TASK-004 | `collectors/handoff_multibranch.py` — `parse_handoff_frontmatter` 消费 + 全分支 track 列表重建 | ✅ ship |
| TASK-005 | `renderers/track_board.py` — 多 track 看板渲染 (collision badge 🔴/🟡) | ✅ ship |
| TASK-006 | `writers/latest_md_writer.py` — `latest.md` 角色降级 (单 track pointer / 多 track deprecation banner) | ✅ ship (D.3-scoped, Finding #2) |
| TASK-007 | 离线退化 — `coordination_fetch.py` offline 分支 + 顶部红条告警 | ✅ ship |

**P2 Layer L (claim/reconcile 协调机制)**:

| Task | 内容 | 状态 |
|------|------|------|
| TASK-010 | `lib/claim_schema.py` — claim YAML schema v1 | ✅ ship |
| TASK-011 | `lib/identity.py` — owner/container/session identity | ✅ ship |
| TASK-014 | `lib/track_id.py` — 确定性 track-id 派生 | ✅ ship |
| TASK-012 | `lib/orphan_ref_bootstrap.py` — orphan ref bootstrap | ✅ ship |
| TASK-013 | `lib/coordination_ref.py` — claim CRUD + push/fetch | ✅ ship |
| TASK-018 | `lib/claim_lifecycle.py` + `lib/constants.py` — lifecycle FSM + GC | ✅ ship |
| TASK-015 | `lib/reconcile.py` — 4→6 rule deterministic reconcile | ✅ ship |
| TASK-019 | `lib/failure_handlers.py` — 7-case resilient wrapper | ✅ ship |
| TASK-016 | `scripts/phase1_gate.py` — 9-step 急切认领闸门 | ✅ ship |
| TASK-017 | `scripts/renderers/track_board.py` — collision render upgrade | ✅ ship |
| TASK-020/021/022 | 90 P2 tests (golden + race + failure) | ✅ 90 PASS |

**P3 remaining**: TASK-023 同容器并发 active claim 检测; TASK-024 worktree 触发流程入口 (phase1_gate 集成到 state-scanner 主流程); TASK-025 worktree 生命周期。

本文档 (TASK-009 e + TASK-029 review) 记录 L3 在 5 层矩阵中的定位与职责边界;
实施细节见各 Task 及 `SKILL.md` §"Layer L Phase B 集成" (TASK-029 新增)。

---

## L4 — Convention SOT: session-handoff.md

### 职责

`standards/conventions/session-handoff.md` 是 Rule #9 的权威文字来源,包含:

- §1 核心条款 + forbidden patterns
- §2 模板结构 (9-section skeleton)
- **§2.3 机读 frontmatter schema** (v1.1.0 新增,multi-terminal-coordination TASK-001)
- §3 Enforcement matrix (本 L4 自身的 SOT)
- §4 Migration notes
- §5 Source incidents

### 改动状态

**已完成** — TASK-001 于 commit `03ddfd0` ship:

- 新增 §2.3 节 (§2.3.1 Schema 字段 / §2.3.2 YAML 示例 / §2.3.3 与 prose 段共存规则 /
  §2.3.4 向后兼容 / §2.3.5 多 owner 语义 / §2.3.6 与 Layer L claim 的区别)
- Version bump: v1.0.0 → v1.1.0 (additive minor)
- 本文档的所有字段定义均以该文件 §2.3.1 表格为权威

### 引用关系

```
CLAUDE.md Rule #9
    └── standards/conventions/session-handoff.md  ← L4 SOT
            ├── §2.3.1 (字段定义) ← L2 helper docstring 引用
            ├── §2.3.4 (向后兼容 fallback) ← L2 helper + L3 消费者行为
            └── §3 (5-layer matrix) ← 本文档 cross-ref
```

---

## L5 — Template: aria/templates/session-handoff.md

### 职责

`aria/templates/session-handoff.md` 是 `phase-d-closer` D.3 step 使用的输出模板。
v1.21.0+ 硬编码输出路径为 `docs/handoff/{YYYY-MM-DD}-{slug}.md`。

v1.22.x+ 升级:模板顶部加 frontmatter 段,确保所有新写出的 handoff doc 自动含完整
§2.3.1 schema,AI 无需手动填写 frontmatter 格式。

### 改动状态

**已完成** — TASK-002 于 commit `6cb110f` ship:

模板新增:

```yaml
---
track-id: {{track_id}}
owner-container: {{owner}}/{{container_id}}
phase: {{phase}}
status: active
updated-at: {{utc_iso_now}}
---
```

hardcoded 输出路径 `docs/handoff/` 保持不变;L1 hook 对此目录放行。

---

## 设计原则与层间关系

```
写入时:
  AI tool call
      │
      ▼
  L1 hook (path guard) ──[.aria/handoff/ ?]──► DENY (exit 0 + JSON block)
      │ [docs/handoff/ → PASS]
      ▼
  L5 template (D.3 output) ── 硬编码 docs/handoff/ + frontmatter

读取时:
  /state-scanner
      │
      ▼
  L3 Phase 1 fetch + scan
      │
      ├── L2 parse_handoff_frontmatter() ── valid frontmatter → track entry
      │                                  └── None → legacy fallback (mtime)
      ▼
  多 track 看板 (TASK-004/005 渲染)

规约:
  L4 session-handoff.md §2.3.1 ← 字段权威 (L2 helper docstring 引用此)
```

### 层间不重叠原则

- L1 负责"写入位置是否违规",不感知内容。
- L2 负责"内容机读解析",不感知工具调用。
- L3 负责"用户可见推荐与看板",消费 L2 输出。
- L4 是文字权威,不执行任何检测。
- L5 是输出闭环,确保所有新产出符合 L4 规约。

---

## 相关文件索引

| 文件 | 说明 |
|------|------|
| `standards/conventions/session-handoff.md` | L4 规约 SOT,§2.3 frontmatter schema 权威 |
| `aria/hooks/handoff-location-guard.sh` | L1 hook 实现 + TASK-009 (a) 注释 |
| `aria/skills/state-scanner/scripts/collectors/handoff.py` | L2 collector + TASK-009 (b) helper |
| `aria/templates/session-handoff.md` | L5 template,含 frontmatter 段 |
| `aria/skills/state-scanner/SKILL.md` | L3 skill 文档 (TASK-003~007 后更新) |
| `aria/skills/state-scanner/RECOMMENDATION_RULES.md` | L3 推荐规则 (rule 1.91 migrate-handoff-drift) |
| `openspec/changes/multi-terminal-coordination/tasks.md §1.9` | TASK-009 原始规约 |
| `openspec/changes/multi-terminal-coordination/proposal.md §What` | Layer H 设计说明 |
