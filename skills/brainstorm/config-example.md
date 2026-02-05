# Brainstorm Skill 配置示例

## 项目级配置

将以下配置添加到项目的 `.claude/aria.local.md` 文件中：

```yaml
brainstorm:
  # ============================================================================
  # 基础配置
  # ============================================================================

  # 是否启用头脑风暴功能
  enabled: true

  # 触发模式:
  # - auto: 根据复杂度和模糊度自动触发 (推荐)
  # - always: 总是触发
  # - manual: 仅手动触发
  trigger_mode: auto

  # ============================================================================
  # 自动触发阈值
  # ============================================================================
  auto_trigger:
    # 模糊度阈值 (0-1)
    # 0 = 完全清晰，1 = 完全模糊
    # 超过此值时自动触发 problem 模式
    fuzziness_threshold: 0.6

    # 复杂度阈值
    # Level1 = 简单修复，不需要头脑风暴
    # Level2 = 中等复杂，建议头脑风暴
    # Level3 = 高复杂，必须头脑风暴
    complexity_threshold: Level2

  # ============================================================================
  # 对话配置
  # ============================================================================
  conversation:
    # 各模式最大对话轮次
    max_rounds:
      problem: 10       # 问题空间探索
      requirements: 15  # 需求分解
      technical: 8      # 技术方案设计

    # 收敛阈值
    # 共识度超过此值时可以进入收敛阶段
    convergence_threshold: 0.7

    # 是否在达到最大轮次时强制收敛
    force_converge: true

    # 对话风格
    style:
      # 是否使用表情符号
      use_emoji: false

      # 问题详细程度: brief | normal | detailed
      verbosity: normal

  # ============================================================================
  # 输出配置
  # ============================================================================
  output:
    # 是否保存决策日志
    save_decisions: true

    # 是否保存完整对话记录
    save_conversation: false

    # 决策日志保存目录
    decision_dir: docs/decisions/

    # 是否自动同步到 OpenSpec
    auto_sync_openspec: true

    # 是否自动生成 PRD 草案
    auto_generate_prd: false

  # ============================================================================
  # 默认约束
  # ============================================================================
  default_constraints:
    # 业务约束
    business:
      budget:
        value: "$1000/月"
        hard: true
        description: "项目月度预算限制"

      timeline:
        value: "8周"
        hard: false
        description: "预期开发周期"

    # 技术约束
    technical:
      deployment:
        value: "on-premise"
        hard: true
        description: "私有化部署"

      tech_stack:
        value: ["TypeScript", "React", "Node.js"]
        hard: false
        description: "首选技术栈"

    # 合规约束
    compliance:
      data_localization:
        value: true
        hard: true
        description: "数据不得出境"

      gdpr:
        value: false
        hard: false
        description: "GDPR 合规要求"

  # ============================================================================
  # 模式特定配置
  # ============================================================================
  problem:
    # 是否自动建议创建 PRD
    suggest_prd: true

    # 问题澄清的关键词列表
    clarification_keywords:
      - "什么"
      - "如何"
      - "为什么"
      - "哪个"
      - "还是"

  requirements:
    # User Story 模板路径
    story_template: "standards/templates/user-story-template.md"

    # 默认优先级规则
    default_priority_rules:
      - rule: "用户核心流程 > 辅助功能"
        weight: 3
      - rule: "技术依赖优先"
        weight: 2
      - rule: "快速产出优先"
        weight: 1

  technical:
    # 技术方案评估维度
    evaluation_criteria:
      - name: "成本"
        weight: 3
      - name: "复杂度"
        weight: 2
      - name: "可维护性"
        weight: 2
      - name: "性能"
        weight: 2
      - name: "团队能力"
        weight: 1

  # ============================================================================
  # 集成配置
  # ============================================================================
  integration:
    # 与 state-scanner 集成
    state_scanner:
      enabled: true
      # 在状态报告中显示头脑风暴建议
      show_recommendation: true

    # 与 spec-drafter 集成
    spec_drafter:
      enabled: true
      # 自动填充 OpenSpec
      auto_prefill: true
      # 引用决策记录
      reference_decisions: true

    # 与 requirements-validator 集成
    requirements_validator:
      enabled: true
      # 验证决策一致性
      check_consistency: true
```

---

## 会话级配置

### 方式 1: 通过参数传递

```bash
# 指定模式
/brainstorm problem "添加新功能"

# 指定模糊度
/brainstorm --fuzziness high

# 指定最大轮次
/brainstorm --max-rounds 15

# 指定约束
/brainstorm --constraints budget:$500,deployment:private

# 组合使用
/brainstorm technical "数据库选型" --max-rounds 10 --constraints budget:$500
```

### 方式 2: 通过配置文件

创建 `.claude/brainstorm-session.md`:

```yaml
# 会话特定配置
mode: technical
max_rounds: 10
constraints:
  - type: budget
    value: "$500/月"
    hard: true
  - type: deployment
    value: "on-premise"
    hard: true

context:
  related_prd: "docs/requirements/prd-v1.md"
  related_stories:
    - "docs/requirements/user-stories/US-001.md"
  related_decisions:
    - "docs/decisions/technical-001.md"
```

---

## 环境变量

可以通过环境变量覆盖部分配置：

```bash
# 禁用头脑风暴
export ARIA_BRAINSTORM_ENABLED=false

# 设置触发模式
export ARIA_BRAINSTORM_TRIGGER_MODE=manual

# 设置决策日志目录
export ARIA_BRAINSTORM_DECISION_DIR=/path/to/decisions
```

---

## 配置验证

Brainstorm skill 启动时会验证配置：

```yaml
验证检查:
  - [ ] decision_dir 目录可写
  - [ ] default_constraints 格式正确
  - [ ] max_rounds 为正整数
  - [ ] threshold 在 0-1 范围内
  - [ ] 模板文件存在 (如果指定)

错误处理:
  - 配置错误 → 使用默认值并警告
  - 目录不可写 → 创建目录或使用临时目录
  - 模板缺失 → 使用内置模板
```

---

## 示例配置

### 小型项目配置

```yaml
brainstorm:
  enabled: true
  trigger_mode: auto
  auto_trigger:
    fuzziness_threshold: 0.7  # 较宽松
    complexity_threshold: Level3  # 只在高复杂时触发
  conversation:
    max_rounds:
      problem: 5
      requirements: 8
      technical: 5
  output:
    save_decisions: true
    save_conversation: false
    decision_dir: .decisions/
```

### 企业级项目配置

```yaml
brainstorm:
  enabled: true
  trigger_mode: auto
  auto_trigger:
    fuzziness_threshold: 0.5  # 较严格
    complexity_threshold: Level2
  conversation:
    max_rounds:
      problem: 10
      requirements: 15
      technical: 10
    convergence_threshold: 0.8
  output:
    save_decisions: true
    save_conversation: true  # 保留完整记录
    decision_dir: docs/decisions/
    auto_sync_openspec: true
  default_constraints:
    compliance:
      audit_required: true
      documentation_level: "full"
```

---

**配置更新**: 2026-02-05
**版本**: 1.0.0
