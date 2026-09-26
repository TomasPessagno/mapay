"""One persistent intel_cache belief per stable layer hazard ID; atomic additive updates.

Evidence IDs must be stable upstream IDs (article URL, report ID, detection ID).
Embedded evidence receipts prevent duplicate delivery and support concurrent decay.
Beliefs intentionally have no expires_at: TTL deletion would erase their priors.
"""
import hashlib
import math
from datetime import datetime, timezone

from app.routing.belief_config import BELIEF_CONFIG as C


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def log_odds(probability: float) -> float:
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("Probability must be finite and in [0, 1]")
    p = min(1 - C["epsilon"], max(C["epsilon"], probability))
    return math.log(p / (1 - p))


def probability(value: float) -> float:
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exp = math.exp(value)
    return exp / (1 + exp)


def prior_probability(kind: str, properties: dict) -> float:
    if "probability" in properties:
        log_odds(properties["probability"])  # validate upstream value
        return properties["probability"]
    if kind == "flood":
        base = C["flood_zone_probability"].get(properties["fema_zone"].upper(), C["flood_default_probability"])
        delta = properties["tide_ft_mhhw"] - properties["flood_threshold_ft_mhhw"]
        return probability(log_odds(base) + delta * C["tide_log_odds_per_foot"])
    if kind == "pothole":
        density = properties["complaints_per_km"]
        if density < 0:
            raise ValueError("Complaint density cannot be negative")
        return probability(log_odds(C["pothole_base_probability"]) + density * C["pothole_log_odds_per_complaint_per_km"])
    if kind in ("construction", "closure"):
        return C["construction_probability"][properties["status"].lower()]
    raise ValueError(f"No prior mapping for {kind}")


def contribution(source: str, observed_at: datetime, now: datetime) -> float:
    value = C["evidence"][source]
    if source in ("crowd", "cleared"):
        age = max(0, (utc(now) - utc(observed_at)).total_seconds())
        value *= max(0, 1 - age / C["crowd_window_seconds"])
    return value


async def register_hazard(db, hazard_id: str, kind: str, geometry: dict, properties: dict,
                          now: datetime) -> None:
    """Layer ingestion calls this with its stable ID and FEMA/tide, 311 or permit fields.

    Prior refresh uses compare-and-swap plus $inc so concurrent evidence is preserved.
    """
    value = log_odds(prior_probability(kind, properties))
    key = f"belief:{hazard_id}"
    await db.intel_cache.update_one({"_id": key}, {"$setOnInsert": {
        "type": "hazard_belief", "hazard_id": hazard_id, "hazard_type": kind,
        "geometry": geometry, "severity": properties.get("severity", 1),
        "prior_log_odds": value, "log_odds": value, "last_updated": utc(now),
        "created_at": utc(now), "evidence": {},
    }}, upsert=True)
    while True:
        old = await db.intel_cache.find_one({"_id": key})
        result = await db.intel_cache.update_one(
            {"_id": key, "prior_log_odds": old["prior_log_odds"]},
            {"$inc": {"log_odds": value - old["prior_log_odds"]},
             "$set": {"prior_log_odds": value, "geometry": geometry},
             "$max": {"last_updated": utc(now)}})
        if result.matched_count:
            return


async def add_evidence(db, hazard_id: str, evidence_id: str, source: str,
                       observed_at: datetime, now: datetime) -> bool:
    """Exactly-once contribution per source/ID, using a single atomic Mongo update."""
    token = hashlib.sha256(f"{source}:{evidence_id}".encode()).hexdigest()
    path = f"evidence.{token}"
    value = contribution(source, observed_at, now)
    result = await db.intel_cache.update_one(
        {"_id": f"belief:{hazard_id}", path: {"$exists": False}},
        {"$inc": {"log_odds": value}, "$max": {"last_updated": utc(now)},
         "$set": {path: {"source": source, "observed_at": utc(observed_at),
                         "applied": value, "evaluated_at": utc(now)}}})
    if not result.matched_count and not await db.intel_cache.find_one({"_id": f"belief:{hazard_id}"}):
        raise ValueError(f"Unknown hazard: {hazard_id}")
    return bool(result.matched_count)


async def refresh_belief(db, hazard_id: str, now: datetime) -> dict:
    """Apply only the decay delta. CAS retries prevent double decay across workers."""
    key = f"belief:{hazard_id}"
    while True:
        doc = await db.intel_cache.find_one({"_id": key})
        if doc is None:
            raise ValueError(f"Unknown hazard: {hazard_id}")
        retry = False
        for token, evidence in doc["evidence"].items():
            if utc(now) <= utc(evidence["evaluated_at"]):
                continue
            value = contribution(evidence["source"], evidence["observed_at"], now)
            if value == evidence["applied"]:
                continue
            path = f"evidence.{token}"
            result = await db.intel_cache.update_one(
                {"_id": key, f"{path}.applied": evidence["applied"],
                 f"{path}.evaluated_at": evidence["evaluated_at"]},
                {"$inc": {"log_odds": value - evidence["applied"]},
                 "$set": {f"{path}.applied": value, f"{path}.evaluated_at": utc(now)},
                 "$max": {"last_updated": utc(now)}})
            retry |= not bool(result.matched_count)
        if not retry:
            return await db.intel_cache.find_one({"_id": key})


def snapshot(doc: dict) -> dict:
    return {"log_odds": doc["log_odds"], "prior_log_odds": doc["prior_log_odds"],
            "sources": {source: sum(e["applied"] for e in doc["evidence"].values() if e["source"] == source)
                        for source in C["evidence"]}}


def threshold_changes(before: dict, after: dict) -> list[dict]:
    changes = []
    for hazard_id, current in after.items():
        previous = before.get(hazard_id)
        if previous is None:  # No historical value: establish baseline, don't invent a crossing.
            continue
        if (previous["log_odds"] >= C["threshold"]) != (current["log_odds"] >= C["threshold"]):
            sources = [s for s in C["evidence"] if previous["sources"].get(s, 0) != current["sources"].get(s, 0)]
            if previous["prior_log_odds"] != current["prior_log_odds"]:
                sources.append("static/tide prior")
            changes.append({"hazard_id": hazard_id, "before": previous["log_odds"],
                            "after": current["log_odds"], "before_probability": probability(previous["log_odds"]),
                            "after_probability": probability(current["log_odds"]), "sources": sources})
    return changes
