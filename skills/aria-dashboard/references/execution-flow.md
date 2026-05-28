# Dashboard Execution Flow — Steps 1-4

> 完整 4-step dashboard 生成流程: 数据收集 → HTML 生成 → 输出 → Issue 存储 (web mode). 从 SKILL.md §执行流程 提取 (iter-2, 2026-05-28)。

## Step 1: 数据收集

扫描项目目录, 解析 5 种数据源。每种数据源独立解析, 任一缺失不影响其余。

```yaml
数据源:
  1. UPM (项目进度总览):
     路径: Glob "**/{unified-progress-management,UPM}.md"
     提取: UPMv2-STATE YAML 区块 (两种格式)
     正则 (优先级顺序):
       1. HTML 注释: /<!--\s*UPMv2-STATE\s*\n([\s\S]+?)\n-->/
       2. YAML 代码块: /```ya?ml\s*\n([\s\S]*?project:\s[\s\S]+?)\n```/
     输出: phase / status / KPI / cycle / risks

  2. User Stories (三列看板):
     路径: docs/requirements/user-stories/*.md (所有 .md 文件, 不限 US- 前缀)
     提取: 文件名 ID + 标题 + Status + Priority
     ID 提取: 文件名去掉 .md 后缀 (支持 US-001, MEM-001, OPS-001 等任意前缀)
     Status 字段匹配 (多语言, 按优先级):
       1. /\*\*Status\*\*:\s*(.+)/i
       2. /\*\*状态\*\*:\s*(.+)/i
       3. /^Status:\s*(.+)/im
       4. /^状态:\s*(.+)/im
     Priority 字段匹配:
       1. /\*\*Priority\*\*:\s*(.+)/i
       2. /\*\*优先级\*\*:\s*(.+)/i
     分组: done|completed|已完成 → 已完成, in_progress|active|进行中 → 进行中, 其余 → TODO

  3. OpenSpec (活跃 + 归档):
     活跃路径: openspec/changes/*/proposal.md
     归档路径: openspec/archive/*/proposal.md
     提取: 标题 + Status + Level + Created + Parent Story
     耗时: 归档目录日期前缀 - Created 字段

  4. Audit Reports (审计历史):
     路径: .aria/audit-reports/*.md
     提取: YAML frontmatter (checkpoint/mode/rounds/converged/timestamp)
     排序: 按 timestamp 降序, 取最近 5 条

  5. AB Benchmark (基准测试摘要):
     路径优先级 (命中即停止):
       (a) Glob "aria-plugin-benchmarks/ab-results/*/benchmark.json" (新格式, /skill-creator 标准产出)
       (b) Glob "aria-plugin-benchmarks/ab-results/*/summary.yaml"   (旧格式, 向后兼容)
     提取: overall 区块统计 + 按 delta 排序的 top skills
     选取: 按目录名日期排序, 取最新一个 (跨格式同优先级合并后选最新)
```

**容错规则**: 任何数据源不存在或解析失败时, 对应区块显示"未配置", 不报错, 不中断。

## Step 2: HTML 生成

读取 HTML 模板文件, 用收集到的数据替换占位符。

```yaml
模板路径: ${SKILL_DIR}/templates/dashboard.html
占位符格式: {{PLACEHOLDER_NAME}}

生成逻辑:
  1. 读取模板文件内容
  2. 替换静态占位符 (项目名、时间戳、统计数字)
  3. 生成动态 HTML 片段:
     - KPI 卡片: 每个 KPI 生成一个 .kpi-card
     - Story 卡片: 按列分组生成 .story-card
     - Spec 表格行: 每个 Spec 生成一行 <tr>
     - Audit 表格行: 每条审计报告生成一行 <tr>
     - Benchmark chips: top skills 生成 .skill-chip
     - Risks: 每个 risk 生成 .risk-item
  4. 组装完整 HTML
```

## Step 2.5: Issue 表单注入

在 HTML 生成时, 将 Issue 提交表单区块注入到看板内容之后、页脚之前。

```yaml
表单区块: "提交反馈" section
占位符: {{ISSUE_FORM_HTML}} (模板已内置, 无需动态替换)

表单字段:
  title:       text input (必填, maxlength=100)
  description: textarea (必填)
  priority:    select (P0 | P1 | P2 | P3, 默认 P2)
  type:        select (bug | feature | question, 默认 bug)

交互模式 (静态 HTML, 无后端):
  1. 用户填写表单
  2. 点击 "生成 Issue Markdown" 按钮
  3. JavaScript 在页面内生成 Issue Markdown 内容 (含 frontmatter)
  4. 显示在只读文本框中, 供用户手动复制
  5. 用户可通过 CLI 或手动创建 .aria/issues/ISSUE-{timestamp}.md

可部署模式 (Web 服务):
  1. 表单 POST 到后端
  2. 后端写入 .aria/issues/ 并 git commit
  3. 详见 deploy-guide.md
```

**说明**: 静态 HTML 模式下无后端, Issue 表单仅生成 Markdown 供手动使用。需要直接提交功能时, 参考部署指南启动 Web 服务。

## Step 3: 输出

```yaml
输出路径: .aria/dashboard/index.html
操作:
  1. 确保 .aria/dashboard/ 目录存在 (mkdir -p)
  2. 写入生成的 HTML 文件
  3. 尝试打开浏览器:
     - macOS: open .aria/dashboard/index.html
     - Linux: xdg-open .aria/dashboard/index.html 2>/dev/null || true
     - 打开失败不报错 (可能在 headless 环境)
  4. 输出文件路径和数据摘要
```

## Step 4: Issue 存储 (Web 服务模式)

当看板以 Web 服务模式运行时, 处理 Issue 提交请求。静态 HTML 模式下此步骤不执行。

```yaml
触发: POST /api/issues (Web 服务模式)

存储后端选择 (读取 .aria/config.json → dashboard.issue_backend):

  Git 原生模式 (默认, issue_backend = "git"):
    1. 生成 timestamp (UTC, ISO 8601, 冒号替换为连字符)
       例: "2026-03-27T14-05-32Z"
    2. 构造路径: .aria/issues/ISSUE-{timestamp}.md
    3. mkdir -p .aria/issues/
    4. 写入 Markdown 文件 (frontmatter + body)
       格式见 issue-storage.md 第 1 节
    5. git add .aria/issues/ISSUE-{timestamp}.md
    6. git commit -m "chore(issues): add ISSUE-{timestamp} — {title_truncated}"
       title 超过 50 字符时截断并加 "..."

  GitHub API 模式 (issue_backend = "github"):
    1. 读取 issue_repo 配置 (格式: owner/repo)
    2. 认证: 环境变量 ARIA_GITHUB_TOKEN 或 config 中的 token
    3. POST https://api.github.com/repos/{owner}/{repo}/issues
       body: title + description + labels [type, priority]
    4. 详见 issue-storage.md 第 3 节

  Forgejo API 模式 (issue_backend = "forgejo"):
    1. 读取 issue_repo + issue_api_url 配置
    2. 通过 forgejo CLI wrapper 调用 API
    3. forgejo POST /repos/{owner}/{repo}/issues -d '{...}'
    4. 详见 issue-storage.md 第 3 节

响应:
  成功: 返回 Issue ID + 确认消息
  失败: 返回错误信息 (文件写入失败 / API 调用失败 / 认证缺失)
```
