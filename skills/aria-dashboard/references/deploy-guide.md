# aria-dashboard Deploy Guide

> 部署参考 | 三种运行模式: 静态 / Git 原生服务 / CI 集成

---

## 1. 静态模式 (默认)

直接在浏览器中打开生成的 HTML 文件。无需任何服务器。

```bash
# 生成看板
# (通过 /aria:dashboard skill 执行)

# 打开
open .aria/dashboard/index.html          # macOS
xdg-open .aria/dashboard/index.html      # Linux
```

### 功能范围

| 功能 | 支持 |
|------|------|
| 进度看板 (5 个数据区块) | 是 |
| Issue 表单 → 生成 Markdown | 是 |
| Issue 直接提交到 Git/API | 否 (需手动复制) |

### Issue 提交流程 (手动)

1. 在看板页面填写 Issue 表单
2. 点击 "Generate Issue Markdown"
3. 复制生成的 Markdown 内容
4. 手动创建文件:

```bash
# 文件名使用生成的 timestamp
mkdir -p .aria/issues/
# 粘贴内容到文件
vim .aria/issues/ISSUE-2026-04-03T10-30-00Z.md

# 提交
git add .aria/issues/ISSUE-2026-04-03T10-30-00Z.md
git commit -m "chore(issues): add ISSUE-2026-04-03T10-30-00Z — issue title"
```

---

## 2. Git 原生服务模式

简单 Node.js 服务器接收 POST 请求，写入 `.aria/issues/` 并自动 git commit。

### 前置条件

- Node.js >= 18
- Git 仓库已初始化
- 运行目录为项目根目录

### 最小服务器示例

```javascript
// server.js — 最小 Issue 提交服务器
const http = require('http');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const PORT = process.env.PORT || 3001;
const ISSUES_DIR = path.join(process.cwd(), '.aria', 'issues');
const DASHBOARD_PATH = path.join(process.cwd(), '.aria', 'dashboard', 'index.html');

const server = http.createServer((req, res) => {
  // Serve dashboard
  if (req.method === 'GET' && (req.url === '/' || req.url === '/index.html')) {
    if (fs.existsSync(DASHBOARD_PATH)) {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      res.end(fs.readFileSync(DASHBOARD_PATH, 'utf-8'));
    } else {
      res.writeHead(404);
      res.end('Dashboard not generated. Run /aria:dashboard first.');
    }
    return;
  }

  // Handle issue submission
  if (req.method === 'POST' && req.url === '/api/issues') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      try {
        const data = JSON.parse(body);
        const result = createIssue(data);
        res.writeHead(201, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(result));
      } catch (err) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: err.message }));
      }
    });
    return;
  }

  res.writeHead(404);
  res.end('Not found');
});

function createIssue({ title, description, type = 'bug', priority = 'P2' }) {
  if (!title || !description) {
    throw new Error('title and description are required');
  }

  const now = new Date();
  const ts = now.toISOString().replace(/:/g, '-').replace(/\.\d+Z$/, 'Z');
  const id = `ISSUE-${ts}`;
  const filepath = path.join(ISSUES_DIR, `${id}.md`);

  // Ensure directory
  fs.mkdirSync(ISSUES_DIR, { recursive: true });

  // Render markdown
  const titleTrunc = title.length > 50 ? title.slice(0, 50) + '...' : title;
  const content = [
    '---',
    `id: ${id}`,
    `title: "${title.replace(/"/g, '\\"')}"`,
    `type: ${type}`,
    `priority: ${priority}`,
    `status: open`,
    `created: "${now.toISOString()}"`,
    `updated: "${now.toISOString()}"`,
    `reporter: ""`,
    `assignee: ""`,
    `labels: []`,
    `resolution: ""`,
    `pr_link: ""`,
    '---',
    '',
    '## Description',
    '',
    description,
    ''
  ].join('\n');

  fs.writeFileSync(filepath, content, 'utf-8');

  // Git commit
  execSync(`git add "${filepath}"`, { stdio: 'pipe' });
  execSync(`git commit -m "chore(issues): add ${id} — ${titleTrunc}"`, { stdio: 'pipe' });

  return { id, filepath, message: `Issue ${id} created and committed.` };
}

server.listen(PORT, () => {
  console.log(`aria-dashboard server running on http://localhost:${PORT}`);
  console.log(`  Dashboard:  GET /`);
  console.log(`  Submit:     POST /api/issues`);
});
```

### 启动

```bash
cd /path/to/project
node server.js
# → http://localhost:3001
```

### API 调用示例

```bash
curl -X POST http://localhost:3001/api/issues \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Login page broken on mobile",
    "description": "Input field extends beyond viewport on iPhone 14 Pro",
    "type": "bug",
    "priority": "P1"
  }'
```

### 注意事项

- 服务器运行在项目根目录，直接操作 Git 仓库
- 不适合多人并发写入 (Git 锁冲突)，适用于单人或小团队场景
- 生产环境请使用 API 模式 (GitHub/Forgejo)

---

## 3. CI 集成

通过 Forgejo Actions 或 GitHub Actions 在 Issue 提交后自动重新生成看板。

### Forgejo Actions 示例

```yaml
# .forgejo/workflows/dashboard-refresh.yml
name: Refresh Dashboard
on:
  push:
    paths:
      - '.aria/issues/**'
      - 'docs/requirements/user-stories/**'
      - 'openspec/**'

jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Generate dashboard
        run: |
          # 调用 aria-dashboard skill 重新生成
          # 具体命令取决于 CI 环境中的 AI agent 配置
          echo "Dashboard refresh triggered by file change"
```

### GitHub Actions 示例

```yaml
# .github/workflows/dashboard-refresh.yml
name: Refresh Dashboard
on:
  push:
    paths:
      - '.aria/issues/**'
      - 'docs/requirements/user-stories/**'
      - 'openspec/**'

jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Generate dashboard
        run: |
          echo "Dashboard refresh triggered by file change"
```

### 触发条件说明

| 触发路径 | 原因 |
|----------|------|
| `.aria/issues/**` | 新 Issue 提交 |
| `docs/requirements/user-stories/**` | User Story 状态变更 |
| `openspec/**` | Spec 创建/归档 |

---

## 模式对比

| 特性 | 静态模式 | Git 原生服务 | CI 集成 |
|------|----------|-------------|---------|
| 外部依赖 | 无 | Node.js | CI runner |
| Issue 提交 | 手动复制 | 自动写入 + git commit | 依赖其他提交方式 |
| 看板刷新 | 手动运行 skill | 手动运行 skill | push 触发自动刷新 |
| 适用场景 | 个人开发 | 小团队本地 | 团队协作 + 自动化 |
| 并发安全 | N/A | 单人 | Git 原生 (push/pull) |
