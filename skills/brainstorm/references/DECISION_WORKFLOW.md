# 决策记录工作流

> **所属文件**: SKILL.md 阶段 2.5
> **目的**: 结构化记录"为什么选 A 而非 B"

---

## 决策点识别

### 明确选择

用户明确表达选择偏好时，直接识别：

```yaml
模式匹配:
  - "我选择方案?\\s*([A-Z]|\\d+)"
  - "决定?用\\s+(.+)"
  - "就用\\s+(.+)"
  - "采用\\s+(.+)"

动作:
  - 直接提取方案 ID
  - 进入 SUMMARY 状态

示例:
  输入: "我选择方案A"
  识别: 方案 A
  动作: 进入 SUMMARY
```

### 隐式选择

用户表达倾向但未明确选择：

```yaml
模式匹配:
  - "([\\w]+)更适合"
  - "倾向于([\\w]+)"
  - "([\\w]+)更好"

动作:
  - 识别倾向方案
  - 要求确认: "所以你更倾向 [X]，对吗？"
  - 确认后进入 SUMMARY

示例:
  输入: "我觉得 FAISS 更适合"
  识别: 方案 FAISS
  动作: "所以你更倾向 FAISS，对吗？"
```

### 约束选择

约束过滤后只剩一个可行方案：

```yaml
条件:
  - 约束验证后 feasible_options == 1

动作:
  - 说明约束导致的唯一选择
  - 确认: "由于 [约束]，只有 [方案] 可行。是否采用？"
  - 确认后进入 SUMMARY

示例:
  输入: 约束 {预算<$500, 数据不出境}
  可行方案: 仅剩 FAISS
  说明: "由于预算限制和数据不出境要求，只有 FAISS 可行。"
```

---

## 决策 ID 生成

### 格式规范

```yaml
pattern: "DEC-{YYYYMMDD}-{序列号}"

示例:
  - DEC-20260205-001 (2026年2月5日第1个决策)
  - DEC-20260205-002 (2026年2月5日第2个决策)
  - DEC-20260206-001 (2026年2月6日第1个决策)
```

### 生成逻辑

```python
def generate_decision_id():
    # 1. 获取当前日期
    date_str = datetime.now().strftime("%Y%m%d")

    # 2. 读取 docs/decisions/ 目录
    # 3. 查找当日最大序号
    existing = glob(f"docs/decisions/*-{date_str}-*.md")
    if existing:
        max_seq = max(int(extract_seq(f)) for f in existing)
    else:
        max_seq = 0

    # 4. 生成新序号
    new_seq = max_seq + 1

    # 5. 格式化为 3 位数字
    return f"DEC-{date_str}-{new_seq:03d}"
```

---

## 决策记录写入

### 步骤流程

```yaml
步骤:
  1. 读取决策模板:
     模板路径: aria/skills/brainstorm/templates/decision-template.md

  2. 填充占位符:
     - {ID}: 生成的决策 ID
     - {DATE}: 当前日期 (YYYY-MM-DD)
     - {MODE}: 当前模式
     - {TITLE}: 决策标题
     - {背景}: 从对话中提取的背景信息
     - {约束}: 收集的约束条件表格
     - {方案}: 考虑的方案及对比
     - {选择}: 最终选择的方案
     - {理由}: 决策理由
     - {假设}: 假设条件
     - {风险}: 风险与缓解措施

  3. 写入文件:
     路径: docs/decisions/{mode}-{序列号}.md
     工具: Write
     确认: 写入前展示预览

  4. 更新索引:
     更新 docs/decisions/index.md (如果存在)
```

### 文件命名

```yaml
格式: {mode}-{sequence}.md

模式前缀:
  - problem: problem-001.md
  - requirements: requirements-001.md
  - technical: technical-001.md

示例:
  docs/decisions/
  ├── problem-001.md      # 问题空间探索
  ├── requirements-001.md # 需求分解
  └── technical-001.md    # 技术方案
```

---

## 决策记录模板

### 完整格式

```markdown
# 决策: DEC-{id} - {title}

> **日期**: {date} | **模式**: {mode} | **状态**: Active

## 背景

{决策的背景和上下文}

## 约束条件

| 类型 | 约束 | 影响 |
|------|------|------|
| business | {约束} | {影响} |
| technical | {约束} | {影响} |
| team | {约束} | {影响} |

## 考虑的方案

### 方案 A: {name}

**描述**: {方案描述}

**优点**:
- {优点1}
- {优点2}

**缺点**:
- {缺点1}
- {缺点2}

**约束匹配**: {满足/违反} {约束名}

### 方案 B: {name}

...

## 最终选择

**方案**: {selected}

## 理由

1. {理由1}
2. {理由2}
3. {理由3}

## 假设条件

- {假设1}
- {假设2}

## 风险与缓解

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|----------|
| {风险} | {高/中/低} | {高/中/低} | {措施} |

## 变更历史

| 日期 | 变更 | 原因 |
|------|------|------|
| {date} | 初始决策 | - |
```

### 简化格式

```markdown
## 决策: {ID} - {TITLE}

> **日期**: {DATE} | **模式**: {MODE} | **状态**: Active

### 背景
{背景描述}

### 约束条件
| 类型 | 约束 | 影响 |
|------|------|------|
| {约束行} |

### 考虑的方案
| 方案 | 描述 | 评分 | 状态 |
|------|------|------|------|
| {方案行} |

### 最终选择
**方案**: {选择}

### 理由
{理由列表}

### 风险与缓解
| 风险 | 缓解措施 |
|------|----------|
| {风险行} |
```

---

## 后续步骤建议

### 按模式的建议

```yaml
after_problem:
  输出: problem-{id}.md
  建议:
    - "[1] 继续头脑风暴，分解 User Stories (requirements 模式)"
    - "[2] 创建 PRD 文档"
    - "[3] 记录决策，稍后继续"

after_requirements:
  输出: requirements-{id}.md + user-stories/
  建议:
    - "[1] 为每个 Story 创建 OpenSpec (technical 模式)"
    - "[2] 更新 PRD 文档"
    - "[3] 开始实现 (Phase B)"

after_technical:
  输出: technical-{id}.md + proposal.md 草案
  建议:
    - "[1] 创建完整的 OpenSpec proposal.md"
    - "[2] 继续讨论其他技术点"
    - "[3] 开始实现 (Phase B)"
```

---

## 与其他 Skills 的集成

### spec-drafter 集成

```yaml
输入:
  - 决策记录路径
  - 约束条件
  - 方案选择

行为:
  - 自动填充 proposal.md 的背景部分
  - 预填充技术方案
  - 引用决策 ID

输出示例:
  ```markdown
  # Proposal: AI 客服功能

  > **决策来源**: [DEC-001](../../decisions/technical-001.md)

  ## 背景
  (来自 problem-brainstorm 的问题定义)

  ## 技术方案
  (来自 technical-brainstorm 的方案选择)
  ```
```

### requirements-validator 集成

```yaml
验证内容:
  - User Story 与决策记录的一致性
  - 约束条件是否被违反
  - 优先级与决策逻辑的一致性

错误示例:
  "❌ US-003 描述使用了 OpenAI API，但 DEC-001 决策排除数据出境方案"
```

### task-planner 集成

```yaml
输入增强:
  - 来自 technical-brainstorm 的技术方案
  - 更准确的任务分解
  - 更好的依赖关系识别

输出改进:
  - 任务关联决策 ID
  - 风险任务标记
```
