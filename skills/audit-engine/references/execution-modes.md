# audit-engine Execution Flow & Modes

> 完整执行流程: 入口逻辑 → pre_merge gate → convergence/challenge 模式。从 SKILL.md §执行流程 提取 (iter-2, 2026-05-28)。

## 入口逻辑

```
1. 读取配置: config-loader → audit.* 块
   - audit.enabled == false → 静默返回
   - checkpoint 未启用 → 静默返回

2. 确定模式:
   - mode 参数显式指定 → 使用指定值
   - audit.mode == "adaptive" → 按 adaptive_rules 推导
   - checkpoints 显式配置 > adaptive_rules 推导 > 默认 off

3. 加载 Agent 分组:
   - agents_config 参数 > config.json teams[checkpoint] > 默认分组

4. 执行审计 (按模式分支)
```

## Pre-merge: Checkpoint Report Completeness Gate

> **新增**: 2026-04-23, 修复 Forgejo Issue #26 checkpoint 完整性 gate — 与 Issue #27 (change_id dangling reference gate, 见 [pre-write-validation.md](./pre-write-validation.md)) 互补。
>
> **#26 + #27 互补说明**:
> - **#26 (本节)** = 横向完整性 — 该跑的 checkpoint 都跑了 (completeness)
> - **#27 (写盘前)** = 纵向真实性 — 报告引用的 change_id 都真实存在 (authenticity)
> 两者均在 pre_merge 阶段运行, 错误输出均走 audit trail。

**触发条件**: 仅在 `checkpoint == "pre_merge"` 时执行, 在调用任何 Agent 之前运行。

```
Checkpoint Report Completeness Gate (pre_merge 专属):

  Step 1: 读取配置
    config-loader → audit.checkpoints.*
    config-loader → audit.allow_incomplete_checkpoints (默认 false)

  Step 2: 豁免检查
    如果 audit.allow_incomplete_checkpoints == true
      → 跳过校验, 继续执行 pre_merge 审计
      → 记录 [WARN] incomplete checkpoint gate bypassed by config, 写入 audit trail

  Step 3: 枚举需校验的 checkpoint
    对 audit.checkpoints 中每个 key, 满足以下全部条件则纳入校验:
      - value == "on"(字符串)或 value 为非 "off" 的模式字符串
      - key != "pre_merge"(排除自身)
      - key != "post_closure"(事后审计, 不做前置依赖)
      - key != "mid_post_spec"(Aria #79: 事件条件触发, 启用但无漂移时合法
        不产出报告 → 不做前置依赖, 否则启用即会误阻 pre_merge)

  Step 4: 检查报告文件存在性
    对每个纳入校验的 checkpoint_name:
      扫描目录: {project_root}/.aria/audit-reports/
      匹配模式:
        - {checkpoint_name}-*.md         (无 change_id 变体)
        - {checkpoint_name}-*-*.md       (含 change_id 变体)
      任意文件匹配 → 该 checkpoint 通过
      无文件匹配   → 记录为 missing_checkpoint

  Step 5: 校验结果路由
    missing_checkpoints 为空 → 校验通过, 进入正常 pre_merge 审计流程
    missing_checkpoints 非空 → 拒绝执行 pre_merge 审计, 输出 ERROR (见下方), 中止
```

**校验失败输出**:

```
ERROR: pre_merge audit 前序 checkpoint 报告缺失:
  - {checkpoint_name} 配置 "on" 但未找到 .aria/audit-reports/{checkpoint_name}-*.md
  [若多个缺失则逐行列出]

Fix 任一:
  1. 补跑缺失 checkpoint 审计 (对应 Phase Skill 重新调用)
  2. 在 .aria/config.json 将该 checkpoint 改为 "off" (若本轮确实不需要)
  3. 在 .aria/config.json 设 audit.allow_incomplete_checkpoints: true
     (不推荐, 豁免需 audit trail 记录 [WARN])
```

**豁免设计原则**: `allow_incomplete_checkpoints` 默认 `false`, 需在 `.aria/config.json` 显式声明才能开启。豁免模式下 pre_merge 审计继续执行, 但 audit trail 必须记录 `[WARN] incomplete checkpoint gate bypassed: missing={checkpoint_names}`。

## Convergence 模式

全员讨论 → 汇总引擎 → 结论提取 → 四元组比较 → 收敛/振荡检测。

```
Round N:
  每轮入口: 竞品 spec 探针 —— python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/audit-engine/scripts/sibling_spec_probe.py" --own-spec-dir "<本轨 spec 目录名>" --repo-path "<repo root>"
  读 stdout JSON 的 verdict: sibling_found ⇒ 本轮 🔴 (含 N 份/归档标注) · no_sibling_found ⇒ 「已完整扫描, 未发现同 issue 竞品」 · not_established / exit≠0 / 非 JSON / schema_version 未知 ⇒ 「未能核实」(禁止渲染为无竞品); 不阻断本轮
  1. 调用 agent-team-audit 单轮引擎
     - spawn Agent team (convergence_agents)
     - 各 Agent 独立分析
     - 返回原始 issues 列表

  2. 汇总引擎处理
     - 合并所有 Agent 输出
     - 去重: 基于 {category, scope} (复用 agent-team-audit 算法)
     - 冲突标记: 同 scope 矛盾意见保留双方, 标记 conflicted
     - 结构化提取: 转换为结论记录 (见数据 Schema)

  3. 收敛判定 (详见收敛判定算法)
     - 四元组集合比较: Round N vs Round N-1
     - 振荡检测: Round N vs Round N-2
     - 全票 PASS 检查

  4. 路由:
     收敛 → 计算 verdict → 生成审计报告
     振荡 → 取最后轮结论 → 报告 + 振荡标记
     未收敛 + 有余量 → Round N+1
     未收敛 + max_rounds 耗尽 → 降级策略
```

## Challenge 模式

讨论组提案 → 挑战组质疑 → 全员合并 → objections resolved 判定。

```
Round N (一个完整周期):
  每轮入口: 竞品 spec 探针 —— python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/audit-engine/scripts/sibling_spec_probe.py" --own-spec-dir "<本轨 spec 目录名>" --repo-path "<repo root>"
  读 stdout JSON 的 verdict: sibling_found ⇒ 本轮 🔴 (含 N 份/归档标注) · no_sibling_found ⇒ 「已完整扫描, 未发现同 issue 竞品」 · not_established / exit≠0 / 非 JSON / schema_version 未知 ⇒ 「未能核实」(禁止渲染为无竞品); 不阻断本轮
  Step 1: 讨论组 spawn → discussion_output
     - proposal (统一提案文本)
     - decisions [{severity, category, scope, summary}]
     - rationale [string]

  Step 2: 挑战组 spawn (输入: discussion_output) → challenge_output
     - objections [{agent, target_decision, severity, point, status: "new"}]

  Step 3: 全员讨论 (输入: discussion_output + challenge_output) → 修正 proposal

  Step 4: 挑战组再审 (输入: 修正 proposal) → 更新 objections status
     - status: new → resolved | overruled

  Step 5: Drift Check (详见 challenge-mode-schema.md)
     - drift-checker 按 anchor 对 decisions ∪ objections 分类 → drift_ratio → 三档处置 (#17)

  收敛判定:
     - 提案结论四元组集合无变化 (vs Round N-1)
     - AND objections 全部 status=resolved (无 unresolved)
     - 满足 → 生成审计报告
     - 不满足 → Round N+1 或降级策略
```

**Round 计数**: 一个 Round = 讨论组提案 + 挑战组质疑的完整周期。全员合并讨论属于下一 Round 的开头。max_rounds=5 意味着最多 5 个完整周期。

详细 Schema 见 [challenge-mode-schema.md](./challenge-mode-schema.md)。

## 竞品 spec 探针 (per-round 入口)

> Spec: `openspec/changes/sibling-spec-probe/proposal.md` §3–§10 (主仓)。本节是探针 **stdout 契约 + exit code + 消费措辞的权威可执行版**; SKILL.md 「per-round 入口探针」小节只放概述与指针。上方 Convergence / Challenge 两个围栏块内各有一条同字面的两行调用串 (机械护栏 SC-17 计数恰 2), 本节**不**复用那个前缀。

**为什么每轮跑, 为什么两个模式块都改**: 探针看的是远端仓里已落盘的 proposal 语料 (`openspec/changes/*/proposal.md` + `openspec/archive/*/proposal.md`, 全部 `refs/heads/*`), 与 claim 通道没有共享失效模式 —— 对方没走认领、或已 ship 归档时, 只有语料通道还能把「这件事别人做完了」摆到台面上 (Spec §Why 第 5 次事故)。审计跨天时首轮结论会陈旧, 所以每轮入口重跑 (不复用 `remote_refresh` 缓存, P3)。`config-loader/DEFAULTS.json` 的 `adaptive_rules.level_3 = "challenge"` 让下游 Level-3 审计走 Challenge 块, 只 patch Convergence 会让那些项目静默漏掉探针。它与 Step 0 (Anchor 固化, Round 1 启动前一次性) 是两回事, 不沿用 Step 编号。

**调用** (每轮入口, Round 1 含):

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/audit-engine/scripts/sibling_spec_probe.py" \
  --own-spec-dir "<本轨 spec 目录名>" --repo-path "<repo root>"
```

- `--own-spec-dir` = 本轨 `openspec/changes/<目录名>` 的目录名 (自命中排除键); `--repo-path` = 仓库根 (探针不假定 cwd)。
- 探针自带 fetch (`--no-tags --prune`, 写进私有命名空间 `refs/aria/sibling-probe/<remote>/<branch>`, 不动 `refs/remotes/*`), 每个 git 子进程 30s, fetch 腿最多 2 次; 双远端一轮约 25s (Spec §5), 这是本探针的成本, 不称轻量。

**stdout — 恰一个 JSON 对象 (schema_version "1")**:

| 字段 | 类型 | 语义 |
|---|---|---|
| `schema_version` | str | 固定 `"1"`; 未知值 ⇒ 按「未能核实」处置 |
| `probe` | str | 固定 `"sibling_spec_probe"` |
| `status` | str | 运行面 (覆盖是否完整): `ok` \| `degraded` \| `skipped` |
| `reason` | str \| null | `status != "ok"` **或** `verdict == "not_established"` 时必非空: `no_enforced_remote` \| `remote_unresolved` \| `fetch_failed` \| `cap_applied` \| `own_token_absent` |
| `verdict` | str | 判定面 (一等字段): `sibling_found` \| `no_sibling_found` \| `not_established` |
| `own_spec_dir` | str | 本轨 spec 目录名 |
| `own_layer` | str | 本轨 proposal 走的层: `canonical` \| `none_sentinel` \| `url_fallback` \| `no_token_no_url` \| `no_field` \| `bad_token_union` |
| `own_keys` | list | 本轨比较键, 每项 `["k", <repo basename>, <n>]` 或 `["r", <原串>]` |
| `remotes` | list[obj] | 每 remote: `name` / `default_branch` (str\|null, 只认 `ls-remote --symref`, 不猜) / `resolved_by` (`ls_remote_symref`\|null) / `error_kind` (str\|null) / `scanned` / `capped` / `refs_scanned` / `stale_skipped` |
| `hits` | list[obj] | **恒为 list**; 每项 `remote` / `branch` / `corpus` (`changes`\|`archive`) / `spec_dir` / `path` / `field_line` / `key` / `layer` / `refs` (`<remote>/<branch>` 全部命中处, 字节序) |
| `caps_applied` | list[obj] | 每项 `remote` / `kind` (`proposals`\|`refs`) / `total` / `kept` / `dropped_from` |
| `elapsed_ms` | int | 探针总耗时 |

`error_kind` 封闭集合: `network` / `auth_403` / `non_ff` / `git_missing` / `other` (形态照 `phase-d-closer/scripts/fetch_gate.py::_classify_error`) + `timeout` / `no_symref` / `bad_symref_prefix`; git 原始 stderr 永不回显 (Rule #7)。

**`verdict` 取值表** (消费方**不得**从 `hits == []` 推断结论 —— 「扫完没有」与「没扫到 / 本轨无输入」在 `hits` 上取值相同):

| `verdict` | 何时 |
|---|---|
| `sibling_found` | `hits` 非空 (即使 `status == "degraded"`: 正证据不因覆盖不完整而降级, 此时 `reason` 说明缺口) |
| `no_sibling_found` | `hits` 为空 **且** 覆盖完整 (全部 enforced remote 解析出默认分支、fetch 成功、全部 `refs/heads/*` 已枚举、无任何 cap) **且** `own_keys` 非空 |
| `not_established` | 其余: `own_keys` 为空 (本轨无可比较输入, 典型: 字段值为哨兵 `none` / `无`, 或无字段) / 任一 remote 未解析或 fetch 失败 / 任一 cap / enforced 集合为空 |

**exit code**: `0` = 探针完成了一次有定义的判定 (命中与不命中都是 0; `degraded` / `skipped` 也是 0); 非 `0` = 仅探针自身失败 (参数错 / 内部异常 / 仓库不可读), 此时 stdout 不保证是 JSON。

**消费措辞 (三档, 不得合并)** —— 写进当轮 `### Round N` 记录 (模板见 [report-format.md](./report-format.md)) 并进聚合报告; N = 去重后的 `spec_dir` 数 (同一 Spec 在 origin/github 两镜像各成一条 `hits[]` 项, 计数须去重):

| `verdict` | 措辞 |
|---|---|
| `sibling_found` | 「🔴 检测到 N 份同 issue 的竞品 Spec: <spec_dir 列表>」; 命中项 `corpus == "archive"` 时标注**「已完成的 Spec」**; `status == "degraded"` 时追加「(覆盖不完整: <reason>)」 |
| `no_sibling_found` | 「本轮已完整扫描, 未发现同 issue 竞品」 |
| `not_established` | 「**未能核实** —— 本轮竞品扫描未取到完整证据 (原因: <reason>)」; **禁止**渲染为「无竞品」 |

**消费方 fail-closed 义务**: `exit != 0` **或** stdout 无法解析为 JSON **或** `schema_version` 未知 ⇒ 一律按 `not_established` 处置 (渲染「未能核实」)。

**不阻断**: 探针是 advisory 副机制 —— 不改 verdict 计算、不改收敛判定、不改轮次路由; 「同 issue」≠「重复劳动」(Spec §Why 的 `#137` 簇是有意拆分), 命中是告警不是判决, 由人一眼可辨。
