#!/usr/bin/env bash
# Run one GitHub issue with OpenCode in its own git worktree (see docs/orchestration.md).
#
#   scripts/opencode-task.sh <issue-number> [model]      (OPENCODE_VARIANT=max for more reasoning; default high)
#
# Reads the branch name from the issue's "**Branch:**" line, creates ../mapay-<branch> from
# origin/main (or reuses it), activates the shared Python venv (creating it on first use), and
# starts OpenCode with the standard prompt. The agent commits, pushes and opens the PR itself.
# Needs git, gh (logged in) and opencode (logged in to the Go plan). On Windows, run it in Git Bash.
set -eu

issue="${1:?usage: scripts/opencode-task.sh <issue-number> [model]}"
model="${2:-opencode-go/deepseek-v4.1-flash}"
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

prompt="Read AGENTS.md and follow 'Working on a task'. Implement the GitHub issue below on the current branch. Only touch the files in its Scope, keep tests offline, and run the checks it lists. Then commit, push the branch (git push -u origin HEAD) and open a PR into main whose body says 'Closes #$issue' (gh pr create --base main). If you can't open the PR, stop after pushing and say so.

$(gh issue view "$issue" -R "$repo" --json number,title,body -q '"#\(.number) \(.title)\n\n\(.body)"')"

variant="${OPENCODE_VARIANT:-high}"  # reasoning effort: minimal, high, max
echo "Issue #$issue on branch $branch in $dir, model $model ($variant)"
opencode run --model "$model" --variant "$variant" "$prompt"
