# git-remote-helper — Canonical JSON Schema

这是 3 个指令块输出 JSON 的权威定义 (canonical source of truth)。

Spec A (state-scanner Phase 1.12) 和降级 fallback 实现必须引用本文档, 不得独立定义 schema。

---

## 枚举类型定义

### `parity` 枚举

| 值 | 含义 | 触发条件 |
|----|------|---------|
| `"equal"` | local HEAD = remote HEAD | SHA 完全匹配 |
| `"ahead"` | local 有 remote 没有的 commit | `ahead_count > 0 AND behind_count = 0` |
| `"behind"` | remote 有 local 没有的 commit | `behind_count > 0 AND ahead_count = 0` |
| `"diverged"` | 双方都有对方没有的 commit | `ahead_count > 0 AND behind_count > 0` |
| `"unknown"` | 无法判断 | shallow clone / no tracking ref / network error 等 |

### `reason` 枚举

| 值 | 含义 | 使用场景 |
|----|------|---------|
| `null` | 无错误 | parity 为 equal/ahead/behind/diverged 时 |
| `"shallow_clone"` | 浅克隆, rev-list 不可靠 | `.git/shallow` 存在或 `--is-shallow-repository` = true |
| `"detached_head"` | 游离 HEAD 状态 | `symbolic-ref -q HEAD` 失败 (仅在特定场景显式标注) |
| `"no_local_tracking_ref"` | 本地无该 remote 的 tracking ref | `refs/remotes/<remote>/<branch>` 不存在 (未 fetch) |
| `"not_found"` | 分支在远程不存在 | `ls_remote` 返回空 |
| `"network_timeout"` | 网络超时 | `ls_remote` exit 124 |
| `"auth_failed"` | 认证失败 | `ls_remote` exit 128 |
| `"error"` | 其他错误 | 其他非零 exit code |
| `"sha_mismatch"` | SHA 不匹配 | `verify_parity_post_push` 全部 attempt 耗尽 |

---

## Schema 1: `check_parity` 输出

```json
{
  "repo_path": "string",
  "branch": "string",
  "local_head": "string (full SHA)",
  "detached_head": "boolean",
  "shallow": "boolean",
  "remotes": [
    {
      "name": "string (remote name)",
      "remote_head": "string | null (full SHA, null if unknown)",
      "parity": "equal | ahead | behind | diverged | unknown",
      "behind_count": "integer | null (null for shallow/unknown)",
      "ahead_count": "integer | null (null for shallow/unknown)",
      "reachable": "boolean | \"unknown\"",
      "reason": "null | shallow_clone | detached_head | no_local_tracking_ref | not_found | network_timeout | auth_failed | error",
      "method": "local_refs | ls_remote"
    }
  ],
  "local_refs_stale": "boolean (true if FETCH_HEAD mtime > 24h, local_refs mode only)",
  "overall_parity": "boolean",
  "has_unreachable_remote": "boolean",
  "has_pending_push": "boolean"
}
```

### 字段详细说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `repo_path` | string | 仓库绝对路径 (传入的 `--repo` 参数值) |
| `branch` | string | 检测的分支名 |
| `local_head` | string | 本地 HEAD 的完整 SHA |
| `detached_head` | boolean | 是否处于 detached HEAD 状态 |
| `shallow` | boolean | 是否是浅克隆 |
| `remotes` | array | 每个 remote 的 parity 状态 |
| `remotes[].name` | string | remote 名称 (如 `origin`, `github`) |
| `remotes[].remote_head` | string\|null | remote 的 branch HEAD SHA, 未知时为 null |
| `remotes[].parity` | parity enum | parity 状态 |
| `remotes[].behind_count` | integer\|null | local 落后 remote 的 commit 数, 不可知时为 null |
| `remotes[].ahead_count` | integer\|null | local 领先 remote 的 commit 数, 不可知时为 null |
| `remotes[].reachable` | boolean\|"unknown" | remote 是否可达; `"unknown"` 表示未尝试网络连接 |
| `remotes[].reason` | reason enum | 异常原因, 正常时为 null |
| `remotes[].method` | string | 检测方法: `local_refs` 或 `ls_remote` |
| `overall_parity` | boolean | true = 无 behind/diverged remote (all in sync or ahead/unknown) |
| `has_unreachable_remote` | boolean | true = 至少一个 remote `reachable == false` |
| `has_pending_push` | boolean | true = 至少一个 remote `parity == "ahead"` |

### `overall_parity` 精确定义

```
overall_parity = NOT any(remote.parity IN {"behind", "diverged"})
```

- `ahead`: 本地领先, 待推送, **不**视为 parity 失败
- `unknown`: 网络故障等, **不**视为 parity 失败
- `behind` 或 `diverged`: remote 有本地没有的内容 → parity 失败

---

## Schema 2: `push_all_remotes` 输出

```json
{
  "repo_path": "string",
  "branch": "string",
  "pre_local_head": "string (full SHA)",
  "results": [
    {
      "remote": "string",
      "exit_code": "integer",
      "success": "boolean",
      "pre_remote_head": "string | null",
      "post_remote_head": "string | null",
      "message": "string (truncated git output, max 512 chars)"
    }
  ],
  "all_success": "boolean"
}
```

### 字段详细说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `repo_path` | string | 仓库绝对路径 |
| `branch` | string | 推送的分支名 |
| `pre_local_head` | string | push 前的本地 HEAD SHA (快照) |
| `results` | array | 每个 remote 的推送结果 |
| `results[].remote` | string | remote 名称 |
| `results[].exit_code` | integer | `git push` 的退出码 |
| `results[].success` | boolean | 严格判定: `exit_code==0 AND post_remote_head==pre_local_head` |
| `results[].pre_remote_head` | string\|null | push 前 remote 的 HEAD SHA (via local tracking ref), 无 tracking ref 时为 null |
| `results[].post_remote_head` | string\|null | push 后 remote 的 HEAD SHA (via local tracking ref), 读取失败时为 null |
| `results[].message` | string | git push 的输出 (截断至 512 字符) |
| `all_success` | boolean | 所有 remote `success == true` |

---

## Schema 3: `verify_parity_post_push` 输出

```json
{
  "repo_path": "string",
  "branch": "string",
  "expected_sha": "string (full or short SHA)",
  "max_retries": "integer",
  "retry_schedule_seconds": "array[number]",
  "results": [
    {
      "remote": "string",
      "actual_sha": "string | null",
      "match": "boolean",
      "attempts": "integer",
      "total_seconds": "number",
      "reason": "string? (only present when match=false)"
    }
  ],
  "all_match": "boolean"
}
```

### 字段详细说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `repo_path` | string | 仓库绝对路径 |
| `branch` | string | 验证的分支名 |
| `expected_sha` | string | 期望的 commit SHA |
| `max_retries` | integer | 初次后的最大重试次数 |
| `retry_schedule_seconds` | array | 每次 attempt 前的等待时间 (第一个元素始终为 0) |
| `results` | array | 每个 remote 的验证结果 |
| `results[].remote` | string | remote 名称 |
| `results[].actual_sha` | string\|null | 最后一次 ls-remote 读到的 SHA, 失败时为 null |
| `results[].match` | boolean | `actual_sha == expected_sha` |
| `results[].attempts` | integer | 实际执行的 attempt 次数 (1 到 max_retries+1) |
| `results[].total_seconds` | number | 该 remote 从开始到结束的总耗时 (秒) |
| `results[].reason` | string | 仅在 `match=false` 时出现, 见 reason 枚举 |
| `all_match` | boolean | 所有 remote `match == true` |

### 重试 schedule 计算

```python
schedule = [0] + [initial_backoff * (2**i) for i in range(max_retries)]
# 默认 max_retries=3, initial_backoff=2: [0, 2, 4, 8]
```

v1.15.1 默认 timeout 从 5s 提升为 15s (适配 Forgejo SSH over Cloudflare Access):

| attempt | sleep before (s) | timeout (s) | 累计上界 (s) |
|---------|-----------------|-------------|-------------|
| 1 | 0 | 15 | 15 |
| 2 | 2 | 15 | 32 |
| 3 | 4 | 15 | 51 |
| 4 | 8 | 15 | 74 |

**per-remote 时间上界 = 74s** (`max_per_remote_seconds` 配置项默认值, v1.15.1)
**快速网络优化**: 设 `--timeout=5` 回到 v1.15.0 的 34s 上界

---

## Schema 一致性要求

降级实现 (helper 不可用时, `phase-c-integrator` 使用内联 Bash) 必须产出与上述完全相同的 JSON 结构。字段名、类型、null 语义必须完全一致。差异将在 AC 验证中被检测。
