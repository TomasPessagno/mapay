# Agent orchestration: Tomas's queue (Antigravity + OpenCode)

How Tomas runs his queue from [`TASKS.md`](../TASKS.md) with two local coding agents:
- **Google Antigravity** (1-year student plan) for the app screens, through its CLI `agy`.
- **OpenCode** on the Go plan (DeepSeek V4.1 Flash) for the backend tasks.

**OpenAI Codex** (free plan) is the spare. Jean runs his own queue with his own tools under the same rules. The agents read [`AGENTS.md`](../AGENTS.md) on their own: OpenCode and Codex natively, and Antigravity as a workspace rule. So "Working on a task" applies without pasting it.

**The orchestrator (the Claude session, or whoever is coordinating)** decides the next wave from the GitHub state (open/closed issues, open PRs), hands out the prompts below, and reviews PRs before they merge.

---

## Set up once

**GitHub CLI** (the prompts and the agents use it to read issues and open PRs):
- Install `gh`: `brew install gh` on a Mac, `winget install GitHub.cli` on Windows.
- Run `gh auth login`.

**OpenCode** (a terminal app):
1. Install it:
   - macOS / Linux: `curl -fsSL https://opencode.ai/install | bash`.
   - Windows: `npm i -g opencode-ai`, or the same curl command inside WSL.
2. Sign in to the Go plan:
   - `opencode auth login opencode` on V2.
   - `opencode console login` on V1.
   - `opencode --version` tells you which one you have.
3. Pick the model: run `opencode` in the repo, type `/models` and choose **DeepSeek V4.1 Flash** (`opencode-go/deepseek-v4.1-flash`). The prompts below also pass it explicitly.
4. Usage lives on the Go page: 5-hour, weekly and monthly bars. Leave **Extra Usage** off so it never charges more than the $10.

**Antigravity CLI** (`agy`, what the orchestrator launches):
1. Install it from [google-antigravity/antigravity-cli](https://github.com/google-antigravity/antigravity-cli) (see its README).
2. Run `agy` once and sign in with the Google account that has the student plan. On a remote machine it prints a URL and a one-time code.
3. `scripts/agent-task.sh` runs it with `--dangerously-skip-permissions`, so headless runs don't stop to ask. The agent is confined to its task's worktree by the prompt, not by the tool, so review every diff before merging.

**Antigravity desktop app** (optional, to watch or steer an agent by hand):
1. Download it from [antigravity.google](https://antigravity.google) (macOS, Windows, Linux) and sign in with the Google account that has the student plan.
2. Keep the default review policy ("Agent Decides"), and still review every diff before merging.
3. Install the Antigravity Chrome extension when it asks. That's how the agent opens the app, clicks through it and attaches screenshots.
4. Per task:
   - File → Open Folder → the task's worktree.
   - Switch to the Agent Manager (Cmd+E on a Mac, Ctrl+E on Windows).
   - Start a new agent in that workspace and paste the prompt.
   - It runs up to 5 agents at once; we keep 2–3.

---

## Which tool does what

| Tool | Strengths and limits | Gets |
| --- | --- | --- |
| **Antigravity** | Agent Manager runs several agents at once, each in its own workspace; its browser extension checks the UI and brings back screenshots; weekly quota on the student plan | The app screens, and help on the Mac tasks |
| **OpenCode** (Go plan) | DeepSeek V4.1 Flash gets about 26,000 requests per 5 hours, inside Go's caps ($12 per 5 h, $30 per week, $60 per month). It runs headless with `opencode run`, and it runs commands on your machine (network included, no sandbox). | Every backend task, up to 3 at once |
| **Codex** (free) | About 50 agent messages a day; its sandbox has no network by default | Spare, if Go's weekly cap runs out |
| **Tomas** | The Mac, the iPhone and the accounts | Mac builds, AltStore installs, Vercel, reviews and merges, checkpoints with Jean |

### Tomas's queue by tool

| # | Issue | Task | Tool |
| --- | --- | --- | --- |
| 1 | [#12](https://github.com/TomasPessagno/mapay/issues/12) | B1 · App shell | Antigravity |
| 2 | [#10](https://github.com/TomasPessagno/mapay/issues/10) | A1 · Device id + CORS | OpenCode |
| 3 | [#4](https://github.com/TomasPessagno/mapay/issues/4) | A5 · Neighbourhoods | OpenCode |
| 4 | [#5](https://github.com/TomasPessagno/mapay/issues/5) | A11 · City construction + closures | OpenCode |
| 5 | [#7](https://github.com/TomasPessagno/mapay/issues/7) | A13 · NWS weather | OpenCode |
| 6 | [#8](https://github.com/TomasPessagno/mapay/issues/8) | A14 · OSM sidewalks | OpenCode |
| 7 | [#15](https://github.com/TomasPessagno/mapay/issues/15) | A16 · News → Laya → Gemini | OpenCode |
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
| P1 | [#37](https://github.com/TomasPessagno/mapay/issues/37) · [#41](https://github.com/TomasPessagno/mapay/issues/41) · [#24](https://github.com/TomasPessagno/mapay/issues/24) | B14 Live Activity · B15 Design polish · A22 Potholes + radar | Mac · Antigravity + iPhone · OpenCode |

- "Agent on the Mac" means OpenCode or Antigravity installed on the Mac, so it can run `xcodebuild` and `xcrun simctl`. If neither is, an agent drafts the code anywhere and Tomas builds it in Xcode.
- If OpenCode struggles with a task, rerun it in Antigravity and tell the orchestrator.

---

## Waves

Run a wave's rows at the same time; start the next wave when its blockers have merged. Keep Antigravity at 2–3 agents at once and OpenCode at up to 3: the limit is the review load and Go's $12-per-5-hours cap.

| Wave | Starts when | Antigravity | OpenCode | Tomas |
| --- | --- | --- | --- | --- |
| 1 | T0 done ([#2](https://github.com/TomasPessagno/mapay/issues/2)) | #12 B1 app shell | #10 A1 · #4 A5 · #5 A11 at once (Jean waits on all three), then #8 A14 | Keys, secrets, bundle ids (T0) |
| 2 | #12 merged | #20 B3 map · #21 B5 routines | #7 A13, then #15 A16 news (needs the AI Studio key; Laya is optional, see below) | #19 B2 on the Mac + AltStore |
| 3 | #20 merged | #27 B4 sheet + routes · #22 B6 preferences | #24 A22 (P1, once Jean's #13 has merged) | Review, merge |
| T1 | #10 and #27, and Jean's #13 and #26 merged | | | Real map + routing with Jean ([#38](https://github.com/TomasPessagno/mapay/issues/38)) |
| 4 | #19 and #27 merged | #34 B7 heads-up card · #30 B11 hazard sheet | | #28 B8 and #29 B9 on the Mac (in parallel) |
| T2 | #21, #34, #28, #29, and Jean's #32 merged | | | Heads-up end to end with Jean ([#42](https://github.com/TomasPessagno/mapay/issues/42)) |
| 5 | T2 done | #35 B10 customize sheet | | #36 B12 on the Mac · #31 B13 Vercel |
| T3 → P1 → T4 | | #41 B15 (with the iPhone) | | #37 B14 on the Mac, demo prep ([#44](https://github.com/TomasPessagno/mapay/issues/44)) |

**Files several tasks edit:**
- **`frontend/package.json` + lockfile** (#12 adds Ionic, #19 adds Capacitor, #28 adds plugins): run #12 alone first. After that, resolve lockfile conflicts by merging `main` and re-running `npm install`, never by hand.
- **The Map tab and its sheet:** strictly one after another: #20 → #27 → then #34 and #30.
- **`backend/app/routing/belief_config.py`** (#7 and #15, and Jean's #9): run #7 before #15. Keep edits additive, and merge `main` before the PR.
- **`backend/app/main.py` router includes** (#10 and #4, and Jean's #33 and #14): each adds a line, so they can run at once. Whoever merges second merges `main` and keeps both lines.
- **`backend/app/config.py` settings** (#10 and #15): each adds fields. One-line conflicts: keep both lines.

---

## Set-up per task: one git worktree each

Two agents in one checkout overwrite each other, so every task gets its own folder and branch (bash; on Windows use Git Bash or WSL):

```bash
cd mapay && git fetch origin
git worktree add ../mapay-a1 -b a1-device-id-cors origin/main   # folder + branch from the issue
cd ../mapay-a1
# frontend tasks
cd frontend && npm install && cd ..
# backend tasks: one shared venv for every worktree
python -m venv ~/.venvs/mapay && source ~/.venvs/mapay/bin/activate
pip install -r backend/requirements.txt pytest ruff
```

`scripts/agent-task.sh <N> [opencode|agy]` does all of this for you (it also copies `.env` and `frontend/.env` in, and runs `npm install` for app tasks). By hand: run `opencode` or `agy` in that folder, or open it in the Antigravity app. When the PR has merged: `git worktree remove ../mapay-a1`.

---

## Prompts

**OpenCode:** from the `mapay` folder, one terminal per task:

```bash
scripts/opencode-task.sh <N>      # e.g. scripts/opencode-task.sh 4
```

The script does the whole set-up:
- reads the branch name from the issue;
- creates `../mapay-<branch>` from `origin/main`, or reuses it;
- activates the shared venv, creating it the first time;
- runs OpenCode with the prompt below.

By hand, from the task's worktree (`gh` pastes the issue into the prompt for you):

```bash
opencode run --model opencode-go/deepseek-v4.1-flash "Read AGENTS.md and follow 'Working on a task'. Implement the GitHub issue below on the current branch. Only touch the files in its Scope, keep tests offline, and run the checks it lists. Then commit, push the branch (git push -u origin HEAD) and open a PR into main whose body says 'Closes #<issue number>' (gh pr create --base main). If you can't open the PR, stop after pushing and say so.

$(gh issue view <N> -R TomasPessagno/mapay --json number,title,body -q '"#\(.number) \(.title)\n\n\(.body)"')"
```

- To watch or steer the agent while it works, run `opencode` (the interactive screen) in the worktree instead, and paste the same text.
- Up to three terminals can run at once, one per worktree.

**Antigravity** (Agent Manager → new agent in the task's workspace). Paste the issue title and body where marked:

> Read AGENTS.md (especially "Working on a task") and, for UI work, docs/design.md. Implement GitHub issue #&lt;N&gt; of TomasPessagno/mapay, pasted below. You are in a git worktree on branch `<branch>`, created from main. Only change files in the issue's Scope. Build against the mocks (`VITE_USE_MOCKS=true`). For UI work, run `npm run dev`, open the app in the browser at iPhone size, compare it with docs/design.md and attach screenshots. Before finishing, run the checks the issue lists, commit, push the branch, and open a PR into main that says "Closes #&lt;N&gt;" (`gh pr create --base main`). If you can't open the PR, stop after pushing and say so.
>
> &lt;issue title and body&gt;

**Codex** (spare). Its sandbox can't push, so the prompt stops at the commit:

```bash
codex "Read AGENTS.md and follow 'Working on a task'. Implement the GitHub issue below on the current branch. Only touch the files in its Scope, keep tests offline, run the checks it lists, and commit.

$(gh issue view <N> -R TomasPessagno/mapay --json number,title,body -q '"#\(.number) \(.title)\n\n\(.body)"')"
```

Then push and open the PR yourself: `git push -u origin HEAD && gh pr create --base main --title "<ID> · <title>" --body "Closes #<N>"`.

---

## Reviewing and merging

1. CI is green on the PR.
2. The diff stays inside the issue's Scope, and response shapes still match `frontend/public/mocks/`. If a shape changed, the mock, `frontend/src/lib/types.ts` and `backend/app/db/models.py` changed together.
3. UI work: the screenshots match docs/design.md.
4. Squash-merge, delete the branch, remove the worktree, and tell Jean if his work depends on it (#4, #5, #10).
5. The orchestrator can review a PR on request ("review PR #N") before you merge.

---

## For the orchestrator (any Claude Code session, cloud or local)

Everything the orchestrator needs is in the repo: this file, [`TASKS.md`](../TASKS.md), [`AGENTS.md`](../AGENTS.md) and the issues. The decisions log is "Status and open items" below. A new session starts by reading those three files.

**People**
- **Tomas** is `TomasPessagno`, the repo owner.
  - He has the Mac and the iPhone (AltStore).
  - He runs Antigravity and OpenCode.
- **Jean** is `Jeanm2005`.
  - He owns the backend and the cloud, and runs Laya on his laptop.
  - He uses his own Claude agents.

**Check the state**
- `gh issue list -R TomasPessagno/mapay --state open --limit 100`
- `gh pr list -R TomasPessagno/mapay`
- `gh pr checks <N>` for one PR.

**"What's next"**
1. Take the tasks from the Waves table whose "Blocked by" issues are closed and that have no open PR. Respect "Files several tasks edit".
2. A local session launches them itself: `scripts/agent-task.sh <N> opencode` for backend tasks, `scripts/agent-task.sh <N> agy` for the app screens.
3. A cloud session can't reach Tomas's computer, so it gives him those commands instead.

**"Review PR #N"**
- Run `gh pr view <N>`, `gh pr diff <N>` and `gh pr checks <N>`, and apply "Reviewing and merging" above.
- Reply with `gh pr review <N> --comment` (or `--approve` / `--request-changes`).

**"Run the queue" (a local session, on Tomas's computer)**

Tomas can hand the backend queue to a local Claude Code session: "you're the orchestrator, run the queue". It works through the OpenCode tasks on its own and stops only when it needs him. This session runs on his computer because OpenCode is installed and signed in there. Start it with `claude remote-control` in the `mapay` folder so Tomas can follow it from the Claude app.

1. **Check the tools:** `git pull` in `mapay`, `gh auth status`, `opencode --version`.
2. **Pick tasks:**
   - From "Tomas's queue by tool", take the OpenCode tasks whose "Blocked by" issues are closed and that have no open PR.
   - Respect "Files several tasks edit".
   - Run at most 3 at once. Run the very first one alone until the shared venv exists.
   - Current order (#4, #5, #7, #8 and #10 are merged):
     - OpenCode: #15 (running);
     - Antigravity (`agy`): #12 app shell now, then #20 and #21 once it merges, then #27 and #22 (see Waves);
     - #24 (P1) once Jean's #13 has merged.
3. **Launch** each one in the background from `mapay`: `scripts/agent-task.sh <N> <tool> > ../agent-<N>.log 2>&1`, with the tool from "Tomas's queue by tool" (`agy` for Antigravity rows). Up to 3 OpenCode and 2 Antigravity runs at once. Check the log for `Error:` too: `opencode run` exits 0 when the model refuses.
4. **When a run ends,** find its PR with `gh pr list --head <branch>`. If there's none, read the log (look for `Error:`, since `opencode run` exits 0 anyway) and the worktree's `git status`, then send a follow-up from the worktree: `opencode run --session <id> --model opencode-go/deepseek-v4.1-flash --variant high "<what's missing>"`.
   - Take the id from `opencode session list`, matched by title. All worktrees share one session list, so `--continue` can resume another task's session.
   - Headless runs automatically refuse file access outside the worktree, and the agent stops there (usually it saved downloads to `/tmp`). Tell it to use `.scratch/` in the worktree instead; that folder is git-ignored (`.gitignore`).
5. **Review each PR** with "Reviewing and merging" above:
   - `gh pr checks <N> --watch`, then `gh pr diff <N>`.
   - Also check that no keys were committed and that tests don't touch the network.
   - If something is wrong, send OpenCode the specific fixes (at most two rounds).
   - App screens: run `npm run dev` in the worktree's `frontend/`, take screenshots at iPhone size (390×844, light and dark) and compare them with docs/design.md before merging.
6. **Merge:**
   - `gh pr merge <N> --squash --delete-branch`, `git worktree remove ../mapay-<branch>`, `git pull`.
   - If Jean waits on it, comment on his issue: "Unblocked: #N is merged". That's #4 → #17, #5 → #16, #10 → #18.
   - Give Tomas one line: what merged, and what's next.
7. **Repeat** until a stop below applies.

**Stop and ask Tomas when:**
- the next task needs a decision, a key or an account (T0, [#2](https://github.com/TomasPessagno/mapay/issues/2));
- only Mac, iPhone or together tasks are left;
- a PR still fails after two follow-ups, or the fix would leave the issue's Scope or change a mock shape (that affects Jean);
- OpenCode reports that Go's usage limit is reached;
- anything would touch Jean's queue.

**House rules**
- Plan and doc changes (README, AGENTS.md, TASKS.md, `docs/`) go straight to `main` as small commits. Code goes through the issue's branch and a PR.
- When a task changes hands:
  - reassign the issue;
  - update the queues in TASKS.md, the task board [#45](https://github.com/TomasPessagno/mapay/issues/45) and this file.
- Keys and tokens never go in git or an issue (the repo is public).
- Everything must be free unless Tomas says otherwise. OpenCode Go is the one paid exception.
- Never analyse Google Maps imagery or Street View (see AGENTS.md).
- Record every decision under "Status and open items".

---

## Status and open items (as of Sept 26)

- **T0 ([#2](https://github.com/TomasPessagno/mapay/issues/2)) is nearly closed (Sept 26):** decisions made (Routes API, mocks as contract, Jean's GCP project, `X-Device-Id`); secrets and variables are in and the first deploy succeeded; `mapay-api` (us-east1) is public; `frontend/.env` exists. Still open: the Map ID (until then the app falls back to Google's demo map), satellite accounts (Jean, for #9/#16), Apple bundle ids (after Tomas's macOS update).
- **Web preview (#31):** https://mapay-blue.vercel.app/ (Vercel, root `frontend`, mocks on). Jean is adding the Vercel domain to the browser key restrictions and to `CORS_ORIGINS`; the refresh test on a tab route is still to do.
- **Deploys work:** merges touching `backend/` deploy to Cloud Run, one at a time (`concurrency: deploy-backend`).
- **Jean's queue hasn't produced a PR yet (Sept 26, late):** T1 waits on his #11, #13 and #26. If he wants help, OpenCode can take his unstarted `agent-ready` tasks (#3, #6, #14 first); reassign each issue before launching so two agents never do the same task.
- **Uneven split, kept on purpose:** A16 news (#15) moved to Tomas, and Jean took the Laya service (A24), so Tomas ≈ 34.5 h vs Jean ≈ 28.5 h of P0. Jean also has 8.5 h of P1, including the Laya fine-tune. #5 (A11) and #7 (A13) stay with Tomas. If he falls behind, he says so and the orchestrator hands them to Jean: reassign both issues, move their rows to Jean's queue in TASKS.md, and tell Jean. #5 goes first either way, because Jean's #16 waits on it.
- **Jean** uses his own agents (his commits are co-authored by Claude); same AGENTS.md rules.
- **OpenCode Go adopted (Sept 26):** Tomas pays $10/month, DeepSeek V4.1 Flash does the backend tasks, and Codex is the spare. The first runs are wave 1's #10, #4 and #5. Rerun any task that goes badly in Antigravity.
- **`X-Device-Id` confirmed (Sept 26):** the header name is settled, so #10 is unblocked. Its value is the iPhone's `identifierForVendor`, not a computer name.
- **OpenCode needs the Global region (Sept 26):** DeepSeek V4.1 Flash refuses requests unless the OpenCode workspace's Privacy setting is Global. The first runs of #4, #5 and #8 failed on that before writing any code. `opencode run` still exits 0 when that happens, so check the log for `Error:`. `scripts/opencode-task.sh` now passes `--variant high` (override with `OPENCODE_VARIANT=max`).
- **Queue progress (Sept 26, evening):** Tomas's OpenCode P0 tasks are all merged: #5 (PR #49), #8 (#48), #10 (#52), #7 (#51), #4 (#50) and #15 (#54); Jean was told on #16, #18 and #17. Only #24 (P1) is left for OpenCode, and it waits on Jean's #13. #12 (app shell, #53) is merged after a screenshot review at 393×852 in light and dark; #20 and #21 run in the Antigravity CLI (`scripts/agent-task.sh <N> agy`). #8's coverage check is on the issue: 67 no-sidewalk ways within 2 km of MMC, 74 of BBC. #5 computes a title/place per hazard, but `register_hazard` doesn't store properties yet; `/layers` (#13) will need them. Keep `LAYA_URL` unset until #47's fine-tune: zero-shot Laya kept 2/10 road headlines at p 0.2 (numbers on #46 and PR #54).
- **Gemini runs on Vertex AI (Jean, Sept 26):** `backend/app/agents/genai_client.py` builds the client, switched by `GOOGLE_GENAI_USE_VERTEXAI` (see AGENTS.md › Gemini fallback plan). The AI Studio key's project is out of credit, so nobody needs a `GEMINI_API_KEY`. When reviewing #15 and any later Gemini task, check it calls `get_genai_client()` and `settings.gemini_model`, not its own client. Jean's commit left merge markers in AGENTS.md; fixed.
- **Tomas's Mac needs a macOS update before Xcode (Sept 26):** #19 and the other Mac tasks wait; the browser app tasks go ahead.
- **Antigravity through its CLI (Sept 26):** the orchestrator launches app-screen tasks with `scripts/agent-task.sh <N> agy`, so Tomas doesn't prompt the desktop app. `scripts/opencode-task.sh` is now a wrapper for `agent-task.sh <N> opencode`.
- **The orchestrator merges its own PRs (decided Sept 26):** Tomas said to merge the orchestrator's own PRs (small follow-ups such as #57) once CI is green and its review passes, without waiting for him. App screens are merged after a screenshot review at 393×852 in light and dark against docs/design.md; `frontend/.env` (Maps browser key + Map ID) is copied into each Track B worktree for that.
- **Laya instead of Jev (decided Sept 26).** We have no access to TypeSafe's Jev, so we use [Laya](https://github.com/NandhaKishorM/laya): open source (Apache-2.0), the same kind of model, and it speaks Jev's API. You send it a text and typed questions (yes/no, one option from a list, a score on a scale), and it returns an answer with a probability for each. We host it ourselves, so there's no key to get. It isn't a coding agent, so it doesn't change the tool plan above.
  - **Jean's A24 ([#46](https://github.com/TomasPessagno/mapay/issues/46)):** runs it for free on his laptop behind a tunnel (multilingual checkpoint, about 0.2 s per question). Cloud Run would need billing and cost cents, and Hugging Face's Docker Spaces now need a paid plan. When the laptop is off, #15 runs Gemini-only.
  - **Jean's A25 ([#47](https://github.com/TomasPessagno/mapay/issues/47), P1):** fine-tunes it on about 1,000 Miami news items. Claude labels them (Claude Code in the session, not the paid API), and training runs on Kaggle's free GPUs.
  - **Tomas's A16 ([#15](https://github.com/TomasPessagno/mapay/issues/15)):** asks Laya one yes/no question per article, drops the clear misses (below p 0.2) and sends the rest to Gemini. Without `LAYA_URL` it runs Gemini-only, so #15 doesn't wait for #46. The agent can also run Laya locally for the threshold check.
