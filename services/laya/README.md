# Laya on Jean's laptop (#46)

[Laya](https://github.com/NandhaKishorM/laya) (Apache-2.0) answers typed questions about a text with a probability.
The news pipeline (`backend/app/agents/news_triage.py`) asks it one yes/no question per story ("is this a street
problem in Miami-Dade?") before Gemini reads it. It runs here for free; when the laptop is off, the backend runs
Gemini-only.

> **Keep `LAYA_URL` unset on Cloud Run for now.** The zero-shot `multilingual` checkpoint keeps only 2 of 10 real
> road stories at the pipeline's 0.2 cut (numbers on #46 / PR #54). Point the backend at it once the A25 fine-tune
> (#47) passes that check: run this launcher with `LAYA_CHECKPOINT=<fine-tuned repo or folder>`.

## One-time set-up

```bash
cd services/laya
python3 -m venv .venv && . .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU build, ~1 GB smaller
pip install -r requirements.txt
python -c "import secrets; print(secrets.token_urlsafe(32))"          # your LAYA_API_KEY: keep it private
```

The first start downloads the `multilingual` checkpoint (322M params, ~1.3 GB) into `~/.cache/huggingface`.

## Every time (demo day)

1. **Server**, bound to 127.0.0.1 so only the tunnel reaches it:
   ```bash
   cd services/laya && . .venv/bin/activate
   export LAYA_API_KEY=<the token>
   # export LAYA_CHECKPOINT=<A25 fine-tune repo id or folder>   # once #47 is done
   python serve.py            # listens on 127.0.0.1:8001 (LAYA_PORT to change)
   ```
2. **Tunnel** with a fixed URL (the backend's `LAYA_URL` secret must not change):
   - ngrok's free static domain: `ngrok http --url=<your-name>.ngrok-free.app 8001`, or
   - Tailscale Funnel: `tailscale funnel 8001`.
   - For a quick test only (the URL changes on every restart, no account):
     `cloudflared tunnel --url http://localhost:8001`.
3. **Keep the laptop awake:** `caffeinate -dims` on a Mac; on Windows, Settings → Power → Sleep: Never while plugged in.
4. **Check it:**
   ```bash
   curl -s <tunnel URL>/health          # "loaded": ["multilingual"]
   curl -s <tunnel URL>/v1/systemone -H "Authorization: Bearer $LAYA_API_KEY" -H 'content-type: application/json' \
     -d '{"model":"multilingual","state":{"title":"SW 8th Street closed at SW 17th Avenue"},
          "questions":{"street_problem":{"type":"noul","instructions":"Is this about a street problem in Miami-Dade?"}}}'
   ```
   A wrong or missing token must return 401.

## Backend settings

`LAYA_URL` (the tunnel URL) and `LAYA_API_KEY` (the token) are GitHub secrets that the deploy passes to Cloud Run
(`.github/workflows/ci-cd.yml`). Empty values are fine: the pipeline then skips Laya.
