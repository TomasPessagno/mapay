# Mac session: the iOS tasks

You're a Claude Code session on Tomas's Mac. You do the tasks that need Xcode, the iOS Simulator or the iPhone. Another Claude Code session on Tomas's Windows PC is the **orchestrator**: it runs the rest of the queue, reviews PRs and merges them. You talk to each other through GitHub, never through Tomas copy-pasting.

Read [`AGENTS.md`](../AGENTS.md) ("Working on a task"), [`docs/design.md`](design.md) and the issue you're on first. The repo is `TomasPessagno/mapay`.

## How we talk

- **The channel is your task's PR.** For #19 it's the draft PR from `b2-capacitor-ios` (its description links here).
- **You** push commits to the task's branch and post PR comments that start with `[mac]`:
  - after each checkpoint below: what you did, what worked, what didn't, and screenshots when useful (`xcrun simctl io booted screenshot shot.png`, then attach it with `gh pr comment --body-file` or describe it);
  - `[mac → orchestrator]` when you need a decision or a change on the Windows side (keys, the mocks, another task's code), then keep working on what isn't blocked;
  - `[mac] ready for review` when the task's "Done when" is met and the checks pass.
- **The orchestrator** answers in comments that start with `[orchestrator]`. Before each step, check for new ones: `gh pr view <N> --comments`.
- **Tomas** is at the Mac with you. Ask him directly for anything physical: Xcode GUI clicks you can't script, the iPhone, AltStore, his Apple ID. Don't ask him to relay messages to the orchestrator; post a comment.
- Don't merge. The orchestrator reviews and merges, then tells you the next task in a comment on the merged PR (and in this file on `main`).

## Before you start

1. `gh auth status` (log in with `gh auth login` if needed), `node -v` (20+), `xcodebuild -version`, `xcrun simctl list devices available | head`.
2. `frontend/.env` must exist with `VITE_GOOGLE_MAPS_API_KEY`, `VITE_GOOGLE_MAPS_MAP_ID`, `VITE_API_BASE_URL=http://localhost:8000`, `VITE_USE_MOCKS=true`. Tomas copies it over privately; never commit it or print the key. `scripts/check-env.sh` (from the repo root) tells you what's missing.
3. The Maps browser key must allow the iOS web view's origin `capacitor://localhost` (or be restricted by API only). If the map is blank in the Simulator with `RefererNotAllowedMapError` in the Safari Web Inspector console, that's why: tell Tomas.

## The queue here

| Order | Issue | Branch | Notes |
| --- | --- | --- | --- |
| ✅ | #19 B2 · Capacitor iOS project + widget target + AltStore proof | `b2-capacitor-ios` | Merged (PR #73). App and widget `identifierForVendor` match on the iPhone. |
| 1 | #76 B16 · iPhone fit: keyboard doesn't move the UI; tab bar height and safe areas | `b16-iphone-fit` | Small; from Tomas's first iPhone test |
| 2 | #37 B14 · Duolingo-style Live Activity (Lock Screen banner + Dynamic Island) | `b14-live-activity` | **P0**, the demo's centrepiece; spec in the issue and docs/design.md › The heads-up |
| 3 | #28 B8 · Local notifications + `mapay://` deep links | `b8-notifications` | Its tap opens the app, which starts the Live Activity |
| 3 | #29 B9 · Home-screen widget (SwiftUI) | `b9-widget` | Replaces the #19 placeholder |
| 4 | #36 B12 · Demo button | `b12-demo-button` | After #28, #29 and #37 |
| P1 | #41 B15 · design polish on the iPhone | | Only after the P0 ones; also removes the device id debug line |

For each task after #19: `git fetch && git switch -c <branch> origin/main`, open a draft PR into `main` that says `Closes #<N>` and links this file, and use it the same way.

## #19 step by step

**Bundle ids** (fixed for the whole event, because AltStore allows only 10 new App IDs per week): app `com.tomaspessagno.mapay`, widget `com.tomaspessagno.mapay.widget`. **Confirm them with Tomas before the first build.** If he wants different ones, change `appId` in `frontend/capacitor.config.ts` and use his in Xcode.

1. **Generate the project** (Capacitor 8 uses Swift Package Manager, no CocoaPods):
   ```bash
   cd frontend && npm install && npm run build && npx cap add ios
   ```
2. **Add the widget extension.** Easiest in Xcode (`npx cap open ios`), with Tomas clicking if you can't script it:
   - File → New → Target… → Widget Extension, named `MapayWidget`, with Include Live Activity and Include Configuration App Intent unchecked. Activate the scheme when asked.
   - The widget shows a static placeholder ("Mapay · no routine yet") for now; #29 builds the real one.
3. **Targets:**
   - App: bundle id as above, Minimum Deployments iOS 17.0, and Info → URL Types with identifier and scheme `mapay`.
   - `MapayWidgetExtension`: bundle id `com.tomaspessagno.mapay.widget`, iOS 17.0.
   - Signing: "Sign to Run Locally" or Tomas's personal team for the Simulator. The `.ipa` is built unsigned (AltStore signs it).
4. **Simulator:** build and run on an iPhone 16 (Xcode ⌘R, or `npx cap run ios --target <udid>`). The app shows the three tabs and the map, and the widget can be added from the Home Screen.
   → Post `[mac] checkpoint 1` with a screenshot.
5. **Device id check** (a Done-when item): the app and the widget both show `identifierForVendor`.
   - App: `Device.getId()`, shown in a small debug line (for example at the bottom of the Preferences tab, dev builds only).
   - Widget: `UIDevice.current.identifierForVendor`, in the placeholder view.
   - Compare them on the iPhone, not only the Simulator. If they differ, say so; the fallback is a baked-in demo user id.
6. **iPhone via AltStore:**
   - Tomas installs AltServer on the Mac (its menu-bar icon → Install Mail Plug-in, enabled in Mail → Settings → Manage Plug-ins), then plugs in the iPhone, trusts the Mac, and uses AltServer → Install AltStore → his iPhone with his Apple ID.
   - On the iPhone: Settings → General → VPN & Device Management → trust his Apple ID, and Settings → Privacy & Security → Developer Mode on (it restarts).
   - Build and install: `cd frontend && scripts/build-ipa.sh`, then AirDrop `frontend/build/Mapay.ipa` to the iPhone and open it in AltStore (or AltStore → My Apps → + with the file). Mac and iPhone on the same Wi-Fi with AltServer running.
   → Post `[mac] checkpoint 2`: installed or not, and the two device ids (app vs widget).
7. **Checks** before `[mac] ready for review`: `cd frontend && npm run lint && npx tsc -b --noEmit && npm run build`. Commit `frontend/ios/**` (Capacitor's own `.gitignore` keeps build output out) and anything else in the issue's Scope. Never commit `.env`, signing files or `frontend/build/`.

## Rules

- Only the files in the issue's Scope; `backend/**` belongs to the backend track.
- API shapes come from `frontend/public/mocks/`; if one must change, ask the orchestrator first.
- Keys and tokens never go in git, a PR or a comment (the repo is public).
- Everything free: a free Apple ID, no paid Apple Developer features (no push, App Groups, iCloud, Sign in with Apple).

## Testing on the iPhone

The iPhone may be with Tomas at the Windows PC instead of the Mac. Then build with `frontend/scripts/build-ipa.sh`, attach `frontend/build/Mapay.ipa` to a **draft** GitHub release named `<branch>-ipa-<short sha>` (`gh release create <tag> frontend/build/Mapay.ipa --draft --target <branch>`), and post `[mac → orchestrator]` with the tag. The orchestrator installs it through AltServer for Windows, reports back in the PR, and deletes the draft release after merging.
