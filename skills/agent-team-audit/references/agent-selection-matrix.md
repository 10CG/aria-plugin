# Agent 选择矩阵 (Agent Selection Matrix)

## 触发点 → Agent 映射

| 触发点 | Tech Lead | Code Reviewer | QA Engineer | Knowledge Manager |
|--------|:---------:|:-------------:|:-----------:|:-----------------:|
| pre_merge | ✅ | ✅ | — | ✅ |
| post_implementation | — | ✅ | ✅ | — |
| post_spec | ✅ | — | — | ✅ |

## Agent 职责

### Tech Lead
- 架构决策审查
- 版本一致性验证
- 依赖关系分析
- 技术债务评估

### Code Reviewer
- 代码质量检查
- 安全漏洞扫描
- 性能问题检测
- 编码规范验证

### QA Engineer
- 测试覆盖率评估
- 边界条件检查
- 错误处理验证
- 回归风险评估

### Knowledge Manager
- 文档同步检查
- CHANGELOG 完整性
- README 一致性
- 术语规范性

## 并发调度

```
pre_merge (3 Agents):
  Batch 1: Tech Lead + Code Reviewer (并行)
  Batch 2: Knowledge Manager (等 Batch 1 完成后或并行, 取决于 max_parallel_agents)

post_implementation (2 Agents):
  Batch 1: QA Engineer + Code Reviewer (并行)

post_spec (2 Agents):
  Batch 1: Tech Lead + Knowledge Manager (并行)
```

---

**最后更新**: 2026-03-18
