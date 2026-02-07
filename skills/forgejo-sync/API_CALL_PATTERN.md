# Forgejo API 调用标准模式

> **版本**: 1.0.0 | **用途**: AI 统一调用规范
> **重要**: 此文档定义 AI 调用 Forgejo API 时必须遵循的模式

---

## AI 必须遵循的模式

### 模式选择流程图

```
开始 Forgejo API 调用
    │
    ▼
读取配置: forgejo.cloudflare_access.enabled
    │
    ├─→ enabled = true
    │       │
    │       ▼
    │   使用 Cloudflare Access 模式
    │   (添加 CF-Access-Client-Id/Secret 头部)
    │
    └─→ enabled = false / 未设置
            │
            ▼
        使用标准模式
            │
            ▼
        执行 API 调用
            │
            ▼
        检查响应状态
            │
            ├─→ 成功 (200/201) → 结束
            │
            └─→ 失败 (403/401)
                    │
                    ▼
                检测响应内容
                    │
                    ├─→ 包含 "cloudflare" / "challenge"
                    │       │
                    │       ▼
                    │   自动提示配置 Cloudflare Access
                    │
                    └─→ 其他错误
                            │
                            ▼
                        报告原始错误
```

---

## 命令模板

### 标准模式 (cloudflare_access 未启用)

```bash
curl \
  -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "Content-Type: application/json" \
  "${API_ENDPOINT}"
```

### Cloudflare Access 模式 (cloudflare_access.enabled = true)

```bash
curl \
  -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}" \
  -H "CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}" \
  -H "Content-Type: application/json" \
  "${API_ENDPOINT}"
```

---

## 配置读取规则

### AI 配置读取流程

```yaml
Read_Config:
  1. 读取 CLAUDE.local.md
  2. 查找 forgejo.cloudflare_access.enabled
  3. 如果不存在，读取 .claude/skills/forgejo-sync/CONFIG.md
  4. 确定最终的 enabled 状态

Config_Priority:
  - CLAUDE.local.md (最高优先级)
  - 项目级 CONFIG.md
  - 默认值: false
```

---

## 错误检测规则

### 必须检测的错误条件

```yaml
Error_Detection:
  http_status_403:
    trigger: status_code == 403
    action: 检查响应内容

  response_contains:
    - "cloudflare"
    - "challenge"
    - "access denied"
    - "403 Forbidden"

  cloudflare_detected:
    action: 输出配置提示模板
```

---

## 自动提示模板

### 检测到 Cloudflare Access 时的输出

```
⚠️ 检测到 Cloudflare Access 保护

Forgejo API 调用返回 403，响应中包含 Cloudflare challenge。
请在 CLAUDE.local.md 中添加以下配置：

forgejo:
  url: "你的 Forgejo URL"
  api_token: "${FORGEJO_TOKEN}"
  repo: "owner/repo"

  cloudflare_access:
    enabled: true
    client_id_env: "CF_ACCESS_CLIENT_ID"
    client_secret_env: "CF_ACCESS_CLIENT_SECRET"

并设置环境变量：

# Linux/macOS
export CF_ACCESS_CLIENT_ID="your-client-id"
export CF_ACCESS_CLIENT_SECRET="your-service-token"

# Windows PowerShell
$env:CF_ACCESS_CLIENT_ID = "your-client-id"
$env:CF_ACCESS_CLIENT_SECRET = "your-service-token"
```

---

## 常见 API 端点示例

### 创建 Issue

**标准模式**:
```bash
curl -X POST "${FORGEJO_API}/repos/owner/repo/issues" \
  -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "[US-001] Feature Title",
    "body": "Issue content",
    "labels": ["user-story", "ready"]
  }'
```

**Cloudflare Access 模式**:
```bash
curl -X POST "${FORGEJO_API}/repos/owner/repo/issues" \
  -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}" \
  -H "CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "[US-001] Feature Title",
    "body": "Issue content",
    "labels": ["user-story", "ready"]
  }'
```

### 创建 PR

**标准模式**:
```bash
curl -X POST "${FORGEJO_API}/repos/owner/repo/pulls" \
  -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "feat: add feature",
    "body": "PR description",
    "head": "feature/branch",
    "base": "main"
  }'
```

**Cloudflare Access 模式**:
```bash
curl -X POST "${FORGEJO_API}/repos/owner/repo/pulls" \
  -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}" \
  -H "CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "feat: add feature",
    "body": "PR description",
    "head": "feature/branch",
    "base": "main"
  }'
```

### 获取 Issue

**标准模式**:
```bash
curl -H "Authorization: token ${FORGEJO_TOKEN}" \
  "${FORGEJO_API}/repos/owner/repo/issues/123"
```

**Cloudflare Access 模式**:
```bash
curl \
  -H "Authorization: token ${FORGEJO_TOKEN}" \
  -H "CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}" \
  -H "CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}" \
  "${FORGEJO_API}/repos/owner/repo/issues/123"
```

---

## 不可协商规则 (Non-Negotiable Rules)

1. **配置检查优先**: API 调用前必须先检查 `cloudflare_access.enabled`
2. **头部完整性**: Cloudflare Access 模式必须同时包含两个头部，缺一不可
3. **错误检测**: API 调用后必须检查是否为 Cloudflare 相关错误
4. **自动提示**: 检测到 CF 错误时必须输出配置提示模板

---

**最后更新**: 2026-02-07
**适用版本**: Aria v1.4.0+
