#!/usr/bin/env bash
# Aria SessionStart Hook: Detect interrupted workflows
# Checks for .aria/workflow-state.json and notifies Claude if found

STATE_FILE=".aria/workflow-state.json"

if [ ! -f "$STATE_FILE" ]; then
  exit 0
fi

# Read state using python3 for reliable JSON parsing
RESULT=$(python3 -c "
import json, sys
try:
    with open('$STATE_FILE') as f:
        state = json.load(f)
    status = state.get('session', {}).get('status', 'unknown')
    workflow = state.get('workflow', {}).get('name', 'unknown')
    phase = state.get('workflow', {}).get('current_step', 'unknown')
    branch = state.get('git_anchor', {}).get('branch', 'unknown')
    if status in ('in_progress', 'suspended', 'failed'):
        print(json.dumps({
            'status': status,
            'workflow': workflow,
            'phase': phase,
            'branch': branch
        }))
    else:
        sys.exit(0)
except Exception:
    sys.exit(0)
" 2>/dev/null)

if [ -n "$RESULT" ]; then
  echo "$RESULT"
fi
