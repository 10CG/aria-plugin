# GREEN 阶段检查说明

> **TDD Enforcer** - Superpowers 模式 GREEN 阶段验证
> **版本**: 2.0.0
> **更新**: 2026-02-06

---

## 概述

GREEN 阶段检查是 Superpowers 模式的独有功能，确保在测试通过后只编写最小实现，防止过度设计。

---

## 为什么需要 GREEN 阶段检查？

### TDD 的最小实现原则

```
传统开发:
  1. 思考所有可能的需求
  2. 一次性实现所有功能
  3. 编写测试
  → 问题: 过度设计，开发时间长

TDD 最小实现:
  1. 编写一个失败测试
  2. 编写刚好能通过的代码
  3. 重构优化
  → 优势: 小步快跑，避免过度设计
```

### 过度设计的风险

| 风险 | 说明 |
|------|------|
| **浪费开发时间** | 提前实现不需要的功能 |
| **增加维护负担** | 更多代码 = 更多维护 |
| **延迟反馈** | 长时间才能看到可运行的功能 |
| **复杂度累积** | 过早优化导致代码复杂 |

---

## 检查项目

### 1. 代码增量行数

```yaml
检测: 测试从失败变为通过后，新增的代码行数
限制: 默认 50 行 (可配置)
违规: 超过限制时警告或拦截

计算方式:
  - 记录测试通过时的文件快照
  - 每次编辑后对比当前文件
  - 计算新增行数 (新增 - 删除)
```

### 2. 新增函数数量

```yaml
检测: 测试通过后新增的函数/方法数量
限制: 默认 3 个 (可配置)
违规: 超过限制时警告或拦截

识别方式:
  Python: def function_name(
  JavaScript: function functionName(
  Dart:  returnType functionName(
```

### 3. 代码复杂度

```yaml
检测: 新增代码的循环复杂度
限制: 默认 5 (可配置)
违规: 超过限制时警告

计算方式:
  - 统计 if/for/while/switch 分支
  - 复杂度 = 分支数 + 1
```

---

## 配置

```json
{
  "green_phase_limits": {
    "enabled": true,
    "max_lines_after_pass": 50,
    "max_new_functions": 3,
    "max_complexity": 5,
    "warn_on_exceed": true
  }
}
```

### 配置说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | boolean | false | 是否启用 GREEN 阶段检查 |
| `max_lines_after_pass` | int | 50 | 最大新增代码行数 |
| `max_new_functions` | int | 3 | 最大新增函数数量 |
| `max_complexity` | int | 5 | 最大循环复杂度 |
| `warn_on_exceed` | boolean | true | 超限时警告而非拦截 |

---

## 违规处理

### 警告模式 (warn_on_exceed: true)

```
⚠️ GREEN 阶段代码增量警告

统计:
  - 新增代码: 65 行 (限制: 50)
  - 新增函数: 5 个 (限制: 3)

建议:
  GREEN 阶段应编写最小实现。
  如需添加更多功能，请先编写新的失败测试。

[继续] [添加测试]
```

### 拦截模式 (warn_on_exceed: false)

```
🚫 GREEN 阶段代码增量超限

统计:
  - 新增代码: 65 行 (限制: 50)
  - 新增函数: 5 个 (限制: 3)

要求:
  1. 添加新功能的测试用例
  2. 确认测试失败
  3. 继续实现

[添加测试] [回滚代码] [取消]
```

---

## 检测时机

```yaml
触发条件:
  1. 测试状态从失败变为通过
  2. 用户继续编辑源代码文件

检测流程:
  1. 记录测试通过时的文件快照
  2. 监控后续的文件修改
  3. 每次编辑后计算增量
  4. 超过限制时触发警告/拦截
```

---

## 实现细节

### 快照记录

```python
def record_green_snapshot(file_path):
    """记录测试通过时的文件快照"""
    return {
        "file_path": file_path,
        "timestamp": time.time(),
        "line_count": count_lines(file_path),
        "functions": extract_functions(file_path),
        "hash": file_hash(file_path)
    }
```

### 增量计算

```python
def calculate_increment(current_file, snapshot):
    """计算相对于快照的增量"""
    return {
        "lines": current_file["line_count"] - snapshot["line_count"],
        "functions": len(current_file["functions"]) - len(snapshot["functions"]),
        "complexity": calculate_complexity(current_file)
    }
```

---

## 最佳实践

### 编写最小实现

```python
# ❌ 过度实现
def add(a, b):
    """加法函数 - 过度实现"""
    # 不必要的错误处理
    if not isinstance(a, (int, float)):
        raise TypeError("a must be a number")
    if not isinstance(b, (int, float)):
        raise TypeError("b must be a number")
    if a < 0 or b < 0:
        raise ValueError("negative numbers not supported")
    # 不必要的日志
    logger.info(f"Adding {a} and {b}")
    return a + b

# ✅ 最小实现
def add(a, b):
    """加法函数 - 最小实现"""
    return a + b
```

### 何时添加额外功能

```yaml
场景: 需要添加边界检查

正确做法:
  1. 添加边界检查的失败测试
  2. 确认测试失败 (RED)
  3. 实现边界检查 (GREEN)
  4. 重构优化 (REFACTOR)

错误做法:
  1. 测试通过后直接添加边界检查
  2. 违反最小实现原则
```

---

## 常见问题

### Q: 如果需要一次性写很多代码怎么办？

**A**: 拆分成多个小的 TDD 循环：
1. 先实现核心功能（最小实现）
2. 添加更多测试用例
3. 逐个实现额外功能

### Q: 重构时增加复杂度怎么办？

**A**: REFACTOR 阶段不受 GREEN 限制约束，但应该：
1. 保持测试通过
2. 避免增加新功能
3. 专注于代码质量提升

### Q: 如何禁用 GREEN 阶段检查？

**A**: 设置 `green_phase_limits.enabled = false`

---

**最后更新**: 2026-02-06
