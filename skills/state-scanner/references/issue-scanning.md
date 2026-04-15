# Phase 1.13: Issue 感知扫描 — 详细实现逻辑

> **版本**: 1.1.0 | **适用于**: state-scanner 阶段 1.13
> **关联 Spec**:
> - v1.0.0: `state-scanner-issue-awareness` (v2.9.0, 2026-04-09 归档)
> - v1.1.0: `state-scanner-submodule-issue-scan` (v2.10.0 / aria-plugin v1.16.0, 2026-04-15 Draft)
> **fail-soft 定义**: 锚定 `state-scanner-remote-sync-check/proposal.md#D9`

---

## 概览

Phase 1.13 在阶段 1.12 (同步检测) 之后、阶段 2 (推荐决策) 之前执行，职责为：

1. 调用 Git 平台 API 拉取主仓库当前所有 open issues
2. 对每个 issue 执行启发式关联，匹配 `US-NNN` 引用和 OpenSpec change 名称
3. 将结构化结果写入 `issue_status` 输出字段，供阶段 2 推荐决策使用

**关键约束**: 默认 `enabled: false` (opt-in)；任何错误均 fail-soft，绝不阻塞主流程。

---

## 输出 Schema

**v1.0.0 单 repo 格式** (默认 `scan_submodules=false`, 保持向后兼容):

```yaml
issue_status:
  schema_version: "1.0"                 # v1.1.0+ 新增, 标识 schema 版本
  fetched_at: "2026-04-09T10:23:00Z"    # ISO 8601 UTC (聚合视图时间戳)
  source: cache | live | unavailable    # 数据来源
  fetch_error: null                     # 见 fetch_error 枚举表 (10 个值)
  warning: null                         # 可选警告，如 "stale_cache_api_failed"
  platform: forgejo | github | null     # 检测到的平台
  open_count: 3                         # open issues 总数
  items:                                # v1.0/v1.1 共有: 扁平 items 列表
    - number: 6
      title: "state-scanner: add issue scan and sync detection"
      labels: ["enhancement", "skill"]
      url: "https://forgejo.10cg.pub/10CG/Aria/issues/6"
      linked_openspec: "state-scanner-issue-awareness"  # 启发式，null 表示无匹配
      linked_us: null                                    # 启发式，null 表示无匹配
      heuristic: true                                    # 标注为启发式结果
      repo: "10CG/Aria"                                  # v1.1.0+ 新增 — 来源 repo (v1.0 场景下固定为主 repo)
  # v1.1.0+ 新增: 向后兼容别名 (写入时同步写, 读取时优先 items, fallback open_issues)
  open_issues:                          # 别名: 指向同一份 items 列表, 避免 v1.0 消费者 break
  # ^ 实际实现上, open_issues 与 items 指向同一数组 (jq '.open_issues = .items')
  label_summary:                        # 按 label 聚合统计 (全局, 跨 repo)
    bug: 1
    enhancement: 2
```

**v1.1.0+ 多 repo 格式** (`scan_submodules=true`):

```yaml
issue_status:
  schema_version: "1.1"                 # v1.1.0 固定
  fetched_at: "2026-04-15T10:00:00Z"    # 聚合 fetched_at (最后一次全量 refresh 时间)
  source: live                          # 以主 repo 为准
  fetch_error: null                     # 聚合 error (任一 repo 失败则降级显示)
  warning: null
  platform: forgejo                     # 以主 repo 为准
  open_count: 5                         # 所有 repos 的 items 聚合总数
  items:                                # 聚合扁平视图 — 每个 item 带 repo 字段
    - { number: 16, title: "...", repo: "10CG/Aria", ... }
    - { number: 18, title: "...", repo: "10CG/aria-plugin", ... }
    # ...
  open_issues:                          # 向后兼容别名 (同上, 指向 items)
  repos:                                # v1.1.0+ 分组视图 — 按 repo key 隔离
    "10CG/Aria":
      platform: forgejo
      source: live
      fetch_error: null
      fetched_at: "2026-04-15T10:00:00Z"   # v1.1.0+ 修复 C2 — 每 repo 独立时间戳
      open_count: 2
      items: [...]
    "10CG/aria-plugin":
      platform: forgejo
      source: live
      fetch_error: null
      fetched_at: "2026-04-15T10:00:00Z"
      open_count: 2
      items: [...]
  label_summary:                        # 跨 repo 聚合
    bug: 1
    enhancement: 4
```

**字段规则**:
- 所有字符串字段缺失时降级为空字符串 `""`，不使用 `null`
- `labels` 缺失时降级为空数组 `[]`
- `fetch_error` 为 `null` 表示成功，否则为 10 个枚举值之一
- `source: unavailable` 时 `items` 为空数组，`open_count` 为 0
- **v1.1.0+ 向后兼容**: `open_issues` 与 `items` 始终指向同一份数据 (writer 同步双写). v1.0 消费者读 `open_issues` 仍然可用, v1.1 消费者应优先读 `items`. 未来 v2.x 可移除 `open_issues` 别名 (deprecation 至少跨 2 个 MINOR 版本)
- **v1.1.0+ schema_version**: 必填字段. `"1.0"` = 仅主 repo 扁平结构, `"1.1"` = 含 `repos` 分组视图. 读取端应先判断 `schema_version` 再决定消费策略
- **v1.1.0+ per-repo fetched_at**: `repos[owner/repo].fetched_at` 独立, 允许部分 refresh (某 repo 缓存命中, 其他 repo live fetch). 聚合视图 `issue_status.fetched_at` = 所有 repo 中 **最早** 的 `fetched_at` (保守, 表达"整体新鲜度下限")

---

## 执行流程

串行执行，每步失败即进入降级路径：

```
步骤 1: 前置检查 — enabled 开关
步骤 2: 平台检测 (4 级优先级)
步骤 3: CLI 可用性检查
步骤 4: 缓存读取 (TTL 15 分钟)
步骤 5: API 调用 (缓存未命中时)
步骤 6: JSON normalize (Forgejo / GitHub 映射)
步骤 7: 启发式关联计算
步骤 8: 缓存写回 (原子 tmp + mv)
步骤 9: 构造 issue_status 输出
```

### 步骤 1: 前置检查

```bash
enabled=$(jq -r '.state_scanner.issue_scan.enabled // false' .aria/config.json)
if [ "$enabled" != "true" ]; then
  # 静默跳过，issue_status 字段完全省略
  exit 0
fi
```

`enabled` 非 `true` 时静默跳过，不输出任何 `issue_status` 字段，不打印警告。

### 步骤 2: 平台检测

见下方"平台检测逻辑"章节，检测失败时 `fetch_error: "platform_unknown"`，静默跳过。

### 步骤 3: CLI 可用性检查

```bash
if [ "$platform" = "forgejo" ]; then
  command -v forgejo >/dev/null 2>&1 || { fetch_error="cli_missing"; exit_soft; }
elif [ "$platform" = "github" ]; then
  command -v gh >/dev/null 2>&1 || { fetch_error="cli_missing"; exit_soft; }
fi
```

CLI 未找到时 exit code 为 127，判定为 `cli_missing`，判定顺序在 `network_unavailable` 之前 (修复 N3)。

### 步骤 4: 缓存读取

**v1.1.0+ (修复 R1 C1 cache_schema_migration_gap)**: 读取前必须检查 `schema_version` 字段, 若缺失或低于当前版本则视为**冷缓存** (cold cache), 强制 invalidate 并重新 fetch。这避免了从 pre-v1.1 升级的用户静默读到旧 schema。

```bash
cache_path=$(jq -r '.state_scanner.issue_scan.cache_path // ".aria/cache/issues.json"' .aria/config.json)
ttl=$(jq -r '.state_scanner.issue_scan.cache_ttl_seconds // 900' .aria/config.json)
# 统一初始化 now_ts (v1.1 修复 M2 now_ts 未定义):
now_ts=$(date +%s)

# v1.1.0+ 初始化 all_repos_json 聚合器 (修复 R1 M4):
all_repos_json=$(jq -n '{}')

# 跨平台 date → epoch 解析函数 (v1.1 修复 R1 I5 GNU-date-only):
parse_iso8601_to_epoch() {
  local ts="$1"
  # 优先 python3 (POSIX-ubiquitous), fallback 到 GNU date / BSD date
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "import sys,datetime; print(int(datetime.datetime.fromisoformat(sys.argv[1].replace('Z','+00:00')).timestamp()))" "$ts" 2>/dev/null && return 0
  fi
  date -d "$ts" +%s 2>/dev/null && return 0          # GNU date (Linux/WSL)
  date -j -f "%Y-%m-%dT%H:%M:%SZ" "$ts" +%s 2>/dev/null && return 0  # BSD date (macOS)
  echo ""  # 无法解析 → 返回空, 调用方应将其视为 cache miss
}

if [ -f "$cache_path" ]; then
  # v1.1 修复 C1: schema_version 守卫
  cache_schema=$(jq -r '.schema_version // "0.0"' "$cache_path" 2>/dev/null)
  case "$cache_schema" in
    "1.0"|"1.1")
      : # 兼容, 继续
      ;;
    *)
      # 未知或 pre-v1.1 schema → 冷缓存, 跳过本次读取, 下次写入时重建
      echo "[info] cache schema $cache_schema < 1.0, treating as cold cache (one-time re-fetch)"
      # 不 rm, 让 step 8 原子覆写; 继续到 API 调用
      schema_invalid=1
      ;;
  esac

  if [ -z "$schema_invalid" ]; then
    fetched_at=$(jq -r '.fetched_at // ""' "$cache_path")
    cache_ts=$(parse_iso8601_to_epoch "$fetched_at")
    if [ -n "$cache_ts" ]; then
      age=$((now_ts - cache_ts))
      if [ "$age" -lt "$ttl" ]; then
        # 缓存命中，source: cache
        source="cache"
        # v1.1 向后兼容: 优先读 items, fallback 到 open_issues 别名
        issues_json=$(jq '.items // .open_issues // []' "$cache_path")
        # 跳转至步骤 7
      fi
    fi
  fi
fi
```

缓存命中时跳过 API 调用，直接进入启发式关联步骤。

**schema_version 语义**:

| cache 中 schema_version | reader 行为 |
|---|---|
| 缺失 / `"0.0"` / `"0.x"` | 视为 pre-v1.1 旧 cache, **忽略内容**, 一次性 re-fetch, 下次写回时附带 `"1.1"` |
| `"1.0"` | 兼容读取 (仅 `items[]` + `open_issues` 别名) |
| `"1.1"` | 完整读取 (`items[]` + `repos{}` 分组视图) |
| `"1.2"` 或未来更高 | 未来版本, 视为 downgrade 场景, 保守 fail-soft 重新 fetch + warning |

### 步骤 5: API 调用

总阶段超时 12s，单次 API 调用超时 5s (修复 m9)：

**Forgejo 分支**:

```bash
# 稳健提取 owner/repo: 剥离协议/hostname/端口/.git/query string
# 兼容: https://host/owner/repo.git | ssh://git@host:2222/owner/repo.git | git@host:owner/repo.git
remote_url=$(git remote get-url origin)
# 1. 剥离协议 + 用户@ + hostname(:port)
stripped=$(echo "$remote_url" | sed -E 's|^[a-z]+://||; s|^[^@]+@||; s|^[^:/]+[:/]||')
# 2. 去掉尾部 .git 和可能的 query/fragment
owner_repo=$(echo "$stripped" | sed -E 's|\.git([?#/].*)?$||; s|\.git$||; s|/$||')
# 3. 验证格式: owner/repo (不允许更多层级)
if ! echo "$owner_repo" | grep -qE '^[^/]+/[^/]+$'; then
  echo "fetch_error: parse_error (owner/repo extraction failed: $remote_url)"
  # 继续其他阶段，不阻塞
fi

limit=$(jq -r '.state_scanner.issue_scan.limit // 20' .aria/config.json 2>/dev/null || echo 20)

response=$(timeout 5 forgejo GET "/repos/${owner_repo}/issues?state=open&limit=${limit}" 2>&1)
exit_code=$?
```

**GitHub 分支**:

```bash
limit=$(jq -r '.state_scanner.issue_scan.limit // 20' .aria/config.json)

response=$(timeout 5 gh issue list --state open \
  --json number,title,labels,url,body \
  --limit "$limit" 2>&1)
exit_code=$?
```

API 调用错误判定见"fetch_error 枚举值"章节。

### 步骤 6: JSON Normalize

见下方"IssueItem Normalize 映射表"章节。

### 步骤 7: 启发式关联

见下方"启发式关联算法"章节。

### 步骤 8: 缓存写回 (原子)

```bash
tmp_path="${cache_path}.tmp.$$"
jq -n \
  --arg fetched_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg platform "$platform" \
  --argjson issues "$normalized_issues" \
  '{"fetched_at": $fetched_at, "platform": $platform, "open_issues": $issues}' \
  > "$tmp_path" && mv "$tmp_path" "$cache_path"
```

`mv` 为原子操作，防止写入中途读取到损坏文件。

---

## 平台检测逻辑

4 级优先级，按顺序检测，首个成功即采用：

```bash
detect_platform() {
  local config_path=".aria/config.json"

  # 优先级 1: 显式声明
  platform=$(jq -r '.state_scanner.issue_scan.platform // empty' "$config_path" 2>/dev/null)
  if [ -n "$platform" ] && [ "$platform" != "null" ]; then
    echo "$platform"
    return 0
  fi

  # 优先级 2: hostname 匹配 platform_hostnames 映射表
  remote_url=$(git remote get-url origin 2>/dev/null)
  hostname=$(echo "$remote_url" | sed 's|.*://\([^/:]*\).*|\1|; s|.*@\([^:]*\):.*|\1|')

  forgejo_hosts=$(jq -r '.state_scanner.issue_scan.platform_hostnames.forgejo[]? // empty' "$config_path" 2>/dev/null)
  github_hosts=$(jq -r '.state_scanner.issue_scan.platform_hostnames.github[]? // empty' "$config_path" 2>/dev/null)

  for host in $forgejo_hosts; do
    if [ "$hostname" = "$host" ]; then
      echo "forgejo"
      return 0
    fi
  done

  for host in $github_hosts; do
    if [ "$hostname" = "$host" ]; then
      echo "github"
      return 0
    fi
  done

  # 优先级 3: 兜底推断 (URL 子串)
  if echo "$remote_url" | grep -q "github\.com"; then
    echo "github"
    return 0
  fi

  # 优先级 4: 全失败
  echo "platform_unknown"
  return 1
}
```

优先级说明:

| 优先级 | 触发条件 | 结果 |
|--------|---------|------|
| 1 | `issue_scan.platform` 字段非 null | 直接使用配置值 |
| 2 | remote hostname 在 `platform_hostnames` 映射表中 | 匹配到的平台 |
| 3 | remote URL 包含 `github.com` | `github` |
| 4 | 以上全部失败 | `fetch_error: "platform_unknown"` |

---

## IssueItem Normalize 映射表

将 Forgejo API 响应和 GitHub CLI 响应统一为规范 `IssueItem` 格式：

| 规范字段 | Forgejo API JSON 路径 | GitHub (gh) JSON 路径 | 缺失时默认值 |
|---------|-----------------------|----------------------|-------------|
| `number` | `.number` | `.number` | `0` |
| `title` | `.title` | `.title` | `""` |
| `labels[]` | `.labels[].name` | `.labels[].name` | `[]` |
| `url` | `.html_url` | `.url` | `""` |
| `body` | `.body` | `.body` | `""` |

**Forgejo normalize jq 示例**:

```bash
normalized=$(echo "$response" | jq '[.[] | {
  number: (.number // 0),
  title: (.title // ""),
  labels: ([.labels[]?.name] // []),
  url: (.html_url // ""),
  body: (.body // "")
}]')
```

**GitHub normalize jq 示例** (gh 输出已是 JSON 数组):

```bash
normalized=$(echo "$response" | jq '[.[] | {
  number: (.number // 0),
  title: (.title // ""),
  labels: ([.labels[]?.name] // []),
  url: (.url // ""),
  body: (.body // "")
}]')
```

所有字段缺失均降级为空字符串或空数组，不使用 `null`，避免 jq 嵌套判断复杂化。

---

## 启发式关联算法

对每个 issue 的 `title` 和 `body` 字段执行正则匹配（不扫描 comments）。

**跨平台策略** (Round 1 pre_merge M6 fix): 主流程**优先使用 awk** (POSIX 标准, 跨平台可用); `grep -P` / `grep -oP` 仅作为 fallback, 且始终探测可用性后再使用.

### 能力探测 (执行前一次性检测)

```bash
# 一次性探测 grep -P 是否可用, 结果缓存在 $GREP_HAS_PCRE
if echo "" | grep -qP "" 2>/dev/null; then
  GREP_HAS_PCRE=1
else
  GREP_HAS_PCRE=0
fi
```

### US-NNN 匹配

**主流程 (awk, 跨平台)**:

```bash
linked_us=$(echo "$title $body" | awk '
  {
    while (match($0, /(^|[^A-Za-z0-9])US-[0-9][0-9][0-9]+([^A-Za-z0-9]|$)/)) {
      token = substr($0, RSTART, RLENGTH)
      gsub(/[^A-Za-z0-9-]/, "", token)
      print token
      exit
    }
  }
' | head -1)
[ -z "$linked_us" ] && linked_us="null"
```

**Fallback (grep -oP, 仅当 GREP_HAS_PCRE=1)**:
```bash
if [ "$GREP_HAS_PCRE" = "1" ] && [ -z "$linked_us" ]; then
  linked_us=$(echo "$title $body" | grep -oP '\bUS-\d{3,}\b' | head -1)
  [ -z "$linked_us" ] && linked_us="null"
fi
```

### OpenSpec change 名称匹配

扫描 `openspec/changes/*/` 目录，对每个 change 名称生成单词边界正则，防止 URL 路径误匹配。

**主流程 (awk, 跨平台)**:

```bash
linked_openspec="null"
if [ -d "openspec/changes" ]; then
  for change_dir in openspec/changes/*/; do
    change_name=$(basename "$change_dir")
    # awk 不需要正则元字符转义 (literal string 模式), 但需要 ERE 字符类
    found=$(echo "$title $body" | awk -v name="$change_name" '
      BEGIN {
        # 构造边界模式: 前面为 ^ 或非 [a-z0-9/-], 后面为 $ 或非 [a-z0-9/-]
        # literal name 无需 escape (不走 ERE 编译路径, 用 index() 做子串定位 + 边界验证)
      }
      {
        line = $0
        name_len = length(name)
        pos = 1
        while ((idx = index(substr(line, pos), name)) > 0) {
          absolute = pos + idx - 1
          left_char = (absolute == 1) ? "" : substr(line, absolute - 1, 1)
          right_char = substr(line, absolute + name_len, 1)
          # 边界检查: 两侧不能是 [a-z0-9/-]
          if (left_char !~ /[a-z0-9\/-]/ && right_char !~ /[a-z0-9\/-]/) {
            print name
            exit 0
          }
          pos = absolute + 1
        }
      }
    ')
    if [ -n "$found" ]; then
      linked_openspec="$change_name"
      break
    fi
  done
fi
```

**Fallback (grep -P, 仅当 GREP_HAS_PCRE=1)**:

```bash
if [ "$GREP_HAS_PCRE" = "1" ] && [ "$linked_openspec" = "null" ] && [ -d "openspec/changes" ]; then
  for change_dir in openspec/changes/*/; do
    change_name=$(basename "$change_dir")
    # 正则元字符转义 (防止 . + ? 等误匹配)
    # Round 1 code-review fix: 补全 ] 和 - 转义
    escaped_name=$(printf '%s' "$change_name" | sed 's/[].[\*^$+?(){}|\\/-]/\\&/g')
    pattern="(?<![a-z0-9/-])${escaped_name}(?![a-z0-9/-])"
    if echo "$title $body" | grep -qP "$pattern"; then
      linked_openspec="$change_name"
      break
    fi
  done
fi
```

**优势**:
- awk 在 Git Bash / WSL / macOS / Linux / BusyBox / Alpine 全部可用, 是真正的跨平台主流程
- 使用 `index()` + 边界字符检查而非正则编译, 自动规避元字符转义问题 (Round 1 code-review cr_m3 根因)
- grep -P fallback 仅作为加速路径, 主流程不依赖它

### URL 路径保护测试 case

| 输入文本 | 期望 `linked_openspec` | 说明 |
|---------|----------------------|------|
| `"fix state-scanner-issue-awareness auth"` | `"state-scanner-issue-awareness"` | 正常标题匹配 |
| `"https://repo/openspec/changes/state-scanner-issue-awareness/proposal.md"` | `null` | URL 路径不匹配 (负向查找保护) |
| `"related: state-scanner-issue-awareness"` | `"state-scanner-issue-awareness"` | 冒号后空格，边界成立 |
| `"my-state-scanner-issue-awareness-fork"` | `null` | 被 `-` 前缀阻断 (负向查找) |

US-NNN 正则测试 case:

| 输入文本 | 期望 `linked_us` | 说明 |
|---------|----------------|------|
| `"fix US-006 auth flow"` | `"US-006"` | 标准匹配 |
| `"fixUS-006"` | `null` | 无单词边界 |
| `"US-6"` | `null` | 少于 3 位数字 |
| `"US-123 and US-456"` | `"US-123"` | 取第一个匹配 |

---

## 10 个 fetch_error 枚举值

完整错误分类，与 `tasks.md T3` 完全对齐。**判定顺序**: `cli_missing` 先于 `network_unavailable` (修复 N3)。

| # | 判定顺序 | `fetch_error` 枚举 | 触发条件 | 用户面板行为 |
|---|---------|-------------------|---------|-------------|
| 1 | 最先判定 | `cli_missing` | `command -v forgejo/gh` 失败 (exit 127) | 提示安装命令 |
| 2 | | `auth_missing` | `.aria/config.json` 缺 token 字段或对应环境变量 | 提示 "未配置 token，跳过" |
| 3 | | `platform_unknown` | 4 级平台检测全部失败 | 静默跳过 |
| 4 | | `network_unavailable` | CLI exit != 0 且 stderr 含网络错误关键字 | 降级，用缓存 (若有) |
| 5 | | `auth_failed` | HTTP 401 / 403 | 提示 "权限不足 / token 过期" |
| 6 | | `rate_limited` | HTTP 429，读 `Retry-After` 头 | 使用缓存，显示 Retry-After 时间 |
| 7 | | `not_found_or_no_access` | HTTP 404 (真无此仓库 或 私有+无权限伪 404) | 歧义提示，建议检查仓库路径和权限 |
| 8 | | `timeout` | API 响应超过 `api_timeout_seconds` (5s) | 使用缓存 |
| 9 | | `parse_error` | jq 解析 API 响应失败 | 使用缓存 + warning |
| 10 | 最后兜底 | `unknown` | 其余未分类错误 | warning + stderr 片段 (前 200 字符) |

**HTTP 状态码判定**:

```bash
http_status=$(echo "$response_headers" | grep -oP 'HTTP/[0-9.]+ \K\d+' | tail -1)
case "$http_status" in
  401|403) fetch_error="auth_failed" ;;
  404)     fetch_error="not_found_or_no_access" ;;
  429)     fetch_error="rate_limited" ;;
esac
```

---

## Fail-soft 行为

所有错误场景均降级处理，绝不抛出异常或阻塞主流程 (锚定 sync-check D9)：

| 场景 | `source` | `fetch_error` | `items` | 用户可见 |
|------|---------|--------------|---------|---------|
| 正常拉取 | `live` | `null` | 完整列表 | 正常输出 |
| 缓存命中 | `cache` | `null` | 缓存列表 | 注明 "cache (Xm ago)" |
| 缓存过期 + API 成功 | `live` | `null` | 新鲜列表 | 正常输出 |
| 缓存过期 + API 失败 | `cache` | 具体枚举 | 旧缓存列表 | `warning: "stale_cache_api_failed"` |
| 无缓存 + API 失败 | `unavailable` | 具体枚举 | `[]` | 降级提示 |
| `enabled: false` | (字段省略) | (字段省略) | (字段省略) | 完全静默 |
| `platform_unknown` | `unavailable` | `platform_unknown` | `[]` | 静默跳过 |
| `cli_missing` | `unavailable` | `cli_missing` | `[]` | 提示安装 |

**总阶段超时保障**:

**方案 A: 函数封装 + SECONDS 早退 (推荐, 无变量作用域问题)**

```bash
issue_scan_stage() {
  local start=$SECONDS
  local timeout_sec=12

  # 步骤 2-8 的完整执行逻辑, 可直接访问外层变量 $cache_path / $platform
  detect_platform || return 1
  [ $((SECONDS - start)) -ge $timeout_sec ] && { fetch_error="timeout"; return 1; }

  read_cache || fetch_from_api
  [ $((SECONDS - start)) -ge $timeout_sec ] && { fetch_error="timeout"; return 1; }

  normalize_response
  return 0
}

issue_scan_stage
```

**方案 B: `timeout bash -c` + 显式导出变量 (如果必须用 timeout 子进程)**

```bash
# 重要: bash -c 子进程不继承非 export 变量，必须 export 或作为参数传递
export cache_path platform config_path limit

timeout 12 bash -c '
  # 可访问 $cache_path / $platform / $config_path / $limit (已 export)
  ...
'
exit_code=$?
if [ $exit_code -eq 124 ]; then
  fetch_error="timeout"
  # 降级到缓存或 unavailable
fi
```

**推荐使用方案 A** — 避免子进程变量作用域陷阱；SECONDS 内建变量零开销。

---

## 缓存策略

### 读取逻辑 (同步 refresh，修复 M10)

```
缓存文件存在?
├── 否 → 同步 API 调用 → 成功: 写缓存，source=live
│                      → 失败: source=unavailable, fetch_error=<枚举>
└── 是 → 检查 age (now - fetched_at)
    ├── age < TTL (15分钟) → source=cache，直接使用
    └── age >= TTL → 同步 API 调用
        ├── 成功 → 覆写缓存，source=live
        └── 失败 → 沿用旧缓存，source=cache，warning="stale_cache_api_failed"
```

**无后台任务**: bash skill 无后台异步模型，一律同步阻塞执行 (D11)。

### 缓存文件 Schema

`.aria/cache/issues.json`:

```json
{
  "fetched_at": "2026-04-09T10:23:00Z",
  "platform": "forgejo",
  "open_issues": [
    {
      "number": 6,
      "title": "state-scanner: add issue scan and sync detection",
      "labels": ["enhancement", "skill"],
      "url": "https://forgejo.10cg.pub/10CG/Aria/issues/6",
      "body": "..."
    }
  ]
}
```

### 命名空间隔离

- `.aria/cache/` 为 Skill 运行时缓存目录 (修复 m3)
- `config-loader` 不扫描 `.aria/cache/`
- `.gitignore` 必须包含 `.aria/cache/`，防止缓存文件被 Git 追踪

---

## 配置项

`state_scanner.issue_scan.*` 完整 9 字段清单：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | boolean | `false` | opt-in 开关，需显式设为 `true` |
| `platform` | string\|null | `null` | 显式指定平台 (`forgejo`/`github`)；`null` 则自动检测 |
| `platform_hostnames` | object | `{"forgejo":["forgejo.10cg.pub"],"github":["github.com"]}` | hostname → 平台映射，用户可追加自托管域名 |
| `cache_ttl_seconds` | integer | `900` | 缓存有效期 (15 分钟) |
| `cache_path` | string | `.aria/cache/issues.json` | 缓存文件路径 |
| `stage_timeout_seconds` | integer | `12` | 整阶段超时 (修复 m9) |
| `api_timeout_seconds` | integer | `5` | 单次 API 调用超时 |
| `limit` | integer | `20` | 单次拉取 open issue 上限 |
| `label_filter` | array | `[]` | 标签过滤；空数组表示不过滤，如 `["bug","blocker"]` |

**默认关闭原因**: 需要网络连接和 CLI token 配置，离线场景下强制启用会产生无意义错误。

---

## 超时设计

**v1.1 修复 R1 I2 + I3**: 总阶段超时**按 scan_submodules 分档 + 按 N 自适应**, 而非硬编码 20s。

| 层级 | 默认值 | 计算公式 | 实现 |
|------|--------|---------|------|
| 整阶段 `scan_submodules=false` | **12s** | 常量 (主 repo only, 复用 v1.0 D9 预算, **对现有用户零影响**) | `timeout 12 bash -c '...'` |
| 整阶段 `scan_submodules=true` | **自适应** | `max(20, (N_submodules + 1) × api_timeout_seconds)` | 启动时动态计算, 记录实际值 |
| 单次 API 调用 | 5s (不变) | 常量 | `timeout 5 forgejo GET ...` / `timeout 5 gh -C ...` |

**分档设计理由**:

1. **向后兼容保证 (修复 I3)**: `scan_submodules=false` 用户的行为与 v1.0 **完全一致** — 相同 12s 预算, 相同单 repo 扫描路径。tech-lead 在 Round 1 指出的"非 opt-in 副作用"被消除。
2. **自适应扩展 (修复 I2)**: `scan_submodules=true` 时, 预算从 `max(20, (N+1)×5s)` 自动计算, 其中 `max(20, ...)` 保证小项目有至少 20s 的合理 floor, `(N+1)×5s` 保证大项目 (如 N=10) 有足够预算扫完。backend-architect 在 Round 1 指出的"hardcoded 20s not scaling with N"被消除。
3. **AI 实现提示**: 启动 Phase 1.13 时, bash skill 应:
   ```bash
   if [ "$scan_submodules" = "true" ]; then
     n_subs=${#submodule_paths[@]}
     stage_budget=$(( (n_subs + 1) * 5 ))  # (N+1) × api_timeout_seconds
     if [ "$stage_budget" -lt 20 ]; then stage_budget=20; fi
   else
     stage_budget=12  # v1.0 常量, 向后兼容
   fi
   # 允许 config 显式覆盖 (例如降低 timeout 以 fast-fail)
   stage_budget=$(jq -r --argjson default "$stage_budget" '.state_scanner.issue_scan.stage_timeout_seconds // $default' .aria/config.json)
   ```

**配置项语义 (v1.1 澄清)**:
- `stage_timeout_seconds` 若用户显式设置 → 尊重用户值, **禁用自适应**, 用户自负其责 (可能太紧或太松)
- `stage_timeout_seconds` 若未设置 → 按 scan_submodules 分档默认值

**向后兼容保证 (精确)**: 一个 v1.15.2 用户升级到 v1.16.0:
- 不开启 `scan_submodules` → stage_timeout 仍为 12s, behaviour 完全一致
- 开启 `scan_submodules` 且未覆盖 `stage_timeout_seconds` → 自适应 (Aria 3 submodule → 20s, 其他项目按实际)
- 显式设置了 `stage_timeout_seconds: 12` → 尊重, 即使 scan_submodules=true 时也是 12s (用户可能需要 fast-fail)

超时触发时:
- 若缓存存在 (即使过期) → 沿用旧缓存 + `fetch_error: "timeout"` + `warning: "stale_cache_api_failed"`
- 若无缓存 → `source: unavailable`, `fetch_error: "timeout"`
- **v1.1**: submodule 部分超时时, 已完成扫描的 repo 结果保留, 未完成的 repo 不出现在 `repos` 中 (非 timeout 错误码, 因为没调用过), 聚合视图附加 `warning: "stage_timeout"` 提示用户预算不足

---

## 输出示例

### 场景 1: 正常拉取 (live)

```
🎫 Open Issues
───────────────────────────────────────────────────────────────
  平台: Forgejo (10CG/Aria) — 3 open
  #6  state-scanner: add issue scan      [enhancement, skill]
      -> 已关联 OpenSpec: state-scanner-issue-awareness (启发式)
  #5  Pulse 项目集成                      [feature]
  #4  某 bug 修复                         [bug]
  数据来源: live | ttl: 15m
```

```yaml
issue_status:
  fetched_at: "2026-04-09T10:23:00Z"
  source: live
  fetch_error: null
  warning: null
  platform: forgejo
  open_count: 3
  items:
    - number: 6
      title: "state-scanner: add issue scan and sync detection"
      labels: ["enhancement", "skill"]
      url: "https://forgejo.10cg.pub/10CG/Aria/issues/6"
      linked_openspec: "state-scanner-issue-awareness"
      linked_us: null
      heuristic: true
    - number: 5
      title: "Pulse 项目集成"
      labels: ["feature"]
      url: "https://forgejo.10cg.pub/10CG/Aria/issues/5"
      linked_openspec: null
      linked_us: null
      heuristic: true
    - number: 4
      title: "某 bug 修复"
      labels: ["bug"]
      url: "https://forgejo.10cg.pub/10CG/Aria/issues/4"
      linked_openspec: null
      linked_us: null
      heuristic: true
  label_summary:
    enhancement: 1
    skill: 1
    feature: 1
    bug: 1
```

### 场景 2: 离线降级 (unavailable)

```
🎫 Open Issues
───────────────────────────────────────────────────────────────
  [跳过] 网络不可达，无法拉取 issue 数据
  (fetch_error: network_unavailable)
```

```yaml
issue_status:
  fetched_at: null
  source: unavailable
  fetch_error: network_unavailable
  warning: null
  platform: forgejo
  open_count: 0
  items: []
  label_summary: {}
```

### 场景 3: 缓存命中 (cache)

```
🎫 Open Issues
───────────────────────────────────────────────────────────────
  平台: Forgejo (10CG/Aria) — 3 open
  #6  state-scanner: add issue scan      [enhancement, skill]
  数据来源: cache (8m ago) | ttl: 15m
```

```yaml
issue_status:
  fetched_at: "2026-04-09T10:15:00Z"
  source: cache
  fetch_error: null
  warning: null
  platform: forgejo
  open_count: 3
  items: [ ... ]   # 同场景 1
  label_summary:
    enhancement: 1
    skill: 1
```

### 场景 4: rate_limited + 旧缓存 fallback

```
🎫 Open Issues
───────────────────────────────────────────────────────────────
  平台: Forgejo (10CG/Aria) — 3 open (旧缓存, API 限速)
  #6  state-scanner: add issue scan      [enhancement, skill]
  [警告] API 返回 429，使用缓存数据 (可能已过期)
  Retry-After: 60s
```

```yaml
issue_status:
  fetched_at: "2026-04-09T09:50:00Z"   # 旧缓存时间
  source: cache
  fetch_error: rate_limited
  warning: "stale_cache_api_failed"
  platform: forgejo
  open_count: 3
  items: [ ... ]
  label_summary: { ... }
```

---

## submodule 扫描流程 (v1.1.0+)

> **适用条件**: `state_scanner.issue_scan.scan_submodules == true`
> **关联 Spec**: `state-scanner-submodule-issue-scan` (2026-04-15 Draft, aria-plugin v1.16.0)
> **默认行为**: `scan_submodules=false` 时本章节**完全跳过**, 与 v1.0.0 行为字节级一致

### 概览

当启用时, Phase 1.13 在完成主 repo 扫描后, 继续扫描 `.gitmodules` 中注册的所有 submodule。每个 submodule 是独立扫描单元, **串行执行**, **独立 fail-soft**, 结果聚合到同一个 `issue_status.repos` 结构。

### 适用场景判定

| 场景 | 推荐 `scan_submodules` | 理由 |
|------|----------------------|------|
| Meta-repo (如 Aria: 主 repo 只是 meta, 实际开发在 submodule) | `true` | submodule 是一等协同开发 repo, 不看会盲区 |
| Monorepo-of-submodules (同组织多仓库, 主 repo 协调) | `true` | 同上 |
| 传统项目 + vendored 依赖 (如 jQuery 作为 submodule) | `false` | submodule 是第三方依赖, 看 issue 制造噪音 |
| 纯应用项目, 无 submodule | `false` (不相关) | 无 `.gitmodules` 文件, 静默跳过 |

### 执行流程

```
步骤 1: 前置检查 (scan_submodules 开关)
步骤 2: 解析 .gitmodules 得到 submodule 列表
步骤 3: 对每个 submodule 独立执行:
  3.1: 进入 submodule 目录
  3.2: 读取 origin remote URL
  3.3: 解析 owner/repo
  3.4: 独立 platform 检测 (4 级优先级, 复用主流程)
  3.5: 独立 CLI 可用性检查
  3.6: 检查 repo 级缓存命中 (TTL 复用全局设置)
  3.7: API 调用 (timeout 5s)
  3.8: JSON normalize
  3.9: 启发式关联 (使用主 repo 的 openspec/changes/, D9 决策)
  3.10: 写入 issue_status.repos[owner/repo]
步骤 4: 聚合所有 repo 的 items 到 issue_status.items (flat 视图)
步骤 5: 更新 label_summary 聚合统计
步骤 6: 原子写回缓存 (单文件多 repo 结构)
```

### 步骤 1: 前置检查

```bash
scan_submodules=$(jq -r '.state_scanner.issue_scan.scan_submodules // false' .aria/config.json 2>/dev/null)
if [ "$scan_submodules" != "true" ]; then
  # 静默跳过 submodule 扫描, 仅返回主 repo 结果
  # issue_status.repos 仅包含主 repo 条目
  :  # 继续主流程的后续步骤
fi
```

### 步骤 2: 解析 .gitmodules

**首选方案** (POSIX, 跨平台, **v1.1 修复 R1 I4** 路径含空格):

将 submodule 路径写入 bash 数组而非 IFS-split 字符串, 避免路径含空格时 for-loop 错误分词 (AC-2 兼容性要求)。

```bash
submodule_paths=()
if [ -f .gitmodules ]; then
  # 用 while IFS= read -r 读取 git config 输出, 每行一路径, 保留空格
  while IFS= read -r path_line; do
    [ -n "$path_line" ] && submodule_paths+=("$path_line")
  done < <(git config --file .gitmodules --get-regexp '^submodule\..*\.path$' 2>/dev/null \
    | awk '{$1=""; sub(/^ /,""); print}')
fi
```

**备选方案** (若 `git config --file` 不可用):

```bash
submodule_paths=()
if [ -f .gitmodules ]; then
  while IFS= read -r path_line; do
    [ -n "$path_line" ] && submodule_paths+=("$path_line")
  done < <(awk -F= '/^[[:space:]]*path[[:space:]]*=/ {gsub(/^[[:space:]]+|[[:space:]]+$/,"",$2); print $2}' .gitmodules)
fi
```

**输出**: `${submodule_paths[@]}` 数组, 每元素是一个完整路径 (支持空格, 如 `my lib`)。后续迭代必须使用 `"${submodule_paths[@]}"` (带引号) 保持分词完整。

### 步骤 3: 逐 submodule 扫描

**关键变量约定** (v1.1 修复 R1 M2/M4):
- `now_ts` — 在步骤 4 开头已初始化为 `$(date +%s)`, 本循环复用
- `all_repos_json` — 在步骤 4 开头初始化为 `$(jq -n '{}')`, 本循环通过 `jq --argjson` 增量追加
- `submodule_paths` — 步骤 2 产出的 bash 数组 (支持空格)
- `helper functions` (record_repo_success / record_repo_error / classify_error / apply_heuristic_linking / detect_platform_for_url) — 逻辑占位符, AI 执行时应内联实现等效 jq 操作 (见下方各示例)

```bash
# 使用 "${submodule_paths[@]}" 带引号展开, 保留含空格路径完整性 (修复 R1 I4)
for submodule_path in "${submodule_paths[@]}"; do
  # 3.1: 验证 submodule 已初始化 (目录存在且含 .git 引用)
  if [ ! -d "$submodule_path" ] || [ ! -e "$submodule_path/.git" ]; then
    # v1.1 修复 R1 M3: fail-soft 矩阵一致性 — 未初始化 submodule 也记录条目
    # 用 path 作为临时 key (owner/repo 未知), 标记 fetch_error
    all_repos_json=$(echo "$all_repos_json" | jq --arg key "$submodule_path" '
      .[$key] = {
        platform: null,
        source: "unavailable",
        fetch_error: "submodule_not_initialized",
        fetched_at: null,
        open_count: 0,
        items: []
      }')
    continue
  fi

  # 3.2: 读取 submodule 的 origin remote
  sub_remote=$(git -C "$submodule_path" remote get-url origin 2>/dev/null)
  if [ -z "$sub_remote" ]; then
    all_repos_json=$(echo "$all_repos_json" | jq --arg key "$submodule_path" '
      .[$key] = { platform: null, source: "unavailable", fetch_error: "no_origin_remote", fetched_at: null, open_count: 0, items: [] }')
    continue
  fi

  # 3.3: 复用主流程的 owner/repo 提取逻辑
  stripped=$(echo "$sub_remote" | sed -E 's|^[a-z]+://||; s|^[^@]+@||; s|^[^:/]+[:/]||')
  sub_owner_repo=$(echo "$stripped" | sed -E 's|\.git([?#/].*)?$||; s|\.git$||; s|/$||')
  if ! echo "$sub_owner_repo" | grep -qE '^[^/]+/[^/]+$'; then
    # D11: 解析失败 → 跳过该 submodule, 不阻断整个 Phase 1.13
    all_repos_json=$(echo "$all_repos_json" | jq --arg key "$submodule_path" '
      .[$key] = { platform: null, source: "unavailable", fetch_error: "parse_error", fetched_at: null, open_count: 0, items: [] }')
    continue
  fi

  # 3.4: 独立 platform 检测
  sub_platform=$(detect_platform_for_url "$sub_remote")
  if [ "$sub_platform" = "platform_unknown" ]; then
    all_repos_json=$(echo "$all_repos_json" | jq --arg key "$sub_owner_repo" '
      .[$key] = { platform: null, source: "unavailable", fetch_error: "platform_unknown", fetched_at: null, open_count: 0, items: [] }')
    continue
  fi

  # 3.5: CLI 可用性 (主流程已验证, 此处复用)

  # 3.6: 缓存命中检查 (repo 级粒度, v1.1 修复 R1 C2 — 使用 per-repo fetched_at)
  # 注: v1.1 schema 中每个 repo 条目携带自己的 fetched_at, 支持部分 refresh
  cached=$(jq -r --arg key "$sub_owner_repo" '.repos[$key] // empty' "$cache_path" 2>/dev/null)
  if [ -n "$cached" ] && [ "$cached" != "null" ]; then
    cached_fetched_at=$(echo "$cached" | jq -r '.fetched_at // ""')
    if [ -n "$cached_fetched_at" ]; then
      # 使用跨平台 parse_iso8601_to_epoch (步骤 4 定义, 修复 R1 I5)
      cached_ts=$(parse_iso8601_to_epoch "$cached_fetched_at")
      if [ -n "$cached_ts" ] && [ $((now_ts - cached_ts)) -lt "$ttl" ]; then
        # 缓存命中, 跳过 API 调用, 直接追加到聚合器
        all_repos_json=$(echo "$all_repos_json" | jq --arg key "$sub_owner_repo" --argjson v "$cached" '
          .[$key] = $v')
        continue
      fi
    fi
  fi

  # 3.7: API 调用 (5s 超时)
  # v1.1 修复 R1 I6: 使用 gh -C 而非 cd + gh, 避免改变外层 shell 状态且正确捕获 exit code
  if [ "$sub_platform" = "forgejo" ]; then
    sub_response=$(timeout 5 forgejo GET "/repos/${sub_owner_repo}/issues?state=open&limit=${limit}" 2>&1)
    sub_exit=$?
  elif [ "$sub_platform" = "github" ]; then
    sub_response=$(timeout 5 gh -C "$submodule_path" issue list --state open --json number,title,labels,url,body --limit "$limit" 2>&1)
    sub_exit=$?
  fi

  # 3.8: 错误分类 (复用 10 个 fetch_error 枚举, D12)
  if [ $sub_exit -ne 0 ]; then
    sub_fetch_error=$(classify_error "$sub_exit" "$sub_response")
    all_repos_json=$(echo "$all_repos_json" | jq --arg key "$sub_owner_repo" --arg err "$sub_fetch_error" --arg plat "$sub_platform" '
      .[$key] = { platform: $plat, source: "unavailable", fetch_error: $err, fetched_at: null, open_count: 0, items: [] }')
    continue
  fi

  # 3.9: JSON normalize
  sub_normalized=$(echo "$sub_response" | jq '[.[] | { number: (.number // 0), title: (.title // ""), labels: ([.labels[]?.name] // []), url: (.html_url // .url // ""), body: (.body // "") }]')

  # 3.10: 启发式关联 (使用 **主 repo 的** openspec/changes/ 扫描, 见 D9)
  sub_items=$(apply_heuristic_linking "$sub_normalized")

  # 3.11: 写入 repo 级结果 (v1.1 修复 C2: 含 per-repo fetched_at)
  sub_fetched_at_iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  sub_open_count=$(echo "$sub_items" | jq 'length')
  all_repos_json=$(echo "$all_repos_json" | jq --arg key "$sub_owner_repo" --arg plat "$sub_platform" --arg fa "$sub_fetched_at_iso" --argjson items "$sub_items" --argjson oc "$sub_open_count" '
    .[$key] = {
      platform: $plat,
      source: "live",
      fetch_error: null,
      fetched_at: $fa,
      open_count: $oc,
      items: $items
    }')
done
```

### 步骤 4: 聚合视图构造

聚合扁平 `items[]` 视图 (每个 item 附带 `repo` 字段) + 全局 `open_count` + 跨 repo `label_summary`:

```bash
# 从 repos 构造 flat items 视图 (带 repo 字段标注来源)
# 只聚合 fetch_error == null 的 repo, 失败 repo 不污染聚合视图
flat_items=$(echo "$all_repos_json" | jq '[
  to_entries[]
  | select(.value.fetch_error == null)
  | .key as $repo_key
  | .value.items[]?
  | . + {repo: $repo_key}
]')

# open_count 是跨 repo 聚合总和
open_count=$(echo "$flat_items" | jq 'length')

# label_summary 聚合 (跨 repo, 见 D7)
label_summary=$(echo "$flat_items" | jq '[.[].labels[]?] | group_by(.) | map({(.[0]): length}) | add // {}')

# 聚合 fetched_at: 取所有 repo 中 **最早** 的时间戳 (保守估计, 表达"整体新鲜度下限")
# 若某 repo 为 cache 命中 (旧时间戳), 聚合视图反映这个下限
aggregate_fetched_at=$(echo "$all_repos_json" | jq -r '
  [to_entries[] | .value.fetched_at // empty] | sort | .[0] // ""
')
```

### 步骤 5: 缓存写回 (多 repo 结构 + v1.1 schema_version)

写入时必须携带 `schema_version` 标识 + 每 repo 独立 `fetched_at` (修复 R1 C1/C2) + `open_issues` 别名 (修复 R1 I1 向后兼容):

```json
{
  "schema_version": "1.1",
  "fetched_at": "2026-04-15T10:00:00Z",
  "ttl_seconds": 900,
  "scan_submodules": true,
  "platform": "forgejo",
  "open_count": 5,
  "items": [
    { "number": 16, "title": "...", "repo": "10CG/Aria", "labels": [], "url": "...", "linked_us": "US-020", "linked_openspec": null },
    { "number": 18, "title": "...", "repo": "10CG/aria-plugin", "labels": [], "url": "...", "linked_us": null, "linked_openspec": null }
  ],
  "open_issues": [],
  "__comment_open_issues": "v1.0 backward-compat alias — writer duplicates items[] to open_issues[]. Deprecated, remove in v2.0.",
  "label_summary": {},
  "repos": {
    "10CG/Aria": {
      "platform": "forgejo",
      "source": "live",
      "fetch_error": null,
      "fetched_at": "2026-04-15T10:00:00Z",
      "open_count": 2,
      "items": [...]
    },
    "10CG/aria-plugin": {
      "platform": "forgejo",
      "source": "live",
      "fetch_error": null,
      "fetched_at": "2026-04-15T10:00:00Z",
      "open_count": 2,
      "items": [...]
    },
    "10CG/aria-standards": {
      "platform": "forgejo",
      "source": "live",
      "fetch_error": null,
      "fetched_at": "2026-04-15T10:00:00Z",
      "open_count": 0,
      "items": []
    },
    "10CG/aria-orchestrator": {
      "platform": "forgejo",
      "source": "live",
      "fetch_error": null,
      "fetched_at": "2026-04-15T10:00:00Z",
      "open_count": 1,
      "items": [...]
    }
  }
}
```

**关键修复**:
- `schema_version: "1.1"` — reader 在步骤 4 用此字段决定 schema 兼容策略
- `repos[owner/repo].fetched_at` — 每 repo 独立时间戳, 支持部分 refresh (修复 C2)
- `items[]` 与 `open_issues[]` 同步双写 (修复 I1 向后兼容)

**原子写入** (复用主流程 `tmp + mv`):

```bash
tmp_path="${cache_path}.tmp.$$"
# v1.1 writer: 同步双写 items + open_issues, 携带 schema_version
jq -n \
  --arg schema "1.1" \
  --arg fetched_at "$aggregate_fetched_at" \
  --argjson scan_sub "$scan_submodules" \
  --arg plat "$platform" \
  --argjson oc "$open_count" \
  --argjson items "$flat_items" \
  --argjson repos "$all_repos_json" \
  --argjson label_sum "$label_summary" '
  {
    schema_version: $schema,
    fetched_at: $fetched_at,
    ttl_seconds: 900,
    scan_submodules: $scan_sub,
    platform: $plat,
    open_count: $oc,
    items: $items,
    open_issues: $items,        # v1.0 向后兼容别名 (writer 同步双写, reader 优先 items)
    label_summary: $label_sum,
    repos: $repos
  }' > "$tmp_path" && mv "$tmp_path" "$cache_path"
```

### Fail-soft 矩阵扩展

**v1.1 修复 R1 M3** — 失败 submodule 均记录 repos 条目 (而非 "不包含"), 保持 D10 "独立 fail-soft, 记录 fetch_error" 语义一致性:

| 场景 | repos 条目行为 | fetch_error 值 |
|------|-----------|------|
| `scan_submodules=false` | 仅主 repo, 不扫 submodule (v1.0 行为) | N/A |
| `.gitmodules` 不存在 | 仅主 repo 条目 | N/A |
| `.gitmodules` 存在但为空 | 仅主 repo 条目 | N/A |
| 某 submodule 未初始化 (`.git` 目录缺失) | **用路径作为临时 key 记录条目** | `"submodule_not_initialized"` |
| 某 submodule 的 `origin` remote 缺失 | **用路径作为临时 key 记录条目** | `"no_origin_remote"` |
| 某 submodule 的 owner/repo 解析失败 (D11) | **用路径作为临时 key 记录条目** | `"parse_error"` |
| 某 submodule 的 platform 检测失败 | 记录条目 (sub_owner_repo 已知) | `"platform_unknown"` |
| 某 submodule 的 API 调用失败 | 记录条目 | 具体枚举 (timeout / rate_limited / auth_failed / ...) |
| 某 submodule 缓存命中 | 记录条目 (source: cache) | null |
| 整阶段 20s 超时 | 已完成 repos 保留, 未完成 repos 不出现在 `repos` 中, 聚合视图含 `warning: "stage_timeout"` | 部分 |

**聚合视图的失败过滤**: 步骤 4 的 `flat_items` 聚合只包含 `fetch_error == null` 的 repo, 失败 repo 的空 `items: []` 不污染聚合 `items[]`, 但**分组视图 `repos{}`** 保留全部记录 (含失败), 让消费者可以看到哪个 repo 失败了以及原因。

### 推荐规则 `open_blocker_issues` 聚合

v1.1.0+ 该规则评估逻辑:

```bash
# 聚合所有 repo 的 items, 检查 blocker/critical label
blocker_count=$(jq -r '.items[] | select(.labels | any(. == "blocker" or . == "critical")) | .number' "$issue_status" | wc -l)

if [ "$blocker_count" -gt 0 ]; then
  # 降级推荐 + 提示 (跨 repo)
  blocker_repos=$(jq -r '.items[] | select(.labels | any(. == "blocker" or . == "critical")) | .repo' "$issue_status" | sort -u)
  echo "降级: 检测到 $blocker_count 个 blocker issue, 分布在 $(echo "$blocker_repos" | wc -l) 个 repo"
fi
```

---

## 安全边界

Phase 1.13 严格只读，明确不做以下事项：

- **不管理 API token**: 完全依赖已配置的 `forgejo` / `gh` CLI wrapper，skill 内部无 token 存储或传递
- **不扫描 issue comments**: 首版仅扫描 `title` 和 `body`，避免大量 API 请求和噪音
- **默认不递归子模块 issues**: 默认仅扫描主仓库 (`git remote get-url origin`), 避免 vendored submodule 噪音污染。**v1.1.0+** 新增 opt-in `state_scanner.issue_scan.scan_submodules: true` 支持 meta-repo 模式递归扫描, 详见下方 §submodule 扫描流程 章节
- **不做写操作**: 不创建、评论、关闭 issue (这是 `forgejo-sync` skill 的职责)
- **不扫描 PR**: PR 感知为独立功能，需单独 Spec
- **不支持 GitLab**: 首版仅 Forgejo + GitHub，GitLab 预留 v2 扩展接口

---

**创建**: 2026-04-09
**更新**: 2026-04-15 (v1.1.0 — 新增 §submodule 扫描流程)
**版本**: 1.1.0
**关联 Spec**:
- v1.0.0 `state-scanner-issue-awareness` (2026-04-09 归档)
- v1.1.0 `state-scanner-submodule-issue-scan` (2026-04-15 Draft)
**目标版本**: aria-plugin v2.10.0 / v1.16.0
