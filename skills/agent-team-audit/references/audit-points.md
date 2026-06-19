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
    - 数据可用性 (Aria #54)        # diff 类: 验证实现依赖的数据/环境前置实际存在
                                   # → 见下「横切检查原则 · 数据可用性」(含 verdict 后果)
    - 框架约定 (Aria #95)          # framework-specific convention; tsc/lint/单测不抓
                                   # → 见下「横切检查原则 · 框架约定」(含约束清单)
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
    - 数据可用性 (Aria #54)        # 断言引用历史 git / 外部 / 环境数据时, 机械核实
                                   # 数据实际存在 → 见下「横切检查原则 · 数据可用性」
                                   # (含 verdict 后果 + 机械核实命令; 实战 TH v0.3.2)
    - 框架约定 (Aria #95)          # framework 项目验证 framework-specific 约束
                                   # → 见下「横切检查原则 · 框架约定」(含约束清单;
                                   # 实战 SilkNode US-096 Next.js route named export)
  Knowledge Manager:
    - 文档完整性
    - 术语一致性
    - 与现有 Spec 的关系
```

---

## 横切检查原则 (适用多个检查点)

### 数据可用性 (Aria #54) — post_spec / mid_implementation / post_implementation

任何断言依赖"历史 / 外部 / 环境数据"事实 (而非纯代码逻辑) 时, 审计 agent 必须用机械手段核实该数据**当前实际存在且符合断言规模**, 不接受"逻辑自洽即通过":
- git 历史断言 → `git log --oneline -- <path>` / `git rev-list --count`
- 文件/目录存在断言 → `ls` / `test -e`
- 数据量 / baseline 断言 → `wc -l` / 计数查询
- 外部 API / 服务断言 → 标注为"运行期依赖, 实施前需 probe", 不在 spec 阶段假定可用

> **verdict 后果 (载重, 非观察性)**: 核实发现数据**缺失或规模不符** → 该 agent verdict **必须 REVISE/FAIL**, 即使 post_spec 为 `blocking: false`。缺失数据是 **spec 事实错误**, 非风格建议; 仅"记一笔"会重演 #54 (逻辑自洽 spec + 数据不存在仍 PASS, 靠 owner 事后挑战才发现)。检查的价值不在"看一眼", 而在 lookup 结果对 verdict **载重**。

### 框架约定 (Aria #95) — post_spec / post_implementation

涉及 framework 项目 (Next.js / Astro / SvelteKit / Vue / Remix / Solid 等) 时, 验证 framework-specific convention (tsc/lint/单测层不覆盖, 仅 build 期暴露):
- 从 `package.json` dependencies 探测 framework + 版本
- 对照该 framework 的 export / routing / directive / metadata 约束
- 以项目内现有同类文件 (相同目录/角色) 作 baseline 对比
- 配合 phase-b-developer 的本地 build 验证步骤 (config `framework_build_check`) 形成双层防护

**最后更新**: 2026-06-19 (audit-rubric-runtime-reality-checks: +数据可用性 #54 / +框架约定 #95 检查项 + 横切原则节)
