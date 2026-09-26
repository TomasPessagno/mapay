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

    subgraph Backend[FastAPI on Cloud Run]
        ING[Ingestion jobs]
        GEM[Gemini<br/>news extraction, satellite check,<br/>prompt to constraints, briefing]
        FUSE[Hazard beliefs<br/>Bayesian log-odds per hazard]
        R[Router<br/>Routes API alternatives<br/>+ hazard scoring + via waypoints]
        SCH[Routine scheduling<br/>upcoming legs, pre-route check,<br/>best time, briefings]
    end

    Sources --> ING
    ING --> GEM --> FUSE
    ING --> FUSE
    FUSE --> DB[(MongoDB Atlas)]
    DB --> R
    DB --> SCH --> R

    subgraph iPhone[iPhone: Capacitor app + widget extension]
        MAP[Colour-coded Google map]
        RUI[Routines + preferences]
        NOTIF[Local notifications]
        WID[Home-screen widget<br/>+ Live Activity]
        CARD[Huge in-app card]
        CUST[Customize sheet]
    end

    DB --> MAP
    RUI --> DB
    SCH -->|/routines/upcoming| NOTIF
    SCH -->|/routines/upcoming| WID
    SCH --> CARD
    NOTIF & WID & CARD -->|Customize| CUST
    CUST --> GEM --> R
    NOTIF & WID & CARD -->|Start| GM[Google Maps app<br/>deep link with waypoints]
    R --> GM
```

## UI flow

```mermaid
flowchart TD
    Map[Map tab:<br/>colour-coded map + bottom sheet] --> Search[Where to?<br/>Places search]
    Search --> Route[Route options:<br/>alternatives + hazards on route]
    Route --> Open[Open in Google Maps]
    Map --> Detail[Hazard detail sheet:<br/>what, source, confidence, pass time]
    Map --> Report[Report +:<br/>flood / construction / closure / pothole / no sidewalk]
    Routines[Routines tab] --> Editor[Routine editor:<br/>places, legs, at / between, repeat, heads-up time]
    Prefs[Preferences tab:<br/>hazard types, neighbourhoods, tolls, nav app]
    Editor --> Heads[30 min before a leg:<br/>notification + widget + in-app card]
    Heads -->|Start| Open
    Heads -->|Customize| Prompt[Customize sheet:<br/>'stop at Starbucks, avoid Brickell']
    Prompt --> Route
```
