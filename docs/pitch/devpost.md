# MAPAY: a heads-up for the Miami commute

**Tagline:** Miami streets change fast. Leave with a heads-up.

## Inspiration

We're FIU students, and FIU is a commuter school. Most of us drive in every day: the Palmetto at 5 pm, I-95, the Dolphin, US-1. In the fall, king tides flood NE 151st Street by the Biscayne Bay campus and streets in Brickell and Miami Beach. There's a new closure or construction zone every week, and an afternoon storm can flood a street in twenty minutes.

Google Maps knows traffic. It doesn't know that your street floods at high tide, that the City just closed a lane for a utility permit, or that a crash on the local news is on your way home. We wanted one place that knows all of that, and that tells you *before* you leave, not when you're already stuck.

## What it does

MAPAY is an iPhone app (with a web version) for people who make the same trips every day.

- **One colour-coded map of what's wrong with Miami's streets.** Nine hazard types, each with its own colour, icon and line style: flooded streets, heavy rain and weather alerts, construction, road closures, congestion, missing sidewalks, potholes, incidents from the news, and events. Tap anything to see what it is, where the information came from, when it was last checked, and how confident we are. Lower-confidence items are marked "unconfirmed" or "predicted".
- **Hazard-aware routes.** Pick a destination and **leave now or at a set time**. MAPAY gets alternative routes from Google, scores each one against the hazards on it at that time (using Google's traffic predictions and our flood forecast) and your preferences (avoid, prefer to avoid, or don't care, per hazard type, plus neighbourhoods you'd rather skip), and explains why it recommends one.
- **Routines and a heads-up before every trip.** Save your routine once, for example FIU MMC → BBC at 9:30 and back between 5 and 7 pm on weekdays. Thirty minutes before each trip, MAPAY puts a Duolingo-style **Live Activity** on your Lock Screen and in the Dynamic Island: a countdown, the route, and the biggest hazard on it, coloured by hazard type. You also get a notification and a Home Screen widget. **Start** opens the route in Google Maps; **Customize** lets you change it.
- **Change the route in plain English.** Type "stop at a Starbucks and stay off the Palmetto". Gemini turns the sentence into constraints, and our deterministic router builds the new route and explains the difference.
- **Google Maps drives, MAPAY steers.** When Google's route would cross a flood or closure Google doesn't know about, MAPAY adds a visible steering stop so the Google Maps route bends around it. You keep Google's live traffic, voice, lane guidance and CarPlay.
- **Demo and Live modes.** Live mode uses real Miami data; Demo mode is a complete offline scenario across Miami-Dade for trying the app anywhere.

## How we built it

- **iPhone app:** React + TypeScript + Ionic (iOS mode), wrapped with Capacitor 8. Native Swift for the parts a web view can't do: a WidgetKit extension (Home Screen widget) and an ActivityKit **Live Activity** (Lock Screen banner + Dynamic Island), plus a small native plugin that connects them to the app. Installed on a real iPhone with AltStore and a free Apple ID.
- **Map:** Google Maps JavaScript API with a cloud-styled Map ID that follows light and dark mode, Places API (New) for search, and our own layer renderer for the nine hazard categories.
- **Backend:** FastAPI (Python) on Google Cloud Run, MongoDB Atlas, Shapely for geometry, Cloud Scheduler for ingestion jobs, GitHub Actions for CI/CD (including building the iPhone `.ipa` on GitHub's macOS runners).
- **Routing:** Google Routes API alternatives + our own scoring. Each hazard on a route adds a penalty of `weight(preference) × severity × probability`, counting hazards that intersect a ~30 m corridor around the route; for severe hazards we add "via" waypoints and ask again. Routing is deterministic: AI never picks the road.
- **How sure we are:** every hazard is a **Bayesian belief** in log-odds. Each source registers a hazard with a prior (a FEMA flood zone during a king tide, a City permit, a HERE incident), and news, user reports and other sources add or remove evidence over time. The router only avoids hazards above ~73% probability; the map shows the rest faded or as "unconfirmed".
- **Data sources:** NOAA tide predictions (Virginia Key) + FEMA flood zones + curated hotspots for flood prediction; National Weather Service alerts; HERE Traffic (incidents, closures, roadworks, flow); City of Miami Public Works permits and roadway projects; Miami-Dade 311 (potholes); OpenStreetMap (streets tagged without sidewalks); Google Routes predictions for typical congestion; Copernicus Sentinel-1 flood maps for satellite evidence [check]; local news (NBC6, WLRN, Local10, Miami Herald, CBS News Miami, GDELT).
- **AI:** Gemini on Vertex AI reads news articles into structured events (what, where, when, how serious), turns Customize prompts into route constraints, and writes the one-line route explanations. **Laya**, an open-source decision model we fine-tuned on Miami news [check: used in production?], does a fast first pass that sets aside stories that aren't about the streets.

## Challenges we ran into

- **Google's terms shaped the product.** We wanted an in-app turn-by-turn "route player" like Google Maps, but live turn-by-turn on the Routes API isn't allowed (it needs Google's separate Navigation SDK). We built an in-app animated route preview instead; on the iPhone it broke the Route button just before judging, so we cut it and hand off to Google Maps for the drive.
- **Street View and imagery.** We wanted to show and analyse Street View and satellite imagery inside the app to confirm floods and construction. Google Maps Platform terms don't allow analysing or creating content from Google imagery, so image analysis moved to free Copernicus Sentinel satellite data. Those passes come every few days, radar misses water between buildings, and clouds block optical images, so satellite evidence confirms hazards rather than detecting every one.
- **Other map apps.** Only Google Maps keeps multiple waypoints from a link. Apple Maps and Waze only take start and end, so our steering stops only survive in Google Maps. Waze has no public data API. And Google's terms don't allow showing Google routes and places on a non-Google map, so no MapKit or MapLibre.
- **Rate limits and free tiers, everywhere.** Our Gemini API key ran out of prepaid credit, so we moved to Vertex AI. The free MongoDB Atlas tier throttled us (one-document queries took 7+ seconds) after our map snapshot re-read 30,000 hazards on every ingestion job; we rewrote it to check a tiny change marker instead. Cloud Run killed the server at 512 MiB until we raised memory and made rebuilds lighter. Vercel's free plan hit its deployment limit, so the web preview moved to GitHub Pages. The public OpenStreetMap server was slow enough that generating the demo data took an hour.
- **Messy data sources.** There's no public API for Florida's FL511, so closures come from HERE. City permit data included 14,000+ planned roadway projects that would have painted every street orange, so we lean on the belief model and zoom rules to show what matters. OpenStreetMap usually doesn't tag sidewalks at all, and missing isn't the same as "no sidewalk". The 311 pothole dataset is historic. News stories have to be placed on the map from text like "near the Palmetto at Bird Road".
- **An iPhone without a paid developer account.** A free Apple ID can't receive push notifications, so the phone schedules its own heads-ups; it can't use App Groups, so the widget can't read the app's settings; AltStore allows only one app extension, so the widget and the Live Activity share it; and on a fresh install, one dismissed iOS prompt silently turned off Live Activities.

The data is **relatively accurate rather than perfect**, and the app says so: every hazard shows its source, when it was checked and how confident we are.

## Accomplishments that we're proud of

- A real iPhone app with a working Lock Screen Live Activity, Dynamic Island, Home Screen widget and actionable notifications, installed on a phone, not just a simulator.
- ~30,000 real hazards across Miami-Dade from more than ten public sources, fused with a probabilistic model instead of a pile of pins.
- Plain-English route changes that still go through a deterministic, explainable router.
- A web version with a desktop layout, a full offline demo mode, and an automatic iPhone build on every merge.

## What we learned

- Terms of service are product requirements: they decided our map provider, our navigation hand-off and our imagery source.
- Free tiers fail in surprising ways (throttling, memory, deploy limits), so design for them from the start: cache, read less, measure.
- Being honest about confidence ("predicted", "unconfirmed", "last checked") makes the map more trustworthy, not less.
- Let AI interpret and explain; keep the decision (the route) deterministic.

## What's next

- In-app turn-by-turn navigation with Google's Navigation SDK.
- A paid Apple Developer account: push notifications, fresher heads-ups without opening the app, App Groups for the widget, TestFlight.
- "Arrive by" routines and the best time to leave inside a window.
- Crowd reports from users, a walking mode, CarPlay, and more South Florida cities.
- Our own domain for the web version.

## Built with

react, typescript, ionic, capacitor, swift, swiftui, widgetkit, activitykit, python, fastapi, google-cloud-run, google-cloud-scheduler, mongodb-atlas, google-maps, google-places-api, google-routes-api, gemini, vertex-ai, laya, noaa, fema, national-weather-service, here-traffic, openstreetmap, copernicus-sentinel, github-actions, github-pages, altstore
