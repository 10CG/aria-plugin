---
name: phase-c-integrator
description: |
  十步循环 Phase C - 集成阶段执行器，编排 C.1-C.2 步骤。

  使用场景："执行集成阶段"、"Phase C"、"提交代码并创建 PR"
argument-hint: "[--skip-pr]"
disable-model-invocation: false
user-invocable: true
allowed-tools: Bash, Read, Write, Glob, Grep, Task, Skill
---

# Phase C - 集成阶段 (Integrator)

> **版本**: 1.3.0 | **十步循环**: C.1-C.2
> **更新**: 2026-05-10 - C.2.4 Pre-Merge Precondition Gate (#60, consume aether `--in-flight` primitive)
> **历史更新**: 2026-03-27 - 升级审计触发从 agent-team-audit 改为 audit-engine

## 快速开始

### 我应该使用这个 Skill 吗？

**使用场景**:
- 需要提交代码变更
- 需要创建 Pull Request
- 需要合并分支
- 开发完成后的集成阶段

**不使用场景**:
- 无变更需要提交 → 跳过 C.1
- 不需要 PR → 跳过 C.2

---

## 配置 (config-loader)

执行前读取 `.aria/config.json`，缺失则使用默认值。参见 [config-loader](../config-loader/SKILL.md)。

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `audit.enabled` | `false` | 启用 audit-engine 审计 (新) |
| `audit.checkpoints.pre_merge` | `"off"` | pre_merge 检查点模式 |
| `experiments.agent_team_audit` | `false` | 旧配置 (向后兼容，自动映射到 audit.*) |
| `experiments.agent_team_audit_points` | `["pre_merge"]` | 旧配置 (向后兼容) |
| `upm.milestone_driven` | `false` | 启用 C.2.6 里程碑子进度追加 (opt-in) |
| `phase_c_integrator.pre_merge_gate.enabled` | `true` | 启用 C.2.4 pre-merge precondition gate (v1.3.0+) |
| `phase_c_integrator.submodule_gate.mode` | `"block"` (v1.49.0+ default) / `"warn"` (legacy) / `"off"` (bypass) | C.2.4.5 submodule pointer regression gate 模式 (Spec aria-submodule-pointer-regression-gate) |
| `phase_c_integrator.pre_merge_gate.ci_backends` | `null` (auto-detect) / `[]` (explicit disable) / `[{name: "..."}]` (explicit list) | **v1.31.0+** CI backend 选择 (替代旧 `primitive_preference`). 见 §C.2.4.X CI Backends |
| `phase_c_integrator.pre_merge_gate.no_ci_fallback` | `"skip_with_warning"` | 无可用 CI backend 时降级 (`skip_with_warning` / `abort`). **v1.31.0+** 替代旧 `no_aether_fallback` (alias 仍读, 发 deprecation warning, v2.0 移除) |
| `phase_c_integrator.pre_merge_gate.wait_timeout_seconds` | `1800` | wait+retry max 等待时长 (默认 30 min) |
| `phase_c_integrator.pre_merge_gate.wait_check_intervals` | `[30,60,120,300,300]` | 指数退避秒数; 数组耗尽后重复 `intervals[-1]` |
| `phase_c_integrator.pre_merge_gate.primitive_call_timeout_seconds` | `30` | 单次 aether subprocess 调用 timeout |
| `phase_c_integrator.pre_merge_gate.poll_chunk_seconds` | `5` | Ctrl-C polling chunk 大小 |

当 `audit.enabled=true` 且 `audit.checkpoints.pre_merge != "off"` 时，C.2 合并前触发 audit-engine (pre_merge 检查点)。
旧配置 `experiments.agent_team_audit=true` 且 `"pre_merge" in agent_team_audit_points` 自动映射到新配置。

---

## 核心功能

| 步骤 | Skill | 职责 | 输出 |
|------|-------|------|------|
| C.1 | commit-msg-generator | Git 提交 | commit_sha, message |
| C.2 | branch-manager | PR/合并 | pr_url, pr_number |

---

## 执行流程

### 输入

```yaml
context:
  phase_cycle: "Phase4-Cycle9"
  module: "mobile"
  changed_files: ["lib/auth.dart", "test/auth_test.dart"]
  branch_name: "feature/mobile/TASK-001-add-auth"  # 来自 Phase B
  test_results:                                     # 来自 Phase B
    passed: true
    coverage: 87.5

  # v1.1.0 新增: branch-finisher 输出
  completion_option: 1                              # 来自 branch-finisher
  worktree_path: ".git/worktrees/TASK-001-xxx"     # 可选
  validation_report:                                # 来自 branch-finisher
    passed: true
    blocking_failures: 0
    warnings: 1

config:
  skip_steps: []
  params:
    enhanced_markers: true        # 使用增强提交标记
    create_pr: true               # 是否创建 PR
```

### 步骤执行

```yaml
C.1 - Git 提交:
  skill: commit-msg-generator
  params:
    enhanced_markers: true
    subagent_type: "from_context"
    phase_cycle: "from_context"
    module: "from_context"
  skip_if:
    - no_changes_to_commit: true
  action:
    - 分析暂存区变更
    - 生成规范提交消息
    - 执行 git commit
  output:
    commit_sha: "abc1234"
    commit_message: "feat(auth): 添加用户认证..."

C.2 - PR/合并:
  skill: branch-manager
  action: pr
  skip_if:
    - no_pr_needed: true
    - direct_push_allowed: true
  pre_hook:                               # audit-engine 检查点
    audit_engine:
      checkpoint: pre_merge
      步骤:
        1. 通过 config-loader 读取 .aria/config.json audit 块
        2. 检查 audit.enabled — false 则跳过，保持现有行为不变
        3. 检查 audit.checkpoints.pre_merge — "off" 则跳过
        4. 如启用: 调用 audit-engine
           - checkpoint: "pre_merge"
           - mode: 来自配置 (convergence / challenge / adaptive)
           - context: PR diff (branch_name vs base)
        5. 处理 verdict:
           - PASS / PASS_WITH_WARNINGS → 继续推送和创建 PR
           - FAIL → 阻塞合并，输出审计报告
      backward_compat:
        audit.enabled=false: 完全跳过，Phase C 行为与之前完全相同
        旧配置 experiments.agent_team_audit: 由 audit-engine 内部映射处理
      fallback_description: |
        audit-engine 内部通过 agent-team-audit 单轮引擎执行审计。
        直接调用 agent-team-audit 已由 audit-engine 编排层取代。
      on_fail: 阻塞合并, 输出审计报告
      on_skip: 继续合并 (审计未启用)
  action:
    - (如 audit.enabled) 触发 audit-engine (pre_merge 检查点)
    - 推送分支到远程
    - 创建 Pull Request
    - (可选) 自动合并
  output:
    pr_url: "https://..."
    pr_number: 123
    audit_verdict: "PASS"                 # 如审计启用 (PASS | PASS_WITH_WARNINGS | FAIL)
    audit_report: ".aria/audit-reports/pre_merge-{timestamp}.md"

> **注意**: branch-manager 会自动处理 Cloudflare Access 配置。
> 统一规范见 `../forgejo-sync/PRE_CHECK.md`

C.2.4 - Pre-Merge Precondition Gate (v1.3.0+):
  触发条件:
    - C.2 action PR 已创建 (PR_NUMBER + PR_URL 已知)
    - 即将调用 branch-manager merge action (auto_merge=true 或 user-triggered continue)
    - 配置 phase_c_integrator.pre_merge_gate.enabled: true (默认)
  primitive 调用:
    - aether ci status --branch main --in-flight --json (查 main 是否有 in-flight)
    - aether ci status --branch <PR_BRANCH> --json (查本 PR CI 状态)
    - aria 端 verdict 计算 (aether-pre-merge-check skill 从未实施, P0-B not shipped)
  三态结果:
    green:  本 PR CI passing + main 无 in-flight CI → 继续 branch-manager merge
    wait:   main 有 in-flight CI run OR PR CI pending → 进入 wait+retry (workflow-runner wait_recoverable)
    fail:   PR CI failing OR primitive 错误 → BLOCK + 报告
  output:
    pre_merge_verdict: "green" | "wait" | "fail"
    in_flight_runs: [{run_id, branch, started_at, elapsed_seconds}]   # wait 时
    pr_ci_status: "passing" | "failing" | "pending"
    primitive_used: "aether-ci-cli" | "manual"
    primitive_version_sha: "f29abee"   # aether-cli #116 baseline

C.2.4.5 - Submodule Pointer Regression Gate (v1.28.0+):
  触发条件:
    - C.2.4 verdict=green (CI gate 已通过)
    - 即将调用 branch-manager merge action
    - 配置 phase_c_integrator.submodule_gate.mode: "block" (v1.49.0+ default) | "warn" (legacy opt-out) | "off" (emergency bypass)
  primitive 调用:
    - git fetch origin (bare, 更新所有 ref) — 强制, 失败 abort
    - git -C <submodule> fetch origin — 每 submodule
    - git -C <submodule> merge-base --is-ancestor MASTER_PTR FEATURE_PTR — 主 ancestry 检查
    - 双向 ancestry 区分 regression (case c) vs divergence (case d)
  三态结果:
    pass:   所有 submodule pointer 是 forward bump 或 no-change 或 first-time
    block:  至少一个 submodule pointer 是 regression 或 divergence (v1.49.0+ default; v1.28.0 was warn-only)
    bypass: per-PR commit trailer `Submodule-Rollback: ...` 或 PR label `submodule-rollback-approved` 允许 + audit log
  output:
    gate_verdict: "pass" | "block" | "warn" | "bypass"
    affected_submodules: [{path, master_sha, feature_sha, verdict, override}]
    telemetry_written: <metrics file path>

C.2.5 - Multi-Remote Push Enforcement:
  触发条件:
    - Phase C.2 合并成功 (master 已 fast-forward)
    - 配置 phase_c_integrator.multi_remote_push.enabled: true (默认)
  skill: git-remote-helper (降级: 内联实现)
  action: 见下方 ### C.2.5 详细说明

C.2.6 - UPM Milestone Sub-progress Append (optional):
  触发条件:
    - C.2.5 multi-remote push 已完成 (或跳过)
    - 配置 upm.milestone_driven: true (默认 false，opt-in)
    - 当前 commit 与某 User Story 关联 (commit message 含 US-XXX 或 spec change_id)
  action: 见下方 ### C.2.6 详细说明
  backward_compat: upm.milestone_driven=false 时完全跳过，Phase C 行为与之前完全相同
```

### C.2.4 Pre-Merge Precondition Gate (v1.3.0+)

> **新增于 v1.3.0** — 修复 Forgejo Issue #60 "phase-c-integrator 缺少 pre-merge safety gate"。
> 源于 2026-05-02 SilkNode PR-321 cancel PR-322 main CI Run #3161 (459s 部署观测丢失)。
> Consume aether `--in-flight` primitive (aether-cli #116, SHA `f29abee` 2026-05-06)。

**Naming 命名空间澄清**: phase-c-integrator-level 子步骤标签 (C.2.x) 为 **orchestrator-tier**,与 branch-manager 内部实现层 (也用 C.2.x sequence: C.2.1 sync / C.2.2 push / C.2.3 create-PR / **C.2.4 wait-approval** / C.2.5 merge) 是**独立 label namespace**。本 SKILL §C.2.4 = "pre-merge precondition gate" (orchestrator);branch-manager 内部 C.2.4 = "等待审批" (implementation);同名不同 tier,语义独立。

**触发条件**:
- Phase C.2 action PR 已创建 (PR_NUMBER + PR_URL 已知)
- 即将调用 branch-manager merge action (`auto_merge=true` 自动 / `auto_merge=false` user-triggered)
- 配置 `phase_c_integrator.pre_merge_gate.enabled: true` (默认)

**与 branch-manager 边界** (不重叠):
| Skill | 职责 | 调用顺序 |
|-------|------|----------|
| branch-manager (C.2.1-C.2.3) | sync rebase + push branch + create PR | gate 之前 |
| phase-c-integrator C.2.4 | pre-merge gate 三态判定 | gate (本段) |
| branch-manager (C.2.4-C.2.5) | wait approval + merge API call | gate green 后 |

**执行流程**:

1. **Aether binary pre-flight check**: `aether --help | grep -q "in-flight"` 验证 binary 含 P0-A flag,缺失 → fail-fast 提示 "请升级 aether ≥ commit f29abee (2026-05-06)"
2. **Backend resolution** (v1.31.0+): `resolve_ci_backend(cfg)` 按 config 显式 `ci_backends` 顺序探测,或 fallback 到 BACKENDS list 静态顺序 (Aether-first, GHA-stub-second);所有 backend probe=False → 按 `no_ci_fallback` 配置降级。详见 §C.2.4.X CI Backends
3. **Query main in-flight**: `aether ci status --branch main --in-flight --json` → parse `data.runs[]`
4. **Query PR CI status**: `aether ci status --branch <PR_BRANCH> --json` → parse 最近 run 的 `status` 字段 → 映射为 `passing` / `failing` / `pending`
5. **Verdict 计算** (aria 端):
   - `pr_ci_status in [failing, error]` → `verdict=fail`
   - `pr_ci_status == pending` → `verdict=wait` (PR CI 尚未完成)
   - `pr_ci_status == passing AND main_in_flight_runs == []` → `verdict=green`
   - `pr_ci_status == passing AND main_in_flight_runs != []` → `verdict=wait`
6. **路由决策**:
   - `green` → 调用 branch-manager merge action,进入 C.2.5
   - `wait` → 输出 `wait_recoverable` 错误给 workflow-runner,触发 wait+retry 循环 (见 workflow-runner SKILL.md §wait_recoverable)
   - `fail` → BLOCK + 输出 verdict + raw_message,phase-c-integrator return failure

**Subprocess 调用规范**:
- `subprocess.run(..., timeout=primitive_call_timeout_seconds)` 强制 (默认 30s)
- timeout 触发 → max 3 attempts retry (backoff 5s/15s/45s) → 仍超时则 `fail` verdict
- exit-code 映射 (per-backend, Aether 示例): `0` = success / `1-126` = aether 错误 → `fail` / `127` = binary not found → `no_ci_fallback` / `-SIGTERM` = subprocess timeout → retry → 仍失败则 `fail`。**NIE-propagation 例外 (v1.31.0+, Hard Constraint #7)**: stub backend (e.g. GHA v1.31.0) query 方法 raise `NotImplementedError` → gate **abort** (raise to caller),**不**走 `no_ci_fallback`

**Helper 实现**: `${ARIA_PLUGIN_ROOT:-aria}/skills/phase-c-integrator/scripts/pre_merge_gate.py` (stdlib + subprocess only)

**Output schema**:
```json
{
  "verdict": "green" | "wait" | "fail",
  "pr_ci_status": "passing" | "failing" | "pending",
  "in_flight_runs": [
    {"run_id": 3161, "branch": "main", "started_at": "2026-05-09T12:45:00Z", "elapsed_seconds": 459}
  ],
  "primitive_used": "aether-ci-cli",
  "primitive_version_sha": "f29abee",
  "raw_message": "..."
}
```

**配置参数**:
| 参数 | 默认 | 说明 |
|------|------|------|
| `enabled` | `true` | gate 总开关 (false → 完全跳过 C.2.4,向后兼容) |
| `ci_backends` | `null` (auto-detect) / `[]` (disable) / `[{name: "..."}]` | **v1.31.0+** backend 选择. Alias: 旧 `primitive_preference` 仍读 + deprecation warning |
| `no_ci_fallback` | `"skip_with_warning"` | 无可用 backend 时 (`skip_with_warning` / `abort`). Alias: 旧 `no_aether_fallback` 仍读 + deprecation warning |
| `wait_timeout_seconds` | `1800` | wait+retry max (默认 30 min) |
| `wait_check_intervals` | `[30,60,120,300,300]` | 指数退避 (秒); 数组耗尽后重复 `intervals[-1]` |
| `primitive_call_timeout_seconds` | `30` | 单次 subprocess 调用 timeout |
| `poll_chunk_seconds` | `5` | Ctrl-C polling chunk |

**降级行为**:
- `enabled: false` → 完全跳过 C.2.4 (与 v1.2.0 行为 100% 一致)
- 无可用 backend (所有 backend probe=False, e.g. Aether 未装 + GHA 未 authed) AND `no_ci_fallback: skip_with_warning` → 跳过 + workflow report 警告
- 无可用 backend AND `no_ci_fallback: abort` → BLOCK + 提示安装支持的 CI backend
- 显式禁用 (`ci_backends: []`) → 视为"无可用 backend" 路径,按 `no_ci_fallback` 降级 (canonical way to disable v1.31.0+)
- Stub backend NIE (e.g. `gh` 装但 GHA stub query 未实现) → **不走 fallback,直接 abort** (Hard Constraint #7)
- aether binary 过期 (无 `--in-flight` flag) → fail-fast,**不**继续执行 (避免 silent skip)

**Race condition 处理**: gate 检查与 merge call 之间,main 可能新触发 CI run。窗口最小化 (gate green 后立即调 merge),不消除 race。深度 mitigation 留 future Spec。

---

### C.2.4.X CI Backends (v1.31.0+)

> **新增于 v1.31.0** — 实施 Spec [`aria-ci-backend-abstraction`](../../../openspec/changes/aria-ci-backend-abstraction/proposal.md) (Approved 2026-05-28, post_spec R2 CONVERGED unanimous PASS_WITH_WARNINGS × 3)。源于 2026-05-27 boundary audit P0 C5+C6 — pre_merge_gate.py 去 Aether-only 假设。

**Backend 抽象**: `pre_merge_gate.py` 通过 `aria/skills/phase-c-integrator/scripts/ci_backends/` 包提供的 `CIBackend` ABC + `CIStatus` / `InFlightStatus` dataclass 调用 CI primitive。每个 backend 实现两个 abstract method (`query_pr_ci` / `query_branch_in_flight`) + 一个 ClassVar (`name`) + classmethod `probe()`。

**Supported backends (v1.31.0)**:

| Backend | name | Status | Real implementation? |
|---------|------|--------|---------------------|
| Aether | `aether-ci-cli` | ✅ Default, full | Yes (10CG Lab internal, migrated from v1.30.0 pre_merge_gate.py) |
| GitHub Actions | `github-actions` | 🚧 Stub | No — `probe()` real (`gh` CLI + auth check), `query_*()` raise `NotImplementedError`. Real implementation deferred to v1.32.0+ next cycle |

**Backend selection algorithm** (`resolve_ci_backend(config)`):

```
if config["ci_backends"] is [] (empty list):
    return None  # explicit disable per AC-4.5
elif config["ci_backends"] is non-empty list:
    try each entry in user-specified order, return first probe()=True
elif config["ci_backends"] is None or missing:
    iterate BACKENDS list (Aether → GHA), return first probe()=True
```

**BACKENDS list order** (`ci_backends/__init__.py` static import, Hard Constraint #8):

```python
BACKENDS: list[type[CIBackend]] = [AetherBackend, GitHubActionsBackend]
```

→ Aether-first precedence locked. **不允许** decorator-based registration / `setuptools.entry_points` / 任何 dynamic discovery。

**Config schema example**:

```jsonc
{
  "phase_c_integrator": {
    "pre_merge_gate": {
      "enabled": true,
      "ci_backends": null,                         // auto-detect (default)
      // OR: "ci_backends": [],                    // explicit disable
      // OR: "ci_backends": [{"name": "aether-ci-cli"}],  // explicit list
      "no_ci_fallback": "skip_with_warning",       // when no backend available
      // Legacy alias (auto-translated + DeprecationWarning, removed in v2.0):
      // "primitive_preference": ["aether-ci-cli"],
      // "no_aether_fallback": "skip_with_warning"
    }
  }
}
```

**Hard Constraint #7 (NIE-propagation safety)**:

Stub backend (e.g. `GitHubActionsBackend` in v1.31.0) `probe()` returns True 但 `query_*()` raise `NotImplementedError`。`gate_check()` **必须 propagate NIE to caller**,**不允许** catch-and-route-to-`no_ci_fallback`。理由:防止"装了 `gh` 但实际用 Aether 的项目"因 GHA stub 抢先注册而 Rule #8 静默降级。如需禁用 backend probing,显式设 `ci_backends: []`。

**Probe cache (Hard Constraint #11, Option B)**:

`ci_backends/__init__.py` exports `cached_probe(backend_cls)` + `reset_probe_cache()`。模块-level dict (`_probe_cache`) 缓存 probe 结果。**禁止** `@functools.lru_cache` (test isolation hazard)。测试 setUp/tearDown 必须调 `reset_probe_cache()` 防止状态泄漏。

**Adding a new backend** (e.g. GitLab CI):

1. Create `ci_backends/gitlab_ci.py` 继承 `CIBackend`,实现 `name` / `probe` / `query_pr_ci` / `query_branch_in_flight` (optionally `precheck`)
2. Update `ci_backends/__init__.py` 加 import + 加到 `BACKENDS` list (位置决定 precedence)
3. 加 unit tests 在 `tests/test_ci_backends.py`
4. 加 doc entry in this table

**NIE 是 stub 临时状态**: 如果新 backend 计划只做 stub,所有 `query_*()` 必须 raise `NotImplementedError` 带 operable message (含 `"PR welcome"` 提示 + 显式 disable instructions per `ci_backends: []`)。Hard Constraint #4 + AC-2.5 enforced via test。

---

### C.2.4.5 Submodule Pointer Regression Gate (v1.28.0+)

> **新增于 v1.28.0** — 实施 Spec [`aria-submodule-pointer-regression-gate`](../../../openspec/changes/aria-submodule-pointer-regression-gate/proposal.md) (Approved 2026-05-24, DEC-20260524-002)。
> 源于 2026-05-23 PR #123 silent submodule pointer regression incident (`6fea5d7` 静默回滚 4 commits, 被 post-merge audit catch + fast-forward fix `a8e0096`)。
> Closes Forgejo Aria [#124](https://forgejo.10cg.pub/10CG/Aria/issues/124)。

**Two-phase rollout** (✅ flipped to block default in v1.49.0, 2026-06-21):
- **v1.28.0** (history): `mode=warn` 默认 — 检测 + 日志 `WOULD-BLOCK`, 不阻止 merge
- **v1.49.0+** (current): `mode=block` 默认 — 检测到 regression/divergence + 无 override → 拒绝 merge
- Flip 依据: hard-date Trigger B + minimum-observation guard ≥3 gate executions (实测 5, all warn-PASS) + tripwire green (4 clean host-cron) + FP 0%; owner risk-accept sign-off 2026-06-21。决策记录见 `.aria/decisions/2026-06-21-v1.49.0-block-flip.md` (主仓)。

**触发条件**:
- §C.2.4 verdict=green (CI gate 已通过)
- 即将调用 branch-manager merge action
- 配置 `phase_c_integrator.submodule_gate.mode`: `"block"` (v1.49.0+ default) | `"warn"` (legacy opt-out) | `"off"` (skip 完全)

**执行流程** (Bash gate, 见 `scripts/submodule_gate.sh`):

```bash
# Step 1: fail-loud fetch with bounded retries (1s/2s/4s × 3 attempts)
# Drop fragile `grep success patterns` — use exit code only (AD-FOLLOWUP-1)
BEFORE_REMOTE=$(git rev-parse origin/master 2>/dev/null || echo "FIRST_RUN")

for delay in 1 2 4; do
    if git fetch origin 2>&1; then FETCH_OK=1; break; fi
    sleep "$delay"
done
[[ "${FETCH_OK:-0}" != 1 ]] && {
    log_telemetry "FETCH_FAILURE" "$BEFORE_REMOTE" "(unknown)" "fetch_exhausted_retries"
    echo "BLOCK: git fetch origin failed after 3 attempts" >&2
    exit 1
}

# Step 2: refspec assertion (skip on FIRST_RUN)
AFTER_REMOTE=$(git rev-parse origin/master)
if [[ "$BEFORE_REMOTE" != "FIRST_RUN" && "$BEFORE_REMOTE" != "$AFTER_REMOTE" ]]; then
    if ! git merge-base --is-ancestor "$BEFORE_REMOTE" "$AFTER_REMOTE" 2>/dev/null; then
        echo "BLOCK: origin/master rewritten (non-ancestor advance) — operator confirm required" >&2
        exit 1
    fi
fi

# Step 3: per-submodule loop
exit_code=0
while IFS= read -r SUB; do
    [[ -z "$SUB" ]] && continue
    git -C "$SUB" fetch origin 2>&1 >/dev/null || true

    FEATURE_PTR=$(git ls-tree HEAD "$SUB" | awk '{print $3}')
    MASTER_PTR=$(git ls-tree origin/master "$SUB" | awk '{print $3}')

    # nil-SHA: first-time submodule (master had no gitlink)
    [[ -z "$MASTER_PTR" ]] && {
        echo "INFO: $SUB first introduced this PR (no prior master gitlink); gate PASS"
        continue
    }
    # No-change
    [[ "$FEATURE_PTR" == "$MASTER_PTR" ]] && {
        echo "OK: $SUB unchanged"
        continue
    }

    echo "GATE: submodule=$SUB master=$MASTER_PTR feature=$FEATURE_PTR"

    # Forward bump?
    if git -C "$SUB" merge-base --is-ancestor "$MASTER_PTR" "$FEATURE_PTR" 2>/dev/null; then
        echo "PASS: $SUB forward bump"
        continue
    fi

    # Distinguish regression vs divergent
    if git -C "$SUB" merge-base --is-ancestor "$FEATURE_PTR" "$MASTER_PTR" 2>/dev/null; then
        VERDICT="REGRESSION"
    else
        VERDICT="DIVERGENT"
    fi

    # Check override (commit trailer OR PR label)
    if check_override "$SUB" "$MASTER_PTR" "$FEATURE_PTR"; then
        echo "ALLOW: $SUB $VERDICT overridden (audit logged)"
        log_override "$SUB" "$VERDICT" "$MASTER_PTR" "$FEATURE_PTR"
        continue
    fi

    # Mode dispatch
    MODE="${ARIA_SUBMODULE_GATE_MODE:-block}"
    if [[ "$MODE" == "warn" ]]; then
        echo "WOULD-BLOCK: submodule=$SUB master=$MASTER_PTR feature=$FEATURE_PTR reason=$VERDICT"
        log_warn "$SUB" "$VERDICT" "$MASTER_PTR" "$FEATURE_PTR"
    else
        echo "BLOCK: $VERDICT — submodule=$SUB master=$MASTER_PTR feature=$FEATURE_PTR" >&2
        echo "       Override 1: commit trailer 'Submodule-Rollback: $SUB $MASTER_PTR->$FEATURE_PTR reason=<reason>'" >&2
        echo "       Override 2: PR label 'submodule-rollback-approved'" >&2
        log_block "$SUB" "$VERDICT" "$MASTER_PTR" "$FEATURE_PTR"
        exit_code=1
    fi
done < <(git config --file .gitmodules --get-regexp '^submodule\..*\.path$' 2>/dev/null | awk '{print $2}')

exit $exit_code
```

**Override mechanism** (per-PR explicit, NOT sticky config):

1. **Commit trailer** in merge commit message (accepts both Unicode `→` and ASCII `->`):
   ```
   Submodule-Rollback: aria a8e0096→3b688a9 reason=v1.24.1 introduced critical regression
   Submodule-Rollback: aria a8e0096->3b688a9 reason=同 (ASCII alternative for LANG=C/POSIX safety)
   ```
   Parser resolves short SHAs (≥7 chars) via `git rev-parse` before comparison to FEATURE/MASTER pointers. Mismatched SHAs in trailer → reject override.

2. **PR label** `submodule-rollback-approved` (settable only by repo maintainers via Forgejo):
   - Fetched via `forgejo GET /repos/<owner>/<repo>/issues/<PR>/labels`
   - On API failure: treat as no-label (gate proceeds to mode dispatch)

3. Override audit log to `metrics/submodule-gate-overrides.jsonl` (JSONL append-only, race-safe):
   ```json
   {"timestamp":"...","pr_id":N,"submodule":"...","master_sha":"...","feature_sha":"...","verdict":"REGRESSION","reason":"...","override_type":"trailer"|"label"}
   ```

**Verdict 三态** (output):
- `pass` — all submodules: forward / no-change / first-time
- `warn` (legacy opt-out) — WOULD-BLOCK logged, merge proceeds
- `block` (v1.49.0+ default) — merge refused, exit 1
- `bypass` — override applied, audit logged, merge proceeds

**Output schema** (JSON):
```json
{
  "verdict": "pass" | "warn" | "block" | "bypass",
  "affected_submodules": [
    {
      "path": "aria",
      "master_sha": "a8e0096",
      "feature_sha": "3b688a9",
      "verdict": "REGRESSION",
      "override": "trailer" | "label" | null
    }
  ],
  "telemetry_files": {
    "warns": "metrics/submodule-gate-warns.jsonl",
    "overrides": "metrics/submodule-gate-overrides.jsonl",
    "blocks": "metrics/submodule-gate-blocks.jsonl",
    "misses": "metrics/submodule-gate-misses.jsonl"
  }
}
```

**配置参数**:
| 参数 | 默认 | 说明 |
|------|------|------|
| `mode` | `"block"` (v1.49.0+ default) / `"warn"` (legacy) / `"off"` | `"warn"` 仅日志 / `"block"` 拒绝 merge / `"off"` 跳过 gate |
| `fetch_retries` | `[1, 2, 4]` | 指数退避秒数 |
| `metrics_dir` | `"metrics/"` (relative to aria-plugin root, NOT main repo) | 4 JSONL append-only 文件位置 |
| `forgejo_api_timeout_s` | `5` | PR label fetch timeout |
| `nil_sha_action` | `"pass_with_info"` | first-time submodule (master 无 gitlink) → PASS + INFO log |

**降级行为**:
- `mode: off` → 完全跳过 §C.2.4.5 (与 v1.27.x 行为 100% 一致, 用于紧急 bypass 全 cycle)
- `git fetch origin` 3-attempt failure → terminal block (per `wait_recoverable` pattern, owner remediation: 检查 auth/network/URL drift)
- `git ls-tree` empty output (nil-SHA case) → PASS + INFO (first-time submodule case)
- `git merge-base --is-ancestor` exit 128 (SHA not in submodule DB after fetch) → BLOCK + "submodule fetch incomplete, retry" hint

**Performance budget**:
- Warm cache (local dev): ~310ms per submodule × 3 submodules ≈ ~930ms (well under §C.2.4 ~3-5s)
- CI cold-path: ~610-2110ms per submodule × 3 submodules ≈ ~1.8-6.3s (slightly higher than §C.2.4, ~comparable). Bounded retries on fetch failure add up to 7s only when fetch fails (excluded from steady-state budget).
- Phase B may add background-subshell parallel submodule loop if CI dogfood shows >5s sustained.

**Race condition 处理** (per backend-architect R3 missing scenario):
- Concurrent force-push to `origin/master` during gate execution: refspec assertion (Step 2) compares BEFORE/AFTER rev-parse
- Ancestry-forward change → continue (legitimate)
- Non-ancestor history rewrite → abort with operator confirm
- Deterministic pre-staged fixture in T-replay-9 validates detection logic (not true concurrency)

**Tripwire** (mechanical detection of (B+) gate misses):
- Weekly Forgejo Actions workflow at `.forgejo/workflows/submodule-gate-tripwire.yml` in `10CG/Aria` main repo (NOT `aria/cron/` in aria-plugin)
- Compares master HEAD~1 vs HEAD submodule gitlinks ancestry
- On regression escaped (B+) → append to `metrics/submodule-gate-misses.jsonl` + file Forgejo issue with label `gate-tripwire-count`
- Auto-promote (A) post-merge detector without re-brainstorm if any tripwire condition met:
  1. Regression escapes (B+) within 12 months OR 100 merges (whichever first)
  2. (B+) fetch-failure incident manifests
  3. Non-PR-flow regression (direct master push bypassing PR)
- v1.28.0 ships workflow as `on: workflow_dispatch` only; tripwire periodic execution migrated to **host-cron** (`0 4 * * 0`, v1.41.0 R-fix-2 — Actions runner 无 forgejo 凭据 + CF Access 墙; standalone `scripts/submodule-tripwire-audit.sh`). v1.49.0 block-flip 依赖 host-cron tripwire (4 clean runs) 作独立兜底, 非 workflow cron

**Helper 实现**: `${ARIA_PLUGIN_ROOT:-aria}/skills/phase-c-integrator/scripts/submodule_gate.sh` (Bash, stdlib + git only)

**Cross-references**:
- Spec: `openspec/changes/aria-submodule-pointer-regression-gate/proposal.md`
- DEC: `.aria/decisions/2026-05-24-aria-124-submodule-pointer-regression-gate.md`
- Convention doc: `standards/conventions/submodule-pointer-hygiene.md` (zero-code companion, NOT numbered Rule)
- Forgejo Aria #124
- Source incident: PR #123 merge `6fea5d7` + fast-forward fix `a8e0096`

---

### C.2.5 Multi-Remote Push Enforcement (v1.15.0+)

**触发条件**:
- Phase C.2 合并成功 (master 已 fast-forward)
- 配置 `phase_c_integrator.multi_remote_push.enabled: true` (默认)

**与 branch-manager 边界** (不重叠):
| Skill | 职责 | Remote 范围 |
|-------|------|-----------|
| branch-manager (C.2 PR 发起前) | 推送 feature 分支 + 创建 PR | 仅 origin |
| phase-c-integrator C.2.5 (PR 合并后) | 推送 master + 多 remote SHA 验证 | 所有 enforced remote |

**执行流程**:
1. 快照 `expected_sha = git rev-parse HEAD` (合并后本地 master HEAD)
2. 枚举子模块: `git submodule status --recursive`
3. 确定 `ENFORCED_REMOTES`: skill 级 `enforced_remotes == null` 时继承顶层 `multi_remote.enforced_remotes`, 空则自动发现所有 remote
4. **Per-Remote Matrix Gating** (对每个 REMOTE ∈ ENFORCED_REMOTES):
   - a. 遍历子模块, 调用 `git-remote-helper.push_all_remotes(SUBMODULE.path, SUBMODULE.branch, [REMOTE])`
   - b. 子模块推 REMOTE 任一失败 → 按失败优先级决策 (见下), 阻断则跳过本 REMOTE 的主仓库推送
   - c. 子模块全部成功 → 调用 helper.push_all_remotes(main_repo, branch, [REMOTE])
   - d. 主仓库推送成功 → 调用 helper.verify_parity_post_push(main_repo, branch, expected_sha, [REMOTE])
   - e. verify match=false → 同优先级决策
5. 所有 REMOTE 处理完毕, 全部通过 → 进入 Phase D
6. 任一阻断 → 输出具体失败 remote + 修复命令 (`git -C <path> push <remote> <branch>`)

**失败优先级** (决策表):
| 条件 | 行为 |
|------|------|
| remote ∈ `read_only_remotes` | warning 降级, 继续 (最高优先级) |
| `fail_on_partial_push: false` + 非 read_only | warning, 继续 |
| `fail_on_partial_push: true` + 非 read_only (默认) | **阻断**, 输出修复命令 |

**Per-Remote Matrix 示例**:
```
origin: sub1 ✅ sub2 ✅ main ✅ (已推)
github: sub1 ✅ sub2 ❌ (network timeout) → 跳过 main github; 但 origin 已完成
```

**子模块 detached HEAD**: 沿用 helper canonical (`detached_head: true` + HEAD SHA 比较), 警告但不阻断。

**降级策略**: 检测 `test -f "${ARIA_PLUGIN_ROOT:-aria}/skills/git-remote-helper/SKILL.md"` 存在性 (路径相对项目根; `ARIA_PLUGIN_ROOT` 环境变量优先)。不可用时用内联降级 (不重试, 简化实现), schema 仍一致。

**Race condition 处理**: verify 4 次 attempt 全部 match=false 默认阻断, 记录 "possible race condition"。

---

### C.2.6 UPM Milestone Sub-progress Append (v1.16.0+)

> **新增于 v1.16.0** — 修复 Forgejo #22 "multi-PR cycle UPM 信息盲区"问题。
> 源于 M1 closeout (2026-04-23) single-D.1 一次性更新 85 tasks 的实际痛点
> + silknode US-074 multi-PR migration 场景。

**触发条件**:
- C.2.5 已完成 (或已跳过)
- 配置 `upm.milestone_driven: true`
- commit message 或 spec change_id 中包含 `US-XXX` 模式

**关联识别逻辑**:

```bash
# 1. 从 commit message 中提取 US 编号
#    示例: "feat(m1): T4 complete — DEMO-001 E2E SUCCESS" 含 US-021 前缀
US_REF=$(git log -1 --format="%s %b" | grep -oE 'US-[0-9]+' | head -1)

# 2. 如果 commit message 无 US-XXX，尝试从 spec change_id 推断
if [ -z "$US_REF" ] && [ -n "$SPEC_CHANGE_ID" ]; then
  US_REF=$(grep -r "$SPEC_CHANGE_ID" openspec/changes/ \
    --include="proposal.md" -l | \
    xargs grep -oE 'US-[0-9]+' | head -1)
fi
```

**执行动作**:

```bash
# 获取当前 commit 信息
COMMIT_SHA=$(git rev-parse --short HEAD)
COMMIT_DATE=$(date +%Y-%m-%d)
COMMIT_TITLE=$(git log -1 --format="%s")
PR_URL="${PR_URL:-}"  # 来自 C.2 输出，无则留空

# 构造 sub-bullet
if [ -n "$PR_URL" ]; then
  SUB_BULLET="  - ${COMMIT_DATE}: ${COMMIT_SHA} — ${COMMIT_TITLE} (${PR_URL})"
else
  SUB_BULLET="  - ${COMMIT_DATE}: ${COMMIT_SHA} — ${COMMIT_TITLE}"
fi

# 定位 UPM 文档中对应 US 行并追加 sub-bullet
UPM_FILE=$(find . -name "unified-progress-management.md" \
  -not -path "*/archive/*" | head -1)

if [ -n "$UPM_FILE" ] && [ -n "$US_REF" ]; then
  # 将 [ ] IN_PROGRESS 更新为 [~] IN_PROGRESS (如当前状态为 [ ])
  sed -i "s/\[ \] \(.*${US_REF}.*\)/[~] \1/" "$UPM_FILE"
  # 在 US 行下方追加 sub-bullet
  sed -i "/.*${US_REF}.*/a\\${SUB_BULLET}" "$UPM_FILE"
fi
```

**状态标记约定**:

| 标记 | 含义 | 触发时机 |
|------|------|----------|
| `[ ]` | 未开始 / IN_PROGRESS (原有) | 初始状态 |
| `[~]` | 进行中，有中间进度记录 | C.2.6 首次追加时自动升级 |
| `[x]` | COMPLETED | D.1 final pass 写入 |

**sub-bullet 格式示例**:

```markdown
- [~] US-021: M1 MVP Layer 2 实现
  - 2026-04-20: abc1234 — feat(m1): T1 infra complete (https://forgejo.../pulls/18)
  - 2026-04-22: def5678 — feat(m1): T3 orchestrator ready (https://forgejo.../pulls/19)
  - 2026-04-23: ghi9012 — test(m1): T5 DEMO E2E complete (https://forgejo.../pulls/20)
```

**DoD**:
- `upm.milestone_driven=true` 时: UPM 文档对应 Story 行下出现 sub-bullet，状态从 `[ ]` 升级为 `[~]`
- `upm.milestone_driven=false` (默认) 时: Skill 无行为变化，完全向后兼容

**配置示例** (`.aria/config.json`):

```yaml
upm:
  milestone_driven: false  # 默认 false，保留 D.1-only 现有行为
                           # 设为 true 启用 C.2.6 中间进度追加
```

---

### 输出

```yaml
success: true
steps_executed: [C.1, C.2]
steps_skipped: []
results:
  C.1:
    commit_sha: "abc1234"
    commit_message: "feat(auth): 添加用户认证..."
  C.2:
    pr_url: "https://..."
    pr_number: 123

context_for_next:
  commit_sha: "abc1234"
  pr_url: "https://..."
```

---

## emergency hotfix: pre_merge → convergence (#58, v1.35.0)

当本 cycle 走 emergency_hotfix lane (state-scanner `emergency_hotfix` 规则触发, `hotfix/*` 分支) 时, C.2 的 pre_merge audit 调用点 **仅 `audit.enabled=true` 且 `audit.checkpoints.pre_merge != "off"` 时**, 把 audit mode 降级到 **convergence** (不 challenge) —— prod 紧急修复不必跑 15-30min challenge ceremony。

- advisory: phase-c-integrator 在 pre_merge 调 audit-engine 时传 emergency_hotfix lane 信号, audit-engine 据此 + file-scope 过滤共同 resolve 最终 mode (双降级幂等, 都 → convergence)。
- C.2.4 pre-merge precondition gate (CI passing 等) **不豁免** —— hotfix 仍须过 Rule #8 CI gate (紧急不等于跳 CI 验证)。
- 详见 [audit-engine SKILL.md](../audit-engine/SKILL.md) §emergency hotfix lane。

---

## Context 占用感知 (合并前长会话, #104)

C.2 合并前若会话已很长 (多 cycle 累积), 用 [aria-context-monitor](../aria-context-monitor/SKILL.md) 判断"本 cycle 收尾后是否该暂停换会话", 避免 pre-merge gate 等待期硬撞 context 上限丢上下文:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-aria}/skills/aria-token-telemetry/scripts/token_telemetry.py" --project-root .
```

`used_percentage` (relay 路径) `>85%` → 建议 merge 完成后即暂停 + 写 handoff。advisory, 不自动中断。详见 phase-b-developer 同名章节。

**会话收尾触发** (session-closer TASK-007): merge 完成后调 [closeout_trigger](../session-closer/scripts/closeout_trigger.py)(`--telemetry-json .aria/cache/context-window.json`)—— 占用 ≥ 阈值 + 有未交接成果时 advise `/session-closer`(advisory, 不自动执行)。

---

## 跳过规则

| 条件 | 跳过步骤 | 检测方法 |
|------|---------|----------|
| 无变更 | C.1 | git status --porcelain 为空 |
| 不需要 PR | C.2 | 配置或分支策略 |
| 直接推送 | C.2 | 在 develop 分支 |

### 跳过逻辑

```yaml
skip_evaluation:
  C.1:
    - check: git status --porcelain
      skip_if: empty
      reason: "没有需要提交的变更"

  C.2:
    - check: branch_name
      skip_if: in [develop, main]
      reason: "主分支不需要 PR"

    - check: config.create_pr
      skip_if: false
      reason: "配置为不创建 PR"
```

---

## 输出格式

```
╔══════════════════════════════════════════════════════════════╗
║              PHASE C - INTEGRATION                           ║
╚══════════════════════════════════════════════════════════════╝

📋 执行计划
───────────────────────────────────────────────────────────────
  C.1 commit-msg-generator  → Git 提交
  C.2 branch-manager        → 创建 PR

🚀 执行中...
───────────────────────────────────────────────────────────────
  ✅ C.1 完成 → Commit: abc1234
     Message: feat(auth): 添加用户认证 / Add user authentication

  ✅ C.2 完成 → PR #123 已创建
     URL: https://github.com/...

📤 上下文输出
───────────────────────────────────────────────────────────────
  commit: abc1234
  pr: #123
  ready_for: Phase D (可选)
```

---

## 使用示例

### 示例 1: 完整集成

```yaml
输入:
  context:
    branch_name: "feature/add-auth"
    test_results: { passed: true }

执行:
  C.1: 提交代码 → abc1234
  C.2: 创建 PR → #123

输出:
  commit_sha: "abc1234"
  pr_url: "https://..."
```

### 示例 2: 仅提交

```yaml
输入:
  config:
    create_pr: false

执行:
  C.1: 提交代码
  C.2: 跳过 (不需要 PR)

输出:
  steps_skipped: [C.2]
  commit_sha: "abc1234"
```

### 示例 3: 直接推送

```yaml
输入:
  context:
    branch_name: "develop"  # 在主分支

执行:
  C.1: 提交代码
  C.2: 跳过 (主分支不需要 PR)
  额外: git push

输出:
  commit_sha: "abc1234"
  pushed: true
```

---

## 提交消息增强

### 增强标记格式

```
feat(auth): 添加用户认证 / Add user authentication

- 实现 JWT token 验证
- 添加登录 API 端点

🤖 Executed-By: mobile-developer subagent
📋 Context: Phase4-Cycle9 功能开发
🔗 Module: mobile
```

### 标记来源

| 标记 | 来源 |
|------|------|
| 🤖 Executed-By | 执行的 Agent 类型 |
| 📋 Context | Phase/Cycle + 任务描述 |
| 🔗 Module | 活跃模块名 |

---

## 错误处理

| 错误 | 原因 | 处理 |
|------|------|------|
| 提交失败 | hook 拒绝 | 显示 hook 错误，提示修复 |
| PR 创建失败 | 权限问题 | 提示检查权限 |
| 推送失败 | 远程冲突 | 提示拉取最新代码 |

### Hook 失败处理

```yaml
on_commit_hook_failure:
  action: stop
  report:
    - Hook 错误信息
    - 缺少的标记或格式问题
  next_step: "使用 commit-msg-generator 重新生成消息"
```

---

## branch-finisher 集成 (v1.1.0)

> **新增于 v1.1.0** - 集成 branch-finisher 完成流程

### 完成选项处理

```yaml
completion_option_handling:
  "[1] 提交并创建 PR":
    action: 执行完整 Phase C
    steps: [C.1, C.2]
    worktree_cleanup: 在 PR 创建后询问

  "[2] 继续修改":
    action: 跳过 Phase C
    steps: []
    reason: "用户选择继续修改，不进入集成阶段"

  "[3] 放弃变更":
    action: 跳过 Phase C
    steps: []
    reason: "变更已放弃，无需集成"
    worktree_cleanup: 强制执行

  "[4] 暂停保存":
    action: 跳过 Phase C
    steps: []
    reason: "用户选择暂停，稍后恢复"
```

### 入口前置检查

```yaml
pre_check:
  # 检查 branch-finisher 输出
  completion_option:
    required: true
    valid_for_phase_c: [1]  # 只有选项 1 进入 Phase C

  # 检查测试验证结果
  validation_report:
    required: true
    must_pass: true
    warn_on: warnings > 0

  # 检查 Worktree 状态
  worktree_path:
    check: if exists
    action: 记录，用于后续清理
```

### 集成流程增强

```yaml
enhanced_flow:
  1. 接收 branch-finisher 输出
     ├── completion_option
     ├── validation_report
     └── worktree_path (可选)

  2. 前置检查
     ├── 验证 completion_option == 1
     ├── 验证 validation_report.passed
     └── 记录 worktree_path

  3. 执行 C.1 (提交)
     ├── 使用 commit-msg-generator
     ├── 包含增强标记
     └── 关联 task_id

  4. 执行 C.2 (PR)
     ├── 使用 branch-manager
     ├── 创建 PR
     └── 包含测试验证结果

  5. Worktree 清理决策
     ├── PR 创建成功?
     ├── 询问用户是否清理
     └── 执行清理或保留
```

### Worktree 清理时机

```yaml
worktree_cleanup_timing:
  trigger: PR 创建成功后
  default: 询问用户
  options:
    - "[1] 立即清理 (推荐)"
    - "[2] 保留 worktree"

  auto_cleanup_if:
    - PR merged
    - PR closed
```

### 输出增强

```yaml
context_for_next:
  # 原有字段
  commit_sha: "abc1234"
  pr_url: "https://..."
  pr_number: 123

  # v1.1.0 新增字段
  completion_option: 1
  worktree_status: "cleaned" | "preserved"
  validation_summary:
    passed: true
    warnings: 1
```

---

## 与其他 Phase 的关系

```
phase-b-developer
    │
    │ context:
    │   - branch_name
    │   - test_results
    ▼
branch-finisher (v1.1.0 新增)
    │
    │ context:
    │   - completion_option
    │   - validation_report
    │   - worktree_path
    ▼
phase-c-integrator (本 Skill)
    │
    │ context_for_next:
    │   - commit_sha
    │   - pr_url
    │   - worktree_status
    ▼
phase-d-closer
```

---

## 相关文档

### 核心技能

- [commit-msg-generator](../commit-msg-generator/SKILL.md) - C.1 提交生成
- [branch-manager](../branch-manager/SKILL.md) - C.2 PR/合并

### 集成技能 (v1.1.0 新增)

- [branch-finisher](../branch-finisher/SKILL.md) - 完成流程入口

### Phase 关联

- [phase-b-developer](../phase-b-developer/SKILL.md) - 上一阶段
- [phase-d-closer](../phase-d-closer/SKILL.md) - 下一阶段

---

**最后更新**: 2026-03-27
**Skill版本**: 1.2.0
