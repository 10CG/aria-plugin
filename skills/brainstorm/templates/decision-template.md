# 决策: DEC-{ID} - {TITLE}

> **日期**: {{DATE}}
> **模式**: {{MODE}} | problem | requirements | technical
> **状态**: Active | Archived | Superseded
> **可撤销**: {{REVERSIBLE}}
> **有效期**: {{EXPIRY|N/A}}

---

## 背景

{{决策的背景和上下文，包括：
- 要解决的问题
- 相关的 User Story 或 PRD
- 相关的约束条件
- 任何前置决策}}

---

## 约束条件

| 类型 | 约束 | 影响 | 来源 |
|------|------|------|------|
| business | {{constraint}} | {{impact}} | user/config/inferred |
| technical | {{constraint}} | {{impact}} | user/config/inferred |
| team | {{constraint}} | {{impact}} | user/config/inferred |

---

## 考虑的方案

### 方案 A: {{NAME}}

**描述**:
{{方案详细描述}}

**优点**:
- {{pro 1}}
- {{pro 2}}

**缺点**:
- {{con 1}}
- {{con 2}}

**可行性**: ✅ 可行 | ❌ 不可行 ({{reason}})

**评分**: {{0-10}}

---

### 方案 B: {{NAME}}

...

---

## 最终选择

**方案**: {{SELECTED_OPTION}}

**理由**:
{{为什么选择这个方案而非其他
- 满足关键约束
- 成本效益比最高
- 风险可控
- 团队熟悉度高
- 其他原因}}

---

## 假设条件

| 假设 | 验证方式 | 失败影响 |
|------|----------|----------|
| {{assumption 1}} | {{how to verify}} | {{impact}} |
| {{assumption 2}} | {{how to verify}} | {{impact}} |

---

## 风险与缓解

| 风险 | 可能性 | 影响 | 缓解措施 | 负责人 |
|------|--------|------|----------|--------|
| {{risk 1}} | High/Med/Low | High/Med/Low | {{mitigation}} | {{owner}} |
| {{risk 2}} | High/Med/Low | High/Med/Low | {{mitigation}} | {{owner}} |

---

## 影响范围

{{这个决策会影响：
- 哪些模块/组件
- 哪些团队
- 哪些后续决策
- 哪些文档需要更新}}

---

## 替代方案 (备选)

{{如果当前方案失败，备选方案是：
- 方案 X: {{name and reason}}
- 方案 Y: {{name and reason}}}}

---

## 关联文档

- **PRD**: {{link or N/A}}
- **User Story**: {{link or N/A}}
- **OpenSpec**: {{link or N/A}}
- **前置决策**: {{link or N/A}}
- **相关决策**: {{link or N/A}}

---

## 变更历史

| 日期 | 变更 | 原因 | 操作人 |
|------|------|------|--------|
| {{DATE}} | 初始记录 | - | {{AUTHOR}} |
| | | | |

---

## 下一步

1. {{next action 1}}
2. {{next action 2}}
3. {{next action 3}}

---

**审批**:
- [ ] 技术负责人: _____ 日期: ____
- [ ] 产品负责人: _____ 日期: ____
- [ ] 架构师: _____ 日期: ____
