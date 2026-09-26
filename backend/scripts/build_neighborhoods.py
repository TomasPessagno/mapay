"""Build app/data/neighborhoods.geojson from Miami open data and Census TIGER/Line.

Run from backend/: python -m scripts.build_neighborhoods

The result is a normalised FeatureCollection whose properties are exactly the
`GET /neighborhoods` contract: {id (slug), name, source}. Routing (A6) and
Customize (A10) turn a name into a polygon with app.routers.neighborhoods.get_polygon.

Sources:
  - City of Miami "Miami Neighborhoods" (datahub-miamigis.opendata.arcgis.com)
  - Miami-Dade municipal boundaries (gis-mdc.opendata.arcgis.com)
  - Census TIGER/Line places for Florida, filtered to Miami-Dade County (FIPS 086)
"""
import json
import re
import tempfile
from pathlib import Path

import geopandas as gpd
import httpx
from shapely.geometry import mapping, shape

OUT_PATH = Path(__file__).resolve().parent.parent / "app" / "data" / "neighborhoods.geojson"

CITY_NEIGHBORHOODS_URL = (
    "https://services1.arcgis.com/CvuPhqcTQpZPT9qY/arcgis/rest/services/"
    "Miami_Neighborhoods_Shapefile/FeatureServer/0"
)
MUNICIPALITIES_URL = (
    "https://services.arcgis.com/8Pc9XBTAsYuxx9Ny/arcgis/rest/services/"
    "Municipalitypoly_gdb/FeatureServer/0"
)
CENSUS_PLACES_URL = "https://www2.census.gov/geo/tiger/TIGER2024/PLACE/tl_2024_12_place.zip"
CENSUS_COUNTY_URL = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_5m.zip"

ARCGIS_PAGE_SIZE = 2000
MIAMI_DADE_COUNTY_FP = "086"
SIMPLIFY_TOLERANCE = 0.0002  # ~20 m at Miami's latitude
# Lower number wins when two sources share a slug (a city place shadows the county polygon).
SOURCE_PRIORITY = {"city_of_miami": 0, "municipality": 1, "census_place": 2}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def title_case(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name).strip()
    return cleaned.title() if cleaned.isupper() else cleaned


def simplify(geometry):
    simplified = geometry.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
    return geometry if simplified.is_empty else simplified


def fetch_arcgis(layer_url: str, name_field: str) -> list[dict]:
    """Page through an ArcGIS FeatureServer layer as GeoJSON (WGS84)."""
    features: list[dict] = []
    offset = 0
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        while True:
            response = client.get(
                f"{layer_url}/query",
                params={
                    "where": "1=1",
                    "outFields": name_field,
                    "returnGeometry": "true",
                    "outSR": "4326",
                    "f": "geojson",
                    "resultOffset": offset,
                },
            )
            response.raise_for_status()
            batch = response.json().get("features", [])
            features.extend(batch)
            if len(batch) < ARCGIS_PAGE_SIZE:
                break
            offset += ARCGIS_PAGE_SIZE
    return features


def download(url: str, directory: str, filename: str) -> Path:
    archive = Path(directory) / filename
    with httpx.stream("GET", url, timeout=120.0, follow_redirects=True) as response:
        response.raise_for_status()
        with open(archive, "wb") as handle:
            handle.writelines(response.iter_bytes())
    return archive


def load_census_places() -> list[dict]:
    """Download the Florida places shapefile and keep Miami-Dade cities / CDPs."""
    with tempfile.TemporaryDirectory() as tmp:
        places = gpd.read_file(download(CENSUS_PLACES_URL, tmp, "places.zip"))
        counties = gpd.read_file(download(CENSUS_COUNTY_URL, tmp, "counties.zip"))
    county = counties[(counties["STATEFP"] == "12") & (counties["COUNTYFP"] == MIAMI_DADE_COUNTY_FP)]
    if county.empty:
        raise RuntimeError("Miami-Dade County (12/086) missing from the TIGER county layer")
    frame = places.to_crs(county.crs)
    inside = frame.geometry.representative_point().within(county.geometry.iloc[0])
    frame = frame[inside].to_crs(4326)
    return [
        {"name": title_case(row["NAME"]), "geometry": mapping(row.geometry)}
        for _, row in frame.iterrows()
    ]


def arcgis_records(features: list[dict], name_field: str, source: str) -> list[dict]:
    records = []
    for feature in features:
        name = (feature.get("properties") or {}).get(name_field)
        geometry = feature.get("geometry")
        if name and geometry:
            records.append({"name": title_case(name), "geometry": geometry, "source": source})
    return records


def merge(records: list[dict]) -> dict[str, dict]:
    """One entry per slug; same-name geometries are unioned, best source wins."""
    by_id: dict[str, dict] = {}
    for record in records:
        slug = slugify(record["name"])
        if not slug:
            continue
        existing = by_id.get(slug)
        if existing is None:
            by_id[slug] = {
                "id": slug,
                "name": record["name"],
                "source": record["source"],
                "geometry": simplify(shape(record["geometry"])),
            }
            continue
        if SOURCE_PRIORITY[record["source"]] < SOURCE_PRIORITY[existing["source"]]:
            existing["source"] = record["source"]
        existing["geometry"] = simplify(existing["geometry"].union(shape(record["geometry"])))
    return by_id


def write(by_id: dict[str, dict]) -> None:
    features = [
        {
            "type": "Feature",
            "properties": {"id": e["id"], "name": e["name"], "source": e["source"]},
            "geometry": mapping(e["geometry"]),
        }
        for e in sorted(by_id.values(), key=lambda e: (SOURCE_PRIORITY[e["source"]], e["name"]))
    ]
    collection = {"type": "FeatureCollection", "features": features}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(collection, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(features)} neighborhoods to {OUT_PATH}")


def main() -> None:
    records = []
    records += arcgis_records(fetch_arcgis(CITY_NEIGHBORHOODS_URL, "LABEL"), "LABEL", "city_of_miami")
    records += arcgis_records(fetch_arcgis(MUNICIPALITIES_URL, "NAME"), "NAME", "municipality")
    records += [
        {"name": place["name"], "geometry": place["geometry"], "source": "census_place"}
        for place in load_census_places()
    ]
    write(merge(records))


if __name__ == "__main__":
    main()
