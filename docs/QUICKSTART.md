**English** | [中文](QUICKSTART.zh.md)

# Aria Plugin Quick Start Guide

Get from zero to your first AI-DDD workflow in 10 minutes.

## Prerequisites

- [Claude Code](https://claude.ai/code) installed and authenticated
- A Git repository (existing project or new)

## Step 1: Install

```bash
# Add marketplace
/plugin marketplace add 10CG/aria-plugin

# Install
/plugin install aria@10CG-aria-plugin
```

Verify installation:
```bash
/aria:state-scanner
```

You should see a project state analysis with workflow recommendations.

## Step 2: Configure (Optional)

Create `.aria/config.json` for project-level settings:

```bash
mkdir -p .aria
```

```json
{
  "workflow": {
    "auto_proceed": false
  },
  "state_scanner": {
    "confidence_threshold": 90,
    "auto_execute_enabled": false
  },
  "tdd": {
    "strictness": "advisory"
  }
}
```

All fields are optional — defaults work well for most projects.

## Step 3: Your First Ten-Step Cycle

### Scenario: Adding a new feature to your project

**1. Scan project state**

```
/aria:state-scanner
```

The scanner analyzes your Git status, changes, and project context, then recommends a workflow.

**2. Create a spec (Phase A)**

When prompted, select the recommended workflow. If you're adding a feature, the scanner will guide you to create an OpenSpec:

```
/aria:spec-drafter
```

This creates `openspec/changes/<feature>/proposal.md` — a structured description of what you're building and why.

**3. Plan tasks (Phase A)**

```
/aria:task-planner
```

Breaks your spec into executable tasks with dependencies and complexity estimates.

**4. Develop (Phase B)**

Start coding! The scanner tracks your progress. When you need a commit:

```
/aria:commit-msg-generator
```

Generates Conventional Commits messages from your staged changes.

**5. Integrate (Phase C)**

```
/aria:state-scanner
```

The scanner detects your changes are ready and recommends integration. It handles branch management and PR creation.

**6. Close (Phase D)**

After merging, the scanner recommends archiving your completed spec:

```
/aria:state-scanner
```

Your OpenSpec moves to `openspec/archive/` and progress is updated.

## What You Get

| Feature | How to Use |
|---------|-----------|
| Project state analysis | `/aria:state-scanner` |
| Spec-driven development | `/aria:spec-drafter` |
| Task breakdown | `/aria:task-planner` |
| Commit message generation | `/aria:commit-msg-generator` |
| Code review | `/aria:requesting-code-review` |
| Collaborative brainstorming | `/aria:brainstorm` |
| TDD enforcement | `/aria:tdd-enforcer` |
| Bug/feature reporting | `/aria:report` |

## Key Concepts

**Ten-Step Cycle**: A structured workflow in 4 phases (Plan → Develop → Integrate → Close). You don't need to follow every step — the scanner recommends what's relevant.

**OpenSpec**: A lightweight spec format (`proposal.md`) that captures what you're building, why, and what "done" looks like. Level 1 (skip) for trivial fixes, Level 2 (minimal) for features.

**Skills vs Agents**: Skills are workflows you invoke (e.g., `/aria:state-scanner`). Agents are specialized roles that Skills delegate to (e.g., `code-reviewer`, `tech-lead`).

## Tips

- **Start with the scanner**: Always begin with `/aria:state-scanner`. It tells you where you are and what to do next.
- **Skip what you don't need**: The cycle is flexible. Small bug fix? The scanner will recommend `quick-fix` and skip Phase A entirely.
- **Use brainstorm for unclear requirements**: When a feature is fuzzy, `/aria:brainstorm` helps clarify before you write a spec.

## Standards (Optional)

For teams that want the full methodology (conventions, templates, progress management):

```bash
git submodule add https://github.com/10CG/aria-standards.git standards
```

See the [aria-standards README](https://github.com/10CG/aria-standards) for standalone usage.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Skills not appearing | Run `/reload-plugins` or restart Claude Code |
| Scanner shows no recommendations | Ensure you're in a Git repository with changes |
| Config not loading | Check `.aria/config.json` is valid JSON |
| Need help | `/aria:report question` to ask the maintainers |

## Next Steps

- Browse all [28 Skills and 11 Agents](../README.md)
- Read the [Aria methodology](https://github.com/10CG/Aria)
- Report issues: `/aria:report`
