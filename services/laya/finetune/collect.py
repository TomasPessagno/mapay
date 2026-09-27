"""Collect ~1,000 Miami news items for the Laya fine-tune (#47).

    python services/laya/finetune/collect.py            # writes $LAYA_DATA_DIR/items.jsonl

Sources: Google News RSS search (last 90 days) with road-problem queries plus general Miami news
for negatives, the five RSS feeds the news pipeline reads (backend/app/ingestion/news.py), and the
GDELT DOC API when it answers (it rate-limits hard and often times out, so it's best-effort).
Stories are deduped across outlets by URL and by normalised title. The data is news text and the repo is
public, so it goes to LAYA_DATA_DIR (default ~/mapay-laya-data), never into git.
"""
import html
import json
import random
import re
import sys
import time
from pathlib import Path

import feedparser
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_DIR, title_key  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from app.ingestion.news import RSS_FEEDS, USER_AGENT  # noqa: E402  (same feeds as production)

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GOOGLE_NEWS_URL = "https://news.google.com/rss/search"
PAUSE = 6.0  # GDELT asks for at most one request every 5 s
# Road-problem queries (likely positives) and general Miami news (likely negatives). The group is a
# hint for balancing only; the labels come from the teacher.
QUERIES = {
    "road": ["miami flooding street", "miami beach flooding", "king tide miami", "miami crash", "miami-dade crash",
             "hialeah crash", "i-95 miami crash", "palmetto expressway", "dolphin expressway",
             "miami road closure", "miami lane closures", "miami road construction", "miami police standoff",
             "miami traffic delays", "miami-dade traffic", "brickell traffic"],
    "other": ["miami heat", "miami dolphins", "miami restaurant", "miami real estate", "miami art", "miami schools",
              "miami-dade county commission", "miami business", "miami music festival", "miami weather",
              "miami hurricanes football", "miami health"],
}
MAX_RECORDS = 150


def clean(text) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))).strip()


def gdelt(client: httpx.Client, query: str) -> list[dict] | None:
    """Articles, or None when GDELT is unavailable (rate limit, timeout)."""
    params = {"query": f"{query} sourcelang:english", "mode": "artlist", "format": "json",
              "maxrecords": MAX_RECORDS, "timespan": "3months", "sort": "hybridrel"}
    try:
        response = client.get(GDELT_URL, params=params, timeout=20)
        if response.status_code != 200 or not response.text.strip().startswith("{"):
            return None
        return response.json().get("articles", [])
    except (httpx.HTTPError, ValueError):
        return None


def google_news(client: httpx.Client, query: str) -> list[dict]:
    """(title, outlet, url) for up to 100 recent headlines; titles end in " - <outlet>"."""
    params = {"q": f"{query} when:90d", "hl": "en-US", "gl": "US", "ceid": "US:en"}
    response = client.get(GOOGLE_NEWS_URL, params=params, timeout=30)
    response.raise_for_status()
    results = []
    for entry in feedparser.parse(response.content).entries:
        title, _, outlet = (entry.get("title") or "").rpartition(" - ")
        results.append({"title": title or entry.get("title"), "outlet": outlet, "url": entry.get("link")})
    return results


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    items, urls, titles = [], set(), set()

    def add(source, group, title, summary, url):
        title, summary = clean(title), clean(summary)
        key = title_key(title)
        if not title or not url or url in urls or key in titles or len(title) < 20:
            return
        urls.add(url)
        titles.add(key)
        items.append({"id": f"n{len(items):05d}", "source": source, "group": group, "title": title,
                      "summary": summary[:600], "url": url})

    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        for source, url in RSS_FEEDS.items():
            try:
                feed = feedparser.parse(client.get(url, timeout=30).content)
                for entry in feed.entries:
                    add(source, "rss", entry.get("title"), entry.get("summary") or entry.get("description"),
                        entry.get("link"))
                print(f"rss {source}: {len(feed.entries)} entries")
            except httpx.HTTPError as exc:
                print(f"rss {source} failed: {exc}")
        for group, queries in QUERIES.items():
            for query in queries:
                before = len(items)
                try:
                    for article in google_news(client, query):
                        add(f"gnews:{article['outlet']}", group, article["title"], "", article["url"])
                except httpx.HTTPError as exc:
                    print(f"google news {query!r} failed: {exc}")
                print(f"google news [{group}] {query!r}: +{len(items) - before}")
                time.sleep(1)
        gdelt_ok = True
        for group, queries in QUERIES.items():
            for query in queries if gdelt_ok else []:
                articles = gdelt(client, query)
                if articles is None:
                    print("gdelt unavailable (rate limit / timeout): skipped")
                    gdelt_ok = False
                    break
                before = len(items)
                for article in articles:
                    add(f"gdelt:{article.get('domain', '')}", group, article.get("title"), "", article.get("url"))
                print(f"gdelt [{group}] {query!r}: +{len(items) - before}")
                time.sleep(PAUSE)
    out = DATA_DIR / "items.jsonl"
    out.write_text("".join(json.dumps(item) + "\n" for item in items))
    print(f"{len(items)} unique items → {out}")
    chosen = select(items)
    (DATA_DIR / "to_label.jsonl").write_text("".join(json.dumps(item) + "\n" for item in chosen))
    print(f"{len(chosen)} selected for labelling → {DATA_DIR / 'to_label.jsonl'}")


def select(items: list[dict], total: int = 1000, road: int = 600, seed: int = 47) -> list[dict]:
    """A balanced set to label: every RSS item (the production mix), `road` from the road queries
    (not all are road problems: the teacher decides), the rest general Miami news."""
    rng = random.Random(seed)
    by_group = {g: [i for i in items if i["group"] == g] for g in ("rss", "road", "other")}
    chosen = list(by_group["rss"])
    chosen += rng.sample(by_group["road"], min(road, len(by_group["road"])))
    chosen += rng.sample(by_group["other"], min(max(0, total - len(chosen)), len(by_group["other"])))
    return sorted(chosen, key=lambda i: i["id"])


if __name__ == "__main__":
    main()
