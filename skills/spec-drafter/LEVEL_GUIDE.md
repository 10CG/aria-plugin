# Spec Level 决策指南

> **版本**: 1.0.0
> **最后更新**: 2025-12-23
> **相关 Skill**: spec-drafter

---

## 概述

本文档定义 OpenSpec 三级 Spec 策略的详细判断规则，包括关键词匹配、文件影响分析、综合评分和上下文增强机制。

---

## 三级 Spec 策略

### 决策流程图

```
┌─────────────────────────────────────────────────────────────────────┐
│                      SPEC LEVEL DECISION                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Q1: 是否简单修复/配置/文档格式?                                      │
│      │                                                              │
│      ├─ YES ──────────────────────────────────▶ LEVEL 1 (Skip)     │
│      │                                          直接开发，跳过Spec   │
│      │                                                              │
│      └─ NO ──▶ Q2: 是否架构变更/跨模块/Breaking?                     │
│                    │                                                │
│                    ├─ YES ────────────────────▶ LEVEL 3 (Full)     │
│                    │                            proposal.md         │
│                    │                            + tasks.md          │
│                    │                                                │
│                    └─ NO ─────────────────────▶ LEVEL 2 (Minimal)  │
│                                                 proposal.md only    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Level 定义对照表

| Level | 名称 | 触发条件 | 产出物 | 典型场景 |
|-------|------|---------|--------|---------|
| **1** | Skip | 简单修复、配置、格式 | 无 Spec | Typo 修复、README 更新 |
| **2** | Minimal | 中等功能 (1-3 天) | proposal.md | 新 Skill、新功能 |
| **3** | Full | 架构变更、跨模块 | proposal.md + tasks.md | 重构、Breaking change |

---

## 关键词匹配规则

### Level 1 触发词 (简单修复)

```yaml
高置信度触发词:
  - typo, fix typo
  - format, formatting
  - readme, doc-only
  - config (单独出现)
  - comment (注释相关)
  - minor fix

上下文限定词:
  - "simple", "small", "tiny", "quick"
  - "just", "only"

示例:
  ✅ "Fix typo in README" → Level 1
  ✅ "Update doc formatting" → Level 1
  ✅ "Just a small config change" → Level 1
```

### Level 2 触发词 (中等功能)

```yaml
功能开发词:
  - feature, 功能
  - add, implement, 添加, 实现
  - new, 新建, 创建
  - Skill (新 Skill)
  - component, 组件

增强改进词:
  - improve, 改进
  - update (功能性)
  - extend, 扩展
  - optimize (单模块)

示例:
  ✅ "创建测试报告生成 Skill" → Level 2
  ✅ "Add user authentication feature" → Level 2
  ✅ "Implement offline cache" → Level 2
```

### Level 3 触发词 (架构变更)

```yaml
架构级词汇:
  - architecture, 架构
  - refactor, 重构
  - redesign, 重新设计
  - breaking, breaking change
  - migration, 迁移

跨域词汇:
  - cross-module, 跨模块
  - multi-module
  - integration, 集成 (跨系统)
  - sync (跨模块状态)

影响范围词汇:
  - system-wide
  - global
  - core (核心系统)

示例:
  ✅ "重构进度管理系统" → Level 3
  ✅ "Cross-module state synchronization" → Level 3
  ✅ "Architecture redesign for authentication" → Level 3
```

---

## 文件影响分析

### 模块检测

```yaml
检测方法:
  1. 从需求描述提取模块关键词
  2. 分析涉及的文件路径前缀
  3. 检查是否跨模块

模块映射:
  mobile:
    关键词: Flutter, Dart, UI, Widget, 移动端, iOS, Android
    路径: mobile/**

  backend:
    关键词: Python, FastAPI, API, 数据库, 后端, PostgreSQL
    路径: backend/**

  shared:
    关键词: 契约, Schema, OpenAPI, 共享, types
    路径: shared/**

  standards:
    关键词: 规范, Skill, OpenSpec, 标准, 文档
    路径: standards/**, .claude/**
```

### 跨模块判断

```yaml
跨模块条件 (满足任一):
  - 涉及 2 个及以上模块
  - 修改 shared/ 目录
  - 需要 API 契约变更
  - 影响多个子模块

跨模块 → 自动提升为 Level 3
```

---

## 综合评分机制

### 评分因素

```yaml
因素权重:
  关键词匹配: 40%
  文件影响范围: 30%
  变更类型识别: 20%
  历史模式: 10%

评分计算:
  score = (keyword_score * 0.4) +
          (scope_score * 0.3) +
          (change_type_score * 0.2) +
          (history_score * 0.1)

阈值:
  score < 3  → Level 1
  3 <= score < 7 → Level 2
  score >= 7 → Level 3
```

### 手动覆盖

```yaml
覆盖场景:
  - 自动判断与实际不符
  - 特殊情况需要强制指定

覆盖方式:
  - 参数: level_override=1|2|3
  - 交互确认时选择覆盖
```

---

## 上下文增强机制

### 集成 state-scanner

当 `module` 参数指定或检测到具体模块时，自动获取上下文：

```yaml
获取信息:
  - 当前 Phase/Cycle (如 "Phase 3 - Cycle 5")
  - 活跃风险列表 (用于 Impact.Risk 分析)
  - nextCycle.intent (用于任务关联)
  - KPI 快照 (如覆盖率要求)

填充到 Spec:
  - Context 标记: "Phase3-Cycle5 backend-api"
  - Impact.Risk: 关联现有风险
  - Success Criteria: 参考 KPI 目标
```

### 上下文增强示例

```yaml
原始需求: "为 mobile 模块添加离线缓存功能"

上下文获取:
  module: mobile
  phase: "Phase 4 - Sprint Development"
  cycle: 9
  risks:
    - MOBILE_MEMORY_P0: 内存问题
  kpi:
    coverage: ">= 87.2%"

生成的 Impact:
  | Type | Description |
  |------|-------------|
  | **Positive** | 提升离线体验，减少网络依赖 |
  | **Risk** | 可能增加内存使用，需注意 MOBILE_MEMORY_P0 风险 |

生成的 Success Criteria:
  - [ ] 离线缓存功能正常工作
  - [ ] 测试覆盖率 >= 87.2% (与当前 KPI 一致)
  - [ ] 内存增量 <= 20MB
```

---

## 使用示例

### 示例 1: 简单功能 (Level 2)

```yaml
用户请求: "创建一个新的 Skill 用于生成测试报告"

执行:
  输入:
    requirement: "创建测试报告生成 Skill"
    module: (自动检测: standards)

  Level 判断:
    关键词: "Skill" → 中等功能
    影响范围: 单模块 (.claude/skills/)
    结果: Level 2 (Minimal)

  输出:
    path: standards/openspec/changes/test-report-skill/proposal.md
    模板: proposal-minimal.md 格式
```

### 示例 2: 架构变更 (Level 3)

```yaml
用户请求: "重构进度管理系统，支持跨模块状态同步"

执行:
  输入:
    requirement: "重构进度管理系统，跨模块状态同步"
    module: (自动检测: cross)

  Level 判断:
    关键词: "重构", "跨模块" → 架构级变更
    影响范围: standards + mobile + backend
    结果: Level 3 (Full)

  输出:
    files:
      - standards/openspec/changes/progress-refactor/proposal.md
      - standards/openspec/changes/progress-refactor/tasks.md
```

### 示例 3: 简单修复 (Level 1)

```yaml
用户请求: "Fix typo in README"

执行:
  Level 判断:
    关键词: "fix typo", "README" → 简单修复
    结果: Level 1 (Skip)

  输出:
    建议直接跳过 A.1，进入 B.1 开始开发
```

---

## 边界情况处理

### 不确定情况

```yaml
策略:
  - Level 判断不确定: 默认 Level 2，显示判断理由供用户覆盖
  - 模块检测失败: 提示用户手动指定
  - 关键词冲突: 优先级 Level 3 > Level 2 > Level 1

示例:
  "Add simple authentication feature"
  → "simple" 暗示 Level 1
  → "authentication feature" 暗示 Level 2
  → 冲突解决: 选择更高 Level (Level 2)
```

### 特殊场景

```yaml
场景 1: 新项目初始化
  触发: 涉及多个核心模块
  默认: Level 3

场景 2: 依赖升级
  触发: 仅 package 文件变更
  默认: Level 1 (除非有 breaking change)

场景 3: CI/CD 配置
  触发: .github/ 或 CI 相关
  默认: Level 1-2 (取决于影响范围)
```

---

## 相关文档

- [spec-drafter SKILL.md](./SKILL.md)
- [OpenSpec 项目定义](../../../standards/openspec/project.md)
- [Phase A: 规范与规划](../../../standards/core/ten-step-cycle/phase-a-spec-planning.md)
- [proposal-minimal 模板](../../../standards/openspec/templates/proposal-minimal.md)

