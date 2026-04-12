# git-remote-helper — API Reference

完整调用契约: 3 个指令块的参数 / 输出 / 错误处理 / 调用示例。

---

## 1. `check_parity` (纯读)

### 脚本路径

```
aria/skills/git-remote-helper/scripts/check_parity.sh
```

### 参数签名

| 参数 | 类型 | 必须 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--repo` | string | 是 | — | Git 仓库绝对路径 |
| `--branch` | string | 否 | `master` | 目标分支名 |
| `--verify-mode` | enum | 否 | `local_refs` | `local_refs` (快, 无网络) / `ls_remote` (准, 有网络) |
| `--timeout` | integer | 否 | `15` | `ls_remote` 模式每个 remote 的超时秒数 (v1.15.1: 从 5s 提升为 15s, 适配 Forgejo SSH over Cloudflare Access) |

### 调用示例

```bash
# Bash — local_refs 模式 (快速, 无网络)
bash aria/skills/git-remote-helper/scripts/check_parity.sh \
  --repo=/home/dev/Aria/aria \
  --branch=master \
  --verify-mode=local_refs

# Bash — ls_remote 模式 (权威, 有网络, 带 10s 超时)
bash aria/skills/git-remote-helper/scripts/check_parity.sh \
  --repo=/home/dev/Aria \
  --branch=master \
  --verify-mode=ls_remote \
  --timeout=10
```

### 输出 JSON schema 示例

```json
{
  "repo_path": "/home/dev/Aria/aria",
  "branch": "master",
  "local_head": "19f2861a3b4c5d6e7f8a9b0c",
  "detached_head": false,
  "shallow": false,
  "remotes": [
    {
      "name": "origin",
      "remote_head": "19f2861a3b4c5d6e7f8a9b0c",
      "parity": "equal",
      "behind_count": 0,
      "ahead_count": 0,
      "reachable": true,
      "reason": null,
      "method": "local_refs"
    },
    {
      "name": "github",
      "remote_head": "f55e130a1b2c3d4e5f6a7b8c",
      "parity": "behind",
      "behind_count": 2,
      "ahead_count": 0,
      "reachable": true,
      "reason": null,
      "method": "local_refs"
    }
  ],
  "overall_parity": false,
  "has_unreachable_remote": false,
  "has_pending_push": false
}
```

### 错误处理 — `reason` 枚举

| `reason` 值 | 触发条件 | `parity` 值 | `reachable` 值 |
|-------------|---------|------------|---------------|
| `null` | 正常 — 无错误 | `equal` / `ahead` / `behind` / `diverged` | `true` |
| `shallow_clone` | `--is-shallow-repository` = true 或 `.git/shallow` 存在 | `unknown` | `true` |
| `detached_head` | `symbolic-ref -q HEAD` 返回非零 (附加在顶层 `detached_head: true`) | — | — |
| `no_local_tracking_ref` | `refs/remotes/<remote>/<branch>` 不存在 (未执行 fetch) | `unknown` | `"unknown"` |
| `not_found` | `ls_remote` 返回空 (分支在 remote 不存在) | `unknown` | `true` |
| `network_timeout` | `ls_remote` exit 124 (超时) | `unknown` | `false` |
| `auth_failed` | `ls_remote` exit 128 (认证失败) | `unknown` | `false` |
| `error` | 其他非零 exit code | `unknown` | `false` |

### `overall_parity` 定义

```
overall_parity = true   当且仅当 所有 remote.parity ∉ {"behind", "diverged"}
```

- `ahead` 不导致 overall_parity=false (pending push 但 local 是最新的)
- `unknown` 不导致 overall_parity=false (网络故障不算 parity 失败)
- `behind` 或 `diverged` → overall_parity=false

---

## 2. `push_all_remotes` (写 — 仅授权 skill 调用)

### 脚本路径

```
aria/skills/git-remote-helper/scripts/push_all_remotes.sh
```

### 参数签名

| 参数 | 类型 | 必须 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--repo` | string | 是 | — | Git 仓库绝对路径 |
| `--branch` | string | 否 | `master` | 推送的分支名 |
| `--remotes` | string | 否 | 所有 remote | 逗号分隔的 remote 白名单 (如 `origin,github`) |

### 调用示例

```bash
# Bash — 推送所有 remote
bash aria/skills/git-remote-helper/scripts/push_all_remotes.sh \
  --repo=/home/dev/Aria/aria \
  --branch=master

# Bash — 推送指定 remote 白名单
bash aria/skills/git-remote-helper/scripts/push_all_remotes.sh \
  --repo=/home/dev/Aria/aria \
  --branch=master \
  --remotes=origin,github
```

### 输出 JSON schema 示例

```json
{
  "repo_path": "/home/dev/Aria/aria",
  "branch": "master",
  "pre_local_head": "19f2861a3b4c5d6e7f8a9b0c",
  "results": [
    {
      "remote": "origin",
      "exit_code": 0,
      "success": true,
      "pre_remote_head": "19f2861a3b4c5d6e7f8a9b0c",
      "post_remote_head": "19f2861a3b4c5d6e7f8a9b0c",
      "message": "Everything up-to-date"
    },
    {
      "remote": "github",
      "exit_code": 0,
      "success": true,
      "pre_remote_head": "f55e130a1b2c3d4e5f6a7b8c",
      "post_remote_head": "19f2861a3b4c5d6e7f8a9b0c",
      "message": "f55e130..19f2861  master -> master"
    }
  ],
  "all_success": true
}
```

### 错误处理

| 场景 | `exit_code` | `success` | `message` |
|------|-------------|-----------|-----------|
| 推送成功 (new commits) | 0 | `true` | `"<old>..<new>  master -> master"` |
| 已同步 (no-op) | 0 | `true` | `"Everything up-to-date"` |
| 网络错误 | 非0 | `false` | git 错误信息 |
| 认证失败 | 128 | `false` | git 认证错误 |
| post_remote_head 读取失败 | 0 | `false` | `"post-push verification failed: ..."` |
| remote 不存在 | 1 | `false` | `"Unknown remote \"<name>\""` |

### `success` 判定规则 (严格)

```
success = (exit_code == 0) AND (post_remote_head == pre_local_head)
```

- **不依赖** "Everything up-to-date" 文本
- `pre_remote_head == pre_local_head` (本地已同步) 时: push 是 no-op, exit_code=0, post_remote_head 仍等于 pre_local_head → `success=true` (正确)
- `post_remote_head` 通过 `git rev-parse refs/remotes/<remote>/<branch>` 读取 (本地, 无额外网络)

---

## 3. `verify_parity_post_push` (纯读, Python 实现)

### 脚本路径

```
aria/skills/git-remote-helper/scripts/verify_post_push.py
```

### 参数签名

| 参数 | 类型 | 必须 | 默认值 | 说明 |
|------|------|------|--------|------|
| `--repo` | string | 是 | — | Git 仓库绝对路径 |
| `--branch` | string | 是 | — | 验证的分支名 |
| `--expected-sha` | string | 是 | — | 期望的 commit SHA (push 前快照的 local HEAD) |
| `--max-retries` | integer | 否 | `3` | 初次 attempt 后的最大重试次数 |
| `--initial-backoff` | float | 否 | `2.0` | 初始 backoff 秒数, 每次翻倍 |
| `--timeout` | float | 否 | `15.0` | 每次 ls-remote 的超时秒数 (v1.15.1 默认值) |
| `--remotes` | string | 否 | 所有 remote | 逗号分隔的 remote 名称 |

### 调用示例

```bash
# Bash — 验证所有 remote
python3 aria/skills/git-remote-helper/scripts/verify_post_push.py \
  --repo=/home/dev/Aria/aria \
  --branch=master \
  --expected-sha=19f2861a3b4c5d6e7f8a9b0c

# Bash — 验证指定 remote, 自定义重试
python3 aria/skills/git-remote-helper/scripts/verify_post_push.py \
  --repo=/home/dev/Aria/aria \
  --branch=master \
  --expected-sha=19f2861a3b4c5d6e7f8a9b0c \
  --max-retries=3 \
  --initial-backoff=2 \
  --timeout=5 \
  --remotes=origin,github
```

```python
# Python — subprocess 调用
import subprocess, json

result = subprocess.run(
    [
        "python3", "aria/skills/git-remote-helper/scripts/verify_post_push.py",
        "--repo=/home/dev/Aria/aria",
        "--branch=master",
        "--expected-sha=19f2861a3b4c5d6e7f8a9b0c",
        "--remotes=origin,github",
    ],
    capture_output=True, text=True
)
data = json.loads(result.stdout)
print(data["all_match"])  # True / False
```

### 输出 JSON schema 示例

```json
{
  "repo_path": "/home/dev/Aria/aria",
  "branch": "master",
  "expected_sha": "19f2861a3b4c5d6e7f8a9b0c",
  "max_retries": 3,
  "retry_schedule_seconds": [0, 2, 4, 8],
  "results": [
    {
      "remote": "origin",
      "actual_sha": "19f2861a3b4c5d6e7f8a9b0c",
      "match": true,
      "attempts": 1,
      "total_seconds": 0.31
    },
    {
      "remote": "github",
      "actual_sha": "19f2861a3b4c5d6e7f8a9b0c",
      "match": true,
      "attempts": 2,
      "total_seconds": 2.43
    }
  ],
  "all_match": true
}
```

### 重试策略

```
retry_schedule = [0] + [initial_backoff * (2**i) for i in range(max_retries)]
默认值 (max_retries=3, initial_backoff=2): [0, 2, 4, 8] 秒
```

每次 attempt:
1. Sleep `schedule[i]` 秒
2. `git ls-remote <remote> refs/heads/<branch>` (timeout=15s 默认, v1.15.1+)
3. SHA 匹配 → 立即返回 `match: true`
4. 全部 attempt 耗尽 → 返回 `match: false, reason: <last_error_or_sha_mismatch>`

**per-remote 时间上界**:
- 4 attempts × 15s timeout = 60s (网络, v1.15.1 默认)
- sleep schedule = 0+2+4+8 = 14s
- **合计上界 = 74s per remote** (v1.15.1 默认). 快速网络可设 `--timeout=5` 回到 34s 上界.

### 错误处理 — `reason` 枚举 (match=false 时)

| `reason` 值 | 触发条件 |
|-------------|---------|
| `sha_mismatch` | 全部 attempt 正常完成但 SHA 不匹配 |
| `network_timeout` | 最后一次 attempt 超时 |
| `auth_failed` | 最后一次 attempt 返回 exit 128 |
| `error` | 其他非零 exit code |

### 退出码

| 退出码 | 含义 |
|--------|------|
| `0` | `all_match: true` |
| `1` | `all_match: false` 或运行时错误 |
