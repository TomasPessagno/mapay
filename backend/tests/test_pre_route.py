import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import networkx as nx

from app.routing.beliefs import snapshot
from app.routing.engine import weighted_route
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
        self.routine = {'_id': 'r', 'days': ['sat'], 'time_window': ['16:00', '18:00'],
                        'origin': [25, -80], 'destination': [26, -80],
                        'route_state': {'departure': self.departure, 'route_geojson': self.route,
                                        'beliefs': {'flood-1': snapshot(prior)}}}
        self.db = SimpleNamespace(routines=SimpleNamespace(update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1))))

    async def test_crossing_computes_then_explains(self):
        with patch('app.routing.pre_route.current_hazards', AsyncMock(return_value=[self.hazard])), \
             patch('app.routing.pre_route.weighted_route', return_value=self.route) as compute, \
             patch('app.routing.pre_route.explain_recalculation', AsyncMock(return_value='Explanation')) as explain:
            result = await check_routine(self.db, self.routine, self.departure, self.now, object())
        self.assertTrue(result['recalculated'])
        compute.assert_called_once()
        explain.assert_awaited_once()
        self.assertEqual(result['changes'][0]['sources'], ['crowd'])

    async def test_no_crossing_does_not_compute_or_call_llm(self):
        self.hazard['log_odds'] = 0.9
        with patch('app.routing.pre_route.current_hazards', AsyncMock(return_value=[self.hazard])), \
             patch('app.routing.pre_route.weighted_route') as compute, \
             patch('app.routing.pre_route.explain_recalculation', AsyncMock()) as explain:
            result = await check_routine(self.db, self.routine, self.departure, self.now, None)
        self.assertFalse(result['recalculated'])
        compute.assert_not_called()
        explain.assert_not_awaited()

    async def test_outside_window_does_not_read_beliefs(self):
        with patch('app.routing.pre_route.current_hazards', AsyncMock()) as fetch:
            result = await check_routine(self.db, self.routine, self.departure, self.now - timedelta(hours=2), None)
        self.assertEqual(result['reason'], 'outside_pre_route_window')
        fetch.assert_not_awaited()

    def test_hazard_changes_selected_path(self):
        graph = nx.MultiDiGraph()
        for n, x, y in [('a', 0, 0), ('b', 1, 0), ('c', 1, 1), ('d', 2, 0)]:
            graph.add_node(n, x=x, y=y)
        for u, v, cost in [('a', 'b', 1), ('b', 'd', 1), ('a', 'c', 2), ('c', 'd', 2)]:
            graph.add_edge(u, v, travel_time=cost)
        hazard = {'geometry': {'type': 'Point', 'coordinates': [1, 0]}, 'log_odds': 1.5}
        baseline = weighted_route(graph, (0, 0), (0, 2))
        detour = weighted_route(graph, (0, 0), (0, 2), [hazard])
        self.assertNotEqual(baseline, detour)
