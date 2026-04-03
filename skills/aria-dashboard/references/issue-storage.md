# Issue 存储适配器 — 参考设计

> Phase 2 实现参考 | 适配器模式支持 Git 原生与 GitHub/Forgejo API 双后端

---

## 1. Issue Markdown 格式规范

### 文件路径

```
.aria/issues/ISSUE-{timestamp}.md
```

`{timestamp}` 为 ISO 8601 格式的 UTC 时间戳，冒号替换为连字符，精确到秒：

```
ISSUE-2026-03-27T14-05-32Z.md
```

### Frontmatter 规范

```yaml
---
id: ISSUE-2026-03-27T14-05-32Z
title: "登录页面在移动端布局错乱"
type: bug
priority: P1
status: open
created: "2026-03-27T14:05:32Z"
updated: "2026-03-27T14:05:32Z"
reporter: ""
assignee: ""
labels: []
resolution: ""
pr_link: ""
---
```

#### Frontmatter 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 与文件名一致，格式 `ISSUE-{timestamp}` |
| `title` | string | 是 | Issue 标题，不超过 100 字符 |
| `type` | enum | 是 | `bug` \| `feature` \| `question` |
| `priority` | enum | 是 | `P0` \| `P1` \| `P2` \| `P3`，默认 `P2` |
| `status` | enum | 是 | 见状态机定义，初始值 `open` |
| `created` | ISO 8601 | 是 | 创建时间，UTC，只写一次不更新 |
| `updated` | ISO 8601 | 是 | 每次状态变更时更新 |
| `reporter` | string | 否 | 提交人标识（邮箱或用户名），看板提交时可为空 |
| `assignee` | string | 否 | 处理人，心跳 Agent 接单时填写 |
| `labels` | string[] | 否 | 自定义标签列表，如 `["ui", "mobile"]` |
| `resolution` | string | 否 | 关闭时填写解决说明或关联 PR 编号 |
| `pr_link` | string | 否 | 关联 PR 的 URL，心跳 Agent 自动填写 |

#### Priority 语义

| 值 | 语义 |
|----|------|
| `P0` | 生产阻塞，需立即处理 |
| `P1` | 严重影响使用，优先处理 |
| `P2` | 一般问题，正常排期（默认） |
| `P3` | 低优先级，有时间再处理 |

### Body 格式

Frontmatter 之后为 Markdown 正文，存放用户填写的描述内容：

```markdown
---
[frontmatter]
---

## 描述

登录页面在 iPhone 14 Pro（375px 宽）上，输入框超出屏幕右侧边界，
密码可见切换按钮被截断。

## 复现步骤

1. 使用移动端浏览器访问 /login
2. 观察输入框布局

## 期望结果

输入框完整显示在屏幕内，自适应宽度。

## 实际结果

输入框右侧约 20px 超出视口，需要横向滚动才能看到完整内容。
```

Body 内容不做强制约束，用户可自由书写。Frontmatter 是机读数据，Body 是人读内容。

---

## 2. Git 原生模式操作流程

Git 原生模式为默认模式，零外部依赖，适合个人项目和离线环境。

### 写入流程 (createIssue)

```
1. 生成 timestamp
   timestamp = new Date().toISOString()
              .replace(/:/g, '-').replace(/\..+/, 'Z')
   // 例: "2026-03-27T14-05-32Z"

2. 构造文件路径
   filepath = ".aria/issues/ISSUE-{timestamp}.md"

3. 确保目录存在
   mkdir -p .aria/issues/

4. 渲染 Markdown 文件 (frontmatter + body)

5. 写入文件系统

6. Git 提交
   git add .aria/issues/ISSUE-{timestamp}.md
   git commit -m "chore(issues): add ISSUE-{timestamp} — {title_truncated}"
```

提交消息规范：
- 类型固定为 `chore(issues)`
- 描述格式：`add {id} — {title}`
- title 超过 50 字符时截断并加 `...`

### 读取流程 (listIssues)

```
1. 扫描目录
   ls .aria/issues/ISSUE-*.md

2. 解析每个文件的 frontmatter
   使用 YAML front matter 解析器读取 status、priority 等字段

3. 按 created 降序排列

4. 支持过滤参数:
   - status: open | in_progress | resolved | closed | all (默认 all)
   - type: bug | feature | question
   - priority: P0 | P1 | P2 | P3
```

### 更新流程 (updateIssue)

```
1. 定位文件
   filepath = ".aria/issues/{id}.md"

2. 读取现有内容，解析 frontmatter

3. 合并更新字段，强制更新 updated 时间戳

4. 重新序列化写回文件

5. Git 提交
   git add .aria/issues/{id}.md
   git commit -m "chore(issues): update {id} status={new_status}"
```

注意事项：
- `id` 和 `created` 字段在更新时不可修改
- 状态只能按状态机定义的合法转换执行
- 心跳 Agent 更新时应在提交消息中注明 `[heartbeat]`

---

## 3. GitHub/Forgejo API 模式调用规范

当 `dashboard.issue_backend` 配置为 `github` 或 `forgejo` 时启用 API 模式。

### createIssue

**GitHub API**

```http
POST https://api.github.com/repos/{owner}/{repo}/issues
Authorization: Bearer {token}
Content-Type: application/json

{
  "title": "{title}",
  "body": "{description}\n\n---\n**Type**: {type} | **Priority**: {priority}",
  "labels": ["{type}", "priority:{priority}"]
}
```

**Forgejo API** (通过 `forgejo` CLI wrapper)

```bash
forgejo POST /repos/{owner}/{repo}/issues -d '{
  "title": "{title}",
  "body": "{description}\n\n---\n**Type**: {type} | **Priority**: {priority}",
  "labels": ["{type_label_id}", "{priority_label_id}"]
}'
```

成功响应包含平台分配的 `number` 字段，需存入本地缓存以便后续 updateIssue 使用。

### listIssues

**GitHub API**

```http
GET https://api.github.com/repos/{owner}/{repo}/issues?state=open&per_page=100
```

**Forgejo API**

```bash
forgejo GET /repos/{owner}/{repo}/issues?state=open&limit=50
```

响应字段映射：

| 平台字段 | 适配器字段 |
|----------|-----------|
| `number` | `id` |
| `title` | `title` |
| `state` | `status` (open/closed → 状态机映射) |
| `created_at` | `created` |
| `updated_at` | `updated` |
| `labels[].name` | `type`, `priority` (按 label 名解析) |

### updateIssue

**GitHub API — 关闭 Issue**

```http
PATCH https://api.github.com/repos/{owner}/{repo}/issues/{number}
Authorization: Bearer {token}
Content-Type: application/json

{
  "state": "closed"
}
```

**添加评论 (心跳 Agent 写入解决说明)**

```http
POST https://api.github.com/repos/{owner}/{repo}/issues/{number}/comments
Content-Type: application/json

{
  "body": "Resolved by {pr_link}\n\nResolution: {resolution}"
}
```

### 认证配置

API 模式需要在 `.aria/config.json` 中配置认证令牌，或通过环境变量传入：

```bash
# 环境变量优先级高于配置文件
ARIA_GITHUB_TOKEN=ghp_xxxx
ARIA_FORGEJO_TOKEN=xxxx
```

---

## 4. 适配器接口定义

适配器使用统一接口抽象，上层代码无需感知后端差异。

### IssueData 类型

```typescript
interface IssueData {
  id: string;              // ISSUE-{timestamp} 或 API issue number
  title: string;
  type: 'bug' | 'feature' | 'question';
  priority: 'P0' | 'P1' | 'P2' | 'P3';
  status: IssueStatus;
  created: string;         // ISO 8601
  updated: string;         // ISO 8601
  reporter?: string;
  assignee?: string;
  labels?: string[];
  description: string;     // body 正文
  resolution?: string;
  pr_link?: string;
}

type IssueStatus = 'open' | 'in_progress' | 'resolved' | 'closed';

interface CreateIssueInput {
  title: string;
  description: string;
  type: 'bug' | 'feature' | 'question';
  priority?: 'P0' | 'P1' | 'P2' | 'P3';  // 默认 P2
  reporter?: string;
  labels?: string[];
}

interface UpdateIssueInput {
  status?: IssueStatus;
  assignee?: string;
  resolution?: string;
  pr_link?: string;
  labels?: string[];
}

interface ListIssuesFilter {
  status?: IssueStatus | 'all';
  type?: 'bug' | 'feature' | 'question';
  priority?: 'P0' | 'P1' | 'P2' | 'P3';
}
```

### IssueStorageAdapter 接口

```typescript
interface IssueStorageAdapter {
  /**
   * 创建新 Issue。
   * Git 模式: 写入 .aria/issues/ 并提交。
   * API 模式: 调用平台 API 创建，返回平台分配的 ID。
   */
  createIssue(input: CreateIssueInput): Promise<IssueData>;

  /**
   * 查询 Issue 列表，支持过滤。
   * Git 模式: 扫描 .aria/issues/*.md 并解析 frontmatter。
   * API 模式: 调用平台 list issues API。
   */
  listIssues(filter?: ListIssuesFilter): Promise<IssueData[]>;

  /**
   * 更新 Issue 状态或元数据。
   * Git 模式: 修改文件 frontmatter 并提交。
   * API 模式: 调用平台 patch/close issue API。
   * 状态变更必须符合状态机定义的合法转换。
   */
  updateIssue(id: string, input: UpdateIssueInput): Promise<IssueData>;
}
```

### 适配器工厂

```typescript
function createIssueAdapter(config: DashboardConfig): IssueStorageAdapter {
  switch (config.issue_backend) {
    case 'git':
    default:
      return new GitIssueAdapter(config);
    case 'github':
      return new GitHubIssueAdapter(config);
    case 'forgejo':
      return new ForgejoIssueAdapter(config);
  }
}
```

AI 实现时可使用文件读写 + Bash git 命令代替 TypeScript 类，接口语义保持一致。

---

## 5. .aria/config.json 配置说明

### 完整 dashboard 配置块

```json
{
  "dashboard": {
    "enabled": true,
    "output_path": ".aria/dashboard/index.html",
    "issue_backend": "git",
    "issue_repo": "",
    "issue_api_url": ""
  }
}
```

### 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | boolean | `true` | 是否启用 dashboard |
| `output_path` | string | `.aria/dashboard/index.html` | 生成的 HTML 输出路径 |
| `issue_backend` | string | `"git"` | 存储后端，见下表 |
| `issue_repo` | string | `""` | API 模式的目标仓库，格式 `owner/repo` |
| `issue_api_url` | string | `""` | Forgejo 自建实例的 API 根地址，GitHub 留空 |

### issue_backend 取值

| 值 | 后端 | 依赖 |
|----|------|------|
| `"git"` | Git 原生（默认） | 无，零依赖 |
| `"github"` | GitHub Issues API | `ARIA_GITHUB_TOKEN` 环境变量 |
| `"forgejo"` | Forgejo Issues API | `forgejo` CLI wrapper 或 `ARIA_FORGEJO_TOKEN` |

### 切换示例：Git → GitHub

```json
{
  "dashboard": {
    "issue_backend": "github",
    "issue_repo": "10CG/aria-plugin"
  }
}
```

执行需要设置环境变量：

```bash
export ARIA_GITHUB_TOKEN=ghp_xxxxxxxxxxxx
```

### 切换示例：Git → Forgejo 自建

```json
{
  "dashboard": {
    "issue_backend": "forgejo",
    "issue_repo": "10CG/Aria",
    "issue_api_url": "https://git.example.com/api/v1"
  }
}
```

---

## 6. Issue 状态机

### 状态定义

```
open         初始状态，Issue 刚创建，等待分配
in_progress  心跳 Agent 已接单，正在执行十步循环
resolved     开发完成，PR 已创建/合并，等待人工确认
closed       人工确认关闭，或 wontfix / duplicate
```

### 状态转换图

```
         createIssue()
              │
              ▼
           [open]
              │
    ┌─────────┴──────────┐
    │ 心跳 Agent 接单      │ 人工关闭 (wontfix/duplicate)
    ▼                    ▼
[in_progress]         [closed]
    │
    │ PR 创建成功
    ▼
[resolved]
    │
    ├──── 人工确认 ──────► [closed]
    │
    └──── 重新开启 ───────► [open]
```

### 合法状态转换表

| 当前状态 | 可转换到 | 触发条件 |
|----------|----------|----------|
| `open` | `in_progress` | 心跳 Agent 开始处理 |
| `open` | `closed` | 人工标记 wontfix / duplicate |
| `in_progress` | `resolved` | PR 创建或合并成功 |
| `in_progress` | `open` | 处理失败，退回队列 |
| `resolved` | `closed` | 人工确认解决 |
| `resolved` | `open` | 人工判断未真正解决，重新开启 |
| `closed` | `open` | 重新开启（任何来源） |

### 非法转换处理

适配器在执行 `updateIssue` 时须校验状态转换合法性。如转换非法，应返回错误而非静默失败：

```
Error: Invalid status transition: in_progress → open is not allowed.
       Use status "open" only after rolling back from in_progress.
```

Git 模式下如文件不存在应返回：

```
Error: Issue not found: ISSUE-2026-03-27T14-05-32Z
       Expected path: .aria/issues/ISSUE-2026-03-27T14-05-32Z.md
```

---

## 参考

- 完整 Phase 2 设计: `openspec/changes/aria-dashboard/proposal.md`
- 配置模板: `.aria/config.template.json`
- 心跳 Agent 状态更新逻辑: `proposal.md` Phase 3 章节
- Forgejo API wrapper 路径: `/home/dev/.npm-global/bin/forgejo`
