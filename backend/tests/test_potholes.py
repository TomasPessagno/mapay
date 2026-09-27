import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.ingestion import potholes

FIXTURE = Path(__file__).parent / "fixtures" / "miamidade_311_potholes.json"


def fixture_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def get(self, url, params=None):
        self.calls.append((url, params))
        return FakeResponse(self.pages[len(self.calls) - 1])


class FakeDb:
    def __init__(self):
        self.intel_cache = SimpleNamespace(update_one=AsyncMock())


class QueryTests(unittest.TestCase):
    def test_query_filters_potholes_to_the_bbox(self):
        params = potholes.build_query(offset=1000)
        self.assertIn("UPPER(issue_type) = 'POTHOLE'", params["where"])
        self.assertIn("latitude >= 25.55", params["where"])
        self.assertIn("latitude <= 25.98", params["where"])
        self.assertIn("longitude <= -80.1", params["where"])
        self.assertEqual(params["resultOffset"], 1000)
        self.assertEqual(params["f"], "json")


class NormaliseTests(unittest.TestCase):
    def test_strips_house_number_and_normalises(self):
        self.assertEqual(potholes.normalise_street("13296 SW 8TH ST"), "SW 8TH ST")
        self.assertEqual(potholes.normalise_street("1  Biscayne   Blvd"), "BISCAYNE BLVD")
        self.assertIsNone(potholes.normalise_street(""))
        self.assertIsNone(potholes.normalise_street(None))

    def test_slug_and_display(self):
        self.assertEqual(potholes.slugify("SW 8TH ST"), "sw-8th-st")
        self.assertEqual(potholes.display_street("SW 328TH ST"), "SW 328th St")
        self.assertEqual(potholes.display_street("BISCAYNE BLVD"), "Biscayne Blvd")


class ParseTests(unittest.TestCase):
    def test_skips_non_potholes_null_coords_and_out_of_area(self):
        records = potholes.parse_records(fixture_payload())
        self.assertEqual(len(records), 11)
        tickets = {r["ticket_id"] for r in records}
        self.assertNotIn("23-10000061", tickets)  # not a pothole
        self.assertNotIn("23-10000071", tickets)  # null coordinates
        self.assertNotIn("23-10000081", tickets)  # outside the Miami-Dade bbox


class AggregateTests(unittest.TestCase):
    def test_aggregates_chronic_corridors_and_ignores_small_streets(self):
        corridors = potholes.aggregate(potholes.parse_records(fixture_payload()))
        by_id = {corridor["hazard_id"]: corridor for corridor in corridors}
        self.assertEqual(set(by_id), {
            "pothole:311-corridor-sw-8th-st",
            "pothole:311-corridor-biscayne-blvd-1",
            "pothole:311-corridor-biscayne-blvd-2",
        })

        sw = by_id["pothole:311-corridor-sw-8th-st"]
        self.assertEqual((sw["count"], sw["complaints_per_km"], sw["severity"]), (3, 12.0, 2))
        self.assertEqual(sw["place"], "SW 8th St")
        self.assertEqual(sw["geometry"]["type"], "LineString")
        self.assertEqual(len(sw["geometry"]["coordinates"]), 3)

        # Two clusters 3 km apart on Biscayne Blvd are separate segments, each chronic.
        self.assertEqual(by_id["pothole:311-corridor-biscayne-blvd-1"]["count"], 3)
        self.assertEqual(by_id["pothole:311-corridor-biscayne-blvd-2"]["count"], 3)
        # NW 12th St only has two complaints: below the chronic threshold.
        self.assertNotIn("pothole:311-corridor-nw-12th-st", by_id)

    def test_distance_is_used_when_it_exceeds_the_floor(self):
        records = [{"ticket_id": str(i), "street": "SW 1ST ST",
                    "lat": 25.7600 + i * 0.004, "lng": -80.37} for i in range(4)]
        corridor, = potholes.aggregate(records, min_complaints=3)
        self.assertGreater(corridor["length_km"], potholes.MIN_CORRIDOR_KM)
        self.assertEqual(corridor["complaints_per_km"],
                         round(corridor["count"] / corridor["length_km"], 1))

    def test_single_point_corridor_is_a_point(self):
        corridor, = potholes.aggregate(
            [{"ticket_id": "t", "street": "SW 1ST ST", "lat": 25.76, "lng": -80.37}],
            min_complaints=1)
        self.assertEqual(corridor["geometry"], {"type": "Point", "coordinates": [-80.37, 25.76]})
        self.assertEqual(corridor["complaints_per_km"], 4.0)  # 1 / 0.25 km floor

    def test_severity_scales_with_density(self):
        self.assertEqual(potholes.severity_for(0), 1)
        self.assertEqual(potholes.severity_for(5), 2)
        self.assertEqual(potholes.severity_for(20), 3)


class FetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_paginates_until_a_short_page(self):
        pages = [
            {"features": [{"attributes": {"issue_type": "POTHOLE"}}, {"attributes": {}}]},
            {"features": [{"attributes": {"issue_type": "POTHOLE"}}]},
        ]
        client = FakeClient(pages)
        payload = await potholes.fetch(client, page_size=2)
        self.assertEqual(len(payload["features"]), 3)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[0][1]["resultOffset"], 0)
        self.assertEqual(client.calls[1][1]["resultOffset"], 2)

    async def test_one_short_page_stops(self):
        client = FakeClient([{"features": [{"attributes": {}}]}])
        await potholes.fetch(client, page_size=100)
        self.assertEqual(len(client.calls), 1)


class RegisterTests(unittest.IsolatedAsyncioTestCase):
    async def test_registers_prior_and_presentation_fields(self):
        corridor = {"hazard_id": "pothole:311-corridor-sw-8th-st",
                    "geometry": {"type": "LineString", "coordinates": [[-80.371, 25.7608]]},
                    "complaints_per_km": 12.0, "severity": 2, "place": "SW 8th St"}
        db = FakeDb()
        now = datetime.now(timezone.utc)
        with patch.object(potholes, "register_hazard", new=AsyncMock()) as register:
            count = await potholes.register_corridors(db, [corridor], now)

        self.assertEqual(count, 1)
        register.assert_awaited_once()
        hazard_id, kind, geometry, properties = register.await_args.args[1:5]
        self.assertEqual((hazard_id, kind, geometry), (corridor["hazard_id"], "pothole",
                                                       corridor["geometry"]))
        self.assertEqual(properties, {"complaints_per_km": 12.0, "severity": 2})

        filt, update = db.intel_cache.update_one.await_args.args
        self.assertEqual(filt, {"_id": "belief:pothole:311-corridor-sw-8th-st"})
        self.assertEqual(update["$set"]["properties"]["place"], "SW 8th St")
        self.assertIn("12.0 complaints/km", update["$set"]["properties"]["source_label"])

    async def test_run_uses_a_saved_payload_without_network(self):
        db = FakeDb()
        with patch.object(potholes, "register_hazard", new=AsyncMock()) as register, \
                patch.object(potholes, "fetch", new=AsyncMock()) as fetch:
            result = await potholes.run(db, datetime.now(timezone.utc), payload=fixture_payload())

        fetch.assert_not_awaited()
        self.assertEqual(result, {"complaints": 11, "corridors": 3})
        self.assertEqual(register.await_count, 3)


if __name__ == "__main__":
    unittest.main()
