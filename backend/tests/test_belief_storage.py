import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.routing.beliefs import add_evidence, refresh_belief


class StorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_add_is_atomic_increment_with_duplicate_guard(self):
        collection = SimpleNamespace(update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1)))
        now = datetime.now(timezone.utc)
        await add_evidence(SimpleNamespace(intel_cache=collection), 'h', 'report-1', 'crowd', now, now)
        query, update = collection.update_one.call_args.args
        self.assertEqual(update['$inc'], {'log_odds': 1.5})
        self.assertTrue(any(key.startswith('evidence.') and value == {'$exists': False}
                            for key, value in query.items()))
        self.assertNotIn('log_odds', update['$set'])

    async def test_decay_applies_only_delta_with_compare_and_swap(self):
        now = datetime.now(timezone.utc)
        doc = {'_id': 'belief:h', 'evidence': {'receipt': {
            'source': 'crowd', 'observed_at': now - timedelta(hours=1),
            'evaluated_at': now - timedelta(hours=1), 'applied': 1.5}}}
        collection = SimpleNamespace(find_one=AsyncMock(return_value=doc),
                                     update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1)))
        await refresh_belief(SimpleNamespace(intel_cache=collection), 'h', now)
        query, update = collection.update_one.call_args.args
        self.assertEqual(update['$inc']['log_odds'], -0.75)
        self.assertEqual(query['evidence.receipt.applied'], 1.5)


class BeliefAtTests(unittest.IsolatedAsyncioTestCase):
    def doc(self, now):
        observed = now - timedelta(hours=1)
        return {'_id': 'belief:h', 'hazard_id': 'h', 'log_odds': 2.0, 'prior_log_odds': 0.5, 'evidence': {
            'crowd': {'source': 'crowd', 'observed_at': observed, 'evaluated_at': observed, 'applied': 1.5},
            'news': {'source': 'news', 'observed_at': observed, 'evaluated_at': observed, 'applied': 0.5}}}

    def test_matches_refresh_belief_without_writing(self):
        from app.routing.beliefs import belief_at
        now = datetime.now(timezone.utc)
        doc = self.doc(now)
        result = belief_at(doc, now)
        # Crowd evidence one hour into its 2 h window keeps half of +1.5; news never decays.
        self.assertAlmostEqual(result['log_odds'], 2.0 - 0.75)
        self.assertAlmostEqual(result['evidence']['crowd']['applied'], 0.75)
        self.assertEqual(result['evidence']['news']['applied'], 0.5)
        self.assertEqual(doc['log_odds'], 2.0)  # the stored document is untouched
        self.assertEqual(doc['evidence']['crowd']['applied'], 1.5)

    def test_already_evaluated_later_is_left_alone(self):
        from app.routing.beliefs import belief_at
        now = datetime.now(timezone.utc)
        self.assertEqual(belief_at(self.doc(now), now - timedelta(hours=2))['log_odds'], 2.0)

    async def test_current_hazards_is_one_query(self):
        from app.routing.pre_route import current_hazards
        now = datetime.now(timezone.utc)
        cursor = SimpleNamespace(to_list=AsyncMock(return_value=[self.doc(now)] * 3))
        collection = SimpleNamespace(find=MagicMock(return_value=cursor), find_one=AsyncMock(),
                                     update_one=AsyncMock())
        hazards = await current_hazards(SimpleNamespace(intel_cache=collection), now)
        self.assertEqual(len(hazards), 3)
        self.assertAlmostEqual(hazards[0]['log_odds'], 1.25)
        collection.find.assert_called_once_with({'type': 'hazard_belief'})
        collection.find_one.assert_not_awaited()
        collection.update_one.assert_not_awaited()
