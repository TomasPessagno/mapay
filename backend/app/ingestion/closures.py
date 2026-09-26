"""Ingestion: City of Miami roadway projects and permit street closures -> hazard beliefs.

Two City of Miami ArcGIS services feed construction and closure beliefs:

* ``RPW_Roadway_Infrastructure_Projects`` — capital projects as ``construction``.
* ``RPW_Permit_Status`` — street-segment closures joined to permits, as ``closure``
  (utility work becomes ``construction``).

Both are queried for the Miami bounding box. The permit MapServer rejects
``resultOffset``/``resultRecordCount`` ("Pagination is not supported"), so each layer is
paged by object id: request ``returnIdsOnly`` first, then fetch the features in
``PAGE_SIZE`` chunks with ``f=geojson``. Hazard ids stay stable as ``city:<layer>:<id>``.

Statuses are normalised to the keys of ``BELIEF_CONFIG["construction_probability"]``
(closed, active, approved, pending, completed, cleared); completed/cleared items whose
last activity is older than 30 days are skipped so the backlog never floods the beliefs.
"""
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from app.routing.beliefs import register_hazard, utc

log = logging.getLogger(__name__)

_SERVICE = "https://gis.miami.gov/gis/rest/services/PublicWorks"
ROADWAY_LAYER = f"{_SERVICE}/RPW_Roadway_Infrastructure_Projects/FeatureServer/0"
PERMIT_LAYER = f"{_SERVICE}/RPW_Permit_Status/MapServer/0"
MIAMI_BBOX = (-80.45, 25.55, -80.10, 25.98)  # west, south, east, north
PAGE_SIZE = 1000
STALE_AFTER = timedelta(days=30)

# The permit layer joins two tables; ArcGIS exposes the columns with table prefixes.
_P = "GISADMIN.StreetsToClose."
_A = "GISADMIN.%vw_PermitApplicationInformation."
_PERMIT_ID_FIELDS = (_A + "PermitNumber", _P + "APPID", _P + "PermitRequestId", _P + "OBJECTID")
_PERMIT_TYPE = _A + "PermitType"
_PERMIT_STATUS = _P + "Status"
_PERMIT_APP_STATUS = _A + "PermitStatus"
_PERMIT_APPLICATION_STATUS = _A + "PermitApplicationStatus"

# Raw ArcGIS values, lower-cased and de-punctuated, to the six belief config statuses.
_STATUS_ALIASES = {
    "active": "active",
    "in progress": "active",
    "construction": "active",
    "issued": "active",
    "extended": "active",
    "permit issued": "active",
    "approved": "approved",
    "plan approved": "approved",
    "plan approved finalization": "approved",
    "preliminarily sufficient": "approved",
    "pending": "pending",
    "on hold": "pending",
    "in review": "pending",
    "submitted": "pending",
    "preliminarily sufficient review ongoing": "pending",
    "bidding": "pending",
    "design": "pending",
    "planning": "pending",
    "a e selection": "pending",
    "pre construction": "pending",
    "dry run permit": "pending",
    "applicant corrections": "pending",
    "prescreen": "pending",
    "prescreen corrections": "pending",
    "applicant upload": "pending",
    "incomplete": "pending",
    "n a": "pending",
    "complete": "completed",
    "completed": "completed",
    "closed": "completed",
    "expired": "completed",
    "final completion": "completed",
    "administrative close out": "completed",
    "inactive": "cleared",
    "cancelled": "cleared",
    "canceled": "cleared",
    "denied": "cleared",
    "discarded": "cleared",
    "cleared": "cleared",
}
_SEVERITY = {"closed": 5, "active": 4, "approved": 3, "pending": 2, "completed": 1, "cleared": 1}


def normalise_status(raw) -> str | None:
    """Map a raw ArcGIS status/phase (e.g. "07- Construction") to a belief status."""
    if raw is None:
        return None
    text = re.sub(r"^\d+\s*[-:]\s*", "", str(raw).strip().lower())
    text = re.sub(r"[_/\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return _STATUS_ALIASES.get(text)


def _as_datetime(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _stale(status: str, observed: datetime | None, now: datetime) -> bool:
    return status in ("completed", "cleared") and observed is not None and observed < now - STALE_AFTER


def _merge_geometries(geometries: list[dict]) -> dict:
    if len(geometries) == 1:
        return geometries[0]
    types = {geometry.get("type") for geometry in geometries}
    if types == {"LineString"}:
        return {"type": "MultiLineString", "coordinates": [g["coordinates"] for g in geometries]}
    if types == {"Point"}:
        return {"type": "MultiPoint", "coordinates": [g["coordinates"] for g in geometries]}
    if types == {"Polygon"}:
        return {"type": "MultiPolygon", "coordinates": [g["coordinates"] for g in geometries]}
    return {"type": "GeometryCollection", "geometries": geometries}


def roadway_hazards(features: list[dict], now: datetime) -> list[dict]:
    """Roadway capital projects -> construction hazards, keyed by ArcGIS OBJECTID."""
    now = utc(now)
    hazards = []
    for feature in features:
        props = feature.get("properties") or {}
        geometry = feature.get("geometry")
        object_id = props.get("OBJECTID")
        if not geometry or object_id is None:
            continue
        status = (normalise_status(props.get("STATUS")) or normalise_status(props.get("PHASE"))
                  or "pending")
        observed = _as_datetime(props.get("CONSTR_EN")) or _as_datetime(props.get("last_edited_date"))
        if _stale(status, observed, now):
            continue
        project = props.get("PROJECT") or props.get("PRJ_DESC")
        street = props.get("STREET")
        hazards.append({
            "id": f"city:roadway:{object_id}",
            "kind": "construction",
            "status": status,
            "title": project or street or f"Roadway project {object_id}",
            "place": props.get("ADDRESS_") or street,
            "severity": _SEVERITY[status],
            "geometry": geometry,
        })
    return hazards


def _permit_id(props: dict):
    for field in _PERMIT_ID_FIELDS:
        value = props.get(field)
        if value not in (None, ""):
            return value
    return None


def _permit_kind(props: dict) -> str:
    permit_type = str(props.get(_PERMIT_TYPE) or "").lower()
    return "closure" if "closure" in permit_type else "construction"


def _permit_status(props: dict, kind: str) -> str:
    status = normalise_status(props.get(_PERMIT_STATUS))
    if status is None:
        status = normalise_status(props.get(_PERMIT_APP_STATUS))
    if status is None:
        status = normalise_status(props.get(_PERMIT_APPLICATION_STATUS))
    if status is None:
        status = "pending"
    total = props.get(_P + "LaneNumTot")
    closed = props.get(_P + "LaneNumClose")
    if kind == "closure" and status == "active" and total and closed and closed >= total:
        status = "closed"
    return status


def _permit_observed(props: dict) -> datetime | None:
    for field in (_P + "ClosureEndDate", _A + "ExpirationDate", _P + "last_edited_date",
                  _A + "CreatedDate"):
        value = _as_datetime(props.get(field))
        if value is not None:
            return value
    return None


def _permit_title(props: dict, permit_id) -> str:
    permit_type = props.get(_PERMIT_TYPE) or "Street permit"
    street = props.get(_P + "St_Label")
    return f"{permit_type} on {street}" if street else f"{permit_type} {permit_id}"


def _permit_place(props: dict) -> str | None:
    from_street = props.get(_P + "FROM_ST")
    to_street = props.get(_P + "TO_ST")
    if from_street and to_street:
        return f"{from_street} – {to_street}"
    return props.get(_A + "ProjectAddress") or props.get(_P + "St_Label")


def permit_hazards(features: list[dict], now: datetime) -> list[dict]:
    """Permit street segments -> closure/construction hazards, one per permit number.

    A permit is joined to several street segments; they are merged into one geometry so a
    single permit cannot add its penalty to a route several times.
    """
    now = utc(now)
    groups: dict[str, list[tuple[dict, dict]]] = {}
    for feature in features:
        props = feature.get("properties") or {}
        geometry = feature.get("geometry")
        permit_id = _permit_id(props)
        if not geometry or permit_id is None:
            continue
        groups.setdefault(str(permit_id), []).append((props, geometry))

    hazards = []
    for permit_id, rows in groups.items():
        kinds = {_permit_kind(props) for props, _ in rows}
        status, status_props = max(
            ((_permit_status(props, _permit_kind(props)), props) for props, _ in rows),
            key=lambda pair: _SEVERITY[pair[0]])
        observed = max((date for date in (_permit_observed(props) for props, _ in rows)
                        if date is not None), default=None)
        if _stale(status, observed, now):
            continue
        hazards.append({
            "id": f"city:permit:{permit_id}",
            "kind": "closure" if "closure" in kinds else "construction",
            "status": status,
            "title": _permit_title(status_props, permit_id),
            "place": _permit_place(status_props),
            "severity": _SEVERITY[status],
            "geometry": _merge_geometries([geometry for _, geometry in rows]),
        })
    return hazards


def _bbox() -> str:
    west, south, east, north = MIAMI_BBOX
    return f"{west},{south},{east},{north}"


async def _get(client, layer: str, params: dict) -> dict:
    response = await client.get(f"{layer}/query", params=params)
    response.raise_for_status()
    return response.json()


async def _object_ids(client, layer: str) -> list:
    data = await _get(client, layer, {
        "where": "1=1", "geometry": _bbox(), "geometryType": "esriGeometryEnvelope",
        "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        "returnIdsOnly": "true", "f": "json",
    })
    return data.get("objectIds") or []


async def _features_by_ids(client, layer: str, object_ids: list) -> list[dict]:
    features = []
    for start in range(0, len(object_ids), PAGE_SIZE):
        chunk = object_ids[start:start + PAGE_SIZE]
        data = await _get(client, layer, {
            "objectIds": ",".join(str(i) for i in chunk),
            "outFields": "*", "outSR": "4326", "returnGeometry": "true", "f": "geojson",
        })
        features.extend(data.get("features") or [])
    return features


async def fetch(layer: str) -> list[dict]:
    """All features in the Miami bbox for one ArcGIS layer endpoint, paged by object id."""
    async with httpx.AsyncClient(timeout=60) as client:
        object_ids = await _object_ids(client, layer)
        return await _features_by_ids(client, layer, object_ids)


async def fetch_all() -> dict[str, list[dict]]:
    return {"roadway": await fetch(ROADWAY_LAYER), "permit": await fetch(PERMIT_LAYER)}


async def run(db, now: datetime) -> int:
    """Register construction/closure beliefs for both City of Miami layers. Returns the count."""
    current = utc(now)
    raw = await fetch_all()
    hazards = (roadway_hazards(raw.get("roadway", []), current)
               + permit_hazards(raw.get("permit", []), current))
    for hazard in hazards:
        await register_hazard(db, hazard["id"], hazard["kind"], hazard["geometry"],
                              {"status": hazard["status"], "severity": hazard["severity"]}, current)
    log.info("city GIS: registered %d construction/closure hazards", len(hazards))
    return len(hazards)
