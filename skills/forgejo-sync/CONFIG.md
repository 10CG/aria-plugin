# Forgejo Sync Configuration

> **Note**: Copy this to `CLAUDE.local.md` or create a local CONFIG.md with your settings.

---

## Required Configuration

```yaml
forgejo:
  # Forgejo instance URL
  url: "https://forgejo.example.com"

  # API token (use environment variable for security)
  # Create token at: {forgejo_url}/user/settings/applications
  api_token: "${FORGEJO_TOKEN}"

  # Repository in owner/repo format
  repo: "owner/repo"
```

---

## Cloudflare Access Support

> **AI 读取规则**: 当调用 Forgejo API 前，AI **必须先检查**本配置中的 `cloudflare_access.enabled` 状态。如果为 `true`，所有 API 调用必须添加 Cloudflare Access 头部。

### What is Cloudflare Access?

Cloudflare Access 保护服务器需要额外的认证头部。如果你的 Forgejo 服务器返回 403 错误或 Cloudflare challenge 页面，说明启用了此保护。

### 配置检测规则 (AI 必须遵循)

```yaml
# AI 执行前检查流程
1. 读取 forgejo.cloudflare_access.enabled
2. 如果 enabled == true:
   - 所有 API 调用添加 CF-Access-Client-Id 头部
   - 所有 API 调用添加 CF-Access-Client-Secret 头部
3. 如果 API 调用返回 403/Cloudflare 错误:
   - 自动提示用户启用 cloudflare_access
```

### Configuration

```yaml
forgejo:
  url: "https://forgejo.example.com"
  api_token: "${FORGEJO_TOKEN}"
  repo: "owner/repo"

  # Cloudflare Access (AI 会自动读取此配置)
  cloudflare_access:
    # 是否启用 Cloudflare Access
    enabled: true

    # Client ID 环境变量名
    client_id_env: "CF_ACCESS_CLIENT_ID"

    # Client Secret (Service Token) 环境变量名
    client_secret_env: "CF_ACCESS_CLIENT_SECRET"
```

### Environment Variables

```bash
# Cloudflare Access Service Token
export CF_ACCESS_CLIENT_ID="your-client-id-here"
export CF_ACCESS_CLIENT_SECRET="your-service-token-here"

# Forgejo API Token
export FORGEJO_TOKEN="your-api-token-here"
```

### API Call Templates

**Standard Mode** (cloudflare_access.enabled = false):
```bash
curl -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "Content-Type: application/json" \
  "${FORGEJO_API_URL}/repos/owner/repo/issues"
```

**Cloudflare Access Mode** (cloudflare_access.enabled = true):
```bash
curl \
  -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}" \
  -H "CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}" \
  -H "Content-Type: application/json" \
  "${FORGEJO_API_URL}/repos/owner/repo/issues"
```

### Error Detection & Auto-Prompt

**AI must detect** these conditions:
- HTTP status code is 403
- Response contains: "cloudflare" OR "challenge" OR "access denied"

**Auto-prompt template**:
```
⚠️ 检测到 Cloudflare Access 保护

API 调用返回 403，响应包含 Cloudflare challenge。
请在 CLAUDE.local.md 中添加配置：

forgejo:
  cloudflare_access:
    enabled: true
    client_id_env: "CF_ACCESS_CLIENT_ID"
    client_secret_env: "CF_ACCESS_CLIENT_SECRET"

并设置环境变量：
export CF_ACCESS_CLIENT_ID="your-client-id"
export CF_ACCESS_CLIENT_SECRET="your-service-token"
```

### Complete Example with Cloudflare Access

```yaml
# In CLAUDE.local.md
forgejo:
  url: "https://forgejo.example.com"
  api_token: "${FORGEJO_TOKEN}"
  repo: "owner/repo"

  # Cloudflare Access
  cloudflare_access:
    enabled: true
    client_id_env: "CF_ACCESS_CLIENT_ID"
    client_secret_env: "CF_ACCESS_CLIENT_SECRET"

  default_labels: ["user-story"]
  wiki:
    enabled: true
    page_prefix: "PRD-"
```

---

## Optional Configuration

```yaml
forgejo:
  # Default labels for new issues
  default_labels: ["user-story"]

  # Automatically create milestones if they don't exist
  auto_create_milestone: true

  # Wiki publishing settings
  wiki:
    # Enable PRD to Wiki publishing
    enabled: true

    # Prefix for wiki page names
    page_prefix: "PRD-"

    # Generate index page listing all PRDs
    generate_index: true

    # Auto-publish when PRD status changes to approved
    auto_publish_on_approve: false

  # Sync behavior
  sync:
    # Sync on git commit (requires hook)
    on_commit: false

    # Rate limit delay between API calls (ms)
    rate_limit_delay: 100
```

---

## Environment Variables

Set the following environment variable:

```bash
# Linux/macOS
export FORGEJO_TOKEN="your-api-token-here"

# Windows (PowerShell)
$env:FORGEJO_TOKEN = "your-api-token-here"

# Windows (CMD)
set FORGEJO_TOKEN=your-api-token-here
```

---

## Example Complete Configuration

```yaml
# In CLAUDE.local.md
forgejo:
  url: "https://git.mycompany.com"
  api_token: "${FORGEJO_TOKEN}"
  repo: "myorg/todo-app"
  default_labels: ["user-story", "todo-app"]
  auto_create_milestone: true
  wiki:
    enabled: true
    page_prefix: "PRD-"
    generate_index: true
```

---

## Troubleshooting

### Token Permission Issues

Ensure your API token has the following permissions:
- `write:issue` - Create and update issues
- `write:repository` - Access to wiki (if using wiki sync)

### Rate Limiting

If you encounter rate limit errors, increase `rate_limit_delay`:

```yaml
forgejo:
  sync:
    rate_limit_delay: 500  # 500ms between calls
```

### Connection Issues

Test API access:

```bash
curl -H "Authorization: token ${FORGEJO_TOKEN}" \
  https://forgejo.example.com/api/v1/user
```
