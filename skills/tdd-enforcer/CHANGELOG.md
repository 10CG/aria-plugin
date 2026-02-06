# Changelog

All notable changes to TDD Enforcer will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [2.0.0] - 2026-02-06

### Design Change

- **重大重构**: 从代码驱动设计重构为**文档驱动设计**
- 参考 Superpowers 的实现方式，AI 读取文档理解并执行 TDD 规则

### Removed

- 移除所有 Python 实现文件 (17+ 模块)
- 移除 `test_runners/` 目录
- 移除 `validators/` 目录
- 移除 `hooks/` 目录
- 移除 `tests/` 目录
- 移除以下文件:
  - `cache.py`
  - `config.py`
  - `diff_analyzer.py`
  - `state_persistence.py`
  - `state_tracker.py`

### Added

- **SKILL.md**: 重写为 355 行的文档驱动描述
- **EXAMPLES.md**: 添加使用示例文档
- **references/**: 新增参考文档目录
  - `strictness-levels.md`: 三级严格度详解
  - `red-state-detection.md`: RED 状态检测说明
  - `green-phase-check.md`: GREEN 阶段检查说明
  - `migration-guide.md`: v1.x 到 v2.0 迁移指南
- **examples/config-examples/**: 新增配置文件示例
  - `advisory.json`: 建议模式配置
  - `strict.json`: 严格模式配置
  - `superpowers.json`: 完整模式配置

### Changed

- **配置格式**:
  - `strict_mode` (boolean) → `strictness` (enum: advisory|strict|superpowers)
  - `test_runners` → `language_settings`
  - 新增 `green_phase_limits` 配置节
  - 新增 `golden_testing_detection` 配置节
  - 新增 `state_persistence` 配置节

### Updated

- **Python 示例**: 更新配置和 README 以匹配 v2.0 格式
- **JavaScript 示例**: 更新配置和 README 以匹配 v2.0 格式
- **Dart 示例**: 更新配置和 README 以匹配 v2.0 格式
- **tdd-config-schema.json**: 更新 schema 以匹配新配置格式

### Design Philosophy

```yaml
v1.x (错误):
  问题: 把 Skill 当作 Python 包来开发
  - 创建大量 Python 模块
  - 实现复杂的类继承结构
  - 编写单元测试
  根本问题: Claude Code 不会导入执行这些 Python 代码

v2.0 (正确):
  方案: 参考 Superpowers，文档驱动设计
  - SKILL.md 描述工作流
  - AI 读取并理解流程
  - AI 按流程执行检查
  优势: 符合 Agent Skills 设计原则
```

### Migration

从 v1.x 迁移到 v2.0:

1. 备份现有配置
2. 更新配置文件字段名
3. 删除旧的 Python 实现文件
4. 使用新的文档驱动方式

详见: [references/migration-guide.md](references/migration-guide.md)

---

## [1.0.0] - 2025-12-20

### Added

- 初始版本发布
- Python/JavaScript/Dart 测试状态检测
- RED/GREEN 状态追踪
- 配置系统
- Hook 集成
