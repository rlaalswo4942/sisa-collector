"""Fetch Google News RSS, ask the backend which items are new, write the ones
that need real-URL resolution to resolve_input.json."""
import calendar
import hashlib
import json
import os
import time
import urllib.request
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

RSS_URL = "https://news.google.com/rss/headlines/section/topic/WORLD?hl=ko&gl=KR&ceid=KR:ko"
API_BASE_URL = os.environ["API_BASE_URL"].rstrip("/")
API_KEY = os.environ["API_KEY"]


def _kst_day(epoch_s: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(epoch_s + 9 * 3600))


def _api_post(path: str, payload) -> dict:
    req = urllib.request.Request(
        f"{API_BASE_URL}{path}",
        data=json.dumps(payload).encode(),
        # Cloudflare's default bot protection on workers.dev domains blocks
        # the generic "Python-urllib/x.y" user agent outright (error 1010).
        headers={"Content-Type": "application/json", "X-API-Key": API_KEY, "User-Agent": "sisa-app-collector/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def main():
    req = urllib.request.Request(RSS_URL, headers={"User-Agent": "sisa-app-collector/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        root = ElementTree.fromstring(resp.read())

    items = []
    for item in root.iterfind("./channel/item"):
        link = item.findtext("link")
        title = item.findtext("title")
        pub_date = item.findtext("pubDate")
        source = item.findtext("source") or ""
        if not (link and title and pub_date):
            continue
        try:
            published_at = parsedate_to_datetime(pub_date).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            continue
        items.append(
            {
                "external_id": hashlib.sha256(link.encode()).hexdigest(),
                "title": title,
                "source": source,
                "google_link": link,
                "published_at": published_at,
            }
        )

    # The feed keeps listing yesterday's stories; the backend only keeps today
    # (KST) and drops the rest on ingest, so don't spend browser/Gemini time on them.
    total = len(items)
    today = _kst_day(time.time())
    items = [i for i in items if _kst_day(calendar.timegm(time.strptime(i["published_at"], "%Y-%m-%dT%H:%M:%SZ"))) == today]

    to_resolve = []
    if items:
        unknown = set(_api_post("/v1/news/unknown-ids", [i["external_id"] for i in items])["unknown"])
        to_resolve = [i for i in items if i["external_id"] in unknown]
    print(f"{total} items in feed, {len(items)} from today (KST), {len(to_resolve)} new")

    with open("resolve_input.json", "w", encoding="utf-8") as f:
        json.dump(to_resolve, f, ensure_ascii=False)
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"new={len(to_resolve)}\n")


if __name__ == "__main__":
    main()
