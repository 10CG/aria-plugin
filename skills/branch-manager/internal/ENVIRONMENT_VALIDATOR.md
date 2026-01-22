# Environment Validator

> **Branch Manager v2.0.0** | 环境验证 (npm/cargo/pnpm + 测试基线)
> **Phase 1.6** | enforcement-mechanism-redesign

## Overview

确保分支创建前开发环境配置正确，包括：
- 包管理器可用性检查 (npm, cargo, pnpm, poetry, etc.)
- 依赖安装状态验证
- 测试基线检查
- 构建工具可用性

---

## Supported Ecosystems

| 生态系统 | 包管理器 | 检测文件 | 测试命令 |
|---------|---------|---------|---------|
| **Node.js** | npm, pnpm, yarn | `package.json` | `npm test`, `pnpm test` |
| **Python** | poetry, pip, uv | `pyproject.toml`, `requirements.txt` | `pytest`, `python -m unittest` |
| **Rust** | cargo | `Cargo.toml` | `cargo test` |
| **Flutter** | flutter | `pubspec.yaml` | `flutter test` |
| **Go** | go | `go.mod` | `go test ./...` |

---

## Implementation

### Pseudo-Code

```python
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

class EnvironmentValidator:
    """环境验证器"""

    # 生态系统检测映射
    ECOSYSTEM_DETECTIONS = {
        "nodejs": {
            "files": ["package.json"],
            "managers": ["npm", "pnpm", "yarn"],
            "test_commands": ["npm test", "pnpm test", "yarn test"],
            "install_commands": ["npm install", "pnpm install", "yarn install"],
        },
        "python": {
            "files": ["pyproject.toml", "requirements.txt", "setup.py"],
            "managers": ["poetry", "pip", "uv"],
            "test_commands": ["pytest", "python -m pytest", "python -m unittest"],
            "install_commands": ["poetry install", "pip install -r requirements.txt", "uv sync"],
        },
        "rust": {
            "files": ["Cargo.toml"],
            "managers": ["cargo"],
            "test_commands": ["cargo test"],
            "install_commands": ["cargo fetch"],
        },
        "flutter": {
            "files": ["pubspec.yaml"],
            "managers": ["flutter", "dart"],
            "test_commands": ["flutter test", "dart test"],
            "install_commands": ["flutter pub get"],
        },
        "go": {
            "files": ["go.mod"],
            "managers": ["go"],
            "test_commands": ["go test ./..."],
            "install_commands": ["go mod download"],
        },
    }

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self.ecosystem = self._detect_ecosystem()
        self.validation_results = {}

    def validate(
        self,
        check_dependencies: bool = True,
        check_tests: bool = False,
        auto_fix: bool = False
    ) -> dict:
        """
        执行环境验证

        Args:
            check_dependencies: 是否检查依赖安装状态
            check_tests: 是否运行测试基线
            auto_fix: 是否自动修复问题

        Returns:
            {
                "valid": bool,
                "ecosystem": str,
                "manager": str,
                "checks": {...},
                "errors": list[str],
                "warnings": list[str],
                "fixes_applied": list[str],
            }
        """
        result = {
            "valid": True,
            "ecosystem": self.ecosystem or "unknown",
            "manager": None,
            "checks": {},
            "errors": [],
            "warnings": [],
            "fixes_applied": [],
        }

        # 1. 检测生态系统
        if not self.ecosystem:
            result["warnings"].append("无法检测项目类型")
            return result

        ecosystem_config = self.ECOSYSTEM_DETECTIONS[self.ecosystem]

        # 2. 查找可用的包管理器
        manager = self._find_manager(ecosystem_config["managers"])
        result["manager"] = manager

        if not manager:
            result["valid"] = False
            result["errors"].append(f"找不到包管理器: {', '.join(ecosystem_config['managers'])}")
            return result

        # 3. 检查包管理器版本
        version = self._get_manager_version(manager)
        result["checks"]["manager_version"] = {
            "manager": manager,
            "version": version,
            "valid": version is not None,
        }

        # 4. 检查依赖安装状态
        if check_dependencies:
            dep_result = self._check_dependencies(manager, ecosystem_config)
            result["checks"]["dependencies"] = dep_result

            if not dep_result["installed"]:
                if auto_fix:
                    self._install_dependencies(manager, ecosystem_config)
                    result["fixes_applied"].append(f"依赖安装: {manager}")
                    # 重新检查
                    dep_result = self._check_dependencies(manager, ecosystem_config)
                    result["checks"]["dependencies"] = dep_result
                else:
                    result["valid"] = False
                    result["errors"].append(f"依赖未安装，运行: {ecosystem_config['install_commands'][0]}")

        # 5. 运行测试基线
        if check_tests:
            test_result = self._run_tests(manager, ecosystem_config)
            result["checks"]["tests"] = test_result

            if not test_result["passed"]:
                result["warnings"].append(f"测试基线未通过: {test_result.get('output', '')}")

        return result

    def _detect_ecosystem(self) -> Optional[str]:
        """检测项目生态系统"""
        for ecosystem, config in self.ECOSYSTEM_DETECTIONS.items():
            for file in config["files"]:
                if (self.project_root / file).exists():
                    return ecosystem
        return None

    def _find_manager(self, managers: List[str]) -> Optional[str]:
        """查找可用的包管理器"""
        for manager in managers:
            if self._command_exists(manager):
                return manager
        return None

    def _command_exists(self, command: str) -> bool:
        """检查命令是否存在"""
        try:
            subprocess.run(
                ["which", command],
                capture_output=True,
                check=True
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def _get_manager_version(self, manager: str) -> Optional[str]:
        """获取包管理器版本"""
        try:
            version_commands = {
                "npm": ["npm", "--version"],
                "pnpm": ["pnpm", "--version"],
                "yarn": ["yarn", "--version"],
                "poetry": ["poetry", "--version"],
                "pip": ["pip", "--version"],
                "uv": ["uv", "--version"],
                "cargo": ["cargo", "--version"],
                "flutter": ["flutter", "--version"],
                "dart": ["dart", "--version"],
                "go": ["go", "version"],
            }
            result = subprocess.run(
                version_commands.get(manager, [manager, "--version"]),
                capture_output=True,
                text=True,
                check=False
            )
            return result.stdout.strip().split("\n")[0]
        except:
            return None

    def _check_dependencies(self, manager: str, config: dict) -> dict:
        """检查依赖安装状态"""
        # 根据不同生态系统使用不同检查方法
        checks = {
            "npm": self._check_npm_dependencies,
            "pnpm": self._check_pnpm_dependencies,
            "yarn": self._check_yarn_dependencies,
            "poetry": self._check_poetry_dependencies,
            "pip": self._check_pip_dependencies,
            "uv": self._check_uv_dependencies,
            "cargo": self._check_cargo_dependencies,
            "flutter": self._check_flutter_dependencies,
            "dart": self._check_flutter_dependencies,
            "go": self._check_go_dependencies,
        }

        checker = checks.get(manager)
        if checker:
            return checker()

        return {"installed": True, "message": "未实现检查"}

    def _check_npm_dependencies(self) -> dict:
        """检查 npm 依赖"""
        node_modules = self.project_root / "node_modules"
        if node_modules.exists():
            return {"installed": True, "path": str(node_modules)}
        return {"installed": False, "message": "node_modules 不存在"}

    def _check_pnpm_dependencies(self) -> dict:
        """检查 pnpm 依赖"""
        # pnpm 使用 node_modules 但有不同的结构
        return self._check_npm_dependencies()

    def _check_yarn_dependencies(self) -> dict:
        """检查 yarn 依赖"""
        return self._check_npm_dependencies()

    def _check_poetry_dependencies(self) -> dict:
        """检查 poetry 依赖"""
        try:
            result = subprocess.run(
                ["poetry", "check"],
                capture_output=True,
                text=True,
                cwd=self.project_root,
            )
            return {"installed": result.returncode == 0}
        except:
            return {"installed": False}

    def _check_pip_dependencies(self) -> dict:
        """检查 pip 依赖"""
        # 简化检查: 检查是否存在 venv
        venv_paths = [".venv", "venv", "env"]
        for venv in venv_paths:
            if (self.project_root / venv).exists():
                return {"installed": True, "path": venv}
        return {"installed": False, "message": "虚拟环境未找到"}

    def _check_uv_dependencies(self) -> dict:
        """检查 uv 依赖"""
        return self._check_pip_dependencies()

    def _check_cargo_dependencies(self) -> dict:
        """检查 cargo 依赖"""
        # Cargo 在构建时自动下载依赖
        return {"installed": True, "message": "依赖按需下载"}

    def _check_flutter_dependencies(self) -> dict:
        """检查 Flutter 依赖"""
        # 检查 .packages 文件
        if (self.project_root / ".packages").exists():
            return {"installed": True}
        # 检查 .dart_tool/package_config.json
        if (self.project_root / ".dart_tool" / "package_config.json").exists():
            return {"installed": True}
        return {"installed": False, "message": "Flutter 依赖未安装"}

    def _check_go_dependencies(self) -> dict:
        """检查 Go 依赖"""
        # Go 模块缓存自动管理
        return {"installed": True, "message": "依赖按需下载"}

    def _install_dependencies(self, manager: str, config: dict):
        """安装依赖"""
        install_cmd = config["install_commands"][0]
        subprocess.run(
            install_cmd.split(),
            cwd=self.project_root,
            check=True
        )

    def _run_tests(self, manager: str, config: dict) -> dict:
        """运行测试基线"""
        test_cmd = config["test_commands"][0]
        try:
            result = subprocess.run(
                test_cmd.split(),
                capture_output=True,
                text=True,
                cwd=self.project_root,
                timeout=60,  # 1分钟超时
            )
            return {
                "passed": result.returncode == 0,
                "output": result.stdout + result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"passed": False, "output": "测试超时"}
        except Exception as e:
            return {"passed": False, "output": str(e)}
```

---

## Shell Script Implementation

```bash
#!/bin/bash
# scripts/env-validator.sh
# 环境验证脚本

PROJECT_ROOT=${1:-.}
CHECK_DEPS=${2:-true}
RUN_TESTS=${3:-false}
AUTO_FIX=${4:-false}

echo "=== 环境验证 ==="
echo ""

# 检测生态系统
detect_ecosystem() {
    if [ -f "$PROJECT_ROOT/package.json" ]; then
        echo "nodejs"
    elif [ -f "$PROJECT_ROOT/pyproject.toml" ] || [ -f "$PROJECT_ROOT/requirements.txt" ]; then
        echo "python"
    elif [ -f "$PROJECT_ROOT/Cargo.toml" ]; then
        echo "rust"
    elif [ -f "$PROJECT_ROOT/pubspec.yaml" ]; then
        echo "flutter"
    elif [ -f "$PROJECT_ROOT/go.mod" ]; then
        echo "go"
    else
        echo "unknown"
    fi
}

ECOSYSTEM=$(detect_ecosystem)
echo "检测到生态系统: $ECOSYSTEM"
echo ""

# Node.js 验证
validate_nodejs() {
    # 查找包管理器
    if command -v pnpm &> /dev/null; then
        MANAGER="pnpm"
    elif command -v npm &> /dev/null; then
        MANAGER="npm"
    elif command -v yarn &> /dev/null; then
        MANAGER="yarn"
    else
        echo "❌ 找不到包管理器 (npm/pnpm/yarn)"
        return 1
    fi

    echo "✓ 包管理器: $MANAGER"

    # 检查版本
    VERSION=$($MANAGER --version)
    echo "  版本: $VERSION"

    # 检查依赖
    if [ "$CHECK_DEPS" = "true" ]; then
        if [ -d "$PROJECT_ROOT/node_modules" ]; then
            echo "✓ 依赖已安装"
        else
            echo "⚠️ 依赖未安装"
            if [ "$AUTO_FIX" = "true" ]; then
                echo "  正在安装依赖..."
                $MANAGER install
                echo "✓ 依赖已安装"
            else
                echo "  运行: $MANAGER install"
            fi
        fi
    fi

    # 运行测试
    if [ "$RUN_TESTS" = "true" ]; then
        echo "运行测试基线..."
        $MANAGER test
    fi
}

# Python 验证
validate_python() {
    if command -v poetry &> /dev/null; then
        MANAGER="poetry"
    elif command -v uv &> /dev/null; then
        MANAGER="uv"
    elif command -v pip &> /dev/null; then
        MANAGER="pip"
    else
        echo "❌ 找不到包管理器 (poetry/pip/uv)"
        return 1
    fi

    echo "✓ 包管理器: $MANAGER"

    VERSION=$($MANAGER --version 2>/dev/null || echo "unknown")
    echo "  版本: $VERSION"

    # 检查虚拟环境
    if [ -d "$PROJECT_ROOT/.venv" ] || [ -d "$PROJECT_ROOT/venv" ]; then
        echo "✓ 虚拟环境已创建"
    else
        echo "⚠️ 虚拟环境未找到"
        if [ "$AUTO_FIX" = "true" ] && [ "$MANAGER" = "poetry" ]; then
            echo "  正在创建虚拟环境..."
            poetry install
            echo "✓ 虚拟环境已创建"
        fi
    fi
}

# Rust 验证
validate_rust() {
    if ! command -v cargo &> /dev/null; then
        echo "❌ 找不到 cargo"
        return 1
    fi

    echo "✓ 包管理器: cargo"
    VERSION=$(cargo --version)
    echo "  版本: $VERSION"

    # 运行测试
    if [ "$RUN_TESTS" = "true" ]; then
        echo "运行测试基线..."
        cargo test
    fi
}

# Flutter 验证
validate_flutter() {
    if ! command -v flutter &> /dev/null; then
        echo "❌ 找不到 flutter"
        return 1
    fi

    echo "✓ 包管理器: flutter"
    VERSION=$(flutter --version 2>&1 | head -1)
    echo "  版本: $VERSION"

    # 检查依赖
    if [ -f "$PROJECT_ROOT/.dart_tool/package_config.json" ]; then
        echo "✓ 依赖已安装"
    else
        echo "⚠️ 依赖未安装"
        if [ "$AUTO_FIX" = "true" ]; then
            echo "  正在获取依赖..."
            flutter pub get
            echo "✓ 依赖已安装"
        fi
    fi
}

# Go 验证
validate_go() {
    if ! command -v go &> /dev/null; then
        echo "❌ 找不到 go"
        return 1
    fi

    echo "✓ 包管理器: go"
    VERSION=$(go version)
    echo "  版本: $VERSION"

    # 运行测试
    if [ "$RUN_TESTS" = "true" ]; then
        echo "运行测试基线..."
        go test ./...
    fi
}

# 执行验证
case "$ECOSYSTEM" in
    nodejs)
        validate_nodejs
        ;;
    python)
        validate_python
        ;;
    rust)
        validate_rust
        ;;
    flutter)
        validate_flutter
        ;;
    go)
        validate_go
        ;;
    *)
        echo "⚠️ 未知项目类型，跳过环境验证"
        ;;
esac

echo ""
echo "=== 验证完成 ==="
```

---

## Integration with Branch Creation

### B.1 流程集成

```yaml
B.1.1 - 环境验证 (增强版):
  ├─ 检查当前分支
  ├─ 检查工作目录状态
  ├─ ✅ 验证 .gitignore
  ├─ ✅ 验证开发环境 (新增)
  │   ├─ 检测项目类型 (Node/Python/Rust/Flutter/Go)
  │   ├─ 检查包管理器可用性
  │   ├─ 检查依赖安装状态
  │   │   └─ 未安装? → 提示安装 (或自动修复)
  │   └─ 运行测试基线 (可选)
  └─ 拉取最新代码
```

---

## Validation Summary

| 生态系统 | 包管理器 | 依赖检查 | 测试命令 |
|---------|---------|---------|---------|
| Node.js | npm/pnpm/yarn | `node_modules/` | `npm test` |
| Python | poetry/pip/uv | `.venv/` | `pytest` |
| Rust | cargo | N/A (自动) | `cargo test` |
| Flutter | flutter | `.dart_tool/` | `flutter test` |
| Go | go | N/A (自动) | `go test ./...` |

---

**Created**: 2026-01-20
**Part of**: enforcement-mechanism-redesign Phase 1.6
