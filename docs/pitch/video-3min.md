# MAPAY: 3-minute video script + judging table

App footage and real renders only (no AI footage). About 430 words of voiceover, which fills 3:00 at a natural pace. Each section: **Show** (on screen) + **Say** (voiceover).

Assets:
- Lock Screen banner renders: `Downloads\Mapay graphics\` (and `v2\` for the versions that show the hazard's name); images-only deck: `Mapay banners (images only).pptx`.
- Web preview (desktop layout): https://tomaspessagno.github.io/mapay/
- Latest iPhone build: `gh release download latest-ipa -R TomasPessagno/mapay -p Mapay.ipa`

## Structure

| # | Section | Time | Goal |
|---|---|---|---|
| 1 | Cold open: the banner wall | 0:00–0:15 | Visual hook: all 10 banners |
| 2 | The problem | 0:15–0:30 | The Miami commuter |
| 3 | The map | 0:30–1:00 | 9 hazard types, sources, Demo/Live, desktop |
| 4 | Routing | 1:00–1:30 | Leave now/at, scored routes, the "why" |
| 5 | Routines + heads-up | 1:30–1:55 | Live Activity, notification, widget |
| 6 | Customize | 1:55–2:20 | Prompt → new route; "Google drives, MAPAY steers" |
| 7 | Under the hood | 2:20–2:50 | Every data source, shown in the app |
| 8 | Close | 2:50–3:00 | Tagline and logo |

## Script

### 1. Cold open (0:00–0:15)

**Show:** black screen; the 10 Lock Screen banners flip in to the beat, ~1 s each, in this order: cyan flood, indigo rain, orange roadwork, grey closure, red traffic, purple no sidewalk, brown potholes, pink crash, green event, blue clear route. End on the grid of all 10, zoom out, "MAPAY" title.

**Say:** "Flood. Rain. Roadwork. Closure. Traffic. Crash. In Miami, every drive has a surprise. MAPAY tells you before you leave."

### 2. The problem (0:15–0:30)

**Show:** the website on the PC in **Live** mode, zoomed out on Miami-Dade with every layer on → slow zoom into the Palmetto near FIU (traffic lines, construction) → cut to the iPhone map at NE 151st St by BBC (cyan flood hotspots).

**Say:** "We're FIU students. Most of us commute. The Palmetto at five, king tides on 151st Street, a new closure every week. Google Maps knows traffic, but it doesn't know your street floods at high tide."

### 3. The map (0:30–1:00)

**Show:** iPhone map in Demo mode → open the legend, toggle layers → tap a flood (sheet: source, confidence, "predicted"), a construction site, a crash → Preferences › Data → **Live**, real data loads → cut to the PC website, desktop layout, dark mode.

**Say:** "MAPAY puts nine hazard types on one map, each with its own colour: floods, weather, construction, closures, traffic, missing sidewalks, potholes, incidents and events. Tap anything to see where it came from and how sure we are. It runs on your iPhone and on the web, on live Miami data."

### 4. Routing (1:00–1:30)

**Show:** search "FIU Biscayne Bay" → place card → **Leave at… 5:30 PM** → Route Options (grouped hazard chips, "Recommended", the explanation) → tap each route to compare its hazards → **Open in Google Maps** shows the stops.

**Say:** "Pick where you're going and when you're leaving. MAPAY asks Google for alternative routes, then scores every one against the hazards on it at that time, using Google's traffic predictions and our flood forecast. And it tells you why it picked that one."

### 5. Routines + heads-up (1:30–1:55)

**Show:** Routines tab ("MMC → BBC 9:30, BBC → MMC 5–7 PM, weekdays") → Preferences › **Fire heads-up now** → lock the phone: the banner, the notification arriving, long-press → Start / Customize → Home Screen widget → Dynamic Island render (`island-flood.png`).

**Say:** "Save your routine once. Thirty minutes before every trip, MAPAY puts a live countdown on your Lock Screen with your route and the biggest hazard on it, plus a notification and a Home Screen widget. One tap to start."

### 6. Customize (1:55–2:20)

**Show:** tap **Customize** → type "stop at a Starbucks and stay off the Palmetto" → the new route next to the old one with the one-line explanation → tap **Start**: Google Maps opens with the stops.

**Say:** "Want to change it? Just say it. Gemini turns your words into rules, and our router builds the new route. Then MAPAY hands it to Google Maps. Google Maps drives. MAPAY steers: those extra stops are how we route you around the flood before Google knows it's there."

### 7. Under the hood (2:20–2:50)

Tap one hazard per source so its detail sheet shows the source; put the source name as a caption on each tap.

| Say | Show |
|---|---|
| "Under the hood: NOAA tides and FEMA flood zones predict flooding." | Tap a cyan flood: "predicted", NOAA tides, confidence |
| "Copernicus satellites confirm it." | Tap the satellite flood area with its pass time. **Only if it's in the data; otherwise cut this line.** |
| "The National Weather Service," | Tap the indigo rain area: NWS alert |
| "HERE traffic," | Tap a closure or crash: HERE live traffic |
| "City of Miami permits, Miami-Dade 311" | Zoom in on the orange permits, then tap a brown pothole: 311 |
| "and OpenStreetMap fill in the rest." | Tap a purple dotted street: no sidewalk, OpenStreetMap |
| "Local news is read by Laya, a model we fine-tuned on Miami news, and Gemini on Vertex AI." | Tap a pink crash pin: the news source |
| "Every hazard is a Bayesian belief that gets stronger or fades as evidence comes in." | Point at the confidence, then turn on "show unconfirmed" and tap an unconfirmed one |
| "FastAPI on Cloud Run, MongoDB Atlas, Google Maps Platform, and a native SwiftUI widget and Live Activity on the iPhone." | Split screen: website (Live) left, iPhone banner + widget right; tech names as small captions |

### 8. Close (2:50–3:00)

**Show:** the banner grid again, shrinking into the app icon → tagline → team names.

**Say:** "MAPAY. Miami streets change fast. Leave with a heads-up."

### Check with Jean before recording

- Is the Copernicus satellite flood layer live in production? If not, cut that line.
- Does the news pipeline actually use Laya in production?

## At the judging table

- **Two screens:** the iPhone and a laptop with the website, both in Demo. Switch to Live to prove it's real.
- **Let judges drive:** hand them the phone and have them type their own Customize prompt. It's the most memorable moment.
- **Fire heads-up now** on cue, lock the phone, show the banner.
- **Open in 20 seconds:** the section 2 hook + "let me show you". Then use [`faq.md`](faq.md), especially "Why does Google Maps show extra stops?" and "How do you know a street is flooded?".
