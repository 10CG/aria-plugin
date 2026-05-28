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

4 步: Step 1 数据收集 (扫描 5 种数据源 UPM/User Stories/OpenSpec/Audit Reports/AB Benchmark, 容错独立) → Step 2 HTML 生成 (模板 `${SKILL_DIR}/templates/dashboard.html` + `{{PLACEHOLDER_NAME}}` 替换 + 动态片段循环) → Step 2.5 Issue 表单注入 (静态 / web 服务双模) → Step 3 输出 (写 `.aria/dashboard/index.html` + 跨平台浏览器打开) → Step 4 Issue 存储 (web 模式 git / GitHub API / Forgejo API 三 backend)。

**完整 Step-by-Step 流程 (数据源 glob + 提取正则 + 字段映射 / 模板占位符 / Issue 表单字段 / 输出路径 / 3 个 issue backend 详细)**: 见 [references/execution-flow.md](./references/execution-flow.md)。

---

## 数据解析详细规则

5 个 parser (1) parse-upm / (2) parse-stories / (3) parse-openspec / (4) parse-audit / (5) parse-benchmark, 分别从 UPM block / User Stories / OpenSpec proposals / `.aria/audit-reports/*.md` (frontmatter + markdown-fallback) / `aria-plugin-benchmarks/ab-results/*/` (新 benchmark.json + 旧 summary.yaml 双格式) 5 类数据源映射到 dashboard 内部模型。

**完整解析逻辑 (含正则 / fallback chain / verdict CSS class 映射 / 字段映射规则)**: 见 [references/parse-rules.md](./references/parse-rules.md)。

**输入数据 schema (5 类原始数据格式定义)**: 见 [references/data-schema.md](./references/data-schema.md)。

---

## HTML 片段生成规则

7 类模板片段: **KPI 卡片** (4 子元素 + pct 阈值染色 green/yellow/red) / **Story 卡片** (id+title+priority-class) / **Spec 表格** (5 列, status-class 映射 4 档) / **Audit 表格** (5 列, verdict-class 4 档含 PASS_WITH_*) / **Carry-forward 区块** (条件渲染, 4 个数据源合并去重) / **Benchmark Skill Chips** (delta 显示 + zero class) / **Risks Section** (severity + status 双 class) / **空状态** (5 个数据源各自 message)。

**完整 HTML 模板 + CSS class 映射规则 + 占位符列表 + 数据源 schema**: 见 [references/html-templates.md](./references/html-templates.md)。

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
