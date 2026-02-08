# Strategic Commit Orchestrator - 示例库

> 本文档提供 strategic-commit-orchestrator 的完整示例集合，涵盖各种实战场景。

## 📚 示例分类

本文档按照变更类型分类提供示例：

- **类型A示例**: 子模块功能变更（需读取UPM，使用实际Phase/Cycle）
- **类型B示例**: 主项目基础设施变更（使用逻辑Phase/Cycle）
- **类型C示例**: 跨模块协同变更（读取主模块UPM）

---

## 类型A示例：子模块功能变更

### 示例A1: Mobile功能开发 - 数据可视化图表页面

**场景**: Mobile实现数据可视化图表页面

**变更文件**:
```
M  mobile/lib/pages/analytics_page.dart
A  mobile/lib/widgets/chart_widget.dart
M  mobile/lib/services/task_service.dart
M  mobile/pubspec.yaml
```

**执行流程**:
```yaml
Step 1.0: 变更类型识别
  识别: mobile/** 变更
  变更类型: 类型A（子模块功能变更）
  UPM路径: mobile/docs/project-planning/unified-progress-management.md

Step 1.1: 读取Mobile UPM
  读取结果:
    stage: "Phase 4 - Sprint Development"
    cycleNumber: 9
    → 实际Phase/Cycle: Phase4-Cycle9

Step 2: 变更智能分析
  - 新增: chart_widget.dart (UI组件)
  - 修改: analytics_page.dart (页面整合)
  - 修改: task_service.dart (数据服务)
  - 修改: pubspec.yaml (fl_chart依赖)

Step 3: 分组提交策略
  单次提交: 完整功能实现（UI + 数据服务 + 依赖）

Step 4: Subagent分配
  mobile-developer subagent (熟悉Flutter UI和状态管理)

Step 6.2: 增强标记
  🤖 Executed-By: mobile-developer subagent
  📋 Context: Phase4-Cycle9 mobile-feature-development  # 来自UPM
  🔗 Module: mobile
```

**最终提交**:
```
feat(mobile): 实现任务分析图表页面 / Implement task analytics chart page

添加数据可视化组件展示任务统计信息。

- 使用 fl_chart 绘制完成率趋势图
- 实现任务分类饼图
- 添加时间范围筛选器

🤖 Executed-By: mobile-developer subagent

📋 Context: Phase4-Cycle9 mobile-feature-development

🔗 Module: mobile

Refs: mobile/docs/project-planning/unified-progress-management.md#P2
```

---

### 示例A2: Backend API开发 - 任务优先级功能

**场景**: Backend添加任务优先级API端点

**变更文件**:
```
M  backend/src/routes/tasks.py
M  backend/src/models/task.py
A  backend/tests/test_task_priority.py
M  backend/alembic/versions/add_priority_field.py
```

**执行流程**:
```yaml
Step 1.0: 变更类型识别
  识别: backend/** 变更
  变更类型: 类型A（子模块功能变更）
  UPM路径: backend/project-planning/unified-progress-management.md

Step 1.1: 读取Backend UPM
  读取结果:
    stage: "Phase 2 - Core Development"
    cycleNumber: 5
    → 实际Phase/Cycle: Phase2-Cycle5

Step 2-3: 分析和分组
  Group 1: 数据模型和迁移（model + migration）
  Group 2: API路由和测试（routes + tests）

Step 4: Subagent分配
  Task 1: backend-architect → Group 1
  Task 2: backend-architect → Group 2
```

**最终提交（共2个）**:
```
Commit 1:
feat(backend/db): 添加任务优先级字段

在Task模型中添加priority字段，支持High/Medium/Low三级优先级。

🤖 Executed-By: backend-architect subagent

📋 Context: Phase2-Cycle5 backend-task-priority-schema

🔗 Module: backend

---

Commit 2:
feat(backend/api): 实现任务优先级API端点

添加设置和查询任务优先级的API接口，包含完整的单元测试。

🤖 Executed-By: backend-architect subagent

📋 Context: Phase2-Cycle5 backend-task-priority-api

🔗 Module: backend
```

---

## 类型B示例：主项目基础设施变更

### 示例B1: 标准文档更新 - UPM路径修复

**场景**: 修复UPM路径规范不一致问题

**变更文件**:
```
M  standards/core/unified-progress-management-spec.md
M  .claude/skills/strategic-commit-orchestrator/SKILL.md
A  .claude/docs/UPM_PATH_INCONSISTENCY_ANALYSIS.md
A  .claude/docs/UPM_PATH_FIX_VERIFICATION.md
```

**执行流程**:
```yaml
Step 1.0: 变更类型识别
  识别: standards/** + .claude/skills/** + .claude/docs/** 变更
  变更类型: 类型B（主项目基础设施变更）
  → 跳过UPM路径解析

Step 1.1: 确定逻辑Phase/Cycle
  工作内容: 标准文档统一和修复
  工作阶段: Phase1（基础设施完善）第1轮迭代
  → 逻辑Phase/Cycle: Phase1-Cycle1

Step 2-5: 分析、分组、Subagent分配、编排

Step 6.2: 增强标记
  🤖 Executed-By: knowledge-manager subagent
  📋 Context: Phase1-Cycle1 standards-unification  # 逻辑Phase
  🔗 Module: standards
```

**最终提交**:
```
fix(standards/upm): 修复UPM路径规范不一致问题 / Fix UPM path specification inconsistency

修复unified-progress-management-spec.md和strategic-commit-orchestrator.md中UPM路径定义不一致问题。

修复内容:
- unified-progress-management-spec.md: 更新路径规范为基于Submodule架构的实际路径
- strategic-commit-orchestrator.md: 新增步骤1.0动态UPM路径解析逻辑

🤖 Executed-By: knowledge-manager subagent

📋 Context: Phase1-Cycle1 standards-unification

🔗 Module: standards

Refs: .claude/docs/UPM_PATH_INCONSISTENCY_ANALYSIS.md
Refs: .claude/docs/UPM_PATH_FIX_VERIFICATION.md
```

---

### 示例B2: Skills系统升级 - v2.0.0通用化

**场景**: Skills v2.0.0通用化升级支持多模块

**变更文件**:
```
M  .claude/skills/strategic-commit-orchestrator/SKILL.md
M  .claude/skills/commit-msg-generator/SKILL.md
A  .claude/docs/SKILLS_COMBINATION_DESIGN.md
A  .claude/docs/ai-ddd-universal-progress-management-adr.md
```

**执行流程**:
```yaml
Step 1.0: 变更类型识别
  识别: .claude/skills/** + .claude/docs/** 变更
  变更类型: 类型B（主项目基础设施变更）
  → 跳过UPM路径解析

Step 1.1: 确定逻辑Phase/Cycle
  工作内容: Skills系统升级支持多模块
  工作阶段: Phase1（Skills v2.0.0）第2轮迭代
  → 逻辑Phase/Cycle: Phase1-Cycle2

Step 3: 分组提交策略
  Group 1: strategic-commit-orchestrator升级
  Group 2: commit-msg-generator升级
  Group 3: 架构设计文档

Step 4: Subagent分配
  tech-lead subagent (系统级架构升级)
```

**最终提交（共3个）**:
```
Commit 1:
docs(skills): strategic-commit-orchestrator v2.0.0通用化升级

升级支持AI-DDD v3.0.0多模块架构，支持mobile/backend/frontend/shared模块。

- 模块自动识别机制
- UPM路径模板化
- Subagent映射增强

🤖 Executed-By: tech-lead subagent

📋 Context: Phase1-Cycle2 skills-v2-orchestrator-upgrade

🔗 Module: skills

---

Commit 2:
docs(skills): commit-msg-generator v2.0.0增强标记支持

添加可选增强标记（Agent/Context/Module），完全向后兼容v1.0.0。

🤖 Executed-By: tech-lead subagent

📋 Context: Phase1-Cycle2 skills-v2-generator-upgrade

🔗 Module: skills

---

Commit 3:
docs(architecture): AI-DDD v3.0.0通用进度管理架构设计

完成Skills组合设计方案和AI-DDD v3.0.0架构决策文档。

🤖 Executed-By: tech-lead subagent

📋 Context: Phase1-Cycle2 skills-v2-architecture-docs

🔗 Module: docs/architecture

Refs: .claude/docs/SKILLS_COMBINATION_DESIGN.md
```

---

### 示例B3: Scripts工具开发

**场景**: 新增文档健康度监控脚本

**变更文件**:
```
A  scripts/doc-health-monitor.js
M  package.json
A  .github/workflows/doc-health-check.yml
```

**执行流程**:
```yaml
Step 1.0: 变更类型识别
  识别: scripts/** + package.json + .github/** 变更
  变更类型: 类型B（主项目基础设施变更）
  → 跳过UPM路径解析

Step 1.1: 确定逻辑Phase/Cycle
  工作内容: 项目工具链建设
  工作阶段: Phase2（开发体验优化）第3轮迭代
  → 逻辑Phase/Cycle: Phase2-Cycle3

Step 3: 分组提交策略
  单次提交: 完整的监控系统（脚本 + CI集成）
```

**最终提交**:
```
feat(tools): 添加文档健康度监控系统

实现自动化文档质量检查，集成到CI/CD流程。

- 死链检测
- 文档分类验证
- 健康度评分

🤖 Executed-By: tech-lead subagent

📋 Context: Phase2-Cycle3 tooling-doc-health

🔗 Module: scripts
```

---

## 类型C示例：跨模块协同变更

### 示例C1: Backend + Mobile + API契约协同开发

**场景**: Backend API + Mobile客户端 + API契约

**变更文件**:
```
A  docs/contracts/api/user-auth-api-contract.md
A  backend/src/routes/auth.py
M  backend/src/app.py
A  mobile/lib/services/auth_service.dart
M  mobile/lib/main.dart
```

**执行流程**:
```yaml
Step 1.0: 变更类型识别
  识别: backend/** + mobile/** + docs/contracts/** 变更
  变更类型: 类型C（跨模块协同变更）
  主模块: backend（API提供方）

Step 1.1: 读取Backend UPM
  UPM路径: backend/project-planning/unified-progress-management.md
  读取结果:
    stage: "Phase 1 - Planning"
    cycleNumber: 1
    → 实际Phase/Cycle: Phase1-Cycle1

Step 3: 分组策略
  Group 1: API契约定义（docs/contracts/api/）
  Group 2: Backend API实现（backend/src/routes/）
  Group 3: Mobile客户端实现（mobile/lib/services/）

Step 5: Subagent编排
  Task 1: backend-architect → Group 1（API契约）
  Task 2: backend-architect → Group 2（Backend实现）
  Task 3: mobile-developer → Group 3（Mobile实现）
```

**最终提交（共3个）**:
```
Commit 1:
docs(api): 定义用户认证API契约 / Define user authentication API contract

创建用户认证相关API的OpenAPI规范。

- POST /api/auth/login - 用户登录
- POST /api/auth/register - 用户注册
- POST /api/auth/refresh - 刷新Token

🤖 Executed-By: backend-architect subagent
📋 Context: Phase1-Cycle1 backend-api-contract
🔗 Module: docs/contracts

---

Commit 2:
feat(backend): 实现用户认证API / Implement user authentication API

实现JWT token生成和验证逻辑。

- JWT token生成
- 密码哈希验证
- Token刷新机制

🤖 Executed-By: backend-architect subagent
📋 Context: Phase1-Cycle1 backend-api-development
🔗 Module: backend
🔗 Related: docs/contracts/api/user-auth-api-contract.md

---

Commit 3:
feat(mobile): 集成用户认证API / Integrate user authentication API

Mobile端调用Backend认证接口。

- 实现AuthService调用API
- Token存储和刷新
- 登录状态管理

🤖 Executed-By: mobile-developer subagent
📋 Context: Phase1-Cycle1 mobile-auth-integration
🔗 Module: mobile
🔗 Related: backend-auth-api
```

---

### 示例C2: Shared契约 + Backend + Mobile同步更新

**场景**: 任务数据模型升级（添加priority字段）

**变更文件**:
```
M  shared/contracts/schemas/task.schema.json
M  shared/contracts/openapi/tasks.yaml
M  backend/src/models/task.py
M  backend/alembic/versions/add_task_priority.py
M  mobile/lib/models/task.dart
M  mobile/lib/database/task_dao.dart
```

**执行流程**:
```yaml
Step 1.0: 变更类型识别
  识别: shared/** + backend/** + mobile/** 变更
  变更类型: 类型C（跨模块协同变更）
  主模块: shared（契约定义）

Step 1.1: 确定Phase/Cycle
  工作属性: Contract-First变更，从shared开始
  → 使用Backend的UPM（因为Backend是主要实现方）
  读取Backend UPM:
    stage: "Phase 2 - Core Development"
    cycleNumber: 5
    → 实际Phase/Cycle: Phase2-Cycle5

Step 3: 分组策略
  Group 1: API契约更新（shared/**）
  Group 2: Backend数据模型和迁移
  Group 3: Mobile数据模型和DAO

Step 5: Subagent编排
  Task 1: backend-architect → Group 1（契约定义）
  Task 2: backend-architect → Group 2（Backend实现）
  Task 3: mobile-developer → Group 3（Mobile实现）
```

**最终提交（共3个）**:
```
Commit 1:
feat(contracts): 在任务数据模型中添加priority字段

更新Task Schema和OpenAPI规范，支持优先级字段。

🤖 Executed-By: backend-architect subagent
📋 Context: Phase2-Cycle5 contracts-task-priority
🔗 Module: shared

---

Commit 2:
feat(backend): 实现任务优先级数据模型

Backend数据库Schema添加priority字段并完成数据迁移。

🤖 Executed-By: backend-architect subagent
📋 Context: Phase2-Cycle5 backend-task-priority
🔗 Module: backend
🔗 Related: contracts-task-priority

---

Commit 3:
feat(mobile): 同步任务优先级字段

Mobile本地数据库和模型添加priority字段支持。

🤖 Executed-By: mobile-developer subagent
📋 Context: Phase2-Cycle5 mobile-task-priority
🔗 Module: mobile
🔗 Related: backend-task-priority, contracts-task-priority
```

---

## 补充场景示例

### 场景1: Hotfix紧急修复

**变更文件**:
```
M  backend/src/database/connection_pool.py
M  backend/config.py
```

**提交**:
```
fix(backend/critical): 修复生产环境数据库连接池泄露

紧急修复：连接池最大连接数设置错误导致连接泄露，影响生产环境稳定性。

修复内容:
- 调整max_connections从10调整到100
- 添加connection timeout配置
- 增加连接池监控日志

🤖 Executed-By: backend-architect subagent
📋 Context: Phase3-Cycle8 hotfix-connection-pool
🔗 Module: backend
🔗 Priority: Critical

Closes #999
```

---

### 场景2: Breaking Change处理

**变更文件**:
```
M  shared/contracts/openapi/tasks.yaml (API v2)
M  backend/src/routes/tasks.py
M  mobile/lib/services/task_service.dart
A  docs/migration-guides/task-api-v2-migration.md
```

**提交**:
```
feat(api)!: 重构任务API响应格式到v2版本

BREAKING CHANGE: 任务API响应格式重大变更

旧格式 (v1):
{ "tasks": [...] }

新格式 (v2):
{
  "data": [...],
  "meta": {
    "total": 100,
    "page": 1,
    "pageSize": 20
  }
}

迁移指南: docs/migration-guides/task-api-v2-migration.md

🤖 Executed-By: backend-architect subagent
📋 Context: Phase3-Cycle10 api-v2-migration
🔗 Module: backend, mobile, shared
🔗 Priority: High

Refs #789
```

---

### 场景3: 文档批量更新

**变更文件**:
```
M  docs/maintained/README.md
M  standards/do-ref-workflow.md
M  docs/components/document-header.md
A  docs/templates/document-template-v2.md
```

**提交（单个commit）**:
```
docs: 更新文档模板和导航系统

批量更新项目文档结构和导航链接，提升文档可维护性。

更新内容:
- 统一文档头部格式
- 更新主文档索引
- 添加v2文档模板
- 修复workflow文档中的死链

🤖 Executed-By: knowledge-manager subagent
📋 Context: Phase1-Cycle3 docs-restructure
🔗 Module: docs
```

---

## 最佳实践提示

### 1. Phase/Cycle来源判断

- **类型A**: 从子模块UPM读取 → 实际Phase/Cycle
- **类型B**: 根据工作内容确定 → 逻辑Phase/Cycle
- **类型C**: 从主模块UPM读取 → 实际Phase/Cycle

### 2. 分组粒度控制

- **原子性原则**: 每个commit应该是独立可回滚的
- **功能完整性**: 相关文件尽量在同一commit
- **跨模块分离**: Contract → Backend → Frontend 分3个commit

### 3. Subagent选择策略

- **Backend变更**: backend-architect
- **Mobile变更**: mobile-developer
- **文档变更**: knowledge-manager
- **架构级变更**: tech-lead
- **跨模块协同**: 根据主模块选择

### 4. 增强标记规范

- **Context格式**: `Phase{N}-Cycle{M} {work-description}`
- **Module标识**: 使用准确的模块路径
- **Related链接**: 明确关联的相关commit或Issue

---

*更多示例持续更新中...*

参考：[SKILL.md](./SKILL.md) | [ADVANCED_GUIDE.md](./ADVANCED_GUIDE.md)
