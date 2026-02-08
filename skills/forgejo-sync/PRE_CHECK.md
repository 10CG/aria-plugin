# Forgejo API 调用前置检查 (Unified Pre-Check)

> **版本**: 1.5.0 | **用途**: 所有 Forgejo API 调用的强制前置检查
> **重要性**: ⚠️ **不可协商规则** - AI 在调用任何 Forgejo API 前必须执行此检查

---

## 核心原则

```yaml
Forgejo_API_Call_Pre_Check:
  执行时机: API 调用之前 (BEFORE, not after)
  适用范围: 所有 Forgejo API 调用
  不可跳过: true
  不可协商: true
```

---

## 执行流程 (AI 必须按顺序执行)

```yaml
Step_1_Config_Check:
  动作: 读取配置
  优先级:
    1. CLAUDE.local.md (最高优先级)
    2. .claude/skills/forgejo-sync/CONFIG.md
    3. 默认: false

  检查内容: forgejo.cloudflare_access.enabled

Step_2_Mode_Decision:
  enabled = true:
    → 使用 Cloudflare Access 模式
    → 必须添加头部:
      - CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}
      - CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}

  enabled = false 或未设置:
    → 使用标准模式
    → 仅添加标准 Authorization 头部

Step_3_Execute_API_Call:
  使用选择的模式执行 API 调用

Step_4_Error_Detection:
  检查 HTTP 状态码和响应内容

  如果 status == 403 或 响应包含:
    - "cloudflare"
    - "challenge"
    - "access denied"

    → 自动提示用户配置 Cloudflare Access
```

---

## 命令模板 (不可修改)

### 标准模式 (enabled = false)

```bash
curl "${API_ENDPOINT}" \
  -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"data": "value"}'
```

### Cloudflare Access 模式 (enabled = true)

```bash
curl "${API_ENDPOINT}" \
  -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}" \
  -H "CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}" \
  -H "Content-Type: application/json" \
  -d '{"data": "value"}'
```

---

## 错误检测与自动提示

### 检测条件

```yaml
Error_Detection_Rules:
  条件1: HTTP 状态码 == 403
  条件2: 响应体包含 "cloudflare"
  条件3: 响应体包含 "challenge"
  条件4: 响应体包含 "access denied"

  满足任一条件 → 触发自动提示
```

### 自动提示模板

```
⚠️ 检测到 Cloudflare Access 保护

Forgejo API 调用返回 403，响应中包含 Cloudflare challenge。

请在 CLAUDE.local.md 中添加以下配置：

```yaml
forgejo:
  url: "你的 Forgejo URL"
  api_token: "${FORGEJO_TOKEN}"
  repo: "owner/repo"

  cloudflare_access:
    enabled: true
    client_id_env: "CF_ACCESS_CLIENT_ID"
    client_secret_env: "CF_ACCESS_CLIENT_SECRET"
```

并设置环境变量：

# Linux/macOS
export CF_ACCESS_CLIENT_ID="your-client-id"
export CF_ACCESS_CLIENT_SECRET="your-service-token"

# Windows PowerShell
$env:CF_ACCESS_CLIENT_ID = "your-client-id"
$env:CF_ACCESS_CLIENT_SECRET = "your-service-token"
```

---

## 配置示例

### 完整配置示例 (CLAUDE.local.md)

```yaml
forgejo:
  # Forgejo 服务器配置
  url: "https://forgejo.example.com"
  api_token: "${FORGEJO_TOKEN}"
  repo: "owner/repo"

  # Cloudflare Access 配置
  cloudflare_access:
    enabled: true
    client_id_env: "CF_ACCESS_CLIENT_ID"
    client_secret_env: "CF_ACCESS_CLIENT_SECRET"

  # 其他配置
  default_labels: ["user-story"]
```

### 环境变量设置

```bash
# Linux/macOS - 添加到 ~/.bashrc 或 ~/.zshrc
export CF_ACCESS_CLIENT_ID="your-client-id-here"
export CF_ACCESS_CLIENT_SECRET="your-service-token-here"
export FORGEJO_TOKEN="your-api-token-here"

# Windows PowerShell - 添加到 $PROFILE
$env:CF_ACCESS_CLIENT_ID = "your-client-id-here"
$env:CF_ACCESS_CLIENT_SECRET = "your-service-token-here"
$env:FORGEJO_TOKEN = "your-api-token-here"
```

---

## 不可协商规则 (Non-Negotiable Rules)

| 规则 | 说明 | 违规后果 |
|------|------|----------|
| **先检查后调用** | API 调用前必须先检查配置 | 调用失败，浪费时间 |
| **头部完整性** | CF 模式必须包含两个头部 | 认证失败 |
| **错误必检测** | API 调用后必须检查错误 | 无法自动提示用户 |
| **提示必输出** | 检测到 CF 错误必须输出模板 | 用户无法修复 |

---

## 引用此文档的 Skills

以下 Skills 必须在执行 Forgejo API 调用时引用此文档：

- `branch-manager` - C.2.3 创建 PR 步骤
- `forgejo-sync` - 所有 Forgejo API 调用
- `phase-c-integrator` - 通过 branch-manager 间接使用

---

## 变更历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.5.0 | 2026-02-08 | 统一前置检查规范，作为所有 Forgejo API 调用的前置条件 |
| 1.4.1 | 2026-02-07 | 初始版本 (forgejo-sync/API_CALL_PATTERN.md) |

---

**最后更新**: 2026-02-08
**适用版本**: Aria v1.5.0+
