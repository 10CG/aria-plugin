# Phase 1.12: 本地/远程同步检测 — 详细实现逻辑

> **版本**: 1.0.0 | **适用于**: state-scanner v2.9.0 阶段 1.12
> **父规范**: `openspec/changes/state-scanner-remote-sync-check/proposal.md`

---

## 1. 概览

Phase 1.12 在阶段 1.11 (项目级自定义检查) 之后、阶段 2 (推荐决策) 之前执行，负责检测**本地 git 仓库与远程的同步状态**，涵盖：

- 当前分支是否落后远程 upstream
- FETCH_HEAD 时间戳（上次 fetch 距今多久）
- 子模块工作目录、主仓库记录、远程三者之间的偏差

所有检测均为只读操作，遵循 fail-soft 原则：单项失败仅置对应字段为 `null` + `reason` 标注，不中断后续阶段，不以非零 exit code 退出。

总阶段超时保护：**10s**（含 `ls-remote` 最多 5s + 其余命令 5s）。

---

## 2. 输出 Schema

```yaml
sync_status:
  has_remote: true                   # bool: git remote -v 是否有输出
  remote_refs_age: "2h"              # string: FETCH_HEAD 距今时长 (格式见下)
  shallow: false                     # bool: 仓库是否为浅克隆
  current_branch:
    name: "master"                   # string | null: null 表示 detached HEAD
    upstream: "origin/master"        # string | null: null 表示无 upstream
    upstream_configured: true        # bool: 是否配置了 set-upstream-to
    ahead: 0                         # int | null
    behind: 3                        # int | null
    diverged: false                  # bool | null
    reason: null                     # string | null: 见 fail-soft 表格
  submodules:
    - path: "aria"
      tree_commit: "abc1234"         # 主仓库 HEAD 记录的 commit
      head_commit: "abc1234"         # 本地 checkout 的 commit
      remote_commit: "def5678"       # 远程默认分支 commit (fallback 链)
      remote_commit_source: "ls-remote"
      drift:
        workdir_vs_tree: false       # 工作目录偏离主仓库记录
        tree_vs_remote: true         # 主仓库记录落后远程
        behind_count: 4              # int | null: null 表示 remote_commit 为 null
        hint: "git submodule update --remote aria"
```

### 字段 null 语义

| 字段 | 为 null 的条件 |
|------|---------------|
| `current_branch.name` | detached HEAD |
| `current_branch.upstream` | 未配置 upstream |
| `current_branch.upstream_configured` | 不会为 null（始终 bool） |
| `current_branch.ahead` | upstream 缺失 / shallow / detached HEAD |
| `current_branch.behind` | upstream 缺失 / shallow / detached HEAD |
| `current_branch.diverged` | ahead 或 behind 为 null 时为 null |
| `current_branch.reason` | 正常状态时为 null |
| `submodules[].remote_commit` | 四级 fallback 全部失败 |
| `submodules[].drift.behind_count` | `remote_commit` 为 null |

### `remote_refs_age` 格式

| 值 | 含义 |
|----|------|
| `"never"` | FETCH_HEAD 文件不存在 |
| `"15m"` | 15 分钟前 |
| `"2h"` | 2 小时前 |
| `"3d"` | 3 天前 |

使用 `git log -1 --format=%cr FETCH_HEAD` 的原始输出，跨平台一致。

---

## 3. 执行流程

以下步骤串行执行，任一步失败仅影响对应字段，不中断后续步骤。

### 步骤 1: 检测 `has_remote`

```bash
has_remote=$(git remote -v 2>/dev/null | wc -l)
if [ "$has_remote" -eq 0 ]; then
  # 纯本地仓库：输出 has_remote: false，跳过所有远程相关字段
  echo "has_remote: false"
  exit 0
fi
```

`has_remote: false` 时，`current_branch.upstream`、`submodules[].remote_commit` 等字段不输出。

### 步骤 2: Upstream 探测（修复 M3 / Decision D11）

先探测 upstream 是否存在，再决定 ahead/behind 计算，避免 `rev-list --count` 非零退出。

```bash
# 探测 upstream
upstream=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null)

if [ -z "$upstream" ]; then
  # upstream 未配置
  upstream_configured=false
  ahead=null
  behind=null
  reason="no_upstream"
else
  upstream_configured=true

  # 检查是否 detached HEAD
  branch_name=$(git branch --show-current 2>/dev/null)
  if [ -z "$branch_name" ]; then
    ahead=null
    behind=null
    reason="detached_head"
  else
    # 安全计算 ahead/behind（浅克隆检测在步骤 3，此处先算，若 shallow 后覆盖为 null）
    ahead=$(git rev-list --count "${upstream}..HEAD" 2>/dev/null) || ahead=null
    behind=$(git rev-list --count "HEAD..${upstream}" 2>/dev/null) || behind=null
    reason=null
  fi
fi
```

### 步骤 3: 浅克隆检测（修复 m5 / Decision D12）

含 git 版本 fallback，处理 `git rev-parse --is-shallow-repository` 在 git < 2.15 不可用的情况。

```bash
# 探测 git 版本
git_version=$(git --version | awk '{print $3}')
git_major=$(echo "$git_version" | cut -d. -f1)
git_minor=$(echo "$git_version" | cut -d. -f2)

if [ "$git_major" -gt 2 ] || { [ "$git_major" -eq 2 ] && [ "$git_minor" -ge 15 ]; }; then
  # git >= 2.15: 使用内置选项
  is_shallow=$(git rev-parse --is-shallow-repository 2>/dev/null)
else
  # git < 2.15: fallback 到 .git/shallow 文件检测
  git_dir=$(git rev-parse --git-dir 2>/dev/null)
  if [ -f "${git_dir}/shallow" ]; then
    is_shallow="true"
  else
    is_shallow="false"
  fi
fi

if [ "$is_shallow" = "true" ]; then
  shallow=true
  # 覆盖步骤 2 的 ahead/behind
  ahead=null
  behind=null
  reason="shallow_clone"
else
  shallow=false
fi
```

### 步骤 4: FETCH_HEAD 时间戳读取（跨平台，修复 m4）

使用 `git log` 方式读取，避免 `stat -c`（Linux only）和 `stat -f`（macOS only）的平台差异。

```bash
remote_refs_age=$(git log -1 --format="%cr" FETCH_HEAD 2>/dev/null)
if [ -z "$remote_refs_age" ]; then
  remote_refs_age="never"
fi
```

`FETCH_HEAD > warn_after_hours`（默认 24h）时，在输出中附加 warning 标注（"建议执行 git fetch"）。

### 步骤 5: Submodule 遍历 + 四级 fallback 链（修复 M4 / Decision D10）

跳过未初始化的子模块，不报错。

```bash
# 获取已初始化的子模块列表
git submodule status 2>/dev/null | while read -r sha path extra; do
  # 以 '-' 开头的 sha 表示未初始化，跳过
  case "$sha" in
    -*) continue ;;
  esac

  # 获取主仓库 HEAD 记录的 commit（tree_commit）
  tree_commit=$(git ls-tree HEAD -- "$path" 2>/dev/null | awk '{print $3}')

  # 获取本地 checkout 的 commit（head_commit）
  head_commit=$(git -C "$path" rev-parse HEAD 2>/dev/null) || head_commit=null

  # 计算 remote_commit（四级 fallback 链）
  remote_commit=""
  remote_commit_source=""

  # Tier 1: origin/HEAD（若已配置 git remote set-head）
  remote_commit=$(git -C "$path" rev-parse refs/remotes/origin/HEAD 2>/dev/null)
  if [ -n "$remote_commit" ]; then
    remote_commit_source="origin_HEAD"
  fi

  # Tier 2: ls-remote（网络操作，5s 超时）
  if [ -z "$remote_commit" ]; then
    remote_commit=$(timeout 5 git -C "$path" ls-remote origin HEAD 2>/dev/null | awk '{print $1}')
    if [ -n "$remote_commit" ]; then
      remote_commit_source="ls-remote"
    fi
  fi

  # Tier 3: 读 init.defaultBranch config + 本地 refs
  if [ -z "$remote_commit" ]; then
    default_branch=$(git -C "$path" config --get init.defaultBranch 2>/dev/null || echo "main")
    remote_commit=$(git -C "$path" rev-parse "refs/remotes/origin/${default_branch}" 2>/dev/null)
    if [ -n "$remote_commit" ]; then
      remote_commit_source="config_default"
    fi
  fi

  # Tier 4: 全部失败 → null + warning
  if [ -z "$remote_commit" ]; then
    remote_commit=null
    remote_commit_source="unavailable"
  fi

  # 计算偏差
  # workdir_vs_tree: 工作目录偏离主仓库记录
  if [ "$head_commit" != "$tree_commit" ] && [ "$head_commit" != "null" ]; then
    workdir_vs_tree=true
  else
    workdir_vs_tree=false
  fi

  # tree_vs_remote: 主仓库记录落后远程
  if [ "$remote_commit" != "null" ] && [ "$tree_commit" != "$remote_commit" ]; then
    tree_vs_remote=true
    behind_count=$(git -C "$path" rev-list --count "${tree_commit}..${remote_commit}" 2>/dev/null) || behind_count=null
    hint="git submodule update --remote ${path}"
  else
    tree_vs_remote=false
    behind_count=null
    hint=null
  fi

  # 输出该子模块条目...
done
```

### 步骤 6: 计算 `diverged`

```bash
if [ "$ahead" != "null" ] && [ "$behind" != "null" ]; then
  if [ "$ahead" -gt 0 ] && [ "$behind" -gt 0 ]; then
    diverged=true
  else
    diverged=false
  fi
else
  diverged=null
fi
```

---

## 4. Fail-soft 字段语义表格

| 状态 | `shallow` | `behind` | `reason` |
|------|-----------|----------|----------|
| 正常（有 upstream，非浅克隆） | `false` | 数字 | `null` |
| 浅克隆 | `true` | `null` | `"shallow_clone"` |
| 无 upstream | `false` | `null` | `"no_upstream"` |
| detached HEAD | `false` | `null` | `"detached_head"` |

规则（Decision D9 权威定义）：任一命令失败 → 对应字段 `null` + `reason` 标注 + warning，绝不 exit ≠ 0，绝不阻塞后续阶段。

---

## 5. 边界场景处理

| 场景 | 行为 | 字段表现 |
|------|------|---------|
| 无 remote（纯本地仓库） | 跳过所有远程相关字段 | `has_remote: false` |
| FETCH_HEAD 缺失 | 标注 never | `remote_refs_age: "never"` |
| FETCH_HEAD > `warn_after_hours`（默认 24h） | 输出附加 warning | `remote_refs_age: "2d"` + warning |
| upstream 未配置 | 跳过 ahead/behind 计算 | `ahead: null, behind: null, reason: "no_upstream"` |
| detached HEAD | 跳过分支名和 upstream | `current_branch.name: null, reason: "detached_head"` |
| 浅克隆 | 跳过 behind 计算 | `shallow: true, behind: null, reason: "shallow_clone"` |
| 子模块未初始化（sha 以 `-` 开头） | 跳过该条目，不报错 | 该 submodule 条目不出现 |
| `git ls-remote` 超时（> 5s）或失败 | Tier 2 失败 → 降级 Tier 3/4 | `remote_commit_source: "unavailable"` 或 `"config_default"` |
| Tier 3 本地 config defaultBranch 与远端不一致 | 接受为 fail-soft 可接受误差 | `remote_commit_source: "config_default"` |
| 浅克隆 worktree 下 `.git/shallow` 路径不同 | 通过 `git rev-parse --git-dir` 动态定位 | 正常检测 |
| 子模块 remote URL 为 fork/mirror | 不影响检测逻辑，来源透明标注 | `remote_commit_source` 字段说明来源 |
| 子模块数量 > 10 | 当前串行遍历；超 10 个时引入并行（future） | 输出正常，耗时线性增长 |
| 阶段总超时（10s）触发 | 已遍历的子模块正常输出，未遍历的跳过 | 已处理条目保留 |

---

## 6. 跨平台命令参考

| 功能 | 兼容命令 | 备注 |
|------|---------|------|
| FETCH_HEAD 时间戳 | `git log -1 --format=%cr FETCH_HEAD 2>/dev/null` | 跨平台；避免 `stat -c`（Linux only）/ `stat -f`（macOS only）差异 |
| 浅克隆检测（git ≥ 2.15） | `git rev-parse --is-shallow-repository` | 返回 `true`/`false` 字符串 |
| 浅克隆检测（fallback） | `[ -f "$(git rev-parse --git-dir)/shallow" ] && echo true` | 兼容 git < 2.15，动态定位 git 目录 |
| git 版本探测 | `git --version \| awk '{print $3}'` | 决定是否使用 fallback |
| upstream 探测 | `git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null` | 无 upstream 时返回空字符串 |
| 子模块 tree commit | `git ls-tree HEAD -- <path> \| awk '{print $3}'` | 读主仓库记录，不访问子目录 |
| 网络操作超时 | `timeout 5 git -C <sub> ls-remote origin HEAD` | POSIX `timeout`；Windows Git Bash 通过 Git 内置支持 |
| 分支名检测 | `git branch --show-current` | git ≥ 2.22；旧版 fallback: `git rev-parse --abbrev-ref HEAD` |

---

## 7. 配置项

由 `config-loader` 加载，配置块 `state_scanner.sync_check`：

```json
{
  "state_scanner": {
    "sync_check": {
      "enabled": true,
      "check_submodules": true,
      "warn_after_hours": 24
    }
  }
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | boolean | `true` | Phase 1.12 主开关（本地 git 操作，默认开启） |
| `check_submodules` | boolean | `true` | 是否检测子模块偏差 |
| `warn_after_hours` | number | `24` | FETCH_HEAD 陈旧度告警阈值（小时） |

配置分层原则（Decision D12）：单阶段子配置使用嵌套 object（`state_scanner.sync_check.*`）；全局开关使用扁平字段（`state_scanner.confidence_threshold`）。

---

## 8. 输出示例

### 场景 A: 正常同步

```
🔄 同步状态
───────────────────────────────────────────────────────────────
  当前分支: master (超前 0 / 落后 0)
  远程引用: 30m 前同步
  子模块:
    ✅ aria: 同步
    ✅ standards: 同步
    ✅ aria-orchestrator: 同步
```

对应 YAML：

```yaml
sync_status:
  has_remote: true
  remote_refs_age: "30m"
  shallow: false
  current_branch:
    name: "master"
    upstream: "origin/master"
    upstream_configured: true
    ahead: 0
    behind: 0
    diverged: false
    reason: null
  submodules:
    - path: "aria"
      tree_commit: "abc1234"
      head_commit: "abc1234"
      remote_commit: "abc1234"
      remote_commit_source: "origin_HEAD"
      drift:
        workdir_vs_tree: false
        tree_vs_remote: false
        behind_count: null
        hint: null
```

### 场景 B: 落后远程

```
🔄 同步状态
───────────────────────────────────────────────────────────────
  当前分支: master (落后 origin/master 3 commits)
  远程引用: 2h 前同步
  子模块:
    ✅ standards: 同步
    ⚠️  aria: 落后远程 4 commits
        修复建议: git submodule update --remote aria
```

对应 YAML（关键字段）：

```yaml
sync_status:
  remote_refs_age: "2h"
  current_branch:
    behind: 3
    diverged: false
    reason: null
  submodules:
    - path: "aria"
      remote_commit: "def5678"
      remote_commit_source: "ls-remote"
      drift:
        tree_vs_remote: true
        behind_count: 4
        hint: "git submodule update --remote aria"
```

### 场景 C: 浅克隆

```
🔄 同步状态
───────────────────────────────────────────────────────────────
  当前分支: master (浅克隆，无法计算落后数)
  远程引用: never (未执行 git fetch)
  ⚠️ 浅克隆模式: 落后计算不可用
```

对应 YAML（关键字段）：

```yaml
sync_status:
  has_remote: true
  remote_refs_age: "never"
  shallow: true
  current_branch:
    name: "master"
    upstream: "origin/master"
    upstream_configured: true
    ahead: null
    behind: null
    diverged: null
    reason: "shallow_clone"
```

---

## 9. 与推荐规则的联动

Phase 1.12 输出直接驱动阶段 2 的两条推荐规则（均不阻断，仅降级 + 附加提示，遵循 fail-soft 原则）：

| 规则 ID | 触发条件 | 动作 |
|---------|---------|------|
| `submodule_drift` | 任一 submodule `drift.tree_vs_remote: true` | 降级推荐置信度，附加 `git submodule update --remote <path>` 提示 |
| `branch_behind_upstream` | `current_branch.behind >= 5` | 降级推荐置信度，附加 "建议先执行 git pull" 提示 |

两条规则定义详见 `RECOMMENDATION_RULES.md`（`submodule_drift` 和 `branch_behind_upstream` 条目）。

子阶段数量追踪（Decision D8）：当前 12/15，超过 15 时须重构为分组（Git / Context / Quality）或合并语义相近阶段。

---

**创建**: 2026-04-09
**版本**: 1.0.0
**对应 Spec**: `openspec/changes/state-scanner-remote-sync-check/proposal.md`
