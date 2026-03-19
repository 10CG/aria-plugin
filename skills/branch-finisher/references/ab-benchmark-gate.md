# AB Benchmark Gate — 参考文档

> branch-finisher 步骤 2.5 的检测逻辑规范

## 触发条件

当 `benchmarks.require_before_merge` 为 `true` 且变更文件中包含以下路径时触发:

```
skills/*/SKILL.md
skills/*/DEFAULTS.json
```

排除: `user-invocable: false` 且 `disable-model-invocation: true` 的内部 Skill (如 config-loader) 可由用户确认跳过。

## 检测方法

```yaml
步骤:
  1. 获取分支变更文件:
     git diff --name-only $(git merge-base HEAD master)..HEAD
     # 在子模块内执行时无需前缀

  2. 过滤匹配:
     grep -E "skills/.*/SKILL\.md"

  3. 对每个匹配文件做 zone 分类:
     git diff $(git merge-base HEAD master)..HEAD -- {file}
     分析变更行所属区域 (见下方 Zone 定义)

  4. 检查 AB 结果:
     查找 aria-plugin-benchmarks/ab-results/ 中对应 Skill 的记录
     验证记录时间戳晚于 SKILL.md 最后修改时间
```

## Zone 分类 (逻辑变更 vs 文档变更)

### 逻辑 Zone (AB Required)

变更落在以下区域时需要 AB 测试:

| Zone | 匹配模式 |
|------|---------|
| YAML frontmatter | `---` 之间的 `description:`, `allowed-tools:`, `argument-hint:` 等 |
| 执行流程 | `## 执行流程`, `阶段 N`, `步骤 N` 下的内容 |
| 检测/判断逻辑 | `检测步骤:`, `action:`, `condition:`, `skip_if:`, `trigger:` |
| 输出定义 | `输出:`, `output:` 下的结构化字段 |
| 配置字段 | `## 配置` 下的字段定义 |
| 推荐规则 | `RECOMMENDATION_RULES.md` 中的规则条件 |

### 文档 Zone (AB Not Required)

| Zone | 匹配模式 |
|------|---------|
| 使用场景/示例 | `## 快速开始`, `## 使用示例`, `## 相关文档` |
| 元数据 | `**最后更新**:`, `**Skill版本**:` |
| 排版/格式 | 仅空行、缩进、Markdown 语法调整 |
| 注释/说明 | `> 注意:`, `> 参考:` 等 blockquote 说明 |

### 保守策略

无法确定 Zone 时 (如 diff > 20 行跨多区域)，默认归为逻辑变更。宁可多跑一次 benchmark，不可漏过逻辑变更。

## 验证 AB 结果是否新鲜

```yaml
新鲜判断:
  1. 查找 aria-plugin-benchmarks/ab-results/latest/summary.yaml
  2. 提取对应 Skill 的条目
  3. 比较: result_date > skill_last_modified_date?
     - 是 → AB 验证通过
     - 否 → 需要重新运行 benchmark
  4. 无条目 → 从未测试，需要运行
```

## 门控行为

由 `.aria/config.json` → `benchmarks.skill_change_block_mode` 控制:

| 模式 | 行为 |
|------|------|
| `warn` (默认) | 输出警告 + 提供选项 [1] 运行 AB [2] 跳过 (记录原因) |
| `block` | 阻塞选项 [1] 提交并创建 PR，仅允许 [2] 继续修改 |
| `off` | 跳过检测 |

## 警告输出格式

```
⚠️  Skill 变更 AB 验证
──────────────────────────────────────────────────────
  检测到 SKILL.md 逻辑变更:
    - state-scanner (阶段 1.5 Status 提取模式变更)
  AB 验证状态: 未找到新鲜结果

  操作:
    [1] 运行 /skill-creator benchmark
    [2] 跳过 — 确认为纯文档修改，无需 AB (记录到 audit.log)

  规则依据: CLAUDE.md 规则 #6
  详细手册: aria-plugin-benchmarks/AB_TEST_OPERATIONS.md
```

## 绕过规程

选择 [2] 跳过时:
- 记录到 `.aria/audit.log`: `[SKIP] {date} {skill} AB验证跳过 reason={user_input}`
- commit message 追加: `[AB-SKIP: {skill}]`

---

**最后更新**: 2026-03-19
