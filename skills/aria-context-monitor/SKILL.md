---
name: aria-context-monitor
description: |
  机读当前 Claude Code 会话的 context 占用 (runtime-truth, 零猜测), 辅助 "继续推进 vs 暂停"
  决策。返回结构化 occupancy: used%/remaining%/window size + confidence + staleness。
  使用场景: "还剩多少 context", "context 用了多少", "该暂停吗", "check context usage",
  Phase B/C 实施期暂停决策。
allowed-tools: Bash, Read
---

# aria-context-monitor

## 用途

让 AI 机读**当前会话的 context 占用**, 替代"凭感觉"估算 (实证 #104: 凭感觉 +22% 偏差导致不必要暂停)。
数据来自 Claude Code runtime 渲染 statusLine 时 pipe 的 stdin JSON (`context_window_size` /
`used_percentage` 等真实值), 经 statusLine relay 写入 `.aria/cache/context-window.json`, 由本 skill 读取。

底层数据层是 internal skill [aria-token-telemetry](../aria-token-telemetry/SKILL.md) (3 档 fallback)。

---

## 何时使用

- 十步循环 Phase B/C 实施期, AI 判断"当前会话继续 vs 暂停 (形成 commit boundary)"
- 用户问"还剩多少 context"/"该暂停吗"
- 长会话接近窗口上限前的主动预警

**不使用**: 本 skill **只提供数据, 不自动中断会话**。暂停决策由 AI / phase skill 判断 (DEC: 不自动暂停)。

---

## 执行

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/aria-token-telemetry/scripts/token_telemetry.py" --project-root .
```

读返回 JSON 后, AI 按 `source` 字段选对应口径解读 (见下)。

### 首次使用 / relay 未安装

若返回 `source=transcript_fallback` 或 `confidence=estimate` 且用户期望精确值, 引导安装 relay:

```bash
bash "${CLAUDE_PLUGIN_ROOT:-aria}/skills/aria-context-monitor/scripts/setup_relay.sh"        # 幂等注入
bash "${CLAUDE_PLUGIN_ROOT:-aria}/skills/aria-context-monitor/scripts/setup_relay.sh --status" # 查状态
```

注入后需 statusLine **渲染一次** (任意交互) relay cache 才写入; 之后即走 `source=relay_cache` (runtime-truth)。

`setup_relay.sh` 退出码: `0` 成功 (injected / no-op / minimal-reference-created) / `2` 参数错 / `3` jq 缺失 / `4` 找不到 `input=$(cat)` 锚点 / `5` statusLine command 非脚本文件 (需手动注入)。

---

## 输出解读 (口径不混用)

| `source` | `confidence` | 读哪个占用字段 | 含义 |
|----------|-------------|----------------|------|
| `relay_cache` | `high` | **`used_percentage`** (proxy=null) | runtime-truth, statusLine 算好的 % — **0 偏差** |
| `transcript_fallback` | `estimate` | **`used_percentage_proxy`** (used_percentage=null) | transcript usage 推算, window 可能非精确 (见 `window_source`) |
| `unavailable` | `estimate` | 两者皆 null | 无 statusLine + 无 transcript, 无法判定 — 不报错, 不可用此信号 |

> ⚠️ **绝不混用**: relay 路径只看 `used_percentage`, transcript 路径只看 `used_percentage_proxy`。两者是**不同口径的量** (前者 total_input/window, 后者 input+cache 合计/window), 混用会重蹈 #104 的 22% drift。

### staleness 判定

- `staleness_seconds ≤ 300` (config `context_monitor.staleness_threshold_seconds` 可覆盖): relay cache 可信, `confidence=high`
- `staleness_seconds > 300`: token_telemetry 自动降级到 transcript fallback (`confidence=estimate`)
- transcript / unavailable 路径: `staleness_seconds = null` (不适用)

### window_source (window 大小来源)

`relay_cache` 命中恒 = `runtime`。`transcript_fallback` 时 4 档: `cached_size_reuse` > `config` > `empirical_peak` > `default` (200K 兜底)。`empirical_peak`/`default` 时 window 可能低估真实大小 → 占用 % 偏高, 仅作下界参考。

---

## 决策阈值建议 (advisory)

| `used_percentage` (relay 路径) | 建议 |
|-------------------------------|------|
| < 70% | 继续推进 (容量充足) |
| 70–85% | 留意; 找自然 commit boundary |
| > 85% | 建议暂停 + commit, 避免硬撞限丢上下文 |

transcript fallback (`used_percentage_proxy`) 因 window 可能低估, 阈值放宽解读 (proxy 偏高时实际余量可能更多)。

消费集成点 (phase-b-developer / phase-c-integrator 调用建议) 见各 skill 文档。

---

## 错误处理

| 情况 | 行为 |
|------|------|
| relay cache 缺失 | 自动 transcript fallback (estimate) |
| relay cache corrupt / schema 不匹配 | 忽略 cache, transcript fallback; corrupt 不抛异常 |
| 无 statusLine 且无 transcript | `source=unavailable`, 不报错; 提示安装 relay |
| jq 缺失 | relay 写入侧失效 (aria-doctor 提示); transcript fallback 仍可用 |

---

## 可移植性

数据 schema (statusLine stdin) 是**通用 Claude Code 特性**, 任何项目可用。relay 抓取依赖 statusLine 配置 + relay marker (故有 3 档 fallback + `setup_relay.sh` helper)。无 statusLine 的 sandbox 项目跑本 skill → transcript fallback / unavailable, **不报错**。

---

## 相关文档

- [aria-token-telemetry](../aria-token-telemetry/SKILL.md) — 底层数据层 (relay 读 + transcript 解析 + window resolve)
- [aria-doctor](../aria-doctor/SKILL.md) — relay 3 态检测 + jq 可用性
- Spec: `openspec/changes/aria-context-monitor/proposal.md` (#104)
- 决策: `.aria/decisions/2026-05-29-context-monitor-architecture.md` (DEC-20260529-001)

---

**Skill 版本**: 1.0.0 (2026-05-29, #104 Phase B)
