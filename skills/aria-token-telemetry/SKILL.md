---
name: aria-token-telemetry
description: |
  Claude Code context/token telemetry 的共享数据层。内部工具, 仅供其他 skills 引用
  (aria-context-monitor 消费实时占用; aria-plugin #18 estimator 复用 raw counts)。
  提供 relay cache 读取 + transcript JSONL usage 解析 + window 大小 4 档 resolve。
user-invocable: false
disable-model-invocation: true
allowed-tools: Bash, Read
---

# aria-token-telemetry

## 用途

`aria-token-telemetry` 是一个 **internal skill**(复用 [git-remote-helper](../git-remote-helper/SKILL.md) US-012 Layer 3 "internal skill 作跨-skill 共享基础设施"先例),不直接被用户触发。它为以下消费方提供标准化的 Claude Code context/token 数据采集:

- **aria-context-monitor** (user-facing) — 消费实时 context 占用 (used%/remaining%/window)
- **aria-plugin #18 ai-native-estimator** (future) — 复用 raw token counts (per-turn input/output/cache),**独立于 window%** (Q2=a)

核心脚本: `scripts/token_telemetry.py` (stdlib-only Python)。

---

## 数据来源 (3 档 fallback)

数据 schema (statusLine stdin) 是**通用 Claude Code 特性**;relay 抓取依赖 statusLine 配置 + relay marker。

| 档 | 来源 | 何时 | confidence | window_source |
|----|------|------|-----------|---------------|
| 1 | `.aria/cache/context-window.json` (relay cache, fresh) | statusLine 已配 + relay marker + staleness≤阈值 | high (runtime-truth) | `runtime` |
| 2 | setup helper 检测无 relay marker → 提示注入 | 未注入 | — (引导) | — |
| 3 | transcript JSONL 解析 | 无 statusLine / cache 缺失/陈旧/corrupt | estimate | 4 档见下 |

---

## statusLine stdin schema 契约 (TASK-001 BLOCKING gate 固化, 2026-05-29)

> **证据**: 2026-05-29 重新 capture 实测 (`aria-plugin-benchmarks/context-monitor/statusline-stdin-sample.json`),
> 验证 `context_window_size` 真实存在且为 number → gate PASS, 不触发回退条款。
> Claude Code runtime version `2.1.156`。

Claude Code runtime 每次渲染 statusLine 时 pipe 一个 JSON 到 statusLine command 的 **stdin**。冻结契约字段:

```jsonc
{
  "model": {
    "id": "claude-opus-4-8[1m]",            // ✅ 完整 ID 带 [1m] (transcript message.model 丢此后缀)
    "display_name": "Opus 4.8 (1M context)"
  },
  "context_window": {
    "context_window_size": 1000000,          // ✅🔑 window 大小 — 零推断 (gate 验证字段)
    "used_percentage": 14,                    // ✅ runtime 算好的 % (口径: total_input/window)
    "remaining_percentage": 86,               // ✅
    "total_input_tokens": 142208,             // ✅
    "total_output_tokens": 1274,
    "current_usage": {                        // ✅ raw counts (供 #18 estimator 复用)
      "input_tokens": 131, "output_tokens": 1274,
      "cache_creation_input_tokens": 980, "cache_read_input_tokens": 141097
    }
  },
  "exceeds_200k_tokens": false,               // ✅
  "transcript_path": "...",                   // ✅
  "session_id": "...", "version": "2.1.156",
  "cost": {...}, "rate_limits": {...}, "workspace": {...}, "fast_mode": false
}
```

**relay cache 写入子集** (`setup_relay.sh` 中 jq 投影): `schema_version` + `model.id` + `context_window.*` + `exceeds_200k_tokens` + `transcript_path` + `captured_at`。**不写** `cost`/`rate_limits`/`session_id` (隐私 + 非必要)。

字段级注解与 transcript 字段映射见 [references/schema.md](./references/schema.md)。

---

## relay cache schema (`.aria/cache/context-window.json`)

```jsonc
{
  "schema_version": "1.0",                    // 顶层校验 (对比 issues.json 模式)
  "captured_at": "2026-05-29T...",            // relay 写入时刻 (ISO8601)
  "model_id": "claude-opus-4-8[1m]",
  "context_window_size": 1000000,
  "used_percentage": 14,
  "remaining_percentage": 86,
  "total_input_tokens": 142208,
  "current_usage": { "input_tokens": 131, "cache_read_input_tokens": 141097, "cache_creation_input_tokens": 980, "output_tokens": 1274 },
  "exceeds_200k_tokens": false,
  "transcript_path": "..."
}
```

---

## window 大小 4 档 resolve (transcript fallback 时)

relay cache 命中 → `window_source = "runtime"` (恒定, 不得标其他值)。

transcript fallback 时按优先级:

| 档 | window_source | 来源 |
|----|---------------|------|
| 1 | `cached_size_reuse` | 复用上次 relay cache 见过的 `context_window_size` (session 内不变) |
| 2 | `config` | `.aria/config.json` `context_monitor.window_tokens` |
| 3 | `empirical_peak` | observed-peak input_tokens 反推最小 fitting tier (snap to {200000,1000000}) |
| 4 | `default` | 200000 保守兜底 |

---

## 公共接口 (token_telemetry.py)

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/aria-token-telemetry/scripts/token_telemetry.py" [--project-root DIR] [--json]
```

返回 JSON (供消费方解析):

```jsonc
{
  "source": "relay_cache | transcript_fallback | unavailable",
  "schema_version": "1.0",
  "context_window_size": 1000000,
  "window_source": "runtime | cached_size_reuse | config | empirical_peak | default",
  "used_percentage": 14,                  // relay 路径口径 (total_input/window); transcript 路径为 null
  "used_percentage_proxy": null,          // transcript 路径口径 (input+cache_read+cache_creation)/window; relay 路径为 null
  "remaining_percentage": 86,
  "total_input_tokens": 142208,
  "current_usage": {...},                 // raw counts (#18 复用; 独立于 window%)
  "model_id": "claude-opus-4-8[1m]",
  "exceeds_200k_tokens": false,
  "captured_at": "2026-05-29T...",
  "staleness_seconds": 12                  // relay 路径: now - captured_at; transcript/unavailable 路径为 null
}
```

> **口径不混用**: relay 路径填 `used_percentage`,transcript 路径填 `used_percentage_proxy` —— 两者是**不同的量**,消费方按 `source` 读对应字段。`unavailable` 态两者皆 null。

**Python 复用接口** (供消费 skill / #18 直接 import):

```python
from token_telemetry import collect, parse_transcript_usage, resolve_window
result = collect(project_root=".")          # 完整 telemetry dict
usage  = parse_transcript_usage(jsonl_path) # raw counts only (window-independent, #18 axis)
```

---

## 错误处理 (graceful degradation, 永不抛异常给消费方)

| 情况 | 行为 |
|------|------|
| relay cache 文件缺失 | → transcript fallback |
| relay cache JSONDecodeError / OSError | → `source=unavailable` (不抛), 或 transcript fallback |
| relay cache `schema_version` 不匹配 | → 忽略 cache, transcript fallback |
| relay cache staleness > 阈值 (默认 300s) | → transcript fallback, confidence 降级 |
| transcript 缺失 / 无 usage block | → `source=unavailable`, used_percentage 与 proxy 皆 null |
| jq 缺失 (relay 写入侧) | aria-doctor 提示; relay 不工作但 transcript fallback 仍可用 |

---

## 相关文档

- [references/schema.md](./references/schema.md) — statusLine stdin + relay cache 字段级契约 + transcript 映射
- [aria-context-monitor](../aria-context-monitor/SKILL.md) — user-facing 消费方
- [git-remote-helper](../git-remote-helper/SKILL.md) — internal-skill 先例
- Spec: `openspec/changes/aria-context-monitor/proposal.md` (#104)
- 决策: `.aria/decisions/2026-05-29-context-monitor-architecture.md` (DEC-20260529-001)

---

**Skill 版本**: 1.0.0 (2026-05-29, #104 Phase B)
**类型**: internal (user-invocable: false)
