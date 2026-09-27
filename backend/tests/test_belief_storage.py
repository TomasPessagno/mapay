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

    async def test_current_hazards_is_one_projected_query(self):
        from app.routing import pre_route
        from app.routing.pre_route import current_hazards
        now = datetime.now(timezone.utc)
        cursor = SimpleNamespace(to_list=AsyncMock(return_value=[self.doc(now)] * 3))
        collection = SimpleNamespace(find=MagicMock(return_value=cursor), find_one=AsyncMock(),
                                     update_one=AsyncMock())
        hazards = await current_hazards(SimpleNamespace(intel_cache=collection), now)
        self.assertEqual(len(hazards), 3)
        self.assertAlmostEqual(hazards[0]['log_odds'], 1.25)
        collection.find.assert_called_once_with({'type': 'hazard_belief'}, pre_route.BELIEF_PROJECTION)
        collection.find_one.assert_not_awaited()
        collection.update_one.assert_not_awaited()


class BulkRegisterTests(unittest.IsolatedAsyncioTestCase):
    """register_hazards must leave exactly what register_hazard would, in bulk."""

    class Cache:
        def __init__(self):
            self.docs = {}
            self.bulk_calls = 0

        def find(self, query, projection=None):
            ids = query["_id"]["$in"]
            return SimpleNamespace(to_list=AsyncMock(return_value=[
                dict(self.docs[i]) for i in ids if i in self.docs]))

        async def find_one(self, query):
            return self.docs.get(query["_id"])

        async def update_one(self, query, update, upsert=False):
            doc = self.docs.get(query["_id"])
            if doc is None:
                if upsert:
                    self.docs[query["_id"]] = {"_id": query["_id"], **update.get("$setOnInsert", {})}
                return SimpleNamespace(matched_count=0)
            if any(doc.get(k) != v for k, v in query.items()):
                return SimpleNamespace(matched_count=0)
            for k, v in update.get("$inc", {}).items():
                doc[k] = doc.get(k, 0) + v
            doc.update(update.get("$set", {}))
            for k, v in update.get("$max", {}).items():
                doc[k] = max(doc.get(k, v), v)
            return SimpleNamespace(matched_count=1)

        async def bulk_write(self, operations, ordered=False):
            self.bulk_calls += 1
            for op in operations:
                await self.update_one(op._filter, op._doc, upsert=op._upsert)

    async def test_matches_register_hazard_and_keeps_evidence(self):
        from app.routing.beliefs import register_hazard, register_hazards
        now = datetime.now(timezone.utc)
        geometry = {"type": "Point", "coordinates": [-80.2, 25.8]}
        one, bulk = self.Cache(), self.Cache()
        props = {"status": "active", "severity": 4, "title": "Utility work on SW 8th St", "noise": 1}
        await register_hazard(SimpleNamespace(intel_cache=one), "city:permit:1", "construction", geometry, props, now)
        await register_hazards(SimpleNamespace(intel_cache=bulk), [
            {"id": "city:permit:1", "kind": "construction", "geometry": geometry, "properties": props}], now)
        self.assertEqual(one.docs, bulk.docs)
        self.assertEqual(bulk.docs["belief:city:permit:1"]["properties"], {"title": "Utility work on SW 8th St"})
        # Evidence arrives, then the permit's status changes: only the prior delta moves log_odds.
        for cache in (one, bulk):
            cache.docs["belief:city:permit:1"]["log_odds"] += 1.5
        props2 = {**props, "status": "closed"}
        await register_hazard(SimpleNamespace(intel_cache=one), "city:permit:1", "construction", geometry, props2, now)
        await register_hazards(SimpleNamespace(intel_cache=bulk), [
            {"id": "city:permit:1", "kind": "construction", "geometry": geometry, "properties": props2}], now)
        self.assertAlmostEqual(bulk.docs["belief:city:permit:1"]["log_odds"],
                               one.docs["belief:city:permit:1"]["log_odds"])
        self.assertAlmostEqual(bulk.docs["belief:city:permit:1"]["log_odds"],
                               bulk.docs["belief:city:permit:1"]["prior_log_odds"] + 1.5)

    async def test_thousands_in_a_few_bulk_writes(self):
        from app.routing.beliefs import register_hazards
        cache = self.Cache()
        hazards = [{"id": f"city:permit:{i}", "kind": "construction", "properties": {"status": "active"},
                    "geometry": {"type": "Point", "coordinates": [-80.2, 25.8]}} for i in range(2500)]
        self.assertEqual(await register_hazards(SimpleNamespace(intel_cache=cache), hazards,
                                                datetime.now(timezone.utc)), 2500)
        self.assertEqual(len(cache.docs), 2500)
        self.assertEqual(cache.bulk_calls, 3)  # 1000 per batch


class BeliefCacheTests(unittest.IsolatedAsyncioTestCase):
    """A29: one full belief read per 15 min per process, shared by routes, pre-route and /layers."""

    @staticmethod
    def db():
        doc = {'_id': 'belief:h', 'hazard_id': 'h', 'log_odds': 2.0, 'prior_log_odds': 2.0, 'evidence': {}}
        cursor = SimpleNamespace(to_list=AsyncMock(return_value=[doc]))
        return SimpleNamespace(intel_cache=SimpleNamespace(find=MagicMock(return_value=cursor)))

    async def test_reads_are_served_from_cache_until_the_window_passes(self):
        from unittest.mock import patch

        from app.routing import pre_route
        now = datetime.now(timezone.utc)
        db = self.db()
        with patch('app.routing.pre_route.time.monotonic', return_value=1000.0):
            await pre_route.current_hazards(db, now)
            await pre_route.current_hazards(db, now)
            db.intel_cache.find.assert_called_once_with({'type': 'hazard_belief'},
                                                        pre_route.BELIEF_PROJECTION)
        with patch('app.routing.pre_route.time.monotonic',
                   return_value=1000.0 + pre_route.BELIEF_CACHE_SECONDS + 1):
            await pre_route.current_hazards(db, now)
        self.assertEqual(db.intel_cache.find.call_count, 2)

    async def test_clear_belief_cache_forces_a_fresh_read(self):
        from app.routing import pre_route
        now = datetime.now(timezone.utc)
        db = self.db()
        await pre_route.current_hazards(db, now)
        await pre_route.current_hazards(db, now)
        db.intel_cache.find.assert_called_once()
        pre_route.clear_belief_cache()  # what a snapshot rebuild does before its own read
        await pre_route.current_hazards(db, now)
        self.assertEqual(db.intel_cache.find.call_count, 2)
