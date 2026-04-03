---
name: aria-dashboard
description: |
  项目进度看板生成器。解析 UPM、User Story、OpenSpec、审计报告、AB Benchmark 五种数据源，
  生成单文件自包含 HTML 看板，写入 .aria/dashboard/index.html 并尝试在浏览器中打开。

  使用场景："生成看板"、"项目看板"、"dashboard"、"查看全局进度"、
  "项目进度可视化"、"生成进度报告"
user-invocable: true
allowed-tools: Bash, Read, Write, Glob, Grep
---

# 项目进度看板 (aria-dashboard v1.1.0)

> **版本**: 1.1.0 | **角色**: 数据可视化 + Issue 提交
> **数据 schema**: [references/data-schema.md](./references/data-schema.md)
> **HTML 模板**: [templates/dashboard.html](./templates/dashboard.html)
> **Issue 存储设计**: [references/issue-storage.md](./references/issue-storage.md)
> **部署指南**: [references/deploy-guide.md](./references/deploy-guide.md)

---

## 快速开始

### 使用场景

- 需要查看项目全局进度和状态
- 向非 CLI 用户展示项目状态
- 审阅 Spec 耗时、审计历史、AB 测试趋势
- 通过看板表单提交 Issue (bug/feature/question)

### 不使用场景

- 实时状态快照 (文本) -> 使用 `state-scanner`
- 更新 UPM 进度数据 -> 使用 `progress-updater`
- 已有 CLI 环境时直接提交 Issue -> 使用 `aria-report`

---

## 执行流程

### Step 1: 数据收集

扫描项目目录，解析 5 种数据源。每种数据源独立解析，任一缺失不影响其余。

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
     排序: 按 timestamp 降序，取最近 5 条

  5. AB Benchmark (基准测试摘要):
     路径: Glob "aria-plugin-benchmarks/ab-results/*/summary.yaml"
     提取: overall 区块统计 + 按 delta 排序的 top skills
     选取: 按日期最新的 summary.yaml
```

**容错规则**: 任何数据源不存在或解析失败时，对应区块显示"未配置"，不报错，不中断。

### Step 2: HTML 生成

读取 HTML 模板文件，用收集到的数据替换占位符。

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

### Step 2.5: Issue 表单注入

在 HTML 生成时，将 Issue 提交表单区块注入到看板内容之后、页脚之前。

```yaml
表单区块: "提交反馈" section
占位符: {{ISSUE_FORM_HTML}} (模板已内置，无需动态替换)

表单字段:
  title:       text input (必填, maxlength=100)
  description: textarea (必填)
  priority:    select (P0 | P1 | P2 | P3, 默认 P2)
  type:        select (bug | feature | question, 默认 bug)

交互模式 (静态 HTML, 无后端):
  1. 用户填写表单
  2. 点击 "生成 Issue Markdown" 按钮
  3. JavaScript 在页面内生成 Issue Markdown 内容 (含 frontmatter)
  4. 显示在只读文本框中，供用户手动复制
  5. 用户可通过 CLI 或手动创建 .aria/issues/ISSUE-{timestamp}.md

可部署模式 (Web 服务):
  1. 表单 POST 到后端
  2. 后端写入 .aria/issues/ 并 git commit
  3. 详见 references/deploy-guide.md
```

**说明**: 静态 HTML 模式下无后端，Issue 表单仅生成 Markdown 供手动使用。需要直接提交功能时，参考部署指南启动 Web 服务。

### Step 3: 输出

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

### Step 4: Issue 存储 (Web 服务模式)

当看板以 Web 服务模式运行时，处理 Issue 提交请求。静态 HTML 模式下此步骤不执行。

```yaml
触发: POST /api/issues (Web 服务模式)

存储后端选择 (读取 .aria/config.json → dashboard.issue_backend):

  Git 原生模式 (默认, issue_backend = "git"):
    1. 生成 timestamp (UTC, ISO 8601, 冒号替换为连字符)
       例: "2026-03-27T14-05-32Z"
    2. 构造路径: .aria/issues/ISSUE-{timestamp}.md
    3. mkdir -p .aria/issues/
    4. 写入 Markdown 文件 (frontmatter + body)
       格式见 references/issue-storage.md 第 1 节
    5. git add .aria/issues/ISSUE-{timestamp}.md
    6. git commit -m "chore(issues): add ISSUE-{timestamp} — {title_truncated}"
       title 超过 50 字符时截断并加 "..."

  GitHub API 模式 (issue_backend = "github"):
    1. 读取 issue_repo 配置 (格式: owner/repo)
    2. 认证: 环境变量 ARIA_GITHUB_TOKEN 或 config 中的 token
    3. POST https://api.github.com/repos/{owner}/{repo}/issues
       body: title + description + labels [type, priority]
    4. 详见 references/issue-storage.md 第 3 节

  Forgejo API 模式 (issue_backend = "forgejo"):
    1. 读取 issue_repo + issue_api_url 配置
    2. 通过 forgejo CLI wrapper 调用 API
    3. forgejo POST /repos/{owner}/{repo}/issues -d '{...}'
    4. 详见 references/issue-storage.md 第 3 节

响应:
  成功: 返回 Issue ID + 确认消息
  失败: 返回错误信息 (文件写入失败 / API 调用失败 / 认证缺失)
```

---

## 数据解析详细规则

> 完整 schema 定义见 [references/data-schema.md](./references/data-schema.md)

### 1. parse-upm

```
查找: Glob "**/unified-progress-management.md"
过滤: 文件内容必须包含 "UPMv2-STATE" 字符串
提取: 正则 /<!--\s*UPMv2-STATE\s*\n([\s\S]+?)\n-->/
解析: YAML → state 对象

输出字段:
  current_phase   → phase-banner 标题
  phase_status    → status badge (in_progress / completed / blocked)
  kpi.*           → KPI 卡片 (名称从 key 转换: paying_users → Paying Users)
  currentCycle    → 周期进度条 (completed_tasks / total_tasks * 100)
  risks[]         → 风险列表 (severity 颜色编码)

未找到时: phase 显示 "未配置", KPI 区域显示空状态提示
```

### 2. parse-stories

```
扫描: Glob "docs/requirements/user-stories/*.md"
ID: 从文件名提取 /^(US-\d+)/
标题: 第一个 # 标题行
Status: 按优先级 → frontmatter > Markdown 引用块 > 默认 pending
  引用块正则: /\*\*Status\*\*:\s*(\w+)/
Priority: 按优先级 → frontmatter > Markdown 引用块 > 默认 P3
  引用块正则: /\*\*Priority\*\*:\s*(\w+)/

三列映射:
  done | completed | closed         → Done
  in_progress | active | doing      → In Progress
  pending | todo | open | planned   → TODO

未找到时: 三列均为空，显示空状态提示
```

### 3. parse-openspec

```
活跃: Glob "openspec/changes/*/proposal.md"
归档: Glob "openspec/archive/*/proposal.md"

每个 proposal.md 提取:
  ID:     目录名
  Title:  第一个 # 标题
  Status: 引用块 />\s*\*\*Status\*\*:\s*(.+)/  (归档强制 "Archived")
  Level:  引用块 />\s*\*\*Level\*\*:\s*(.+)/
  Created: 引用块 />\s*\*\*Created\*\*:\s*(.+)/
  Parent:  引用块 />\s*\*\*Parent Story\*\*:\s*\[(.+?)\]/

耗时计算 (仅归档):
  归档日期 = 目录名前 10 字符 (YYYY-MM-DD 格式)
  duration_days = 归档日期 - Created 日期
  avg_duration = sum(duration_days) / count(有效记录)

未找到时: 表格为空，计数显示 0
```

### 4. parse-audit

```
扫描: Glob ".aria/audit-reports/*.md"

每个文件提取 YAML frontmatter (--- ... ---):
  checkpoint: string
  mode: string (convergence | challenge)
  rounds: number
  converged: string → 取第一个单词作为布尔值
  timestamp: string (ISO 8601)
  context: string
  agents: [string]

verdict 推导:
  converged == "true"  → PASS
  converged == "false" → REVISE

排序: 按 timestamp 降序
展示: 最近 5 条

未找到时: 表格为空，显示"暂无审计记录"
```

### 5. parse-benchmark

```
查找: Glob "aria-plugin-benchmarks/ab-results/*/summary.yaml"
选取: 按目录名日期排序，取最新一个

提取 overall 区块:
  total_skills, with_better, mixed, equal, without_better
  avg_delta, with_skill_win_rate

提取 results 区块:
  每个 skill 的 delta_pass_rate + verdict
  按 delta 降序排序，取 top 5 展示

未找到时: 所有数值显示 0，chips 区域显示空状态
```

---

## HTML 片段生成规则

### KPI 卡片

```html
<!-- 每个 KPI 生成一个 -->
<div class="kpi-card">
  <div class="kpi-label">{KPI_NAME}</div>
  <div class="kpi-value">{VALUE}</div>
  <div class="kpi-target">Target: {TARGET}</div>
  <div class="kpi-progress">
    <div class="kpi-progress-fill" style="width:{PCT}%; background:{COLOR}"></div>
  </div>
</div>

颜色规则: pct >= 80 → accent-green, >= 50 → accent-yellow, < 50 → accent-red
```

### Story 卡片

```html
<div class="story-card">
  <div class="story-id">{ID}</div>
  <div class="story-title">{TITLE}</div>
  <span class="story-priority {PRIORITY_CLASS}">{PRIORITY}</span>
</div>

PRIORITY_CLASS: HIGH → high, MEDIUM → medium, LOW/P2/P3 → low
```

### Spec 表格

```html
<table class="spec-table">
  <thead>
    <tr><th>Name</th><th>Status</th><th>Level</th><th>Duration</th><th>Story</th></tr>
  </thead>
  <tbody>
    <!-- 活跃 Specs 在前，归档 Specs 在后 -->
    <tr>
      <td class="spec-name">{ID}</td>
      <td><span class="spec-status {STATUS_CLASS}">{STATUS}</span></td>
      <td>{LEVEL}</td>
      <td class="spec-duration">{DURATION} days</td>
      <td>{PARENT_STORY}</td>
    </tr>
  </tbody>
</table>

STATUS_CLASS: Approved → approved, Draft → draft, Archived → archived, In Review → in-review
归档 Spec 的 duration 显示天数; 活跃 Spec 显示 "--"
```

### Audit 表格

```html
<table class="audit-table">
  <thead>
    <tr><th>Checkpoint</th><th>Verdict</th><th>Rounds</th><th>Mode</th><th>Date</th></tr>
  </thead>
  <tbody>
    <tr>
      <td class="audit-checkpoint">{CHECKPOINT}</td>
      <td class="{VERDICT_CLASS}">{VERDICT}</td>
      <td>{ROUNDS}</td>
      <td>{MODE}</td>
      <td>{DATE}</td>
    </tr>
  </tbody>
</table>

VERDICT_CLASS: PASS → verdict-pass, REVISE → verdict-revise
```

### Benchmark Skill Chips

```html
<span class="skill-chip">
  {SKILL_NAME} <span class="delta">{+DELTA}</span>
</span>

delta == 0 时添加 class "zero"
```

### Risks Section

```html
<!-- 仅在 risks 非空时渲染此 section -->
<div class="section">
  <div class="section-header">
    <span class="section-title">Risks</span>
    <span class="section-badge">{RISK_COUNT} active</span>
  </div>
  <div class="risk-list">
    <div class="risk-item">
      <span class="risk-severity {SEVERITY}"></span>
      <span class="risk-desc">{DESCRIPTION}</span>
      <span class="risk-status {STATUS}">{STATUS}</span>
    </div>
  </div>
</div>
```

### 空状态

```html
<div class="empty-state">
  <div class="empty-icon">--</div>
  <div>{MESSAGE}</div>
</div>

各区块的空状态消息:
  UPM:       "No UPM document found. Run progress-updater to initialize."
  Stories:   "No user stories found in docs/requirements/user-stories/"
  Specs:     "No OpenSpec found in openspec/"
  Audits:    "No audit reports found in .aria/audit-reports/"
  Benchmark: "No AB benchmark results found in aria-plugin-benchmarks/"
```

---

## 项目名称获取

```yaml
优先级:
  1. .aria/config.json → dashboard.project_name (如存在)
  2. Git remote URL 提取: git remote get-url origin → 取最后一段
     例: git@github.com:10CG/Aria.git → "Aria"
  3. 当前目录名: basename $(pwd)
```

---

## 配置 (可选)

读取 `.aria/config.json` 中的 `dashboard` 区块:

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `dashboard.project_name` | (auto-detect) | 覆盖项目名称 |
| `dashboard.output_path` | `.aria/dashboard/index.html` | 输出文件路径 |
| `dashboard.issue_backend` | `"git"` | Issue 存储后端: `git` / `github` / `forgejo` |
| `dashboard.issue_repo` | `""` | API 模式目标仓库，格式 `owner/repo` |
| `dashboard.issue_api_url` | `""` | Forgejo 自建实例 API 根地址，GitHub 留空 |

配置缺失时使用默认值，无需 config.json 即可运行。

### Issue 后端切换示例

```json
// Git 原生 (默认, 无需配置)
{
  "dashboard": {
    "issue_backend": "git"
  }
}

// GitHub Issues
{
  "dashboard": {
    "issue_backend": "github",
    "issue_repo": "10CG/aria-plugin"
  }
}
// 需设置: export ARIA_GITHUB_TOKEN=ghp_xxxx

// Forgejo 自建
{
  "dashboard": {
    "issue_backend": "forgejo",
    "issue_repo": "10CG/Aria",
    "issue_api_url": "https://git.example.com/api/v1"
  }
}
// 需设置: export ARIA_FORGEJO_TOKEN=xxxx
```

完整字段说明见 [references/issue-storage.md](./references/issue-storage.md) 第 5 节。

---

## 输出示例

```
Dashboard generated successfully.

  Output:  .aria/dashboard/index.html
  Data sources:
    UPM:        Phase 2: Growth (in_progress)
    Stories:    5 total (2 TODO, 1 WIP, 2 Done)
    OpenSpec:   1 active, 36 archived (avg 5.2 days)
    Audits:     1 report (latest: post_spec REVISE)
    Benchmark:  28 skills tested, avg delta +0.56

  Opening in browser...
```

---

## 参考

- [Data Schema Reference](./references/data-schema.md) -- 完整解析规则和输出格式
- [HTML Template](./templates/dashboard.html) -- 单文件自包含模板 (含 Issue 表单)
- [Issue Storage Design](./references/issue-storage.md) -- Issue 存储适配器设计 (格式/状态机/API)
- [Deploy Guide](./references/deploy-guide.md) -- 部署指南 (静态/Git 服务/CI 集成)
- [proposal.md](../../../openspec/changes/aria-dashboard/proposal.md) -- 功能规范
