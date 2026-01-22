"""
TDD Enforcer Validators

Implements validation rules for enforcing Test-Driven Development practices.

Related: TASK-003 (aria-workflow-enhancement)
Version: 1.0.0
"""

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
from enum import Enum


class Severity(Enum):
    """Severity levels for violations"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Violation:
    """Represents a TDD rule violation"""

    def __init__(
        self,
        rule_id: str,
        severity: Severity,
        message: str,
        suggestion: str,
        dependencies: Optional[List[str]] = None
    ):
        self.rule_id = rule_id
        self.severity = severity
        self.message = message
        self.suggestion = suggestion
        self.dependencies = dependencies or []

    def __str__(self) -> str:
        result = f"[{self.severity.value.upper()}] {self.message}\n"
        if self.suggestion:
            result += f"Suggestion:\n{self.suggestion}\n"
        if self.dependencies:
            result += f"Dependencies:\n" + "\n".join(f"  - {d}" for d in self.dependencies)
        return result


class LanguageMapping:
    """Maps source files to their corresponding test files"""

    MAPPINGS = {
        "python": {
            "test_patterns": ["test_*.py", "*_test.py"],
            "source_patterns": ["*.py"],
            "test_dir": "tests"
        },
        "javascript": {
            "test_patterns": ["*.test.js", "*.spec.js"],
            "source_patterns": ["*.js"],
            "test_dir": "__tests__"
        },
        "typescript": {
            "test_patterns": ["*.test.ts", "*.spec.ts"],
            "source_patterns": ["*.ts"],
            "test_dir": "__tests__"
        },
        "dart": {
            "test_patterns": ["*_test.dart"],
            "source_patterns": ["*.dart"],
            "test_dir": "test"
        },
        "java": {
            "test_patterns": ["*Test.java"],
            "source_patterns": ["*.java"],
            "test_dir": "src/test/java"
        },
        "go": {
            "test_patterns": ["*_test.go"],
            "source_patterns": ["*.go"],
            "test_dir": ""
        }
    }

    @classmethod
    def detect_language(cls, file_path: str) -> Optional[str]:
        """Detect programming language from file extension"""
        ext = Path(file_path).suffix.lower()
        for lang, config in cls.MAPPINGS.items():
            if f".{ext}" in config["source_patterns"]:
                return lang
        return None

    @classmethod
    def get_test_file_patterns(cls, language: str) -> List[str]:
        """Get test file patterns for a language"""
        return cls.MAPPINGS.get(language, {}).get("test_patterns", [])

    @classmethod
    def find_test_files(cls, source_file: str, root_dir: str) -> List[str]:
        """Find corresponding test files for a source file"""
        language = cls.detect_language(source_file)
        if not language:
            return []

        source_path = Path(source_file)
        patterns = cls.get_test_file_patterns(language)
        test_dir = cls.MAPPINGS[language].get("test_dir", "")

        test_files = []
        root = Path(root_dir)

        # Try same directory
        for pattern in patterns:
            test_name = pattern.replace("*", source_path.stem)
            same_dir_test = source_path.parent / test_name
            if same_dir_test.exists():
                test_files.append(str(same_dir_test))

        # Try test directory
        if test_dir:
            test_root = root / test_dir
            if test_root.exists():
                relative_path = source_path.relative_to(root)
                for pattern in patterns:
                    test_name = pattern.replace("*", source_path.stem)
                    test_file = test_root / relative_path.parent / test_name
                    if test_file.exists():
                        test_files.append(str(test_file))

        return test_files


class TDDValidator:
    """Main validator for enforcing TDD rules"""

    def __init__(
        self,
        root_dir: str = ".",
        strict_mode: bool = False,
        skip_patterns: Optional[List[str]] = None
    ):
        self.root_dir = Path(root_dir).resolve()
        self.strict_mode = strict_mode
        self.skip_patterns = skip_patterns or self._default_skip_patterns()

    def _default_skip_patterns(self) -> List[str]:
        """Default file patterns to skip validation"""
        return [
            "**/*.md",
            "**/*.json",
            "**/*.yaml",
            "**/*.yml",
            "**/config/**",
            "**/migrations/**",
            "**/fixtures/**",
            "**/mock*/**",
            "**/node_modules/**",
            "**/.venv/**",
            "**/venv/**",
            "**/__pycache__/**"
        ]

    def _should_skip(self, file_path: str) -> bool:
        """Check if file should be skipped"""
        from fnmatch import fnmatch

        path = Path(file_path)
        rel_path = str(path.relative_to(self.root_dir))

        for pattern in self.skip_patterns:
            if fnmatch(rel_path, pattern) or fnmatch(path.name, pattern):
                return True
        return False

    def validate_write_before_test(self, file_path: str) -> Optional[Violation]:
        """
        Validate that source code is not written before tests exist.

        Rule: no_test_before_code
        """
        if self._should_skip(file_path):
            return None

        language = LanguageMapping.detect_language(file_path)
        if not language:
            return None

        # Check if this is a test file
        test_patterns = LanguageMapping.get_test_file_patterns(language)
        for pattern in test_patterns:
            if "*" in pattern:
                pattern = pattern.replace("*", ".*")
            if re.match(pattern, Path(file_path).name):
                return None  # This is a test file, allow writing

        # This is a source file, check for corresponding test
        test_files = LanguageMapping.find_test_files(file_path, str(self.root_dir))

        if not test_files:
            return Violation(
                rule_id="no_test_before_code",
                severity=Severity.ERROR if self.strict_mode else Severity.WARNING,
                message=f"Writing source code without corresponding test: {file_path}",
                suggestion=f"1. Create a failing test first (RED phase)\n"
                          f"2. Run test to confirm failure\n"
                          f"3. Then write implementation code\n\n"
                          f"Expected test location: Based on {language} conventions"
            )

        return None

    def validate_test_deletion(self, file_path: str) -> Optional[Violation]:
        """
        Validate that tests with code dependencies are not deleted.

        Rule: delete_test_with_dependency
        """
        path = Path(file_path)

        # Check if this is a test file
        if not self._is_test_file(path):
            return None

        # Find dependencies
        dependencies = self._find_code_dependencies(path)

        if dependencies:
            return Violation(
                rule_id="delete_test_with_dependency",
                severity=Severity.ERROR,
                message=f"Cannot delete test: Source code depends on {file_path}",
                suggestion="1. Remove or update dependent code first\n"
                          "2. Then delete the test",
                dependencies=dependencies
            )

        return None

    def _is_test_file(self, path: Path) -> bool:
        """Check if file is a test file"""
        name = path.name
        return (
            "test" in name.lower() or
            name.startswith("test_") or
            name.endswith("_test.py") or
            name.endswith(".test.js") or
            name.endswith(".test.ts") or
            name.endswith(".spec.js") or
            name.endswith(".spec.ts") or
            name.endswith("_test.dart") or
            name.endswith("Test.java") or
            name.endswith("_test.go")
        )

    def _find_code_dependencies(self, test_file: Path) -> List[str]:
        """
        Find source files that depend on this test.
        This is a simplified implementation.
        """
        # In production, this would parse test and source files
        return []

    def validate_refactor_safety(self, file_path: str, tests_run: bool = False) -> Optional[Violation]:
        """
        Validate that refactoring is done with test safety.

        Rule: refactor_without_tests
        """
        if self._should_skip(file_path):
            return None

        if not tests_run:
            return Violation(
                rule_id="refactor_without_tests",
                severity=Severity.INFO,
                message="Refactoring code without running tests",
                suggestion="Run tests after each refactor step to ensure no regressions"
            )

        return None


def validate_file_operation(
    operation: str,
    file_path: str,
    root_dir: str = ".",
    strict_mode: bool = False,
    **kwargs
) -> Tuple[bool, Optional[Violation]]:
    """
    Main entry point for validating file operations.

    Args:
        operation: The operation being performed ('write', 'edit', 'delete')
        file_path: Path to the file being operated on
        root_dir: Root directory of the project
        strict_mode: Whether to use strict mode (errors instead of warnings)
        **kwargs: Additional operation-specific arguments

    Returns:
        Tuple of (is_valid, violation)
    """
    validator = TDDValidator(root_dir=root_dir, strict_mode=strict_mode)

    if operation in ("write", "edit"):
        violation = validator.validate_write_before_test(file_path)
        if violation:
            return (False, violation)

    elif operation == "delete":
        violation = validator.validate_test_deletion(file_path)
        if violation:
            return (False, violation)

    return (True, None)


# CLI interface for testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python validator.py <operation> <file_path>")
        sys.exit(1)

    operation = sys.argv[1]
    file_path = sys.argv[2]

    is_valid, violation = validate_file_operation(
        operation=operation,
        file_path=file_path,
        strict_mode="--strict" in sys.argv
    )

    if not is_valid:
        print(violation)
        sys.exit(1)
    else:
        print(f"OK: {operation} on {file_path}")
        sys.exit(0)
