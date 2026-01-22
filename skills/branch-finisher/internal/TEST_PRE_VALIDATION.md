# 测试前置验证逻辑

> **Branch Finisher v1.0.0** | Test Pre-Validation
> **Phase 3.2** | enforcement-mechanism-redesign

## Overview

测试前置验证确保分支开发完成后，所有测试通过才能继续提交流程。

---

## 验证项目

```
┌─────────────────────────────────────────────────────────────┐
│                      测试前置验证项目                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  阻塞级别 (必须通过):                                        │
│    ├─ 单元测试                                              │
│    ├─ 集成测试 (如有)                                       │
│    ├─ 类型检查                                              │
│    └─ 构建验证                                              │
│                                                             │
│  警告级别 (可选通过):                                        │
│    ├─ Lint 检查                                             │
│    ├─ 覆盖率检查                                            │
│    └─ 代码风格检查                                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation

### Pseudo-Code

```python
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum
import subprocess
import os

class ValidationLevel(Enum):
    BLOCKING = "blocking"  # 必须通过
    WARNING = "warning"    # 可以警告通过

class ValidationStatus(Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    WARNING = "warning"

@dataclass
class ValidationResult:
    """单项验证结果"""
    name: str
    status: ValidationStatus
    level: ValidationLevel
    message: str = ""
    details: List[str] = field(default_factory=list)
    duration: float = 0.0

@dataclass
class TestValidationReport:
    """测试验证报告"""
    passed: bool
    results: List[ValidationResult] = field(default_factory=list)
    blocking_failures: int = 0
    warnings: int = 0
    total_duration: float = 0.0

    def add_result(self, result: ValidationResult):
        self.results.append(result)
        self.total_duration += result.duration

        if result.status == ValidationStatus.FAIL:
            if result.level == ValidationLevel.BLOCKING:
                self.blocking_failures += 1
                self.passed = False
        elif result.status == ValidationStatus.WARNING:
            self.warnings += 1


class TestPreValidator:
    """测试前置验证器"""

    # 项目类型检测和命令映射
    PROJECT_CONFIGS = {
        "nodejs": {
            "detect_files": ["package.json"],
            "test_cmd": ["npm", "test"],
            "lint_cmd": ["npm", "run", "lint"],
            "build_cmd": ["npm", "run", "build"],
            "type_check_cmd": ["npx", "tsc", "--noEmit"],
        },
        "python": {
            "detect_files": ["pyproject.toml", "setup.py", "requirements.txt"],
            "test_cmd": ["pytest", "-v"],
            "lint_cmd": ["pylint", "src/"],
            "build_cmd": None,
            "type_check_cmd": ["mypy", "src/"],
        },
        "rust": {
            "detect_files": ["Cargo.toml"],
            "test_cmd": ["cargo", "test"],
            "lint_cmd": ["cargo", "clippy"],
            "build_cmd": ["cargo", "build"],
            "type_check_cmd": None,  # Rust 编译时检查
        },
        "flutter": {
            "detect_files": ["pubspec.yaml"],
            "test_cmd": ["flutter", "test"],
            "lint_cmd": ["flutter", "analyze"],
            "build_cmd": ["flutter", "build", "apk", "--debug"],
            "type_check_cmd": None,  # Dart 编译时检查
        },
        "go": {
            "detect_files": ["go.mod"],
            "test_cmd": ["go", "test", "./..."],
            "lint_cmd": ["golangci-lint", "run"],
            "build_cmd": ["go", "build", "./..."],
            "type_check_cmd": None,  # Go 编译时检查
        },
    }

    def __init__(self, project_root: str):
        self.project_root = project_root
        self.project_type = self._detect_project_type()

    def validate(
        self,
        run_tests: bool = True,
        run_lint: bool = True,
        run_build: bool = True,
        run_type_check: bool = True,
        coverage_threshold: float = None,
    ) -> TestValidationReport:
        """
        执行测试前置验证

        Args:
            run_tests: 是否运行测试
            run_lint: 是否运行 lint
            run_build: 是否运行构建
            run_type_check: 是否运行类型检查
            coverage_threshold: 覆盖率阈值 (可选)

        Returns:
            TestValidationReport: 验证报告
        """
        report = TestValidationReport(passed=True)

        if not self.project_type:
            report.add_result(ValidationResult(
                name="项目检测",
                status=ValidationStatus.WARNING,
                level=ValidationLevel.WARNING,
                message="无法检测项目类型，跳过验证",
            ))
            return report

        config = self.PROJECT_CONFIGS[self.project_type]

        # 1. 运行测试 (阻塞)
        if run_tests and config.get("test_cmd"):
            result = self._run_tests(config["test_cmd"])
            report.add_result(result)

        # 2. 类型检查 (阻塞)
        if run_type_check and config.get("type_check_cmd"):
            result = self._run_type_check(config["type_check_cmd"])
            report.add_result(result)

        # 3. 构建验证 (阻塞)
        if run_build and config.get("build_cmd"):
            result = self._run_build(config["build_cmd"])
            report.add_result(result)

        # 4. Lint 检查 (警告)
        if run_lint and config.get("lint_cmd"):
            result = self._run_lint(config["lint_cmd"])
            report.add_result(result)

        # 5. 覆盖率检查 (警告)
        if coverage_threshold:
            result = self._check_coverage(coverage_threshold)
            report.add_result(result)

        return report

    def _detect_project_type(self) -> Optional[str]:
        """检测项目类型"""
        for project_type, config in self.PROJECT_CONFIGS.items():
            for detect_file in config["detect_files"]:
                if os.path.exists(os.path.join(self.project_root, detect_file)):
                    return project_type
        return None

    def _run_command(
        self,
        cmd: List[str],
        timeout: int = 300
    ) -> tuple[bool, str, float]:
        """运行命令并返回结果"""
        import time
        start = time.time()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.project_root,
                timeout=timeout,
            )
            duration = time.time() - start
            success = result.returncode == 0
            output = result.stdout + result.stderr
            return success, output, duration

        except subprocess.TimeoutExpired:
            return False, "命令超时", time.time() - start
        except Exception as e:
            return False, str(e), time.time() - start

    def _run_tests(self, cmd: List[str]) -> ValidationResult:
        """运行测试"""
        success, output, duration = self._run_command(cmd)

        # 解析测试结果
        test_stats = self._parse_test_output(output)

        if success:
            return ValidationResult(
                name="单元测试",
                status=ValidationStatus.PASS,
                level=ValidationLevel.BLOCKING,
                message=f"通过 ({test_stats.get('passed', '?')}/{test_stats.get('total', '?')})",
                duration=duration,
            )
        else:
            return ValidationResult(
                name="单元测试",
                status=ValidationStatus.FAIL,
                level=ValidationLevel.BLOCKING,
                message=f"失败 ({test_stats.get('failed', '?')} 个测试失败)",
                details=self._extract_failed_tests(output),
                duration=duration,
            )

    def _run_type_check(self, cmd: List[str]) -> ValidationResult:
        """运行类型检查"""
        success, output, duration = self._run_command(cmd)

        if success:
            return ValidationResult(
                name="类型检查",
                status=ValidationStatus.PASS,
                level=ValidationLevel.BLOCKING,
                message="通过",
                duration=duration,
            )
        else:
            return ValidationResult(
                name="类型检查",
                status=ValidationStatus.FAIL,
                level=ValidationLevel.BLOCKING,
                message="类型错误",
                details=output.split("\n")[:10],  # 前 10 行错误
                duration=duration,
            )

    def _run_build(self, cmd: List[str]) -> ValidationResult:
        """运行构建"""
        success, output, duration = self._run_command(cmd, timeout=600)

        if success:
            return ValidationResult(
                name="构建验证",
                status=ValidationStatus.PASS,
                level=ValidationLevel.BLOCKING,
                message="构建成功",
                duration=duration,
            )
        else:
            return ValidationResult(
                name="构建验证",
                status=ValidationStatus.FAIL,
                level=ValidationLevel.BLOCKING,
                message="构建失败",
                details=output.split("\n")[-20:],  # 最后 20 行错误
                duration=duration,
            )

    def _run_lint(self, cmd: List[str]) -> ValidationResult:
        """运行 lint"""
        success, output, duration = self._run_command(cmd)

        if success:
            return ValidationResult(
                name="Lint 检查",
                status=ValidationStatus.PASS,
                level=ValidationLevel.WARNING,
                message="通过",
                duration=duration,
            )
        else:
            # Lint 失败是警告级别
            return ValidationResult(
                name="Lint 检查",
                status=ValidationStatus.WARNING,
                level=ValidationLevel.WARNING,
                message="有警告",
                details=output.split("\n")[:10],
                duration=duration,
            )

    def _check_coverage(self, threshold: float) -> ValidationResult:
        """检查测试覆盖率"""
        # 这里需要根据项目类型使用不同的覆盖率工具
        # 简化实现
        coverage = self._get_coverage()

        if coverage >= threshold:
            return ValidationResult(
                name="覆盖率检查",
                status=ValidationStatus.PASS,
                level=ValidationLevel.WARNING,
                message=f"{coverage:.1f}% >= {threshold:.1f}%",
            )
        else:
            return ValidationResult(
                name="覆盖率检查",
                status=ValidationStatus.WARNING,
                level=ValidationLevel.WARNING,
                message=f"{coverage:.1f}% < {threshold:.1f}%",
            )

    def _get_coverage(self) -> float:
        """获取覆盖率"""
        # 简化实现，实际需要解析覆盖率报告
        return 85.0

    def _parse_test_output(self, output: str) -> Dict:
        """解析测试输出"""
        # 简化实现
        return {"total": 42, "passed": 42, "failed": 0}

    def _extract_failed_tests(self, output: str) -> List[str]:
        """提取失败的测试"""
        # 简化实现
        return []
```

---

## 验证报告格式

### 成功报告

```yaml
# 验证成功
passed: true
blocking_failures: 0
warnings: 1
total_duration: 45.2

results:
  - name: "单元测试"
    status: "pass"
    level: "blocking"
    message: "通过 (42/42)"
    duration: 30.5

  - name: "类型检查"
    status: "pass"
    level: "blocking"
    message: "通过"
    duration: 5.2

  - name: "构建验证"
    status: "pass"
    level: "blocking"
    message: "构建成功"
    duration: 8.5

  - name: "Lint 检查"
    status: "warning"
    level: "warning"
    message: "3 个警告"
    details:
      - "src/auth.py:42: Line too long (120 > 100)"
    duration: 1.0
```

### 失败报告

```yaml
# 验证失败
passed: false
blocking_failures: 1
warnings: 0
total_duration: 35.8

results:
  - name: "单元测试"
    status: "fail"
    level: "blocking"
    message: "失败 (2 个测试失败)"
    details:
      - "test_auth.py::test_login_invalid_password - AssertionError"
      - "test_auth.py::test_register_duplicate_email - IntegrityError"
    duration: 28.3

  - name: "类型检查"
    status: "pass"
    level: "blocking"
    message: "通过"
    duration: 5.2

  - name: "构建验证"
    status: "skip"
    level: "blocking"
    message: "因测试失败跳过"
    duration: 0.0
```

---

## 显示格式

```
┌─────────────────────────────────────────────────────────────┐
│                      测试前置验证                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  项目类型: Python (pytest)                                  │
│                                                             │
│  验证结果:                                                   │
│    ✅ 单元测试     通过 (42/42)           30.5s            │
│    ✅ 类型检查     通过                    5.2s            │
│    ✅ 构建验证     构建成功                8.5s            │
│    ⚠️ Lint 检查   3 个警告                1.0s            │
│                                                             │
│  总计: 45.2s                                                │
│  状态: ✅ 通过 (0 阻塞, 1 警告)                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 与 tdd-enforcer 集成

```python
def validate_with_tdd_enforcer(project_root: str) -> TestValidationReport:
    """
    使用 tdd-enforcer 进行验证

    优势:
    - 复用 TDD 流程中的测试配置
    - 确保 RED-GREEN-REFACTOR 流程完整
    """
    # 调用 tdd-enforcer 的验证功能
    # ...
    pass
```

---

**Created**: 2026-01-21
**Part of**: enforcement-mechanism-redesign Phase 3.2
