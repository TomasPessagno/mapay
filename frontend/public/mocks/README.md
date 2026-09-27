# API contract mocks (draft)

Example responses for every endpoint the app uses. They are the **API contract**: the app builds against them (`VITE_USE_MOCKS=true`) while the backend implements the real endpoints to return the same shapes. The data is made up (Miami places, fake hazards), so the app should show a "Mock data" badge while using them.

| File | Endpoint |
| --- | --- |
| `layers.json` | `GET /layers?t=` |
| `route.json` | `POST /route` |
| `places.json` | `GET /places` |
| `preferences.json` | `GET /me/preferences` |
| `routines.json` | `GET /routines` |
| `routines-upcoming.json` | `GET /routines/upcoming` (the widget uses the same shape) |
| `customize.json` | `POST /customize` |
| `neighborhoods.json` | `GET /neighborhoods` |
| `report.json` | `POST /report` (a new report, or "Still there" / "Cleared" on a hazard) |

**Changing a shape:** update the mock here, `frontend/src/lib/types.ts` and `backend/app/db/models.py` in the same PR, and tell the other person.

**Widget in the iOS Simulator:** Vite serves these files, so the widget can fetch `http://localhost:5173/mocks/routines-upcoming.json` while the real endpoint doesn't exist yet (allow local networking in the widget's App Transport Security settings for development).

Times are Miami local (`-04:00`). Coordinates are `[lng, lat]` in GeoJSON and `lat,lng` in map URLs.
