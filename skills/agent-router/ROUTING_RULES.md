# Agent Router 路由规则配置

> **版本**: 1.0.0
> **更新**: 2026-01-22

---

## 规则结构

```yaml
路由规则:
  - id: 规则唯一标识
    agent: 目标 Agent
    confidence: 基础置信度 (0-1)
    conditions:
      文件路径匹配
      任务类型匹配
      关键词匹配
    boosters: 置信度加成
    priority: 优先级 (越高越优先)
```

---

## 文件路径规则

| ID | Agent | 路径模式 | 置信度 | 说明 |
|----|-------|----------|--------|------|
| FP-001 | backend-architect | `backend/**/*` | 0.90 | 后端目录 |
| FP-002 | backend-architect | `api/**/*` | 0.95 | API 目录 |
| FP-003 | backend-architect | `server/**/*` | 0.85 | 服务器目录 |
| FP-004 | backend-architect | `services/**/*` | 0.85 | 服务层 |
| FP-005 | backend-architect | `database/**/*` | 0.90 | 数据库 |
| FP-006 | backend-architect | `migrations/**/*` | 0.80 | 数据迁移 |
| FP-007 | backend-architect | `*.go` | 0.85 | Go 后端 |
| FP-008 | backend-architect | `*Routes.java` | 0.90 | Java 路由 |
| FP-009 | mobile-developer | `mobile/**/*` | 0.95 | 移动端目录 |
| FP-010 | mobile-developer | `ios/**/*` | 0.90 | iOS 目录 |
| FP-011 | mobile-developer | `android/**/*` | 0.90 | Android 目录 |
| FP-012 | mobile-developer | `*.dart` | 0.90 | Flutter/Dart |
| FP-013 | mobile-developer | `*.swift` | 0.85 | Swift |
| FP-014 | mobile-developer | `*.kt` | 0.85 | Kotlin |
| FP-015 | knowledge-manager | `docs/**/*` | 0.85 | 文档目录 |
| FP-016 | knowledge-manager | `spec/**/*` | 0.80 | 规格目录 |
| FP-017 | knowledge-manager | `ARCHITECTURE.md` | 0.90 | 架构文档 |
| FP-018 | ai-engineer | `ai/**/*` | 0.90 | AI 目录 |
| FP-019 | ai-engineer | `llm/**/*` | 0.95 | LLM 目录 |
| FP-020 | ai-engineer | `rag/**/*` | 0.95 | RAG 目录 |
| FP-021 | ai-engineer | `agents/**/*` | 0.85 | Agent 目录 |
| FP-022 | frontend-developer | `frontend/**/*` | 0.85 | 前端目录 |
| FP-023 | frontend-developer | `web/**/*` | 0.85 | Web 目录 |
| FP-024 | frontend-developer | `*.jsx` | 0.70 | React |
| FP-025 | frontend-developer | `*.vue` | 0.70 | Vue |

---

## 任务类型规则

| ID | Agent | 任务类型 | 置信度 | 触发关键词 |
|----|-------|----------|--------|------------|
| TT-001 | backend-architect | `architecture` | 0.85 | 后端架构、API 设计 |
| TT-002 | backend-architect | `api-design` | 0.95 | API、接口、endpoint |
| TT-003 | backend-architect | `database` | 0.90 | 数据库、schema、索引 |
| TT-004 | backend-architect | `microservice` | 0.85 | 微服务、服务边界 |
| TT-005 | mobile-developer | `mobile-feature` | 0.95 | 移动端功能、App |
| TT-006 | mobile-developer | `offline-sync` | 0.90 | 离线同步 |
| TT-007 | mobile-developer | `push-notification` | 0.90 | 推送通知 |
| TT-008 | knowledge-manager | `documentation` | 0.85 | 文档、API 文档 |
| TT-009 | knowledge-manager | `ai-ddd` | 0.90 | AI-DDD、领域建模 |
| TT-010 | qa-engineer | `code-review` | 0.95 | 代码审查、PR review |
| TT-011 | qa-engineer | `testing` | 0.85 | 测试、测试策略 |
| TT-012 | qa-engineer | `performance` | 0.70 | 性能分析 |
| TT-013 | tech-lead | `planning` | 0.85 | 任务规划、分解 |
| TT-014 | tech-lead | `tech-decision` | 0.90 | 技术决策、选型 |
| TT-015 | ai-engineer | `llm` | 0.95 | LLM、大模型 |
| TT-016 | ai-engineer | `rag` | 0.95 | RAG、向量检索 |
| TT-017 | ai-engineer | `prompt` | 0.85 | 提示工程、prompt |
| TT-018 | ai-engineer | `embedding` | 0.90 | 嵌入、向量 |
| TT-019 | api-documenter | `api-doc` | 0.95 | API 文档、OpenAPI |
| TT-020 | api-documenter | `sdk` | 0.85 | SDK、客户端库 |
| TT-021 | legal-advisor | `legal` | 0.95 | 法律、合规 |
| TT-022 | legal-advisor | `privacy` | 0.90 | 隐私、GDPR |
| TT-023 | ui-ux-designer | `ui-design` | 0.90 | UI、界面设计 |
| TT-024 | ui-ux-designer | `ux-research` | 0.85 | 用户研究、体验 |
| TT-025 | context-manager | `context-sync` | 0.85 | 上下文同步 |

---

## 关键词匹配规则

### 后端相关

| 关键词 | Agent | 加成 |
|--------|-------|------|
| API, endpoint, route | backend-architect | +0.1 |
| schema, migration, SQL | backend-architect | +0.1 |
| microservice, service | backend-architect | +0.05 |
| auth, authentication, authorization | backend-architect | +0.05 |

### 移动端相关

| 关键词 | Agent | 加成 |
|--------|-------|------|
| mobile, app, iOS, Android | mobile-developer | +0.1 |
| Flutter, React Native, Dart | mobile-developer | +0.15 |
| offline, sync, push | mobile-developer | +0.1 |
| widget, screen, navigation | mobile-developer | +0.05 |

### AI 相关

| 关键词 | Agent | 加成 |
|--------|-------|------|
| LLM, GPT, Claude, model | ai-engineer | +0.15 |
| RAG, vector, embedding | ai-engineer | +0.15 |
| prompt, completion | ai-engineer | +0.1 |
| agent, orchestration | ai-engineer | +0.1 |

### 文档相关

| 关键词 | Agent | 加成 |
|--------|-------|------|
| documentation, docs | knowledge-manager | +0.1 |
| architecture, design | knowledge-manager | +0.1 |
| API doc, OpenAPI | api-documenter | +0.15 |
| SDK, client library | api-documenter | +0.1 |

### 质量相关

| 关键词 | Agent | 加成 |
|--------|-------|------|
| review, code review | qa-engineer | +0.15 |
| test, testing, coverage | qa-engineer | +0.1 |
| bug, fix, issue | qa-engineer | +0.05 |
| performance, optimization | qa-engineer | +0.05 |

### 领导相关

| 关键词 | Agent | 加成 |
|--------|-------|------|
| plan, planning, task | tech-lead | +0.1 |
| decision, choice, trade-off | tech-lead | +0.15 |
| architecture, design | tech-lead | +0.05 |

---

## 技术栈匹配

| 技术栈 | Agent | 置信度 |
|--------|-------|--------|
| **后端框架** |
| Express.js | backend-architect | 0.85 |
| Django / Flask | backend-architect | 0.90 |
| Spring Boot | backend-architect | 0.85 |
| FastAPI | backend-architect | 0.85 |
| **移动端** |
| Flutter | mobile-developer | 0.95 |
| React Native | mobile-developer | 0.95 |
| Swift / UIKit | mobile-developer | 0.90 |
| Kotlin / Jetpack | mobile-developer | 0.90 |
| **AI/ML** |
| LangChain | ai-engineer | 0.90 |
| OpenAI API | ai-engineer | 0.85 |
| Anthropic API | ai-engineer | 0.85 |
| Pinecone / Qdrant | ai-engineer | 0.90 |
| **数据库** |
| PostgreSQL | backend-architect | 0.80 |
| MongoDB | backend-architect | 0.80 |
| Redis | backend-architect | 0.75 |

---

## 置信度计算

```yaml
最终置信度 = base_confidence + boosters

计算示例:
  任务: "实现用户登录 REST API"
  文件: backend/api/auth.js

  匹配:
    - FP-002 (api/**/*) → backend-architect: 0.95
    - 关键词 "API" → +0.1

  最终: 0.95 + 0.1 = 1.0 (上限为 1.0)
```

---

## 优先级处理

```yaml
当多个规则匹配同一 Agent:
  1. 选择最高置信度
  2. 如果置信度相同，选择优先级最高的规则
  3. 如果仍然相同，选择 ID 最小的 (最早定义)

当多个 Agent 置信度相近 (差值 < 0.1):
  - 降级到推荐模式
  - 展示所有候选 Agent
```

---

## Fallback 规则

```yaml
Fallback 层级:
  1. 专业 Agent (confidence > 0.7)
  2. general-purpose (兜底)
  3. 错误: 无可用 Agent (不应发生)
```

---

## 配置示例

### 项目级覆盖

```json
{
  "enabled": true,
  "default_mode": "recommend",
  "confidence_threshold": 0.9,
  "max_candidates": 3,
  "fallback_agent": "general-purpose",
  "custom_rules": {
    "backend-architect": {
      "boosters": ["microservice", "graphql"]
    },
    "mobile-developer": {
      "boosters": ["state-management", "navigation"]
    }
  }
}
```

### 任务级覆盖

```yaml
# detailed-tasks.yaml
tasks:
  - id: TASK-001
    description: "实现用户认证"
    agent: backend-architect
    agent_reason: "指定后端架构师处理认证逻辑"
```

---

## 维护指南

### 添加新规则

1. 确定规则类型 (FP/TT/关键词)
2. 分配唯一 ID
3. 定义匹配条件和置信度
4. 更新此文档
5. 测试规则有效性

### 规则审查

- 每月审查规则有效性
- 根据实际使用调整置信度
- 移除冗余规则
- 合并相似规则

---

**最后更新**: 2026-01-22
