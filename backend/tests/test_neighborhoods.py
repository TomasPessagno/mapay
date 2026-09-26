import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import Polygon

from app.routers import neighborhoods

FIXTURE = Path(__file__).parent / "fixtures" / "neighborhoods.geojson"


class NeighborhoodSearchTests(unittest.TestCase):
    def test_search_without_query_returns_every_neighborhood(self):
        results = neighborhoods.search(path=FIXTURE)
        self.assertEqual({r["id"] for r in results}, {"brickell", "doral", "westchester"})
        for result in results:
            self.assertEqual(set(result), {"id", "name", "source"})

    def test_search_is_case_insensitive_substring(self):
        results = neighborhoods.search("BRICK", path=FIXTURE)
        self.assertEqual([r["id"] for r in results], ["brickell"])

    def test_search_matches_partial_name(self):
        results = neighborhoods.search("west", path=FIXTURE)
        self.assertEqual([r["id"] for r in results], ["westchester"])

    def test_search_with_no_match_is_empty(self):
        self.assertEqual(neighborhoods.search("atlantis", path=FIXTURE), [])

    def test_get_polygon_returns_shapely_geometry(self):
        geometry = neighborhoods.get_polygon("brickell", path=FIXTURE)
        self.assertIsInstance(geometry, Polygon)
        self.assertAlmostEqual(geometry.centroid.x, -80.19)
        self.assertAlmostEqual(geometry.centroid.y, 25.76)

    def test_get_polygon_unknown_id_returns_none(self):
        self.assertIsNone(neighborhoods.get_polygon("atlantis", path=FIXTURE))


class NeighborhoodEndpointTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(neighborhoods.router)
        self.client = TestClient(app)

    def test_endpoint_returns_id_name_source(self):
        with patch.object(neighborhoods, "DATA_PATH", FIXTURE):
            response = self.client.get("/neighborhoods")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 3)
        self.assertEqual(set(payload[0]), {"id", "name", "source"})

    def test_endpoint_applies_q_filter(self):
        with patch.object(neighborhoods, "DATA_PATH", FIXTURE):
            response = self.client.get("/neighborhoods", params={"q": "brickell"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["id"] for r in response.json()], ["brickell"])
