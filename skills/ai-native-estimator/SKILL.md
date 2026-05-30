---
name: ai-native-estimator
description: |
  Token 轴工作量估算 (v1)。基于历史 cycle 的 token 消耗 (runtime-truth from transcript)
  估算 spec_level 工作量, 替代传统 4-8h 人工时假设。提供 forecast / history / velocity 查询;
  采集由 phase-d-closer 收尾自动触发。使用场景: "估算工作量", "token velocity",
  "这个 Spec 大概多少 token", "历史 cycle 消耗"。
allowed-tools: Bash, Read
---

# ai-native-estimator

## 用途

让 aria 用 **Token (AI 侧真实工作量, runtime-truth)** 而非传统 4-8h 人工时估算 cycle 工作量
(#18: 1 Human + Claude Code 模式下传统估算失效, 同一小时 AI 可产出 1 行或 1000 行)。

**v1 = Token 轴薄切片**: phase-d 收尾自动采集每 cycle 的 token 消耗 → `.aria/estimator/variance.jsonl`;
按 `spec_level` 聚类, 提供 forecast/history/velocity。Attention 轴 + L1/L2 预估 + task-planner 集成
defer v2 (见 [DEC-20260530-001](../../../.aria/decisions/2026-05-30-ai-native-estimator-v1-architecture.md))。

底层复用 internal skill [aria-token-telemetry](../aria-token-telemetry/SKILL.md) 的 `iter_transcript_usage()`。

---

## 何时使用

- 用户问"这个 Spec 大概多少 token / 多大工作量" → `forecast`
- 查历史 cycle 消耗 / 趋势 → `history` / `velocity`
- (采集**自动**发生在 phase-d-closer 收尾, 无需手动调 `capture`)

---

## 查询

```bash
EST="${CLAUDE_PLUGIN_ROOT:-aria}/skills/ai-native-estimator/scripts/estimator.py"

python3 "$EST" --project-root . forecast --spec-level 2   # 估算 L2 cycle work_metric
python3 "$EST" --project-root . history                    # 全部 variance 记录
python3 "$EST" --project-root . velocity --window 10       # 最近 10 cycle 趋势
```

### forecast 解读

| 响应 | 含义 |
|------|------|
| `{status:"ok", median_work_metric, n}` | N≥`min_samples`(默认3) 同 spec_level 历史 → median (可信) |
| `{status:"insufficient", have, need, bootstrap, uncalibrated:true}` | 样本不足 → 返回 **uncalibrated** bootstrap 种子 (仅参考, 别当真值) |
| `{status:"insufficient", reason:"no_spec_level"}` | 无 spec_level (forecast(None) 或无 Spec cycle) |

> **cross-level 隔离**: L1 样本不足时即使 L2 充足也返 L1 insufficient, 不混算。

---

## 数据模型

### work_metric (工作量指标)

```
work_metric = output_tokens + cache_creation_input_tokens
```

(纯生成 + 新写上下文; **cache_read 不计入** — 它是上下文重载, 非"工作")。variance.jsonl 存
全部四个 raw 分量, work_metric 可由此固化公式重算。

### wall_clock_seconds (被动元数据)

> ⚠️ **calendar-elapsed (日历经过时间), NOT effort/workload**。agent 跑 30min 时人在做别的事 —
> 墙钟 ≠ 人工投入。`wall_clock_seconds` **不参与** forecast / workload 计算, 仅 history/velocity
> 附带展示供人脑排期。timestamp 缺失 → `null` (null-safe, 不算术)。

### 采集机制 (cycle 粒度 watermark)

phase-d 收尾调 `capture(cycle_meta)`:
- `watermark.json {last_uuid, last_timestamp, session_id, transcript_path}` 增量 anchor
- range = `iter_transcript_usage` 中 `last_uuid` 之后的 turns (uuid-miss → timestamp fallback + warn)
- **幂等主机制 = 空区间**: 重跑无新 turn → range 空 → skip (不 append, watermark 不前进)
- `cycle_id = {spec_slug}-{end_uuid[:8]}` (range 末 uuid 锚, cycle 内稳定)
- `captured_at` = ISO8601 毫秒级

### variance.jsonl record

```jsonc
{"cycle_id":"<spec>-<uuid8>", "spec":"<slug>", "spec_level":2|null,
 "captured_at":"...Z", "uuid_range":["<start>","<end>"], "n_turns":N, "n_tasks":N|null,
 "tokens":{"input":..,"output":..,"cache_read":..,"cache_creation":..},
 "work_metric":<output+cache_creation>, "wall_clock_seconds":<int|null>}
```

---

## 配置 (config-loader)

`ai_native_estimator.{enabled:true, min_samples:3, window:10, bootstrap_seed:{L1,L2,L3}}`。
`enabled:false` → phase-d 不采集。详见 [config-example.md](../config-loader/config-example.md)。

---

## 错误处理 (graceful, 永不抛)

| 情况 | 行为 |
|------|------|
| 无 transcript / 空 transcript | capture skip + warn |
| watermark uuid 不在文件 (session 切换/轮转) | timestamp fallback + warn |
| range 越界 / partial transcript | warn, 不抛 |
| variance.jsonl 缺失/空/corrupt 行 | 容错; forecast 返 insufficient |
| `enabled:false` | capture 不触发 |

---

## v2 defer (见 DEC-20260530-001)

Attention 轴 (Attention-Minutes) / L1 (Haiku dry-run) + L2 (回归) 预估 / task-planner +
progress-updater + state-scanner burndown + phase-a-planner + requirements-sync 集成 /
S/M/L/XL 替代 / per-task 粒度归因 / usd_cost / multi-terminal 并发写。

---

## 相关文档

- [aria-token-telemetry](../aria-token-telemetry/SKILL.md) — `iter_transcript_usage` 数据层
- Spec: `openspec/changes/ai-native-estimator/proposal.md` (#18)
- 决策: `.aria/decisions/2026-05-30-ai-native-estimator-v1-architecture.md`

---

**Skill 版本**: 1.0.0 (2026-05-30, #18 v1 Token 轴)
