# 跨平台兼容命令参考

> **目的**: 确保 state-scanner Skill 在 Windows (Git Bash/WSL)、macOS、Linux 上正常工作

---

## 背景

Claude Code 在 Windows 上使用 **Git Bash** 或 **WSL**，而非 Windows CMD。所有 Bash 命令必须使用跨平台兼容的语法。

---

## 命令对照表

| 场景 | ✅ 正确 (跨平台) | ❌ 错误 (Windows CMD) |
|------|------------------|----------------------|
| 检查文件存在 | `ls path/*.md 2>/dev/null \|\| echo "NO"` | `if exist path\*.md (dir ...) else (echo NO)` |
| 列出文件 | `ls docs/requirements/` | `dir docs\requirements\` |
| 条件判断 | `[ -f file ] && cat file \|\| echo "NO"` | `if exist file (type file) else ...` |
| 路径分隔符 | `/` (正斜杠) | `\` (反斜杠) |
| 重定向错误 | `2>/dev/null` | `2>nul` |

---

## 文件检查模式

### 基本模式

```bash
# 检查文件是否存在 (推荐)
ls docs/requirements/prd-*.md 2>/dev/null || echo "NO_PRD"

# 检查目录是否存在
ls docs/requirements/user-stories/US-*.md 2>/dev/null || echo "NO_STORIES"

# 检查并读取文件
cat docs/architecture/system-architecture.md 2>/dev/null || echo "NO_ARCH"
```

### Test 命令模式

```bash
# 文件存在检查
[ -f "docs/requirements/prd.md" ] && echo "EXISTS" || echo "NOT_FOUND"

# 目录存在检查
[ -d "docs/requirements" ] && echo "DIR_EXISTS" || echo "DIR_NOT_FOUND"

# 文件可读检查
[ -r "docs/architecture/system-architecture.md" ] && echo "READABLE"

# 组合条件
[ -f "file.md" ] && [ -r "file.md" ] && cat file.md
```

---

## Git 命令规范

Git 命令本身是跨平台的，直接使用：

```bash
git status --porcelain
git branch --show-current
git log --oneline -5
git submodule status
git diff --stat
```

---

## 禁用模式

以下模式**禁止使用**，因为它们是 Windows CMD 专用语法：

| 禁用模式 | 原因 |
|---------|------|
| `if exist ... ( ... ) else ( ... )` | CMD 条件语法 |
| `dir /b` | CMD 列表命令 |
| `type` | CMD 显示文件命令 |
| `2>nul` | CMD 错误重定向 |
| `\` 路径分隔符 | Windows 路径格式 |

---

## 调试技巧

### 检测 Shell 类型

```bash
# 检测当前 shell
echo $SHELL

# 检测是否为 Git Bash
[[ "$BASH_VERSION" ]] && echo "Running Bash"

# 检测操作系统
case "$(uname -s)" in
  Linux*)     echo "Linux";;
  Darwin*)    echo "macOS";;
  MINGW*|MSYS*) echo "Git Bash";;
  CYGWIN*)    echo "Cygwin";;
  *)          echo "Unknown";;
esac
```

### 测试命令兼容性

```bash
# 测试文件检查
test -f "test.txt" && echo "PASS" || echo "FAIL"

# 测试错误重定向
ls nonexistent 2>/dev/null && echo "SHOULD NOT SEE"
```

---

## 常见场景

### 扫描 PRD 文件

```bash
# 方法 1: ls + 通配符
ls docs/requirements/prd-*.md 2>/dev/null || echo "NO_PRD"

# 方法 2: find 命令
find docs/requirements -name "prd-*.md" -type f 2>/dev/null
```

### 扫描 User Stories

```bash
# 检查是否有 US 文件
ls docs/requirements/user-stories/US-*.md 2>/dev/null || echo "NO_STORIES"

# 统计数量
ls docs/requirements/user-stories/US-*.md 2>/dev/null | wc -l
```

### 检查 OpenSpec

```bash
# 检查 proposal 是否存在
cat openspec/changes/proposal.md 2>/dev/null || echo "NO_PROPOSAL"

# 检查目录结构
ls -la openspec/changes/ 2>/dev/null || echo "NO_OPENSPEC_DIR"
```

---

## 更新记录

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-02-06 | 初始版本 |
