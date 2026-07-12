---
name: agent-router
description: |
  任务到 Agent 的智能路由器，根据任务类型、文件路径自动选择最合适的 Agent。

  使用场景：subagent-driver 需要为任务选择 Agent、不确定应该使用哪个 Agent
argument-hint: "[task-description]"
disable-model-invocation: false
user-invocable: false
context: fork
agent: general-purpose
allowed-tools: Read, Glob, Grep, Bash
---

# Agent Router (智能路由器)

> **版本**: 1.2.2 | **类型**: 路由器 (Agent 选择)
> **更新**: 2026-07-12 - 摘要表残余漂移对齐 #101 (architecture→backend-architect 0.85 / api-doc·llm·rag 0.95 / React Native·Flutter 0.95 [后两行 recon 新发现]) + 表级 canonical banner (ROUTING_RULES=SOT, 根治双写漂移); 前版 1.2.1 基线层语义补明 #99

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- 为任务自动选择合适的 Agent
- 不确定应该使用哪个专业 Agent
- 需要智能 Agent 匹配

**不使用场景**:
- 已明确知道使用哪个 Agent → 直接调用
- 简单通用任务 → 使用 general-purpose

---

## 核心功能

| 功能 | 说明 |
|------|------|
| **智能路由** | 根据任务特征自动匹配 Agent |
| **置信度评分** | 对每个匹配结果评分 (0-1) |
| **项目级 capability 路由** | 扫描 `.aria/agents/` 项目级 Agent, 按 capabilities 匹配进入 auto/recommend (v1.2.0, ROUTING_RULES §CAP) |
| **多模式支持** | 自动 / 推荐 / 手动三种模式 |
| **用户覆盖** | 允许用户显式指定 Agent |
| **Fallback** | 无匹配时使用 general-purpose |

---

## 路由模式

### 自动模式 (auto)

```yaml
行为: 两段式裁决 (v1.2.0, 详见 §执行流程 step 5 + ROUTING_RULES §CAP-4):
  Stage 1 基线裁决 (FP/TT/技术栈/关键词, 既有规则含 threshold 与 <0.1 近分降级)
  Stage 2 项目级 CAP 挑战 (仅当存在项目级 CAP 候选):
    R-a 决定性直派 (specialist 全命中) / R-b 有序四分支数值裁决
条件: 用户未显式指定 Agent

示例:
  任务: "实现用户登录 API" (无项目级候选)
  路由结果: backend-architect (confidence: 0.95, decision_path: baseline)
  动作: 直接使用 backend-architect
```

### 推荐模式 (recommend) - 默认

```yaml
行为: 展示 Top-3 Agent 供用户选择
触发: confidence < threshold 或有多个候选
条件: 用户未显式指定 Agent

示例:
  任务: "优化数据库查询"
  路由结果:
    [1] backend-architect (0.85) - 后端架构优化
    [2] qa-engineer (0.60) - 性能分析
    [3] general-purpose (0.50) - 通用任务兜底
  动作: 询问用户选择
```

### 手动模式 (manual)

```yaml
行为: 使用用户显式指定的 Agent
触发: 用户在任务中指定
优先级: 最高 (覆盖自动和推荐)

示例:
  任务: "用 backend-architect 实现用户认证"
  路由结果: backend-architect (手动指定)
  动作: 直接使用 backend-architect
```

---

## 路由规则

> 本节为插件级基线四类规则 (文件路径/任务类型/技术栈/关键词) 摘要。**项目级 capability 匹配 (§CAP: required_caps 推断 / 评分公式 / 两段式决策 / 同名得分归属 / recommend 混排)** 见 [ROUTING_RULES.md §CAP](./ROUTING_RULES.md)。
>
> **Canonical banner (v1.2.2, #101)**: 本节摘要表的目标 Agent 与置信度以
> [ROUTING_RULES.md](./ROUTING_RULES.md) 为 **canonical SOT**, 摘要仅便于扫读;
> 与 canonical 冲突时一律以 canonical 为准。改路由规则**只改 ROUTING_RULES**,
> 摘要表随之对齐 (摘要表历史上已两次漂移: #99 frontend 行 / #101 六行, 皆双写所致)。

### 文件路径匹配

| 路径模式 | 目标 Agent | 置信度 |
|----------|-----------|--------|
| `backend/**/*` | backend-architect | 0.90 |
| `api/**/*` | backend-architect | 0.95 |
| `database/**/*` | backend-architect | 0.90 |
| `mobile/**/*` | mobile-developer | 0.95 |
| `*.dart` | mobile-developer | 0.90 |
| `frontend/**/*` | frontend-developer (注) | 0.85 |
| `docs/**/*` | knowledge-manager | 0.85 |
| `ai/**/*` | ai-engineer | 0.90 |

> **注 (v1.2.1, #99)**: `frontend/**/*` 行此前写 `general-purpose 0.70`, 与 canonical
> ROUTING_RULES FP-022 (`frontend-developer 0.85`) 冲突, 现对齐。`frontend-developer`
> 非插件内置 Agent (不在 §Agent 能力矩阵) — 胜出时按 §错误处理「Agent 不存在」回退
> `general-purpose`, 除非项目级 `.aria/agents/frontend-developer.md` 提供该 Agent
> (详见 ROUTING_RULES FP-022~025 注 1)。

### 任务类型匹配

| 任务类型 | 目标 Agent | 置信度 |
|----------|-----------|--------|
| `architecture` | backend-architect | 0.85 |
| `code-review` | qa-engineer | 0.95 |
| `ui-design` | ui-ux-designer | 0.90 |
| `legal` | legal-advisor | 0.95 |
| `api-doc` | api-documenter | 0.95 |
| `llm` / `rag` | ai-engineer | 0.95 |
| `tech-lead` / `planning` | tech-lead | 0.85 |

### 技术栈匹配

| 技术关键词 | 目标 Agent | 置信度 |
|-----------|-----------|--------|
| `React Native` | mobile-developer | 0.95 |
| `Flutter` | mobile-developer | 0.95 |
| `REST` / `GraphQL` | backend-architect | 0.85 |
| `vector` / `embedding` | ai-engineer | 0.90 |
| `OpenAPI` / `Swagger` | api-documenter | 0.90 |

---

## 输入参数

| 参数 | 必需 | 说明 | 默认值 |
|------|------|------|--------|
| `task` | ✅ | 任务描述 | - |
| `task_type` | ❌ | 任务类型。未传时自动推断: 以 TT 表「触发关键词」为唯一依据, task 文本词边界逐字命中 (非语义联想), 见 ROUTING_RULES §任务类型规则推断程序 (v1.2.1, #99) | 自动推断 |
| `files` | ❌ | 相关文件列表 | [] |
| `mode` | ❌ | 路由模式 | recommend |
| `threshold` | ❌ | 自动模式阈值; 比较取 `>=` (恰等合格, 见 ROUTING_RULES §threshold 比较语义, v1.2.1 #99) | 0.9 |
| `user_agent` | ❌ | 用户指定的 Agent | null |
| `required_caps` | ❌ | 显式任务需求标签 (taxonomy tag list, v1.2.0)。传入 → 跳过 L1/L2 推断直接采用 (归一失败值剔除+WARN), 见 ROUTING_RULES §CAP-1 | null (推断) |

---

## 输出格式

### 自动模式 (直接匹配)

```yaml
status: "auto_match"
agent: "backend-architect"
confidence: 0.95
reason: "任务涉及 API 设计，路径匹配 backend/**/*"
model: "sonnet"

# ── v1.2.0 additive 字段 (仅当 step 3e 实际执行时输出; 3e 被门控跳过或
#    .aria/agents/ 为空时, 输出 shape 完全等同 v1.1.x, 不含以下任何字段。
#    适用形态: auto_match 与 recommend **两种输出均携带**本块 decision 级字段 —
#    recommend 时 agent_source 改为逐候选条目携带 [§CAP-7], decision_path/
#    required_caps_trace/warnings 仍为顶层 decision 级) ──
agent_source: "plugin"            # "plugin" | "project" — 胜出者来源层
decision_path: "baseline"         # "R-a" | "R-b" | "baseline" (decision 级单值;
                                  #  赋值通则见 ROUTING_RULES §CAP-4;
                                  #  baseline + agent_source=project = 同名接管)
required_caps_trace:              # 推断轨迹 (可审计)
  explicit: false                 # 显式传参时 true (此时 l1/l2 为空)
  l1: [api-design]
  l2: []                          # [{tag, evidence}] 语义补充及其证据 token
  negated: []
off_taxonomy_tags: []             # 胜出者为项目级时: 其惰性标签提示 (owner 修标签)
warnings: []                      # 既有输出惯例 (如同名警告)
# manual / fallback 输出不含上述字段 (manual 不经 3e; fallback 恒 general-purpose)
```

### 推荐模式 (多候选)

```yaml
status: "recommend"
candidates:
  - rank: 1
    agent: "backend-architect"
    confidence: 0.85
    reason: "后端架构相关任务"
    model: "sonnet"

  - rank: 2
    agent: "qa-engineer"
    confidence: 0.60
    reason: "可能涉及性能分析"
    model: "sonnet"

  - rank: 3
    agent: "general-purpose"
    confidence: 0.50
    reason: "通用任务兜底"
    model: "sonnet"

user_select_required: true
```

### 手动模式 (用户指定)

```yaml
status: "manual"
agent: "mobile-developer"
confidence: 1.0
reason: "用户显式指定"
source: "user_override"
```

### 无匹配 (Fallback)

```yaml
status: "fallback"
agent: "general-purpose"
confidence: 0.0
reason: "无明确匹配规则"
fallback: true
```

---

## 执行流程

```yaml
路由流程:

  1. 解析输入:
     ├── 读取 task 描述
     ├── 读取 task_type (如有)
     ├── 读取 files 列表
     └── 检查 user_agent (手动指定)

  2. 手动模式检查:
     ├── if user_agent 存在:
     │   └── 返回手动模式结果
     └── else: 继续

  3. 规则匹配:
     ├── 3a 文件路径匹配 (FP)
     ├── 3b 任务类型匹配 (TT)
     ├── 3c 技术栈匹配
     ├── 3d 关键词匹配
     └── 3e 项目级 capability 匹配 (v1.2.0 新增, 主链默认步, 受配置门控):
         ├── 门控 (最先判定, 命中即整步不执行 — 含同名检测/吸收在内的一切 3e 逻辑):
         │   agent_router.plugin_only == true 或 scan_project_agents == false
         │   → 跳过 3e, 退化纯基线 (输出 shape 完全等同 v1.1.x, 不含 3e 新字段)
         ├── 扫描 .aria/agents/*.md (缓存与失效语义见 §项目级 Agent 发现「缓存」)
         ├── frontmatter 健壮性: capabilities 缺失/非 list/YAML parse 失败 → skip 该
         │   agent 不阻断; 空 list → 合法 (零命中)
         ├── 同名保护复合 (得分归属见 ROUTING_RULES §CAP-6): 池构建期先按名去重 —
         │   项目级替换插件级候选 + 输出警告; 幸存者吸收插件级按名命中的全部
         │   FP/TT/技术栈/关键词 confidence; agent_source 恒 = project
         ├── 读 capabilities, 经 capabilities-taxonomy.yaml 归一 (ROUTING_RULES §CAP-2)
         └── 按 ROUTING_RULES §CAP-3 评分产出项目级候选 (match_rate > 0 才产出,
             零命中不入池; 候选携带 match_rate/|matched|/|required_caps|/precision/
             off_taxonomy_tags)

  4. 置信度聚合:
     ├── 合并所有匹配结果 (基线候选 + 项目级 CAP 候选进同一候选池)
     ├── 侧别语义: B12 吸收候选凭吸收分归基线侧; 其 CAP 分录仅用于 recommend
     │   排序与 trace, 不参与 Stage 2 auto 挑战者遴选 (ROUTING_RULES §CAP-6)
     ├── 去重并排序
     └── 选择 Top-N

  5. 模式决策:
     ├── if mode == auto: 两段式 (ROUTING_RULES §CAP-4):
     │   ├── Stage 1 基线裁决: 基线侧候选 (含吸收分候选) 按既有规则得出
     │   │   baseline 决策 + baseline_top — 基线侧候选间差值 < 0.1 严格降级
     │   │   与 threshold 检查照旧 (无项目级候选时行为与 v1.1.x 一致)
     │   └── Stage 2 项目级 CAP 挑战 (仅当存在纯 CAP 项目级候选):
     │       R-a 决定性直派 → R-b 有序分支 (0)-(4), 含基线池空分支 → 采纳/直派/降级
     │       (auto 内部任何降级产出的 recommend 输出, 同样按 §CAP-7 混排)
     │
     ├── if mode == recommend:
     │   └── 返回 Top-3 推荐 (项目级候选按 §CAP-7 规则混排进入)
     │
     └── if mode == manual:
         └── 既有逻辑不变 (user_agent 显式指定时于 step 2 前置返回;
             未指定时等待指定 — 两形态均不经 3e 评分)

  6. 返回结果
```

---

## 与 subagent-driver 集成

```yaml
subagent-driver 调用流程:

  1. 接收任务列表
  2. for each task:
     a. 调用 agent-router
        ├── task: 任务描述
        ├── files: 相关文件
        └── mode: recommend (配置)

     b. 获取路由结果
        ├── auto: 直接使用
        ├── recommend: 询问用户
        ├── manual: 使用用户指定
        └── v1.2.0: 结果含 agent_source (plugin|project) — 项目级 Agent 胜出时
            subagent-driver 可据此填充 handoff-contract 预留字段 agent_source

     c. 启动 Fresh Subagent
        └── 使用选定 Agent

  3. 执行任务
  4. 任务间审查
  5. 4 选项完成
```

---

## 配置

### 项目级配置 (.claude/agent-router-config.json) — **legacy**

> **Legacy 标注 (v1.2.0)**: 本块为 v1.0.0 era 遗留配置面。**step 3e 门控与缓存的 3 个 key** (`scan_project_agents` / `plugin_only` / `cache_ttl_seconds`) 的 SOT 为 **`.aria/config.json` 的 `agent_router` 块** (见下方「项目级 Agent 发现 → 配置」); 既有 `confidence_threshold` / `max_candidates` / `default_mode` 等仍居本 legacy 块, 迁移不在 v1.2.0 范围。

```json
{
  "enabled": true,
  "default_mode": "recommend",
  "confidence_threshold": 0.9,
  "max_candidates": 3,
  "fallback_agent": "general-purpose"
}
```

### 任务级覆盖

```yaml
# detailed-tasks.yaml
tasks:
  - id: TASK-001
    description: "实现用户认证"
    agent: backend-architect  # 手动指定
    files:
      - backend/api/auth.js
```

---

## Agent 能力矩阵

> 下表为**插件级基线** Agent (静态)。**项目级 Agent** (`.aria/agents/*.md`) 为动态发现, 不在此表 — 其能力由各自 frontmatter `capabilities` 标签声明, 经 ROUTING_RULES §CAP 匹配参与路由。

| Agent | 擅长任务 | 模型 | 颜色 |
|-------|---------|------|------|
| general-purpose | 通用任务、复杂搜索 | sonnet | gray |
| knowledge-manager | 文档架构、AI-DDD | sonnet | blue |
| tech-lead | 架构决策、任务规划 | opus | red |
| qa-engineer | 代码审查、质量保证 | sonnet | yellow |
| context-manager | 上下文管理、多任务协调 | opus | cyan |
| ai-engineer | LLM 应用、RAG 系统 | opus | yellow |
| backend-architect | API 设计、微服务 | sonnet | green |
| mobile-developer | React Native、Flutter | sonnet | pink |
| api-documenter | OpenAPI、SDK 生成 | haiku | orange |
| legal-advisor | 法律文档、合规 | haiku | purple |
| ui-ux-designer | 界面设计、用户体验 | sonnet | purple |

---

## 使用示例

### 示例 1: 自动匹配

```yaml
输入:
  task: "实现用户登录 REST API"
  files: ["backend/api/auth.js"]
  mode: auto

输出:
  status: auto_match
  agent: backend-architect
  confidence: 0.95
  reason: "文件路径匹配 backend/**/*，包含 API 关键词"
```

### 示例 2: 推荐模式

```yaml
输入:
  task: "优化用户注册流程性能"
  files: ["backend/api/register.js", "database/schema.sql"]
  mode: recommend

输出:
  status: recommend
  candidates:
    - rank: 1
      agent: backend-architect
      confidence: 0.75
      reason: "后端相关文件和性能优化"

    - rank: 2
      agent: qa-engineer
      confidence: 0.65
      reason: "性能分析和优化"

    - rank: 3
      agent: general-purpose
      confidence: 0.50
      reason: "通用任务兜底"
```

### 示例 3: 手动指定

```yaml
输入:
  task: "用 tech-lead 规划系统重构"
  user_agent: tech-lead

输出:
  status: manual
  agent: tech-lead
  confidence: 1.0
  source: user_override
```

### 示例 4: 项目级 Agent R-a 决定性直派 (v1.2.0)

```yaml
前提: .aria/agents/database-specialist.md 存在
  (capabilities: [orm-migration, query-optimization, database-schema])

输入:
  task: "给 extraction_job.status 的 CHECK 约束加值, 写 Alembic migration, 同步模型"
  files: ["backend/models/extraction_job.py"]
  mode: auto
  required_caps: [orm-migration, database-schema]   # 显式传参 (或经 L1/L2 推断)

输出:
  status: auto_match
  agent: database-specialist
  confidence: 1.0                  # match_rate 2/2
  agent_source: project
  decision_path: R-a               # 全命中 + |req|>=2 + precision 2/3≈0.67 >= 0.5
                                   # (valid_caps=3, matched=2 — 分母为该 agent 全部
                                   #  taxonomy 内标签, 见 ROUTING_RULES §CAP-3)
  reason: "项目级 specialist 全命中 required_caps (R-a 决定性直派)"
  required_caps_trace: {explicit: true, l1: [], l2: [], negated: []}
  off_taxonomy_tags: []
  warnings: []
# 对比: v1.1.x 同输入会被 FP(backend/**) 0.90 短路直派 backend-architect,
# database-specialist 从不进候选池 (#153 发现 B, 已修复)
```

---

## 错误处理

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 无匹配规则 | 任务特征不符合任何规则 | 使用 general-purpose |
| Agent 不存在 | 指定的 Agent 无效 | 警告并回退到 general-purpose |
| 多高置信度 | 多个 Agent 置信度都 >= threshold | 降级到推荐模式 |
| 3e 扫描失败 (目录不可读) | 权限/IO 异常 | skip 3e 退化纯基线, WARN 不阻断 |
| 项目级 frontmatter 损坏 | capabilities 缺失/非 list/parse 失败 | skip 该 agent 不阻断; 空 list = 合法零命中 |
| 缓存写入失败 | 权限/磁盘/目录缺失 | mkdir -p 或 WARN + 直读 frontmatter, 不阻断 (§缓存) |
| required_caps 传参含无效值 | off-taxonomy/拼写错 | 剔除该值 + WARN, 余下继续 (§CAP-1) |

---

## 项目级 Agent 发现 (v1.2.0 主链接线; 机制引入于 v1.1.0)

### 机制

项目级 Agent 发现是 §执行流程 **step 3e 的主链默认步** (v1.2.0 起, 见上方执行流程; v1.1.0-v1.53.0 期间本段曾为文末孤儿描述, auto 路径从未真正执行 — #153 发现 B, 已修复): 扫描 `.aria/agents/` 目录, 项目级 Agent 经 capability 匹配 (ROUTING_RULES §CAP) 进入候选池并参与两段式 auto 裁决。

```
路由决策流程 (接线版):
  1. 加载插件级 Agent 列表 (aria/agents/*.md)
  2. step 3e: 扫描项目级 Agent 目录 (.aria/agents/*.md, 受配置门控)
  3. 合并: 项目级 CAP 候选与基线候选进同一候选池 (同名保护复合见 §CAP-6)
  4. 执行路由匹配: FP/TT/技术栈/关键词 (基线) + capabilities (项目级, §CAP)
  5. step 5 两段式裁决 → 输出 (含 agent_source / decision_path 等字段, 见 §输出格式)
```

**注意** (D4 rationale, 保留): 这是 **Skill 层的运行时行为**,不是 Plugin 层的静态注册。Claude Code Plugin 不会自动加载 `.aria/agents/` 中的 Agent,但 agent-router Skill 在执行时会读取它们的 description 和 capabilities。

### 缓存 (v1.2.0 per-file 语义)

- 缓存文件 `.aria/cache/project-agents.json`, schema:
  `last_full_scan` (int epoch seconds UTC, TTL 判定基准) + `files: [{path, mtime[纳秒精度, 文件系统支持时], size}, ...]`
- 主判: 每次 3e 对 `.aria/agents/*.md` 做 stat 集合比对, 任何差异 (增/删/改) → 重建缓存 + 更新 last_full_scan
- `cache_ttl_seconds` (配置, 默认 0): `>0` = 即使 stat 集合一致, now − last_full_scan 超 TTL 也强制重建 (对 stat 粒度漏检的时间兜底); `0` = 仅 stat 比对
- 已知残余窗口 (诚实标注): 同秒 (纳秒不可用时) + 字节数不变的原地编辑可能漏检 — 兜底 1: cache_ttl_seconds; 兜底 2: 强制刷新 (删除缓存文件)
- 写入健壮性: `.aria/cache/` 不存在 → mkdir -p; 写入失败 → WARN + 本次直读 frontmatter 不用缓存, 不阻断路由; tmp + rename 原子写; 旧 schema 缓存 (无 last_full_scan) → 视为失效直接重建

### 同名保护

如果项目级 Agent 与插件级 Agent 同名:
- 输出警告: `⚠️ 项目级 Agent '<name>' 覆盖了插件级路由`
- 项目级优先 (用户显式创建的应优先)
- 回退: 用户可在配置中设置 `plugin_only: true` 忽略项目级 Agent

### 配置

```json
// .aria/config.json
{
  "agent_router": {
    "scan_project_agents": true,    // 默认 true
    "plugin_only": false,           // 设为 true 忽略项目级 Agent
    "cache_ttl_seconds": 0          // 0 = 仅 mtime 失效, >0 = 时间失效
  }
}
```

---

## 相关文档

- [ROUTING_RULES.md](./ROUTING_RULES.md) - 路由规则全集 (FP/TT/技术栈/关键词 + **§CAP 项目级 capability 评分与两段式决策**)
- [subagent-driver](../subagent-driver/SKILL.md) - Fresh Subagent 执行器
- [agent-gap-analyzer](../agent-gap-analyzer/SKILL.md) - 覆盖度分析 (v1.13.0)
- [agent-creator](../agent-creator/SKILL.md) - Agent 配置生成 (v1.13.0)
- [capabilities-taxonomy](../../references/capabilities-taxonomy.yaml) - 能力标签词汇表
- [phase-b-developer](../phase-b-developer/SKILL.md) - Phase B 开发

---

**最后更新**: 2026-07-12
**Skill版本**: 1.2.2 (摘要表残余漂移对齐 #101: 6 行对齐 canonical + 表级 canonical banner; 前版 1.2.1 基线层 5 处语义补明 #99)
