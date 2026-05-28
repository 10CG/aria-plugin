# Dashboard HTML Fragment Generation Rules

> 各模板片段的 HTML 结构 + 占位符规范 + 颜色/CSS class 映射。从 SKILL.md §HTML 片段生成规则 提取 (iter-2, 2026-05-28)。

## KPI 卡片

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

## Story 卡片

```html
<div class="story-card">
  <div class="story-id">{ID}</div>
  <div class="story-title">{TITLE}</div>
  <span class="story-priority {PRIORITY_CLASS}">{PRIORITY}</span>
</div>

PRIORITY_CLASS: HIGH → high, MEDIUM → medium, LOW/P2/P3 → low
```

## Spec 表格

```html
<table class="spec-table">
  <thead>
    <tr><th>Name</th><th>Status</th><th>Level</th><th>Duration</th><th>Story</th></tr>
  </thead>
  <tbody>
    <!-- 活跃 Specs 在前, 归档 Specs 在后 -->
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

## Audit 表格

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

# 2026-04-23 修复 #23 Major 2 — Minor 4-9 延期到 v1.17.x
VERDICT_CLASS 映射:
  PASS          → verdict-pass    (绿色)
  PASS_WITH_*   → verdict-warning (黄色, 新增)
  FAIL / REVISE → verdict-revise  (红色)
  其他          → verdict-neutral (灰色, 新增)
```

## Carry-forward 区块

```html
<!-- 2026-04-23 修复 #23 Major 3 — Minor 4-9 延期到 v1.17.x -->
<!-- 仅在存在 carry-forward 数据时渲染; 否则整个 section 隐藏 (backward-compat) -->
<section class="carry-forward">
  <h2>Carry-forward (polish 流动)</h2>
  <div class="cf-group">
    <h3>{TARGET_RELEASE} 候选 ({COUNT} 条)</h3>
    <ul>
      <li>CF-{N}: {ITEM_TEXT} (源: {SOURCE}, {DATE})</li>
      ...
    </ul>
  </div>
  ...
</section>

数据源 (依次扫描, 合并去重):
  1. .aria/audit-reports/*.md frontmatter carry_forward: 字段 (列表)
     target_release 字段用于分组; 缺失时归入 "未指定版本"
  2. .aria/audit-reports/*.md body 中 "Carry-forward" H2/H3 章节下的列表项
  3. openspec/changes/*/proposal.md "Out of Scope" 章节列表项
     → 分组 key: proposal 目录名 + "(Active)"
  4. openspec/archive/*/proposal.md "Out of Scope" 章节列表项
     → 分组 key: proposal 目录名 + "(Archived)"

分组 / 排序: 按 target_release 字母升序; 同组内按来源时间升序

无数据时: section 完全隐藏 (display:none 或不生成 HTML)
占位符: {{CARRY_FORWARD_HTML}} (模板中标记注入点)
```

## Benchmark Skill Chips

```html
<span class="skill-chip">
  {SKILL_NAME} <span class="delta">{+DELTA}</span>
</span>

delta == 0 时添加 class "zero"
```

## Risks Section

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

## 空状态

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
