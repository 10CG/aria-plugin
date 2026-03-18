# 审计触发点定义 (Audit Points)

## pre_merge (C.2 合并前)

```yaml
trigger: branch-finisher 完成，准备合并到 master/main
agents:
  - Tech Lead
  - Code Reviewer
  - Knowledge Manager
blocking: true  # 任一 Agent 报告 Critical 即 FAIL
timeout:
  single_agent: 120s
  overall: 300s
  on_timeout: skipped  # 不视为 FAIL

检查重点:
  Tech Lead:
    - 架构一致性
    - 版本号一致性
    - 依赖关系合理性
  Code Reviewer:
    - 代码质量
    - 安全漏洞
    - 测试覆盖
  Knowledge Manager:
    - 文档同步
    - CHANGELOG 更新
    - README 一致性
```

## post_implementation (B.2 实现完成后)

```yaml
trigger: 所有任务标记完成，准备进入 Phase C
agents:
  - QA Engineer
  - Code Reviewer
blocking: true  # 任一 Agent 报告 Critical 即 FAIL
timeout:
  single_agent: 120s
  overall: 300s
  on_timeout: skipped

检查重点:
  QA Engineer:
    - 测试覆盖完整性
    - 边界条件处理
    - 错误路径覆盖
  Code Reviewer:
    - 代码规范
    - 性能问题
    - 安全问题
```

## post_spec (A.1 规范完成后, 可选)

```yaml
trigger: OpenSpec 创建完成
agents:
  - Tech Lead
  - Knowledge Manager
blocking: false  # 非阻塞 (建议性)
timeout:
  single_agent: 120s
  overall: 300s
  on_timeout: skipped

检查重点:
  Tech Lead:
    - 技术可行性
    - 架构影响评估
    - 依赖分析
  Knowledge Manager:
    - 文档完整性
    - 术语一致性
    - 与现有 Spec 的关系
```

---

**最后更新**: 2026-03-18
