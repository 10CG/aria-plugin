# Data Schema Reference — aria-dashboard

> **版本**: 1.0.0
> **用途**: 定义 5 个解析器的输入路径、提取规则、输出格式和容错策略

---

## 通用容错规则

| 场景 | 行为 |
|------|------|
| 目标目录不存在 | 返回空数据，对应区块显示"未配置" |
| 文件存在但内容为空 | 同上 |
| YAML/frontmatter 解析失败 | 跳过该条目，其余正常输出 |
| 字段缺失 | 使用默认值（见各解析器定义） |

**原则**: 任何单一数据源的缺失都不应阻止看板生成。看板必须在"零数据"到"全数据"的连续谱上都能正确渲染。

---

## 1. parse-upm (项目进度总览)

### 输入路径

按优先级查找（命中即停止）:

```
1. docs/project-planning/unified-progress-management.md
2. {module}/docs/project-planning/unified-progress-management.md
   (module = mobile | backend | shared | standards)
```

使用 Glob 模式 `**/unified-progress-management.md` 搜索，取第一个包含 `UPMv2-STATE` 标记的文件。

### 提取规则

UPM 文档中包含 HTML 注释形式的机读 YAML 区块:

```
<!-- UPMv2-STATE
state:
  stateToken: "..."
  currentPhase: "Phase 2: Growth"
  phaseStatus: "in_progress"
  kpi:
    paying_users: 5
    mrr_usd: 500
    target_paying_users: 10
    target_mrr_usd: 1000
  currentCycle:
    number: 3
    total_tasks: 8
    completed_tasks: 5
  risks:
    - id: R1
      description: "..."
      severity: high
      status: mitigating
  completedTasks:
    - id: T1
      spec: "feature-x"
      status: done
      completedDate: "2026-03-20"
-->
```

**提取正则**: `<!--\s*UPMv2-STATE\s*\n([\s\S]+?)\n-->`

**YAML 解析**: 提取 match[1]，按 YAML 语法解析（注意缩进敏感）。

### 输出格式

```yaml
upm:
  found: true
  state_token: string
  current_phase: string       # 例: "Phase 2: Growth"
  phase_status: string        # in_progress | completed | blocked
  kpi:
    - name: string            # KPI 名称 (从 key 转换)
      value: number
      target: number
  cycle:
    number: number
    total_tasks: number
    completed_tasks: number
    completion_pct: number    # 计算值: completed / total * 100
  risks:
    - id: string
      description: string
      severity: string        # critical | high | medium | low
      status: string          # open | mitigating | resolved
  completed_tasks:
    - id: string
      spec: string
      completed_date: string
```

### 默认值 (UPM 未找到时)

```yaml
upm:
  found: false
  current_phase: "未配置"
  phase_status: "unknown"
  kpi: []
  cycle: { number: 0, total_tasks: 0, completed_tasks: 0, completion_pct: 0 }
  risks: []
  completed_tasks: []
```

---

## 2. parse-stories (User Story 三列看板)

### 输入路径

```
docs/requirements/user-stories/*.md
```

### 提取规则

每个 `.md` 文件提取:

1. **ID**: 从文件名提取，正则 `^(US-\d+)` (例: `US-001.md` -> `US-001`)
2. **Title**: 从第一个 `# ` 标题提取，正则 `^#\s+(.+)$` (multiline)
3. **Status**: 按优先级查找:
   - frontmatter `status` 字段 (如果有 `---` ... `---` 区块)
   - Markdown 引用块: `> **Status**: done` 正则 `\*\*Status\*\*:\s*(\w+)`
   - 如都无，默认 `pending`
4. **Priority**: 按优先级查找:
   - frontmatter `priority` 字段
   - Markdown 引用块: `> **Priority**: HIGH` 正则 `\*\*Priority\*\*:\s*(\w+)`
   - 默认 `P3`

### 状态归一化与三列映射

```yaml
status 值 → 列名:
  done | completed | closed       → "已完成"
  in_progress | active | doing    → "进行中"
  pending | todo | open | planned → "TODO"
  其他值                          → "TODO" (默认)
```

### 输出格式

```yaml
stories:
  found: true
  total: number
  items:
    - id: string           # US-001
      title: string        # 增强工作流自动化
      status: string       # done | in_progress | pending (归一化后)
      priority: string     # HIGH | MEDIUM | LOW | P0-P3
      column: string       # 已完成 | 进行中 | TODO
  columns:
    todo: [Story]
    in_progress: [Story]
    done: [Story]
```

### 默认值

```yaml
stories:
  found: false
  total: 0
  items: []
  columns: { todo: [], in_progress: [], done: [] }
```

---

## 3. parse-openspec (OpenSpec 列表 + 耗时)

### 输入路径

```
活跃 Specs:  openspec/changes/*/proposal.md
归档 Specs:  openspec/archive/*/proposal.md
```

### 提取规则

每个 `proposal.md` 提取:

1. **ID**: 目录名 (例: `aria-dashboard`, `2026-03-21-readme-i18n-upgrade`)
2. **Title**: 从第一个 `# ` 标题提取
3. **Status**: 从 Markdown 引用块提取:
   - 正则 `>\s*\*\*Status\*\*:\s*(.+)` (例: `> **Status**: Approved`)
   - 归档目录中的 Spec 强制标记为 `Archived`
4. **Level**: 从引用块提取:
   - 正则 `>\s*\*\*Level\*\*:\s*(.+)` (例: `> **Level**: Full (Level 3 Spec)`)
5. **Created**: 从引用块提取:
   - 正则 `>\s*\*\*Created\*\*:\s*(.+)` (例: `> **Created**: 2026-04-02`)
6. **Parent Story**: 从引用块提取:
   - 正则 `>\s*\*\*Parent Story\*\*:\s*\[(.+?)\]`

### 耗时计算 (归档 Specs)

归档目录名格式为 `YYYY-MM-DD-{name}`。提取目录名前缀作为归档日期。

```
耗时(天) = 归档日期 - 创建日期 (Created 字段)
```

如果 `Created` 字段缺失，耗时显示 `--`。

### 输出格式

```yaml
specs:
  found: true
  active_count: number
  archived_count: number
  items:
    - id: string
      title: string
      status: string         # Approved | Draft | In Review | Archived
      level: string          # Level 1 | Level 2 | Level 3
      created: string        # ISO date
      archived: string       # ISO date (仅归档 Spec)
      duration_days: number  # 耗时天数 (仅归档 Spec，无法计算时为 null)
      parent_story: string   # 例: US-005
      is_archived: boolean
  avg_duration_days: number  # 所有可计算耗时的归档 Spec 的平均值
```

### 默认值

```yaml
specs:
  found: false
  active_count: 0
  archived_count: 0
  items: []
  avg_duration_days: 0
```

---

## 4. parse-audit (审计报告历史)

### 输入路径

```
.aria/audit-reports/*.md
```

### 提取规则

每个 `.md` 文件从 YAML frontmatter (`---` ... `---`) 提取:

```yaml
checkpoint: string     # post_spec | post_implementation | pre_merge | ...
mode: string           # convergence | challenge
rounds: number         # 审计轮次
converged: string      # true | false (可能带括号说明)
timestamp: string      # ISO 8601
context: string        # 被审计内容路径
agents: [string]       # 参与 Agent 列表
```

**converged 解析**: 值可能是 `true`、`false`、或 `false (1 PASS / 3 REVISE, trend converging)` 等。
提取方式: 取第一个单词 (`true` 或 `false`) 作为布尔值。

**verdict 推导**:
- `converged` 为 `true` -> verdict = `PASS`
- `converged` 为 `false` -> verdict = `REVISE`

### 输出格式

```yaml
audits:
  found: true
  total: number
  items:
    - checkpoint: string
      mode: string
      rounds: number
      converged: boolean
      verdict: string      # PASS | REVISE
      timestamp: string
      context: string
      agents: [string]
  # 按 timestamp 降序排列，取最近 5 条
```

### 默认值

```yaml
audits:
  found: false
  total: 0
  items: []
```

---

## 5. parse-benchmark (AB 基准测试摘要)

### 输入路径

按优先级查找（命中即停止）:

```
1. aria-plugin-benchmarks/ab-results/latest/summary.yaml
2. aria-plugin-benchmarks/ab-results/*/summary.yaml (取最近日期)
```

使用 Glob `aria-plugin-benchmarks/ab-results/*/summary.yaml` 搜索，按文件名日期排序取最新。

### 提取规则

summary.yaml 是标准 YAML 格式:

```yaml
date: "2026-03-13"
skills_tested: 28

results:
  skill-name:
    with_skill_pass_rate: 1.0
    without_skill_pass_rate: 0.42
    delta_pass_rate: 0.58
    verdict: "WITH_BETTER"

overall:
  total_skills: 28
  with_better: 24
  mixed: 1
  equal: 3
  without_better: 0
  avg_delta: 0.56
  with_skill_win_rate: 0.86
```

提取 `overall` 区块和 `results` 中每个 skill 的 verdict 统计。

### 输出格式

```yaml
benchmark:
  found: true
  date: string
  total_skills: number
  with_better: number
  mixed: number
  equal: number
  without_better: number
  avg_delta: number
  win_rate: number           # with_skill_win_rate
  top_skills:                # delta 最高的前 5 个
    - name: string
      delta: number
      verdict: string
  bottom_skills:             # delta 最低的前 3 个 (含 EQUAL)
    - name: string
      delta: number
      verdict: string
```

### 默认值

```yaml
benchmark:
  found: false
  date: "--"
  total_skills: 0
  with_better: 0
  mixed: 0
  equal: 0
  without_better: 0
  avg_delta: 0
  win_rate: 0
  top_skills: []
  bottom_skills: []
```

---

## 汇总数据结构

所有解析器的输出汇聚为一个完整数据对象，用于填充 HTML 模板:

```yaml
dashboard_data:
  project_name: string        # 从 git remote 或目录名获取
  generated_at: string        # ISO 8601 时间戳
  generator_version: string   # "1.0.0"
  upm: { ... }               # parse-upm 输出
  stories: { ... }           # parse-stories 输出
  specs: { ... }             # parse-openspec 输出
  audits: { ... }            # parse-audit 输出
  benchmark: { ... }         # parse-benchmark 输出
```

---

## HTML 模板占位符映射

| 占位符 | 数据来源 | 说明 |
|--------|----------|------|
| `{{PROJECT_NAME}}` | `dashboard_data.project_name` | 项目名称 |
| `{{GENERATED_AT}}` | `dashboard_data.generated_at` | 生成时间 |
| `{{PHASE_NAME}}` | `upm.current_phase` | 当前阶段名 |
| `{{PHASE_STATUS}}` | `upm.phase_status` | 阶段状态 |
| `{{KPI_HTML}}` | `upm.kpi[]` 循环生成 | KPI 卡片 HTML |
| `{{CYCLE_NUMBER}}` | `upm.cycle.number` | 当前周期号 |
| `{{CYCLE_PCT}}` | `upm.cycle.completion_pct` | 周期完成百分比 |
| `{{RISKS_HTML}}` | `upm.risks[]` 循环生成 | 风险列表 HTML |
| `{{STORIES_TODO_HTML}}` | `stories.columns.todo[]` 循环 | TODO 列卡片 |
| `{{STORIES_WIP_HTML}}` | `stories.columns.in_progress[]` 循环 | 进行中列卡片 |
| `{{STORIES_DONE_HTML}}` | `stories.columns.done[]` 循环 | 已完成列卡片 |
| `{{STORIES_TOTAL}}` | `stories.total` | Story 总数 |
| `{{SPECS_HTML}}` | `specs.items[]` 循环生成 | Spec 行 HTML |
| `{{SPECS_ACTIVE_COUNT}}` | `specs.active_count` | 活跃 Spec 数 |
| `{{SPECS_ARCHIVED_COUNT}}` | `specs.archived_count` | 归档 Spec 数 |
| `{{SPECS_AVG_DURATION}}` | `specs.avg_duration_days` | 平均耗时 |
| `{{AUDITS_HTML}}` | `audits.items[]` 循环生成 | 审计行 HTML |
| `{{AUDITS_TOTAL}}` | `audits.total` | 审计报告总数 |
| `{{BENCHMARK_DATE}}` | `benchmark.date` | 测试日期 |
| `{{BENCHMARK_TOTAL}}` | `benchmark.total_skills` | 测试技能数 |
| `{{BENCHMARK_AVG_DELTA}}` | `benchmark.avg_delta` | 平均 delta |
| `{{BENCHMARK_WIN_RATE}}` | `benchmark.win_rate` | 赢率 |
| `{{BENCHMARK_TOP_HTML}}` | `benchmark.top_skills[]` 循环 | Top Skills HTML |
| `{{BENCHMARK_SUMMARY_HTML}}` | 综合统计 | 分类汇总 HTML |
