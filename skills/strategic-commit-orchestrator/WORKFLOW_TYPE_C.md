# 工作流程 - 类型C: 跨项目共享基础设施

> **版本**: 2.1.0
> **适用**: standards/**, .claude/agents/** 路径下的变更

本文档包含类型C（跨项目共享基础设施）特定的工作流程步骤。

**📚 文档导航**:
- **入口文档** → [SKILL.md](./SKILL.md)
- **变更类型识别** → [CHANGE_TYPES.md](./CHANGE_TYPES.md)
- **通用流程** → [WORKFLOW_CORE.md](./WORKFLOW_CORE.md)
- **类型C流程（本文档）** → 您正在阅读

---

## 类型C特征

```yaml
文件路径模式:
  - standards/**/*              # AI-DDD方法论规范
  - .claude/agents/**/*         # AI代理配置系统

特殊性:
  - 跨项目共享，不绑定特定项目进度
  - 无UPM文档
  - 使用逻辑Phase/Cycle

UPM处理: 跳过（无UPM）
Phase/Cycle来源: 逻辑阶段描述
```

---

## Phase 1: 项目状态感知 (类型C专用)

### 步骤1.0: 跳过UPM读取

⚠️ **类型C不需要读取UPM文档**

```yaml
原因:
  - standards/ 是AI-DDD方法论SSOT，跨多个项目复用
  - .claude/agents/ 是AI代理配置系统，跨项目复用
  - 这些模块不跟踪具体项目进度
```

### 步骤1.1: 确定逻辑Phase/Cycle

**逻辑阶段命名规则**:

```yaml
逻辑Phase/Cycle描述工作阶段:

  Phase1-Cycle1: 初始化/基础设施建设
    示例: 首次创建standards规范

  Phase1-Cycle2: 二次优化/升级
    示例: 规范修订和完善

  Phase{N}-Cycle{M}: 对应具体工作迭代
    示例: 第N轮重大更新的第M次迭代
```

**常用逻辑Context**:
```yaml
standards模块:
  - Phase1-Cycle1 standards-initialization
  - Phase1-Cycle2 standards-refinement
  - Phase2-Cycle1 methodology-upgrade

agents模块:
  - Phase1-Cycle1 agents-setup
  - Phase1-Cycle2 agents-enhancement
```

---

## Phase 6.3: 项目进度关联 (类型C专用)

### Context来源

```yaml
类型C Context策略:
  来源: 自定义逻辑描述（非UPM读取）

  格式: Phase{N}-Cycle{M} {work-description}

  命名原则:
    - N: 表示第N轮主要工作迭代
    - M: 表示该轮工作的第M次修订
    - work-description: 简短描述工作内容
```

### 完整提交消息示例

```
fix(standards/upm): 修复UPM路径规范不一致问题 / Fix UPM path specification inconsistency

修复unified-progress-management-spec.md和strategic-commit-orchestrator.md中
UPM路径定义不一致问题。

- 统一路径模板格式
- 添加动态解析逻辑
- 更新文档说明

🤖 Executed-By: knowledge-manager subagent
📋 Context: Phase1-Cycle1 standards-unification  # ← 逻辑Phase，非UPM读取
🔗 Module: standards
```

```
docs(agents): 升级AI代理配置系统 / Upgrade AI agent configuration system

重构代理配置结构，支持多项目复用。

🤖 Executed-By: tech-lead subagent
📋 Context: Phase1-Cycle2 agents-v2-upgrade  # ← 逻辑Phase
🔗 Module: agents
```

---

## 快速检查清单

### Phase 1 检查
- [ ] 确认变更属于跨项目共享模块 (standards/ 或 .claude/agents/)
- [ ] ⚠️ **跳过UPM读取**
- [ ] 确定逻辑Phase/Cycle描述

### Phase 6.3 检查
- [ ] Context使用逻辑Phase/Cycle（如 Phase1-Cycle1）
- [ ] 包含工作描述（如 standards-unification）
- [ ] Module标记为共享模块名（standards 或 agents）

---

## 下一步

完成Phase 1后，继续执行 [WORKFLOW_CORE.md](./WORKFLOW_CORE.md) 中的Phase 2-7通用流程。

---

*本文档是 strategic-commit-orchestrator v2.1.0 的类型C工作流程指南。*
