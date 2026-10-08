"""Read resolve_output.json (items with real source_url resolved) and POST
them to the backend's bulk quiet-ingest endpoint."""
import json
import os
import urllib.request

API_BASE_URL = os.environ["API_BASE_URL"].rstrip("/")
API_KEY = os.environ["API_KEY"]


def main():
    with open("resolve_output.json", encoding="utf-8") as f:
        items = json.load(f)

    if not items:
        print("nothing to ingest")
        return

    payload = [
        {
            "external_id": item["external_id"],
            "title": item["title"],
            "country_code": "UNCLASSIFIED",
            "published_at": item["published_at"],
            "summary": item["title"],
            "detail_text": f"{item['title']}\n\n출처: {item['source']}" if item["source"] else item["title"],
            "source_url": item["source_url"],
            "ai_summary": item.get("ai_summary"),
        }
        for item in items
    ]

    req = urllib.request.Request(
        f"{API_BASE_URL}/v1/ingest",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": API_KEY, "User-Agent": "sisa-app-collector/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(resp.read().decode())


if __name__ == "__main__":
    main()
