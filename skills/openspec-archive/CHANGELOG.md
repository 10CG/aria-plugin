# Changelog

All notable changes to this skill will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-02-08

### Added

- **OpenSpec Archive Skill** - 归档已完成的 OpenSpec 变更
  - 自动验证 Spec 完成状态
  - 执行 openspec archive CLI 命令
  - **自动修正 CLI 归档位置 bug**
  - 清理空目录和验证最终结果

### Design Philosophy

```yaml
问题: OpenSpec CLI 的 archive 命令输出到错误位置
  CLI 输出: openspec/changes/archive/
  正确位置: openspec/archive/

解决: 本 Skill 自动检测并修正此问题
  Step 1: 执行 CLI 归档命令
  Step 2: 检测错误目录 openspec/changes/archive/
  Step 3: 移动到正确位置 openspec/archive/
  Step 4: 清理空目录
```

### Features

| 功能 | 说明 |
|------|------|
| 状态验证 | 检查 tasks.md 所有任务是否完成 |
| CLI 包装 | 封装 openspec archive 命令 |
| Bug 修正 | 自动修正归档目录位置 |
| 清理验证 | 清理空目录并验证结果 |
| Dry Run | 支持仅验证不执行模式 |

---

## 相关文档

- [SKILL.md](./SKILL.md) - 主文档
- [Phase D 规范](../../../standards/core/ten-step-cycle/phase-d-closure.md)
