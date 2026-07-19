# Status Field Best Practices

> state-scanner 通过 `_normalize_status` 归一化 OpenSpec proposal.md / User Story 的 `Status:` 行。从 SKILL.md §Status 字段最佳实践 提取 (iter-2, 2026-05-28)。

state-scanner 通过 `_normalize_status` 把 OpenSpec proposal.md / User Story 的 `Status:` 行归一化为 lifecycle state (`archived` / `deprecated` / `pending` / `in_progress` / `implemented` / `approved` / `reviewed` / `active` / `ready` / `done` / `unknown`), 驱动 `pending_archive` / `requirements` / 各类推荐规则。

> **#166 note**: done 家族含 `completed` —— #101 的 `\bcomplete\b` 词边界修复曾把自然词形 `Completed` 误落 `unknown` (进而触发 `design_deferred` 噪音)。`\bcompleted\b` 不匹配 `uncompleted`/`incomplete` (无边界), 故 #101 仍闭合。

## Supported token set

按 priority 顺序 (从最高到最低):

| 类别 | tokens | normalized state |
|------|--------|------------------|
| 终态 (irreversible) | `archived` | `archived` |
| | `deprecated` | `deprecated` |
| 待开始 | `draft`, `pending`, `placeholder` | `pending` |
| 进行中 | `in progress`, `in_progress`, `in-progress`, `进行中` | `in_progress` |
| 已批准 | `approved` | `approved` |
| **已实施** (post-merge, awaiting verify/archive) | `implemented`, `delivered`, `shipped` | `implemented` |
| 已评审 | `reviewed` | `reviewed` |
| 活跃 | `active` | `active` |
| 就绪 | `ready` | `ready` |
| 完成 (fallback) | `done`, `complete`, `completed` | `done` |

## 推荐 Status 行格式

✅ **单 token** — 最安全:
```markdown
> **Status**: Approved
> **Status**: Implemented
> **Status**: Active
```

✅ **`<token> — <narrative>`** — em-dash 后任意内容, 只看首 token 决定语义:
```markdown
> **Status**: Approved (Rev2 CONVERGED) — Phase A done, ready for Phase B
> **Status**: Implemented (Phase B PR-A merged) — post-deploy 验证后归档
```

> **lifecycle-head 截断 (aria-plugin #50, 2026-05-21)**: `_normalize_status` 只读 Status 的**首段** (第一个分隔符前的内容) 决定 lifecycle。分隔符 = em-dash `—` / en-dash `–` / 空格包围的 ASCII hyphen ` - ` / 半全角分号 `;` `；` / 全角句号 `。`。分隔符**后**的 narrative **不参与** lifecycle 归类 —— 因此 lifecycle keyword 必须写在首段; 把它写在分隔符后属于 Status 写法违规。`raw_status` 字段仍保留**完整** Status 文本供人类展示, 不被截断 (`raw_status` full / `status` from-head 职责分离)。逗号 `,` 与 ASCII 句号 `.` **不是**分隔符 (保护 `Approved, revised` / `v2.0` 版本串)。首段超 200 字符且无分隔符 → collector 发 `status_field_truncated` soft_error。

## Anti-pattern: substring shadows

Word-boundary regex 匹配 (`\b<token>\b`) 已根治大部分 substring shadow 风险 (修复见 Forgejo Aria #101), 但部分 narrative 仍要小心:

❌ **避免** narrative 含 token 字面 (无 word boundary 风险时不会触发, 但容易让人误读):
```markdown
> **Status**: WIP - 已完成 mock 测试   ← "done" 不会被错误命中, 但语义模糊
```

❌ **历史陷阱** (已修复, 不再触发 — 仅作教育示例):
```markdown
"Approved Phase A done"  ← 历史会误归 done, 现在 word boundary 正确归 approved
"Implemented stubs"      ← 历史会误归 unknown, 现在 implemented
"Inactive — deprecated"  ← 历史会误归 active, 现在 deprecated 优先级更高
```

## Implementation note

实现细节见 `scripts/collectors/_status.py` — `_normalize_status` (归一化) + `_has_token` (word-boundary) + `_status_lifecycle_head` (首段截断, #50) + `_status_field_overlong` (超长谓词, collector 发 soft_error 用)。归一化逻辑 backed by regression test (`tests/test_openspec.py`): `TestStatusNormalizationIssue101Fix` (13, #101 substring shadow) + `TestStatusNormalizationIssue73Fix` (8, #73 transitional) + `TestStatusExtractionRangeIssue50Fix` (20, #50 首段截断 + delivered/shipped + 边界); soft_error e2e 见 `TestOpenspecCollector` + `test_requirements.py::TestPrdScanning`。
