# MAPAY

Miami-native hazard-aware navigation. MAPAY knows which Miami streets will flood, close, or slow down before you get there, and routes you around it.

## Setup

```bash
# create .env (root) and frontend/.env and fill in the keys -- they are gitignored, ask the team for values

# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.init_db       # create indexes in Atlas (idempotent)
uvicorn app.main:app --reload    # http://localhost:8000/docs

# frontend
cd frontend && npm install && npm run dev   # http://localhost:5173
```

See `AGENTS.md` for scope, data sources, and roadmap; `docs/` for architecture.
