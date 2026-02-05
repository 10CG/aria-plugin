# 深度控制算法

> **所属文件**: SKILL.md 阶段 2.4
> **目的**: 控制对话深度，防止过早收敛或无限讨论

---

## 深度计算

### 指标定义

```yaml
depth_metrics:
  fuzziness:
    description: 输入模糊度 (0=清晰, 1=非常模糊)
    calculation:
      - 术语模糊度: 未定义术语数 / 总术语数
      - 约束模糊度: 未指定约束数 / 预期约束数
      - 范围模糊度: 边界不明确的程度
    formula: "(术语模糊度 + 约束模糊度 + 范围模糊度) / 3"

  coverage:
    description: 讨论覆盖面 (0-1)
    calculation:
      - 话题覆盖: 已讨论话题数 / 预期话题数
      - 角度覆盖: 业务/技术/用户/运维 等角度
      - 约束覆盖: 已验证约束数 / 总约束数
    formula: "(话题 + 角度 + 约束) / 3"

  consensus:
    description: 共识程度 (0=分歧, 1=一致)
    calculation:
      - 用户明确选择: +0.5
      - 方案对比收敛: +0.3
      - 约束导致唯一解: +0.2
    formula: "min(1.0, 各项之和)"
```

### 示例计算

```yaml
场景: 讨论向量数据库选择

fuzziness 计算:
  - 术语模糊度: 0/5 = 0 (术语都明确)
  - 约束模糊度: 1/4 = 0.25 (成本未定)
  - 范围模糊度: 0.1 (边界较清楚)
  - 结果: (0 + 0.25 + 0.1) / 3 = 0.12

coverage 计算:
  - 话题覆盖: 3/4 = 0.75
  - 角度覆盖: 0.67 (缺运维角度)
  - 约束覆盖: 3/4 = 0.75
  - 结果: (0.75 + 0.67 + 0.75) / 3 = 0.72

consensus 计算:
  - 用户明确选择: 0 (未选择)
  - 方案对比收敛: 0.3 (已讨论优缺点)
  - 约束导致唯一解: 0 (仍有2个可行方案)
  - 结果: min(1.0, 0 + 0.3 + 0) = 0.3
```

---

## 深度阈值

```yaml
depth_thresholds:
  shallow:
    condition: "coverage < 0.5"
    action: "继续探索，不收敛"
    guidance: "我们还需要了解更多信息才能做决策。"

  adequate:
    condition: "coverage >= 0.5 && consensus >= 0.5"
    action: "可以开始收敛"
    guidance: "信息基本充分，可以开始对比方案了。"

  deep:
    condition: "coverage >= 0.7 && consensus >= 0.7"
    action: "应该收敛"
    guidance: "我们已经讨论得足够充分了，建议现在做决策。"

  force_converge:
    condition: "round >= max_rounds * 0.8"
    action: "强制收敛"
    guidance: "为了效率，我们需要在接下来几轮内做出决策。"
```

### 决策树

```
当前状态评估
    │
    ├─ coverage < 0.5?
    │   └─ YES → shallow: 继续探索
    │
    ├─ coverage >= 0.5 && consensus >= 0.5?
    │   └─ YES → adequate: 可以收敛
    │
    ├─ coverage >= 0.7 && consensus >= 0.7?
    │   └─ YES → deep: 应该收敛
    │
    └─ round >= max_rounds * 0.8?
        └─ YES → force_converge: 强制收敛
```

---

## 收敛检测

### 检查项

```yaml
convergence_detection:
  检查项:
    1. 用户明确选择:
       模式: "我选择|决定用|就用|采用"
       权重: 1.0 (直接触发收敛)

    2. 高共识度:
       条件: consensus >= 0.7
       权重: 0.8

    3. 轮次接近上限:
       条件: round >= max_rounds * 0.8
       权重: 0.6 (强制收敛)

    4. 约束导致唯一解:
       条件: feasible_options == 1
       权重: 0.9
```

### 收敛决策

```yaml
收敛决策规则:
  - 任一检查项权重 >= 0.8 → 触发收敛
  - 多项检查项权重之和 >= 1.0 → 触发收敛
  - 否则 → 继续当前状态
```

### 示例

```yaml
示例 1: 用户明确选择
  检查结果:
    - 用户明确选择: ✅ (权重 1.0)
  决策: 触发收敛
  动作: 进入 SUMMARY 状态

示例 2: 高共识度
  检查结果:
    - 高共识度: ✅ consensus = 0.8 (权重 0.8)
  决策: 触发收敛
  动作: 进入 SUMMARY 状态

示例 3: 组合触发
  检查结果:
    - 高共识度: ⚠️ consensus = 0.6 (权重 0.8 未达)
    - 轮次接近: ✅ round = 12/15 = 0.8 (权重 0.6)
  总权重: 0.6 < 0.8，但接近
  决策: 建议收敛，询问用户是否准备决策

示例 4: 不收敛
  检查结果:
    - 高共识度: ❌ consensus = 0.4
    - 轮次接近: ❌ round = 5/15
  决策: 继续探索
```

---

## 最大轮次配置

```yaml
max_rounds:
  # 各模式总轮次上限
  problem: 10
  requirements: 15
  technical: 8

  # 每状态问题上限
  per_state:
    CLARIFY: 3
    EXPLORE: 5
    CONVERGE: 3
```

### 轮次计数

```yaml
轮次定义:
  - 一轮 = AI 一次提问 + 用户一次回答
  - 状态内计数: 每个状态独立计数
  - 总轮次: 整个对话的总轮次

强制收敛:
  - 当总轮次 >= max_rounds * 0.8 时
  - 显示提示: "为了效率，我们需要在接下来几轮内做出决策。"
  - 提供选项: 强制选择最优方案 / 放宽约束 / 分解问题
```

---

## 使用建议

1. **初期 (shallow)**: 多提问，多探索，不要急于收敛
2. **中期 (adequate)**: 开始对比方案，引导用户思考
3. **后期 (deep)**: 明确推荐，促成决策
4. **超时 (force)**: 保护用户体验，避免无限讨论
