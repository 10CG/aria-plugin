---
name: config-loader
description: |
  Aria 项目级配置加载器（内部基础设施）。
  查找、解析、验证 .aria/config.json 并合并默认值。

  此 Skill 不直接触发，由其他 Skills 引用以读取项目配置。
user-invocable: false
disable-model-invocation: true
allowed-tools: Read, Glob
---

# 配置加载器 (Config Loader)

> **版本**: 1.0.0 | **角色**: 内部基础设施 Skill

## 职责

为所有需要读取项目配置的 Skills 提供统一的配置加载逻辑。

## 加载流程

```
1. 查找 .aria/config.json (项目根目录)
2. 如果存在 → 解析 JSON
3. 验证字段类型和范围
4. 与 DEFAULTS.json 合并 (用户值覆盖默认值)
5. 返回完整配置对象
```

## 错误处理

| 场景 | 行为 |
|------|------|
| 文件缺失 | 静默返回 DEFAULTS.json 全部默认值 |
| JSON 格式错误 | 警告用户 + 返回默认值 |
| 字段类型错误 | 警告 + 使用该字段默认值 |
| 字段值超范围 | 警告 + clamp 到有效范围 |

## 字段验证规则

```yaml
workflow.auto_proceed:
  type: boolean
  default: false

state_scanner.confidence_threshold:
  type: integer
  range: [0, 100]
  default: 90

state_scanner.auto_execute_enabled:
  type: boolean
  default: false

state_scanner.auto_execute_rules:
  type: array of string
  valid_values: [commit_only, quick_fix, doc_only, feature_with_spec]
  default: [commit_only, quick_fix, doc_only]

state_scanner.audit_log_path:
  type: string
  default: ".aria/audit.log"

tdd.strictness:
  type: string
  valid_values: [advisory, strict, superpowers]
  default: "advisory"

benchmarks.require_before_merge:
  type: boolean
  default: true

experiments.agent_team_audit:
  type: boolean
  default: false

experiments.agent_team_audit_points:
  type: array of string
  valid_values: [pre_merge, post_implementation, post_spec]
  default: [pre_merge]
```

## 与 .claude/tdd-config.json 的优先级关系

```
优先级 (高 → 低):
  .aria/config.json tdd.strictness     ← 项目统一配置 (推荐)
  .claude/tdd-config.json              ← 遗留配置 (向后兼容)
  Skill 内置默认值 (DEFAULTS.json)     ← 兜底
```

当 `.aria/config.json` 存在时，其 `tdd.strictness` 覆盖 `.claude/tdd-config.json` 中的对应字段。`.claude/tdd-config.json` 中的细粒度字段 (`skip_patterns`, `test_patterns`) 不在 `.aria/config.json` 中重复，继续在原位生效。

## 调用方式

其他 Skill 在执行前通过以下模式读取配置：

```
1. 检查 .aria/config.json 是否存在
2. 如果存在，读取并解析
3. 提取所需字段，缺失字段使用 DEFAULTS.json 中的默认值
4. 字段验证参照上述规则
```

## 消费方 Skills

| Skill | 读取字段 |
|-------|---------|
| state-scanner | `state_scanner.*`, `workflow.auto_proceed` |
| workflow-runner | `workflow.auto_proceed` |
| tdd-enforcer | `tdd.strictness` |
| branch-finisher | `benchmarks.require_before_merge` |
| phase-c-integrator | `experiments.agent_team_audit*` |
| phase-b-developer | `experiments.agent_team_audit*` |

## 默认值文件

所有默认值集中管理在 [`DEFAULTS.json`](./DEFAULTS.json)。

---

**最后更新**: 2026-03-18
