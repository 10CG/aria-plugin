---
name: tdd-enforcer
description: |
  强制执行测试驱动开发 (TDD) 工作流，使用 RED-GREEN-REFACTOR 循环确保测试先于代码编写。

  三级严格度：Advisory（警告）、Strict（强制）、Superpowers（完整循环）。

  使用场景：开发新功能时确保 TDD 最佳实践、代码质量审查。
disable-model-invocation: false
user-invocable: true
---

# TDD 强制执行器 (TDD Enforcer)

> **版本**: 2.0.0 | **设计**: 文档驱动 (Document-Driven)
> **更新**: 2026-02-06 - 重构为文档驱动设计
> **参考**: [Superpowers test-driven-development](https://github.com/obra/superpowers)

---

## 快速开始

### 我应该使用这个 skill 吗？

**使用场景**:
- ✅ 编写新功能代码时
- ✅ 需要确保测试覆盖率
- ✅ 代码质量检查前

**不使用场景**:
- ❌ 文档修改 → 无需 TDD
- ❌ 配置文件修改 → 一般跳过
- ❌ 重构已有测试 → 跳过 RED 阶段

---

## 配置 (config-loader)

执行前读取 `.aria/config.json`，缺失则使用默认值。参见 [config-loader](../config-loader/SKILL.md)。

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `tdd.strictness` | `"advisory"` | 严格度: `advisory` / `strict` / `superpowers` |

**优先级**: `.aria/config.json` > `.claude/tdd-config.json` > Skill 默认值。`.claude/tdd-config.json` 中的细粒度字段 (`skip_patterns`, `test_patterns`) 继续在原位生效。

---

## 核心工作流

```
┌─────────────────────────────────────────────────────────────────┐
│                    TDD 工作流 (RED-GREEN-REFACTOR)              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   RED (失败测试)        GREEN (最小实现)      REFACTOR (重构)    │
│   ──────────────        ────────────────      ─────────────────   │
│                                                                 │
│   1. 编写测试           1. 编写最小代码        1. 优化结构       │
│   2. 运行测试           2. 运行测试            2. 提取抽象       │
│   3. 确认失败           3. 确认通过            3. 运行测试       │
│   4. 停止编码           4. 停止扩展            4. 确认通过       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三级严格度

### Level 1: Advisory (建议模式)

```yaml
触发: 用户编辑源代码时

检查:
  - 测试文件是否存在

违规处理:
  - 显示警告
  - 允许继续操作

输出示例:
  ⚠️ 未找到测试文件
  建议先编写失败的测试 (RED 阶段)

  期望测试: tests/test_{name}.py
  当前文件: src/{name}.py
```

### Level 2: Strict (严格模式)

```yaml
触发: 用户编辑源代码时

检查:
  - 测试文件是否存在
  - 测试是否处于失败状态 (RED)

违规处理:
  - 阻止操作
  - 要求修正后继续

输出示例:
  🚫 TDD 严格模式拦截
  必须先创建测试文件

  当前操作: 编辑 src/auth.py
  要求: tests/test_auth.py 中必须有失败的测试

  [创建测试] [取消]
```

### Level 3: Superpowers (完全模式)

```yaml
触发: 用户编辑源代码时

检查:
  - 测试文件存在
  - 测试处于失败状态
  - 无金装甲测试 (assert True, 跳过测试)
  - GREEN 阶段代码增量限制

违规处理:
  - 不可绕过
  - 详细违规说明
  - 强制 TDD 完整循环

额外功能:
  - 状态持久化
  - 阶段转换验证
```

---

## 跨语言测试状态检测

### Python

```bash
# 检测框架
if [ -f pytest.ini ] || grep -q "pytest" pyproject.toml; then
    framework="pytest"
    command="pytest tests/ --collect-only --quiet"
else
    framework="unittest"
    command="python -m unittest discover -s tests"
fi

# 运行检测
result=$(eval $command)

# 判断 RED 状态
# pytest: exit_code != 0 表示有测试
# unittest: 输出包含 "FAILED" 或 "ERROR"
```

### JavaScript/TypeScript

```bash
# 检测框架
if [ -f jest.config.js ] || grep -q '"test": "jest"' package.json; then
    framework="jest"
    command="npx jest --passWithNoTests --verbose"
elif [ -f mocha.opts ]; then
    framework="mocha"
    command="npx mocha --require ./test/setup.js"
fi

# 运行检测
result=$(eval $command)

# 判断 RED 状态
# 输出包含 "failing" 或 "FAIL" 或 exit_code != 0
```

### Dart

```bash
# 检测框架
if grep -q "flutter:" pubspec.yaml; then
    framework="flutter"
    command="flutter test --dry-run"
else
    framework="dart"
    command="dart test --dry-run"
fi

# 运行检测
result=$(eval $command)

# 判断 RED 状态
# 输出包含 "FAIL" 或 exit_code != 0
```

---

## 配置文件

### 项目配置 (.claude/tdd-config.json)

```json
{
  "$schema": "tdd-config-schema.json",
  "enabled": true,
  "strictness": "advisory",
  "skip_patterns": [
    "**/*.md",
    "**/*.json",
    "**/config/**"
  ],
  "test_patterns": {
    "python": ["test_*.py", "*_test.py"],
    "javascript": ["*.test.js", "*.spec.js"],
    "dart": ["*_test.dart"]
  },
  "green_phase_limits": {
    "enabled": false,
    "max_lines_after_pass": 50,
    "max_new_functions": 3
  },
  "golden_testing_detection": {
    "enabled": false,
    "patterns": [
      {"pattern": "assert True", "severity": "error"},
      {"pattern": "@skip", "severity": "warning"}
    ]
  }
}
```

### 严格度级别选择

| 场景 | 推荐级别 | 理由 |
|------|---------|------|
| 新项目团队适应期 | Advisory | 学习 TDD 流程 |
| 生产环境项目 | Strict | 确保测试先于代码 |
| 高质量要求项目 | Superpowers | 完整质量控制 |

---

## 金装甲测试检测 (Superpowers)

### 反模式检测

| 模式 | 描述 | 严重程度 |
|------|------|---------|
| `assert True` | 永远通过的断言 | error |
| `assert False` | 永远通过的断言 | error |
| `@skip` | 跳过的测试 | warning |
| 空测试 | 没有断言的测试 | error |

### 多语言检测规则

```
Python:     assert\s+(True|False)\b
JavaScript: expect\((true|false)\)\.to[Bb]e\((true|false)\)
Dart:       expect\((true|false)\,\s*(true|false)\)
```

---

## 执行流程

### 当用户编辑源代码时:

```yaml
1. 检查文件类型
   └─ 跳过: *.md, *.json, 配置文件

2. 查找对应测试文件
   └─ 根据文件名映射规则

3. 应用严格度检查
   │
   ├─ Advisory: 测试不存在 → 警告
   ├─ Strict:   测试不存在或已通过 → 拦截
   └─ Superpowers: 完整检查 → 拦截

4. 返回结果
   └─ Allow / Warn / Block
```

---

## 输出格式

### 警告 (Advisory)

```yaml
status: warning
message: |
  ⚠️ TDD 规则警告

  当前文件: src/services/auth.js
  期望测试: tests/services/auth.test.js

  建议先编写失败测试 (RED 阶段)
```

### 拦截 (Strict/Superpowers)

```yaml
status: blocked
message: |
  🚫 TDD 严格模式拦截

  当前操作: 编辑 src/services/auth.js
  要求: 必须先存在失败测试

  [查看测试] [取消]
```

---

## Hook 集成

tdd-enforcer 通过 PreToolUse Hook 在 Write/Edit 操作前进行检查。

### Hook 配置

```json
{
  "name": "tdd-enforcer",
  "events": ["PreToolUse"],
  "handler": "tdd-enforcer"
}
```

### 执行时机

- 用户使用 Write 工具
- 用户使用 Edit 工具
- 检查目标文件是源代码

---

## 检查清单

### 使用前
- [ ] 确认项目需要 TDD 强制执行
- [ ] 配置 `tdd-config.json`
- [ ] 选择合适的严格度级别

### 使用后
- [ ] 测试先于代码编写
- [ ] RED-GREEN-REFACTOR 循环完整
- [ ] 无金装甲测试模式

---

## 相关文档

- [references/strictness-levels.md](references/strictness-levels.md) - 严格度级别详解
- [references/red-state-detection.md](references/red-state-detection.md) - RED 状态检测说明
- [references/green-phase-check.md](references/green-phase-check.md) - GREEN 阶段检查
- [references/migration-guide.md](references/migration-guide.md) - v1.x → v2.0 迁移
- [EXAMPLES.md](EXAMPLES.md) - 使用示例

---

**设计原则**: 文档驱动，AI 读取理解并执行检查规则。

**最后更新**: 2026-02-06
**Skill版本**: 2.0.0 (文档驱动重构)
