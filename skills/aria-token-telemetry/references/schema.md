# aria-token-telemetry — 字段级 schema 契约

> statusLine stdin (runtime 来源) + relay cache (relay 写入) + transcript usage (fallback 来源) 三方字段映射。
> Source-of-truth: `scripts/token_telemetry.py`。冻结样本: `aria-plugin-benchmarks/context-monitor/statusline-stdin-sample.json` (2026-05-29 capture, runtime 2.1.156)。

## statusLine stdin (TASK-001 gate 验证存在)

| 字段路径 | 类型 | 用途 | 独立证据 |
|----------|------|------|---------|
| `context_window.context_window_size` | number | window 大小 (零推断) | ✅ TASK-001 gate (2026-05-29) |
| `context_window.used_percentage` | number | runtime 算好的占用 % (口径: total_input/window) | ✅ 生产 statusline + gate |
| `context_window.remaining_percentage` | number | 余量 % | ✅ gate |
| `context_window.total_input_tokens` | number | 累计 input | ✅ 生产 statusline + gate |
| `context_window.current_usage.{input,output,cache_creation,cache_read}_tokens` | number | per-turn raw counts (#18 复用) | ✅ gate |
| `model.id` | string | 完整 model id **带 `[1m]`** | ✅ gate (transcript message.model 丢此后缀) |
| `model.display_name` | string | 显示名 | ✅ 生产 statusline + gate |
| `exceeds_200k_tokens` | bool | 是否超 200K | ✅ gate |
| `transcript_path` | string | 当前 session transcript | ✅ gate |

> **隐私**: `cost` / `rate_limits` / `session_id` 存在于 stdin 但 **relay 不写入 cache** (非必要 + 隐私)。

## relay cache (`.aria/cache/context-window.json`)

`setup_relay.sh` 的 relay 块用 jq 从 stdin 投影写入 (atomic tmp→rename, tmp 名含 `$$` PID 防并发)。
顶层 `schema_version="1.0"` (对比 `issues.json` 模式)。字段见 SKILL.md。

## transcript usage (fallback)

transcript JSONL 每个 assistant turn: `message.usage.{input_tokens, output_tokens,
cache_creation_input_tokens, cache_read_input_tokens}` + `message.model` (⚠️ 丢 `[1m]` 后缀)。
`parse_transcript_usage()` 取**最后一个**含 usage 的 turn。

occupancy proxy = `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`。
window 大小 transcript 不可靠提供 → 走 4 档 resolve (见 SKILL.md)。

### 口径漂移注意 (transcript 路径, review Minor 2/3)

- **`total_input_tokens`**: relay 路径 = runtime **累计**值; transcript 路径 = **末轮** `input_tokens` (单轮, 非 cumulative)。两路径同名不同口径 —— #18 estimator 复用时**应读 `current_usage` raw counts**, 不要直接信任 transcript 路径的 `total_input_tokens`。
- **`exceeds_200k_tokens`**: relay 路径 = Anthropic runtime 定义; transcript 路径 = 本地 `occupancy > 200000` **近似重算** (口径可能不同, 仅参考)。

## 口径对照 (避免 #104 22% drift)

| 路径 | 占用字段 | 口径 |
|------|---------|------|
| relay_cache | `used_percentage` | `total_input_tokens / window` (runtime 算) |
| transcript_fallback | `used_percentage_proxy` | `(input + cache_read + cache_creation) / window` (本地算, window 可能估) |

两者**不同量, 不共用字段**。消费方按 `source` 二选一读取。
