"""Hand-picked heuristics, not calibrated probabilities. All belief tuning lives here."""
BELIEF_CONFIG = {
    "threshold": 1.0,
    "epsilon": 1e-6,
    "evidence": {"news": 0.5, "crowd": 1.5, "street_view": 2.5, "cleared": -1.5,
                 # A Sentinel-1/2 detection overlapping the hazard (GFM, Earth Engine; #9, #16).
                 "satellite": 1.0},
    "crowd_window_seconds": 7200,
    "check_window_minutes": (30, 60),
    "route_buffer_degrees": 0.0003,  # ~30 m in Miami; deliberately local, not global
    "hazard_weight_multiplier": 8.0,
    "flood_zone_probability": {"VE": 0.7, "V": 0.7, "AE": 0.6, "A": 0.6, "X": 0.1},
    "flood_default_probability": 0.3,
    "tide_log_odds_per_foot": 1.0,
    "pothole_base_probability": 0.1,
    "pothole_log_odds_per_complaint_per_km": 0.2,
    "construction_probability": {"closed": 0.95, "active": 0.8, "approved": 0.5,
                                 "pending": 0.2, "completed": 0.05, "cleared": 0.05},
    # Fixed prior for news-only `incident` hazards (crashes, police activity). Adding the
    # news evidence on top pushes p from 0.7 to ~0.79, above the 1.0 log-odds routing threshold.
    "incident_probability": 0.7,
    # Fixed priors for unmatched news-only `closure` / `construction` hazards (A28), e.g. "fire
    # shuts down roadway" with no City permit or HERE incident nearby. One report must show on the
    # map but not reroute by itself: prior (log-odds 0.20 / 0.0) + the +0.5 news evidence stays at
    # 0.70 / 0.50, under the 1.0 threshold (p ≈ 0.67 / 0.62). A second report or a crowd /
    # satellite confirmation crosses it, and severity then drives the detour penalty. Construction
    # starts lower because those stories are routinely longer-lived and less acute.
    "news_closure_probability": 0.55,
    "news_construction_probability": 0.5,
    # Fixed prior for a flood seen only by satellite (no hotspot there). Radar misses water between
    # buildings but rarely invents it; still below "certain" since each pass is hours to days old.
    "satellite_flood_probability": 0.75,
    # Fixed prior for a Gemini-confirmed Sentinel-2 construction site with no City permit nearby.
    "satellite_construction_probability": 0.7,
}
