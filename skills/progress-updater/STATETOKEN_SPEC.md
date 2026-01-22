# stateToken 计算规范

> **版本**: 1.0.0
> **最后更新**: 2025-12-23
> **相关 Skill**: progress-updater

---

## 概述

stateToken 是 UPMv2-STATE 机读接口的核心组件，用于：
- 并发写入的乐观锁机制
- 状态变更检测
- 版本追踪和审计

---

## 计算算法

### 输入字段

```yaml
必需字段:
  - module: 模块标识符 (如 "mobile", "backend")
  - stage: 当前阶段 (如 "Phase 3 - Development")
  - cycleNumber: 循环编号 (正整数)
  - lastUpdateAt: ISO 8601 时间戳
  - kpiSnapshot: KPI 快照对象

拼接顺序:
  "{module}|{stage}|{cycleNumber}|{lastUpdateAt}|{kpiJson}"
```

### Python 实现

```python
import hashlib
import json
from datetime import datetime

def calculate_state_token(module, stage, cycle_number, last_update_at, kpi_snapshot):
    """
    计算 stateToken

    Args:
        module: 模块名称 (str)
        stage: 当前阶段 (str)
        cycle_number: 循环编号 (int)
        last_update_at: ISO 8601 时间戳 (str)
        kpi_snapshot: KPI 快照字典 (dict)

    Returns:
        stateToken 字符串，格式: "sha256:{12位哈希}"
    """
    # 1. 序列化 KPI (排序键确保一致性)
    kpi_json = json.dumps(kpi_snapshot, sort_keys=True, ensure_ascii=False)

    # 2. 拼接状态字符串
    state_str = f"{module}|{stage}|{cycle_number}|{last_update_at}|{kpi_json}"

    # 3. SHA256 哈希
    hash_obj = hashlib.sha256(state_str.encode('utf-8'))
    hash_hex = hash_obj.hexdigest()

    # 4. 取前 12 位 + 前缀
    return f"sha256:{hash_hex[:12]}"
```

### JavaScript 实现

```javascript
const crypto = require('crypto');

function calculateStateToken(module, stage, cycleNumber, lastUpdateAt, kpiSnapshot) {
    // 1. 序列化 KPI (排序键)
    const kpiJson = JSON.stringify(kpiSnapshot, Object.keys(kpiSnapshot).sort());

    // 2. 拼接状态字符串
    const stateStr = `${module}|${stage}|${cycleNumber}|${lastUpdateAt}|${kpiJson}`;

    // 3. SHA256 哈希
    const hash = crypto.createHash('sha256').update(stateStr, 'utf8').digest('hex');

    // 4. 取前 12 位 + 前缀
    return `sha256:${hash.substring(0, 12)}`;
}
```

### 计算示例

```yaml
输入:
  module: "mobile"
  stage: "Phase 4 - Sprint Development"
  cycleNumber: 9
  lastUpdateAt: "2025-12-16T15:30:00+08:00"
  kpiSnapshot:
    coverage: "89.5%"
    build: "green"
    lintErrors: 0

中间步骤:
  kpiJson: '{"build":"green","coverage":"89.5%","lintErrors":0}'
  stateStr: 'mobile|Phase 4 - Sprint Development|9|2025-12-16T15:30:00+08:00|{"build":"green","coverage":"89.5%","lintErrors":0}'

输出: "sha256:a1b2c3d4e5f6"
```

---

## 冲突检测机制

### 冲突场景

```yaml
典型并发冲突:
  1. AI-1 读取 UPM (记录 stateToken: abc123)
  2. AI-2 读取 UPM (记录 stateToken: abc123)
  3. AI-2 完成任务，更新 UPM (新 stateToken: def456)
  4. AI-1 尝试更新 (预期 token: abc123, 实际: def456)
  → 检测到冲突!

人机协作冲突:
  1. AI 读取 UPM (stateToken: abc123)
  2. Human 手动编辑 UPM (新 stateToken: xyz789)
  3. AI 尝试更新 (基于旧 token abc123)
  → 检测到冲突!
```

### 检测逻辑

```yaml
写入前检查:
  current_token = 读取文件中当前 stateToken
  expected_token = 操作开始时记录的 token

  IF current_token != expected_token THEN
    → 检测到冲突
    → 执行重试策略
  ELSE
    → 正常写入
  END IF
```

---

## 重试策略

### 策略 A: 重读-合并-重试 (推荐)

```yaml
步骤:
  1. 检测到冲突
  2. 重新读取最新 UPM 状态
  3. 合并 AI 的变更和最新状态:
     - 时间戳: 使用当前时间
     - KPI: 合并两方的更新
     - 任务状态: 取最新状态
  4. 重新计算 stateToken
  5. 再次尝试写入
  6. 最多重试 3 次

合并规则:
  kpiSnapshot:
    - 数值类型: 取最新值 (AI 更新优先)
    - 状态类型: 取更严重的状态 (red > yellow > green)

  risks:
    - 新增风险: 保留
    - 已解决风险: 标记为 resolved

  nextCycle.candidates:
    - 合并两个列表，去重
```

### 策略 B: 报告冲突

```yaml
触发条件: 重试 3 次仍失败

处理:
  1. 返回冲突详情
  2. 记录冲突上下文
  3. 请求人工干预

冲突报告格式:
  ═══════════════════════════════════════════════════════════════
    ⚠️ CONFLICT DETECTED
  ═══════════════════════════════════════════════════════════════

  Module: mobile
  Conflict Type: stateToken mismatch

  Expected: sha256:abc123
  Actual: sha256:xyz789

  Retry Attempts: 3/3
  Status: FAILED

  建议操作:
    1. 稍后重试
    2. 手动检查 UPM 文档
    3. 确认没有其他进程在更新

  ═══════════════════════════════════════════════════════════════
```

---

## 最佳实践

### DO

```yaml
✅ 每次更新 UPM 时都重新计算 stateToken
✅ 写入前校验 token 是否匹配
✅ 记录操作开始时的 token 用于冲突检测
✅ 使用 sort_keys=True 确保 KPI 序列化一致性
✅ 快速完成写入操作，减少冲突窗口
```

### DON'T

```yaml
❌ 不要手动编辑 stateToken
❌ 不要跳过冲突检测
❌ 不要使用不同的哈希长度
❌ 不要在多个进程中并发写入同一 UPM
```

---

## 错误处理

| 错误类型 | 原因 | 处理方式 |
|----------|------|----------|
| Token 不匹配 | 并发写入 | 执行重试策略 |
| 计算结果为空 | 输入字段缺失 | 检查必需字段 |
| 格式错误 | stateToken 格式损坏 | 重新计算覆盖 |

---

## 相关文档

- [progress-updater SKILL.md](./SKILL.md)
- [UPM 规范](../../../standards/core/upm/unified-progress-management-spec.md)
- [状态管理标准](../../../standards/core/state-management/ai-ddd-state-management.md)
