"""Build app/data/neighborhoods.geojson from Miami open data and Census TIGER/Line.

Run from backend/: python -m scripts.build_neighborhoods  (needs requirements-dev.txt: geopandas)

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
# The 2020 Census merged the University Park CDP into Westchester, so the latest
# TIGER place file no longer has it. The endpoint contract still lists
# university-park, so restore its last published boundary from the 2019 vintage.
CENSUS_PLACES_RETIRED_URL = "https://www2.census.gov/geo/tiger/TIGER2019/PLACE/tl_2019_12_place.zip"
RETIRED_CENSUS_PLACE_GEOIDS = {"1273287"}  # University Park CDP, discontinued in 2020
CENSUS_COUNTY_URL = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_5m.zip"

ARCGIS_PAGE_SIZE = 2000
MIAMI_DADE_COUNTY_FP = "086"
SIMPLIFY_TOLERANCE = 0.0002  # ~20 m at Miami's latitude
# Lower number wins when two sources share a slug (a city place shadows the county polygon).
SOURCE_PRIORITY = {"city_of_miami": 0, "municipality": 1, "census_place": 2}

# The City's public layers are fine-grained sub-areas (Brickell Business District,
# Latin Quarter, ...). The coarser official layers we checked (NET Areas, Police
# Neighborhoods) merge Brickell with Downtown and Wynwood with Edgewater, which
# cannot be split cleanly. So the contract names below are unions of the fine
# sub-areas that make up each well-known neighbourhood. The fine sub-areas stay
# in the file too; ids match frontend/public/mocks/neighborhoods.json.
COMPOSITES = {
    "brickell": ("Brickell", [
        "brickell-business-district", "brickell-key", "brickell-residential-district",
        "brickell-village", "west-brickell",
    ]),
    "little-havana": ("Little Havana", [
        "east-little-havana", "latin-quarter", "la-pastorita",
    ]),
    "downtown": ("Downtown", [
        "cbd", "government-center", "bayside", "bayfront", "bicentennial-park",
        "miami-avenue", "parkwest", "lummus-park", "omni-pac", "riverfront",
    ]),
    "wynwood": ("Wynwood", ["wynwood-industrial-district"]),
    "coconut-grove": ("Coconut Grove", [
        "east-grove", "grove-center", "north-grove", "oakland-grove", "palm-grove",
        "south-grove", "south-grove-bayside", "west-grove",
    ]),
    "little-haiti": ("Little Haiti", ["lemon-city-little-haiti"]),
    "allapattah": ("Allapattah", ["allapattah-industrial-district"]),
}


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


def _census_place_records(frame) -> list[dict]:
    return [
        {"name": title_case(row["NAME"]), "geometry": mapping(row.geometry)}
        for _, row in frame.iterrows()
    ]


def _miami_dade(frame, county):
    """Keep places whose representative point falls inside the county polygon."""
    frame = frame.to_crs(county.crs)
    inside = frame.geometry.representative_point().within(county.geometry.iloc[0])
    return frame[inside].to_crs(4326)


def load_census_places() -> list[dict]:
    """Florida places filtered to Miami-Dade, plus retired CDPs the contract still lists."""
    with tempfile.TemporaryDirectory() as tmp:
        places = gpd.read_file(download(CENSUS_PLACES_URL, tmp, "places.zip"))
        retired = gpd.read_file(download(CENSUS_PLACES_RETIRED_URL, tmp, "places_2019.zip"))
        counties = gpd.read_file(download(CENSUS_COUNTY_URL, tmp, "counties.zip"))
    county = counties[(counties["STATEFP"] == "12") & (counties["COUNTYFP"] == MIAMI_DADE_COUNTY_FP)]
    if county.empty:
        raise RuntimeError("Miami-Dade County (12/086) missing from the TIGER county layer")
    records = _census_place_records(_miami_dade(places, county))
    retired = retired[retired["GEOID"].isin(RETIRED_CENSUS_PLACE_GEOIDS)]
    records += _census_place_records(_miami_dade(retired, county))
    return records


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


def composite_records(by_id: dict[str, dict]) -> list[dict]:
    """Well-known City neighbourhoods as unions of their fine sub-areas."""
    records = []
    for slug, (name, parts) in COMPOSITES.items():
        missing = [part for part in parts if part not in by_id]
        if missing:
            raise KeyError(f"{slug} references unknown sub-areas: {missing}")
        geometry = by_id[parts[0]]["geometry"]
        for part in parts[1:]:
            geometry = geometry.union(by_id[part]["geometry"])
        records.append({"id": slug, "name": name, "source": "city_of_miami",
                        "geometry": simplify(geometry)})
    return records


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
    by_id = merge(records)
    for composite in composite_records(by_id):
        by_id[composite["id"]] = composite
    write(by_id)


if __name__ == "__main__":
    main()
