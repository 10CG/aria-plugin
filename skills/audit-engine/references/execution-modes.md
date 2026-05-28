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
  Step 1: 讨论组 spawn → discussion_output
     - proposal (统一提案文本)
     - decisions [{severity, category, scope, summary}]
     - rationale [string]

  Step 2: 挑战组 spawn (输入: discussion_output) → challenge_output
     - objections [{agent, target_decision, severity, point, status: "new"}]

  Step 3: 全员讨论 (输入: discussion_output + challenge_output) → 修正 proposal

  Step 4: 挑战组再审 (输入: 修正 proposal) → 更新 objections status
     - status: new → resolved | overruled

  收敛判定:
     - 提案结论四元组集合无变化 (vs Round N-1)
     - AND objections 全部 status=resolved (无 unresolved)
     - 满足 → 生成审计报告
     - 不满足 → Round N+1 或降级策略
```

**Round 计数**: 一个 Round = 讨论组提案 + 挑战组质疑的完整周期。全员合并讨论属于下一 Round 的开头。max_rounds=5 意味着最多 5 个完整周期。

详细 Schema 见 [challenge-mode-schema.md](./challenge-mode-schema.md)。
