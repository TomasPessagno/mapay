import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app.ingestion import closures

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
_RECENT = int((NOW - timedelta(days=5)).timestamp() * 1000)
_STALE = int((NOW - timedelta(days=40)).timestamp() * 1000)

_LINE_A = [[-80.2, 25.8], [-80.201, 25.801]]
_LINE_B = [[-80.21, 25.81], [-80.211, 25.811]]


def roadway_feature(object_id, status, phase, **overrides):
    props = {
        "OBJECTID": object_id,
        "STREET": "NW 69TH ST",
        "PROJECT": "District 5 Traffic Calming",
        "PRJ_DESC": "",
        "STATUS": status,
        "PHASE": phase,
        "ADDRESS_": "NW 6 Ave between NW 44 St and NW 45 St",
        "CONSTR_EN": "",
        "last_edited_date": _RECENT,
    }
    props.update(overrides)
    return {"type": "Feature", "id": object_id,
            "geometry": {"type": "LineString", "coordinates": _LINE_A}, "properties": props}


def permit_feature(object_id, permit_number, permit_type, status, **overrides):
    props = {
        closures._P + "OBJECTID": object_id,
        closures._P + "St_Label": "NW 16TH AV",
        closures._P + "FROM_ST": "NW 5TH ST",
        closures._P + "TO_ST": "NW 6TH ST",
        closures._P + "Status": status,
        closures._P + "LaneNumTot": 2,
        closures._P + "LaneNumClose": 1,
        closures._P + "ClosureEndDate": _RECENT,
        closures._P + "last_edited_date": _RECENT,
        closures._P + "APPID": "PW21002168UP",
        closures._A + "PermitNumber": permit_number,
        closures._A + "PermitType": permit_type,
        closures._A + "PermitStatus": "Expired",
        closures._A + "PermitApplicationStatus": "Permit Issued",
        closures._A + "ProjectAddress": "",
        closures._A + "CreatedDate": _RECENT,
    }
    props.update(overrides)
    return {"type": "Feature", "id": object_id,
            "geometry": {"type": "LineString", "coordinates": _LINE_A}, "properties": props}


class StatusTests(unittest.TestCase):
    def test_normalise_status_covers_raw_arcgis_values(self):
        cases = {
            "Active": "active",
            "07- Construction": "active",
            "Issued": "active",
            "On-Hold": "pending",
            "05- Bidding": "pending",
            "N/A": "pending",
            "Plan Approved": "approved",
            "Complete": "completed",
            "11- Closed": "completed",
            "10- Administrative Close-Out": "completed",
            "Inactive": "cleared",
            "Discarded": "cleared",
            "something unknown": None,
            None: None,
        }
        for raw, expected in cases.items():
            self.assertEqual(closures.normalise_status(raw), expected, raw)


class MappingTests(unittest.TestCase):
    def test_roadway_project_maps_to_construction_with_stable_id(self):
        hazards = closures.roadway_hazards([roadway_feature(173, "Active", "03- Design")], NOW)
        self.assertEqual(len(hazards), 1)
        hazard = hazards[0]
        self.assertEqual(hazard["id"], "city:roadway:173")
        self.assertEqual(hazard["kind"], "construction")
        self.assertEqual(hazard["status"], "active")
        self.assertEqual(hazard["severity"], closures._SEVERITY["active"])
        self.assertEqual(hazard["title"], "District 5 Traffic Calming")
        self.assertEqual(hazard["geometry"]["type"], "LineString")

    def test_permit_segments_group_into_one_multilinestring(self):
        features = [
            permit_feature(246187, "PW21002168UP001", "Utility (UP)", "Inactive",
                           **{closures._P + "St_Label": "NW 16TH AV"}),
            permit_feature(92227, "PW21002168UP001", "Utility (UP)", "Inactive",
                           **{closures._P + "St_Label": "NW 7TH ST"}),
        ]
        features[0]["geometry"] = {"type": "LineString", "coordinates": _LINE_A}
        features[1]["geometry"] = {"type": "LineString", "coordinates": _LINE_B}
        hazards = closures.permit_hazards(features, NOW)
        self.assertEqual(len(hazards), 1)
        hazard = hazards[0]
        self.assertEqual(hazard["id"], "city:permit:PW21002168UP001")
        self.assertEqual(hazard["kind"], "construction")
        self.assertEqual(hazard["status"], "cleared")
        self.assertEqual(hazard["geometry"]["type"], "MultiLineString")
        self.assertEqual(len(hazard["geometry"]["coordinates"]), 2)
        self.assertEqual(hazard["place"], "NW 5TH ST – NW 6TH ST")

    def test_full_lane_closure_normalises_to_closed(self):
        feature = permit_feature(1, "PW24000001RW001", "Right-of-Way Closure (RW)", "Active",
                                 **{closures._P + "LaneNumTot": 1,
                                    closures._P + "LaneNumClose": 1})
        hazards = closures.permit_hazards([feature], NOW)
        self.assertEqual(hazards[0]["kind"], "closure")
        self.assertEqual(hazards[0]["status"], "closed")
        self.assertEqual(hazards[0]["severity"], closures._SEVERITY["closed"])
        self.assertIn("Right-of-Way Closure (RW)", hazards[0]["title"])

    def test_active_closure_uses_active_prior(self):
        feature = permit_feature(2, "PW24000002RW001", "Right-of-Way Closure (RW)", "Active")
        hazards = closures.permit_hazards([feature], NOW)
        self.assertEqual(hazards[0]["kind"], "closure")
        self.assertEqual(hazards[0]["status"], "active")

    def test_completed_items_older_than_30_days_are_skipped(self):
        stale = roadway_feature(900, "Complete", "11- Closed", CONSTR_EN=_STALE)
        recent = roadway_feature(901, "Complete", "11- Closed", CONSTR_EN=_RECENT)
        hazards = closures.roadway_hazards([stale, recent], NOW)
        self.assertEqual([h["id"] for h in hazards], ["city:roadway:901"])

    def test_features_without_geometry_or_id_are_skipped(self):
        no_geometry = roadway_feature(1, "Active", "07- Construction")
        no_geometry["geometry"] = None
        no_id = roadway_feature(None, "Active", "07- Construction")
        self.assertEqual(closures.roadway_hazards([no_geometry, no_id], NOW), [])


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _FakeClient:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    async def get(self, url, params=None):
        self.calls.append(params)
        return _FakeResponse({"features": self.pages[len(self.calls) - 1]})


class FetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_features_are_paged_by_object_id(self):
        client = _FakeClient([[{"id": 1}], [{"id": 2}]])
        with patch.object(closures, "PAGE_SIZE", 2):
            features = await closures._features_by_ids(client, "http://layer/0", [10, 11, 12])
        self.assertEqual(client.calls[0]["objectIds"], "10,11")
        self.assertEqual(client.calls[1]["objectIds"], "12")
        self.assertEqual(client.calls[0]["f"], "geojson")
        self.assertEqual(features, [{"id": 1}, {"id": 2}])

    async def test_object_ids_query_is_bbox_filtered(self):
        class _IdsClient(_FakeClient):
            async def get(self, url, params=None):
                self.calls.append(params)
                return _FakeResponse({"objectIds": [1, 2]})

        ids_client = _IdsClient([])
        ids = await closures._object_ids(ids_client, "http://layer/0")
        self.assertEqual(ids, [1, 2])
        self.assertEqual(ids_client.calls[0]["returnIdsOnly"], "true")
        self.assertEqual(ids_client.calls[0]["geometry"], "-80.45,25.55,-80.1,25.98")


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_registers_every_mapped_hazard(self):
        raw = {
            "roadway": [roadway_feature(173, "Active", "07- Construction")],
            "permit": [permit_feature(246187, "PW21002168UP001", "Utility (UP)", "Active")],
        }
        with patch.object(closures, "fetch_all", AsyncMock(return_value=raw)), \
                patch.object(closures, "register_hazards", AsyncMock()) as register:
            count = await closures.run(object(), NOW)
        self.assertEqual(count, 2)
        register.assert_awaited_once()  # one bulk call, not one per hazard
        hazards = register.await_args.args[1]
        self.assertEqual({h["id"]: h["kind"] for h in hazards},
                         {"city:roadway:173": "construction", "city:permit:PW21002168UP001": "construction"})
        first = hazards[0]["properties"]
        self.assertEqual((first["status"], first["severity"]), ("active", 4))
        self.assertTrue(first["title"])


if __name__ == "__main__":
    unittest.main()
