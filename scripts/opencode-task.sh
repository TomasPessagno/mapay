#!/usr/bin/env bash
# Kept for existing commands: same as `scripts/agent-task.sh <issue> opencode [model]`
# (OPENCODE_VARIANT=max for more reasoning; default high).
exec "$(dirname "$0")/agent-task.sh" "${1:?usage: scripts/opencode-task.sh <issue-number> [model]}" opencode "${2:-}"
