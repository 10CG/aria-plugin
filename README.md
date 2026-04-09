**English** | [中文](README.zh.md)

# Aria Plugin

> **Version**: 1.11.0 | **Released**: 2026-04-09
>
> AI-DDD methodology plugin for Claude Code — 30 Skills + 11 Agents + Hooks

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

| Hook | Trigger | Purpose |
|------|---------|---------|
| `SessionStart` | Session begins | Detect interrupted workflows and prompt recovery |

**Disable Hooks**:
```bash
# Set environment variable
export ARIA_HOOKS_DISABLED=true

# Or disable the plugin
/plugin disable aria@10CG-aria-plugin
```

### Skills (29 user-facing + 3 internal)

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

**Visualization**
- aria-dashboard — Project progress dashboard (UPM/Stories/OpenSpec/Audit/Benchmark)

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

## Related Projects

- [Aria](https://github.com/10CG/Aria) — Aria main project (methodology research)
- [aria-standards](https://github.com/10CG/aria-standards) — Aria methodology standards

## License

MIT — [10CG Lab](https://github.com/10CG)
