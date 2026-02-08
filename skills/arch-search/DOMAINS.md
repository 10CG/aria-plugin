# 架构搜索领域映射

> **Purpose**: Layer 1 快速路由的领域→文档映射表
> **Format**: 关键词模式 → primary/secondary 文档路径
> **维护**: 新增架构文档时同步更新此映射

---

## 映射格式说明

```yaml
领域名称:
  keywords: [关键词列表，支持中英文]
  primary: 首选文档路径
  secondary: 备选文档路径（可选）
  description: 领域简述
```

---

## 领域映射表

### 认证与安全

```yaml
auth_security:
  keywords:
    - 认证
    - 登录
    - 注册
    - auth
    - jwt
    - token
    - 安全
    - security
    - 加密
    - encryption
    - 权限
    - permission
  primary: mobile/docs/architecture/security.md
  secondary: shared/contracts/api/auth.yaml
  description: 用户认证、安全机制、加密存储
```

### 数据存储

```yaml
data_storage:
  keywords:
    - 数据库
    - database
    - postgresql
    - postgres
    - sqlite
    - sqlcipher
    - 存储
    - storage
    - 持久化
    - persistence
  primary: backend/docs/architecture/database.md
  secondary: mobile/docs/architecture/data-storage.md
  description: 后端数据库设计、移动端本地存储
```

### 网络通信

```yaml
network:
  keywords:
    - api
    - 接口
    - endpoint
    - rest
    - restful
    - 网络
    - network
    - http
    - dio
    - 请求
    - request
  primary: shared/contracts/openapi/
  secondary: mobile/docs/architecture/network.md
  description: API 契约定义、网络层实现
```

### 数据同步

```yaml
sync:
  keywords:
    - 同步
    - sync
    - 离线
    - offline
    - 冲突
    - conflict
    - 增量
    - incremental
  primary: mobile/docs/architecture/sync.md
  secondary: shared/contracts/api/sync.yaml
  description: 离线同步、冲突解决、增量更新
```

### 状态管理

```yaml
state_management:
  keywords:
    - 状态
    - state
    - provider
    - riverpod
    - 状态管理
    - notifier
  primary: mobile/docs/architecture/state.md
  description: Flutter 状态管理方案
```

### UI 与组件

```yaml
ui_components:
  keywords:
    - ui
    - 界面
    - widget
    - 组件
    - component
    - theme
    - 主题
    - 设计
    - design
    - 样式
    - style
  primary: mobile/docs/architecture/ui.md
  secondary: mobile/docs/architecture/components.md
  description: UI 架构、组件库、主题系统
```

### 导航与路由

```yaml
navigation:
  keywords:
    - 导航
    - navigation
    - 路由
    - router
    - route
    - 页面
    - page
    - screen
  primary: mobile/docs/architecture/navigation.md
  description: 应用导航、路由配置
```

### 测试

```yaml
testing:
  keywords:
    - 测试
    - test
    - 单元测试
    - unit
    - 集成测试
    - integration
    - widget测试
    - coverage
    - 覆盖率
    - mock
  primary: mobile/docs/testing/
  secondary: mobile/docs/testing/
  description: 测试策略、测试报告
```

### Git 与版本控制

```yaml
git_version:
  keywords:
    - git
    - commit
    - 提交
    - 分支
    - branch
    - merge
    - 合并
    - submodule
    - 子模块
  primary: standards/conventions/git-commit.md
  secondary: standards/workflow/git-submodule-workflow.md
  description: Git 提交规范、子模块工作流
```

### 开发规范

```yaml
conventions:
  keywords:
    - 规范
    - 标准
    - convention
    - naming
    - 命名
    - 格式
    - format
    - 风格
    - style
  primary: standards/conventions/
  secondary: standards/README.md
  description: 代码规范、命名约定
```

### 进度管理

```yaml
progress:
  keywords:
    - 进度
    - progress
    - upm
    - 计划
    - plan
    - milestone
    - 里程碑
    - 状态
    - 开发计划
  primary: "{module}/project-planning/unified-progress-management.md"
  secondary: "{module}/docs/project-planning/unified-progress-management.md"
  description: 统一进度管理、开发计划
  note: "{module}" 需替换为具体模块名 (mobile/backend)
```

### API 契约

```yaml
api_contracts:
  keywords:
    - 契约
    - contract
    - schema
    - openapi
    - swagger
    - 数据模型
    - model
  primary: shared/contracts/
  secondary: shared/schemas/
  description: API 契约定义、数据模型
```

### AI 系统

```yaml
ai_system:
  keywords:
    - ai
    - 人工智能
    - llm
    - 大模型
    - 记忆
    - memory
    - 智能
  primary: mobile/docs/architecture/ai-memory.md
  secondary: mobile/docs/ai-hybrid-system/
  description: AI 功能设计、记忆系统
```

### 架构文档管理

```yaml
doc_management:
  keywords:
    - 架构文档
    - 文档管理
    - 文档维护
    - L0
    - L1
    - L2
  primary: standards/architecture-documentation-management-system.md
  description: 架构文档的创建和维护规范
```

---

## 模块入口速查

当无法匹配具体领域时，使用模块入口：

```yaml
mobile:
  keywords: [mobile, 移动端, flutter, dart, app, 客户端]
  entry: mobile/docs/ARCHITECTURE.md

backend:
  keywords: [backend, 后端, python, fastapi, server, 服务端]
  entry: backend/docs/ARCHITECTURE.md

shared:
  keywords: [shared, 共享, 契约, contract, api定义]
  entry: shared/README.md

standards:
  keywords: [standards, 规范, 标准, ai-ddd, methodology]
  entry: standards/README.md
```

---

## 维护指南

### 添加新领域

1. 在上方添加新的领域映射块
2. 确保 `keywords` 覆盖中英文常用词
3. `primary` 指向最相关的架构文档
4. `secondary` 指向补充文档（可选）

### 更新现有领域

1. 当架构文档路径变更时，更新 `primary/secondary`
2. 当发现常用关键词未被覆盖时，添加到 `keywords`

---

**相关文档**: `@.claude/skills/arch-common/SKILL.md`
