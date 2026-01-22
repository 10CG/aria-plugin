# 工作流程 - 类型D: 跨模块协同变更

> **版本**: 2.1.0
> **适用**: 涉及多个子模块 + 主项目的协同变更

本文档包含类型D（跨模块协同变更）特定的工作流程步骤。

**📚 文档导航**:
- **入口文档** → [SKILL.md](./SKILL.md)
- **变更类型识别** → [CHANGE_TYPES.md](./CHANGE_TYPES.md)
- **通用流程** → [WORKFLOW_CORE.md](./WORKFLOW_CORE.md)
- **类型D流程（本文档）** → 您正在阅读

---

## 类型D特征

```yaml
文件涉及:
  - 多个子模块 + 主项目文档
  - 示例: backend/** + mobile/** + docs/contracts/**

典型场景:
  - API契约变更 + 双端实现
  - 架构重构涉及多模块
  - 测试覆盖跨模块同步

UPM处理: 读取主模块UPM
Phase/Cycle来源: 主模块进度
```

---

## Phase 1: 项目状态感知 (类型D专用)

### 步骤1.0: 识别涉及的模块

```yaml
模块识别流程:

1. 分析所有变更文件
2. 识别涉及的模块列表
3. 确定主要模块（变更量最大或最核心）
4. 记录关联模块

示例:
  变更文件:
    - backend/app/api/sync.py
    - backend/app/services/sync_service.py
    - mobile/lib/services/sync_client.dart
    - mobile/lib/pages/sync_page.dart
    - shared/contracts/sync_api.yaml

  识别结果:
    主要模块: backend（API定义方）
    关联模块: mobile, shared
```

### 步骤1.1: 读取主模块UPM

**使用主模块UPM**:
```
docs/project-planning/unified-progress-management.md
```

```bash
# 读取主模块UPM获取当前状态
grep -A 20 "^# UPMv2-STATE" docs/project-planning/unified-progress-management.md
```

**提取信息**:
```yaml
UPMv2-STATE:
  module: "main"
  stage: "Phase 3 - Development"
  cycleNumber: 7
  lastUpdateAt: "2025-12-18T..."
```

### 步骤1.2: 分组提交策略

```yaml
跨模块提交策略:

选项A: 单次大提交（不推荐）
  - 所有变更一次提交
  - 缺点: 提交过大，难以回滚

选项B: 按模块分组提交（推荐）
  - Group 1: shared/contracts（API契约）
  - Group 2: backend/**（后端实现）
  - Group 3: mobile/**（前端实现）
  - 优点: 清晰的变更边界

选项C: 按功能层次提交
  - Group 1: 契约定义
  - Group 2: 所有实现
  - Group 3: 所有测试
```

---

## Phase 6.3: 项目进度关联 (类型D专用)

### Context来源

```yaml
类型D Context策略:
  来源: 主模块UPM的 UPMv2-STATE

  格式: Phase{N}-Cycle{M} {context}

  特殊处理:
    - 主模块标记: 🔗 Module: {primary_module}
    - 关联模块标记: 🔗 Related: {related_modules}
```

### 完整提交消息示例

**单次跨模块提交**:
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
📋 Context: Phase3-Cycle7 cross-module-sync-feature  # ← 从主模块UPM读取
🔗 Module: backend
🔗 Related: mobile-sync-integration, shared-contracts
```

**分组提交示例**:

Group 1 - API契约:
```
docs(shared): 定义实时同步API契约 / Define real-time sync API contract

🤖 Executed-By: api-documenter subagent
📋 Context: Phase3-Cycle7 sync-api-contract
🔗 Module: shared
```

Group 2 - Backend实现:
```
feat(backend): 实现WebSocket同步服务 / Implement WebSocket sync service

🤖 Executed-By: backend-architect subagent
📋 Context: Phase3-Cycle7 backend-sync-implementation
🔗 Module: backend
🔗 Related: shared-contracts
```

Group 3 - Mobile实现:
```
feat(mobile): 集成实时同步客户端 / Integrate real-time sync client

🤖 Executed-By: mobile-developer subagent
📋 Context: Phase3-Cycle7 mobile-sync-integration
🔗 Module: mobile
🔗 Related: backend-sync-service
```

---

## 快速检查清单

### Phase 1 检查
- [ ] 识别所有涉及的模块
- [ ] 确定主要模块
- [ ] 读取主模块UPM
- [ ] 确定分组提交策略

### Phase 6.3 检查
- [ ] Context使用主模块Phase/Cycle
- [ ] Module标记为主要模块
- [ ] Related标记关联模块
- [ ] 分组提交时每组Context一致

---

## 下一步

完成Phase 1后，继续执行 [WORKFLOW_CORE.md](./WORKFLOW_CORE.md) 中的Phase 2-7通用流程。

---

*本文档是 strategic-commit-orchestrator v2.1.0 的类型D工作流程指南。*
