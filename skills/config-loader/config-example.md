# .aria/config.json 配置示例

> **用途**: 本文件是 `.aria/config.json` 的完整配置参考，展示所有可用字段及典型用法。
> **实际配置文件路径**: `.aria/config.json`（从 `config.template.json` 复制后自定义）

---

## 最小配置（推荐新项目起点）

```json
{
  "version": "1.0",
  "workflow": {
    "auto_proceed": false
  }
}
```

缺失字段均由 `DEFAULTS.json` 提供默认值，无需显式写出。

---

## 完整配置示例

```json
{
  "version": "1.0",

  "workflow": {
    "auto_proceed": false
  },

  "state_scanner": {
    "confidence_threshold": 90,
    "auto_execute_enabled": false,
    "auto_execute_rules": ["commit_only", "quick_fix", "doc_only"],
    "audit_log_path": ".aria/audit.log"
  },

  "tdd": {
    "strictness": "advisory"
  },

  "benchmarks": {
    "require_before_merge": true,
    "skill_change_block_mode": "warn"
  },

  "experiments": {
    "agent_team_audit": false,
    "agent_team_audit_points": ["pre_merge"]
  },

  "audit": {
    "enabled": false,
    "mode": "adaptive",
    "max_rounds": 5,

    "convergence_criteria": {
      "conclusion_match": true,
      "unanimous_pass": true
    },

    "adaptive_rules": {
      "level_1": "off",
      "level_2": "convergence",
      "level_3": "challenge"
    },

    "mid_implementation": {
      "trigger": "task_progress",
      "threshold": 50,
      "unit": "percent_tasks_completed"
    },

    "checkpoints": {
      "post_brainstorm": "off",
      "post_spec": "off",
      "post_planning": "off",
      "mid_implementation": "off",
      "post_implementation": "off",
      "pre_merge": "off",
      "post_closure": "off"
    },

    "teams": {
      "post_brainstorm": {
        "convergence": [
          "tech-lead",
          "backend-architect",
          "knowledge-manager"
        ],
        "discussion": [
          "tech-lead"
        ],
        "challenge": [
          "backend-architect",
          "qa-engineer",
          "knowledge-manager"
        ]
      },

      "post_spec": {
        "convergence": [
          "tech-lead",
          "backend-architect",
          "qa-engineer",
          "knowledge-manager",
          "context-manager",
          "api-documenter",
          "ui-ux-designer"
        ],
        "discussion": [
          "tech-lead",
          "backend-architect",
          "api-documenter"
        ],
        "challenge": [
          "qa-engineer",
          "knowledge-manager",
          "context-manager",
          "ai-engineer",
          "ui-ux-designer"
        ]
      },

      "post_planning": {
        "convergence": [
          "tech-lead",
          "qa-engineer",
          "context-manager"
        ],
        "discussion": [
          "tech-lead",
          "context-manager"
        ],
        "challenge": [
          "qa-engineer",
          "backend-architect"
        ]
      },

      "mid_implementation": {
        "convergence": [
          "tech-lead",
          "code-reviewer"
        ],
        "discussion": [
          "code-reviewer"
        ],
        "challenge": [
          "tech-lead"
        ]
      },

      "post_implementation": {
        "convergence": [
          "code-reviewer",
          "backend-architect",
          "qa-engineer",
          "ai-engineer",
          "api-documenter",
          "mobile-developer"
        ],
        "discussion": [
          "code-reviewer",
          "backend-architect",
          "api-documenter"
        ],
        "challenge": [
          "qa-engineer",
          "tech-lead",
          "ai-engineer",
          "mobile-developer"
        ]
      },

      "pre_merge": {
        "convergence": [
          "code-reviewer",
          "qa-engineer",
          "tech-lead",
          "knowledge-manager",
          "mobile-developer",
          "api-documenter",
          "ui-ux-designer"
        ],
        "discussion": [
          "code-reviewer",
          "qa-engineer",
          "api-documenter"
        ],
        "challenge": [
          "tech-lead",
          "knowledge-manager",
          "mobile-developer",
          "ui-ux-designer"
        ]
      },

      "post_closure": {
        "convergence": [
          "tech-lead",
          "knowledge-manager",
          "context-manager"
        ],
        "discussion": [
          "tech-lead",
          "context-manager"
        ],
        "challenge": [
          "knowledge-manager",
          "qa-engineer"
        ]
      }
    }
  }
}
```

---

## 字段说明

### audit.enabled

总开关，默认 `false`。设为 `true` 后，audit-engine 在检查点被调用时才会实际执行。

### audit.mode

| 值 | 行为 |
|----|------|
| `adaptive` | 根据 `adaptive_rules` 按 OpenSpec Level 推导每个检查点的模式 |
| `convergence` | 所有检查点强制使用 convergence 模式 |
| `challenge` | 所有检查点强制使用 challenge 模式 |
| `manual` | 仅按 `checkpoints` 显式配置执行，不推导 |

**优先级**: `checkpoints` 显式值 > `adaptive_rules` 推导值 > 默认 `"off"`

### audit.max_rounds

最大审计轮次，防止无限循环。范围 `[1, 20]`，默认 `5`。

耗尽且未收敛时触发降级策略（展示摘要 + 三路径选择）。

### audit.convergence_criteria

收敛判定双重验证条件：

| 字段 | 类型 | 说明 |
|------|------|------|
| `conclusion_match` | boolean | 相邻两轮结论四元组集合必须相等 |
| `unanimous_pass` | boolean | 全员（convergence 模式）或无 unresolved 反对意见（challenge 模式）必须通过 |

两个条件同时为 `true` 时才判定收敛。通常不需要修改此字段。

### audit.adaptive_rules

`mode=adaptive` 时，按 OpenSpec Level 自动推导检查点模式：

| Level | 含义 | 默认模式 |
|-------|------|---------|
| `level_1` | Skip 级别（简单修复） | `"off"` — 不触发审计 |
| `level_2` | Minimal（`proposal.md`） | `"convergence"` — 全员讨论收敛 |
| `level_3` | Full（`proposal.md` + `tasks.md`） | `"challenge"` — 对抗讨论收敛 |

### audit.mid_implementation

`mid_implementation` 检查点的条件触发配置（非运行时 AI 判断，确定性触发）：

| 字段 | 说明 |
|------|------|
| `trigger` | 触发类型，目前固定为 `"task_progress"` |
| `threshold` | 触发阈值（百分比），默认 `50` |
| `unit` | 单位，固定为 `"percent_tasks_completed"` |

当已完成任务数 >= 总任务数 × threshold% 时，phase-b-developer 在每个任务完成后检查并触发。

### audit.checkpoints

各检查点的审计模式显式配置。优先级高于 `adaptive_rules` 推导。

| 检查点 | 阶段 | 侧重 | 调用方 |
|--------|------|------|--------|
| `post_brainstorm` | A | 决策验证 | brainstorm |
| `post_spec` | A.1 | 决策验证 | phase-a-planner |
| `post_planning` | A.2 | 质量保障 | task-planner |
| `mid_implementation` | B.2 | 质量保障 | phase-b-developer（条件触发） |
| `post_implementation` | B.2 | 质量保障 | phase-b-developer |
| `pre_merge` | C.2 | 共识构建 | phase-c-integrator |
| `post_closure` | D.1 | 经验积累 | phase-d-closer |

有效值：`"off"` / `"convergence"` / `"challenge"`

**post_closure 限制**: 代码已合并后无法回退，此检查点强制 convergence 模式 + max_rounds=1，忽略显式 challenge 配置。

### audit.teams

各检查点的 Agent 分组配置。每个检查点包含三个分组：

| 分组 | 用途 |
|------|------|
| `convergence` | convergence 模式下参与全员讨论的 Agent 列表 |
| `discussion` | challenge 模式下负责提案的讨论组 |
| `challenge` | challenge 模式下负责质疑的挑战组 |

**Agent 分配原则**（各检查点 5 个扩展 Agent 的适用说明）:

| Agent | 适用检查点 | 职责 |
|-------|-----------|------|
| `ai-engineer` | post_spec、post_implementation | AI 实现方案审查、AI 集成风险识别 |
| `context-manager` | post_spec、post_planning、post_closure | 上下文一致性核查、知识归档质量 |
| `mobile-developer` | post_implementation、pre_merge | 移动端实现审查、跨平台兼容性 |
| `api-documenter` | post_spec、post_implementation、pre_merge | API 设计审查、文档完整性验证 |
| `ui-ux-designer` | post_spec、pre_merge | UX 决策合理性、UI 变更审查 |

非适用检查点（如 `post_brainstorm`、`mid_implementation`、`post_closure`）保持最小团队配置，避免 Token 消耗过高。

---

## 典型场景配置

### 场景 A：仅启用合并前审计（低成本起步）

```json
{
  "audit": {
    "enabled": true,
    "mode": "manual",
    "max_rounds": 3,
    "checkpoints": {
      "post_brainstorm": "off",
      "post_spec": "off",
      "post_planning": "off",
      "mid_implementation": "off",
      "post_implementation": "off",
      "pre_merge": "convergence",
      "post_closure": "off"
    }
  }
}
```

### 场景 B：Level 3 项目全流程自适应审计

```json
{
  "audit": {
    "enabled": true,
    "mode": "adaptive",
    "max_rounds": 5,
    "adaptive_rules": {
      "level_1": "off",
      "level_2": "convergence",
      "level_3": "challenge"
    }
  }
}
```

### 场景 C：对关键检查点手动覆盖（混合模式）

`mode=adaptive` 时，`checkpoints` 中的显式值优先于 `adaptive_rules` 推导值。

```json
{
  "audit": {
    "enabled": true,
    "mode": "adaptive",
    "max_rounds": 5,
    "adaptive_rules": {
      "level_1": "off",
      "level_2": "convergence",
      "level_3": "challenge"
    },
    "checkpoints": {
      "post_spec": "challenge",
      "post_closure": "off"
    }
  }
}
```

此示例中，`post_spec` 强制使用 challenge 模式（不论 Level），`post_closure` 强制关闭，其余检查点按 `adaptive_rules` 推导。

### 场景 D：调整 mid_implementation 触发阈值

```json
{
  "audit": {
    "enabled": true,
    "mode": "adaptive",
    "mid_implementation": {
      "trigger": "task_progress",
      "threshold": 70,
      "unit": "percent_tasks_completed"
    }
  }
}
```

将触发阈值从默认 50% 提高到 70%，减少中途审计频率。

---

## 旧配置迁移

若你的 `.aria/config.json` 使用旧版 `experiments.agent_team_audit`，config-loader 会自动映射并输出迁移提示：

```json
{
  "experiments": {
    "agent_team_audit": true,
    "agent_team_audit_points": ["post_spec", "post_implementation", "pre_merge"]
  }
}
```

自动映射结果等价于：

```json
{
  "audit": {
    "enabled": true,
    "mode": "manual",
    "checkpoints": {
      "post_spec": "convergence",
      "post_implementation": "convergence",
      "pre_merge": "convergence",
      "post_brainstorm": "off",
      "post_planning": "off",
      "mid_implementation": "off",
      "post_closure": "off"
    }
  }
}
```

建议将配置迁移到新格式以获得完整的 7 个检查点、多轮收敛和挑战模式功能。

---

**参考**: [`DEFAULTS.json`](./DEFAULTS.json) | [`SKILL.md`](./SKILL.md) | [audit-engine/SKILL.md](../audit-engine/SKILL.md) | [proposal.md](../../../openspec/changes/auto-audit-system/proposal.md)

**最后更新**: 2026-03-27
