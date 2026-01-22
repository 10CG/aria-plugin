# 故障处理与最佳实践

> **版本**: 2.1.0
> **职责**: 最佳实践、故障处理、检查清单、参考资源

本文档帮助你解决使用过程中遇到的问题，并提供最佳实践指导。

**📚 文档导航**:
- **入口文档** → [SKILL.md](./SKILL.md)
- **变更类型识别** → [CHANGE_TYPES.md](./CHANGE_TYPES.md)
- **工作流程** → [WORKFLOW_CORE.md](./WORKFLOW_CORE.md) + WORKFLOW_TYPE_*.md
- **故障处理（本文档）** → 您正在阅读

---

## 最佳实践

### 实践1: 合理分组原则

```yaml
✅ 好的分组:
  - 职责单一: 每个分组解决一个明确问题
  - 大小适中: 3-8个文件为宜
  - 逻辑完整: 分组内文件形成完整单元
  - 依赖清晰: 分组间依赖关系明确

❌ 不好的分组:
  - 过大分组: 20+文件混在一起
  - 职责混杂: 功能代码+测试+文档混合
  - 依赖混乱: 循环依赖或依赖不明
  - 过度拆分: 每个文件单独提交
```

### 实践2: Agent选择策略

```yaml
✅ 正确选择:
  - 文档专业性 → knowledge-manager
  - 技术领域匹配 → 对应技术栈agent
  - 测试专业性 → qa-engineer
  - 跨领域决策 → tech-lead

❌ 错误选择:
  - 所有都用general-purpose (缺少专业性)
  - 文档用backend-architect (职责不匹配)
  - 测试用mobile-developer (专业性偏差)
```

### 实践3: 并行策略选择

```yaml
✅ 适合并行:
  - 不同端的独立功能
  - 不同模块的文档
  - 不相关的Skill更新

❌ 不适合并行:
  - 同一文件的多次修改
  - 有明确依赖关系的变更
  - Submodule更新 + 主项目引用
```

### 实践4: 提交粒度控制

```yaml
提交粒度指导:

  太粗 (需要拆分):
    - 单次提交>50个文件
    - 混合多种变更类型
    - 跨越多个功能模块

  合适 (推荐):
    - 单次提交3-15个文件
    - 单一变更类型
    - 聚焦单一功能或模块

  太细 (需要合并):
    - 每个文件单独提交
    - 功能实现被过度拆分
    - 提交历史过于碎片化
```

### 实践5: 消息质量保证

```yaml
高质量提交消息特征:

  ✅ 标题清晰:
    - type准确 (feat/fix/docs等)
    - scope明确 (backend/mobile/shared等)
    - 描述简洁 (<50字符)
    - 双语完整

  ✅ 正文完整:
    - 说明"为什么"而非"做了什么"
    - 列出主要变更点
    - 包含Agent和Context标记
    - 关联任务和文档

  ✅ 上下文丰富:
    - Phase/Cycle信息
    - 任务ID关联
    - 里程碑关系
    - 参考文档链接
```

---

## 故障处理

### 故障1: Git冲突

```yaml
症状:
  - 多个Task同时修改同一文件
  - Merge冲突错误

解决:
  1. 暂停所有并行Task
  2. git status 确认冲突文件
  3. 手动解决冲突
  4. git add 和 git commit
  5. 重新启动剩余Task

预防:
  - 分组时避免同一文件在多组中
  - 串行提交有依赖的变更
  - 使用更细粒度的分组
```

### 故障2: Task执行失败

```yaml
症状:
  - Subagent执行超时
  - 提交消息生成失败
  - Git命令错误

解决:
  1. 使用AgentOutputTool查看Task输出
  2. 识别失败原因
  3. 修复问题（如暂存文件、修正路径）
  4. 手动完成失败Task的提交
  5. 继续后续Task

预防:
  - 提交前确保文件已暂存
  - 验证分支状态
  - 提供清晰的Task prompt
```

### 故障3: 消息格式不符合规范

```yaml
症状:
  - Git hook拒绝提交
  - 缺少双语描述
  - type或scope错误

解决:
  1. 查看Git hook错误信息
  2. 修正提交消息格式
  3. git commit --amend 修改消息
  4. 重新提交

预防:
  - 调用commit-msg-generator生成规范消息
  - 严格遵循git-rule.mdc规范
  - 添加消息验证步骤
```

### 故障4: 分组策略不合理

```yaml
症状:
  - 依赖关系导致提交失败
  - 分组过大或过小
  - 并行冲突

解决:
  1. 重新分析变更文件
  2. 调整分组策略
  3. 修正依赖关系
  4. 重新执行提交

预防:
  - 分组前仔细分析依赖
  - 遵循最佳实践
  - 优先使用串行或阶段并行
```

### 故障5: UPM文档找不到

```yaml
症状:
  - get_upm_path() 返回空值
  - 无法读取Phase/Cycle信息

解决:
  1. 确认变更类型是否正确
  2. 类型C无需UPM，使用逻辑Phase
  3. 检查UPM文件路径是否存在
  4. 手动指定Phase/Cycle

预防:
  - 先识别变更类型再读取UPM
  - 类型C跳过UPM读取
  - 确认模块UPM已创建
```

---

## 检查清单

### 执行前检查

```yaml
□ 变更类型识别:
  □ 确定变更类型 (A/B/C/D)
  □ 加载对应 WORKFLOW_TYPE_*.md

□ 项目状态确认 (类型A/B/D):
  □ 已读取对应UPM文档
  □ 识别当前 Phase/Cycle
  □ 了解活跃任务和目标

□ 项目状态确认 (类型C):
  □ 跳过UPM读取
  □ 确定逻辑Phase/Cycle

□ 变更分析完成:
  □ git status 确认所有变更
  □ 识别文件类型和模块
  □ 分析依赖关系

□ 分组策略设计:
  □ 分组逻辑清晰
  □ 依赖关系正确
  □ 并行策略可行

□ Subagent分配合理:
  □ Agent能力匹配
  □ 职责边界清晰
  □ 专业性保证

□ 提交消息准备:
  □ 符合git-rule.mdc规范
  □ 包含Agent和Context标记
  □ 关联项目进度
```

### 执行后验证

```yaml
□ 提交成功验证:
  □ git log 确认所有提交
  □ 提交消息格式正确
  □ 分支状态正常

□ 质量验证:
  □ 提交粒度合理
  □ 消息描述清晰
  □ 上下文信息完整

□ 进度同步:
  □ 更新 unified-progress-management.md (如需要)
  □ 记录完成的任务
  □ 更新验证队列
```

---

## 参考资源

### 核心规范文档
- **Git提交规范**: `standards/conventions/git-commit.md`
- **UPM接口规范**: `standards/core/upm/unified-progress-management-spec.md`
- **AI-DDD核心标准**: `standards/core/progress-management/ai-ddd-progress-management-core.md`
- **Conventional Commits**: https://www.conventionalcommits.org/

### 模块扩展标准
- **Mobile扩展**: `standards/extensions/mobile-ai-ddd-extension.md`
- **Backend扩展**: `standards/extensions/backend-ai-ddd-extension.md`

### 项目UPM文档
- **主模块UPM**: `docs/project-planning/unified-progress-management.md`
- **Mobile UPM**: `mobile/docs/project-planning/unified-progress-management.md`
- **Backend UPM**: `backend/project-planning/unified-progress-management.md`

### 依赖Skill
- **commit-msg-generator**: `.claude/skills/commit-msg-generator/SKILL.md`

### 相关Skill
- **architecture-doc-updater**: `.claude/skills/architecture-doc-updater/SKILL.md`
- **api-doc-generator**: `.claude/skills/api-doc-generator/SKILL.md`
- **flutter-test-generator**: `.claude/skills/flutter-test-generator/SKILL.md`

---

*本文档是 strategic-commit-orchestrator v2.1.0 的故障处理与最佳实践指南。*
