# 任务复杂度评估指南

> 此文件定义 task-planner Skill 使用的复杂度评估规则

---

## 复杂度等级定义

| 等级 | 代号 | 典型时长 | 说明 |
|------|------|----------|------|
| **Small** | S | 1-2h | 简单修改，单文件，无依赖 |
| **Medium** | M | 3-5h | 中等功能，多文件，单模块 |
| **Large** | L | 6-8h | 复杂功能，跨组件，可能有重构 |
| **X-Large** | XL | >8h | 超大功能，跨模块，需要拆分 |

---

## 评估维度

### 维度 1: 文件影响范围

| 等级 | 文件数 | 示例 |
|------|--------|------|
| S | 1-2 | 修改配置文件，修复 typo |
| M | 3-5 | 添加新功能模块 |
| L | 6-10 | 重构子系统 |
| XL | >10 | 跨模块架构变更 |

### 维度 2: 关键词触发

```yaml
S (Small):
  触发词:
    - config, configuration
    - typo, format, formatting
    - fix typo, update doc
    - readme, changelog
    - 配置, 格式化, 文档

M (Medium):
  触发词:
    - implement, add, create
    - update, feature, enhance
    - 实现, 添加, 创建
    - 更新, 功能, 增强

L (Large):
  触发词:
    - refactor, integrate, optimize
    - redesign, restructure
    - 重构, 集成, 优化
    - 重设计, 重组

XL (X-Large):
  触发词:
    - architecture, migration
    - breaking, cross-module
    - multi-module, system-wide
    - 架构, 迁移, 跨模块
```

### 维度 3: 依赖复杂度

| 等级 | 依赖数 | 说明 |
|------|--------|------|
| S | 0 | 无依赖，可独立执行 |
| M | 1-2 | 少量依赖，依赖链短 |
| L | 3-4 | 多依赖，需要协调 |
| XL | >4 或跨模块 | 复杂依赖网络 |

---

## 综合评估算法

```yaml
算法:
  1. 分别评估三个维度
  2. 取最高等级作为最终评估
  3. 如有不确定，倾向于高估 (保守策略)

示例:
  任务: "重构用户认证模块"

  文件影响: 8 文件 → L
  关键词: "重构" → L
  依赖: 2 依赖 → M

  最终: max(L, L, M) = L
```

---

## 任务类型特征

### S 级任务特征

```yaml
典型任务:
  - 修复文档 typo
  - 更新配置文件
  - 添加代码注释
  - 调整格式/风格

特征:
  - 单文件或极少文件
  - 无逻辑变更
  - 无需测试变更
  - 即时可验证

示例:
  "Fix typo in README.md"
  "Update .gitignore to exclude .env"
  "Add JSDoc comments to utils.js"
```

### M 级任务特征

```yaml
典型任务:
  - 实现新功能
  - 添加新 API 端点
  - 创建新组件
  - 编写测试用例

特征:
  - 3-5 文件修改
  - 包含逻辑实现
  - 需要对应测试
  - 单模块范围

示例:
  "Implement user login API"
  "Create TaskCard widget"
  "Add unit tests for AuthService"
```

### L 级任务特征

```yaml
典型任务:
  - 重构子系统
  - 集成第三方服务
  - 优化性能
  - 重设计数据模型

特征:
  - 6-10 文件修改
  - 可能影响多个组件
  - 需要回归测试
  - 可能有 breaking changes

示例:
  "Refactor state management to use Riverpod"
  "Integrate OAuth2 authentication"
  "Optimize database queries for performance"
```

### XL 级任务特征

```yaml
典型任务:
  - 架构级变更
  - 跨模块迁移
  - 技术栈升级
  - 大规模重构

特征:
  - >10 文件修改
  - 跨多个模块
  - 需要迁移策略
  - 高风险，需要详细规划

建议:
  → XL 任务应该拆分为多个 L/M 任务
  → 使用 spec-drafter Level 3 创建详细 tasks.md

示例:
  "Migrate from REST to GraphQL"
  "Upgrade Flutter 2.x to 3.x"
  "Restructure monolith to microservices"
```

---

## 边界情况处理

### 不确定时的决策

```yaml
规则:
  1. 倾向于高估一级
     - 不确定 S 还是 M → 选 M
     - 不确定 M 还是 L → 选 L

  2. 新技术/不熟悉领域 → 高估一级

  3. 有外部依赖 → 高估一级
     - 依赖第三方 API
     - 依赖其他团队
     - 依赖未完成的组件

原因:
  - 低估导致延期
  - 高估最多浪费缓冲时间
  - 保守策略更安全
```

### 特殊任务类型

```yaml
测试任务:
  - 单元测试: 通常 S-M
  - 集成测试: 通常 M-L
  - E2E 测试: 通常 L

文档任务:
  - 内联注释: S
  - API 文档: M
  - 架构文档: M-L

重构任务:
  - 小范围: M
  - 中范围: L
  - 大范围: XL (需拆分)
```

---

## 评估输出格式

```yaml
任务:
  id: TASK-001
  title: "实现用户登录 API"

  complexity:
    level: M
    reasoning:
      file_impact: M (预计修改 4 文件)
      keyword_match: M (关键词: 实现, API)
      dependencies: S (1 依赖: 用户模型)
    final: M (取最高)

  estimated_hours: 4

  confidence: high  # high / medium / low
```

---

## 常见误判及修正

| 误判场景 | 原因 | 修正 |
|----------|------|------|
| S 实际是 M | 隐藏复杂度 | 检查是否有副作用 |
| M 实际是 L | 依赖评估不足 | 考虑间接依赖 |
| L 实际是 XL | 范围蔓延 | 及时拆分 |
| XL 未拆分 | 急于开始 | 强制拆分为 L/M |

---

**最后更新**: 2025-12-17
