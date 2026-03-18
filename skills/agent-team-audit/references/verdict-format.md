# Verdict 格式规范 (Verdict Format)

## 判定规则

```
verdict = PASS               如果: 0 Critical + 0 Major
verdict = PASS_WITH_WARNINGS  如果: 0 Critical + >=1 Major
verdict = FAIL               如果: >=1 Critical (任一 Agent)
```

## 阻塞行为

| 触发点 | PASS | PASS_WITH_WARNINGS | FAIL |
|--------|------|--------------------|------|
| pre_merge | 继续合并 | 继续合并 (附警告) | **阻塞合并** |
| post_implementation | 继续到 Phase C | 继续到 Phase C (附警告) | **阻塞进入 Phase C** |
| post_spec | 继续 | 继续 | 继续 (仅记录) |

## 报告结构

```yaml
audit_report:
  trigger_point: string        # pre_merge | post_implementation | post_spec
  verdict: string              # PASS | PASS_WITH_WARNINGS | FAIL
  blocking: boolean            # 是否阻塞后续流程

  agents:
    total: integer             # 参与 Agent 数
    completed: integer         # 完成审查的 Agent 数
    skipped: integer           # 超时跳过的 Agent 数
    details:
      - name: string
        status: string         # completed | skipped | error
        issues_found: integer
        duration_ms: integer

  issues:
    total_raw: integer         # 去重前总数
    total_deduped: integer     # 去重后总数
    critical: integer
    major: integer
    minor: integer
    items:
      - severity: string       # Critical | Major | Minor
        category: string       # 问题分类
        affected_file: string  # 影响的文件
        description: string    # 问题描述
        found_by: list         # 发现此问题的 Agent 列表

  timing:
    total_ms: integer          # 总耗时
    per_agent:
      - name: string
        duration_ms: integer
```

## 去重规则

两个 issue 被视为相同当且仅当:
1. `category` 相同
2. `affected_file` 相同

去重后保留:
- 最高 severity
- 所有发现者 (found_by 合并)
- 最详细的 description

---

**最后更新**: 2026-03-18
