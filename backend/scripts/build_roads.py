"""Build app/data/roads.geojson: geometry of Miami's major roads from OpenStreetMap (Overpass).

/customize avoids roads by name ("stay off the Palmetto"). Asking the public Overpass servers at
request time is slow and often times out, so the roads people name most are snapshotted here and
only unknown names fall back to a live query. Re-run when roads change (rarely):

    cd backend && .venv/bin/python -m scripts.build_roads
"""
import asyncio
import json
from pathlib import Path

import httpx
from shapely.geometry import LineString, MultiLineString, mapping
from shapely.ops import linemerge

OUT = Path(__file__).resolve().parents[1] / "app" / "data" / "roads.geojson"
URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter")
BBOX = "25.13,-80.87,25.98,-80.10"  # Miami-Dade: south, west, north, east
MAJOR = 'highway~"^(motorway|trunk|primary)(_link)?$"'

# label → (aliases people type, Overpass way selectors). Aliases are matched lower-cased.
ROADS = {
    "SR 826": (["palmetto", "palmetto expressway", "sr 826", "sr-826", "fl 826", "826"],
               [f'way[{MAJOR}][ref~"(^|[ ;])826($|[ ;])"]']),
    "SR 836": (["dolphin", "dolphin expressway", "sr 836", "sr-836", "836"],
               [f'way[{MAJOR}][ref~"(^|[ ;])836($|[ ;])"]']),
    "Florida's Turnpike": (["turnpike", "florida's turnpike", "floridas turnpike", "hefT", "homestead extension",
                            "sr 821", "821"],
                           ['way[highway~"^motorway(_link)?$"][name~"Turnpike|Homestead Extension",i]',
                            f'way[{MAJOR}][ref~"(^|[ ;])821($|[ ;])"]']),
    "I-95": (["i-95", "i95", "i 95", "interstate 95", "95"], ['way[highway~"^motorway(_link)?$"][ref~"(^|[ ;])I 95($|[ ;])"]']),
    "I-195": (["i-195", "i195", "i 195", "julia tuttle", "julia tuttle causeway", "195"],
              ['way[highway~"^motorway(_link)?$"][ref~"(^|[ ;])I 195($|[ ;])"]']),
    "I-395": (["i-395", "i395", "i 395", "macarthur causeway", "395"],
              ['way[highway~"^motorway(_link)?$"][ref~"(^|[ ;])I 395($|[ ;])"]']),
    "I-75": (["i-75", "i75", "i 75", "75"], ['way[highway~"^motorway(_link)?$"][ref~"(^|[ ;])I 75($|[ ;])"]']),
    "SR 874": (["don shula", "don shula expressway", "sr 874", "874"], [f'way[{MAJOR}][ref~"(^|[ ;])874($|[ ;])"]']),
    "SR 878": (["snapper creek", "snapper creek expressway", "sr 878", "878"], [f'way[{MAJOR}][ref~"(^|[ ;])878($|[ ;])"]']),
    "SR 112": (["airport expressway", "sr 112", "112"], [f'way[{MAJOR}][ref~"(^|[ ;])112($|[ ;])"]']),
    "SR 924": (["gratigny", "gratigny parkway", "sr 924", "924"], [f'way[{MAJOR}][ref~"(^|[ ;])924($|[ ;])"]']),
    "US 1": (["us 1", "us-1", "us1", "south dixie highway", "dixie highway"], [f'way[{MAJOR}][ref~"(^|[ ;])US 1($|[ ;])"]']),
    "US 41": (["us 41", "us-41", "tamiami trail", "sw 8th street", "sw 8th st", "calle ocho"],
              [f'way[{MAJOR}][ref~"(^|[ ;])US 41($|[ ;])"]']),
    "US 27": (["us 27", "us-27", "okeechobee road"], [f'way[{MAJOR}][ref~"(^|[ ;])US 27($|[ ;])"]']),
    "Biscayne Boulevard": (["biscayne", "biscayne boulevard", "biscayne blvd"],
                           ['way[highway][name~"^Biscayne Boulevard",i]']),
}


async def fetch(selectors: list[str], client: httpx.AsyncClient) -> dict:
    query = "[out:json][timeout:90];(" + "".join(f"{s}({BBOX});" for s in selectors) + ");out geom;"
    for attempt in range(4):
        for url in URLS:
            try:
                response = await client.post(url, data={"data": query},
                                             headers={"User-Agent": "MAPAY/0.1 (https://github.com/TomasPessagno/mapay)"})
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as exc:
                print(f"  {url.split('/')[2]} failed ({type(exc).__name__}), retrying")
        await asyncio.sleep(10 * (attempt + 1))
    raise RuntimeError("Overpass unavailable")


def to_geometry(payload: dict):
    lines = [LineString([(p["lon"], p["lat"]) for p in way["geometry"]])
             for way in payload.get("elements", []) if len(way.get("geometry") or []) >= 2]
    if not lines:
        return None
    merged = linemerge(MultiLineString(lines)).simplify(0.00005)  # ~5 m: plenty for a 25 m buffer
    return merged if merged.geom_type == "MultiLineString" else MultiLineString([merged])


async def main() -> None:
    features = []
    async with httpx.AsyncClient(timeout=120) as client:
        for label, (aliases, selectors) in ROADS.items():
            print(label)
            geometry = to_geometry(await fetch(selectors, client))
            if geometry is None:
                print("  no ways found, skipped")
                continue
            print(f"  {len(geometry.geoms)} lines")
            features.append({"type": "Feature", "geometry": mapping(geometry),
                             "properties": {"label": label, "aliases": sorted({a.lower() for a in aliases})}})
    OUT.write_text(json.dumps({"type": "FeatureCollection", "attribution": "© OpenStreetMap contributors (ODbL)",
                               "features": features}, separators=(",", ":")) + "\n")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    asyncio.run(main())
