# Dashboard Parse Rules

> 完整 input schema 定义见 [data-schema.md](./data-schema.md)。本文档聚焦 **解析逻辑** — 从 5 类输入数据源映射到 dashboard 内部模型。

## 1. parse-upm

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

## 2. parse-stories

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

## 3. parse-openspec

```
活跃: Glob "openspec/changes/*/proposal.md"
归档: Glob "openspec/archive/*/proposal.md"

每个 proposal.md 提取:
  ID:     目录名
  Title:  第一个 # 标题
  Status: 引用块 />\s*\*\*Status\*\*:\s*(.+)/  (归档强制 "Archived")
  Level:  引用块 />\s*\*\*Level\*\*:\s*(.+)/
  Created: 见下方 fallback chain
  Parent:  引用块 />\s*\*\*Parent Story\*\*:\s*\[(.+?)\]/

# 2026-04-23 修复 #23 Major 1 — Minor 4-9 延期到 v1.17.x
Created 日期 fallback chain (依次尝试, 第一个命中即返回):
  1. 引用块 />\s*\*\*Created\*\*:\s*(\d{4}-\d{2}-\d{2})/
  2. 文件内任意位置 Created 日期: /\*\*Created\*\*:\s*(\d{4}-\d{2}-\d{2})/
  3. git log --follow --diff-filter=A --format=%aI <proposal.md 路径>
     → 取输出首行, 截取前 10 字符 (YYYY-MM-DD)
  4. 归档目录名前缀 YYYY-MM-DD (仅适用于 archive/ 条目)
     → 同一目录名已用于 archived_date, Created 取相同值时 duration = 0 days
  5. null → 显示 "—" (保持原有行为)

耗时计算 (仅归档):
  archived_date = 目录名前 10 字符 (YYYY-MM-DD 格式)
  created_date  = 以上 fallback chain 得出
  duration_days = (archived_date - created_date).days
  仅当 archived_date 与 created_date 均非 null 时计算; 否则显示 "—"
  avg_duration  = sum(duration_days) / count(有效记录)

未找到时: 表格为空，计数显示 0
```

## 4. parse-audit

```
扫描: Glob ".aria/audit-reports/*.md"

主路径 — 每个文件提取 YAML frontmatter (--- ... ---):
  checkpoint: string
  mode: string (convergence | challenge)
  rounds: number
  converged: string → 取第一个单词作为布尔值
  timestamp: string (ISO 8601)
  context: string
  agents: [string]
  verdict: string (可选, audit-engine 规范输出字段)

Fallback 路径 — frontmatter 缺失时 (Forgejo Issue #126 兼容旧报告, 2026-05-28):
  扫描文件前 30 行的 markdown header pattern:
    `**Verdict**:` / `**verdict**:` / `^Verdict:`  → verdict 字段
    `**Date**:` / `**Timestamp**:` / `^Date:`       → timestamp 字段
    `**Round**:` / `**Rounds**:` / `^Round`         → rounds 字段
    `**Mode**:` / `^Mode:`                          → mode 字段
    `**Checkpoint**:` / `^Checkpoint:`              → checkpoint 字段
    `**Converged**:` / `^Converged:`                → converged 字段
    (字段未匹配时填 null; checkpoint 缺失时从文件名前缀 fallback, e.g. `post_spec-R1-...md` → `post_spec`)
    (rounds 缺失时从文件名 `R{N}` 段 fallback)
    (agents 缺失时从文件名 `-{agent_role}.md` 后缀 fallback)
    (timestamp 缺失时退回 file mtime)
  显式标记 `_source: "frontmatter" | "markdown_fallback" | "filename_fallback"` 供 UI 加 badge 提示数据完整度

新报告 (2026-05-28+) 由 audit-engine 强制 frontmatter, fallback 主要服务 Issue #126 之前生成的旧报告 (实测 42/105 无 frontmatter)。

# 2026-04-23 修复 #23 Major 2 — Minor 4-9 延期到 v1.17.x
verdict 解析优先级 (先读 frontmatter 显式字段, 再做 fallback 推导):
  1. 若 frontmatter 存在 `verdict:` 字段, 直接使用其值
  2. 否则从 converged 推导:
       converged == "true"  → PASS
       converged == "false" → REVISE

verdict CSS class 映射 (规范化):
  PASS                  → verdict-pass    (绿色)
  PASS_WITH_* (任意后缀) → verdict-warning (黄色, 新增)
    涵盖: PASS_WITH_WARNINGS / PASS_WITH_POLISH / PASS_WITH_MINOR / 未来扩展
    匹配规则: /^PASS_WITH_/i
  FAIL / REVISE         → verdict-revise  (红色)
  未知值                 → verdict-neutral (灰色, 新增) 避免"未知=失败"误导

排序: 按 timestamp 降序
展示: 最近 5 条

未找到时: 表格为空，显示"暂无审计记录"
```

## 5. parse-benchmark

```
查找 (跨两种格式取最新; 详细 schema 见 [data-schema.md](./data-schema.md) §5):
  (a) Glob "aria-plugin-benchmarks/ab-results/*/benchmark.json"  (新格式, /skill-creator 标准产出)
  (b) Glob "aria-plugin-benchmarks/ab-results/*/summary.yaml"    (旧格式, 向后兼容)
选取: 合并两个 glob 结果, 按目录名日期排序，取最新一个

新格式 (benchmark.json, 优先) — 字段映射:
  metadata.skill_name           → skill 名
  metadata.timestamp[:10]       → date (YYYY-MM-DD)
  configurations                → ["pre-fix"/"without_skill", "post-fix"/"with_skill"] (单 skill 双 config)
  runs[?config in {"with_skill","post-fix"}].pass_rate      → with_skill_pass_rate
  runs[?config in {"without_skill","pre-fix"}].pass_rate    → without_skill_pass_rate
  delta.pass_rate (or computed)                              → delta_pass_rate
  delta.verdict (or computed by threshold)                   → verdict
  → 包装为 single-skill summary (total_skills=1) 兜底; 若多 skill, repeat per skill_name

旧格式 (summary.yaml, 向后兼容):
  overall 区块: total_skills, with_better, mixed, equal, without_better, avg_delta, with_skill_win_rate
  results 区块: 每个 skill 的 delta_pass_rate + verdict

通用提取:
  按 delta 降序排序，取 top 5 展示

未找到时: 所有数值显示 0，chips 区域显示空状态
```
