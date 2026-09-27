# MAPAY — a heads-up for the Miami commute

**Tagline:** Miami streets change fast. Leave with a heads-up.

## Inspiration

At FIU, the commute is part of the school day. A drive between MMC and BBC can mean the Palmetto at rush hour, a closure you didn’t know about, or a flooded street near home after a high tide. We wanted one place to see the street problems that matter before getting in the car—and a reminder that already knows the trips you make every week.

## What it does

MAPAY is an iPhone-first map and routine-trip assistant for Miami. Its map separates floods, construction, closures, traffic, weather, incidents, sidewalk gaps and other street issues by colour, icon and line style. Tap a feature to see where its information came from and when it was observed or updated.

Save routine trips such as MMC → BBC in the morning and BBC → MMC in an evening time window. MAPAY can suggest a time inside a window, then puts the upcoming trip on a local notification, home-screen widget and in-app heads-up card. Start opens the route in Google Maps. Customize accepts a prompt such as “stop at a Starbucks and stay off the Palmetto,” then shows the revised route and an explanation.

## How we built it

The app uses React, Ionic and Capacitor, with native SwiftUI widgets and a Live Activity. FastAPI and MongoDB power the backend. Google Maps supplies the map, traffic, places and route alternatives; MAPAY scores those alternatives against the hazards on each route and the driver’s preferences, then can add a detour waypoint. Google Maps handles turn-by-turn navigation.

Data comes from sources including NOAA tides and FEMA flood zones, NWS weather, City of Miami projects and permits, HERE road incidents, OpenStreetMap sidewalk tags, local-news feeds, user reports and Copernicus satellite products. A hazard gets a plain-language confidence level that can change as evidence arrives. Gemini extracts useful details from news, translates a Customize prompt into explicit route constraints, and explains route changes. The route ranking itself is deterministic.

## Challenges

Google’s routing service can’t be asked to avoid an arbitrary flooded street or neighborhood. We request route alternatives, compare them with the hazards and preferences, and add a waypoint when a route still crosses something the driver wants to avoid.

Miami data is uneven: a missing sidewalk tag doesn’t prove a sidewalk is absent, and satellite images don’t arrive street by street in real time. We show sources, timestamps and whether a hazard is predicted or observed, instead of presenting every mark as ground truth. The flood-confidence settings are hand-tuned heuristics, not calibrated forecasts.

The free Apple ID used for the demo also shapes the experience: the phone schedules its own notifications, the app must be refreshed through AltStore every seven days, and the Live Activity starts when the app opens—not from a server push while it is closed.

## Accomplishments

- Built an iPhone app with a colour-coded Miami map, hazard details, route alternatives and driver preferences.
- Connected recurring trips and time windows to a heads-up flow with local notifications, a home-screen widget, an in-app card and Start / Customize actions.
- Added the prompt-to-route flow, including a stop, a road to avoid, old/new route comparison and Google Maps handoff.
- Implemented a route-aware confidence model and ingestion paths for local news, weather, traffic, city data and satellite detections.
- Made the interface usable as an iOS-style app and as a web preview.

## What we learned

“No data” is not the same as “no hazard.” A useful map has to say what is predicted, what was observed, who reported it and how fresh it is. We also learned to give AI a bounded job: interpret messy language and evidence, while a repeatable routing algorithm makes the route decision.

## What’s next

Finish rehearsing the seeded demo with verified source timestamps; validate satellite detections when Miami is covered; improve how heavy rain changes flood risk; and check sidewalk coverage around both campuses. A paid Apple Developer account would unlock server push and TestFlight. Longer term, we want stronger ground truth and routines that get smarter as conditions change.

Satellite is not minute-by-minute street surveillance: Sentinel passes are typically days apart, products can arrive hours to a couple of days later, and clouds or buildings limit what each sensor sees. At the latest check, GFM had no recent pass that observed Miami, and Earth Engine registration was still needed to run the Sentinel-2 construction pipeline. The ingestion code is implemented; a current satellite detection still depends on a pass and a successful run.

## Built with

React, TypeScript, Ionic, Capacitor, SwiftUI, WidgetKit, ActivityKit, FastAPI, Python, MongoDB, Google Maps Platform, Gemini on Vertex AI, NOAA, NWS, FEMA, HERE, OpenStreetMap, Copernicus GFM, Sentinel-1, Sentinel-2, Google Earth Engine, Cloud Run, Cloud Scheduler.
