# Agent Router 路由规则配置

> **版本**: 1.1.0
> **更新**: 2026-07-09 - 新增 §CAP 项目级 capability 匹配评分与决策规则 (#153 发现 B)

---

## 规则结构

```yaml
路由规则:
  - id: 规则唯一标识
    agent: 目标 Agent
    confidence: 基础置信度 (0-1)
    conditions:
      文件路径匹配
      任务类型匹配
      关键词匹配
    boosters: 置信度加成
    priority: 优先级 (越高越优先)
```

---

## 文件路径规则

| ID | Agent | 路径模式 | 置信度 | 说明 |
|----|-------|----------|--------|------|
| FP-001 | backend-architect | `backend/**/*` | 0.90 | 后端目录 |
| FP-002 | backend-architect | `api/**/*` | 0.95 | API 目录 |
| FP-003 | backend-architect | `server/**/*` | 0.85 | 服务器目录 |
| FP-004 | backend-architect | `services/**/*` | 0.85 | 服务层 |
| FP-005 | backend-architect | `database/**/*` | 0.90 | 数据库 |
| FP-006 | backend-architect | `migrations/**/*` | 0.80 | 数据迁移 |
| FP-007 | backend-architect | `*.go` | 0.85 | Go 后端 |
| FP-008 | backend-architect | `*Routes.java` | 0.90 | Java 路由 |
| FP-009 | mobile-developer | `mobile/**/*` | 0.95 | 移动端目录 |
| FP-010 | mobile-developer | `ios/**/*` | 0.90 | iOS 目录 |
| FP-011 | mobile-developer | `android/**/*` | 0.90 | Android 目录 |
| FP-012 | mobile-developer | `*.dart` | 0.90 | Flutter/Dart |
| FP-013 | mobile-developer | `*.swift` | 0.85 | Swift |
| FP-014 | mobile-developer | `*.kt` | 0.85 | Kotlin |
| FP-015 | knowledge-manager | `docs/**/*` | 0.85 | 文档目录 |
| FP-016 | knowledge-manager | `spec/**/*` | 0.80 | 规格目录 |
| FP-017 | knowledge-manager | `ARCHITECTURE.md` | 0.90 | 架构文档 |
| FP-018 | ai-engineer | `ai/**/*` | 0.90 | AI 目录 |
| FP-019 | ai-engineer | `llm/**/*` | 0.95 | LLM 目录 |
| FP-020 | ai-engineer | `rag/**/*` | 0.95 | RAG 目录 |
| FP-021 | ai-engineer | `agents/**/*` | 0.85 | Agent 目录 |
| FP-022 | frontend-developer | `frontend/**/*` | 0.85 | 前端目录 |
| FP-023 | frontend-developer | `web/**/*` | 0.85 | Web 目录 |
| FP-024 | frontend-developer | `*.jsx` | 0.70 | React |
| FP-025 | frontend-developer | `*.vue` | 0.70 | Vue |

---

## 任务类型规则

| ID | Agent | 任务类型 | 置信度 | 触发关键词 |
|----|-------|----------|--------|------------|
| TT-001 | backend-architect | `architecture` | 0.85 | 后端架构、API 设计 |
| TT-002 | backend-architect | `api-design` | 0.95 | API、接口、endpoint |
| TT-003 | backend-architect | `database` | 0.90 | 数据库、schema、索引 |
| TT-004 | backend-architect | `microservice` | 0.85 | 微服务、服务边界 |
| TT-005 | mobile-developer | `mobile-feature` | 0.95 | 移动端功能、App |
| TT-006 | mobile-developer | `offline-sync` | 0.90 | 离线同步 |
| TT-007 | mobile-developer | `push-notification` | 0.90 | 推送通知 |
| TT-008 | knowledge-manager | `documentation` | 0.85 | 文档、API 文档 |
| TT-009 | knowledge-manager | `ai-ddd` | 0.90 | AI-DDD、领域建模 |
| TT-010 | qa-engineer | `code-review` | 0.95 | 代码审查、PR review |
| TT-011 | qa-engineer | `testing` | 0.85 | 测试、测试策略 |
| TT-012 | qa-engineer | `performance` | 0.70 | 性能分析 |
| TT-013 | tech-lead | `planning` | 0.85 | 任务规划、分解 |
| TT-014 | tech-lead | `tech-decision` | 0.90 | 技术决策、选型 |
| TT-015 | ai-engineer | `llm` | 0.95 | LLM、大模型 |
| TT-016 | ai-engineer | `rag` | 0.95 | RAG、向量检索 |
| TT-017 | ai-engineer | `prompt` | 0.85 | 提示工程、prompt |
| TT-018 | ai-engineer | `embedding` | 0.90 | 嵌入、向量 |
| TT-019 | api-documenter | `api-doc` | 0.95 | API 文档、OpenAPI |
| TT-020 | api-documenter | `sdk` | 0.85 | SDK、客户端库 |
| TT-021 | legal-advisor | `legal` | 0.95 | 法律、合规 |
| TT-022 | legal-advisor | `privacy` | 0.90 | 隐私、GDPR |
| TT-023 | ui-ux-designer | `ui-design` | 0.90 | UI、界面设计 |
| TT-024 | ui-ux-designer | `ux-research` | 0.85 | 用户研究、体验 |
| TT-025 | context-manager | `context-sync` | 0.85 | 上下文同步 |

---

## 关键词匹配规则

### 后端相关

| 关键词 | Agent | 加成 |
|--------|-------|------|
| API, endpoint, route | backend-architect | +0.1 |
| schema, migration, SQL | backend-architect | +0.1 |
| microservice, service | backend-architect | +0.05 |
| auth, authentication, authorization | backend-architect | +0.05 |

### 移动端相关

| 关键词 | Agent | 加成 |
|--------|-------|------|
| mobile, app, iOS, Android | mobile-developer | +0.1 |
| Flutter, React Native, Dart | mobile-developer | +0.15 |
| offline, sync, push | mobile-developer | +0.1 |
| widget, screen, navigation | mobile-developer | +0.05 |

### AI 相关

| 关键词 | Agent | 加成 |
|--------|-------|------|
| LLM, GPT, Claude, model | ai-engineer | +0.15 |
| RAG, vector, embedding | ai-engineer | +0.15 |
| prompt, completion | ai-engineer | +0.1 |
| agent, orchestration | ai-engineer | +0.1 |

### 文档相关

| 关键词 | Agent | 加成 |
|--------|-------|------|
| documentation, docs | knowledge-manager | +0.1 |
| architecture, design | knowledge-manager | +0.1 |
| API doc, OpenAPI | api-documenter | +0.15 |
| SDK, client library | api-documenter | +0.1 |

### 质量相关

| 关键词 | Agent | 加成 |
|--------|-------|------|
| review, code review | qa-engineer | +0.15 |
| test, testing, coverage | qa-engineer | +0.1 |
| bug, fix, issue | qa-engineer | +0.05 |
| performance, optimization | qa-engineer | +0.05 |

### 领导相关

| 关键词 | Agent | 加成 |
|--------|-------|------|
| plan, planning, task | tech-lead | +0.1 |
| decision, choice, trade-off | tech-lead | +0.15 |
| architecture, design | tech-lead | +0.05 |

---

## 技术栈匹配

| 技术栈 | Agent | 置信度 |
|--------|-------|--------|
| **后端框架** |
| Express.js | backend-architect | 0.85 |
| Django / Flask | backend-architect | 0.90 |
| Spring Boot | backend-architect | 0.85 |
| FastAPI | backend-architect | 0.85 |
| **移动端** |
| Flutter | mobile-developer | 0.95 |
| React Native | mobile-developer | 0.95 |
| Swift / UIKit | mobile-developer | 0.90 |
| Kotlin / Jetpack | mobile-developer | 0.90 |
| **AI/ML** |
| LangChain | ai-engineer | 0.90 |
| OpenAI API | ai-engineer | 0.85 |
| Anthropic API | ai-engineer | 0.85 |
| Pinecone / Qdrant | ai-engineer | 0.90 |
| **数据库** |
| PostgreSQL | backend-architect | 0.80 |
| MongoDB | backend-architect | 0.80 |
| Redis | backend-architect | 0.75 |

---

## §CAP 项目级 capability 匹配 (v1.1.0, #153 发现 B)

> 消费 `.aria/agents/*.md` 项目级 Agent 的 `capabilities` 机读标签, 与任务需求标签
> (required_caps) 做确定性覆盖率匹配。仅对**项目级候选**评分 — 插件级 agent 的路由
> 沿用上方 FP/TT/技术栈/关键词四类既有刻度, 其 capabilities 字段不参与本节评分 (留观)。
> 词表与归一锚定 `aria/references/capabilities-taxonomy.yaml` (tag 名 + synonyms)。

### CAP-1 required_caps 确定 — 显式传参优先 + 两级闭集推断

```
第 0 优先 — 显式传参 (v1.2.0 新增可选输入参数, additive):
    router 输入含 required_caps (list of tag) 时 → 跳过 L1/L2 推断, 经 taxonomy
    归一后直接采用; 无法归一的传入值 (off-taxonomy/拼写错) → 剔除 + WARN,
    不进入 required_caps 分母。
    (fixture 与高级调用方由此获得推断-裁决解耦。)

无显式传参时 — 两级闭集推断:
L1 (机械, 可复算): 对 taxonomy (tag 名 + synonyms) 的词边界全名命中:
    - 显式传入的 task_type 参数值 == tag 名或 synonym (单值参数, 最多贡献 1 个命中)
    - task 文本 / files 路径中逐字出现 tag 名或 synonym
L2-negation (恒时执行, 不受下方启用条件门控):
    执行 agent 可依据相反证据 token 将 L1 命中标记 negated 并移除
    (否定语境鉴别, 须引用任务原文证据)
L2-addition (受启用条件门控): 语义补充 tag, 约束:
    (a) taxonomy 闭集; (b) 每 tag 引用任务原文 evidence token;
    (c) 标记 inferred=semantic; (d) 上界 3 个;
    (e) 启用条件: 仅当 |L1_hits − negated| < 2 (净值计数)

编排: required_caps = (L1_hits − negated) ∪ L2_additions
去重按 canonical tag; required_caps 为空 → CAP 候选空集 → 纯基线路由
```

**确定性定位 (诚实版)**: agent-router 是 prose Skill, FP/TT 匹配同样由 LLM 执行 (受本文件确定性规则表约束 — 既有性质)。§CAP 的确定性 = 显式传参全机械 + L1 机械可复算 + L2 闭集/证据/上界受约束 + 推断轨迹落输出字段 (`required_caps_trace`) 可审计。生产自然语言路径 (无传参) 以 L2 为常态。

### CAP-2 归一语义

- tag 在 taxonomy (名或 synonym) → 归一到 canonical tag
- **off-taxonomy 自造标签 = 惰性**: 不可能命中 required_caps (零分), **也不计入 precision 分母** — 惰性标签无匹配力, 不构成劫持向量, 计入分母只会错杀携带遗留/自定义标签的真 specialist。候选条目输出 `off_taxonomy_tags` 字段提示 owner 修标签。

### CAP-3 评分公式

```
valid_caps = normalize(agent.capabilities) ∩ taxonomy 词表   # off-tax 惰性排除
matched    = valid_caps ∩ required_caps
match_rate = |matched| / |required_caps|                     # 覆盖率, [0,1]
precision  = |matched| / |valid_caps|                        # 精度; valid_caps = ∅ →
                                                             #   不产出候选 (含除零防护)
match_rate == 0 → 不产出候选 (不入池, 不进 recommend)
```

> 防劫持语义: generalist 靠**有效标签**堆宽度 → precision 被稀释 → CAP-4 R-a 拒之门外;
> off-tax 标签不增加任何匹配力, 故不参与该攻防。

### CAP-4 auto 决策规则 (两段式)

**Rationale**: 唯一硬理由是数学事实 — CAP match_rate 上限 1.0, 对 confidence >0.9 的插件对手差值恒 <0.1, 纯数值比较 + 差值护栏会把「specialist 全命中」黄金场景 (#153) 恒降级 recommend。故为 exact-full-match 设 R-a 序数快路; R-b 的跨刻度数值比较是**有界务实近似** (护栏 + 单标签禁令 + threshold), 不声称两刻度同量纲。

```
Stage 1 — 基线裁决 (规则与既有行为一致):
    基线侧候选 = FP/TT/技术栈/关键词候选 + B12 同名吸收分候选 (若有, 见 CAP-6)
    按既有规则: 同 Agent 多规则取最高 → 全局排序 → **基线侧候选间**差值 < 0.1
    (严格, 沿用下方「优先级处理」的「多个 Agent 置信度相近」既有规则; 吸收候选
    一并适用, 不因 agent_source=project 逃逸) → 降级 recommend; threshold 检查照旧
    产出: baseline 决策 + baseline_top

Stage 2 — 项目级 CAP 挑战 (仅当池中存在纯 CAP 项目级候选; 无则采纳 Stage 1):
    挑战者 = 纯 CAP 候选 (B12 吸收候选的 CAP 分录不参与遴选, 防自我挑战)
             中 match_rate 最高者 (再平按 CAP-5)

    R-a 决定性直派 (序数快路):
        挑战者满足全部三条:
          match_rate == 1.0  AND  |required_caps| >= 2  AND  precision >= 0.5
        → auto 直派挑战者 (多候选同满足 → CAP-5 tiebreak)
    R-b 跨池数值裁决 (R-a 不满足; 有序分支 (0)-(4), 按序判定, 先匹配先裁决;
        d = 挑战者 match_rate − baseline_top confidence):
        (0) |required_caps| == 1 的挑战者永不 auto 直派, 仅进 recommend
        (0.5) **基线候选池为空** (无任何 FP/TT/技术栈/关键词命中, baseline_top
              不存在, d 无定义): 挑战者 match_rate >= threshold → 直派挑战者;
              < threshold → 降级 recommend — 均记 decision_path = R-b
              (不得为凑 baseline 而语义虚构 TT/关键词命中)
        (1) |d| <= 0.1 (含 0.1, 本新路径边界显式取含; 精确同分同此) → 降级 recommend
        (2) d > 0.1 且 match_rate >= threshold → 直派挑战者
        (3) d > 0.1 且 match_rate <  threshold → 降级 recommend (领先但不够格)
        (4) 其余 (d < -0.1, baseline_top 显著领先) → 采纳 Stage 1 决策
    decision_path 赋值通则: R-b 评估中结论 = 采纳 Stage 1 (分支 4)
        → decision_path = baseline; 由 R-b 逻辑裁定 (分支 0/1/2/3) → decision_path = R-b

R-a 覆盖面诚实刻画: |required_caps| 大时全命中率下降, R-a 只服务「需求标签集中且
specialist 精确对位」场景, 其余走 R-b/recommend; L2 上界 3 防 required_caps 膨胀。
```

### CAP-5 CAP 候选互相平局

match_rate 相等的项目级候选之间: precision 高者优先, 再平 → agent name 字典序。(跨池不适用, 跨池走 CAP-4。)

理论注记: 项目级互相 0<差值≤0.1 近分场景无专门护栏 — match_rate 量化为 k/|required_caps|, 该窗口需 |required_caps| ≥ 10 才可达, 现实几乎不可达, 接受。

### CAP-6 同名保护复合 (B12 得分归属)

项目级与插件级同名时 (候选池构建期, 先于评分):
- 项目级替换插件级候选 + 输出警告 (v1.1.0 同名保护语义保留: 项目级优先 + `plugin_only` 逃生门)
- 幸存项目级候选**吸收**插件级按名命中的全部 FP/TT/技术栈/关键词 confidence (名匹配语义随名走 — 「覆盖插件级路由」= 接管其路由); `agent_source` 恒 = project
- **裁决消歧**: 吸收的 baseline confidence 是该候选在 auto 裁决中的 governing confidence, 于 Stage 1 按基线侧参与 (可为 baseline_top, 也受基线侧 <0.1 近分检查); 其自身 CAP match_rate 仅用于 trace 与 recommend 排序, **不作为 auto 挑战分数** (防同一候选自我挑战)
- 凭吸收分胜出 → `decision_path = "baseline"` + `agent_source = "project"` (组合语义 = 同名接管)
- junk-caps 同名候选 (match_rate == 0): 无 CAP 候选产出, 仅以吸收分走 Stage 1 — 一切候选恒有唯一归属 (吸收分→Stage 1; 纯 CAP 分→Stage 2)

### CAP-7 recommend Top-3 混排

```
排序: (1) R-a 合格候选置顶 (若有);
      (2) 其余按 confidence 数值降序混排 (项目级 CAP 候选用 match_rate, 基线候选
          [含 B12 吸收候选] 用基线 confidence; 跨刻度务实近似, recommend 由人裁决);
      (3) 同分 → 项目级列前, 再平字典序
候选条目携带 agent_source (+项目级候选带 off_taxonomy_tags); decision_path 为
decision 级单值字段 (本次裁决整体路径), 不逐候选携带
max_candidates 仍为 3 (居 legacy 配置, 见 SKILL.md §项目级配置 legacy 标注)
本节适用于一切 recommend 输出 — 原生 recommend 模式与 auto 内部降级产出者同
```

---

## 置信度计算

```yaml
最终置信度 = base_confidence + boosters

计算示例:
  任务: "实现用户登录 REST API"
  文件: backend/api/auth.js

  匹配:
    - FP-002 (api/**/*) → backend-architect: 0.95
    - 关键词 "API" → +0.1

  最终: 0.95 + 0.1 = 1.0 (上限为 1.0)
```

---

## 优先级处理

```yaml
当多个规则匹配同一 Agent:
  1. 选择最高置信度
  2. 如果置信度相同，选择优先级最高的规则
  3. 如果仍然相同，选择 ID 最小的 (最早定义)

当多个 Agent 置信度相近 (差值 < 0.1):
  - 降级到推荐模式
  - 展示所有候选 Agent
```

---

## Fallback 规则

```yaml
Fallback 层级:
  1. 专业 Agent (confidence > 0.7)
  2. general-purpose (兜底)
  3. 错误: 无可用 Agent (不应发生)
```

---

## 配置示例

### 项目级覆盖

```json
{
  "enabled": true,
  "default_mode": "recommend",
  "confidence_threshold": 0.9,
  "max_candidates": 3,
  "fallback_agent": "general-purpose",
  "custom_rules": {
    "backend-architect": {
      "boosters": ["microservice", "graphql"]
    },
    "mobile-developer": {
      "boosters": ["state-management", "navigation"]
    }
  }
}
```

### 任务级覆盖

```yaml
# detailed-tasks.yaml
tasks:
  - id: TASK-001
    description: "实现用户认证"
    agent: backend-architect
    agent_reason: "指定后端架构师处理认证逻辑"
```

---

## 维护指南

### 添加新规则

1. 确定规则类型 (FP/TT/关键词/技术栈/CAP — 五类; CAP 规则见 §CAP, 其"规则"是评分与决策算法而非映射表行)
2. 分配唯一 ID
3. 定义匹配条件和置信度
4. 更新此文档
5. 测试规则有效性

### 规则审查

- 每月审查规则有效性
- 根据实际使用调整置信度
- 移除冗余规则
- 合并相似规则

---

**最后更新**: 2026-01-22
