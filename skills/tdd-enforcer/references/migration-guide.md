# 迁移指南 (v1.x → v2.0)

> **TDD Enforcer** - 从代码驱动到文档驱动的架构升级
> **版本**: 2.0.0
> **更新**: 2026-02-06

---

## 概述

v2.0 是 TDD Enforcer 的重大架构升级，从**代码驱动**重构为**文档驱动**设计，参考 Superpowers 的实现方式。

### 核心变化

| 项目 | v1.x (旧版) | v2.0 (新版) |
|------|------------|-------------|
| 实现方式 | Python 代码模块 | 文档描述 (SKILL.md) |
| 执行方式 | Hook 调用 Python | AI 读取文档理解 |
| 文件数量 | 17+ Python 文件 | 1 SKILL.md + references/ |
| Token 效率 | 中等 | 高 |
| 修改难度 | 需要编程 | 更新文档 |

---

## 为什么重构？

### v1.x 的问题

```
┌─────────────────────────────────────────────────────────────────┐
│  问题: 把 Skill 当作 Python 包来开发                            │
├─────────────────────────────────────────────────────────────────┤
│  ❌ 创建大量 Python 模块                                       │
│  ❌ 实现复杂的类继承结构                                       │
│  ❌ 编写单元测试                                               │
│                                                                 │
│  根本问题: Claude Code 不会导入执行这些 Python 代码              │
│           Skill 系统读取的是 SKILL.md 文档                        │
└─────────────────────────────────────────────────────────────────┘
```

### v2.0 的解决方案

```
┌─────────────────────────────────────────────────────────────────┐
│  方案: 参考 Superpowers，文档驱动设计                             │
├─────────────────────────────────────────────────────────────────┤
│  ✅ SKILL.md 描述工作流                                         │
│  ✅ AI 读取并理解流程                                           │
│  ✅ AI 按流程执行检查                                           │
│                                                                 │
│  优势: 符合 Agent Skills 设计原则                                 │
│        Token 效率更高                                             │
│        易于维护和扩展                                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 配置变更

### v1.x 配置

```json
{
  "enabled": true,
  "strict_mode": false,
  "skip_patterns": ["**/*.md"]
}
```

### v2.0 配置

```json
{
  "enabled": true,
  "strictness": "advisory",
  "skip_patterns": ["**/*.md"]
}
```

### 字段变更映射

| v1.x 字段 | v2.0 字段 | 说明 |
|----------|----------|------|
| `strict_mode` | `strictness` | 布尔 → 三级枚举 |
| - | `green_phase_limits` | 新增：GREEN 阶段限制 |
| - | `golden_testing_detection` | 新增：金装甲测试检测 |
| - | `state_persistence` | 新增：状态持久化 |

---

## 严格度级别映射

```yaml
v1.x:
  strict_mode: false  → Advisory 级别
  strict_mode: true   → Strict 级别

v2.0:
  strictness: "advisory"     → Advisory 级别
  strictness: "strict"       → Strict 级别
  strictness: "superpowers"  → 新增：完整级别
```

---

## 文件结构变更

### v1.x 目录结构

```
tdd-enforcer/
├── SKILL.md
├── cache.py
├── config.py
├── diff_analyzer.py
├── state_persistence.py
├── state_tracker.py
├── test_runners/
│   ├── base.py
│   ├── python_runner.py
│   ├── js_runner.py
│   └── dart_runner.py
├── validators/
│   ├── green_validator.py
│   └── golden_test_detector.py
├── hooks/
│   └── pre_tool_use_hook.py
└── tests/
    └── ...
```

### v2.0 目录结构

```
tdd-enforcer/
├── SKILL.md                    # 主文档 (<500 行)
├── EXAMPLES.md                 # 使用示例
└── references/                 # 详细参考文档
    ├── strictness-levels.md
    ├── red-state-detection.md
    ├── green-phase-check.md
    └── migration-guide.md      # 本文档
```

---

## 行为变更

### RED 状态检测

| 项目 | v1.x | v2.0 |
|------|------|------|
| 检测方式 | Python 代码运行 | AI 理解文档执行 |
| 状态缓存 | Python TTL 缓存 | AI 会话内缓存 |
| 跨语言 | Python 模块 | 文档描述命令 |

### 金装甲测试检测

| 项目 | v1.x | v2.0 |
|------|------|------|
| 检测方式 | Python 正则匹配 | AI 理解模式 |
| 扩展性 | 需要修改代码 | 更新配置 |

---

## 升级步骤

### 1. 备份现有配置

```bash
# 备份配置文件
cp .claude/tdd-config.json .claude/tdd-config.json.bak
```

### 2. 更新配置文件

```json
{
  "$schema": "tdd-config-schema.json",
  "enabled": true,
  "strictness": "strict",
  "skip_patterns": [
    "**/*.md",
    "**/*.json",
    "**/config/**"
  ],
  "test_patterns": {
    "python": ["test_*.py", "*_test.py"],
    "javascript": ["*.test.js", "*.spec.js"],
    "dart": ["*_test.dart"]
  }
}
```

### 3. 验证配置

```bash
# 检查配置是否有效
cat .claude/tdd-config.json | jq .
```

### 4. 删除旧文件 (可选)

```bash
# 如果不再需要 v1.x 的 Python 实现
rm -f cache.py config.py diff_analyzer.py
rm -f state_persistence.py state_tracker.py
rm -rf test_runners/ validators/ hooks/ tests/
```

---

## 功能对比

### 保持的功能

| 功能 | 状态 |
|------|------|
| 三级严格度 | ✅ 增强为三级 |
| 跨语言支持 | ✅ 保持 |
| RED 状态检测 | ✅ 保持 |
| 测试文件映射 | ✅ 保持 |
| 跳过模式 | ✅ 保持 |

### 新增的功能

| 功能 | 说明 |
|------|------|
| Superpowers 级别 | 完整 TDD 循环控制 |
| 金装甲测试检测 | 自动检测无意义测试 |
| GREEN 阶段限制 | 代码增量检查 |
| 状态持久化 | 跨会话状态恢复 |

### 移除的功能

| 功能 | 说明 |
|------|------|
| Python 单元测试 | 不再需要 |
| Hook 代码实现 | 改为文档描述 |

---

## 常见问题

### Q: v2.0 是否向后兼容？

**A**: 配置文件基本兼容，只需将 `strict_mode` 改为 `strictness`。

### Q: 我需要修改代码行为吗？

**A**: 不需要。v2.0 的变化是内部实现，外部行为保持一致。

### Q: 如何回滚到 v1.x？

**A**:
```bash
git checkout v1.x
# 或恢复备份配置
cp .claude/tdd-config.json.bak .claude/tdd-config.json
```

### Q: v2.0 更可靠吗？

**A**: 是的。v2.0 采用与 Superpowers 相同的文档驱动方式，已被验证更可靠。

---

## 总结

| 方面 | 改进 |
|------|------|
| **维护性** | 更新文档即可，无需编程 |
| **Token 效率** | 文档比代码更简洁 |
| **可扩展性** | 添加语言只需更新文档 |
| **可靠性** | 遵循已验证的设计模式 |

---

**最后更新**: 2026-02-06
