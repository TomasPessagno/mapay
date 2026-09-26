## Architecture (data flow)

```mermaid
flowchart LR
    subgraph Ingestion
        A1[NOAA Tides]
        A2[NWS Alerts]
        A3[FEMA / City GIS]
        A4[311 Potholes]
        A5[News / GDELT]
        A9[HERE Traffic Incidents]
        A6[Ticketmaster]
        A7[Nager.Date Holidays]
        A8[FDOT AADT - fallback]
        A10[Google Routes API<br/>typical traffic samples]
    end

    Ingestion --> W[Ingestion Workers]
    W --> M1[(intel_cache TTL)]
    W --> S[Static GeoJSON files]

    subgraph Backend[FastAPI Backend]
        R[Routing Engine\nGoogle Routes API alternatives\n+ hazard scoring + via waypoints]
        LB[LLM Briefing Agent]
        SC[Satellite Spot-Check Agent]
        NT[Pre-route Notifier\n/internal/tick]
    end

    M1 --> Backend
    S --> Backend
    Backend --> M2[(routes_cache TTL)]
    Backend --> M3[(hazard_reports)]
    Backend --> M4[(routines)]
    Backend --> M5[(devices + notifications_sent)]
    CS[Cloud Scheduler - every minute] --> NT
    NT --> FCM[Firebase Cloud Messaging]

    Backend --> F[React PWA + Google Maps JS API]
    F -->|Open in...| Ext[Google Maps / Apple Maps / Waze deep link]
    F -->|Report hazard| Backend
    FCM --> SW[Service worker push\nStart / Customize actions]
    FCM --> AW[Android home-screen widget\nCapacitor]
    SW --> F
    AW --> F
```

## UI flow

```mermaid
flowchart TD
    Home[Home widget:\nWhere to? + conditions strip] --> Map[Map + Route view]
    Home --> Routines[Routines config:\nday/time + preferences]
    Routines --> Widget[Push + home-screen widget\n30 min before departure]
    Widget -->|tap: start| GM[Google Maps deep link]
    Widget -->|tap: customize via prompt| Prompt[Prompt box] --> Map
    Map -->|Open in...| GM
    Map --> Scrubber[Time scrubber:\nNow / +30m / +1h / Custom]
    Scrubber --> Map
    Map --> Alerts[Alerts drawer:\nNWS + news incidents]
    Map --> ReportFAB[Report FAB:\npothole/flood/closure]
    Map --> Walk[Jogging/walk mode:\nGoogle Places parks + walking routes]
```

