---
name: aria-report
description: |
  向 Aria 维护团队报告 Bug 或提交功能建议。自动收集环境信息，
  自动路由到 Forgejo（内部用户）或 GitHub（外部用户）。

  使用场景："报告 bug"、"report an issue"、"提交功能建议"、
  "aria 有个问题想反馈"、"feature request"、"提 issue"、
  "反馈问题"、"report bug to aria"
argument-hint: "[bug|feature|question]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Bash, Read, AskUserQuestion
dependencies:
  cli:
    required: false
    note: "CLI version is auto-detected for context, not required"
---

# Aria Issue 报告 (aria-report)

**版本**: 1.0.0 | **优先级**: P1

帮助用户向 Aria 维护团队报告 Bug、提交功能建议或提问。自动收集环境信息并路由到正确的仓库。

**自动路由逻辑（核心差异点）：**

```
forgejo CLI 可用 + FORGEJO_TOKEN? → Forgejo (内部用户优先)
GITHUB_TOKEN / GH_TOKEN?         → GitHub API
无 token                         → GitHub Pre-filled URL
```

**目标仓库：**

- Forgejo: `https://forgejo.10cg.pub/10CG/Aria`（内部，通过 `forgejo` CLI wrapper）
- GitHub: `https://github.com/10CG/aria-plugin`（外部，公开）

---

## 执行流程

### Step 1: 分类 Issue 类型

解析用户调用参数：

```
/aria:report bug      → Bug Report
/aria:report feature  → Feature Request
/aria:report question → Question
/aria:report          → 从用户的自然语言推断，或用 AskUserQuestion 询问
```

标签映射：bug → `bug` | feature → `enhancement` | question → `question`

### Step 2: 自动收集环境信息

```bash
PLUGIN_VERSION=$(cat "${CLAUDE_PLUGIN_ROOT}/VERSION" 2>/dev/null | grep -m1 '^[0-9]' || echo "unknown")
SKILLS_COUNT=$(find "${CLAUDE_PLUGIN_ROOT}/skills" -name "SKILL.md" 2>/dev/null | wc -l | tr -d ' ')
OS_INFO=$(uname -s -m 2>/dev/null || echo "unknown")
HAS_CONFIG=$( [ -f ".aria/config.json" ] && echo "yes" || echo "no" )
```

**安全边界 — 绝不自动收集：** config 文件内容、环境变量、SSH 配置、git 历史、源代码。

### Step 3: 交互收集用户输入

用 AskUserQuestion 收集。如果用户在初始消息中已提供足够信息，不要重复询问已知部分。

**Bug Report:** 标题 / 复现步骤 + 预期 vs 实际 / 错误输出（可选）
**Feature Request:** 标题 / 使用场景 / 建议方案（可选）
**Question:** 标题 / 详细描述

### Step 4: 组合 Issue Body

**Bug Report 模板：**

```markdown
## Bug Report

**描述**: {user_description}

**复现步骤**:
{steps}

**预期行为**: {expected}
**实际行为**: {actual}

**错误输出**:
```
{error_output}
```

## 环境信息
- Aria Plugin: {plugin_version}
- Skills: {skills_count}
- OS: {os_info}
- 项目配置 (.aria/config.json): {has_config}

---
*由 aria-report 自动生成*
```

**Feature Request 模板：**

```markdown
## Feature Request

**描述**: {user_description}

**使用场景**: {use_case}

**建议方案**: {proposed_solution}

## 环境信息
- Aria Plugin: {plugin_version}
- Skills: {skills_count}

---
*由 aria-report 自动生成*
```

### Step 5: 隐私审查（必须）

提交前，**必须**展示完整 Issue 内容给用户确认：

```
即将提交以下 Issue 到 {target_repo}:

---
标题: {title}
{full_body}
---
标签: {label} | 目标: {Forgejo 或 GitHub}

此内容将公开可见。请确认：
  1. 提交  2. 编辑后提交  3. 取消
```

使用 AskUserQuestion 获取确认。用户选择编辑时，允许修改任何内容。

### Step 6: 提交路由

```bash
ROUTE=""
# Priority 1: Forgejo (内部用户)
if command -v forgejo &>/dev/null && [ -n "${FORGEJO_TOKEN:-}" ]; then
  ROUTE="forgejo"
fi
# Priority 2: GitHub API
if [ -z "$ROUTE" ] && [ -n "${GITHUB_TOKEN:-${GH_TOKEN:-}}" ]; then
  ROUTE="github_api"
fi
# Priority 3: GitHub Pre-filled URL
if [ -z "$ROUTE" ]; then
  ROUTE="github_url"
fi
```

**Forgejo 提交：**

```bash
forgejo POST /repos/10CG/Aria/issues -d "{
  \"title\": \"${TITLE}\",
  \"body\": \"${BODY}\"
}"
```

**GitHub API 提交：**

```bash
TOKEN="${GITHUB_TOKEN:-$GH_TOKEN}"
curl -s -X POST \
  "https://api.github.com/repos/10CG/aria-plugin/issues" \
  -H "Authorization: token ${TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  -d "{\"title\":\"${TITLE}\",\"body\":\"${BODY}\",\"labels\":[\"${LABEL}\"]}"
```

**GitHub Pre-filled URL（无 token 时）：**

```bash
ENCODED_TITLE=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.stdin.read()))" <<< "$TITLE")
ENCODED_BODY=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.stdin.read()))" <<< "$BODY")
URL="https://github.com/10CG/aria-plugin/issues/new?title=${ENCODED_TITLE}&body=${ENCODED_BODY}&labels=${LABEL}"

if [ ${#URL} -gt 7800 ]; then
  echo "Issue body too long for URL. Please paste manually:"
  echo "$BODY"
  echo "Open: https://github.com/10CG/aria-plugin/issues/new"
else
  echo "Open this URL to submit the issue:"
  echo "$URL"
fi
```

### Step 7: 输出结果

**API 提交成功：**

```
Issue 已提交
  URL:   {issue_url}
  类型:  {Bug Report / Feature Request / Question}
  目标:  {Forgejo / GitHub}
  标题:  {title}
Aria 维护团队会尽快查看。
```

**Pre-filled URL（无 token）：**

```
Issue 已准备好
请在浏览器中打开以下链接提交:
  {pre_filled_url}
提示: 设置 GITHUB_TOKEN 可直接从终端提交。
```

**提交失败：**

```
提交失败: {error}
Issue 内容已保存，请手动提交:
  https://github.com/10CG/aria-plugin/issues/new
{issue_body_for_paste}
```

---

## 与其他 Skill 的集成

- `state-scanner` 检测到异常状态时，建议用户执行 `/aria:report bug`
- `agent-team-audit` 发现 Aria 插件自身的问题时，建议用户执行 `/aria:report`
- 用户说 "aria 有问题" 时，先判断意图：
  - 需要本地诊断 → 引导到 `/aria:state-scanner`
  - 需要向维护者反馈 → 使用 `/aria:report`
- Issue 提交后返回的 URL 可供用户在后续对话中引用

---

## 限制和注意事项

- Forgejo 提交需要 `forgejo` CLI + `FORGEJO_TOKEN` + Cloudflare Access 凭据
- GitHub Pre-filled URL 在无头环境（SSH、Docker）中无法自动打开浏览器，会打印 URL
- URL 长度超过 ~7800 字符时降级为打印 markdown 供手动粘贴
- 不支持附件/截图上传（GitHub API 限制）
- 所有收集的信息仅用于 Issue 内容，不会发送到第三方服务

---

**Skill 版本**: 1.0.0
**最后更新**: 2026-03-27
**维护者**: 10CG Infrastructure Team
