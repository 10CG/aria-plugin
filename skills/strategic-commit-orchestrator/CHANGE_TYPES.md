# 变更类型识别指南

> **版本**: 2.2.0
> **职责**: 识别变更类型，确定UPM读取策略

本文档帮助你识别当前变更属于哪种类型(A/B/C/D/E)，从而确定后续的工作流程。

**📚 文档导航**:
- **入口文档** → [SKILL.md](./SKILL.md)
- **变更类型识别（本文档）** → 您正在阅读
- **工作流程** → [WORKFLOW_CORE.md](./WORKFLOW_CORE.md) + 类型特定文档

---

## 规范引用

### 1. Git提交消息规范
**来源**: `@standards/conventions/git-commit.md`

**核心要求**:
- **双语规范**: 中文描述 / 英文描述
- **前缀标准**: feat/fix/docs/test/perf/style/refactor/chore/ci
- **格式结构**: `<type>(<scope>): <description> / <english description>`
- **破坏性变更**: 类型后添加感叹号 `feat!:`
- **影响范围**: 括号中指明 scope

**示例**:
```
docs(backend): 创建Backend架构文档体系 / Create Backend architecture documentation system
```

### 2. AI-DDD进度管理核心标准 (v3.0.0)
**来源**: `@standards/core/progress-management/ai-ddd-progress-management-core.md` v1.0.0

**核心要求**:
- **模块无关**: 适用于所有模块（mobile/backend/frontend/shared）
- **状态感知**: 读取UPM确定当前Phase/Cycle
- **三层状态机**: Phase → Cycle → Stage
- **七步循环**: 标准AI-DDD工作流
- **扩展点**: 模块特定定制接口

**UPMv2-STATE 机读接口**:
```yaml
module: "backend"                    # 模块标识 (v3.0.0新增)
stage: "Phase 3 - Development"
cycleNumber: 5
lastUpdateAt: "2025-12-09T..."
stateToken: "sha256:..."
```

### 3. 模块扩展规范
**来源**: `@standards/extensions/{module}-ai-ddd-extension.md`

**模块列表**:
- **Mobile扩展**: `mobile-ai-ddd-extension.md` v3.0.0
- **Backend扩展**: `backend-ai-ddd-extension.md` v3.0.0
- **Frontend扩展**: `frontend-ai-ddd-extension.md` v3.0.0 (待创建)

**扩展内容**:
- 模块特定的Stage扩展
- 质量指标定义
- 技术验证流程
- Subagent映射优先级
- 进度度量指标

### 4. 统一进度管理文档 (UPM)

**通用路径模板**: 适用于采用 Git Submodule 架构的项目

```
{module}/[docs/]project-planning/unified-progress-management.md
```

**路径解析原则**:
- `[docs/]` 表示可选中间目录，取决于具体模块的历史结构
- 路径从**主项目根目录**开始计算
- 实际路径通过 `get_upm_path()` 函数动态解析

**通用解析逻辑**:
```yaml
路径发现策略:
  1. 优先尝试: {module}/project-planning/unified-progress-management.md
  2. 备选方案: {module}/docs/project-planning/unified-progress-management.md
  3. 使用第一个存在的文件路径

模块特定例外:
  - 如已知某模块使用非标准路径，在 get_upm_path() 中显式处理
```

**核心信息来源**:
- 当前项目阶段（从 UPMv2-STATE 机读片段获取）
- 活跃任务列表和优先级
- 验证队列状态
- KPI 仪表板数据
- 模块特定的进度指标

> **可移植性说明**: 本 Skill 通过动态路径解析机制，确保在不同项目结构中均可正常工作。

---

## UPM适用范围

**核心原则**: 只有需要进行开发进度跟踪的模块才需要UPM，跨项目共享的基础设施模块不需要UPM。

```yaml
无UPM模块 (跨项目共享基础设施):
  standards/         → AI-DDD方法论SSOT，跨项目复用
  .claude/agents/    → AI代理配置系统，跨项目复用

  特征:
    - 可在多个项目间共享
    - 不跟踪具体项目进度
    - 变更使用逻辑Phase/Cycle描述

有UPM模块 (需要进度跟踪):
  主模块:
    → docs/project-planning/unified-progress-management.md

  业务子模块:
    → {module}/[docs/]project-planning/unified-progress-management.md
    → 示例: mobile/, backend/, frontend/

  特征:
    - 独立的开发周期
    - 需要跟踪Phase/Cycle进度
    - 变更从UPM读取实际进度状态
```

---

## 变更类型分类

在开始标准工作流程前，首先识别变更类型以确定后续处理策略。

### 快速决策表

| 类型 | 特征 | UPM处理 | 工作流文档 |
|------|------|---------|-----------|
| **A** | 子模块功能变更 | 读取子模块UPM | [WORKFLOW_TYPE_A.md](./WORKFLOW_TYPE_A.md) |
| **B** | 主项目变更 | 读取主模块UPM | [WORKFLOW_TYPE_B.md](./WORKFLOW_TYPE_B.md) |
| **C** | 跨项目共享基础设施 | 无UPM | [WORKFLOW_TYPE_C.md](./WORKFLOW_TYPE_C.md) |
| **D** | 跨模块协同变更 | 读取主模块UPM | [WORKFLOW_TYPE_D.md](./WORKFLOW_TYPE_D.md) |
| **E** | 全项目变更 (主项目+子模块) | 混合策略 | [WORKFLOW_TYPE_E.md](./WORKFLOW_TYPE_E.md) |

---

### 类型A: 子模块功能变更

**特征识别**:
```yaml
文件路径模式:
  - mobile/**/*
  - backend/**/*
  - frontend/**/*
  - shared/**/*

典型场景:
  - 子模块功能开发
  - 子模块Bug修复
  - 子模块测试文件
  - 子模块架构文档（在子模块内）
```

**处理策略**:
- ✅ 需要执行"步骤1.0: 动态UPM路径解析"
- ✅ 读取对应子模块的UPM文档获取实际Phase/Cycle
- ✅ Context使用实际Phase/Cycle（如Phase4-Cycle9）
- ✅ Module标记为子模块名（如mobile, backend）

**示例提交**:
```
feat(mobile): 实现任务分析图表页面 / Implement task analytics chart page

添加数据可视化组件展示任务统计信息。

🤖 Executed-By: mobile-developer subagent
📋 Context: Phase4-Cycle9 mobile-feature-development  # 从mobile UPM读取
🔗 Module: mobile
```

**下一步**: 加载 [WORKFLOW_TYPE_A.md](./WORKFLOW_TYPE_A.md) + [WORKFLOW_CORE.md](./WORKFLOW_CORE.md)

---

### 类型B: 主项目变更

**特征识别**:
```yaml
文件路径模式:
  - docs/**/*                   # 主项目文档（非standards/子模块）
  - .claude/skills/**/*         # AI Skills定义
  - .claude/docs/**/*           # 主项目级分析文档
  - .claude/commands/**/*       # 自定义命令
  - scripts/**/*                # 项目级脚本
  - *.md (根目录)               # 主项目README等
  - .cursor/rules/**/*          # Cursor规则
  - *.config.js, package.json   # 项目配置

典型场景:
  - 项目级文档体系建设
  - Skills开发/升级
  - 构建/部署脚本
  - 项目配置调整
```

**处理策略**:
- ✅ 需要执行"步骤1.0: 动态UPM路径解析"
- ✅ 读取**主模块UPM**获取实际Phase/Cycle
  * 主模块UPM: `docs/project-planning/unified-progress-management.md`
- ✅ Context使用实际Phase/Cycle
- ✅ Module标记为"main"或逻辑模块名

**示例提交**:
```
docs(skills): Skills v2.0.0升级和组合设计 / Skills v2.0.0 upgrade and combination design

完成提交相关Skills的v2.0.0升级，支持AI-DDD v3.0.0多模块架构。

🤖 Executed-By: tech-lead subagent
📋 Context: Phase2-Cycle3 skills-v2-universal-upgrade  # 从主模块UPM读取
🔗 Module: main
```

**下一步**: 加载 [WORKFLOW_TYPE_B.md](./WORKFLOW_TYPE_B.md) + [WORKFLOW_CORE.md](./WORKFLOW_CORE.md)

---

### 类型C: 跨项目共享基础设施变更

**特征识别**:
```yaml
文件路径模式:
  - standards/**/*              # AI-DDD方法论规范
  - .claude/agents/**/*         # AI代理配置系统

典型场景:
  - 方法论规范创建/更新
  - AI代理系统升级
  - 跨项目共享组件开发
```

**处理策略**:
- ❌ 不需要执行"步骤1.0: UPM路径解析"
- ❌ 不读取任何UPM文档（跨项目共享，无特定项目进度）
- ✅ Context使用逻辑Phase/Cycle描述工作阶段
  * Phase1-Cycle1: 初始化/基础设施建设
  * Phase1-Cycle2: 二次优化/升级
  * Phase{N}-Cycle{M}: 对应具体工作迭代
- ✅ Module标记为共享模块名（standards, agents）

**示例提交**:
```
fix(standards/upm): 修复UPM路径规范不一致问题 / Fix UPM path specification inconsistency

修复unified-progress-management-spec.md和strategic-commit-orchestrator.md中UPM路径定义不一致问题。

🤖 Executed-By: knowledge-manager subagent
📋 Context: Phase1-Cycle1 standards-unification  # 逻辑Phase，表示标准统一工作第1轮
🔗 Module: standards
```

**下一步**: 加载 [WORKFLOW_TYPE_C.md](./WORKFLOW_TYPE_C.md) + [WORKFLOW_CORE.md](./WORKFLOW_CORE.md)

---

### 类型D: 跨模块协同变更

**特征识别**:
```yaml
文件涉及:
  - 多个子模块 + 主项目文档
  - 示例: backend/** + mobile/** + docs/contracts/**

典型场景:
  - API契约变更 + 双端实现
  - 架构重构涉及多模块
  - 测试覆盖跨模块同步
```

**处理策略**:
- ✅ 需要识别主要变更所属模块
- ✅ 读取主模块的UPM获取Phase/Cycle
- ✅ 可能需要分组提交（每个模块独立commit）
- ✅ Module标记为主模块或使用"cross-module"

**示例提交**:
```
feat(backend+mobile): 实现实时同步功能 / Implement real-time sync feature

Backend提供WebSocket接口，Mobile端建立连接实现数据实时同步。

Backend变更:
- 添加WebSocket服务器
- 实现消息推送逻辑

Mobile变更:
- 集成WebSocket客户端
- 实现自动重连机制

🤖 Executed-By: backend-architect subagent
📋 Context: Phase3-Cycle7 backend-api-development  # 以Backend为主
🔗 Module: backend
🔗 Related: mobile-sync-integration
```

**下一步**: 加载 [WORKFLOW_TYPE_D.md](./WORKFLOW_TYPE_D.md) + [WORKFLOW_CORE.md](./WORKFLOW_CORE.md)

---

### 类型E: 全项目变更 (v2.2.0新增)

**特征识别**:
```yaml
识别条件:
  - 主项目有变更 (docs/**, .claude/skills/**, 等)
  - 且 至少一个子模块有内部变更

检测方式:
  # 1. 检查主项目变更
  git status --short --ignore-submodules=dirty

  # 2. 检查子模块内部变更
  git submodule foreach --quiet '
    changes=$(git status --short | wc -l)
    if [ "$changes" -gt 0 ]; then
      echo "$name:$changes"
    fi
  '

  # 如果两者都有变更 → 类型E

典型场景:
  - OpenSpec 变更涉及主项目Skills + standards规范
  - 大型功能开发涉及多个子模块 + 主项目文档
  - 版本升级涉及所有模块配置调整
```

**处理策略**:
- ✅ 执行 Phase 0 全项目状态扫描
- ✅ 对每个有变更的子模块执行标准分组提交
- ✅ 最后执行主项目分组提交
- ✅ 自动更新子模块引用
- ✅ 生成全项目提交汇总报告

**UPM处理**:
```yaml
混合策略:
  - 子模块 (standards, agents): 无UPM，使用逻辑Phase
  - 子模块 (mobile, backend): 读取各自UPM
  - 主项目: 读取主模块UPM
```

**示例提交汇总**:
```markdown
## 全项目提交汇总

### 子模块提交
| 子模块 | 提交数 | 最终Hash |
|--------|--------|----------|
| standards | 6 | eaad106 |

### 主项目提交
| Commit | 类型 | 描述 |
|--------|------|------|
| cf03a38 | chore | 更新子模块引用 |
| 55e840e | docs | 配置更新 |

### 最终状态
- 总提交数: 12
- 工作树: clean
```

**下一步**: 加载 [WORKFLOW_TYPE_E.md](./WORKFLOW_TYPE_E.md) + [SUBMODULE_GUIDE.md](./SUBMODULE_GUIDE.md)

---

## 模块识别策略

```yaml
从变更文件自动识别模块和变更类型:

  # 类型A: 业务功能子模块
  IF 文件路径匹配 mobile/**:
    → module = "mobile", 类型 = A

  ELSE IF 文件路径匹配 backend/**:
    → module = "backend", 类型 = A

  ELSE IF 文件路径匹配 frontend/**:
    → module = "frontend", 类型 = A

  ELSE IF 文件路径匹配 shared/**:
    → module = "shared", 类型 = A

  # 类型C: 跨项目共享基础设施（无UPM）
  ELSE IF 文件路径匹配 standards/**:
    → module = "standards", 类型 = C

  ELSE IF 文件路径匹配 .claude/agents/**:
    → module = "agents", 类型 = C

  # 类型B: 主项目变更
  ELSE IF 文件路径匹配 docs/** OR .claude/skills/** OR .claude/docs/**
        OR .claude/commands/** OR scripts/** OR 根目录配置文件:
    → module = "main", 类型 = B

  ELSE:
    → 默认为主项目变更，类型 = B
```

---

*本文档是 strategic-commit-orchestrator v2.2.0 的变更类型识别指南。*
