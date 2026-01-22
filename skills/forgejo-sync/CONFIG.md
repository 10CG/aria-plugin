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
