# Runtime Probe Declaration — 声明式运行时探针

> **读者**: spec 作者。本文档回答"如何在我的 `proposal.md` frontmatter 里声明
> `runtime_probe:`，让归档门在归档时机额外核验我的机制是否真被生产环境调用"。
> 声明**完全可选** —— 不声明的 spec，归档门 (`spec_complete.py :: gate_result`)
> 行为逐字节不变 (SC-1)。
>
> 来源: `runtime-probe-archive-gate-integration` (aria-plugin #95 follow-up A，
> 决策 SOT `docs/decisions/DEC-20260705-001-runtime-probe-into-archive-gate.md`，
> 主仓)。折入裁决 / 归档写入契约由 [openspec-archive
> SKILL.md](../../openspec-archive/SKILL.md) 与 [phase-d-closer
> SKILL.md](../../phase-d-closer/SKILL.md) 承载，本文档只覆盖**声明面**，不重复
> 下游折入/写入契约。

## 何时需要声明

某些机制存在"接了线但没人转"的死代码风险 —— 归档时既有的静态引用检查只能证明
"代码路径存在"，证不了"最近真的被调用过"。若你的 spec 引入了这类**关键但调用
路径隐蔽**的机制（例如某个 advisory 闸门只在特定用户交互分支才会触发），且该
机制已埋点写生产 telemetry（JSONL，每条含 `source`/`ts` 字段），可以声明一个
`runtime_probe` 让归档门顺带核验"最近 N 天内是否真有生产记录"。

**不确定是否需要就不声明** —— 声明是新增负担而非默认义务，且分区必须已存在真实
telemetry 写入路径；无中生有声明一个不存在的分区只会换来恒定 `warn`。

**前置条件（数据源二选一，aria-plugin v1.63.0 起分两子态）**: 探针折入发生在归档门
读完任务数据源之后。你的 spec 必须有**其中一个**任务数据源，声明才会被评估：

| spec 形态 | 声明是否被评估 | 说明 |
|-----------|----------------|------|
| 有 `tasks.md`（L3 Full） | ✅ 评估 | 一直如此 |
| 无 `tasks.md`、有 `detailed-tasks.yaml`（task-planner path B / 常见 L2） | ✅ 评估（**v1.63.0 起**） | 见下 |
| 两者皆无（纯 proposal-only） | ❌ **不评估，归档时零痕迹** | 无 warn / 无 note / 无 soft_error |

**为何 yaml-only 子态从「不评估」改为「评估」**（aria-plugin #113，有意反转
DEC-20260705-001 §What Changes ③ R3 裁决在该子态上的适用）：原裁决的前提是
「spec 结构性不完整时探针无意义」。v1.63.0 的归档门已能精确解析
`detailed-tasks.yaml`，这类 spec 不再「结构性不完整」，前提失效；若继续早退，一个
声明了探针的 yaml-only spec 可以干净 `pass` 而探针从未跑过 —— 那是新的假绿角落。
**纯 proposal-only 子态前提仍成立，维持原裁决**（由
`tests/test_spec_complete.py::TestRuntimeProbeFoldL2ProposalOnlyEvaporates` 锁定，
断言未变）。

若你的 spec 两个数据源都没有而确需运行时核验，补任一数据源即可（`tasks.md` 升 L3，
或让 task-planner 产出 `detailed-tasks.yaml`）。

## 声明 Schema

在 `proposal.md` YAML frontmatter 里新增一个 `runtime_probe:` 顶层键，4 个
scalar 子键（2 必填 2 可选）：

| 字段 | 必填 | 类型 | 默认值 | 说明 |
|------|:---:|------|--------|------|
| `partition` | ✅ | string | — | 生产 telemetry 分区路径（JSONL）。**必须是相对路径**，且 resolve 后必须落在 repo 内（`Path.is_relative_to`） |
| `symbol` | ✅ | string | — | 盯的符号名。**仅作消息标签用**，不做记录级过滤 —— 约定一个分区专属一个机制，分区里每条记录天然都属于该 symbol |
| `max_age_days` | — | int | `14` | 新鲜度窗口（天）。必须是**正整数 ≥1** |
| `enabled_when` | — | string | — （探针恒跑） | `.aria/config.json` 里的 dotted-path 开关（如 `state_scanner.coordination.enabled`）。省略则探针不看任何开关，直接探测分区 |

## 官方示例

```yaml
runtime_probe:
  partition: .aria/coordination-telemetry.jsonl   # 生产 telemetry 分区路径 (必填; 必须相对路径且 resolve 后含于 repo)
  symbol: run_gate                                # 盯的符号 (必填; 消息标签用, 不做记录级过滤)
  max_age_days: 14                                # 新鲜度窗口 (可选, 默认 14; 必须正整数 ≥1)
  enabled_when: state_scanner.coordination.enabled # 可选: .aria/config.json dotted-path 开关
```

这段示例（含行尾注释）是解析器的官方回归 fixture —— 4 字段必须原样正确提取。

## 文本层解析约束（stdlib-only 受限 YAML 子集）

不引入 PyYAML。解析分两层：frontmatter 块提取（`lib/frontmatter_block.py::_frontmatter_block`，
文件**绝对起始**的 `---...---` 块，正文代码块里出现的 `---` 不会被误认作分隔符）
+ `runtime_probe:` 声明本身的受限子集手写解析（`extract_runtime_probe`）。

**承认的形态**：

- 顶层 `runtime_probe:`（该行本身不带值）+ 固定 **2-space 缩进**的 `key: value` 子键行
- **行尾注释剥离**：值中第一个"空格紧跟 `#`"（即 ` #`）起丢弃到行尾 —— 裸 scalar
  语义，没有引号/转义 lexing（这就是官方示例能带注释的原因）
- **未识别的额外 scalar 子键**（同样 2-space `key: value` 形态）会被**宽容忽略并
  透传**，值层校验单纯不认识这些键、不报错。这是实现的既定行为，**不算**下面
  的拒绝形态之一
- **重复的同名子键**取最后一次出现的值（last-wins），同样不算拒绝形态 —— 值层
  照常校验终值。避免依赖此行为，它是宽容而非承诺

**拒绝形态（判"声明无效"，不猜）**：

| 形态 | 例子 |
|------|------|
| 更深嵌套（缩进 > 2，或子键下另起 mapping/sequence） | `  partition:` 下一行再缩进出子结构 |
| flow-style `{}` 映射 | `runtime_probe: {partition: x}` |
| YAML 锚点/别名（`&` / `*`） | `partition: &anchor foo` |
| 多行 block-scalar（`\|` / `>`，含 chomping/缩进变体如 `\|-`、`>+3`） | `partition: \|` 后跟多行内容 |
| tab 缩进（子键行以 tab 而非 2-space 缩进；pre-merge R1 加固，防 tab 行被误判 dedent 静默截断声明） | `<TAB>max_age_days: 3` |

## 值层五种无效形态

文本层解析成功（拿到 `{key: raw_string}`）之后，值本身仍可能不合法。以下五种
均判"声明无效" —— fail-toward-warn，从不 block、从不硬崩：

1. 缺必填字段（`partition` 或 `symbol` 缺失/空串）
2. 字段类型错（如某字段拿到了不匹配的类型）
3. `max_age_days` 非正整数（≤ 0，或无法转换为整数）
4. `partition` 是绝对路径，或 resolve 后逃逸 repo（先单独判定绝对路径，是因为
   pathlib `repo / "/abs/path"` 会静默丢弃 `repo` 前缀直接变成 `/abs/path` ——
   不能指望后续 `is_relative_to` 兜住这个陷阱）
5. `enabled_when` dotted-path 中间段命中了一个非 dict 值（如某中间段本身取值
   不是对象）。这一形态**只能在读到真实 `.aria/config.json` 内容后**才能判定，
   因此判定位置与前四种不同（前四种在 `validate_descriptor` 里就地判定；这一种
   在 `probe()` 内部，逐级 `.get`/`isinstance` 防御，不落外层异常兜底）

## outcome 对声明作者意味着什么

| outcome | 何时发生（概览） | 对归档 verdict 的影响 |
|---------|-----------------|----------------------|
| `pass` | 新鲜度窗口内 ≥1 条 `source=="production"` 记录 | 不变 + 绿色 note |
| `warn` | 分区缺失 / 分区存在但读不了（IO error）/ 全部记录已过窗口期 / 只找到非生产记录 | 抬到至少 `warn`（已是 `block` 的不受影响） |
| `skipped` | `enabled_when` 开关为关；或 `.aria/config.json` 缺失/读不到（保守当关处理，不 warn） | 不变 + 低调 note |
| *（声明本身无效）* | 文本层拒绝形态之一，或值层无效形态之一 | 同 `warn`（"无法核验"） |

探针结果**永不**让 verdict 升级到 `block`，也永不覆盖已有的 `block`。三态判定的
完整实现语义见 `lib/runtime_probe.py` module docstring；归档时是否落盘、落哪几个
字段、与 `unverified_claims` 的关系，由 [openspec-archive SKILL.md §Step
1-2](../../openspec-archive/SKILL.md) 承载（本文档不重复）；D.2 收尾时的消费入口
见 [phase-d-closer SKILL.md](../../phase-d-closer/SKILL.md)。

## 书写惯例：活跃期自写，不回改已封存归档

声明的**正常家是 spec 活跃期**，由作者在 `proposal.md` frontmatter 里自己写。
spec 归档时，声明随整个文件移入 `openspec/archive/`，自然带入 —— 不需要任何
额外动作。

**不回改已经封存的归档 proposal.md 去补声明**（owner 决策 2026-07-05）—— 对齐
既有 ERRATA 惯例"不修改归档 proposal 本体"。这意味着：截至本文档撰写时全部已
归档 spec（含 coordination 自身的 `interactive-session-dedup-coordination`）都
保持**无声明**状态，不会被回填。未来第一个真实声明者，会是下一个**自带
telemetry 分区**的**活跃**中 spec。

## Known tradeoff：整读非流式

探针每次调用对 telemetry 分区执行**一次性整读**（`read_text()` 后逐行
`json.loads`），不做流式/分块处理。这依赖分区体量保持较小 —— telemetry 的
**修剪/轮转是显式 out-of-scope**，若未来某分区增长到不适合整读的规模，需要
另行设计（不在本机制覆盖范围内）。

## 相关文档

- `openspec/changes/runtime-probe-archive-gate-integration/proposal.md`（主仓，
  当前位置，归档后移至 `openspec/archive/`）—— §What Changes 1/2，决策 SOT
- `lib/runtime_probe.py` —— `validate_descriptor`（值层）+ `probe`（三态判定）
  实现与 module docstring
- `lib/frontmatter_block.py` —— `extract_runtime_probe` 文本层解析实现与
  module docstring
- [openspec-archive SKILL.md](../../openspec-archive/SKILL.md) —— Step 1 gate
  契约（`--gate` JSON schema）+ Step 2 归档写入契约（`warn_overlay`）
- [phase-d-closer SKILL.md](../../phase-d-closer/SKILL.md) —— D.2 gate 消费点

---

**最后更新**: 2026-07-08（`runtime-probe-archive-gate-integration`，#95 follow-up A，首次创建）
