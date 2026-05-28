# Phase D Usage Examples

> 3 个典型场景示例: 完整收尾 / 仅更新进度 / 全部跳过. 从 SKILL.md §使用示例 提取 (iter-3, 2026-05-28)。

## 示例 1: 完整收尾

```yaml
输入:
  context:
    module: "mobile"
    spec_id: "add-auth-feature"

执行:
  D.1: 更新 UPM → Cycle 10
  D.2: 归档 Spec → archive/

输出:
  upm_updated: true
  spec_archived: true
```

## 示例 2: 仅更新进度

```yaml
输入:
  context:
    spec_id: null  # 无关联 Spec

执行:
  D.1: 更新 UPM
  D.2: 跳过 (无 Spec)

输出:
  steps_skipped: [D.2]
  upm_updated: true
```

## 示例 3: 全部跳过

```yaml
输入:
  context:
    module: "shared"  # 无 UPM
    spec_id: null     # 无 Spec

执行:
  D.1: 跳过 (无 UPM)
  D.2: 跳过 (无 Spec)

输出:
  steps_skipped: [D.1, D.2]
  reason: "收尾阶段无需执行"
```
