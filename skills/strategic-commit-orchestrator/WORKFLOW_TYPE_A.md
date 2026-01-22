# 工作流程 - 类型A: 子模块功能变更

> **版本**: 2.1.0
> **适用**: mobile/**, backend/**, frontend/**, shared/** 路径下的变更

本文档包含类型A（子模块功能变更）特定的工作流程步骤。

**📚 文档导航**:
- **入口文档** → [SKILL.md](./SKILL.md)
- **变更类型识别** → [CHANGE_TYPES.md](./CHANGE_TYPES.md)
- **通用流程** → [WORKFLOW_CORE.md](./WORKFLOW_CORE.md)
- **类型A流程（本文档）** → 您正在阅读

---

## 类型A特征

```yaml
文件路径模式:
  - mobile/**/*
  - backend/**/*
  - frontend/**/*
  - shared/**/*

UPM处理: 读取子模块UPM
Phase/Cycle来源: 子模块实际进度
```

---

## Phase 1: 项目状态感知 (类型A专用)

### 步骤1.0: 动态UPM路径解析

**目标**: 根据子模块名动态确定正确的UPM文档路径

```python
def get_upm_path(module: str) -> str:
    """
    动态获取子模块的UPM文档路径

    Args:
        module: 子模块名（mobile, backend, frontend, shared）

    Returns:
        完整的UPM文档路径
    """
    # 标准路径尝试顺序
    candidates = [
        f"{module}/project-planning/unified-progress-management.md",
        f"{module}/docs/project-planning/unified-progress-management.md"
    ]

    for candidate in candidates:
        if file_exists(candidate):
            return candidate

    return ""  # 未找到UPM文档
```

**路径示例**:
```yaml
mobile:   mobile/docs/project-planning/unified-progress-management.md
backend:  backend/project-planning/unified-progress-management.md
frontend: frontend/project-planning/unified-progress-management.md
shared:   shared/project-planning/unified-progress-management.md
```

### 步骤1.1: 读取子模块UPM

```bash
# 读取子模块UPM获取当前状态
# 以mobile为例
grep -A 20 "^# UPMv2-STATE" mobile/docs/project-planning/unified-progress-management.md

# 或使用 Read 工具读取完整文档
```

**提取信息**:
```yaml
UPMv2-STATE:
  module: "mobile"
  stage: "Phase 4 - Feature Development"
  cycleNumber: 9
  lastUpdateAt: "2025-12-15T..."
```

### 步骤1.2: 识别当前里程碑和目标

```yaml
里程碑信息提取:
  主要目标: nextCycle.intent 字段
  候选任务: nextCycle.candidates 列表
  约束条件: nextCycle.constraints 列表
```

---

## Phase 6.3: 项目进度关联 (类型A专用)

### Context来源

```yaml
类型A Context策略:
  来源: 子模块UPM的 UPMv2-STATE
  读取字段:
    - stage → 提取Phase编号
    - cycleNumber → Cycle编号

  格式: Phase{N}-Cycle{M}
  示例: Phase4-Cycle9
```

### 完整提交消息示例

```
feat(mobile): 实现任务分析图表页面 / Implement task analytics chart page

添加数据可视化组件展示任务统计信息。

- 使用 fl_chart 绘制完成率趋势图
- 实现任务分类饼图
- 添加时间范围筛选器

🤖 Executed-By: mobile-developer subagent
📋 Context: Phase4-Cycle9 mobile-feature-development  # ← 从mobile UPM读取
🔗 Module: mobile
🔗 Related: #B6-2#task-analytics-chart

Refs: unified-progress-management.md#P2-remaining-pages
```

---

## 快速检查清单

### Phase 1 检查
- [ ] 识别变更文件所属子模块
- [ ] 使用 get_upm_path() 获取UPM路径
- [ ] 读取子模块UPM文档
- [ ] 提取 Phase/Cycle 信息

### Phase 6.3 检查
- [ ] Context使用子模块实际Phase/Cycle
- [ ] Module标记为子模块名
- [ ] 关联任务ID（如有）

---

## 下一步

完成Phase 1后，继续执行 [WORKFLOW_CORE.md](./WORKFLOW_CORE.md) 中的Phase 2-7通用流程。

---

*本文档是 strategic-commit-orchestrator v2.1.0 的类型A工作流程指南。*
