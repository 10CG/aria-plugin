# Brainstorm Skill 设计文档

> **版本**: 1.0.0
> **状态**: 设计中
> **作者**: Aria 项目组

---

## 一、架构设计

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Brainstorm Skill 架构                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                         输入层                                     │  │
│  │  用户意图 │ 模式选择 │ 参数配置                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│                              ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                       上下文加载层                                 │  │
│  │  项目配置 │ 现有决策 │ PRD/US │ OpenSpec                          │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│                              ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                       对话引擎层                                   │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐    │  │
│  │  │ 状态机      │  │ 引导器      │  │ 深度控制器              │    │  │
│  │  │ State       │──│ Guide       │──│ Depth                   │    │  │
│  │  │ Machine     │  │ Strategy    │  │ Controller              │    │  │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────┘    │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│                              ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                       决策记录层                                   │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐    │  │
│  │  │ 决策点      │  │ 约束管理    │  │ 方案对比器              │    │  │
│  │  │ Decision    │──│ Constraint  │──│ Solution                │    │  │
│  │  │ Recorder    │  │ Manager     │  │ Comparator              │    │  │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────┘    │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│                              ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                       输出同步层                                   │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐    │  │
│  │  │ 决策日志    │  │ OpenSpec    │  │ PRD 同步                │    │  │
│  │  │ Generator   │──│ Sync        │──│ (可选)                  │    │  │
│  │  │             │  │             │  │                         │    │  │
│  │  └─────────────┘  └─────────────┘  └─────────────────────────┘    │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 核心组件

#### 组件 1: 对话状态机

```typescript
interface ConversationState {
  // 当前状态
  current: 'INIT' | 'CLARIFY' | 'EXPLORE' | 'CONVERGE' | 'SUMMARY' | 'COMPLETE';

  // 状态元数据
  metadata: {
    round: number;           // 当前轮次
    maxRounds: number;       // 最大轮次
    startTime: number;       // 开始时间
    lastUpdate: number;      // 最后更新时间
  };

  // 对话指标
  metrics: {
    fuzziness: number;       // 模糊度 0-1
    coverage: number;        // 覆盖面 0-1
    consensus: number;       // 共识度 0-1
    depth: 'shallow' | 'adequate' | 'deep';
  };

  // 累积数据
  data: {
    terms: string[];         // 识别的术语
    constraints: Constraint[];  // 约束条件
    options: Option[];       // 讨论的选项
    decisions: Decision[];   // 已做出的决策
  };
}

interface Constraint {
  id: string;
  type: 'business' | 'technical' | 'team';
  category: string;
  description: string;
  source: 'user' | 'config' | 'inferred';
  verified: boolean;
}

interface Option {
  id: string;
  name: string;
  description: string;
  pros: string[];
  cons: string[];
  feasible: boolean;
  blockingReasons: string[];
  score?: number;
}

interface Decision {
  id: string;
  type: string;
  description: string;
  selectedOption: string;
  rejectedOptions: string[];
  rationale: string;
  assumptions: string[];
  risks: Risk[];
  reversible: boolean;
  expiry?: string;
}
```

#### 组件 2: 引导策略

```typescript
interface GuideStrategy {
  // 模式特定配置
  mode: 'problem' | 'requirements' | 'technical';

  // 问题模板
  templates: QuestionTemplate[];

  // 状态转换规则
  transitions: StateTransition[];

  // 收敛条件
  convergenceCriteria: ConvergenceCriterion[];
}

interface QuestionTemplate {
  state: ConversationState['current'];
  priority: number;
  condition: (context: ConversationContext) => boolean;
  template: string | QuestionGenerator;
  fallback?: string;
}

type QuestionGenerator = (context: ConversationContext) => string;

interface StateTransition {
  from: ConversationState['current'];
  to: ConversationState['current'];
  condition: (context: ConversationContext) => boolean;
  action?: (context: ConversationContext) => void;
}

interface ConvergenceCriterion {
  metric: keyof ConversationState['metrics'];
  threshold: number;
  operator: '>' | '<' | '>=' | '<=' | '==';
}
```

#### 组件 3: 深度控制器

```typescript
interface DepthController {
  // 计算当前对话深度
  calculateDepth(state: ConversationState): 'shallow' | 'adequate' | 'deep';

  // 判断是否应该收敛
  shouldConverge(state: ConversationState): boolean;

  // 判断是否应该继续探索
  shouldExplore(state: ConversationState): boolean;

  // 获取下一个建议动作
  getNextAction(state: ConversationState): 'continue' | 'converge' | 'force_converge';
}

// 深度计算逻辑
function calculateDepth(state: ConversationState): DepthLevel {
  const { fuzziness, coverage, consensus } = state.metrics;

  // 覆盖面不足 → shallow
  if (coverage < 0.5) return 'shallow';

  // 覆盖面足够，但共识度低 → 继续
  if (consensus < 0.5) return 'adequate';

  // 覆盖面好，共识度高 → deep，应该收敛
  if (coverage >= 0.7 && consensus >= 0.8) return 'deep';

  return 'adequate';
}
```

---

## 二、对话引导逻辑

### 2.1 状态机详细设计

```yaml
状态定义:

  INIT:
    入口条件: 对话开始
    动作:
      - 加载上下文
      - 选择引导模板
      - 输出开场问题
    出口条件: 用户首次响应
    下一状态: CLARIFY

  CLARIFY:
    入口条件: INIT 完成
    目标: 统一术语，明确概念
    动作:
      - 识别模糊术语
      - 请求定义
      - 建立术语表
    出口条件:
      - 关键术语已定义
      - 或达到最大问题数
    下一状态: EXPLORE

  EXPLORE:
    入口条件: CLARIFY 完成
    目标: 探索选项，分析约束
    动作:
      - 列举可能方案
      - 收集约束条件
      - 过滤不可行方案
    出口条件:
      - 可行方案已明确
      - 或达到最大问题数
    下一状态: CONVERGE

  CONVERGE:
    入口条件: EXPLORE 完成
    目标: 方案对比，做出选择
    动作:
      - 多维度方案对比
      - 风险评估
      - 引导决策
    出口条件:
      - 明确选择或达成共识
      - 或达到最大问题数
    下一状态: SUMMARY

  SUMMARY:
    入口条件: CONVERGE 完成
    目标: 总结决策，记录理由
    动作:
      - 总结讨论要点
      - 生成决策记录
      - 确认下一步
    出口条件: 用户确认
    下一状态: COMPLETE

  COMPLETE:
    入口条件: SUMMARY 确认
    动作:
      - 写入决策日志
      - 同步到相关文档
      - 提供后续建议
```

### 2.2 问题生成逻辑

```typescript
class QuestionGenerator {
  /**
   * 根据当前状态生成下一个问题
   */
  generate(state: ConversationState): Question {
    const strategy = this.getStrategy(state);
    const template = this.selectTemplate(strategy, state);

    return this.instantiate(template, state);
  }

  /**
   * 选择问题模板
   */
  private selectTemplate(
    strategy: GuideStrategy,
    state: ConversationState
  ): QuestionTemplate {
    // 获取当前状态的所有模板
    const candidates = strategy.templates.filter(
      t => t.state === state.current
    );

    // 按优先级排序
    candidates.sort((a, b) => b.priority - a.priority);

    // 检查条件，选择第一个满足条件的
    for (const template of candidates) {
      if (template.condition(state)) {
        return template;
      }
    }

    // 返回后备模板
    return candidates[candidates.length - 1] || this.getDefaultTemplate();
  }

  /**
   * 实例化模板
   */
  private instantiate(
    template: QuestionTemplate,
    state: ConversationState
  ): Question {
    if (typeof template.template === 'string') {
      return {
        text: this.fillPlaceholders(template.template, state),
        type: 'open',
        state: state.current
      };
    } else {
      return {
        text: template.template(state),
        type: 'open',
        state: state.current
      };
    }
  }
}
```

### 2.3 收敛检测

```typescript
class ConvergenceDetector {
  /**
   * 检测是否应该收敛
   */
  shouldConverge(state: ConversationState): ConvergenceResult {
    const results: ConvergenceCheck[] = [];

    // 检查 1: 共识度
    results.push(this.checkConsensus(state));

    // 检查 2: 覆盖面
    results.push(this.checkCoverage(state));

    // 检查 3: 轮次限制
    results.push(this.checkRoundLimit(state));

    // 检查 4: 用户明确选择
    results.push(this.checkExplicitChoice(state));

    // 综合判断
    return this.aggregate(results);
  }

  private checkConsensus(state: ConversationState): ConvergenceCheck {
    return {
      factor: 'consensus',
      ready: state.metrics.consensus >= 0.7,
      value: state.metrics.consensus,
      threshold: 0.7
    };
  }

  private checkCoverage(state: ConversationState): ConvergenceCheck {
    return {
      factor: 'coverage',
      ready: state.metrics.coverage >= 0.6,
      value: state.metrics.coverage,
      threshold: 0.6
    };
  }

  private checkRoundLimit(state: ConversationState): ConvergenceCheck {
    const ratio = state.metadata.round / state.metadata.maxRounds;
    return {
      factor: 'round_limit',
      ready: ratio >= 0.8,
      value: ratio,
      threshold: 0.8
    };
  }

  private checkExplicitChoice(state: ConversationState): ConvergenceCheck {
    // 检查最近的用户输入是否包含明确选择
    const lastUserInput = state.data.lastUserInput || '';
    const hasExplicitChoice = /我选择|决定用|就用|采用/i.test(lastUserInput);

    return {
      factor: 'explicit_choice',
      ready: hasExplicitChoice,
      value: hasExplicitChoice ? 1 : 0,
      threshold: 1
    };
  }
}
```

---

## 三、决策记录系统

### 3.1 决策点识别

```typescript
class DecisionRecognizer {
  /**
   * 从对话中识别决策点
   */
  recognize(
    userMessage: string,
    context: ConversationContext
  ): Decision | null {
    // 模式 1: 明确选择
    const explicitChoice = this.matchExplicitChoice(userMessage, context);
    if (explicitChoice) return explicitChoice;

    // 模式 2: 隐式选择
    const implicitChoice = this.matchImplicitChoice(userMessage, context);
    if (implicitChoice) return implicitChoice;

    // 模式 3: 约束导致的选择
    const constraintChoice = this.matchConstraintChoice(userMessage, context);
    if (constraintChoice) return constraintChoice;

    return null;
  }

  /**
   * 匹配明确选择
   * 示例: "我选择方案 A", "就用 FAISS"
   */
  private matchExplicitChoice(
    message: string,
    context: ConversationContext
  ): Decision | null {
    const patterns = [
      /我?选择?\s*(方案|选项)?\s*([A-Z]|\d+)/i,
      /决定?用\s*(.+)/i,
      /就用\s*(.+)/i,
      /采用\s*(.+)/i
    ];

    for (const pattern of patterns) {
      const match = message.match(pattern);
      if (match) {
        const optionId = this.resolveOptionId(match[2], context);
        if (optionId) {
          return this.buildDecision(optionId, context);
        }
      }
    }

    return null;
  }

  /**
   * 匹配隐式选择
   * 示例: "FAISS 更适合我们的场景"
   */
  private matchImplicitChoice(
    message: string,
    context: ConversationContext
  ): Decision | null {
    // 提取提到的选项
    const mentionedOptions = this.extractMentionedOptions(message, context);

    // 如果只提到一个可行选项，可能是隐式选择
    if (mentionedOptions.length === 1) {
      const option = mentionedOptions[0];
      if (option.feasible) {
        return this.buildDecisionWithConfirmation(
          option.id,
          "隐式选择，需要确认",
          context
        );
      }
    }

    return null;
  }

  /**
   * 匹配约束导致的选择
   * 示例: "预算不够，只能用免费的"
   */
  private matchConstraintChoice(
    message: string,
    context: ConversationContext
  ): Decision | null {
    // 识别约束引用
    const constraints = this.extractConstraintReferences(message, context);

    if (constraints.length > 0) {
      // 找出满足约束的选项
      const feasibleOptions = context.data.options.filter(opt =>
        this.checkConstraints(opt, constraints) && opt.feasible
      );

      // 如果只剩一个可行选项
      if (feasibleOptions.length === 1) {
        return this.buildDecision(
          feasibleOptions[0].id,
          `约束 ${constraints.map(c => c.id).join(', ')} 导致的唯一选择`,
          context
        );
      }
    }

    return null;
  }
}
```

### 3.2 决策日志生成

```typescript
class DecisionLogger {
  /**
   * 生成决策日志 Markdown
   */
  generate(decision: Decision, context: ConversationContext): string {
    const sections: string[] = [];

    // 标题
    sections.push(this.generateHeader(decision));

    // 背景
    sections.push(this.generateBackground(decision, context));

    // 约束条件
    sections.push(this.generateConstraints(decision, context));

    // 方案对比
    sections.push(this.generateOptions(decision, context));

    // 最终选择
    sections.push(this.generateSelection(decision));

    // 理由
    sections.push(this.generateRationale(decision));

    // 风险
    sections.push(this.generateRisks(decision));

    return sections.join('\n\n');
  }

  private generateHeader(decision: Decision): string {
    return `## 决策: ${decision.id} - ${decision.description}\n\n` +
           `> **日期**: ${new Date().toISOString().split('T')[0]}\n` +
           `> **模式**: ${decision.type}\n` +
           `> **状态**: Active\n` +
           `> **可撤销**: ${decision.reversible ? '是' : '否'}`;
  }

  private generateOptions(decision: Decision, context: ConversationContext): string {
    const options = context.data.options;
    const rows = options.map(opt => {
      const status = opt.id === decision.selectedOption ? '✅' :
                     decision.rejectedOptions.includes(opt.id) ? '❌' : '⚪';
      const blocking = opt.blockingReasons.length > 0 ?
                       ` (${opt.blockingReasons.join(', ')})` : '';
      return `| ${status} | ${opt.id} | ${opt.name} | ${opt.description || '-'} |` +
             (opt.feasible ? '' : ` | ❌ 不可行${blocking}`);
    }).join('\n');

    return `## 考虑的方案\n\n` +
           `| 状态 | ID | 名称 | 描述 |\n` +
           `|------|----|----|----|\n` +
           rows;
  }

  private generateRationale(decision: Decision): string {
    const rationale = decision.rationale
      .split('\n')
      .map(line => `${line.trim().startsWith('-') ? '' : '- '}${line}`)
      .join('\n');

    return `## 理由\n\n${rationale}`;
  }
}
```

---

## 四、约束管理系统

### 4.1 约束定义

```typescript
interface ConstraintSchema {
  // 约束类型
  type: 'business' | 'technical' | 'team';

  // 约束类别
  category: string;

  // 约束值类型
  valueType: 'enum' | 'range' | 'boolean' | 'string';

  // 枚举选项 (如果是 enum 类型)
  enumValues?: string[];

  // 范围 (如果是 range 类型)
  range?: {
    min: number;
    max: number;
    unit?: string;
  };

  // 是否是硬约束
  hard: boolean;

  // 默认值
  defaultValue?: any;

  // 验证函数
  validator?: (value: any) => boolean;
}

// 预定义约束库
const CONSTRAINT_LIBRARY: Record<string, ConstraintSchema> = {
  budget: {
    type: 'business',
    category: 'financial',
    valueType: 'range',
    range: { min: 0, max: 100000, unit: '$/月' },
    hard: true
  },
  timeline: {
    type: 'business',
    category: 'schedule',
    valueType: 'range',
    range: { min: 1, max: 52, unit: '周' },
    hard: true
  },
  deployment: {
    type: 'technical',
    category: 'infrastructure',
    valueType: 'enum',
    enumValues: ['cloud', 'on-premise', 'hybrid'],
    hard: true
  },
  compliance: {
    type: 'business',
    category: 'legal',
    valueType: 'enum',
    enumValues: ['GDPR', 'SOC2', 'HIPAA', 'ISO27001', '无'],
    hard: true
  }
};
```

### 4.2 约束验证

```typescript
class ConstraintValidator {
  /**
   * 验证方案是否满足约束
   */
  validate(
    option: Option,
    constraints: Constraint[]
  ): ValidationResult {
    const violations: Violation[] = [];

    for (const constraint of constraints) {
      const violation = this.checkConstraint(option, constraint);
      if (violation) {
        violations.push(violation);
      }
    }

    return {
      valid: violations.length === 0,
      violations,
      // 硬约束违反 = 不可行
      feasible: !violations.some(v => v.hard)
    };
  }

  private checkConstraint(
    option: Option,
    constraint: Constraint
  ): Violation | null {
    const schema = CONSTRAINT_LIBRARY[constraint.category];
    if (!schema) return null;

    // 根据约束类型检查
    switch (constraint.category) {
      case 'budget':
        return this.checkBudgetConstraint(option, constraint, schema);

      case 'deployment':
        return this.checkDeploymentConstraint(option, constraint, schema);

      case 'compliance':
        return this.checkComplianceConstraint(option, constraint, schema);

      default:
        return null;
    }
  }

  private checkBudgetConstraint(
    option: Option,
    constraint: Constraint,
    schema: ConstraintSchema
  ): Violation | null {
    // 从选项描述中提取成本信息
    const costMatch = option.description?.match(/\$(\d+)/);
    if (!costMatch) return null;

    const cost = parseInt(costMatch[1]);
    const limit = constraint.value;

    if (cost > limit) {
      return {
        constraint: constraint.id,
        reason: `成本 $${cost} 超过预算限制 $${limit}`,
        hard: constraint.hard
      };
    }

    return null;
  }

  private checkDeploymentConstraint(
    option: Option,
    constraint: Constraint,
    schema: ConstraintSchema
  ): Violation | null {
    const required = constraint.value;
    const optionText = option.description || '';

    // 检查选项是否支持所需的部署方式
    let supports = false;
    if (required === 'on-premise') {
      supports = /自建|本地|私有|on-prem/i.test(optionText);
    } else if (required === 'cloud') {
      supports = /云|托管|cloud|saas/i.test(optionText);
    }

    if (!supports) {
      return {
        constraint: constraint.id,
        reason: `方案不支持 ${required} 部署`,
        hard: constraint.hard
      };
    }

    return null;
  }
}
```

---

## 五、集成接口

### 5.1 与 state-scanner 集成

```typescript
interface StateScannerIntegration {
  /**
   * 推荐触发头脑风暴
   */
  recommendBrainstorm(scanResult: ScanResult): Recommendation | null {
    const triggers = [];

    // 触发条件 1: 模糊的需求意图
    if (this.isFuzzyIntent(scanResult)) {
      triggers.push({
        reason: '检测到模糊需求',
        mode: 'problem',
        priority: 'high'
      });
    }

    // 触发条件 2: 复杂功能无 OpenSpec
    if (this.isComplexWithoutSpec(scanResult)) {
      triggers.push({
        reason: '复杂功能缺少技术方案',
        mode: 'technical',
        priority: 'high'
      });
    }

    // 触发条件 3: PRD 细化
    if (this.needsPRDRefinement(scanResult)) {
      triggers.push({
        reason: 'PRD 需要细化为 User Stories',
        mode: 'requirements',
        priority: 'medium'
      });
    }

    if (triggers.length > 0) {
      return {
        action: 'brainstorm',
        triggers,
        suggestedMode: triggers[0].mode
      };
    }

    return null;
  }
}
```

### 5.2 与 spec-drafter 集成

```typescript
interface SpecDrafterIntegration {
  /**
   * 基于头脑风暴结果预填充 OpenSpec
   */
  prefillSpec(decisions: Decision[]): Partial<OpenSpec> {
    return {
      // 背景来自 problem 模式决策
      background: this.extractBackground(decisions),

      // 约束来自所有决策
      constraints: this.extractConstraints(decisions),

      // 技术方案来自 technical 模式决策
      technicalApproach: this.extractTechnicalApproach(decisions),

      // 决策引用
      decisions: decisions.map(d => ({
        id: d.id,
        link: `../../docs/decisions/${d.id}.md`
      }))
    };
  }

  private extractTechnicalApproach(decisions: Decision[]): string {
    const techDecisions = decisions.filter(d => d.type === 'technical');

    if (techDecisions.length === 0) return '';

    // 构建技术方案描述
    return techDecisions.map(d => {
      const sections = [];
      sections.push(`### ${d.description}`);
      sections.push(d.rationale);
      if (d.assumptions.length > 0) {
        sections.push('**假设条件**:');
        d.assumptions.forEach(a => sections.push(`- ${a}`));
      }
      return sections.join('\n');
    }).join('\n\n');
  }
}
```

---

## 六、测试策略

### 6.1 单元测试

```typescript
describe('QuestionGenerator', () => {
  describe('generate', () => {
    it('should generate CLARIFY question in INIT state', () => {
      const state = createMockState({ current: 'INIT' });
      const question = generator.generate(state);

      expect(question.state).toBe('CLARIFY');
      expect(question.text).toContain('澄清');
    });

    it('should use fallback template when no condition matches', () => {
      const state = createMockState({
        current: 'EXPLORE',
        data: { options: [] }
      });
      const question = generator.generate(state);

      expect(question.text).toBeTruthy();
    });
  });

  describe('shouldConverge', () => {
    it('should converge when consensus >= 0.7', () => {
      const state = createMockState({
        metrics: { consensus: 0.8, coverage: 0.6 }
      });

      const result = detector.shouldConverge(state);

      expect(result.ready).toBe(true);
      expect(result.primaryFactor).toBe('consensus');
    });

    it('should force converge at 80% of max rounds', () => {
      const state = createMockState({
        metadata: { round: 8, maxRounds: 10 },
        metrics: { consensus: 0.5, coverage: 0.5 }
      });

      const result = detector.shouldConverge(state);

      expect(result.ready).toBe(true);
      expect(result.primaryFactor).toBe('round_limit');
    });
  });
});
```

### 6.2 集成测试场景

```yaml
测试场景 1: Problem 模式完整流程
  初始状态: 用户输入模糊需求
  预期流程:
    1. INIT → CLARIFY: 请求澄清术语
    2. CLARIFY → EXPLORE: 识别核心问题
    3. EXPLORE → CONVERGE: 探索解决方案
    4. CONVERGE → SUMMARY: 收敛到方案
    5. SUMMARY → COMPLETE: 生成决策记录
  验证点:
    - 状态转换正确
    - 问题序列合理
    - 决策记录生成

测试场景 2: 约束过滤
  初始状态: 用户有预算约束 ($500/月)
  输入方案:
    - A: $200/月 (可行)
    - B: $800/月 (不可行)
    - C: 免费 (可行)
  预期结果:
    - B 被标记为不可行
    - A 和 C 进入对比
    - 推荐最匹配的方案

测试场景 3: 早期收敛
  初始状态: 用户明确选择
  输入: "就用 FAISS"
  预期结果:
    - 跳过 EXPLORE 和 CONVERGE
    - 直接进入 SUMMARY
    - 记录决策理由: "用户明确选择"

测试场景 4: 无法收敛
  初始状态: 多轮讨论无共识
  条件: 达到最大轮次
  预期结果:
    - 强制收敛
    - 列出所有可行方案
    - 建议暂停或降低期望
```

---

## 七、实现路线图

### Phase 1: 核心框架 (Week 1-2)

```yaml
Week 1:
  Day 1-2: 对话状态机
    - [ ] 实现状态定义
    - [ ] 实现状态转换逻辑
    - [ ] 单元测试

  Day 3-4: 问题生成器
    - [ ] 实现模板系统
    - [ ] 实现问题选择逻辑
    - [ ] 单元测试

  Day 5: 集成测试
    - [ ] 端到端测试框架
    - [ ] 基础场景测试

Week 2:
  Day 1-2: 深度控制器
    - [ ] 实现深度计算
    - [ ] 实现收敛检测
    - [ ] 单元测试

  Day 3-4: 决策记录
    - [ ] 实现决策识别
    - [ ] 实现 Markdown 生成
    - [ ] 单元测试

  Day 5: 集成与测试
    - [ ] 完整流程测试
    - [ ] 文档更新
```

### Phase 2: 约束管理 (Week 3)

```yaml
Day 1-2: 约束库
  - [ ] 定义预定义约束
  - [ ] 实现约束验证逻辑
  - [ ] 单元测试

Day 3-4: 约束应用
  - [ ] 方案过滤逻辑
  - [ ] 风险评估
  - [ ] 单元测试

Day 5: 集成测试
  - [ ] 约束场景测试
```

### Phase 3: 技能集成 (Week 4)

```yaml
Day 1-2: state-scanner 集成
  - [ ] 推荐触发逻辑
  - [ ] 模式选择
  - [ ] 测试

Day 3-4: spec-drafter 集成
  - [ ] 预填充逻辑
  - [ ] 决策引用
  - [ ] 测试

Day 5: 文档与示例
  - [ ] 使用文档
  - [ ] 示例对话
  - [ ] 最佳实践
```

---

**文档维护**: Aria 项目组
**更新日期**: 2026-02-05
**状态**: 设计中，待实施
