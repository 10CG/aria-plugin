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

| Layer | 职责 | 是否需改动 (multi-terminal-coordination) | 实施位置 | 引用 Task |
|-------|------|------------------------------------------|---------|-----------|
| **L1 hook** | 阻断 `.aria/handoff/*.md` 写入 (PreToolUse) | **不需要** — 仅检查路径,不检查内容 | `aria/hooks/handoff-location-guard.sh` | TASK-009 (a) 文档化 |
| **L2 collector** | 检测 misplaced files + 解析 frontmatter | **需要** — 加 frontmatter-aware helper (向后兼容) | `aria/skills/state-scanner/scripts/collectors/handoff.py` | TASK-009 (b) helper; TASK-004 consume |
| **L3 state-scanner** | 推荐 `migrate-handoff-drift` / 多 track 看板渲染 | **需要** — Phase 1 大改:fetch + 全分支重建看板 + claim 闸门 | `aria/skills/state-scanner/` (scan + 新 collectors/renderers) | TASK-003 / 004 / 005 / 006 / 007 |
| **L4 规约 SOT** | `session-handoff.md §2.3` frontmatter schema 权威定义 | **已完成** — TASK-001 ship (commit `03ddfd0`) | `standards/conventions/session-handoff.md` | TASK-001 |
| **L5 D.3 template** | 写出含 frontmatter 的 handoff doc (硬编码输出路径) | **已完成** — TASK-002 ship (commit `6cb110f`) | `aria/templates/session-handoff.md` | TASK-002 |

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

### 改动范围 (跨多个 Task)

| Task | 内容 |
|------|------|
| TASK-003 | fetch + 缓存时间戳逻辑 |
| TASK-004 | `parse_handoff_frontmatter` 消费 + track 列表重建 |
| TASK-005 | 看板渲染 (多 track 表格 + 颜色 + 折叠) |
| TASK-006 | `latest.md` 角色降级 (多 track → deprecation banner) |
| TASK-007 | 离线退化 + 顶部红条告警 |

本文档 (TASK-009 e) 仅记录 L3 在 5 层矩阵中的定位与职责边界;
实施细节见各 Task 及 `SKILL.md` 更新 (TASK 3.7 a)。

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
