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

## mid_post_spec (B.2 实施期 spec 漂移条件触发, Aria #79)

```yaml
trigger: Phase B 实施期 SMOKE / 集成测试暴露 spec 陈述与运行实际不符
         (机械信号: 测试/SMOKE 报告 verdict_invalidated_assumptions 字段非空;
          概念信号: AI 识别运行实际与 spec 陈述矛盾)
  触发判别 (material vs incidental, 防过触发/漏触发):
    - 触发当: 漂移使一个**已写入 spec 的 path/行为/数据断言失效**
      (e.g. spec 假设 path A, SMOKE 证明走 path B)
    - 不触发当: 新发现的实现细节调整, **不影响任何 spec 断言**
      (routine 实现发现, 非 spec 事实错误)
  锚定: 与机械信号同一对象 = 失效的 *assumption* (两半信号对称)
caller: phase-b-developer (条件触发, 非每次实施都跑)
agents:
  - Tech Lead              # 漂移点技术校验 (1-2 agent, scope 限漂移)
  - (backend-architect)    # 漂移涉及架构/数据模型时加入
  - (qa-engineer)          # challenge 模式: 运行实际 vs spec 断言的矛盾核验
blocking: false           # advisory — 输出 amendment 建议, 不硬阻断实施
max_rounds: 1             # 恒单轮 (镜像 post_closure); 快速校验非全量收敛
scope: drift_point_only   # 仅漂移涉及的 spec 陈述, 不全量重审
timeout:
  single_agent: 120s
  overall: 180s
  on_timeout: skipped

检查重点:
  Tech Lead:
    - 漂移确认            # 运行实际 vs spec 原陈述, 确认是否真漂移
    - 影响半径           # 该漂移波及哪些 spec 断言 / 下游 task
    - amendment 建议      # append-only spec amendment block (类 DEC Amendment
                         # 模式: 标注日期 + 原陈述 + 修正 + 触发证据), 不改原文

输出: append-only spec amendment 建议 → 采纳后 resume Phase B
      (避免带 stale 假设继续实施; 实战 TH v0.3.2 SMOKE-A 翻 path A 隔 4 天才发现)
  amendment neutralize 要求 (防 amended-and-ignored, 同 handoff neutralize 模式
  memory feedback_handoff_closure_neutralize_nextstep): amendment block append 到
  proposal.md 末尾 (不改原文), **同时**在原失效断言处加 inline 标记
  (~~strike~~ / "⚠ 见 §Amendment YYYY-MM-DD") 指向 amendment — 否则后续 reader/
  resumed Phase B 读到原文 stale 断言会漏掉底部 amendment (state-scanner surfacing
  字段本 Spec defer, 故 in-doc neutralize 是唯一可见性保障)。
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
