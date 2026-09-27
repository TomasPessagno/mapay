import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.routing.beliefs import snapshot
from app.routing.engine import pick_route
from app.routing.pre_route import check_routine


class PreRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 26, 20, 15, tzinfo=timezone.utc)
        self.departure = self.now + timedelta(minutes=45)
        self.route = {'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': [[-80, 25], [-80, 26]]}, 'properties': {}}]}
        self.hazard = {'hazard_id': 'flood-1', 'geometry': {'type': 'Point', 'coordinates': [-80, 25.5]},
                       'log_odds': 1.5, 'prior_log_odds': 0, 'evidence': {
                           'a': {'source': 'crowd', 'applied': 1.5}}}
        prior = {**self.hazard, 'log_odds': 0, 'evidence': {}}
        self.routine = {'_id': 'r', 'user_id': 'dev', 'tz': 'America/New_York',
                        'repeat': {'kind': 'custom', 'weekdays': ['sat']},
                        'legs': [{'from_place': 'p1', 'to_place': 'p2',
                                  'when': {'kind': 'window', 'start': '16:00', 'end': '18:00'},
                                  'route_state': {'departure': self.departure, 'route_geojson': self.route,
                                                  'beliefs': {'flood-1': snapshot(prior)}}}]}
        places = {'p1': {'_id': 'p1', 'location': {'type': 'Point', 'coordinates': [-80, 25]}},
                  'p2': {'_id': 'p2', 'location': {'type': 'Point', 'coordinates': [-80, 26]}}}
        self.db = SimpleNamespace(
            routines=SimpleNamespace(update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1))),
            places=SimpleNamespace(find_one=AsyncMock(side_effect=lambda q: places.get(q['_id']))),
            users=SimpleNamespace(find_one=AsyncMock(return_value={'preferences': {'avoid_tolls': True}})))

    async def test_crossing_computes_then_explains(self):
        with patch('app.routing.pre_route.current_hazards', AsyncMock(return_value=[self.hazard])), \
             patch('app.routing.pre_route.weighted_route', AsyncMock(return_value=self.route)) as compute, \
             patch('app.routing.pre_route.explain_recalculation', AsyncMock(return_value='Explanation')) as explain:
            result = await check_routine(self.db, self.routine, 0, self.departure, self.now)
        self.assertTrue(result['recalculated'])
        compute.assert_awaited_once()
        self.assertEqual(compute.await_args.kwargs['depart_at'], self.departure)
        self.assertEqual(compute.await_args.args[:2], ((25, -80), (26, -80)))  # the leg's places, (lat, lng)
        self.assertTrue(compute.await_args.kwargs['avoid_tolls'])  # the user's default preferences
        query, update = self.db.routines.update_one.await_args.args
        self.assertIn('legs.0.route_state', query)
        self.assertEqual(list(update['$set']), ['legs.0.route_state'])
        explain.assert_awaited_once()
        self.assertEqual(result['changes'][0]['sources'], ['crowd'])

    async def test_no_crossing_does_not_compute_or_call_llm(self):
        self.hazard['log_odds'] = 0.9
        with patch('app.routing.pre_route.current_hazards', AsyncMock(return_value=[self.hazard])), \
             patch('app.routing.pre_route.weighted_route', AsyncMock()) as compute, \
             patch('app.routing.pre_route.explain_recalculation', AsyncMock()) as explain:
            result = await check_routine(self.db, self.routine, 0, self.departure, self.now)
        self.assertFalse(result['recalculated'])
        compute.assert_not_awaited()
        explain.assert_not_awaited()

    async def test_outside_window_does_not_read_beliefs(self):
        with patch('app.routing.pre_route.current_hazards', AsyncMock()) as fetch:
            result = await check_routine(self.db, self.routine, 0, self.departure, self.now - timedelta(hours=2))
        self.assertEqual(result['reason'], 'outside_pre_route_window')
        fetch.assert_not_awaited()

    def test_hazard_changes_selected_route(self):
        def alt(coords, duration):
            return {'duration_s': duration, 'route_geojson': {'type': 'FeatureCollection', 'features': [
                {'type': 'Feature', 'geometry': {'type': 'LineString', 'coordinates': coords}, 'properties': {}}]}}
        fast = alt([[0, 0], [1, 0], [2, 0]], 100)
        slow = alt([[0, 0], [1, 1], [2, 0]], 200)
        hazard = {'hazard_id': 'flood-1', 'hazard_type': 'flood', 'severity': 3,
                  'geometry': {'type': 'Point', 'coordinates': [1, 0]}, 'log_odds': 1.5}
        def picked(*args):
            return pick_route([fast, slow], *args)['route_geojson']
        self.assertEqual(picked(), fast['route_geojson'])
        self.assertEqual(picked([hazard]), slow['route_geojson'])
        self.assertEqual(picked([{**hazard, 'log_odds': 0.9}]), fast['route_geojson'])
        ignore_floods = {'categories': {'flood': 'ignore'}}
        from app.routing.scoring import merge_preferences
        self.assertEqual(picked([hazard], merge_preferences(ignore_floods)), fast['route_geojson'])
