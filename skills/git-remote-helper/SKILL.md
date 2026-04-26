---
name: git-remote-helper
description: |
  Git 多远程 parity 检测与 push 验证的共享基础设施。
  内部工具, 仅供其他 skills 引用。提供标准化 Bash/Python 执行脚本段 + 输出 JSON schema 契约。
user-invocable: false
disable-model-invocation: true
allowed-tools: Bash, Read
---

# git-remote-helper

## 用途

`git-remote-helper` 是一个 **internal skill**, 不直接被用户触发。它为以下消费方提供标准化的 Git 多远程 parity 检测与 push 验证逻辑:

- `state-scanner` Phase 1.12: 检测多远程 parity 漂移
- `phase-c-integrator` C.2.5: 合并后强制推送所有配置远程 + post-push SHA 验证

**交付形式**: helper 不是"可调用函数", 而是 SKILL.md 中的指令块 + JSON schema 契约。消费方通过引用本 SKILL.md, 让 LLM 执行标准化的 Bash/Python 脚本段并产出约定的 JSON。

## 依赖声明

| 工具 | 必须/可选 | 说明 |
|------|---------|------|
| `jq` | 必须 | JSON 构造 (`jq -n --arg ... --argjson ...`), 禁止 Bash 手工拼接 |
| `python3` | 必须 | `verify_post_push.py` 实现 + ls_remote 超时 fallback |
| `timeout` | 可选 | Linux 原生, 缺失时降级 `gtimeout` 或 Python wrapper |
| `gtimeout` | 可选 | macOS GNU coreutils (`brew install coreutils`), 见 `references/platform-notes.md` |

安装 jq:
- Linux: `apt-get install jq` / `yum install jq`
- macOS: `brew install jq`

## 写/读权限分离

| 指令块 | 权限 | 允许的消费方 |
|--------|------|------------|
| `check_parity` | **纯读** — 不修改任何 ref, 无网络写操作 | 任何 skill (state-scanner / phase-c-integrator / 未来消费方) |
| `verify_parity_post_push` | **纯读** — 仅 `git ls-remote` 查询 | 任何 skill |
| `push_all_remotes` | **写** — 执行 `git push`, 修改远程 ref | 仅 `phase-c-integrator` / `branch-manager` 等明确具有推送权限的 skill |

## 指令块概览

### 1. `check_parity` (纯读)

检测单个仓库所有远程的 parity 状态, 不做网络写操作。

**脚本**: `scripts/check_parity.sh`

**调用示例**:
```bash
bash aria/skills/git-remote-helper/scripts/check_parity.sh \
  --repo=/home/dev/Aria/aria \
  --branch=master \
  --verify-mode=local_refs \
  --timeout=15  # v1.15.1 默认 (适配 Forgejo SSH over CF Access)
```

**输出**: canonical JSON, schema 见 `references/schema.md`

**边界处理**:
- shallow clone: `parity: unknown, reason: shallow_clone`
- detached HEAD: `detached_head: true`, 用 HEAD SHA 比较各 remote
- 未 fetch 的 remote tracking ref: `parity: unknown, reason: no_local_tracking_ref`
- ls_remote 超时: `reachable: false, reason: network_timeout`
- ls_remote 认证失败 (exit 128): `reachable: false, reason: auth_failed`

### 2. `push_all_remotes` (写 — 仅授权 skill 调用)

对单个仓库推送所有 (或白名单内的) remote, 记录 pre/post SHA 状态。

**脚本**: `scripts/push_all_remotes.sh`

**调用示例**:
```bash
bash aria/skills/git-remote-helper/scripts/push_all_remotes.sh \
  --repo=/home/dev/Aria/aria \
  --branch=master \
  --remotes=origin,github
```

**`success` 判定** (严格, 不依赖 "Everything up-to-date" 文本):
```
success = (exit_code == 0) AND (post_remote_head == pre_local_head)
```

**输出**: JSON 包含 `pre_remote_head` / `post_remote_head` / `success` 字段, 供消费方验证。

### 3. `verify_parity_post_push` (纯读, Python 实现)

权威验证远程实际接收到推送, 应对 Forgejo/GitHub 10-30s 复制延迟。

**脚本**: `scripts/verify_post_push.py`

**调用示例**:
```bash
python3 aria/skills/git-remote-helper/scripts/verify_post_push.py \
  --repo=/home/dev/Aria/aria \
  --branch=master \
  --expected-sha=19f2861a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9 \
  --max-retries=3 \
  --initial-backoff=2 \
  --timeout=15 \
  --remotes=origin,github
```

**重试策略**: 立即 + 2s + 4s + 8s = 4 次 attempt
**per-remote 时间上界** (v1.15.1 默认): 4 × 15s (ls-remote) + 14s (sleep) = **74s**
**快速网络**: 设 `--timeout=5` 回到 v1.15.0 的 34s 上界

## 参考文档

| 文档 | 内容 |
|------|------|
| `references/api.md` | 3 个指令块的完整调用契约 (参数 / 输出 / 错误枚举 / 调用示例) |
| `references/schema.md` | canonical JSON schema 定义 (parity 枚举 / reason 枚举 / 字段清单) |
| `references/platform-notes.md` | macOS/Linux 差异 / shallow clone / detached HEAD / jq 安装 |
