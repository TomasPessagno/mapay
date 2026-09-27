"""Laya on Jean's laptop (#46): the news pipeline's first pass (backend/app/agents/news_triage.py).

    python services/laya/serve.py

- Refuses to start without LAYA_API_KEY: the tunnel makes this server public.
- Binds to 127.0.0.1:${LAYA_PORT:-8001}, so only the tunnel (not the Wi-Fi network) reaches it.
- Serves the stock `multilingual` checkpoint, or LAYA_CHECKPOINT (a Hugging Face repo id or a
  local folder, e.g. the A25 fine-tune) attached under the name `multilingual`, which is what the
  backend asks for.
"""
import os
import sys


def main() -> None:
    if not os.environ.get("LAYA_API_KEY"):
        sys.exit("LAYA_API_KEY is not set. Generate one (python -c 'import secrets; print(secrets.token_urlsafe(32))'),\n"
                 "export it here, and share it privately for the backend's LAYA_API_KEY secret.")
    os.environ.setdefault("LAYA_MODELS", "multilingual")
    os.environ.setdefault("LAYA_THREADS", str(min(8, os.cpu_count() or 4)))

    import uvicorn
    from laya.serve import build_router, create_app

    checkpoint = os.environ.get("LAYA_CHECKPOINT")
    if checkpoint:
        import laya
        from laya.router import Router
        os.environ["LAYA_PRELOAD"] = "0"  # don't also download the stock checkpoint
        router = Router(device=os.environ.get("LAYA_DEVICE") or None)
        router.attach("multilingual", laya.load(checkpoint))
        print(f"Serving {checkpoint} as 'multilingual'")
    else:
        router = build_router()
    port = int(os.environ.get("LAYA_PORT", "8001"))
    uvicorn.run(create_app(router), host="127.0.0.1", port=port, log_level=os.environ.get("LAYA_LOG_LEVEL", "info"))


if __name__ == "__main__":
    main()
