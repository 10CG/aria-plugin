# Changelog

All notable changes to this skill will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (#95 archive-gate-runtime-reality, TG-2)

- **Step 1 C 分级证据闸**: 完成 gate 改走 `spec_complete.py --gate` tri-state 契约
  (`verdict: pass|warn|block`), 与 #134 `complete` 字段正交独立判定 — 高置信死代码声称
  (点名符号零生产语义引用) 即便 `complete=true` (tasks.md 全 `[x]`) 也 BLOCK 归档。
  `--archive-design-only` + reason 逃生舱扩展覆盖此新 BLOCK 组合 (显式回显被豁免原因,
  非静默通过)。
- **Step 2 warn frontmatter 覆盖层**: `verdict=warn` 时把 `unverified_claims` 真写入
  归档 proposal.md frontmatter (镜像既有 `archive_type`/`archived_reason` 写入模式);
  新增可选 `--ack-unverified <reason>` 交互模式人工确认记录 (`unverified_ack`/
  `unverified_ack_reason` 字段, 不影响 Step 7 是否建 issue)。
- **Step 7 D auto-issue (新增步骤, 单一 owner)**: 归档若有 deferred 未完成项或
  unverified_claims (无论是否 ack) → 自动创建 Forgejo tracker issue, 幂等去重
  (`<!-- archive-tracker:{spec_id} -->` marker search-before-create), headless 默认
  (无人 ack 也自动创建, 非 stall 非静默), 非-Forgejo 项目降级为打印待创建草稿,
  API 失败打印草稿+WARN 不静默、不 abort 归档本身。

### Changed

- 完成 gate 调用从 legacy 二元 `python3 spec_complete.py <spec_dir>` 改为统一
  `python3 spec_complete.py --gate <spec_dir>` (一次调用同时得到 `complete`/`complete_reason`
  与新 tri-state `verdict`; legacy 调用形式仍受 lib 支持，未被移除)。

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
