---
name: issue-triage
description: |
  对收到的 issue (bug report / feature request / discussion) 进行系统化核对，
  在推荐解决方案前验证版本、代码路径、in-flight 分支和复现情况。
  产出结构化 triage-report.json 和 triage-comment.md 草稿。

  使用场景："triage 这个 issue"、"核对 #101"、"issue 分析"、
  "收到 bug report 需要核对"、"是否已有 in-flight 修复"
argument-hint: "<issue-ref>"
disable-model-invocation: false
user-invocable: true
allowed-tools: Bash, Read, Write
---

# Issue Triage (issue-triage v1.0)

> **版本**: 1.0.0 | **角色**: issue 接收方核对
> **十步循环角色**: B.2 实施阶段 — 接收 issue 后的前置核对步骤，防止在过期信息或未复现 bug 上开起新的 cycle
> **机械化**: Step 0 由 `scripts/triage.py` (stdlib-only Python) 产出 JSON snapshot，AI 读 snapshot 进行 Step 6 复现 + verdict 综合。

---

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- 收到 issue 后，在起新 OpenSpec / branch 之前
- 确认 bug 是否在当前版本可复现
- 查看是否已有 in-flight PR 或本地分支处理同一问题
- 需要留 audit trail (verdict comment) 的 issue 核对

**不使用场景**:
- 已完成 triage、正在起修复 cycle → 直接 `/phase-a-planner`
- 只是看 issue 列表 / 查进度 → `/state-scanner`
- 向 Aria 维护团队报告问题 → `/aria-report` (方向相反，见 §与 aria-report 的关系)

---

## 核心功能

| 阶段 | 内容 | 机械化 |
|------|------|--------|
| **Step 0** | 执行 `triage.py`，产出 `triage-report.json` | 全自动 (`triage.py`) |
| **Steps 1-5** | 读取 issue、版本核对、代码路径验证、git 历史、in-flight 检查 | 全自动 (collectors) |
| **Step 6** | Reproduction — 三模式 exit (auto / pause / skip) | AI 辅助 |
| **综合输出** | Verdict 计算 + severity / recommended_action 填写 + `triage-comment.md` 草稿 | AI |

**步骤定义 (SOT)**:
6 步流程的完整定义（每步目的、检查项、输出字段、失败模式）见 `standards/conventions/issue-triage.md §Steps`。本文档**不复制**步骤定义，仅描述 Skill 调用契约。

---

## 配置 (config-loader)

执行前读取 `.aria/config.json`，缺失则使用默认值。参见 [config-loader](../config-loader/SKILL.md)。

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `issue_triage.default_repo` | `""` (从 forgejo_config 推断) | 裸编号时的默认仓库 |
| `issue_triage.repro_timeout_seconds` | `120` | Step 6 单次复现命令超时 |
| `issue_triage.step6_mode` | `"auto"` | 默认 Step 6 模式: `auto` / `pause` / `skip` |
| `issue_triage.output_dir` | `".aria"` | triage-report.json 输出目录 |

---

## 执行流程

### Step 0: 机械执行 triage.py (硬约束)

> **不可协商**: Steps 1-5 所有字段由 `scripts/triage.py` 机械采集，AI 不得跳过、不得逐字段手工 Bash 替代、不得在失败时"降级"到手工采集。

**执行命令**:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/issue-triage/scripts/triage.py" \
  --issue "<owner>/<repo>#N" \
  --output .aria/triage-report.json
```

**退出码契约**:

| 退出码 | 含义 | AI 动作 |
|--------|------|---------|
| `0` | 全部成功 (`steps_with_data == 5`) | 读 `.aria/triage-report.json`，进入 Stage 2 |
| `10` | 部分 collector 错误 (`steps_with_data >= 2 AND <= 4`)，report 仍可用 | 读 report，展示受影响步骤 warning，继续 Stage 2 |
| `30` | 硬失败 (`steps_with_data < 2`)，**不生成 report** | **Abort**，展示 stderr，提示检查凭证和 issue 引用；禁止进入 Step 6 |

退出码评估顺序：先 30 (hard fail) → 再 10 (partial) → 否则 0。

---

### Stage 1: 读取 Snapshot

triage.py exit 0/10 后：

1. 读取 `.aria/triage-report.json`
2. 验证 `schema_version` 字段存在（缺失 → abort，"report 格式异常，请重跑 /issue-triage"）
3. 展示 Steps 1-5 摘要（版本差、cited paths、likely_fix_candidates、in-flight 命中）
4. 若 exit 10：对每个 `collection_status: error` 的步骤展示 warning

---

### Stage 2: Step 6 复现 (三模式)

根据 `.aria/config.json` 中 `issue_triage.step6_mode` 或用户参数决定模式：

| exit_mode | 触发场景 | Skill 行为 |
|-----------|---------|------------|
| `auto` | AI 可独立复现 (默认) | 执行复现命令，填写所有 `cases[]`，进 Stage 3 |
| `pause` | 需要用户提供 env / data / 交互操作 | **暂停**，展示"需要以下信息才能继续复现：\n{missing_items}"，等待用户补充后 resume |
| `skip` | 无法复现（缺资源、环境、凭证） | 跳过复现，verdict **强制** = `needs-info`，仍生成 report |

每个复现 case 必须填结构化 schema（case schema 定义见 `standards/conventions/issue-triage.md §Step 6`）。即使 verdict=`not-reproducible`，也需 ≥1 case 记录缺失原因；`match: null` 表示未能执行。

---

### Stage 3: Verdict 计算

1. 基于 `repro.cases[]` 和 Steps 1-5 数据，按 `standards/conventions/issue-triage.md §Verdict dictionary` 选择 verdict
2. 填写正交字段：
   - `severity`: 基于影响面（commit blast radius / hit_rate / data corruption 风险）由 AI 判断
   - `recommended_action`: 基于 verdict + severity 推断
   - `deviation_note`: **仅** `partial-repro` verdict **必填**，描述与 issue 描述的实质偏离
3. 将 verdict + 正交字段写入 `.aria/triage-report.json`

---

### Stage 4: 合成 triage-comment.md

生成 `.aria/triage-comment.md` 草稿，准备 POST 到 issue。模板结构见 §输出格式。

---

## 输出格式

### triage-comment.md 模板

```markdown
## Triage Report

**Verdict**: `{verdict}` | **Severity**: `{severity}` | **Recommended Action**: `{recommended_action}`

---

### Version

| Field | Value |
|-------|-------|
| Reported | `{version.reported}` |
| Current | `{version.current}` |
| Gap | {version.gap} |

{版本差注释，如 "issue 报告版本与当前版本相同，非 outdated report" 或 "版本已更新 N 个版本，建议先确认是否已修"}

### Code Path

{code.cited_paths[] 中每个路径的存在状态 + 描述是否与代码一致}

### Git History

{git_history.likely_fix_candidates[] 列表；若空则 "No recent commits matched on cited files"}

### In-flight

| Category | Matches |
|----------|---------|
| Remote PRs | {inflight.remote_prs[] summary or "none"} |
| Local branches | {inflight.local_branches[] summary or "none"} |
| Worktrees | {inflight.worktrees[] summary or "none"} |

### Reproduction

**Mode**: `{repro.exit_mode}` | **Hit rate**: `{repro.hit_rate}`

{repro.cases[] 每个 case 的 input / expected / actual / match 简报}

{partial-repro 时额外显示 deviation_note}

### Verdict Rationale

{2-3 句综合推理：为什么是该 verdict，关键证据来自哪个步骤}

---

*Generated by `/issue-triage` v{triage_tool_version} — Ref: {issue_ref}*
```

---

## 输入参数

| 参数 | 必需 | 格式 | 示例 |
|------|------|------|------|
| `issue` | ✅ | Forgejo URL / `<owner>/<repo>#N` / 裸编号（本仓库默认） | `101`, `10CG/Aria#101`, `https://forgejo.10cg.pub/10CG/Aria/issues/101` |
| `cited_files` | ❌ | 逗号分隔路径列表，覆盖自动抽取 | `aria/skills/state-scanner/scripts/scan.py` |
| `mode` | ❌ | Step 6 模式覆盖 | `auto`, `pause`, `skip` |

---

## 使用示例

### 示例 1: 单仓库 issue（裸编号）— Aria #101

```
用户: "/issue-triage 101"
Step 0: triage.py --issue "10CG/Aria#101" --output .aria/triage-report.json → exit 0
Stage 1: version gap=0, cited paths 存在, likely_fix_candidates=[], in-flight remote_prs=1
Stage 2: auto 复现 → hit_rate=2/4 (2/4 主因 + 1/4 次生 + 1/4 不复现)
Stage 3: verdict=partial-repro, deviation_note="自报 4/4，实测 2/4 主因命中，与描述偏离"
Stage 4: 生成 .aria/triage-comment.md (准备 POST 到 #101)
```

### 示例 2: 跨仓库 issue，已修复

```
用户: "/issue-triage 10CG/SilkNode#42"
Step 0: triage.py --issue "10CG/SilkNode#42" → exit 0
Stage 1: Step 2 → VERSION current=v2.3.1, reported=v2.1.0 (gap=+2 minor)
         Step 4 → likely_fix_candidates=[{sha:"abc123", message:"fix: resolve SilkNode#42"}]
Stage 3: verdict=fixed-in-X, recommended_action=close
```

### 示例 3: pause 模式（需要用户提供数据）

```
用户: "/issue-triage 87 --mode pause"
Stage 2: exit_mode=pause
输出: "Step 6 复现需要：1. 测试用 Forgejo token  2. 触发 bug 的 config.json
      请补充后继续。"
(用户补充) → resume → Stage 3 → Stage 4
```

---

## 跨平台命令规范

| 正确 | 错误 |
|------|------|
| `python3 scripts/triage.py` | `python scripts\triage.py` |
| `ls .aria/triage-report.json 2>/dev/null` | `if exist .aria\triage-report.json` |
| 路径使用 `/` | 路径使用 `\` |
| `2>/dev/null` | `2>nul` |

---

## 错误处理

| 错误 | 原因 | 处理 |
|------|------|------|
| `triage.py exit 30` | `steps_with_data < 2`（凭证失效 / issue 不存在 / 网络问题） | **Abort**，展示 stderr，提示检查 `FORGEJO_TOKEN` 和 issue 引用格式 |
| Forgejo API 429 | Rate limit | `collection_status: error`，exit 10；展示 warning，提示等待后重试 |
| Forgejo API 401/403 | 认证失败 / token 过期 | `collection_status: error`，exit 10；提示重新配置 `FORGEJO_TOKEN` |
| Issue 不存在 (404) | issue 编号错误 / 仓库名拼写 | `collection_status: error`，若 step1 失败即 exit 30 |
| 复现超时 | Step 6 命令执行超过 `repro_timeout_seconds` | case `match: null`，`notes: "timeout"` |
| `steps_with_data == 0` | 所有 collectors 失败 | exit 30，不生成 report |
| `schema_version` 缺失 | triage.py 与 SKILL.md 版本漂移 | Abort，"report 格式异常，请升级 aria-plugin" |
| Step 6 `partial-repro` 缺 `deviation_note` | AI 未填必填字段 | Stage 3 自检：若 verdict=partial-repro 且 deviation_note 为空，**强制提示补填** |

---

## 检查清单

### 使用前
- [ ] `FORGEJO_TOKEN` 已配置（或 `.aria/config.json` 有 forgejo 配置）
- [ ] issue 引用格式正确（`101` / `10CG/Aria#101` / URL）
- [ ] 了解 6 步 SOP 含义：`standards/conventions/issue-triage.md §Steps`

### 使用后
- [ ] `triage.py` exit 0/10（非 30）
- [ ] `.aria/triage-report.json` 存在且 schema_version 字段存在
- [ ] Verdict 已选择（非空）
- [ ] `partial-repro` 时 `deviation_note` 已填写
- [ ] `.aria/triage-comment.md` 已生成，准备 POST 到 issue
- [ ] 如 verdict=`confirmed` 或 `partial-repro`，根据 `recommended_action` 决定是否起新 OpenSpec cycle

---

## 与 aria-report 的关系

这两个 Skill 名字相近，但方向相反，互不冲突：

| | aria-report | issue-triage |
|---|---|---|
| **方向** | **Inbound** — 用户 → Aria 团队 | **Outbound** — Aria 团队 → issue verdict |
| **主体** | Aria 的用户（外部）报告 bug / feature | Aria 团队成员收到 issue 后核对 |
| **输出** | 在 Forgejo / GitHub 创建新 issue | 在现有 issue 下 POST triage comment |
| **典型调用** | `/aria-report bug` — "我发现 state-scanner 有个 bug" | `/issue-triage 101` — "核对 #101 是否真实 + 版本/复现核查" |
| **触发时机** | 用户遇到问题时 | 维护团队接收 issue 时 |

**不重叠**: aria-report 的输出（一个新 issue）正好是 issue-triage 的输入（一个待 triage 的 issue）。aria-report → issue tracker → issue-triage 是完整链路。

---

## 相关文档

- **[standards/conventions/issue-triage.md](../../../../standards/conventions/issue-triage.md)** — **6 步 SOP + Verdict 字典 + Exception 模板 (SOT)**
- [references/triage-report-schema.md](./references/triage-report-schema.md) — triage-report.json schema (source-of-truth)
- [scripts/triage.py](./scripts/triage.py) — 机械化 collector 入口
- [state-scanner SKILL.md](../state-scanner/SKILL.md) — scan.py pattern 参考
- [aria-report SKILL.md](../aria-report/SKILL.md) — Inbound issue 报告（反向边界）
- **触发 issue**: [Forgejo Aria #101](https://forgejo.10cg.pub/10CG/Aria/issues/101)
- **Canonical case study**: [issuecomment-5972](https://forgejo.10cg.pub/10CG/Aria/issues/101#issuecomment-5972)

---

**最后更新**: 2026-05-13
**Skill 版本**: 1.0.0
**维护者**: 10CG Lab
