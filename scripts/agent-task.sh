#!/usr/bin/env bash
# Run one GitHub issue with a coding agent in its own git worktree (see docs/orchestration.md).
#
#   scripts/agent-task.sh <issue-number> [opencode|agy] [model]
#
# opencode (default): OpenCode on the Go plan, for backend tasks. OPENCODE_VARIANT=max for more
#                     reasoning (default high).
# agy:                the Antigravity CLI (student plan), for the app screens. Runs with
#                     --dangerously-skip-permissions so headless runs never stop to ask; override
#                     with AGY_FLAGS.
#
# Reads the branch from the issue's "**Branch:**" line, creates ../mapay-<branch> from origin/main
# (or reuses it), copies the .env files in, prepares the shared Python venv and, for Track B,
# node_modules, and starts the agent with the standard prompt. The agent commits, pushes and opens
# the PR itself. Needs git and gh (logged in), plus the agent's CLI (logged in). On Windows, run it
# in Git Bash. `opencode run` exits 0 even when the model refuses, so check the output for `Error:`.
set -eu

issue="${1:?usage: scripts/agent-task.sh <issue-number> [opencode|agy] [model]}"
tool="${2:-opencode}"
model="${3:-}"
repo="TomasPessagno/mapay"

root="$(git rev-parse --show-toplevel)"
body="$(gh issue view "$issue" -R "$repo" --json body -q .body)"
branch="$(printf '%s\n' "$body" | LC_ALL=C sed -n '/\*\*Branch:\*\*/{s/.*\*\*Branch:\*\* `\([^`]*\)`.*/\1/p;q;}')"
if [ -z "$branch" ]; then
  echo "Issue #$issue has no **Branch:** line; create the worktree by hand (docs/orchestration.md)." >&2
  exit 1
fi
dir="$(dirname "$root")/mapay-$branch"

git -C "$root" fetch origin
if [ -d "$dir" ]; then
  echo "Reusing $dir"
elif git -C "$root" show-ref --verify --quiet "refs/heads/$branch"; then
  git -C "$root" worktree add "$dir" "$branch"
else
  git -C "$root" worktree add --no-track -b "$branch" "$dir" origin/main
fi
cd "$dir"

# Keys: the backend reads .env from the worktree's root, so copy the main checkout's in (never committed).
if [ -f "$root/.env" ] && [ ! -f .env ]; then cp "$root/.env" .env; fi
if [ -f "$root/frontend/.env" ] && [ ! -f frontend/.env ]; then cp "$root/frontend/.env" frontend/.env; fi

# One shared venv for every backend task, created on first use.
venv="$HOME/.venvs/mapay"
if [ ! -d "$venv" ]; then
  case "${OSTYPE:-}" in  # on Windows, python3 can be the Microsoft Store placeholder
    msys*|cygwin*) py="$(command -v py || command -v python)" ;;
    *) py="$(command -v python3 || command -v python)" ;;
  esac
  echo "Creating $venv (first run only, takes a few minutes)"
  "$py" -m venv "$venv"
  created=1
fi
set +u  # activate scripts may read unset variables
if [ -f "$venv/bin/activate" ]; then . "$venv/bin/activate"; else . "$venv/Scripts/activate"; fi
set -u
if [ "${created:-0}" = 1 ]; then
  python -m pip install -q -r backend/requirements.txt pytest ruff
fi

# Frontend tasks (Track B): install node_modules in this worktree once.
if printf '%s\n' "$body" | head -n 1 | grep -q '\*\*Track:\*\* B' && [ ! -d frontend/node_modules ]; then
  (cd frontend && npm install)
fi

prompt="Read AGENTS.md and follow 'Working on a task'. For UI work also read docs/design.md, build against the mocks (VITE_USE_MOCKS=true) and, if you can open a browser, check the app at iPhone size. Implement the GitHub issue below on the current branch. Only touch the files in its Scope, keep tests offline, and run the checks it lists. You can't read or write outside this worktree: put downloads and scratch files in .scratch/ (git-ignored, never commit it), not /tmp. Then commit, push the branch (git push -u origin HEAD) and open a PR into main whose body says 'Closes #$issue' (gh pr create --base main). If you can't open the PR, stop after pushing and say so.

$(gh issue view "$issue" -R "$repo" --json number,title,body -q '"#\(.number) \(.title)\n\n\(.body)"')"

echo "Issue #$issue on branch $branch in $dir, tool $tool"
case "$tool" in
  opencode)
    opencode run --model "${model:-opencode-go/deepseek-v4.1-flash}" --variant "${OPENCODE_VARIANT:-high}" "$prompt" ;;
  agy|antigravity)
    # shellcheck disable=SC2086  # AGY_FLAGS is a list of flags
    if [ -n "$model" ]; then agy ${AGY_FLAGS---dangerously-skip-permissions} --model "$model" -p "$prompt"; else agy ${AGY_FLAGS---dangerously-skip-permissions} -p "$prompt"; fi ;;
  *)
    echo "Unknown tool: $tool (use opencode or agy)" >&2; exit 1 ;;
esac
