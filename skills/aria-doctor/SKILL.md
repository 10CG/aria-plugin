---
name: aria-doctor
description: |
  Aria 环境健康诊断器。检测 aria-plugin 默认 hook 安装状态、配置一致性,
  辅助 owner 决策本地 copy 与 plugin SOT 的清理时机。

  使用场景:"诊断 aria 安装状态"、"check secret-guard install"、
  "dual install 状态"、"何时清理 local copy"、"plugin hook 没加载"
disable-model-invocation: false
user-invocable: true
---

# aria-doctor

> **Version**: 1.0.0 (initial — ships with aria-plugin v1.24.0)
> **Status**: Active
> **Spec**: `openspec/archive/<date>-aria-secret-guard-plugin-default`

---

## Functions

### `check_secret_guard_install()`

检测 aria-plugin secret-guard hook 当前安装状态(plugin SOT vs project-local
copy),返回 **5 primary state** + **2 sub-flag** + 含意建议的 advisory 文本。

**Script**: `scripts/check_secret_guard_install.sh`

**Usage**:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/aria-doctor/scripts/check_secret_guard_install.sh \
  [PROJECT_DIR] [PLUGIN_ROOT]
```

| Arg | Default | 含义 |
|-----|---------|------|
| `PROJECT_DIR` | `$CLAUDE_PROJECT_DIR` or `$PWD` | 要检测的项目根目录 |
| `PLUGIN_ROOT` | `$CLAUDE_PLUGIN_ROOT` or derived from script location | aria-plugin 根目录 |

**Output** (single-line compact JSON):

```json
{
  "state": "<primary>",
  "sub_flags": ["<flag>", ...],
  "advisory": "<human-readable text>",
  "details": {
    "plugin_hook_present": true|false,
    "local_hook_present": true|false,
    "settings_json_valid": true|false,
    "plugin_version": "1.24.0" | null,
    "local_version": "1.2.0" | null,
    "plugin_sha256": "<hex>" | null,
    "local_sha256": "<hex>" | null,
    "plugin_hook_path": "<abs path>",
    "local_hook_path": "<abs path>"
  }
}
```

**Exit code**:

| Exit | 含义 |
|------|------|
| 0 | 检测成功 (任意 state, 包括 `corrupted_settings`) |
| 2 | 使用错误 (plugin root 不可解析等) |

---

## State Schema

> **Source-of-truth**: `aria/skills/aria-doctor/scripts/check_secret_guard_install.sh`
> 任何后续 minor 修改 **只可 append** sub-flag, **不可重命名 / 删除** primary state
> (per memory `feedback_deterministic_structural_skill_rule6_substitute` atomicity guard)。
> 详见 [`atomicity-guard.md`](../../../aria-plugin-benchmarks/ab-results/2026-05-23-aria-secret-guard-plugin-default-structural/atomicity-guard.md)。

### 5 Primary states (mutually exclusive)

| State | 触发条件 | 是否 expected 状态 |
|-------|----------|-------------------|
| `not_installed` | 既无 plugin hook 也无 local hook | ❌ assert-never under normal execution |
| `single_plugin` | 仅 plugin hook 加载,无 local copy | ✅ 新项目预期态 (v1.24.0+ onboard) |
| `single_local` | 仅 local copy + `.claude/settings.json` 注册,plugin hook 未加载 | ⚠️ 异常 — 见 advisory |
| `dual_install` | plugin + local 并存 | ✅ Layer 2 ship 后 Aria self / SilkNode 预期态(双重防线) |
| `corrupted_settings` | `.claude/settings.json` JSON 解析失败 | ❌ 异常 — 优先级最高(mutex 覆盖其他 state) |

### 2 Sub-flags (only attached to `dual_install`)

| Sub-flag | 触发条件 | 含义 |
|----------|----------|------|
| `stale_local_version` | local banner version < plugin SOT version (semver compare) | local 是较旧 upstream snapshot,可同步或删除 |
| `divergent_content` | SHA256(local) != SHA256(plugin) | 内容差异,可能 owner 本地有定制(查清再清理) |

> 两个 sub-flag 可同时存在。若 banner 无法解析(见 NF2 ban-missing edge),
> `stale_local_version` **不触发**(undefined version → skip),只 `divergent_content`
> 通过 SHA 比对触发。

### Advisory text per state

| State | Sub-flag(s) | Advisory key message |
|-------|-------------|----------------------|
| `not_installed` | — | "assert-never under normal plugin-loaded execution" + verify `CLAUDE_PLUGIN_ROOT` |
| `single_plugin` | — | "Expected state for new projects after v1.24.0" |
| `single_local` | — | **(R2 BA N2)** "plugin not loaded? OR aria-plugin version < v1.24.0" + run full check |
| `dual_install` | (none) | "Double defense active — KEEP recommended ≥1 minor cycle as fallback" |
| `dual_install` | `divergent_content` only | "May indicate owner-local customization; preserve via Path 2 ack OR sync" |
| `dual_install` | `stale_local_version + divergent_content` | "Older upstream snapshot — sync from plugin SOT or delete local copy" |
| `corrupted_settings` | — | "Fix JSON or remove `.claude/settings.json`; plugin SOT still loads via plugin path" |

---

## Banner regex spec (R2 QA NF2 closure)

Project-local `secret-guard.sh` copy **可选** 包含版本 banner(在文件头 20 行内
任一行匹配):

```regex
^# (Aria(-plugin)?|secret-guard)[^\n]*\bv([0-9]+\.[0-9]+\.[0-9]+)\b
```

**示例 — 匹配**:

```bash
# Aria-plugin secret-guard hook v1.24.0
# secret-guard.sh v1.2.0 (SilkNode upstream)
# Aria secret-guard v1.24.0+ (some narrative tail)
```

**示例 — 不匹配** (banner-missing edge case):

```bash
# PreToolUse hook (no version banner — SilkNode HEAD shape)
#  v1.24.0 missing leading "# Aria/secret-guard" prefix
# Aria something v1.24 (only 2-part semver, regex requires X.Y.Z)
```

**Behavior on no match**:
- `local_version` field → `null`
- `stale_local_version` sub-flag → **NOT set** (undefined,不与 plugin 版本比较)
- `divergent_content` sub-flag → 仍由 SHA256 决定 (与 banner 独立)

> **Why optional banner**: SilkNode HEAD scripts 当前无 banner。强制 banner
> 会破坏"bytewise identical to SilkNode HEAD"的 cherry-pick 契约 (TASK-001
> 验证要求)。Banner-missing 是 graceful fallback,非错误。

---

## Atomicity guard (Rule #6 structural substitute)

aria-doctor 是 **deterministic structural skill** — 输入(filesystem state)
→ 输出(JSON state object)是 pure function,无 LLM 创意空间。因此 Rule #6
benchmark 用 **structural substitute** 而非 `/skill-creator` LLM AB
(per memory `feedback_deterministic_structural_skill_rule6_substitute`)。

**Substitute artifacts** (Rule #6 closure, 详见 `aria-plugin-benchmarks/ab-results/2026-05-23-aria-secret-guard-plugin-default-structural/`):

| Artifact | 用途 |
|----------|------|
| [`README.md`](../../../aria-plugin-benchmarks/ab-results/2026-05-23-aria-secret-guard-plugin-default-structural/README.md) | substitute 框架说明 + 8 test case 覆盖映射 + 5-state ↔ test 对应表 |
| [`atomicity-guard.md`](../../../aria-plugin-benchmarks/ab-results/2026-05-23-aria-secret-guard-plugin-default-structural/atomicity-guard.md) | schema 演进 contract:append-only sub-flag,不删/重命名 primary state |
| [`dogfood-evidence.md`](../../../aria-plugin-benchmarks/ab-results/2026-05-23-aria-secret-guard-plugin-default-structural/dogfood-evidence.md) | Aria self in-vivo dogfood run (TASK-007 link) + state 分布 + ship gate verdict |

---

## Tests

```bash
bash aria/skills/aria-doctor/tests/check_secret_guard_install.test.sh
```

| Test | State | Sub-flags | 验证目标 |
|------|-------|-----------|---------|
| 1 | `not_installed` | — | R2 BA N1: assert-never 状态可达 (mis-resolved plugin root) |
| 2 | `single_plugin` | — | 新项目 onboard 路径 |
| 3 | `single_local` | — | R2 BA N2: advisory 含两 cause (plugin 未加载 OR version <v1.24.0) |
| 4 | `dual_install` | — | clean path, KEEP advisory |
| 5 | `dual_install` | `stale + divergent` | 两 flag 同时触发 |
| 6 | `dual_install` | `divergent` only | 同版本但内容差异 (owner customization) |
| 7 | `corrupted_settings` | — | 优先级 (mutex over dual_install) |
| 8 | `dual_install` | `divergent` only | **R2 QA NF2**: banner-missing edge — `stale_local_version` NOT set |

**Latest run**: 8/8 PASS (initial implementation,2026-05-23)。

---

## Refs

- **Spec**: `openspec/archive/<date>-aria-secret-guard-plugin-default/proposal.md` §State Schema for aria-doctor
- **Convention**: `standards/conventions/secret-hygiene.md` §6 Local copy + plugin coexist 模式
- **Parent decision**: `.aria/decisions/2026-05-20-secret-rotation-during-m5-deploy.md` §5 (Layer 3 决议)
- **Brainstorm**: `.aria/decisions/2026-05-22-aria-secret-guard-plugin-default-brainstorm.md`
- **Memory**:
  - `feedback_deterministic_structural_skill_rule6_substitute` (Rule #6 substitute pattern)
  - `feedback_claude_code_hook_merge_all_fire` (Q1 hook orchestrator 实证)

---

## Version history

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-05-23 | Initial — `check_secret_guard_install()` 5-state schema + 2 sub-flag + 8 unit tests + banner regex spec + atomicity guard. Ships with aria-plugin v1.24.0. |
