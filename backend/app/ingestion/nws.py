"""Ingestion: NWS active alerts for the Miami-Dade forecast zones -> ``weather`` beliefs.

Alerts come from ``/alerts/active`` filtered by the four Miami-Dade forecast zones
(FLZ073, FLZ074, FLZ173, FLZ174). Storm-based alerts already carry a polygon;
zone-based alerts do not, so their polygon is the union of the affected zones'
geometries, fetched from ``/zones/forecast/<id>`` and cached on disk because zone
boundaries change very rarely.

Each alert becomes a ``weather`` belief with the stable id ``nws:<alert id>``, a
``probability`` prior derived from its ``certainty`` (Observed > Likely > Possible)
and a numeric severity derived from its ``severity``. Updates reuse
``register_hazard``, which applies only the prior delta, so existing evidence is
preserved. Alerts that were registered before but are no longer active (absent
from the feed, cancelled, or past their end time) are re-registered with a
near-zero probability, pushing them below the routing threshold instead of
deleting the belief.
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from app.config import get_settings
from app.routing.beliefs import log_odds, register_hazard, utc

NWS_BASE_URL = "https://api.weather.gov"
ALERTS_URL = f"{NWS_BASE_URL}/alerts/active"
ZONE_URL = f"{NWS_BASE_URL}/zones/forecast/{{zone_id}}"

# The four public forecast zones that together cover Miami-Dade County.
MIAMI_DADE_ZONES = ("FLZ073", "FLZ074", "FLZ173", "FLZ174")

ZONE_CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "cache" / "nws_zones.json"
ZONE_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60  # zone boundaries are near-static
FALLBACK_USER_AGENT = "MAPAY (contact@example.com)"

# Certainty ordering: Observed > Likely > Possible. Unknowns sit below Possible.
CERTAINTY_PROBABILITY = {
    "observed": 0.95,
    "likely": 0.8,
    "possible": 0.5,
    "unlikely": 0.2,
    "unknown": 0.3,
}
DEFAULT_CERTAINTY_PROBABILITY = 0.3

# NWS severity strings -> the 1-5 numeric scale the map and router use.
SEVERITY_LEVEL = {"extreme": 5, "severe": 4, "moderate": 3, "minor": 2, "unknown": 1}
DEFAULT_SEVERITY_LEVEL = 1

# Near-zero prior for ended alerts: log-odds ~ -6.9, well below the 1.0 threshold.
ENDED_PROBABILITY = 0.001


def resolve_user_agent() -> str:
    """NWS requires a descriptive User-Agent. Prefer ``nws_user_agent`` from config.

    Falls back to a constant so offline callers (scripts, tests) never need the
    full app settings just to talk to NWS.
    """
    try:
        return get_settings().nws_user_agent or FALLBACK_USER_AGENT
    except Exception:  # noqa: BLE001 - missing settings must not break offline use
        return FALLBACK_USER_AGENT


def alerts_params() -> dict:
    return {"zone": ",".join(MIAMI_DADE_ZONES)}


async def fetch_active_alerts(*, client: httpx.AsyncClient | None = None,
                              user_agent: str | None = None) -> dict:
    """Raw active alerts for the Miami-Dade forecast zones."""
    headers = {"User-Agent": user_agent or resolve_user_agent(), "Accept": "application/geo+json"}
    if client is not None:
        response = await client.get(ALERTS_URL, params=alerts_params(), headers=headers)
    else:
        async with httpx.AsyncClient(timeout=20.0) as owned:
            response = await owned.get(ALERTS_URL, params=alerts_params(), headers=headers)
    response.raise_for_status()
    return response.json()


async def fetch_zone_geometry(zone_id: str, *, client: httpx.AsyncClient | None = None,
                              user_agent: str | None = None) -> dict | None:
    """The zone's GeoJSON geometry, or None when NWS returns no polygon for it."""
    headers = {"User-Agent": user_agent or resolve_user_agent(), "Accept": "application/geo+json"}
    url = ZONE_URL.format(zone_id=zone_id)
    if client is not None:
        response = await client.get(url, headers=headers)
    else:
        async with httpx.AsyncClient(timeout=20.0) as owned:
            response = await owned.get(url, headers=headers)
    response.raise_for_status()
    return response.json().get("geometry")


def load_zone_cache(path: Path = ZONE_CACHE_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("zones", {})
    except (json.JSONDecodeError, OSError):
        return {}


def save_zone_cache(zones: dict, path: Path = ZONE_CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"zones": zones}, separators=(",", ":")), encoding="utf-8")


def cache_is_fresh(path: Path = ZONE_CACHE_PATH, now: datetime | None = None) -> bool:
    if not path.exists():
        return False
    moment = utc(now or datetime.now(timezone.utc))
    written = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (moment - written).total_seconds() < ZONE_CACHE_TTL_SECONDS


def affected_zone_ids(feature: dict) -> list[str]:
    zones = feature.get("properties", {}).get("affectedZones") or []
    return [zone.rsplit("/", 1)[-1] for zone in zones]


def combine_geometries(geometries: list[dict]) -> dict | None:
    """Union polygon geometries into one GeoJSON geometry (MultiPolygon when disjoint)."""
    present = [geometry for geometry in geometries if geometry]
    if not present:
        return None
    if len(present) == 1:
        return present[0]
    union = unary_union([shape(geometry) for geometry in present])
    if union.is_empty:
        return None
    return json.loads(json.dumps(mapping(union)))


def alert_geometry(feature: dict, zones: dict) -> dict | None:
    geometry = feature.get("geometry")
    if geometry:
        return geometry
    return combine_geometries([zones.get(zone_id) for zone_id in affected_zone_ids(feature)])


def alert_hazard_id(alert_id: str) -> str:
    return f"nws:{alert_id}"


def alert_end(feature: dict) -> datetime | None:
    properties = feature.get("properties", {})
    for key in ("ends", "expires"):
        raw = properties.get(key)
        if raw:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return None


def alert_is_active(feature: dict, now: datetime) -> bool:
    """Cancelled alerts and alerts past their end/expiry are no longer active."""
    if feature.get("properties", {}).get("messageType") == "Cancel":
        return False
    end = alert_end(feature)
    return end is None or utc(end) > utc(now)


def certainty_probability(feature: dict) -> float:
    certainty = str(feature.get("properties", {}).get("certainty") or "").strip().lower()
    return CERTAINTY_PROBABILITY.get(certainty, DEFAULT_CERTAINTY_PROBABILITY)


def severity_level(feature: dict) -> int:
    severity = str(feature.get("properties", {}).get("severity") or "").strip().lower()
    return SEVERITY_LEVEL.get(severity, DEFAULT_SEVERITY_LEVEL)


def parse_alert(feature: dict, zones: dict) -> dict | None:
    """A registrable hazard, or None when the alert has no id or no resolvable geometry."""
    properties = feature.get("properties") or {}
    alert_id = properties.get("id")
    geometry = alert_geometry(feature, zones)
    if not alert_id or geometry is None:
        return None
    hazard_id = alert_hazard_id(alert_id)
    return {
        "hazard_id": hazard_id,
        "kind": "weather",
        "geometry": geometry,
        "properties": {
            "hazard_id": hazard_id,
            "kind": "weather",
            "probability": certainty_probability(feature),
            "severity": severity_level(feature),
            "event": properties.get("event"),
            "certainty": properties.get("certainty"),
            "expires": properties.get("expires"),
            "ends": properties.get("ends"),
            "headline": properties.get("headline"),
            "source_url": properties.get("@id"),
        },
    }


async def ensure_zones(features: list[dict], *, client: httpx.AsyncClient | None = None,
                       path: Path = ZONE_CACHE_PATH, now: datetime | None = None) -> dict:
    """Zone geometries for the alerts, refreshing the disk cache only when needed."""
    moment = utc(now or datetime.now(timezone.utc))
    zones = load_zone_cache(path) if cache_is_fresh(path, moment) else {}
    needed = {zone_id for feature in features for zone_id in affected_zone_ids(feature)
              if not feature.get("geometry")}
    missing = sorted(zone_id for zone_id in needed if zone_id not in zones)
    for zone_id in missing:
        geometry = await fetch_zone_geometry(zone_id, client=client)
        if geometry:
            zones[zone_id] = geometry
    if missing:
        save_zone_cache(zones, path)
    return zones


async def register_alerts(db, alerts: list[dict], now: datetime, *,
                          probability: float | None = None) -> int:
    for alert in alerts:
        properties = alert["properties"]
        if probability is not None:
            properties = {**properties, "probability": probability}
        await register_hazard(db, alert["hazard_id"], alert["kind"], alert["geometry"],
                              properties, now)
    return len(alerts)


async def close_ended(db, present_ids: set[str], now: datetime) -> int:
    """Re-register previously seen NWS beliefs missing from the feed with a near-zero prior."""
    closed = 0
    ended_log_odds = log_odds(ENDED_PROBABILITY)
    cursor = db.intel_cache.find({"type": "hazard_belief", "hazard_type": "weather",
                                  "hazard_id": {"$regex": "^nws:"}})
    async for doc in cursor:
        if doc["hazard_id"] in present_ids or doc.get("prior_log_odds", 0) <= ended_log_odds:
            continue
        await register_hazard(db, doc["hazard_id"], "weather", doc["geometry"],
                              {"probability": ENDED_PROBABILITY,
                               "severity": doc.get("severity", DEFAULT_SEVERITY_LEVEL)}, now)
        closed += 1
    return closed


async def _run(db, now: datetime, client: httpx.AsyncClient, path: Path) -> dict:
    payload = await fetch_active_alerts(client=client)
    features = payload.get("features", [])
    zones = await ensure_zones(features, client=client, path=path, now=now)
    parsed = []
    for feature in features:
        alert = parse_alert(feature, zones)
        if alert is None:
            continue
        alert["active"] = alert_is_active(feature, now)
        parsed.append(alert)
    active = [alert for alert in parsed if alert["active"]]
    ended = [alert for alert in parsed if not alert["active"]]
    await register_alerts(db, active, now)
    await register_alerts(db, ended, now, probability=ENDED_PROBABILITY)
    closed = await close_ended(db, {alert["hazard_id"] for alert in parsed}, now)
    return {"active": len(active), "ended": len(ended), "closed": closed}


async def run(db, now: datetime | None = None, *, client: httpx.AsyncClient | None = None,
              zone_cache_path: Path = ZONE_CACHE_PATH) -> dict:
    """Fetch active NWS alerts, upsert their beliefs and demote the ones that ended."""
    moment = utc(now or datetime.now(timezone.utc))
    if client is not None:
        return await _run(db, moment, client, zone_cache_path)
    async with httpx.AsyncClient(timeout=20.0) as owned:
        return await _run(db, moment, owned, zone_cache_path)


async def main() -> None:
    from app.db.mongo import close_client, get_db

    summary = await run(get_db())
    print(f"NWS weather alerts: {summary}")
    close_client()


if __name__ == "__main__":
    asyncio.run(main())
