---
name: forgejo-sync
description: |
  同步 User Story 与 Forgejo Issue，发布 PRD 到 Wiki。

  使用场景："同步 Story 到 Forgejo Issue"、"发布 PRD 到 Wiki"
argument-hint: "[--sync-direction]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Read, Glob, Grep, Edit, WebFetch
---

# Forgejo Sync Skill

> **版本**: 1.0.0 | **层级**: Layer 2 (Business Skill) | **分类**: Requirements Skills

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- 将 Story 创建为 Forgejo Issue
- 从 Issue 同步状态回 Story
- 发布 PRD 到 Forgejo Wiki
- 检查 Story/Issue 状态差异

**不使用场景**:
- 验证文档格式 → 使用 `requirements-validator`
- 同步到 UPM → 使用 `requirements-sync`

**前置条件**:
- 配置 Forgejo API 访问 (见 CONFIG.md)

---

## 核心功能

| 功能 | 描述 |
|------|------|
| **story-to-issue** | Story → Issue 创建/更新 |
| **issue-to-story** | Issue → Story 状态同步 |
| **bulk-sync** | 批量同步所有 Story |
| **status-check** | 检查状态差异 |
| **prd-to-wiki** | PRD → Wiki 发布 |

---

## 配置

### 必需配置

在 `.claude/skills/forgejo-sync/CONFIG.md` 或 `CLAUDE.local.md` 中配置:

```yaml
forgejo:
  url: "https://forgejo.example.com"
  api_token: "${FORGEJO_TOKEN}"   # 环境变量
  repo: "owner/repo"
```

### 可选配置

```yaml
forgejo:
  default_labels: ["user-story"]
  auto_create_milestone: true
  wiki:
    enabled: true
    page_prefix: "PRD-"
    generate_index: true
```

---

## 状态映射

### Story → Issue

| Story Status | Issue State | Issue Labels |
|--------------|-------------|--------------|
| draft | open | [draft] |
| ready | open | [ready] |
| in_progress | open | [in-progress] |
| blocked | open | [blocked] |
| done | closed | - |

### Issue → Story

| Issue State | Issue Labels | Story Status |
|-------------|--------------|--------------|
| open | draft | draft |
| open | ready | ready |
| open | in-progress | in_progress |
| open | blocked | blocked |
| closed | any | done |

### Priority 映射

| Story Priority | Issue Label |
|----------------|-------------|
| HIGH | priority:high |
| MEDIUM | priority:medium |
| LOW | priority:low |

---

## 执行流程

### 🔒 AI 执行前检查 (不可协商规则)

> **CRITICAL**: 在执行任何 Forgejo API 调用前，AI **必须**遵循以下检查流程。
> **统一规范**: 引用 `PRE_CHECK.md` (同目录)

#### 检查流程

```yaml
# 统一的前置检查规范
引用: PRE_CHECK.md

API_Call_Pre_Check:
  1. 读取配置:
     - 读取 CLAUDE.local.md 或 CONFIG.md
     - 查找 forgejo.cloudflare_access.enabled 值

  2. 根据 enabled 状态决定调用模式:
     enabled = true:
       → 使用 Cloudflare Access 模式
       → 必须添加两个头部:
         - CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}
         - CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}

     enabled = false 或未设置:
       → 使用标准模式
       → 仅添加标准 Authorization 头部

  3. 执行后检测:
     - 检查 HTTP 状态码
     - 检查响应内容
     - 如果 403 或包含 "cloudflare"/"challenge":
       → 自动提示用户配置 Cloudflare Access
```

#### API 调用模板 (引用统一规范)

**标准模式** (cloudflare_access 未启用):
```bash
curl -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "Content-Type: application/json" \
  "${FORGEJO_API_URL}/repos/{owner}/{repo}/issues"
```

**Cloudflare Access 模式** (cloudflare_access.enabled = true):
```bash
curl \
  -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}" \
  -H "CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}" \
  -H "Content-Type: application/json" \
  "${FORGEJO_API_URL}/repos/{owner}/{repo}/issues"
```

#### 错误检测与自动提示

**检测条件**:
- HTTP 状态码: 403
- 响应包含关键词: "cloudflare" OR "challenge" OR "access denied"

**自动提示模板**:
```
⚠️ 检测到 Cloudflare Access 保护

Forgejo API 调用被拒绝 (403)，响应中包含 Cloudflare challenge。
请在 CLAUDE.local.md 中添加以下配置：

forgejo:
  url: "你的 Forgejo URL"
  api_token: "${FORGEJO_TOKEN}"
  repo: "owner/repo"
  cloudflare_access:
    enabled: true
    client_id_env: "CF_ACCESS_CLIENT_ID"
    client_secret_env: "CF_ACCESS_CLIENT_SECRET"

并设置环境变量：
export CF_ACCESS_CLIENT_ID="your-client-id"
export CF_ACCESS_CLIENT_SECRET="your-service-token"
```

---

### Story → Issue

```yaml
步骤:
  1. 读取 Story 文件
  2. 检查是否已有 Forgejo Issue 字段
  3. 如无，调用 API 创建 Issue
     - Title: "[US-XXX] {标题}"
     - Body: Story 内容 + 验收标准
     - Labels: ["user-story", "{status}", "{priority}"]
     - Milestone: 从 Story 读取
  4. 更新 Story 文件的 Forgejo Issue 字段

输出:
  issue_created: true
  issue_number: 123
  issue_url: "https://forgejo.example.com/owner/repo/issues/123"
```

### Issue → Story

```yaml
步骤:
  1. 读取 Story 文件的 Forgejo Issue 字段
  2. 调用 API 获取 Issue 状态
  3. 根据状态映射更新 Story Status
  4. 保存 Story 文件

输出:
  story_updated: true
  old_status: "ready"
  new_status: "in_progress"
```

### PRD → Wiki

```yaml
步骤:
  1. 读取 PRD 文件
  2. 检查 PRD 状态是否为 approved
  3. 调用 Wiki API 创建/更新页面
     - Page Name: "PRD-{version}-{feature}"
     - Content: PRD 内容 + 自动页脚
  4. 更新 UPM 的 wiki_page 字段

输出:
  wiki_published: true
  page_name: "PRD-v2.1.0-notification"
  page_url: "https://forgejo.example.com/owner/repo/wiki/PRD-v2.1.0-notification"
```

---

## 输出格式

```yaml
forgejo_sync_result:
  action: "story-to-issue|issue-to-story|bulk-sync|prd-to-wiki"
  timestamp: "2026-01-01T10:00:00+08:00"

  stories:
    processed: N
    created: N
    updated: N
    skipped: N

  issues:
    created: N
    updated: N

  wiki:
    published: N
    skipped: N

  drift:
    detected: true/false
    items: [...]

  errors: [...]
```

---

## API 调用

### 创建 Issue

```yaml
method: POST
url: /api/v1/repos/{owner}/{repo}/issues
headers:
  Authorization: "token ${FORGEJO_TOKEN}"
body:
  title: "[US-001] Feature Title"
  body: |
    ## User Story
    As a {role}...

    ## Acceptance Criteria
    - [ ] Criteria 1
    - [ ] Criteria 2

    ---
    Story File: `docs/requirements/user-stories/US-001-xxx.md`
  labels: ["user-story", "ready", "priority:high"]
  milestone: 1
```

### 更新 Issue

```yaml
method: PATCH
url: /api/v1/repos/{owner}/{repo}/issues/{id}
body:
  state: "open|closed"
  labels: [...]
```

### 创建 Wiki 页面

```yaml
method: PUT
url: /api/v1/repos/{owner}/{repo}/wiki/page/{pageName}
body:
  title: "PRD: Feature Title"
  content: |
    {prd_content}

    ---
    > **Source**: `docs/requirements/prd-v2.1.0-xxx.md`
    > **Last Synced**: 2026-01-01T10:00:00
    > **Note**: Auto-synced from Git. Do not edit directly.
```

---

## 使用示例

### 创建单个 Issue

```
用户: 为 US-001 创建 Forgejo Issue

助手执行:
1. 读取 US-001-xxx.md
2. 调用 Forgejo API 创建 Issue
3. 更新 Story 文件

输出:
forgejo_sync_result:
  action: "story-to-issue"
  issues:
    created: 1
  story_updated: "US-001-xxx.md"
  issue_url: "https://..."
```

### 批量同步

```
用户: 同步所有 Story 到 Forgejo

助手执行:
1. 扫描所有 Story 文件
2. 为无 Issue 的 Story 创建 Issue
3. 同步有 Issue 的 Story 状态

输出:
forgejo_sync_result:
  action: "bulk-sync"
  stories:
    processed: 8
    created: 3
    updated: 5
```

### 发布 PRD

```
用户: 发布 PRD 到 Wiki

助手执行:
1. 读取 PRD 文件
2. 检查状态为 approved
3. 调用 Wiki API 发布

输出:
forgejo_sync_result:
  action: "prd-to-wiki"
  wiki:
    published: 1
  page_url: "https://..."
```

---

## 与其他 Skills 的关系

```
┌─────────────────────────────────────────────────────────────┐
│  requirements-validator (Layer 2)                           │
│      │ 验证后                                                │
│      ▼                                                      │
│  requirements-sync (Layer 2)                                │
│      │ 同步 UPM 后                                           │
│      ▼                                                      │
│  forgejo-sync (Layer 2) ◄── 本 Skill                        │
│      │                                                      │
│      ▼                                                      │
│  Forgejo API (外部)                                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 相关文档

- **规范**: `openspec/specs/forgejo-sync/spec.md`
- **配置模板**: `CONFIG.md` (同目录)
- **Story 模板**: `standards/templates/user-story-template.md`
- **PRD 模板**: `standards/templates/prd-template.md`
