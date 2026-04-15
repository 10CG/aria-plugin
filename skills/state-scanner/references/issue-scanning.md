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

```yaml
issue_status:
  fetched_at: "2026-04-09T10:23:00Z"   # ISO 8601 UTC
  source: cache | live | unavailable    # 数据来源
  fetch_error: null                     # 见 fetch_error 枚举表 (10 个值)
  warning: null                         # 可选警告，如 "stale_cache_api_failed"
  platform: forgejo | github | null     # 检测到的平台
  open_count: 3                         # open issues 总数
  items:
    - number: 6
      title: "state-scanner: add issue scan and sync detection"
      labels:
        - "enhancement"
        - "skill"
      url: "https://forgejo.10cg.pub/10CG/Aria/issues/6"
      linked_openspec: "state-scanner-issue-awareness"  # 启发式，null 表示无匹配
      linked_us: null                                    # 启发式，null 表示无匹配
      heuristic: true                                    # 标注为启发式结果
  label_summary:                        # 按 label 聚合统计
    bug: 1
    enhancement: 2
```

**字段规则**:
- 所有字符串字段缺失时降级为空字符串 `""`，不使用 `null`
- `labels` 缺失时降级为空数组 `[]`
- `fetch_error` 为 `null` 表示成功，否则为 10 个枚举值之一
- `source: unavailable` 时 `items` 为空数组，`open_count` 为 0

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

```bash
cache_path=$(jq -r '.state_scanner.issue_scan.cache_path // ".aria/cache/issues.json"' .aria/config.json)
ttl=$(jq -r '.state_scanner.issue_scan.cache_ttl_seconds // 900' .aria/config.json)

if [ -f "$cache_path" ]; then
  fetched_at=$(jq -r '.fetched_at' "$cache_path")
  cache_ts=$(date -d "$fetched_at" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$fetched_at" +%s)
  now_ts=$(date +%s)
  age=$((now_ts - cache_ts))
  if [ "$age" -lt "$ttl" ]; then
    # 缓存命中，source: cache
    source="cache"
    issues_json=$(jq '.open_issues' "$cache_path")
    # 跳转至步骤 7
  fi
fi
```

缓存命中时跳过 API 调用，直接进入启发式关联步骤。

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

| 层级 | 超时值 (v1.0) | 超时值 (v1.1+) | 实现 |
|------|--------------|---------------|------|
| 整阶段 (Phase 1.13) | 12s | **20s** (`scan_submodules=true` 时需求增长, 串行扫描预算) | `timeout 20 bash -c '...'` 或 SECONDS 早退 |
| 单次 API 调用 | 5s | 5s (不变) | `timeout 5 forgejo GET ...` / `timeout 5 gh issue list ...` |

**12s → 20s 依据** (v1.1 扩展): `scan_submodules=true` 场景下, 最坏情况是主 repo + N submodule 全部缓存 miss + API 响应接近 5s 上限。以 Aria 为例: 1 主 + 3 submodule = 4 × 5s = 20s 需求上限。总预算增长与串行扫描的 repo 数线性相关, 若项目 submodule 数 > 3, 应按公式 `(N+1) × api_timeout_seconds` 自行调整 `stage_timeout_seconds`。

**向后兼容**: 当 `scan_submodules=false` 时, 仅扫描主 repo, 实际消耗通常 < 6s, 20s 预算对主 repo only 场景**完全不增加**延迟 (早退即可)。**原 D9 的 12s 设计对主 repo only 仍然有效**, 20s 只是"预算上限上调", 不是"实际耗时上调"。

超时触发时:
- 若缓存存在 (即使过期) → 沿用旧缓存 + `fetch_error: "timeout"` + `warning: "stale_cache_api_failed"`
- 若无缓存 → `source: unavailable`, `fetch_error: "timeout"`
- **v1.1**: submodule 部分超时时, 已完成扫描的 repo 结果保留, 未完成的 repo 记录 `fetch_error: "timeout"`, 聚合视图可能部分可用

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

**首选方案** (POSIX, 跨平台):

```bash
if [ ! -f .gitmodules ]; then
  # 无 submodule, 不报错, 主流程继续
  submodule_paths=""
else
  # 从 .gitmodules 提取所有 path 字段
  # 兼容路径含空格 (用 null-delimited 或 quote-aware 解析)
  submodule_paths=$(git config --file .gitmodules --get-regexp '^submodule\..*\.path$' 2>/dev/null \
    | awk '{$1=""; sub(/^ /,""); print}')
fi
```

**备选方案** (纯 grep, 若 `git config --file` 不可用):

```bash
submodule_paths=$(awk -F= '/^\s*path\s*=/ {gsub(/^[ \t]+|[ \t]+$/,"",$2); print $2}' .gitmodules)
```

**输出**: 每行一个 submodule 路径 (如 `aria`, `standards`, `aria-orchestrator`)。

### 步骤 3: 逐 submodule 扫描

```bash
for submodule_path in $submodule_paths; do
  # 3.1: 验证 submodule 已初始化 (目录存在且含 .git 引用)
  if [ ! -d "$submodule_path" ]; then
    # 未初始化, 记录错误但不阻塞
    echo "[warning] submodule $submodule_path not initialized, skipping"
    continue
  fi

  # 3.2: 读取 submodule 的 origin remote
  sub_remote=$(git -C "$submodule_path" remote get-url origin 2>/dev/null)
  if [ -z "$sub_remote" ]; then
    echo "[warning] submodule $submodule_path has no origin, skipping"
    continue
  fi

  # 3.3: 复用主流程的 owner/repo 提取逻辑
  stripped=$(echo "$sub_remote" | sed -E 's|^[a-z]+://||; s|^[^@]+@||; s|^[^:/]+[:/]||')
  sub_owner_repo=$(echo "$stripped" | sed -E 's|\.git([?#/].*)?$||; s|\.git$||; s|/$||')
  if ! echo "$sub_owner_repo" | grep -qE '^[^/]+/[^/]+$'; then
    # D11: 解析失败 → 跳过该 submodule, 不阻断整个 Phase 1.13
    continue
  fi

  # 3.4: 独立 platform 检测 (复用 detect_platform 函数, 基于 submodule 的 remote URL)
  sub_platform=$(detect_platform_for_url "$sub_remote")
  if [ "$sub_platform" = "platform_unknown" ]; then
    # 独立 fail-soft: 该 submodule 记录 platform_unknown, 继续下一个
    record_repo_error "$sub_owner_repo" "platform_unknown"
    continue
  fi

  # 3.5: CLI 可用性 (主流程已验证, 此处复用)

  # 3.6: 缓存命中检查 (repo 级粒度)
  cached=$(jq -r --arg key "$sub_owner_repo" '.repos[$key] // empty' "$cache_path" 2>/dev/null)
  cached_fetched_at=$(echo "$cached" | jq -r '.fetched_at // empty' 2>/dev/null || echo "")
  if [ -n "$cached_fetched_at" ]; then
    cached_ts=$(date -d "$cached_fetched_at" +%s 2>/dev/null)
    if [ -n "$cached_ts" ] && [ $((now_ts - cached_ts)) -lt "$ttl" ]; then
      # 缓存命中, 跳过 API 调用
      sub_items=$(echo "$cached" | jq '.items')
      record_repo_cached "$sub_owner_repo" "$sub_items"
      continue
    fi
  fi

  # 3.7: API 调用 (5s 超时)
  if [ "$sub_platform" = "forgejo" ]; then
    sub_response=$(timeout 5 forgejo GET "/repos/${sub_owner_repo}/issues?state=open&limit=${limit}" 2>&1)
    sub_exit=$?
  elif [ "$sub_platform" = "github" ]; then
    sub_response=$(cd "$submodule_path" && timeout 5 gh issue list --state open --json number,title,labels,url,body --limit "$limit" 2>&1)
    sub_exit=$?
  fi

  # 3.8: 错误分类 (复用 10 个 fetch_error 枚举, D12)
  if [ $sub_exit -ne 0 ]; then
    sub_fetch_error=$(classify_error "$sub_exit" "$sub_response")
    record_repo_error "$sub_owner_repo" "$sub_fetch_error"
    continue
  fi

  # 3.9: JSON normalize (复用主流程)
  sub_normalized=$(echo "$sub_response" | jq '[.[] | { number: (.number // 0), title: (.title // ""), labels: ([.labels[]?.name] // []), url: (.html_url // .url // ""), body: (.body // "") }]')

  # 3.10: 启发式关联 (注: 使用 **主 repo 的** openspec/changes/ 扫描, 见 D9)
  sub_items=$(apply_heuristic_linking "$sub_normalized")

  # 3.11: 写入 repo 级结果
  record_repo_success "$sub_owner_repo" "$sub_platform" "$sub_items"
done
```

### 步骤 4: 聚合视图构造

```bash
# 从 repos 构造 flat items 视图 (带 repo 字段标注来源)
flat_items=$(jq -n --argjson repos "$all_repos_json" '[
  $repos | to_entries[] | .value.items[]? + {repo: .key}
]')

# open_count 是跨 repo 总和
open_count=$(echo "$flat_items" | jq 'length')

# label_summary 聚合
label_summary=$(echo "$flat_items" | jq '[.[].labels[]?] | group_by(.) | map({(.[0]): length}) | add // {}')
```

### 步骤 5: 缓存写回 (多 repo 结构)

```json
{
  "fetched_at": "2026-04-15T10:00:00Z",
  "ttl_seconds": 900,
  "scan_submodules": true,
  "repos": {
    "10CG/Aria": {
      "platform": "forgejo",
      "source": "live",
      "fetch_error": null,
      "open_count": 2,
      "items": [...]
    },
    "10CG/aria-plugin": {
      "platform": "forgejo",
      "source": "live",
      "fetch_error": null,
      "open_count": 2,
      "items": [...]
    },
    "10CG/aria-standards": {
      "platform": "forgejo",
      "source": "live",
      "fetch_error": null,
      "open_count": 0,
      "items": []
    },
    "10CG/aria-orchestrator": {
      "platform": "forgejo",
      "source": "live",
      "fetch_error": null,
      "open_count": 1,
      "items": [...]
    }
  }
}
```

**原子写入** (复用主流程 `tmp + mv`):

```bash
tmp_path="${cache_path}.tmp.$$"
jq -n ... > "$tmp_path" && mv "$tmp_path" "$cache_path"
```

### Fail-soft 矩阵扩展

| 场景 | 行为 |
|------|------|
| `scan_submodules=false` | v1.0 行为, 仅扫主 repo |
| `.gitmodules` 不存在 | 仅扫主 repo, 不报错 |
| `.gitmodules` 存在但为空 | 仅扫主 repo, 不报错 |
| 某 submodule 未初始化 (`.git` 目录缺失) | 跳过该 submodule, `issue_status.repos` 不包含该条目, warning 记录 |
| 某 submodule 的 `origin` remote 缺失 | 跳过该 submodule, warning 记录 |
| 某 submodule 的 owner/repo 解析失败 (D11) | 跳过该 submodule |
| 某 submodule 的 platform 检测失败 | 记录 `repos[owner/repo].fetch_error: "platform_unknown"`, 继续下一个 |
| 某 submodule 的 API 调用失败 | 记录 `repos[owner/repo].fetch_error: <具体枚举>`, 继续下一个 |
| 某 submodule 缓存命中 | 跳过 API 调用, 读缓存 |
| 整阶段 20s 超时 | 已完成的 repos 保留, 未完成标记 timeout, 聚合视图部分可用 |

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
