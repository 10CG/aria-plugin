# .gitignore Validator & Auto-Fix

> **Branch Manager v2.0.0** | .gitignore 强制验证和自动修复
> **Phase 1.5** | enforcement-mechanism-redesign

## Overview

确保分支创建前 `.gitignore` 配置正确，防止意外提交敏感文件或构建产物。

---

## Validation Rules

### 必需规则 (Required)

每个项目应确保以下规则存在：

```gitignore
# 构建产物
/build/
/dist/
/target/
*.py[cod]
__pycache__/

# 依赖
/node_modules/
/vendor/
.venv/
venv/

# IDE
.idea/
.vscode/
*.swp
*.swo

# 环境变量
.env
.env.local
.env.*.local

# 工作目录
.git/worktrees/
```

### Worktree 专用规则

使用 Worktree 模式时，额外验证：

```gitignore
# Worktree 相关 (如果 worktree 在项目外)
/worktrees/
```

---

## Implementation

### Pseudo-Code

```python
import os
from pathlib import Path

class GitignoreValidator:
    """Gitignore 验证器和自动修复器"""

    # 必需规则
    REQUIRED_PATTERNS = {
        "build_artifacts": [
            "/build/",
            "/dist/",
            "/target/",
        ],
        "python": [
            "*.py[cod]",
            "__pycache__/",
            "*.so",
        ],
        "node": [
            "/node_modules/",
        ],
        "venv": [
            ".venv/",
            "venv/",
            "/.venv/",
        ],
        "ide": [
            ".idea/",
            ".vscode/",
            "*.swp",
            "*.swo",
        ],
        "env": [
            ".env",
            ".env.local",
            ".env.*.local",
        ],
        "worktree": [
            ".git/worktrees/",
        ],
    }

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self.gitignore_path = self.project_root / ".gitignore"
        self.missing_patterns = []

    def validate(self, auto_fix: bool = False) -> dict:
        """
        验证 .gitignore

        Args:
            auto_fix: 是否自动修复缺失规则

        Returns:
            {
                "valid": bool,
                "missing": list[str],
                "fixed": bool,
                "warnings": list[str],
            }
        """
        result = {
            "valid": True,
            "missing": [],
            "fixed": False,
            "warnings": [],
        }

        # 1. 检查 .gitignore 是否存在
        if not self.gitignore_path.exists():
            result["valid"] = False
            result["missing"].append("文件不存在")

            if auto_fix:
                self._create_gitignore()
                result["fixed"] = True
            return result

        # 2. 读取现有内容
        content = self._read_gitignore()

        # 3. 检查必需规则
        for category, patterns in self.REQUIRED_PATTERNS.items():
            for pattern in patterns:
                if not self._has_pattern(content, pattern):
                    result["valid"] = False
                    result["missing"].append(pattern)

        # 4. 自动修复
        if not result["valid"] and auto_fix:
            self._add_missing_patterns(result["missing"])
            result["fixed"] = True
            result["valid"] = True

        # 5. 警告检查
        result["warnings"] = self._check_warnings(content)

        return result

    def _read_gitignore(self) -> str:
        """读取 .gitignore 内容"""
        with open(self.gitignore_path, "r", encoding="utf-8") as f:
            return f.read()

    def _has_pattern(self, content: str, pattern: str) -> bool:
        """检查是否包含指定模式"""
        # 标准化: 去除空格和注释
        lines = [
            line.strip()
            for line in content.split("\n")
            if line.strip() and not line.strip().startswith("#")
        ]
        return pattern in lines

    def _create_gitignore(self):
        """创建默认 .gitignore"""
        default_content = self._get_default_content()
        with open(self.gitignore_path, "w", encoding="utf-8") as f:
            f.write(default_content)

    def _add_missing_patterns(self, missing: list[str]):
        """添加缺失的模式"""
        with open(self.gitignore_path, "a", encoding="utf-8") as f:
            f.write("\n# Auto-added by branch-manager\n")
            for pattern in missing:
                f.write(f"{pattern}\n")

    def _get_default_content(self) -> str:
        """获取默认 .gitignore 内容"""
        return """# Build artifacts
/build/
/dist/
/target/
*.py[cod]
__pycache__/
*.so

# Dependencies
/node_modules/
/vendor/

# Virtual environments
.venv/
venv/
/.venv/

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# Environment files
.env
.env.local
.env.*.local

# Worktrees
.git/worktrees/

# OS
.DS_Store
Thumbs.db
"""

    def _check_warnings(self, content: str) -> list[str]:
        """检查警告性问题"""
        warnings = []

        # 检查是否忽略了 .gitignore 本身
        if ".gitignore" in content:
            warnings.append(".gitignore 不应被忽略")

        # 检查是否有过于宽泛的规则
        if "*" in content and "*.py[cod]" not in content:
            warnings.append("存在通配符 * 规则，可能过于宽泛")

        return warnings
```

---

## Shell Script Implementation

```bash
#!/bin/bash
# scripts/gitignore-validator.sh
# .gitignore 验证和自动修复脚本

GITIGNORE_FILE=".gitignore"
AUTO_FIX=${1:-false}

# 验证结果
MISSING=()
WARNINGS=()

echo "=== .gitignore 验证 ==="
echo ""

# 1. 检查文件是否存在
if [ ! -f "$GITIGNORE_FILE" ]; then
    echo "❌ .gitignore 文件不存在"
    if [ "$AUTO_FIX" = "true" ]; then
        echo "   创建默认 .gitignore..."
        create_default_gitignore
    else
        echo "   运行 with --fix 来自动创建"
    fi
    exit 1
fi

# 2. 检查必需规则
check_pattern "/build/" "构建产物"
check_pattern "/dist/" "构建产物"
check_pattern "*.py[cod]" "Python 编译文件"
check_pattern "__pycache__/" "Python 缓存"
check_pattern "/node_modules/" "Node 依赖"
check_pattern ".venv/" "虚拟环境"
check_pattern "venv/" "虚拟环境"
check_pattern ".idea/" "IDE 配置"
check_pattern ".vscode/" "IDE 配置"
check_pattern ".env" "环境变量文件"
check_pattern ".git/worktrees/" "Worktree 目录"

# 3. 报告结果
if [ ${#MISSING[@]} -eq 0 ]; then
    echo "✅ .gitignore 验证通过"
else
    echo "❌ 缺失 ${#MISSING[@]} 条必需规则:"
    for pattern in "${MISSING[@]}"; do
        echo "   - $pattern"
    done

    if [ "$AUTO_FIX" = "true" ]; then
        echo ""
        echo "添加缺失规则..."
        add_missing_patterns
        echo "✅ 已修复"
    fi
fi

# 4. 警告
if [ ${#WARNINGS[@]} -gt 0 ]; then
    echo ""
    echo "⚠️ 警告:"
    for warning in "${WARNINGS[@]}"; do
        echo "   - $warning"
    done
fi

echo ""

check_pattern() {
    local pattern=$1
    local description=$2

    if ! grep -q "^${pattern}" "$GITIGNORE_FILE"; then
        MISSING+=("$pattern  # $description")
    fi
}

create_default_gitignore() {
    cat > "$GITIGNORE_FILE" << 'EOF'
# Build artifacts
/build/
/dist/
/target/
*.py[cod]
__pycache__/
*.so

# Dependencies
/node_modules/
/vendor/

# Virtual environments
.venv/
venv/
/.venv/

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# Environment files
.env
.env.local
.env.*.local

# Worktrees
.git/worktrees/

# OS
.DS_Store
Thumbs.db
EOF
    echo "✅ 已创建默认 .gitignore"
}

add_missing_patterns() {
    echo "" >> "$GITIGNORE_FILE"
    echo "# Auto-added by branch-manager" >> "$GITIGNORE_FILE"
    for entry in "${MISSING[@]}"; do
        local pattern=$(echo "$entry" | cut -d'#' -f1 | xargs)
        echo "$pattern" >> "$GITIGNORE_FILE"
    done
}
```

---

## Integration with Branch Creation

### B.1 流程集成

```yaml
B.1.1 - 环境验证:
  ├─ 检查当前分支
  ├─ 检查工作目录状态
  ├─ ✅ 验证 .gitignore (新增)
  │   ├─ 运行验证器
  │   ├─ 发现缺失规则?
  │   │   ├─ 是 → 提示用户
  │   │   │       用户同意? → 自动修复
  │   │   │       用户拒绝? → 警告并继续
  │   │   └─ 否 → 继续
  └─ 拉取最新代码
```

---

## Interactive Prompt

当发现 .gitignore 问题时：

```
⚠️ .gitignore 验证发现问题

缺失 3 条必需规则:
  - /node_modules/  # Node 依赖
  - .env            # 环境变量文件
  - .git/worktrees/ # Worktree 目录

建议: 自动添加这些规则可以防止意外提交敏感文件。

[Y]es, fix automatically  - 自动添加缺失规则
[N]o, continue anyway     - 跳过验证，继续创建分支
[A]bort                   - 中止操作

选择 [Y/N/A]:
```

---

## Validation Matrix

| 语言/框架 | 必需规则 | 可选规则 |
|----------|---------|---------|
| **Python** | `*.py[cod]`, `__pycache__/`, `.venv/` | `*.egg-info/`, `.tox/` |
| **Node.js** | `/node_modules/` | `npm-debug.log*`, `package-lock.json` |
| **Flutter** | `build/`, `.dart_tool/` | `*.apk`, `*.ipa` |
| **Rust** | `/target/` | `**/*.rs.bk`, `Cargo.lock` |
| **Go** | `*.exe`, `*.test` | `vendor/` |
| **通用** | `.env`, `.idea/`, `.vscode/` | `.DS_Store`, `Thumbs.db` |

---

## Auto-Fix Behavior

### 默认行为 (non-interactive)

```bash
# 验证但不修复
$ branch-manager --mode auto --task-id TASK-001
# → 输出警告，不自动修复

# 验证并自动修复
$ branch-manager --mode auto --task-id TASK-001 --fix-gitignore
# → 自动添加缺失规则
```

### 交互式行为

```bash
# 交互式模式 (默认)
$ branch-manager --mode auto --task-id TASK-001 --interactive
# → 发现问题时提示用户选择
```

---

## Error Messages

| 场景 | 消息 | 建议 |
|------|------|------|
| 文件不存在 | `.gitignore 文件不存在` | 使用 `--fix-gitignore` 自动创建 |
| 缺失规则 | `缺失 N 条必需规则` | 使用 `--fix-gitignore` 自动添加 |
| 有警告 | `发现 W 个警告性问题` | 检查 .gitignore 配置 |
| 无法修复 | `无法写入 .gitignore` | 检查文件权限 |

---

**Created**: 2026-01-20
**Part of**: enforcement-mechanism-redesign Phase 1.5
