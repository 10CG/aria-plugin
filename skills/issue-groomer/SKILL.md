---
name: issue-groomer
description: |
  项目内卫星仓 open issue 的组合面批量梳理: 全分页 fetch → Tier A 机械粗分
  (title 前缀 / label / staleness / 活跃度) → 增量三面指纹 + diff →
  Tier B 语义评估 (疑似已修可关单 / 优先级 vs 在制轨道 / owner 决策面抽取)
  → MD 渲染。产出 groom-report.json (schema v1.1) 与 .aria/groom-assessments.json。
  只读梳理: 产出止于报告与建议清单, 不写回 tracker (建单/关单/打标/挪列均不做)。

  使用场景："梳理 issue 积压"、"issue 分类排序"、"backlog grooming"、
  "找下一个该处理的 issue"、"定期梳理 backlog"
  不适用 (单条核对 → /issue-triage)：核对单个 issue 的版本 / 复现 /
  in-flight 修复；单项目状态快照 → /state-scanner
disable-model-invocation: false
user-invocable: true
allowed-tools: Bash, Read, Write, Edit
---

# Issue Groomer (issue-groomer P1 MVP)

> **版本**: P1 MVP 首版 | **Spec**: `openspec/changes/issue-groomer-p1-mvp` (10CG/Aria#238, 主仓) | **决策**: DEC-20261018-001 (裁定-1~13, 主仓 `.aria/decisions/`)
> **十步循环角色**: issue 接活入口 (裁定-1 流向: groomer 组合面选哪个 → `/issue-triage` 单条核验 → Phase A/B)
> **分层**: 机械核 `scripts/groom.py` (stdlib-only, 多 harness 可移植) + 本适配层 (Tier B 语义评估 + 渲染, 质量随 harness)

---

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- 梳理 issue 积压: 卫星仓 open issue 全量拉取 + 分类汇总
- 定期 backlog grooming / issue 分类排序
- 找下一个该处理的 issue (优先级 vs 在制轨道交叉参照)
- 疑似已修可关单筛查 (对照 openspec 在制轨 + spec 史)

**不使用场景**:
- 单条 issue 核对 (版本 / 复现 / in-flight 修复) → `/issue-triage` (下游: 本 skill 从组合面选出条目后, 单条深核交给它)
- 单项目状态快照渲染 → `/state-scanner` (其 `issue_scan` collector 是本 skill 作用域配置的同款形态来源)
- 对 tracker 执行写动作 (打标 / 回复 / 关单) → P1 只产不写 (裁定-8), 见 §Step 4

---

## 三层架构与文件所有权 (裁定-4)

| 层 | 执行者 | 职责 |
|----|--------|------|
| 机械核 | `scripts/groom.py` (+ `scripts/lib/`) | fetch 全分页 → Tier A 粗分 → 三面指纹 → 增量复用门 → diff 段 → schema v1.1 报告 + 出厂自校验 |
| **适配层 (本文档)** | **AI (Tier B)** | 三类语义判断 → 写 `.aria/groom-assessments.json` → MD 渲染 |
| 打标 / 回复 (P2) | 未实现 | `labels_payload.apply_payload` 只产不写 (裁定-8: 封闭键集无 remove, 结构性只加不删) |

两文件所有权 (裁定-4, 各自 last-writer-wins; 源: `scripts/lib/incremental.py` 模块 docstring):

- `.aria/cache/groom-state.json` — **groom.py 独占写** (原子 temp+rename; 可再生缓存, 删掉重跑即重建)。适配层只读 (Step 3 取 `context_key`), 绝不手写。
- `.aria/groom-assessments.json` — **本适配层独占写** (Tier B 语义产物; 刻意不在 `cache/` 下 — 清 cache 不得连带丢失)。groom.py 对它全程只读 (引擎 public API 上无 assessment 写面), 「groom.py 重写 state 后本文件字节不变」是可断言不变量。

---

## Step 0: 机械执行 groom.py (硬约束)

> **不可协商**: 报告与 state **只能**由 `groom.py` 进程产出。适配层绝不手写 / 手改 `groom-report.json` 或 `groom-state.json`, 失败时不"降级"到手工拼 JSON — 结构化采集的价值在机械完整性, 手写必然漏字段且过不了自校验 (同判 issue-triage D3 regression)。

**最小命令** (主仓根执行; 作用域回落 `.aria/config.json`):

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/issue-groomer/scripts/groom.py" \
  --harness claude-code --model-id <本轮模型标识>
```

**适配层调用纪律**: 恒传 `--harness` + `--model-id` 自报 — Tier B 复用门比对 harness+model_id 完整拼接串, 自报一致才可能复用自己的历史评估; `--model-id` 缺省 None 与任何具体 model_id 不匹配 ⇒ 既有 assessment 全判 stale (源: `scripts/lib/incremental.py` `gate_tier_b`)。

**CLI 参数** (源: `scripts/groom.py` `parse_args`):

| 参数 | 默认 | 说明 |
|------|------|------|
| `--repos NAME [...]` | 回落 config | 扫描仓清单 (裸名或 `owner/name`); 缺省读 `<project_root>/.aria/config.json` 的 `state_scanner.issue_scan` 节 (`repos` 键, 或 `scan_submodules: true` 经 `.gitmodules` + origin 推导) |
| `--project-root PATH` | `.` | 项目根 (taxonomy 覆盖层 / state / assessments / openspec·handoff 指纹锚点) |
| `--out PATH` | stdout | 报告输出文件 (缺省 stdout JSON) |
| `--harness ID` | `unknown-cli` | harness 自报 (provenance 第一层, 落报告顶层 `harness`) |
| `--model-id ID` | `None` | 模型标识 (provenance 第二层; 见上方调用纪律) |
| `--now ISO` | 系统时钟 | 时钟注入 (staleness 档 / ttl 判定 / `generated_at` / state 时间戳同一时钟; 适配层常规省略) |
| `--top-n N` | `20` | drift top-N 截断上限 (schema 结构护栏 100) |
| `--assessments-ttl DAYS` | 续传 state 值 | assessment 有效期天数 (`created_at + ttl ≤ now` 判过期, 边界算过期) |
| `--runner-bin PATH` | `/home/dev/.npm-global/bin/forgejo` | forgejo CLI wrapper 路径 |
| `--state-path PATH` | `<root>/.aria/cache/groom-state.json` | state 路径覆盖 |
| `--quiet` | off | 抑制 stderr 进度行 |

> **已知取舍 (零评论对账 GET)**: issue 的 `comments` 计数字段为 0 时 fetch 层仍会发一次 comments 对账 GET — 不信任计数单侧, 对账以 comments 端点全量返回为准 (计数与端点行数不符 ⇒ fail-closed; 该端点实测忽略 limit/page 恒全量返回, 见 `references/forgejo-behavior-notes.md`)。多出的空 GET 是刻意付的成本, 非 bug。

**退出码契约** (源: `scripts/groom.py` `main`):

| 退出码 | 含义 | 适配层动作 |
|--------|------|-----------|
| `0` | 成功 (报告已过 schema 自校验, state 已写) | 进 Step 1 |
| `1` | 运行错误 / 报告自校验失败 (fail-closed: 不写 state、不出厂非法报告)。**任何仓 `repos[].error` 非空 ⇒ `exit 1` 且不写 state** (state 保持上轮, 重跑幂等 — 半份语料会把失败仓条目谎报成 closed) | Abort, 展示 stderr (失败仓逐一点名), 修复后重跑 |
| `2` | 配置错误 (`--repos` 缺省回落失败等, 报错说明不猜) | Abort, 按 stderr 补 `--repos` 或 config 节 |

---

## Step 1: 读 report, 圈定待评估集

1. 读报告 (stdout 或 `--out` 文件): `issues[]` 为全量非选集; `summary.assessed` = assessment 非 null 条目数 (Tier B 覆盖率面)。
2. **待 Tier B 评估 = `issues[].assessment == null` 的条目**, 三种成因, 区分法:
   - **无评估** — 键不在 `.aria/groom-assessments.json` 中 (首见 / 从未评估过)
   - **被复用门判 stale 剔除** — 键在 assessments 文件中存在但报告面为 null (门拒绝, 报告层以 null 呈现; 引擎不改写不删除)
   - **报告面投影降级** — 键经复用门判 reusable (如 assessments 面 `model_id: null` 与本轮 `--model-id` 缺省 None 匹配), 但报告面 `provenance` 要求 harness/model_id **双双非空 str**, 投影不可满足 ⇒ 该条整体降级 null — 文件面条目原样保留, 下轮带具体 `--model-id` 跑即可恢复进报告 (源: `scripts/groom.py` `_project_assessment`; 与复用门是独立两层)
3. stale 成因 = 封闭枚举 `STALE_REASONS` (9 值; 身份门 provenance-\* / 上下文门 context-\* / 新鲜度门 created-at-\* + ttl-expired, 多违规报第一个命中; **全集与判序以 `scripts/lib/incremental.py` 的 `STALE_REASONS` 常量与 `ASSESSMENTS_SCHEMA_DOC` 为准, 勿凭本文件复述** — 引用勿手抄)。
4. **上下文门预期** (裁定-9 精确分层, Runtime Amendment #4): openspec 在制树 / git HEAD / handoff pointer / taxonomy 任一变 ⇒ **Tier B 全量 stale** (`context-changed`) ⇒ 全量重评是预期工作量模型, 不是 bug; Tier A 免重评 (分类输入 ⊆ issue_key ∪ judgement_inputs, 数学论证; 源: `scripts/lib/incremental.py` 模块 docstring)。
5. `diff.baseline_run == true` ⇒ 首跑/状态缺失, diff 段 no-diff 语义 (new/closed/drift 恒空数组)。

---

## Step 2: Tier B 三类语义判断

对每条待评估 issue (输入 = 报告条目 + 项目上下文), 做三类判断 (裁定-7):

| 判断面 | 问题 | 交叉参照材料 |
|--------|------|--------------|
| **疑似已修可关单** (`suspected_fixed`) | 该 issue 是否已被某项已 ship 的工作解决而可关单? | `openspec/changes/` 在制轨 + `openspec/archive/` spec 史 + 子仓 CHANGELOG + `docs/handoff/` |
| **优先级 vs 在制轨道** (`verdict_priorities`) | issue 隐含的优先级 / 方向是否与在制 spec / 分支冲突, 或已被在制轨覆盖 / 推迟? | `openspec/changes/*/proposal.md` + 活跃分支 + handoff 在制轨记录 |
| **owner 决策面抽取** (`owner_decisions`) | 哪些事项需要人裁 (无法由 AI 依据现存材料定夺)? | 综合以上两面 + 项目约束 |

**原则**: 拿不准 = 不猜。某面判不出就省略该面 — 契约只保证面存在且格式稳定, 不要求全覆盖 (`assessment: null` 本身是合法态; 源: `scripts/groom-report.schema.json` `IssueEntry.assessment`)。机械层 (Tier A) 结构上不产出这些判断 — 语义面全部出自本层; Tier A 有两个保留值: `unknown` (无显式编码信号) 与 `conflict` (多个分类信号互斥不一致 — 信号集原样枚举, 绝不任选其一, 任选即隐性猜测)。渲染层遇 `conflict` 应列为「待人工归边」条目, 不当分类失败处理 (源: `scripts/lib/tier_a.py` `classify`; 值域文档: `scripts/groom-report.schema.json` `IssueEntry.category`)。

---

## Step 3: 写回 `.aria/groom-assessments.json`

> **落盘前必读**: `.aria/cache/groom-state.json` 的 `last_run.context_key`。每条 entry 的 `context_key` **逐字取该值** — 它是本轮所消费报告的上下文指纹 (与报告同一 pipeline run 写入)。不自己计算、不复用旧值; 取错 ⇒ 下轮全部 `context-changed` stale。

**键结构 SOT = `scripts/lib/incremental.py` 的 `ASSESSMENTS_SCHEMA_DOC` + 机读锚点常量** (`ASSESSMENTS_ENTRY_REQUIRED_KEYS` / `ASSESSMENTS_ENTRY_OPTIONAL_KEYS` / `ASSESSMENTS_PROVENANCE_KEYS`; 引用勿手抄, 以常量为准)。最小写作面:

```
根:  {"schema_version": 1, "assessments": {"<repo>#<number>": <entry>, ...}}
entry 必填三键 (ASSESSMENTS_ENTRY_REQUIRED_KEYS):
  provenance   {"harness": <非空 str, 与报告顶层 harness 同源>,
                "model_id": <适配层补全的具体模型标识>}
  created_at   <ISO 8601, 推荐 UTC Z 形态>
  context_key  <上方必读值 — state.last_run.context_key 逐字>
entry 语义面可选三键 (ASSESSMENTS_ENTRY_OPTIONAL_KEYS):
  verdict_priorities / suspected_fixed / owner_decisions
  (文件面富形态含 rationale, 示例见 ASSESSMENTS_SCHEMA_DOC)
```

**文件面 vs 报告面** (防误读, 源: `scripts/groom.py` `_project_assessment`): 报告 `assessment` 面只做**白名单类型投影** — `verdict_priorities` 须为 string / `suspected_fixed` 须为 bool / `owner_decisions` 须为 string 列表, 类型不符即该面**整面省略** (机械层不转语义 = 不造数据)。富形态 (如 `{"from","to","rationale"}` 列表) 在报告面缺席属预期非缺陷; 渲染层语义细节自取本文件 (Step 4)。

**写者纪律** (裁定-4):
- 只增改本轮评估过的键; 其余条目**原样保留** — 含 orphaned (issue 已关闭 / 移出作用域的键, P1 无清理面, 清理属 owner 决策)。
- 本文件是适配层独占写面: 整文件读 → 合并本轮条目 → 序列化写回。groom.py 全程不触它。
- 复用闭环: 下轮以相同 `--harness` / `--model-id` 跑 groom.py ⇒ 门通过 ⇒ 报告 `assessment` 面 非 null (白名单面自动投影), 语义富面仍在本文件。

---

## Step 4: MD 渲染层 (四段骨架)

> 源: `scripts/groom-report.schema.json` `SummarySection` — 渲染层四段 (分类汇总 / 优先级分档 / 决策面 / diff) 由适配层从 `issues[]` + `diff` **自算**; `summary` 面只承载数字对账 (`total_issues` / `by_category` / `by_repo` / `assessed` / `diff_counts`)。

```markdown
# Issue Grooming — <project> @ <generated_at>
harness: <harness> | baseline_run: <diff.baseline_run> | Tier B 覆盖: <summary.assessed>/<summary.total_issues>

## 1. 分类汇总
<summary.by_category 表; 附 summary.by_repo 与 repos[].error 失败显式可见>

## 2. 优先级分档
<适配层自算档位, 例如: 可关单候选 (suspected_fixed) / 待 owner 裁 /
 在制轨相关 (verdict_priorities 命中) / 新增待评 (diff.new) / 陈旧低活跃
 (staleness 信号) — 每条注 issue 键 repo#number 与一句依据>

## 3. Owner 决策面
<owner_decisions 汇总清单 — 每条注来源 issue 键; 取自 assessments 文件富面>

## 4. Diff 段
new: <N> | closed: <N> | drift: <N>
<diff.new / diff.closed / diff.drift 条目列表;
 drift_truncated=true 时显式注 "另有 <drift_total - len(drift)> 条未展示" — 截断不静默>
```

渲染注意 (诚实占位, 源: `scripts/groom.py` 组装层):
- `diff.closed[].title` 是占位符 `"(closed; not in current scan)"` (上轮 state 不存 title), **不是真实标题**, 呈现时注明。
- `diff.drift[].from == "(none)"` = 该条上轮不在册 (new 候选), 非真实旧分类。
- P1 **不执行任何 tracker 写动作**: `labels_payload.apply_payload` (add = suggested − existing 差集, `idempotent` 恒 true) 是 P2 打标 CLI 的直接输入, 本层只可展示建议标签, 不得调用打标 API (裁定-8)。

---

## 多 harness 诚实主张

- **可移植面 = 事实面 + Tier A 机械粗分**: `groom.py` stdlib-only, 报告 schema v1.1 是 plugin 外可及的契约面 (裁定-3/13), 任何 harness 与 Layer 1 可直接消费。
- **Tier B 语义评估质量随 harness 而变**: 契约只保证面存在且格式稳定, 不保证语义质量 (源: `scripts/groom-report.schema.json` `IssueEntry.assessment` description)。
- **跨 harness 杜绝静默复用**: 复用门比对 harness + model_id 完整拼接串 (且上下文门比对 `context_key`), 不同 ⇒ 旧 assessment 判 stale 不进报告 — 换模型 / 换 harness 后全量重评是设计行为 (fail-closed: 宁重评不误复用)。

---

## 双源同步义务预告 (裁定-13)

P2 引入 issue reply 模板时: **契约面 reply 模板定义**与 **issue-triage CC 适配模板族** (`triage-comment.md` 模板) 是两份资产, **一处改动须同步另一处**。本条为预告, 防静默分叉 (P1 无 reply 模板, 零执行面)。改动任一端时在 spec / handoff 中记同步义务。(源: `openspec/changes/issue-groomer-p1-mvp/proposal.md` §What Changed, 主仓)

---

## References 与配套资产

| 资产 | 路径 | 说明 |
|------|------|------|
| 报告 schema (SOT) | `scripts/groom-report.schema.json` | v1.1, additive-only (SC-8: 加字段 = minor bump, 删/改 = major); 消费代码须忽略未识别字段 |
| Forgejo 行为实测 | `references/forgejo-behavior-notes.md` | live 实测事实 (版本钉死 `11.0.16+gitea-1.22.0`): 重复 label add 完整 no-op / **comments 端点忽略 limit+page 恒全量返回** / issue-list 分页正常; Forgejo 升级后须复测 |
| 语料三快照 + 再生成 | 主仓 `scratchpad/issues-open-full-18repos-2026-10-18.json` / `issues-open-2026-10-18.json` / `issues-sample-body-comments-2026-10-18.json` | Tier A 默认层前缀锚定 + fixture 形态源; **清理即失, 靠再生成恢复**: `python3 aria/skills/issue-groomer/scripts/regen_corpus.py` (默认写 scratchpad 日期=今天; `--date 2026-10-18` 原位恢复 canonical 三件套; `--repos <names...>` 子集 smoke) (源: `scripts/regen_corpus.py` docstring) |
| labels taxonomy 双层 | `config/labels-default.yaml` + `<project_root>/.aria/labels.yaml` | 裁定-1: 项目层存在时**整体覆盖**默认层 (**覆盖非合并**, 零字段合并); 默认层只收 4 通用键 (bug/feature/security/tracker), 项目专名前缀由项目层自行声明 (源: `scripts/lib/tier_a.py` `resolve_taxonomy` + `config/labels-default.yaml` 头注) |
| tests | `tests/` (pytest) | 见下节测试 runner 申明 |

---

## 测试 runner 申明

- Runner = **pytest**, 本机路径 `~/.local/bin/pytest` (pytest 9.0.2)。命令 (主仓根): `~/.local/bin/pytest aria/skills/issue-groomer/tests/ -q`。
- 触碰本 skill 任何文件 (`scripts/` / `tests/` / `config/` / 本 SKILL.md) 后跑全目录; 跨 skill 消费方受影响的改动须在对应消费方 tests 一并跑。
- `groom.py` 的出厂自校验与 `tests/test_schema.py` 断言面同源 import 生产层 `scripts/lib/schema_validate.py` 的 `mini_validate` (单点 SOT, stdlib-only, 不依赖 jsonschema/pytest — B.3 依赖方向修正: 校验实现住生产层, 生产代码不直载 tests/ 亦无 pytest stub 注入面; 源: `scripts/groom.py` `_mini_validate`), 故 schema 校验不依赖本机 pytest 安装。

---

## 使用示例

### CLI — 最小 (主仓根, 作用域走 config)

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/issue-groomer/scripts/groom.py" \
  --harness claude-code --model-id glm-5.2
# 报告 → stdout; state → .aria/cache/groom-state.json; stderr 进度行可见
```

### CLI — 全参 (显式作用域 + 落盘 + 截断 + ttl)

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/issue-groomer/scripts/groom.py" \
  --project-root /home/dev/Aria \
  --repos Aria aria-plugin aria-standards aria-orchestrator \
  --harness claude-code --model-id glm-5.2 \
  --out .aria/groom-report.json \
  --top-n 20 --assessments-ttl 14 \
  --state-path .aria/cache/groom-state.json \
  --quiet
```

### 适配层流程 (伪码)

```
1. 跑 groom.py (恒带 --harness/--model-id 自报)          # Step 0; exit 非 0 ⇒ abort
2. 读报告: 圈定 assessment==null 条目                      # Step 1
   ├─ 键不在 .aria/groom-assessments.json ⇒ 无评估
   └─ 键在文件中 ⇒ stale (复用门拒绝, 含上下文门全量 stale 态)
3. 读 .aria/cache/groom-state.json → last_run.context_key  # Step 3 前置, 必读
4. 逐条三类判断 (suspected_fixed / verdict_priorities /
   owner_decisions), 对照 openspec 在制轨 + spec 史 + handoff  # Step 2
5. 合并写回 .aria/groom-assessments.json:
   每条 = 语义面(可选三键) + provenance{harness, model_id}
        + context_key(第 3 步值) + created_at(现在, UTC Z)   # Step 3
   其余条目(含 orphaned)原样保留
6. 渲染 MD 四段呈现用户 (分类汇总/优先级分档/决策面/diff)    # Step 4
   — 不做任何 tracker 写动作 (P1)
```

---

## 检查清单

### 使用前
- [ ] forgejo CLI wrapper 可用 (`/home/dev/.npm-global/bin/forgejo`, 凭据经其代理)
- [ ] 作用域可解析: `.aria/config.json` 有 `state_scanner.issue_scan` 节, 或备好 `--repos` 清单
- [ ] 已确认这是组合面梳理 (单条核对应走 `/issue-triage`)

### 使用后
- [ ] `groom.py` exit 0 (报告已过 schema 自校验)
- [ ] 本轮有评估时: assessments 每条新 entry 含 `provenance` / `created_at` / `context_key`, 且 `context_key` 与 state `last_run.context_key` 一致
- [ ] 未手写 / 未改动 `groom-report.json` 与 `groom-state.json`
- [ ] MD 渲染四段齐备; closed 占位标题 / drift 截断已如实呈现
- [ ] 未执行任何 tracker 写动作 (打标 / 回复 / 关单均为 P2 或人工面)

---

## 相关文档

- [openspec/changes/issue-groomer-p1-mvp/proposal.md](../../../../openspec/changes/issue-groomer-p1-mvp/proposal.md) — Spec SOT (主仓)
- `.aria/decisions/DEC-20261018-001-issue-ops-family-and-issue-groomer-design.md` — 裁定-1~13 (主仓)
- [issue-triage SKILL.md](../issue-triage/SKILL.md) — 下游单条核验; 裁定-13 双源同步义务对端 (P2)
- [state-scanner SKILL.md](../state-scanner/SKILL.md) — `issue_scan` 配置形态同源
- [references/forgejo-behavior-notes.md](./references/forgejo-behavior-notes.md) — 外部 API 行为实测
- 触发 issue: 10CG/Aria#238 (Forgejo 10cg.local)

---

**最后更新**: 2026-10-19 (P1 MVP 首版, TASK-010)
**维护者**: 10CG Lab
