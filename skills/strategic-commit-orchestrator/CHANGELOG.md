# Changelog - strategic-commit-orchestrator

All notable changes to the strategic-commit-orchestrator skill will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.2.0] - 2026-01-01

### 🎉 Added - 全项目变更支持 (类型E)

**核心新增**:
- ✅ 新增类型E：全项目变更（主项目 + 子模块同时变更）
- ✅ 新增 Phase 0：全项目状态扫描
- ✅ 自动检测并编排主项目与所有子模块的分组提交
- ✅ 自动更新子模块引用

**新增文档**:
1. **WORKFLOW_TYPE_E.md** - 类型E全项目变更流程
   - Phase 0: 全项目状态扫描
   - 子模块循环提交
   - 主项目提交 + 引用更新
   - 验证与汇总报告

2. **SUBMODULE_GUIDE.md** - 子模块处理指南
   - 子模块扫描命令参考
   - 变更地图结构定义
   - 执行策略配置
   - 常见问题与解决方案

**更新内容**:
- SKILL.md: 更新决策树、场景匹配表、变更类型表
- CHANGE_TYPES.md: 添加类型E识别规则
- WORKFLOW_CORE.md: 添加 Phase 0 概述

**使用场景**:
- OpenSpec 变更涉及主项目 Skills + standards 规范
- 大型功能开发涉及多个子模块 + 主项目文档
- 版本升级涉及所有模块配置调整

**工作流示例**:
```yaml
场景: evolve-ai-ddd-system OpenSpec 变更

主项目提交: 5个分组
  - G1: requirements-validator + requirements-sync Skills
  - G2: forgejo-sync Skill
  - G3: state-scanner + workflow-runner 扩展
  - G4: CLAUDE.md 配置
  - G5: UPM + 子模块引用

子模块提交: standards 6个分组
  - G1: Aria 品牌
  - G2: UPM Requirements 扩展
  - G3: Requirements Skills 规范
  - G4: state-scanner 规范扩展
  - G5: 组合工作流
  - G6: Summaries + OpenSpec 归档

结果: 一次 skill 调用完成 12 个提交
```

---

## [2.1.0] - 2025-12-09

### 🔧 Changed - 变更类型识别优化

**优化目标**:
- ✅ 明确区分子模块变更 vs 主项目基础设施变更
- ✅ 修正Phase/Cycle来源的误解问题
- ✅ 添加完整的3种变更类型工作流示例

**核心改进**:
1. **新增"变更类型识别"章节**:
   - 类型A: 子模块功能变更（需读取UPM，使用实际Phase/Cycle）
   - 类型B: 主项目基础设施变更（使用逻辑Phase/Cycle）
   - 类型C: 跨模块协同变更（读取主模块UPM）

2. **步骤1.0优化**:
   - 标题改为"（子模块变更时需要）"
   - 明确适用条件：仅子模块变更需要
   - 主项目变更无需执行此步骤

3. **模块识别策略增强**:
   - ELSE分支添加主项目路径识别
   - standards/**, .claude/skills/**, scripts/** 等
   - 明确标记为类型B，跳过UPM读取

4. **增强6.3: Phase/Cycle来源决策**:
   - 明确三种变更类型的Phase/Cycle来源
   - 实际Phase（从UPM读取）vs 逻辑Phase（描述工作阶段）
   - 提供清晰的决策规则

5. **完整工作流示例重写**:
   - 示例1: 子模块功能开发（Mobile图表页面）
   - 示例2: 主项目标准文档更新（UPM路径修复）
   - 示例3: Skills开发/升级（Skills v2.0.0）
   - 示例4: 跨模块协同开发（Backend+Mobile API）

**预期效果**:
- 消除"主项目变更也要读子模块UPM"的误解
- 明确逻辑Phase/Cycle的使用场景和含义
- 提供端到端的参考示例

**相关文档**:
- 问题分析: `.claude/docs/STRATEGIC_COMMIT_ORCHESTRATOR_OPTIMIZATION.md`

---

## [2.0.0] - 2025-12-09

### 🎉 Added - AI-DDD v3.0.0通用架构支持

**核心升级**:
- ✅ 从 mobile-specific 升级到 universal (支持所有模块)
- ✅ 基于AI-DDD v3.0.0核心标准
- ✅ 支持 mobile/backend/frontend/shared 模块

**主要变更**:
1. **文档引用升级**:
   - 从: `mobile-ai-ddd-progress-management-system.md` v2.3.0
   - 到: `ai-ddd-progress-management-core.md` v1.0.0

2. **模块识别机制**:
   - 自动检测变更文件所属模块
   - 读取对应模块的UPM文档
   - 应用模块特定的Subagent映射规则

3. **UPM路径模板化**:
   - 通用路径: `{module}/project-planning/unified-progress-management.md`
   - 支持动态模块识别

4. **Subagent映射增强**:
   - 读取模块扩展文档中的映射规则
   - 支持模块特定的优先级
   - Backend/Mobile不同的Subagent偏好

5. **Phase/Cycle自动传递**:
   - 从UPMv2-STATE读取module字段
   - 传递给commit-msg-generator v2.0
   - 生成增强的Context标记

**向后兼容**:
- ✅ 继续支持 mobile v2.3.0 路径
- ✅ 自动判断使用 v2.3.0 还是 v3.0.0
- ✅ 无需修改现有使用方式

**新特性**:
- 🎨 多模块并行提交支持
- 🎯 模块特定质量门禁
- 📊 更丰富的Context信息
- 🔗 更好的可追溯性

**参考文档**:
- [AI-DDD v3.0.0架构设计](../../docs/analysis/ai-ddd-universal-progress-management-adr.md)
- [Skills组合设计方案](../../.claude/docs/SKILLS_COMBINATION_DESIGN.md)
- [核心标准文档](../../standards/core/ai-ddd-progress-management-core.md)
- [Backend扩展](../../standards/extensions/backend-ai-ddd-extension.md)
- [Mobile扩展](../../standards/extensions/mobile-ai-ddd-extension.md)

---

## [1.0.0] - 2025-12-09

### 🚀 Initial Release - 初始版本

**核心功能**:
- ✅ 建立战略提交编排框架
- ✅ 智能分组提交规划
- ✅ Subagent并行编排
- ✅ 项目进度感知能力
- ✅ 多模块变更协调
- ✅ 阶段性成果提交支持

**Tech-Lead级别能力**:
- 分析项目变更并设计分组提交计划
- 智能分配subagent并行执行
- 协调跨模块提交
- 感知项目进度状态

**工具权限**:
- Bash: 执行git和系统命令
- Read: 读取文件和UPM文档
- Grep: 搜索和分析代码
- Task: 启动subagent执行任务
- Glob: 查找文件模式

**依赖**:
- commit-msg-generator: 生成规范的commit消息

---

*本Skill由 tech-lead 设计，遵循AI-DDD进度管理体系和项目规范标准。*
