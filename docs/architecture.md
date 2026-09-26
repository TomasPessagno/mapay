## Architecture (data flow)

```mermaid
flowchart LR
    subgraph Sources
        NEWS[Local news RSS + GDELT]
        WX[NWS alerts + forecast<br/>radar]
        SAT[Satellite<br/>Copernicus GFM<br/>Sentinel-1/2 via Earth Engine]
        MAPS[Maps APIs<br/>Google, HERE, OSM]
        GOV[Miami open data<br/>City GIS, 311, FEMA, NOAA tides]
    end

    CS[Cloud Scheduler] -->|/internal/ingest| ING
    CS -->|/internal/tick every minute| NT

    subgraph Backend[FastAPI on Cloud Run]
        ING[Ingestion jobs]
        GEM[Gemini<br/>news extraction, satellite check,<br/>prompt to constraints, briefing]
        FUSE[Hazard fusion<br/>category, severity, confidence, expiry]
        R[Router<br/>Routes API alternatives<br/>+ hazard scoring + via waypoints]
        SCH[Routine scheduling<br/>next leg, best time]
        NT[Pre-route notifier]
    end

    Sources --> ING
    ING --> GEM --> FUSE
    ING --> FUSE
    FUSE --> DB[(MongoDB Atlas)]
    DB --> R
    DB --> SCH --> NT
    NT --> R
    NT --> FCM[Firebase Cloud Messaging]

    subgraph Client[React PWA + Capacitor Android]
        MAP[Colour-coded Google map]
        RUI[Routines + preferences]
        CARD[Push + huge card<br/>+ home-screen widget]
        CUST[Customize prompt]
    end

    DB --> MAP
    RUI --> DB
    FCM --> CARD
    CARD -->|Customize| CUST --> GEM
    GEM --> R
    R --> GM[Google Maps app<br/>deep link with waypoints]
    CARD -->|Start| GM
```

## UI flow

```mermaid
flowchart TD
    Home[Home: colour-coded map + legend] --> Search[Where to?<br/>Places search]
    Search --> Route[Route card:<br/>alternatives + hazards on route]
    Route --> Open[Open in Google Maps]
    Home --> Detail[Tap a hazard:<br/>what, source, confidence, pass time]
    Home --> Report[Report FAB:<br/>flood / construction / closure / pothole / no sidewalk]
    Home --> Routines[Routines:<br/>places, legs, at / between, repeat]
    Routines --> Prefs[Preferences:<br/>categories + neighbourhoods]
    Routines --> Heads[30 min before a leg:<br/>push + huge card + home-screen widget]
    Heads -->|Start| Open
    Heads -->|Customize| Prompt[Prompt:<br/>'stop at Starbucks, avoid Brickell']
    Prompt --> Route
```
