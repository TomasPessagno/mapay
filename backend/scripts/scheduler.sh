#!/usr/bin/env bash
# Create (or update) the Cloud Scheduler jobs that call POST /internal/ingest/{job}.
# A human runs this once per project, and again after adding a job (Cloud Shell or any gcloud login).
#
#   PROJECT_ID=<project> REGION=us-east1 SERVICE=mapay-api \
#   SCHEDULER_SA=gemini-runner@<project>.iam.gserviceaccount.com backend/scripts/scheduler.sh
#
# SCHEDULER_SA must be the same account the backend checks (SCHEDULER_SERVICE_ACCOUNT; the deploy
# workflow defaults it to GEMINI_SERVICE_ACCOUNT, the account Cloud Run already runs as). The
# token's audience is the service URL, which the deploy also passes as INTERNAL_AUDIENCE.
# Cadences: AGENTS.md › Data pipelines. Times are America/New_York.
set -euo pipefail

: "${PROJECT_ID:?set PROJECT_ID}"
: "${REGION:=us-east1}"
: "${SERVICE:=mapay-api}"
: "${SCHEDULER_SA:?set SCHEDULER_SA (the scheduler service account email)}"

gcloud services enable cloudscheduler.googleapis.com --project "$PROJECT_ID"
URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" \
      --format='value(status.url)')
echo "Service URL (token audience): $URL"

# job name | cron | attempt deadline
JOBS=(
  "news|*/15 * * * *|300s"
  "weather|*/5 * * * *|120s"
  "here|*/5 * * * *|180s"
  "tides|0 * * * *|120s"
  "city_gis|0 6 * * *|300s"
  "sidewalks|0 3 * * *|300s"
  "potholes|0 4 * * 1|300s"
  "gfm|15 * * * *|300s"
  "s2|0 5 * * 1|300s"
  "briefings|*/10 * * * *|240s"
  # Add as they land: "traffic|..." (#23)
)

for entry in "${JOBS[@]}"; do
  IFS='|' read -r job cron deadline <<<"$entry"
  name="mapay-ingest-$job"
  args=(--project "$PROJECT_ID" --location "$REGION" --schedule "$cron" --time-zone "America/New_York"
        --uri "$URL/internal/ingest/$job" --http-method POST --attempt-deadline "$deadline"
        --oidc-service-account-email "$SCHEDULER_SA" --oidc-token-audience "$URL"
        --max-retry-attempts 1)
  if gcloud scheduler jobs describe "$name" --project "$PROJECT_ID" --location "$REGION" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "$name" "${args[@]}" --quiet
  else
    gcloud scheduler jobs create http "$name" "${args[@]}" --quiet
  fi
  echo "✓ $name  $cron"
done

echo
echo "Run one now to check it:  gcloud scheduler jobs run mapay-ingest-tides --project $PROJECT_ID --location $REGION"
