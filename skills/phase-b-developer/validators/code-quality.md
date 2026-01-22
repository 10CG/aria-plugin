# Phase 2: 代码质量检查

> **版本**: 1.0.0
> **来源**: TASK-019
> **Skill**: phase-b-developer

---

## 概述

Phase 2 验证代码质量，包括测试覆盖率、代码复杂度、安全扫描等。与 Phase 1 不同，Phase 2 问题**不阻塞**开发，仅记录警告和建议。

---

## 检查项目

### 1. 测试覆盖率检查

验证代码测试覆盖是否达到要求。

```yaml
检查项:
  - 单元测试覆盖率
  - 集成测试覆盖率
  - 关键路径覆盖

验证规则:
  test_coverage:
    threshold: 85  # 目标 85%
    warning: 70    # 低于 70% 警告
    critical: 50   # 低于 50% 严重警告

  检测方法:
    - Dart: flutter test --coverage
    - Python: pytest --cov=src --cov-report=term
    - JavaScript: npm test -- --coverage

  排除:
    - generated files
    - test files
    - mock files
```

### 2. 代码复杂度分析

分析代码圈复杂度是否在合理范围。

```yaml
检查项:
  - 圈复杂度 (Cyclomatic Complexity)
  - 认知复杂度 (Cognitive Complexity)
  - 嵌套深度 (Nesting Depth)

验证规则:
  complexity:
    threshold: 10     # 目标 <= 10
    warning: 15       # 超过 15 警告
    critical: 20      # 超过 20 严重警告

  检测方法:
    - Dart: dart analyze
    - Python: radon cc
    - JavaScript: eslint complexity

  按文件类型:
    - Controllers: threshold 8
    - Services: threshold 10
    - Models: threshold 5
    - Utils: threshold 15
```

### 3. 安全漏洞扫描

扫描代码中的潜在安全问题。

```yaml
检查项:
  - SQL 注入风险
  - XSS 风险
  - 硬编码密钥
  - 不安全的随机数

验证规则:
  security_scan:
    level: "high"  # high, medium, low

  检测方法:
    - Python: bandit
    - JavaScript: npm audit
    - 通用: git secrets

  阻塞条件:
    - high severity: warn
    - medium severity: log
    - low severity: info
```

---

## 非阻塞机制

Phase 2 检查结果**不阻塞**开发，仅记录警告：

```yaml
处理策略:
  warning:
    action: "记录并继续"
    notify: true
    block: false

  建议:
    - 记录到评审报告
    - 提供改进建议
    - 标记为技术债务 (可选)
```

---

## 验证流程

```yaml
输入:
  changed_files: [...]
  module: "backend" | "mobile" | "shared"

步骤:
  1. 确定模块类型
     - 选用对应的检查工具

  2. 运行质量检查
     - 测试覆盖率
     - 代码复杂度
     - 安全扫描

  3. 计算质量评分
     - 加权平均各指标
     - 生成 0-100 分

  4. 生成建议
     - 低于阈值的项
     - 改进建议
```

---

## 报告格式

```yaml
Phase 2 Review Report:
  summary:
    status: "warning"
    checked_at: "2026-01-18T10:30:00Z"
    quality_score: 78

  test_coverage:
    status: "warning"
    current: 78
    target: 85
    gap: 7
    recommendations:
      - "为 AuthManager.addUser() 添加测试"
      - "覆盖错误处理路径"

  code_complexity:
    status: "pass"
    average_complexity: 8
    max_complexity: 12
    files_with_high_complexity:
      - file: "lib/services/auth_service.dart"
        complexity: 12
        function: "authenticate"
        suggestion: "考虑拆分函数"

  security_scan:
    status: "pass"
    issues_found: 0

  overall_recommendations:
    - "测试覆盖率需提升 7% 以达到目标"
    - "auth_service.dart:authenticate 复杂度偏高，建议重构"

  blocking: false  # Phase 2 不阻塞
```

---

## 质量评分

```yaml
评分计算:
  test_coverage: 40%  # 权重
  code_complexity: 30%
  security_scan: 30%

  score =
    (coverage / target * 40) +
    ((1 - complexity_avg / threshold) * 30) +
    (security_pass * 30)

评级:
  90-100: Excellent
  80-89: Good
  70-79: Warning
  60-69: Needs Improvement
  < 60: Critical
```

---

## 工具配置

### Python (Backend)

```yaml
工具:
  coverage: pytest --cov=src --cov-report=term-missing
  complexity: radon cc src -a
  security: bandit -r src

配置文件:
  .coveragerc:
    [run]
    omit = [
      "*/tests/*",
      "*/test_*.py",
      "*/__pycache__/*"
    ]
```

### Flutter (Mobile)

```yaml
工具:
  coverage: flutter test --coverage
  complexity: dart analyze
  security: dart analyze --fatal-infos

配置文件:
  analysis_options.yaml:
    linter:
      rules:
        - prefer_const_constructors
        - avoid_print
```

---

## 示例

### 示例 1: 优秀质量

```yaml
结果:
  test_coverage: 92%
  code_complexity: avg 6
  security_scan: 0 issues

  quality_score: 94
  status: Excellent

  建议: 继续保持
```

### 示例 2: 需要改进

```yaml
结果:
  test_coverage: 72%
  code_complexity: avg 11
  security_scan: 1 low issue

  quality_score: 68
  status: Needs Improvement

  建议:
    - 提升测试覆盖率至 85%
    - 重构高复杂度函数
    - 修复低危安全问题
```

---

## 与 Phase 1 配合

```yaml
完整评审流程:
  1. Phase 1: 规范合规性 (阻塞)
     ↓ (通过)
  2. Phase 2: 代码质量 (不阻塞)
     ↓ (记录警告)
  3. 继续: B.3 架构同步

  如果 Phase 1 失败:
     → 阻塞，修复后重新检查

  如果 Phase 2 警告:
     → 记录，继续开发
     → 标记为技术债务 (可选)
```

---

**版本**: 1.0.0
**创建**: 2026-01-18
**相关**: [phase-b-developer](../SKILL.md) | [spec-compliance](./spec-compliance.md)
