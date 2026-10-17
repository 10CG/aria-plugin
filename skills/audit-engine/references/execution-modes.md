# audit-engine Execution Flow & Modes

> 完整执行流程: 入口逻辑 → pre_merge gate → convergence/challenge 模式。从 SKILL.md §执行流程 提取 (iter-2, 2026-05-28)。

## 入口逻辑

```
1. 读取配置: config-loader → audit.* 块
   - audit.enabled == false → 静默返回
   - checkpoint 未启用 → 静默返回 ——「是否启用」按本步五档优先级链判定 (first-match, 命中即止;
     与 phase-c-integrator/SKILL.md C.2 pre_hook 步骤 3「按优先级链判定 pre_merge 是否启用」共用
     同一条, 调用方据此判断是否调用 completeness gate 本身):
     - 级 1: 原始 audit.checkpoints (经旧配置兼容映射、未经 config-loader 第 4 步验证、也未与
       DEFAULTS.json 合并的视图, 用于区分「用户显式 off」与「DEFAULTS 填的 off」) 中该 checkpoint
       自身有显式键 → 取其值, 到此为止 (非 "off" → 可能启用, 照常进入; "off" → 静默返回)
     - 级 2a: 否则 (以下读 config-loader 合并视图) audit.mode == "adaptive" → 取 adaptive_rules
       上界 (checkpoints 显式值 > adaptive_rules 推导值 > 默认 off; 入口层不解析被审 change 的
       OpenSpec Level, 故三档中只要有一档非 "off" 即视为可能启用、照常进入该 checkpoint 的执行
       流程, 由 completeness gate 在 §1.4 做精确分格)
     - 级 2b: 否则 audit.mode == "convergence" → 视为启用, 照常进入 (config-example.md 对
       convergence/challenge 逐字是「所有检查点强制使用该模式」)
     - 级 2c: 否则 audit.mode == "challenge" → 同 2b
     - 级 2d: 否则 audit.mode == "manual" → 视为 "off", 静默返回
     - 级 3: 否则 (audit.mode 不属上述四值枚举) → 照常进入, 交由 completeness gate 判
       config_unreadable —— 本层读的是 config-loader 合并视图; 按该表, 验证会对非法值告警并
       回落缺省 (config-loader/SKILL.md §错误处理 未就此场景逐字写明, 属推断), 真正可能撞到
       这一档的是直读原始 config、不经 config-loader 校验的 completeness gate 本身。三个非
       排除 checkpoint 都已显式且纳入集非空时, mode 写错也不会被 completeness gate 暴露 (格
       SC-15.10-typo-mode-lazy-when-inclusion-nonempty 锁住), 不改变其它 checkpoint 的处置

2. 确定模式 (为该 checkpoint 的实际执行选 mode, 此时具体是哪个 change 已明确; 与上方「是否启用」
   共用级 1, 但 2a 不取上界 —— 直接按该 change 的 Level 精确推导 (Level 取不到时例外,
   按下方「Level 取不到时不当 "off"」一条取值), 见上方 Step 1 括注):
   - mode 参数显式指定 → 使用指定值
   - audit.mode == "adaptive" → 按 adaptive_rules 推导
   - checkpoints 显式配置 > adaptive_rules 推导 > 默认 off
   - Level 取不到时不当 "off": 三种来源 —— spec_level_undetermined (Level 解析不出:
     proposal 无 Level 行 / Level 行存在但取不出 1-3 / proposal.md 缺失或不可读) 被
     allow_incomplete_checkpoints 豁免为 bypassed、allow_dangling_change_ids 的
     dangling-skip、其余 Level 解析失败但不短路 —— 一律按档位取值: adaptive 档取
     adaptive_rules 三档的上界 (最严的非 "off" 值, 默认配置 = challenge; 三档全 "off"
     时上界即 "off", 不执行); convergence / challenge 档取档位值本身 (dangling 的
     change_id 不改变本步取值); manual 档取 "off"。依据: 两个宽松开关是放宽检查,
     不是关掉动作 (audit-engine SKILL.md 配置注释「开启后 pre_merge 仍执行」「开启后
     写盘仍执行」); Level 不知道不等于 owner 配了 off (owner 裁定, 2026-10-15)
   - 多 change 归约: 作用域含多个 change 时逐 change 按上述规则 (含上一条 Level 取不到
     的取值) 精确推导后归约 —— 任一 change 非 "off" ⇒ 该 checkpoint 的审计执行, 归约
     模式取各 change 精确结果中最严的非 "off" 值 (严格度序 off < convergence <
     challenge); 全部为 "off" 才不执行。与 Pre-merge 门侧 §1.4 的前置归约 R-1 / R-2
     同口径 (owner 裁定, 2026-10-15)
   - 本步精确推导的结果若为 "off" ⇒ 不执行该 checkpoint 的审计; 对 pre_merge 而言, completeness
     gate 仍照常运行 (不受本步推导结果影响), 其 fail/error 仍按下方 Pre-merge 节 Step 5 阻塞;
     本条只决定门放行之后是否进入 Convergence/Challenge 流程 —— mode 非 off 时放行后进入该
     流程, 精确推导为 off 时放行后 (即便 completeness gate 已判 verdict=pass, 如 Pre-merge 节
     §1.4 的格 D / 格 E) 也不进入: 门的 pass 只确认前置 checkpoint 证据齐全, 不代表 pre_merge
     本身该跑 (两者正交, 见下方 Pre-merge 节 Step 5)
   - 上条括注里的格 E 例子按「Level 取不到时不当 "off"」一条归约 —— adaptive 档取上界、
     convergence / challenge 档取档位值, 归约后通常非 "off"、会进入审计; 仅 manual 档与
     三档全 "off" 的 adaptive 配置归约后仍为 "off"。格 E 的门侧 [INFO] 行文案 (「pre_merge
     取 "off"」) 描述的是门内逐对解析, 不是本步取值

3. 加载 Agent 分组:
   - agents_config 参数 > config.json teams[checkpoint] > 默认分组

4. 执行审计 (按模式分支)
```

## Pre-merge: Checkpoint Report Completeness Gate

> Spec: `openspec/changes/pre-merge-completeness-gate-change-scope/proposal.md` §1–§4
> (主仓)。本文件中 §1.1–§1.4 与 SC-N 均指该文件的对应小节/编号 (不限本节之后 —— 上方「入口
> 逻辑」的两道启用守卫与「确定模式」同样适用); 本节是其**权威可执行版**。
>
> **新增**: 2026-04-23, 修复 Forgejo Issue #26 checkpoint 完整性 gate — 与 Issue #27 (change_id dangling reference gate, 见 [pre-write-validation.md](./pre-write-validation.md)) 互补。
>
> **#26 + #27 互补说明**:
> - **#26 (本节)** = 横向完整性 — 该跑的 checkpoint 都跑了 (completeness)
> - **#27 (写盘前)** = 纵向真实性 — 报告引用的 change_id 都真实存在 (authenticity)
> 两者均在 pre_merge 阶段运行, 错误输出均走 audit trail。完整性门自本 spec 起带 change 维度。

**触发条件**: 仅在 `checkpoint == "pre_merge"` 时执行, 在调用任何 Agent 之前运行。

```
Checkpoint Report Completeness Gate (pre_merge 专属):

  Step 1: 读取配置
    config-loader → audit.checkpoints.*
    config-loader → audit.allow_incomplete_checkpoints (默认 false)
    脚本侧等价实现: 直读 .aria/config.json + 内联缺省与旧配置兼容映射 (config-loader 无程序化入口), 相等性由 SC-21 锁

  Step 2: 豁免检查
    如果 audit.allow_incomplete_checkpoints == true
      → 仍逐对评估三态并全部留痕, 只把 missing / scope_unresolved / spec_level_undetermined / no_spec_unverifiable 降为 verdict=bypassed (exit 0) 并短路终止求值; no_spec_contradicted / change_id_unanchored 不被本键豁免
      → 记录 [WARN] incomplete checkpoint gate bypassed: missing={cp}@{change_id},... ; scope_unresolved={0|1}, 写入 audit trail

  Step 3: 枚举需校验的 checkpoint
    对每个 (checkpoint, change_id) 对, 按 §1.3 五档优先级链 (first-match, 命中即止) 解析
    resolved_mode: 级 1 对原始 audit.checkpoints (经旧配置兼容映射、未经 config-loader 第 4 步
    验证、也未与 DEFAULTS.json 合并的视图) 求该 checkpoint 是否有显式键; 级 2a 起读「原始 + 旧
    配置兼容映射 + 内联缺省」后的合并视图 (completeness gate 自身内联实现, 不经 config-loader
    第 4 步验证 —— 与入口逻辑级 3 读的「经校验」合并视图是两个不同的视图, 见上方 Step 1「脚本侧
    等价实现」) —— mode == "adaptive" 时只在落到本档才去读该 change 的 proposal.md 解析
    OpenSpec Level N (按需/惰性, 不是上方「是否启用」判定取的上界), 取 adaptive_rules.level_N;
    mode == "convergence"/"challenge" 分别取该值; mode == "manual" 取 "off"; mode 不属四值
    枚举 → error_kind=config_unreadable, exit 2 (未经校验的非法值才会真正撞到这一档)。
    allow_dangling_change_ids=true 时: 级 1 (explicit) 不受影响; 该 change_id 锚点缺失 (S1 已知)
    对级 2b/2c/2d/级 3 一律先于其各自分支求值即短路取 resolved_mode="off"、
    enabled_by="dangling-skip" (不再按 mode 正常取值); 落到级 2a (mode == "adaptive") 时, 锚点
    缺失与 Level 解析失败 (按需/惰性解析该 change 的 proposal.md, 非 adaptive 档不解析 Level)
    由同一次 Level 解析调用发现、不做区分, 同样取 resolved_mode="off"、
    enabled_by="dangling-skip"。pre_merge 本身未显式配置时, 该 id 的纳入集因此只剩 explicit
    档非 off 的键, 空纳入集落 §1.4 格 E (pre_merge 本身若显式配置, 按其自身解析结果走, 不受此
    限)。满足以下全部条件则纳入校验:
      - resolved_mode == "on"(字符串)或 resolved_mode 为非 "off" 的模式字符串
      - key != "pre_merge"(排除自身)
      - key != "post_closure"(事后审计, 不做前置依赖)
      - key != "mid_post_spec"(Aria #79: 事件条件触发, 启用但无漂移时合法
        不产出报告 → 不做前置依赖, 否则启用即会误阻 pre_merge)
      - key != "mid_implementation"(audit.mid_implementation 的 threshold=50 为任务进度阈值,
        事件条件触发, 启用但进度未过阈值时合法不产出报告 → 不做前置依赖, 否则启用即会误阻 pre_merge)
      - key != "post_brainstorm"(brainstorm 为 A.0.5 可选阶段, 事件条件触发, 启用但本轮未跑
        brainstorm 时合法不产出报告 → 不做前置依赖, 否则启用即会误阻 pre_merge)

  Step 4: 调用 completeness gate 机械执行器
    python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/audit-engine/scripts/completeness_gate.py" \
      --repo-path "<主仓 root>" --diff-repo-path "<C.2 合并目标仓 root>" \
      --base "<diff 仓主干的远程跟踪 ref>" [--anchor-base "<主仓主干的远程跟踪 ref>"] \
      [--change-id <id> ...] [--no-spec]

    报告归属匹配规则 (§1.2, 全部机械结构事实, 无 AI 价值判断; 令 C = openspec/changes/* ∪
    openspec/archive/* 下去掉 YYYY-MM-DD- 前缀的 id 全集, 不是本轮纳入校验的作用域子集): 文件 f
    归属 (checkpoint, change_id) 当且仅当全部成立 —— f 以 "{checkpoint}-" 开头且以 ".md" 结尾;
    f 含 "-{change_id}-" 或去掉 ".md" 的主干以 "-{change_id}" 结尾 (双侧界定或末段界定, 逐字
    大小写敏感, 不归一化); 且不存在 C 中另一个 id 的匹配子串整体包含本 change_id 匹配子串的碰撞
    (有界包含排除, 对称)。不要求 "-R\d+-" 段, 不解析时间戳与 role。真 2-field 旧 schema 计入
    excluded_legacy_count; 以 "{checkpoint}-" 开头但按上述规则对 C 中任何 id 都不命中的计入
    unattributed_count (文件名进 audit trail); 两个计数不得混计; 子目录内的报告 (只扫顶层,
    scanned_dir_depth=1) 与不以任何 checkpoint 名开头的文件 (如 *-audit-trail.md 族) 三个桶
    都不收 (详见 report-storage.md §向后兼容)。

    per (checkpoint, change_id) 三态判定 (§1.3, 按序 first-match, 迭代口径 = 逐对不是叉乘):
      - present: 上述归属匹配规则命中 ≥ 1 份
      - not_applicable: (a) scope_source=no_spec (--no-spec 且核验通过); 或 (b) checkpoint=
        post_implementation 且 --diff-repo-path 与 --repo-path 的 git toplevel 相同 (同仓;
        跨仓/子模块合并形态下 (b) 通道结构上禁止触发, 一律落 present/missing —— 主仓 diff 的
        路径形态无法代表子模块内的实现工序) 且 diff 非空且全部变更路径都在
        openspec/changes/{作用域内任一 id}/** 或 .aria/audit-reports/** 之下 (Phase A-only); 或 (c)
        checkpoint=post_planning 且该 change 不存在任何 A.2 产物 (无
        tasks.md/detailed-tasks.yaml 且 proposal.md 无 ## Tasks 小节)
      - missing: 其余 (含 diff 为空的情形, 空集不放行)

    stdout 契约 (§1.4): 人读行 ([OK]/[INFO]/[WARN]/ERROR) 一律走 stderr; stdout 恰一个 JSON
    对象 (schema_version "1", gate "completeness_gate"), 顶层键集逐字 16 项 —— schema_version /
    gate / verdict / error_kind / scope_source / change_ids / checked_checkpoints /
    no_prior_checkpoints / results[] / excluded_legacy_count / unattributed_count /
    unattributed / scanned_dir_depth / scan_status / bypassed / elapsed_ms。verdict 四态:
    任一 missing → fail, exit 1; 全部 present/not_applicable → pass, exit 0; 豁免 → bypassed,
    exit 0; 输入/环境错 → error, exit 2。

  Step 5: 校验结果路由
    verdict == "pass" 或 "bypassed" → 门放行 (前置 checkpoint 证据齐全或已豁免); 放行后按上方
      入口逻辑「2. 确定模式」对 pre_merge 本身精确推导: mode 非 "off" → 进入正常 pre_merge 审计
      流程; 按该 change 的 Level 精确推导为 "off" ⇒ 不执行 pre_merge 审计, 门已判 pass (如
      §1.4 格 D / 格 E) 亦同 —— 门放行只代表前置证据齐全, 不代表 pre_merge 本身该跑
      (上句括注里的格 E 例子同样按入口逻辑「Level 取不到时不当 "off"」归约, 通常非 "off"; 调用方 phase-c-integrator 步骤 5 对精确推导为 "off" 的一支按 on_skip 继续合并, 见其 SKILL.md)
    verdict == "fail" 或 "error" → 拒绝执行 pre_merge 审计, 输出 ERROR (见下方), 中止
    消费方 fail-closed 义务: exit≠0 或 stdout 非 JSON 或 schema_version 未知 ⇒ 按 fail 处置 (拒绝执行 pre_merge 审计, 输出 ERROR), 不得按 PASS
```

**三态校验结果输出模板**:

```
ERROR: pre_merge audit 前序 checkpoint 报告缺失: {cp}@{change_id} 配置 "{mode}" 但未找到
  .aria/audit-reports/ 下含 "-{change_id}-" 或以 "-{change_id}.md" 结尾的 {cp} 报告
  (真 legacy 不计入: N; 归属不明: M, 见下方清单)
  [若多对缺失则逐对列出]

Fix 任一:
  1. 补跑缺失 checkpoint 审计 (对应 Phase Skill 重新调用)
  2. 或在 audit.checkpoints 里显式写该 checkpoint
     (adaptive 推导出的 checkpoint 其报告在产出侧调用链上不产出, 重新调用 Phase Skill 会再次早退)
  3. 把该 checkpoint 改为 "off" (若本轮确实不需要)
  4. 临时开 audit.allow_incomplete_checkpoints: true
     (不推荐, 豁免需 audit trail 记录 [WARN]; no_spec_contradicted / change_id_unanchored 不被本键豁免)

unattributed_count > 0 时另起一行 (全局一行, 不按 checkpoint 重复, 与 §1.2 计数表逐字同一句):
  [WARN] unattributed reports (checked={cp1},{cp2},…): N 份 — <按字典序前 20 个文件名>
  [, … 其余 K 份见 stdout 的 `unattributed`]
  (连接符钉死: checked= 后的 checkpoint 名之间、20 个文件名之间, 一律半角逗号 + 一个空格 ", ")

not_applicable (必须 surface, 不得折叠进「校验通过」):
  [INFO] completeness gate: {cp}@{change_id} not_applicable ({reason}); 依据 = <按 reason
  三选一机械事实: diff N 文件全部在 openspec/changes/{id}/ 或 .aria/audit-reports/ 下 (Phase
  A-only) | 无 tasks.md/detailed-tasks.yaml 且 proposal.md 无 ## Tasks 小节 | --no-spec 且
  diff 不触 openspec/changes/>
  (S3 场景 change_id 为 null 时该行渲染为 "{cp} (无 change_id)", 不渲染 "@null")

present (逐行列出, 使「通过」可核对归属):
  [OK] {cp}@{change_id}: N 份
```

**豁免设计原则**: `allow_incomplete_checkpoints` 默认 `false`, 需在 `.aria/config.json` 显式声明才能开启。豁免模式下 pre_merge 审计仍逐对评估三态并全部留痕, 只把 missing / scope_unresolved / spec_level_undetermined / no_spec_unverifiable 降为 bypassed 并短路终止求值 (no_spec_contradicted / change_id_unanchored 不被本键豁免), audit trail 必须记录 `[WARN] incomplete checkpoint gate bypassed: missing={cp}@{change_id},... ; scope_unresolved={0|1}`。

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
