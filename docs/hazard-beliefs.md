# Hazard confidence and routine checks

`backend/app/routing/belief_config.py` contains all hand-picked priors, evidence
log-likelihood ratios, decay windows, route proximity, routing penalty, and the
1.0 log-odds threshold (p ≈ 0.731). These are heuristics, not calibrated forecasts.

Layer ingestion calls `register_hazard(db, stable_id, kind, geometry, properties,
now)`. IDs must identify the same feature across refreshes. Geometry is GeoJSON
in longitude/latitude. Accepted prior properties:

- Any kind: `probability`, if the upstream layer already supplies it.
- Flood: `fema_zone`, `tide_ft_mhhw`, `flood_threshold_ft_mhhw` (same datum/units).
- Pothole: `complaints_per_km` from chronic 311 corridor data.
- Construction/closure: `status` (closed, active, approved, pending, completed, cleared).

Refreshing the prior applies its delta with `$inc`, preserving existing evidence.
The canonical `intel_cache` document is `belief:<stable_id>`, type `hazard_belief`,
with severity, geometry, prior_log_odds, log_odds, last_updated and evidence receipts.
It deliberately has no expires_at: the existing TTL index still expires ordinary
intel documents, but never silently deletes a running belief. Evidence receipts
remain for deduplication, so a long-running production system will need archival
before documents approach MongoDB's size limit.

`POST /report` accepts optional `hazard_id` and `cleared` (default false). A linked
report updates the corresponding belief; unlinked reports are stored without
inventing a spatial match or static prior. Cleared reports require a hazard ID.
Crowd and cleared evidence decay linearly over two hours, applied lazily during
route computations/checks as atomic deltas. Concurrent decay uses compare-and-swap.

News extraction and confirmed Street View producers can call
`app.agents.evidence.record_evidence` with a registered hazard ID and an IntelItem
shaped dict. IDs must be stable per observation; duplicate deliveries do not add
evidence twice. Street View requires `street_view_confirmed=True`; ordinary
satellite checks do not qualify automatically. Producers may also call
`add_evidence` directly with sources news/crowd/street_view/cleared. Only crowd and
cleared contributions decay; deleting a news document via TTL does not reverse
its contribution. Intel persistence and belief updates are separate writes;
retry the same stable evidence ID after an interruption to complete both safely.

Create a routine using `POST /routines`. Compute its starting route with
`POST /route` using `routine_id` and timezone-aware `depart_at`; this saves the
route geometry and belief snapshot in the routine, independently of route-cache
TTL. Alternatively, the first pre-route check establishes the initial route.

The browser timer calls `POST /routines/{id}/pre-route-check` with
`{"departure": "2026-09-26T17:00:00-04:00"}`. Server time must be 30–60 minutes
before departure, on a scheduled Miami-local day/time. Schedules currently use
same-day HH:MM windows. No background scheduler or push system is introduced.

Only hazards intersecting the previous route's approximately 30 m corridor are
compared against that route's saved snapshot. A plain conditional detects either
direction across 1.0; no change means no routing or Gemini call. A new departure
establishes a fresh baseline. Previously untracked hazards establish their first
snapshot when a route is computed; without a historical value they cannot count
as threshold crossings. No-crossing checks never advance the original snapshot.

Recalculation uses the loaded OSMnx graph's travel_time and deterministic hazard
penalties, then persists the new snapshot. Only after that does Gemini explain
the before/after probabilities and changed sources. Missing credentials or Gemini
failures yield a deterministic explanation without undoing the recalculation.

Repository integration limits: ingestion fetchers, graph build/load, and startup
graph loading were stubs at implementation time, and the committed flood layer
was empty. Populate real layer features via register_hazard and set
`app.state.graph` to the drive MultiDiGraph (nodes x/y, edges travel_time and
optional Shapely geometry) in the existing startup integration. Until then route
computation returns 503, rather than fabricating routes. News/vision extraction
must call the persistence adapter when those producers are implemented. No live
MongoDB or Gemini integration test is claimed.

Run focused tests: `PYTHONPATH=backend python -m unittest discover -s backend/tests -v`.
