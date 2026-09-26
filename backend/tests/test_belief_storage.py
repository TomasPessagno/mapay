import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
