# MAPAY judge FAQ

### Why not just use Google Maps or Waze?

They’re excellent at navigation and traffic. MAPAY adds a Miami street-problem view, remembers routine trips and preferences, and gives you a heads-up before departure; it hands the selected route to Google Maps for turn-by-turn directions.

### Where does the information come from?

We combine public sources such as NOAA tides, FEMA flood zones, NWS weather, City of Miami construction data and OpenStreetMap with HERE traffic incidents, local news, user reports and Copernicus satellite products. A tapped feature shows its source and timestamp where available.

### How do you decide a street is flooded?

MAPAY distinguishes a prediction based on flood zones and tide conditions from observed evidence such as satellite detections, news or a user report. It combines evidence into a hand-tuned confidence score; that score is a heuristic, not a certified flood forecast, and satellite radar can miss water between buildings.

### Is the satellite layer live?

No—“near-real-time” means a satellite pass can show up hours to a couple of days later, and passes over Miami are typically days apart. A pass must actually cover Miami, Sentinel-2 can be blocked by clouds, and we show the pass time rather than implying minute-by-minute coverage.

### What does AI do, and what stays deterministic?

Gemini extracts locations and hazards from local-news text, turns a prompt into explicit constraints, and explains a route change. The router compares Google’s alternatives against the hazards and preferences using fixed scoring rules; Gemini does not choose the road.

### What do you store, and is it private?

The hackathon build doesn’t require a name or account; it links saved places, routines and preferences to an anonymous device identifier. Those trips can still reveal sensitive places, so we don’t call the data private just because it lacks a name; retention needs more work before a broader launch.

### What does it cost?

Public weather, tide, city and satellite sources help keep data access affordable, but Google Maps and Gemini/Vertex AI can incur usage charges. We use hackathon cloud credits and have not measured a reliable per-commuter operating cost yet.

### Why are reminders local, and when does the Live Activity start?

The demo is signed with a free Apple ID, which can’t receive server push, so the phone schedules its notifications and the widget fetches its own updates. The Live Activity starts when MAPAY opens during the trip’s window; it can’t be launched from the server while the app is closed.

### What’s next?

We’ll verify the prepared campus commute against real source timestamps, improve rain-driven flood risk and sidewalk coverage, and validate satellite results when a Miami pass is available. A paid Apple Developer account would enable server push and TestFlight; better local ground truth is just as important.
