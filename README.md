**English** | [中文](README.zh.md)

# Aria Plugin

> **Version**: 1.62.0 | **Released**: 2026-07-19
>
> AI-DDD methodology plugin for Claude Code — 35 user-facing Skills + 7 internal + 11 Agents + 5 Hooks (incl. default secret-guard)

## Prerequisites

- [Claude Code](https://claude.ai/code) installed and authenticated

## Installation

```bash
# Add marketplace
/plugin marketplace add 10CG/aria-plugin

# Install (Skills + Agents + Hooks included)
/plugin install aria@10CG-aria-plugin
```

## What's Included

### Hooks (Auto-triggered)

| Hook | Matcher | Script | Purpose |
|------|---------|--------|---------|
| `SessionStart` | * | session-start-check.sh | Detect interrupted workflows + prompt recovery |
| `PreToolUse` | Write\|Edit\|NotebookEdit | handoff-location-guard.sh | Rule #9 L1 — block writes to `.aria/handoff/*.md` |
| `PreToolUse` | Bash | **secret-guard.sh** | Rule #7 Layer 2 — block raw secret reads (cmd pattern scan), v1.24.0+ |
| `PreToolUse` | Read\|Edit\|Write\|MultiEdit | **secret-guard.sh** | Rule #7 Layer 2 — block secret-bearing file paths (.env, id_rsa, etc.), v1.24.0+ |
| `PostToolUse` | Bash\|Read\|Edit\|Write\|MultiEdit | **secret-scan.sh** | Rule #7 Layer 2 — detect secret-shaped output + warn (additionalContext/systemMessage); cannot redact (PostToolUse architectural limit), real defense = PreToolUse secret-guard, v1.24.0+ |

**Disable Hooks**:
```bash
# Set environment variable
export ARIA_HOOKS_DISABLED=true

# Or disable the plugin
/plugin disable aria@10CG-aria-plugin
```

### Skills (35 user-facing + 7 internal = 42 total)

> Internal skills (7, `user-invocable: false`): agent-router, agent-team-audit, arch-common, audit-engine, config-loader, git-remote-helper (v1.15.0 +1), aria-token-telemetry (v1.33.0 +1).

**Ten-Step Cycle Core**
- state-scanner — Project state scan with intelligent workflow recommendations
- workflow-runner — Lightweight ten-step cycle orchestrator
- phase-a-planner — Phase A planning executor
- phase-b-developer — Phase B development executor
- phase-c-integrator — Phase C integration executor
- phase-d-closer — Phase D closure executor
- spec-drafter — Create OpenSpec proposal.md
- task-planner — Break down OpenSpec into executable tasks
- progress-updater — Update project progress state

**Collaborative Thinking**
- brainstorm — AI-assisted decision discussion and requirement clarification (problem/requirements/technical modes)

**Git Workflow**
- commit-msg-generator — Generate Conventional Commits messages
- strategic-commit-orchestrator — Cross-module / batch / milestone commit orchestration
- branch-manager — Branch creation and PR management
- branch-finisher — Branch completion and cleanup

**Dev Tools**
- subagent-driver — Subagent-Driven Development (SDD) with two-phase code review
- agent-router — Intelligent task-to-agent routing
- tdd-enforcer — Enforce TDD workflow
- requesting-code-review — Two-phase code review (Phase 1: spec compliance → Phase 2: code quality)

**Architecture Docs**
- arch-common *(internal, non-user-invocable)* — Architecture tooling shared config
- arch-search — Search architecture documentation
- arch-update — Update architecture documentation
- arch-scaffolder — Generate architecture skeleton from PRD
- api-doc-generator — API documentation generation

**Requirements**
- requirements-validator — PRD / Story / Architecture validation
- requirements-sync — Story ↔ UPM state sync
- forgejo-sync — Story ↔ Issue sync
- openspec-archive — Archive completed OpenSpec changes (auto-fixes CLI bugs)

**Infrastructure**
- config-loader *(internal, non-user-invocable)* — Configuration loading
- git-remote-helper *(internal, non-user-invocable)* — Git multi-remote parity detection and push verification shared infrastructure (US-012, Layer 3)
- aria-token-telemetry *(internal, non-user-invocable)* — Context/token telemetry shared data layer (relay cache read + transcript usage parse + window 4-tier resolve; #104, reused by #18 estimator)

**Context Awareness** *(v1.33.0, #104)*
- aria-context-monitor — Machine-read current session context occupancy (runtime-truth via statusLine relay) to inform "continue vs pause" decisions

**Effort Estimation** *(v1.34.0, #18)*
- ai-native-estimator — Token-axis cycle workload estimation v1 (phase-d auto-capture + forecast/velocity query; Token replaces 4-8h human-hour assumption)

**Visualization**
- aria-dashboard — Project progress dashboard (UPM/Stories/OpenSpec/Audit/Benchmark)

**Environment Diagnosis** *(v1.24.0)*
- aria-doctor — Detect aria-plugin secret-guard hook install state (`check_secret_guard_install` 5-state schema) + statusLine relay state (`check_context_relay` 3-state + jq, v1.33.0)

**Project Adaptation** *(v1.13.0)*
- project-analyzer — Scan project tech stack, frameworks, and work patterns
- agent-gap-analyzer — Compare project needs vs Agent capabilities, identify gaps
- agent-creator — Generate project-specific Agent configs with STCO + capabilities

**Feedback & Reporting**
- aria-report — Report bugs, feature requests, or questions to the Aria team

**Audit System**
- audit-engine *(internal, non-user-invocable)* — Multi-round convergence/challenge audit orchestrator
- agent-team-audit *(disabled by default, enable via `.aria/config.json`)* — Single-round audit executor

### Agents (11)

**Core Management**
- tech-lead — Technical architecture decisions, task planning, cross-team coordination
- context-manager — Multi-agent collaboration, context management
- knowledge-manager — Knowledge base management, documentation sync
- code-reviewer — Two-phase code review (Phase 1: spec compliance + Phase 2: code quality)

**Development**
- backend-architect — Backend architecture, API design, database schemas
- mobile-developer — React Native / Flutter, offline sync
- qa-engineer — Quality assurance, code review, test strategy

**Specialized**
- ai-engineer — LLM applications, RAG systems, agent orchestration
- api-documenter — OpenAPI specs, SDK generation
- ui-ux-designer — Interface design, wireframes, design systems
- legal-advisor — Privacy policies, terms of service, GDPR compliance

## Usage

### Hooks (Auto-triggered)

After installation, hooks fire automatically:

```bash
# Session start — detect interrupted workflows
# → checks .aria/workflow-state.json for unfinished work

# PreToolUse Bash — block raw secret reads (v1.24.0+)
# → e.g. `nomad var get ...` without REDACT filter → BLOCKED with helpful stderr
# → bypass: append `# guard:ack: <reason ≥8 non-whitespace chars>` to command
#          (audit-logged to ~/.claude/logs/guard-bypass.log)

# PreToolUse Read|Edit|Write|MultiEdit — block secret-bearing file paths (v1.24.0+)
# → e.g. reading .env / id_rsa / .pem / .aws/credentials / .kube/config → BLOCKED

# PostToolUse * — scan output for secret-shaped content, DETECT + warn (v1.24.0+)
# → warn-only (exit 0 always); detects + warns via additionalContext/systemMessage,
#   does NOT rewrite tool_response (PostToolUse cannot redact — real defense = PreToolUse)

# Diagnose install state:
bash ${CLAUDE_PLUGIN_ROOT}/skills/aria-doctor/scripts/check_secret_guard_install.sh
# → JSON state: not_installed / single_plugin / single_local / dual_install / corrupted_settings
```

### Manual Invocation

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

## Aria 2.0 — Autonomous Runtime

This plugin (aria-plugin) is the **interactive layer** of Aria — interactive Skills + Agents for use with Claude Code.

For the **Aria 2.0 autonomous runtime** (10CG Lab internal infrastructure that executes Aria methodology cycles autonomously, currently in development per US-026 M6 milestone), see:

- [Aria main repository](https://github.com/10CG/Aria) — methodology + Aria 2.0 PRD + autonomous runtime documentation
- [aria-orchestrator](https://github.com/10CG/aria-orchestrator) — Layer 1 (Hermes + Luxeno-routed GLM models) + Layer 2 (aria-runner + Claude Code + aria-plugin) implementation

**aria-plugin does NOT bump to v2.0** when Aria v2.0.0 releases — semantic boundary preserved (plugin = universally available interactive tools; Aria main repo = methodology + 10CG Lab-internal runtime). Plugin users: **no action needed**. See [docs/release-notes-v2.0.0.md `§Plugin Compatibility`](https://github.com/10CG/Aria/blob/master/docs/release-notes-v2.0.0.md) in the Aria main repo for full semantic boundary explanation.

## Related Projects

- [Aria](https://github.com/10CG/Aria) — Aria main project (methodology research + Aria 2.0 autonomous runtime)
- [aria-standards](https://github.com/10CG/aria-standards) — Aria methodology standards
- [aria-orchestrator](https://github.com/10CG/aria-orchestrator) — Aria 2.0 autonomous runtime (10CG Lab internal)

## License

MIT — [10CG Lab](https://github.com/10CG)
