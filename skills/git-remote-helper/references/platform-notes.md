# git-remote-helper — Platform Notes

跨平台兼容性、边界条件处理、依赖安装指南。

---

## 1. `timeout` 命令 — 跨平台

### 问题

`check_parity.sh` 的 `ls_remote` 模式需要为 `git ls-remote` 设置超时。

- **Linux** (GNU coreutils): 原生提供 `timeout` 命令
- **macOS** (BSD): 默认**不提供** `timeout`, 需要通过 Homebrew 安装 GNU coreutils

### 解决方案

`check_parity.sh` 按以下优先级自动检测和降级:

```bash
if command -v timeout >/dev/null 2>&1; then
    TIMEOUT_CMD="timeout $TIMEOUT_SECONDS"
elif command -v gtimeout >/dev/null 2>&1; then
    TIMEOUT_CMD="gtimeout $TIMEOUT_SECONDS"
else
    # Python subprocess timeout fallback (inline, no extra file needed)
    # 使用 python3 的 subprocess.run(timeout=N) 实现等效超时
    TIMEOUT_CMD="python3 -c \"...\" "
fi
```

### macOS 安装方法

```bash
# 安装 GNU coreutils (提供 gtimeout 和 gdate 等)
brew install coreutils

# 验证
gtimeout --version
```

或直接使用 Python fallback (不需要安装额外工具, 只需 python3 已安装)。

### Python subprocess 超时 wrapper (inline)

当 `timeout` 和 `gtimeout` 均不可用时, `check_parity.sh` 使用以下 inline Python:

```python
import subprocess, sys
cmd = sys.argv[1:]
try:
    r = subprocess.run(cmd, timeout=TIMEOUT_SECONDS, capture_output=False)
    sys.exit(r.returncode)
except subprocess.TimeoutExpired:
    sys.exit(124)  # 与 GNU timeout 一致的退出码
```

注意: Python `subprocess.run(capture_output=False)` 会让 stdout/stderr 直接透传到当前进程, 行为与 `timeout <cmd>` 完全一致。

---

## 2. `jq` 依赖

### 必须性

所有 Bash 脚本 (`check_parity.sh`, `push_all_remotes.sh`) 使用 `jq -n --arg ... --argjson ...` 构造 JSON 输出。**禁止** Bash 手工字符串拼接 (脆弱, 无法处理路径中的特殊字符、换行等)。

### 安装方法

```bash
# Debian/Ubuntu/apt-based Linux
apt-get install -y jq

# RHEL/CentOS/yum-based Linux
yum install -y jq

# macOS
brew install jq

# 验证
jq --version
```

### jq 构造 JSON 示例

```bash
# 使用 --arg (string) 和 --argjson (JSON value)
jq -n \
  --arg name "origin" \
  --arg sha "abc123" \
  --argjson parity '"equal"' \
  --argjson behind_count 0 \
  --argjson reachable true \
  '{name: $name, sha: $sha, parity: $parity, behind_count: $behind_count, reachable: $reachable}'
```

---

## 3. Git 版本差异 — Shallow Clone 检测

### 问题

`git rev-parse --is-shallow-repository` 只在 **Git 2.15+** 可用。

### 解决方案

`check_parity.sh` 使用双重检测:

```bash
IS_SHALLOW=false

# Method 1: Git 2.15+ (recommended)
if git -C "$REPO" rev-parse --is-shallow-repository >/dev/null 2>&1; then
    if [ "$(git -C "$REPO" rev-parse --is-shallow-repository)" = "true" ]; then
        IS_SHALLOW=true
    fi
fi

# Method 2: Git < 2.15 fallback — .git/shallow 文件存在性
# (文件存在 = 仓库是浅克隆, 空文件 = 曾经是浅克隆但已 unshallow)
if [ -f "$REPO/.git/shallow" ] && [ -s "$REPO/.git/shallow" ]; then
    IS_SHALLOW=true
fi
```

注意: 空的 `.git/shallow` 文件 (0 字节) 表示仓库**已经** unshallow, 不应视为浅克隆。使用 `-s` 检查文件非空。

### Shallow Clone 下的 `rev-list` 不可靠性

在浅克隆中:
- `git rev-list --count A..B` 结果不完整 (commit 历史被截断)
- `behind_count` 和 `ahead_count` 可能严重偏低
- **正确处理**: 当 `IS_SHALLOW=true` 时, 直接返回 `parity: unknown, reason: shallow_clone, behind_count: null, ahead_count: null`

---

## 4. Detached HEAD 处理

### 问题

在 `git checkout <sha>` 或 CI 系统的 checkout 后, 仓库可能处于 detached HEAD 状态。`symbolic-ref -q HEAD` 返回非零。

### 检测方法

```bash
DETACHED_HEAD=false
if ! git -C "$REPO" symbolic-ref -q HEAD >/dev/null 2>&1; then
    DETACHED_HEAD=true
fi
```

### 行为

- `detached_head: true` 出现在顶层输出
- 分支比较退化为 **HEAD SHA vs remote HEAD SHA** (直接比较, 不用分支名)
- `check_parity.sh` 中: 使用 `HEAD` 直接 vs `refs/remotes/<remote>/HEAD` 或通过 `ls_remote` 获取的 SHA
- 消费方 (`phase-c-integrator`) 行为: 输出警告但不阻断, 继续推送 (见 proposal.md D14)

### 子模块 Detached HEAD

Git 子模块**默认**在 detached HEAD 状态。这是正常行为:

```bash
# 子模块 HEAD 是 detached (指向特定 commit)
git -C path/to/submodule symbolic-ref -q HEAD  # 返回非零 — 正常
```

`push_all_remotes.sh` 在子模块 detached HEAD 时:
- 推送当前 HEAD (detached SHA) 到 `refs/heads/<configured-branch>`
- 如需明确分支名, 从父仓库 `.gitmodules` 读取 `branch=` 字段

---

## 5. `verify_post_push.py` 跨平台

Python 脚本使用标准库, 无第三方依赖:

```python
import subprocess  # 跨平台
import time        # 跨平台
import json        # 跨平台
import sys         # 跨平台
import argparse    # 跨平台
```

### macOS 执行

```bash
# 确保 python3 可用
python3 --version  # Python 3.8+

# 直接执行 (需要可执行权限)
chmod +x aria/skills/git-remote-helper/scripts/verify_post_push.py
./aria/skills/git-remote-helper/scripts/verify_post_push.py --repo=... --branch=... --expected-sha=...

# 或通过 python3 调用 (不需要可执行权限)
python3 aria/skills/git-remote-helper/scripts/verify_post_push.py ...
```

### Python 版本要求

- Python 3.8+ (使用 `subprocess.run(capture_output=True)`)
- Python 3.10+ 推荐 (代码使用 `str | None` 类型注解, 3.9 以下需改为 `Optional[str]`)

---

## 6. 环境矩阵总览

| 工具/特性 | Linux (Ubuntu 20.04+) | macOS (Homebrew) | 处理方式 |
|-----------|----------------------|------------------|---------|
| `timeout` | 原生 | 需安装 `brew install coreutils` | 自动降级 → `gtimeout` → Python |
| `gtimeout` | 不存在 | `brew install coreutils` 后提供 | 自动检测 |
| `jq` | `apt-get install jq` | `brew install jq` | 启动时检测, 缺失时报错 |
| `python3` | 通常预装 | 通常预装 | `verify_post_push.py` 依赖 |
| `git --is-shallow-repository` | Git 2.15+ | Git 2.15+ | 双重检测 + `.git/shallow` fallback |
| `symbolic-ref -q HEAD` | 所有 Git 版本 | 所有 Git 版本 | 直接使用 |

---

## 7. 常见问题排查

### Q: `jq: command not found`

```bash
# Ubuntu/Debian
sudo apt-get install -y jq

# macOS
brew install jq
```

### Q: `timeout: command not found` (macOS)

```bash
# 安装 GNU coreutils
brew install coreutils
# 使用 gtimeout 替代 timeout, 或依赖脚本的 Python fallback
```

### Q: `verify_post_push.py` 在 Python 3.9 报语法错误

将 `str | None` 类型注解改为 `Optional[str]` 并添加 `from typing import Optional`。Python 3.10+ 不需要此修改。

### Q: `ls_remote` 始终超时 (防火墙环境)

将 `--verify-mode` 切换为 `local_refs` (仅读本地 tracking ref, 无网络)。但注意 `local_refs` 的结果依赖上次 `git fetch` 的时效性。
