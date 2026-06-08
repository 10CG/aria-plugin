[English](README.md) | **中文**

# Aria Plugin

> **版本**: 1.41.0 | **发布日期**: 2026-06-08
>
> Claude Code 的 AI-DDD 方法论完整插件 — 34 个面向用户 Skills + 7 个内部 + 11 个 Agents + 5 个 Hooks（含默认 secret-guard）

## 前置条件

- [Claude Code](https://claude.ai/code) 已安装并完成登录

## 安装

```bash
# 添加 marketplace
/plugin marketplace add 10CG/aria-plugin

# 安装 (Skills + Agents + Hooks 一起安装)
/plugin install aria@10CG-aria-plugin
```

## 包含内容

### Hooks 系统（自动触发）

| Hook 点 | Matcher | 脚本 | 功能 |
|--------|---------|------|------|
| `SessionStart` | * | session-start-check.sh | 检测中断的工作流并提示恢复 |
| `PreToolUse` | Write\|Edit\|NotebookEdit | handoff-location-guard.sh | Rule #9 L1 — 阻断写入 `.aria/handoff/*.md` |
| `PreToolUse` | Bash | **secret-guard.sh** | Rule #7 Layer 2 — 阻断 raw secret 读取（命令模式扫描），v1.24.0+ |
| `PreToolUse` | Read\|Edit\|Write\|MultiEdit | **secret-guard.sh** | Rule #7 Layer 2 — 阻断含 secret 的文件路径（.env、id_rsa 等），v1.24.0+ |
| `PostToolUse` | Bash\|Read\|Edit\|Write\|MultiEdit | **secret-scan.sh** | Rule #7 Layer 2 — 在输出进入 LLM 上下文前 REDACT secret 形态内容，v1.24.0+ |

**禁用 Hooks**：
```bash
# 设置环境变量
export ARIA_HOOKS_DISABLED=true

# 或禁用插件
/plugin disable aria@10CG-aria-plugin
```

### Skills（34 个面向用户 + 7 个内部 = 41 个）

> 内部 skills（7 个，`user-invocable: false`）：agent-router、agent-team-audit、arch-common、audit-engine、config-loader、git-remote-helper（v1.15.0 +1）、aria-token-telemetry（v1.33.0 +1）。

**十步循环核心**
- state-scanner — 项目状态扫描与智能工作流推荐
- workflow-runner — 十步循环轻量编排器
- phase-a-planner — Phase A 规划阶段执行器
- phase-b-developer — Phase B 开发阶段执行器
- phase-c-integrator — Phase C 集成阶段执行器
- phase-d-closer — Phase D 收尾阶段执行器
- spec-drafter — 创建 OpenSpec proposal.md
- task-planner — 将 OpenSpec 分解为可执行任务
- progress-updater — 更新项目进度状态

**协作思考**
- brainstorm — AI 辅助的决策讨论和需求澄清（problem/requirements/technical 模式）

**Git 工作流**
- commit-msg-generator — 生成符合 Conventional Commits 的提交消息
- strategic-commit-orchestrator — 跨模块/批量/里程碑提交编排
- branch-manager — 分支创建与 PR 管理
- branch-finisher — 分支完成收尾

**开发工具**
- subagent-driver — 子代理驱动开发（SDD），支持两阶段代码审查
- agent-router — 任务到 Agent 的智能路由器
- tdd-enforcer — 强制执行 TDD 工作流
- requesting-code-review — 两阶段代码审查（Phase 1: 规范合规性 → Phase 2: 代码质量）

**架构文档**
- arch-common *（内部，非用户调用）* — 架构工具共享组件
- arch-search — 搜索架构文档
- arch-update — 更新架构文档
- arch-scaffolder — 从 PRD 生成架构骨架
- api-doc-generator — API 文档生成

**需求管理**
- requirements-validator — PRD/Story/Architecture 验证
- requirements-sync — Story ↔ UPM 状态同步
- forgejo-sync — Story ↔ Issue 同步
- openspec-archive — 归档已完成的 OpenSpec 变更（自动修正 CLI bug）

**基础设施**
- config-loader *（内部，非用户调用）* — 配置加载
- git-remote-helper *（内部，非用户调用）* — Git 多远程 parity 检测与 push 校验共享基础设施（US-012，Layer 3）
- aria-token-telemetry *（内部，非用户调用）* — Context/token 遥测共享数据层（relay cache 读取 + transcript usage 解析 + window 4 档 resolve；#104，被 #18 estimator 复用）

**上下文感知** *（v1.33.0，#104）*
- aria-context-monitor — 机读当前 session context 占用（statusLine relay 的 runtime-truth），辅助"继续推进 vs 暂停"决策

**工作量估算** *（v1.34.0，#18）*
- ai-native-estimator — Token 轴 cycle 工作量估算 v1（phase-d 自动采集 + forecast/velocity 查询；Token 替代 4-8h 人工时假设）

**可视化**
- aria-dashboard — 项目进度看板（UPM/Stories/OpenSpec/Audit/Benchmark）

**环境诊断** *（v1.24.0）*
- aria-doctor — 检测 aria-plugin secret-guard hook 安装状态（`check_secret_guard_install` 5 态 schema）+ statusLine relay 状态（`check_context_relay` 3 态 + jq，v1.33.0）

**项目适配** *（v1.13.0）*
- project-analyzer — 扫描项目技术栈、框架与工作模式
- agent-gap-analyzer — 对比项目需求与 Agent 能力，识别缺口
- agent-creator — 生成项目专属 Agent 配置（STCO + capabilities）

**反馈与报告**
- aria-report — 向 Aria 维护团队报告 Bug、提交功能建议或提问

**审计系统**
- audit-engine *（内部，非用户调用）* — 多轮 convergence/challenge 审计编排器
- agent-team-audit *（默认关闭，需通过 `.aria/config.json` 启用）* — 单轮审计执行器

### Agents（11 个）

**核心管理**
- tech-lead — 技术架构决策、任务规划、跨团队协调
- context-manager — 多 Agent 协作、上下文管理
- knowledge-manager — 知识库管理、文档同步
- code-reviewer — 两阶段代码审查（Phase 1: 规范合规性 + Phase 2: 代码质量）

**开发相关**
- backend-architect — 后端架构、API 设计、数据库模式
- mobile-developer — React Native/Flutter、离线同步
- qa-engineer — 质量保证、代码审查、测试策略

**专业领域**
- ai-engineer — LLM 应用、RAG 系统、Agent 编排
- api-documenter — OpenAPI 规范、SDK 生成
- ui-ux-designer — 界面设计、线框图、设计系统
- legal-advisor — 隐私政策、服务条款、GDPR 合规

## 使用方式

### Hooks 自动触发

安装后，hooks 会在关键节点自动触发：

```bash
# 会话开始 — 检测中断的工作流
# → 检查 .aria/workflow-state.json 中的未完成工作

# PreToolUse Bash — 阻断 raw secret 读取 (v1.24.0+)
# → 如 `nomad var get ...` 未加 REDACT filter → BLOCKED 并给出有帮助的 stderr
# → 绕过: 命令尾部追加 `# guard:ack: <理由 ≥8 个非空白字符>`
#          (审计记录到 ~/.claude/logs/guard-bypass.log)

# PreToolUse Read|Edit|Write|MultiEdit — 阻断含 secret 的文件路径 (v1.24.0+)
# → 如读取 .env / id_rsa / .pem / .aws/credentials / .kube/config → BLOCKED

# PostToolUse * — 扫描输出中的 secret 形态内容, 进 LLM 前 REDACT (v1.24.0+)
# → warn-only (始终 exit 0); 替换 tool_response 中的 secret 值

# 诊断安装状态:
bash ${CLAUDE_PLUGIN_ROOT}/skills/aria-doctor/scripts/check_secret_guard_install.sh
# → JSON 状态: not_installed / single_plugin / single_local / dual_install / corrupted_settings
```

### 手动调用

```bash
# Skills
/aria:state-scanner
/aria:spec-drafter
/aria:workflow-runner
/aria:brainstorm
/aria:requesting-code-review
/aria:report bug

# Agents
/aria:tech-lead
/aria:backend-architect
/aria:code-reviewer
/aria:knowledge-manager
```

## Aria 2.0 — 自主运行时

本插件（aria-plugin）是 Aria 的**交互层** — 供 Claude Code 使用的交互式 Skills + Agents。

关于 **Aria 2.0 自主运行时**（10CG Lab 内部基础设施，自主执行 Aria 方法论 cycle，当前按 US-026 M6 里程碑开发中），参见：

- [Aria 主仓库](https://github.com/10CG/Aria) — 方法论 + Aria 2.0 PRD + 自主运行时文档
- [aria-orchestrator](https://github.com/10CG/aria-orchestrator) — Layer 1（Hermes + Luxeno-routed GLM models）+ Layer 2（aria-runner + Claude Code + aria-plugin）实现

**aria-plugin 在 Aria v2.0.0 发布时不会 bump 到 v2.0** — 保留语义边界（插件 = 普遍可用的交互式工具；Aria 主仓 = 方法论 + 10CG Lab 内部运行时）。插件用户：**无需任何操作**。完整语义边界说明见 Aria 主仓 [docs/release-notes-v2.0.0.md `§Plugin Compatibility`](https://github.com/10CG/Aria/blob/master/docs/release-notes-v2.0.0.md)。

## 相关项目

- [Aria](https://github.com/10CG/Aria) — Aria 主项目（方法论研究 + Aria 2.0 自主运行时）
- [aria-standards](https://github.com/10CG/aria-standards) — Aria 方法论规范
- [aria-orchestrator](https://github.com/10CG/aria-orchestrator) — Aria 2.0 自主运行时（10CG Lab 内部）

## 许可证

MIT — [10CG Lab](https://github.com/10CG)
