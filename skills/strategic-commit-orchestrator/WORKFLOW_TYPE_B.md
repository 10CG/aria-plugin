# 工作流程 - 类型B: 主项目变更

> **版本**: 2.1.0
> **适用**: docs/**, .claude/skills/**, scripts/**, 根目录配置文件等

本文档包含类型B（主项目变更）特定的工作流程步骤。

**📚 文档导航**:
- **入口文档** → [SKILL.md](./SKILL.md)
- **变更类型识别** → [CHANGE_TYPES.md](./CHANGE_TYPES.md)
- **通用流程** → [WORKFLOW_CORE.md](./WORKFLOW_CORE.md)
- **类型B流程（本文档）** → 您正在阅读

---

## 类型B特征

```yaml
文件路径模式:
  - docs/**/*                   # 主项目文档
  - .claude/skills/**/*         # AI Skills定义
  - .claude/docs/**/*           # 主项目级分析文档
  - .claude/commands/**/*       # 自定义命令
  - scripts/**/*                # 项目级脚本
  - *.md (根目录)               # 主项目README等
  - .cursor/rules/**/*          # Cursor规则
  - *.config.js, package.json   # 项目配置

UPM处理: 读取主模块UPM
Phase/Cycle来源: 主模块实际进度
```

---

## Phase 1: 项目状态感知 (类型B专用)

### 步骤1.0: 主模块UPM路径

**主模块UPM固定路径**:
```
docs/project-planning/unified-progress-management.md
```

### 步骤1.1: 读取主模块UPM

```bash
# 读取主模块UPM获取当前状态
grep -A 20 "^# UPMv2-STATE" docs/project-planning/unified-progress-management.md

# 或使用 Read 工具读取完整文档
```

**提取信息**:
```yaml
UPMv2-STATE:
  module: "main"
  stage: "Phase 2 - Infrastructure"
  cycleNumber: 3
  lastUpdateAt: "2025-12-20T..."
```

### 步骤1.2: 识别当前里程碑和目标

```yaml
里程碑信息提取:
  主要目标: nextCycle.intent 字段
  候选任务: nextCycle.candidates 列表
  约束条件: nextCycle.constraints 列表
```

---

## Phase 6.3: 项目进度关联 (类型B专用)

### Context来源

```yaml
类型B Context策略:
  来源: 主模块UPM的 UPMv2-STATE
  读取字段:
    - stage → 提取Phase编号
    - cycleNumber → Cycle编号

  格式: Phase{N}-Cycle{M}
  示例: Phase2-Cycle3
```

### 完整提交消息示例

```
docs(skills): Skills v2.0.0升级和组合设计 / Skills v2.0.0 upgrade and combination design

完成提交相关Skills的v2.0.0升级，支持AI-DDD v3.0.0多模块架构。

- 更新strategic-commit-orchestrator
- 优化commit-msg-generator
- 添加文档分层结构

🤖 Executed-By: tech-lead subagent
📋 Context: Phase2-Cycle3 skills-v2-universal-upgrade  # ← 从主模块UPM读取
🔗 Module: main
```

---

## 快速检查清单

### Phase 1 检查
- [ ] 确认变更属于主项目（非子模块）
- [ ] 读取主模块UPM: `docs/project-planning/unified-progress-management.md`
- [ ] 提取 Phase/Cycle 信息

### Phase 6.3 检查
- [ ] Context使用主模块实际Phase/Cycle
- [ ] Module标记为"main"或逻辑模块名
- [ ] 关联任务ID（如有）

---

## 下一步

完成Phase 1后，继续执行 [WORKFLOW_CORE.md](./WORKFLOW_CORE.md) 中的Phase 2-7通用流程。

---

*本文档是 strategic-commit-orchestrator v2.1.0 的类型B工作流程指南。*
