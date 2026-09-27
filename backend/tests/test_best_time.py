import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.routing.beliefs import log_odds
from app.routing.scoring import merge_preferences
from app.scheduling import best_time

NY = ZoneInfo("America/New_York")
START, END = datetime(2026, 9, 28, 17, 0, tzinfo=NY), datetime(2026, 9, 28, 19, 0, tzinfo=NY)
NOW = datetime(2026, 9, 28, 16, 30, tzinfo=NY)
# Predicted minutes by departure: rush hour at the start, best at 17:45.
MINUTES = {"17:00": 38, "17:15": 35, "17:30": 30, "17:45": 24, "18:00": 26, "18:15": 27, "18:30": 28,
           "18:45": 29, "19:00": 30}


def alt(minutes, coords=((-80.30, 25.80), (-80.20, 25.80))):
    return {"summary": "x", "duration_s": minutes * 60, "static_duration_s": 1500, "distance_m": 1,
            "route_geojson": {"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": coords}}]}}


def fake_routes(calls):
    async def route_alternatives(origin, destination, departure, *args):
        calls.append(departure)
        return [alt(MINUTES[departure.astimezone(NY).strftime("%H:%M")])]
    return route_alternatives


class BestTimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_picks_the_fastest_departure_and_reports_the_saving(self):
        calls = []
        with patch("app.scheduling.best_time.route_alternatives", fake_routes(calls)):
            best = await best_time.best_departure((25.8, -80.3), (25.8, -80.2), (START, END), merge_preferences(), [],
                                                  NOW)
        self.assertEqual(len(calls), 9)  # every 15 min, both ends included
        self.assertEqual(best["best_departure_at"].astimezone(NY).strftime("%H:%M"), "17:45")
        self.assertEqual((best["duration_s"], best["window_start_duration_s"], best["saving_s"]),
                         (24 * 60, 38 * 60, 14 * 60))

    async def test_hazards_are_scored_at_each_departure(self):
        # A crowd-reported flood on the route, observed at 16:45: fresh at 17:00, faded by 18:45 (2 h window).
        observed = datetime(2026, 9, 28, 16, 45, tzinfo=NY)
        doc = {"hazard_id": "flood:x", "hazard_type": "flood", "severity": 5, "prior_log_odds": log_odds(0.5),
               "log_odds": log_odds(0.5) + 1.5, "geometry": {"type": "Point", "coordinates": [-80.25, 25.80]},
               "evidence": {"r": {"source": "crowd", "observed_at": observed, "evaluated_at": observed,
                                  "applied": 1.5}}}
        flat = {k: 30 for k in MINUTES}
        with patch.dict(MINUTES, flat), patch("app.scheduling.best_time.route_alternatives", fake_routes([])):
            best = await best_time.best_departure((25.8, -80.3), (25.8, -80.2), (START, END), merge_preferences(),
                                                  [doc], NOW)
        # Same drive time everywhere, so the pick is the first departure once the report has faded below
        # the routing threshold: +1.5 fading over 2 h from 16:45 is +1.31 at 17:00, +1.12 at 17:15 (still
        # active) and +0.94 at 17:30 (not).
        self.assertEqual(best["best_departure_at"].astimezone(NY).strftime("%H:%M"), "17:30")

    async def test_cached_per_leg_and_day(self):
        calls = []
        with patch("app.scheduling.best_time.route_alternatives", fake_routes(calls)):
            args = ((25.8, -80.3), (25.8, -80.2), (START, END), merge_preferences(), [], NOW)
            await best_time.best_departure(*args)
            await best_time.best_departure(*args)
        self.assertEqual(len(calls), 9)

    async def test_skips_far_future_past_windows_and_past_departures(self):
        with patch("app.scheduling.best_time.route_alternatives", fake_routes([])):
            far = await best_time.best_departure((25.8, -80.3), (25.8, -80.2), (START, END), merge_preferences(), [],
                                                 NOW - timedelta(days=3))
            over = await best_time.best_departure((25.8, -80.3), (25.8, -80.2), (START, END), merge_preferences(), [],
                                                  END + timedelta(minutes=1))
        self.assertIsNone(far)
        self.assertIsNone(over)
        inside = best_time.departures(START, END, datetime(2026, 9, 28, 18, 5, tzinfo=NY))
        self.assertEqual(inside[0].strftime("%H:%M"), "18:15")
