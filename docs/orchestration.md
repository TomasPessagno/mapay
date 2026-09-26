# Agent orchestration: Tomas's queue (Antigravity + Codex)

How Tomas runs his queue from [`TASKS.md`](../TASKS.md) with two local coding agents: **Google Antigravity** (1-year student plan) and **OpenAI Codex** (free plan). Jean runs his own queue with his own tools under the same rules. Both agents read [`AGENTS.md`](../AGENTS.md) automatically (Antigravity treats it as a workspace rule; Codex reads it natively), so "Working on a task" applies without pasting it.

**The orchestrator (the Claude session, or whoever is coordinating)** decides the next wave from the GitHub state (open/closed issues, open PRs), hands out the prompts below, and reviews PRs before they merge.

---

## Which tool does what

| Tool | Strengths and limits | Gets |
| --- | --- | --- |
| **Antigravity** | Agent Manager runs several agents in parallel, each in its own workspace; built-in browser to check the UI; weekly quota on the student plan | All the app screens, the bigger backend tasks, and help on the Mac tasks |
| **Codex** (free) | About 50 agent messages a day; its sandbox has no network by default | Small, well-specified backend tasks with tests, one at a time |
| **Tomas** | The Mac, the iPhone and the accounts | Mac builds, AltStore installs, Vercel, reviews and merges, checkpoints with Jean |

### Tomas's queue by tool

| # | Issue | Task | Tool |
| --- | --- | --- | --- |
| 1 | [#12](https://github.com/TomasPessagno/mapay/issues/12) | B1 · App shell | Antigravity |
| 2 | [#10](https://github.com/TomasPessagno/mapay/issues/10) | A1 · Device id + CORS | Codex |
| 3 | [#4](https://github.com/TomasPessagno/mapay/issues/4) | A5 · Neighbourhoods | Antigravity |
| 4 | [#5](https://github.com/TomasPessagno/mapay/issues/5) | A11 · City construction + closures | Codex |
| 5 | [#7](https://github.com/TomasPessagno/mapay/issues/7) | A13 · NWS weather | Codex |
| 6 | [#8](https://github.com/TomasPessagno/mapay/issues/8) | A14 · OSM sidewalks | Codex |
| 7 | [#15](https://github.com/TomasPessagno/mapay/issues/15) | A16 · News → Gemini | Antigravity |
| 8 | [#19](https://github.com/TomasPessagno/mapay/issues/19) | B2 · Capacitor iOS + AltStore proof | Tomas on the Mac (an agent on the Mac can help) |
| 9 | [#20](https://github.com/TomasPessagno/mapay/issues/20) | B3 · Map + legend | Antigravity |
| 10 | [#27](https://github.com/TomasPessagno/mapay/issues/27) | B4 · Sheet, search, route options | Antigravity |
| 11 | [#21](https://github.com/TomasPessagno/mapay/issues/21) | B5 · Routines tab + editor | Antigravity |
| 12 | [#22](https://github.com/TomasPessagno/mapay/issues/22) | B6 · Preferences tab | Antigravity |
| 13 | [#34](https://github.com/TomasPessagno/mapay/issues/34) | B7 · Heads-up card | Antigravity |
| 14 | [#28](https://github.com/TomasPessagno/mapay/issues/28) | B8 · Notifications + deep links | Agent on the Mac + Tomas in the Simulator |
| 15 | [#29](https://github.com/TomasPessagno/mapay/issues/29) | B9 · Widget (SwiftUI) | Agent on the Mac + Tomas in Xcode |
| 16 | [#35](https://github.com/TomasPessagno/mapay/issues/35) | B10 · Customize sheet | Antigravity |
| 17 | [#30](https://github.com/TomasPessagno/mapay/issues/30) | B11 · Hazard sheet + report | Antigravity |
| 18 | [#36](https://github.com/TomasPessagno/mapay/issues/36) | B12 · Demo button | Agent on the Mac + Tomas on the iPhone |
| 19 | [#31](https://github.com/TomasPessagno/mapay/issues/31) | B13 · Vercel preview | Tomas (Vercel account) |
| P1 | [#37](https://github.com/TomasPessagno/mapay/issues/37) · [#41](https://github.com/TomasPessagno/mapay/issues/41) · [#24](https://github.com/TomasPessagno/mapay/issues/24) | B14 Live Activity · B15 Design polish · A22 Potholes + radar | Mac · Antigravity + iPhone · Codex |

"Agent on the Mac" means Antigravity or Codex installed on the Mac, so it can run `xcodebuild` and `xcrun simctl`; if neither is, an agent drafts the code anywhere and Tomas builds it in Xcode.

---

## Waves

Run a wave's rows at the same time; start the next wave when its blockers have merged. Keep Antigravity at 2–3 agents at once (quota and review load) and Codex at one.

| Wave | Starts when | Antigravity | Codex | Tomas |
| --- | --- | --- | --- | --- |
| 1 | T0 done ([#2](https://github.com/TomasPessagno/mapay/issues/2)) | #12 B1 app shell · #4 A5 neighbourhoods | #10 A1, then #5 A11 | Keys, secrets, bundle ids (T0) |
| 2 | #12 merged | #20 B3 map · #21 B5 routines · #15 A16 news (needs the AI Studio key; #4 helps) | #7 A13, then #8 A14 | #19 B2 on the Mac + AltStore |
| 3 | #20 merged | #27 B4 sheet + routes · #22 B6 preferences | (spare: #24 A22, once Jean's #13 has merged) | Review, merge |
| T1 | #10 and #27, and Jean's #13 and #26 merged | | | Real map + routing with Jean ([#38](https://github.com/TomasPessagno/mapay/issues/38)) |
| 4 | #19 and #27 merged | #34 B7 heads-up card · #30 B11 hazard sheet | | #28 B8 and #29 B9 on the Mac (in parallel) |
| T2 | #21, #34, #28, #29, and Jean's #32 merged | | | Heads-up end to end with Jean ([#42](https://github.com/TomasPessagno/mapay/issues/42)) |
| 5 | T2 done | #35 B10 customize sheet | | #36 B12 on the Mac · #31 B13 Vercel |
| T3 → P1 → T4 | | #41 B15 (with the iPhone) | #24 A22 | #37 B14 on the Mac, demo prep ([#44](https://github.com/TomasPessagno/mapay/issues/44)) |

**Don't run these at the same time** (they edit the same files):
- `frontend/package.json` + lockfile: #12 adds Ionic, #19 adds Capacitor, #28 adds plugins. Run #12 alone first; after that, resolve lockfile conflicts by merging `main` and re-running `npm install`, never by hand.
- The Map tab and its sheet: #20 → #27 → then #34 and #30.
- `backend/app/routing/belief_config.py`: #7 and #15 (and Jean's #9). Keep edits additive; merge `main` before the PR.
- `backend/app/main.py` router includes: #10 and #4 (and Jean's #33, #14). One-line conflicts: keep both lines.

---

## Set-up per task: one git worktree each

Two agents in one checkout overwrite each other, so every task gets its own folder and branch (bash; on Windows use Git Bash or WSL):

```bash
cd mapay && git fetch origin
git worktree add ../mapay-b1 -b b1-app-shell origin/main   # folder + branch from the issue
cd ../mapay-b1
# frontend tasks
cd frontend && npm install && cd ..
# backend tasks: one shared venv, prepared before Codex starts (its sandbox has no network)
python -m venv ~/.venvs/mapay && source ~/.venvs/mapay/bin/activate
pip install -r backend/requirements.txt pytest ruff
```

Open that folder as the Antigravity workspace, or run `codex` inside it. When the PR has merged: `git worktree remove ../mapay-b1`.

---

## Prompts

**Antigravity** (Agent Manager → new agent in the task's workspace). Paste the issue title and body where marked:

> Read AGENTS.md (especially "Working on a task") and, for UI work, docs/design.md. Implement GitHub issue #&lt;N&gt; of TomasPessagno/mapay, pasted below. You are in a git worktree on branch `<branch>`, created from main. Only change files in the issue's Scope. Build against the mocks (`VITE_USE_MOCKS=true`). For UI work, run `npm run dev`, open the app in the browser at iPhone size, compare it with docs/design.md and attach screenshots. Before finishing, run the checks the issue lists, commit, push the branch, and open a PR into main that says "Closes #&lt;N&gt;" (`gh pr create --base main`). If you can't open the PR, stop after pushing and say so.
>
> &lt;issue title and body&gt;

**Codex** (from the task's worktree; `gh` pastes the issue into the prompt for you):

```bash
codex "Read AGENTS.md and follow 'Working on a task'. Implement the GitHub issue below on the current branch. Only touch the files in its Scope, keep tests offline, run the checks it lists, and commit.

$(gh issue view <N> -R TomasPessagno/mapay --json number,title,body -q '"#\(.number) \(.title)\n\n\(.body)"')"
```

Then push and open the PR yourself: `git push -u origin <branch> && gh pr create --base main --title "<ID> · <title>" --body "Closes #<N>"`. Check the remaining Codex quota with `/usage` in the CLI.

---

## Reviewing and merging

1. CI is green on the PR.
2. The diff stays inside the issue's Scope, and response shapes still match `frontend/public/mocks/`. If a shape changed, the mock, `frontend/src/lib/types.ts` and `backend/app/db/models.py` changed together.
3. UI work: the screenshots match docs/design.md.
4. Squash-merge, delete the branch, remove the worktree, and tell Jean if his work depends on it (#4, #5, #10).
5. The orchestrator can review a PR on request ("review PR #N") before you merge.

---

## Status and open items (as of Sept 26)

- **T0 ([#2](https://github.com/TomasPessagno/mapay/issues/2)) isn't done yet:** routing engine decision (Routes API vs Jean's OSMnx engine), keys, the shared GCP project, bundle ids.
- **Deploy secrets are missing:** backend merges show a red `deploy-backend` job until Tomas adds `GCP_SA_KEY` and the rest.
- **Uneven split:** A16 news (#15) moved to Tomas, so Tomas ≈ 34 h vs Jean ≈ 27.5 h of P0. Proposed fix, not yet decided: give Jean #5 and #7.
- **Jean** uses his own agents (his commits are co-authored by Claude); same AGENTS.md rules.
- **Unanswered:** what "jev" meant (Vertex AI? Jules? Jean?).
