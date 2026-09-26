#!/usr/bin/env bash
# Check .env and frontend/.env without printing any values: each setting shows as set, EMPTY or MISSING.
#
#   scripts/check-env.sh            (run from the mapay folder)
#
# "needed" = the app or a P0 task breaks without it; "later" = only needed by a later or optional task.
set -u
cd "$(git rev-parse --show-toplevel)" || exit 1

status() {  # status <file> <NAME>
  if [ ! -f "$1" ]; then echo "no file"; return; fi
  line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?$2[[:space:]]*=" "$1" | tail -n 1)"
  if [ -z "$line" ]; then echo "MISSING"; return; fi
  value="${line#*=}"; value="${value%%#*}"; value="$(printf '%s' "$value" | tr -d "[:space:]\"'")"
  if [ -z "$value" ]; then echo "EMPTY"; else echo "set"; fi
}

missing=0
check() {  # check <file> <NAME> <needed|later> <what it's for>
  s="$(status "$1" "$2")"
  printf '  %-30s %-8s %-7s %s\n' "$2" "$s" "$3" "$4"
  if [ "$3" = needed ] && [ "$s" != set ]; then missing=$((missing + 1)); fi
}

echo ".env (backend, repo root)"
[ -f .env ] || echo "  (no .env here: copy Jean's into the mapay folder)"
check .env MONGODB_URI                needed "MongoDB Atlas connection string (the backend won't start without it)"
check .env MONGODB_DB_NAME            needed "database name (the backend won't start without it)"
check .env GOOGLE_GENAI_USE_VERTEXAI  needed "true = Gemini through Vertex AI (the active path)"
check .env GOOGLE_CLOUD_PROJECT       needed "project whose Vertex AI credit Gemini uses"
check .env GOOGLE_MAPS_API_KEY        needed "Maps server key: Routes, Places, Geocoding, Static Maps"
check .env HERE_API_KEY               needed "HERE traffic incidents + flow (#6)"
check .env NWS_USER_AGENT             needed "weather.gov requires a contact User-Agent"
check .env GOOGLE_CLOUD_LOCATION      later  "defaults to global"
check .env GEMINI_API_KEY             later  "AI Studio path, parked (out of credit)"
check .env CORS_ORIGINS               later  "defaults cover localhost + the iPhone app; add the Vercel URL later"
check .env LAYA_URL                   later  "Laya on Jean's laptop (#46)"
check .env LAYA_API_KEY               later  "Laya token (#46)"

echo
echo "frontend/.env (app)"
[ -f frontend/.env ] || echo "  (no frontend/.env yet: create it in mapay/frontend)"
check frontend/.env VITE_GOOGLE_MAPS_API_KEY needed "Maps browser key (Maps JavaScript + Places)"
check frontend/.env VITE_GOOGLE_MAPS_MAP_ID  needed "Map ID for the styled map"
check frontend/.env VITE_API_BASE_URL        needed "backend URL, http://localhost:8000 for now"
check frontend/.env VITE_USE_MOCKS           needed "true until the real endpoints exist"

echo
if command -v gcloud >/dev/null 2>&1; then
  if gcloud auth application-default print-access-token >/dev/null 2>&1; then
    echo "Vertex AI login: ok (gcloud application-default credentials found)"
  else
    echo "Vertex AI login: MISSING, run: gcloud auth application-default login"
  fi
else
  echo "Vertex AI login: gcloud isn't installed; local Gemini calls need it (brew install --cask google-cloud-sdk)"
fi

if git ls-files --error-unmatch .env frontend/.env >/dev/null 2>&1; then
  echo "WARNING: a .env file is tracked by git. Remove it from git (git rm --cached) and rotate the keys."
fi

echo
if [ "$missing" -eq 0 ]; then echo "All needed settings are set."; else echo "$missing needed setting(s) missing or empty."; fi
