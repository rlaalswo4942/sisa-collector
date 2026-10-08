"""Read resolve_output.json (items with a real, resolved source_url) and add
an ai_summary field to each by fetching the article page and asking Gemini
to summarize it. Runs from GitHub Actions because Gemini's API rejects
requests that egress from whatever region Cloudflare Workers happens to
route an outbound fetch() through (confirmed: consistent 400 "not available
in your current location", even though the same key works fine from here)."""
import json
import os
import re
import time
import urllib.error
import urllib.request

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
_RETRY_STATUSES = {429, 503}
_MAX_RETRIES = 3
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_MAX_PAGE_CHARS = 6000


def _extract_text(html: str) -> str:
    no_scripts = _SCRIPT_STYLE_RE.sub(" ", html)
    no_tags = _TAG_RE.sub(" ", no_scripts)
    return _WHITESPACE_RE.sub(" ", no_tags).strip()[:_MAX_PAGE_CHARS]


def _fetch(url, api_key=None, data=None, timeout=15):
    headers = {"User-Agent": "sisa-app-collector/1.0"}
    if api_key:
        headers["x-goog-api-key"] = api_key
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _fetch_gemini_with_retry(url, api_key, data):
    # Free-tier Gemini is flaky under a batch of back-to-back calls — seen
    # both 429/503 (rate limit) and plain socket timeouts on real runs.
    # Retry both rather than giving up on the first hiccup.
    for attempt in range(_MAX_RETRIES):
        try:
            return _fetch(url, api_key=api_key, data=data, timeout=25)
        except urllib.error.HTTPError as e:
            if e.code not in _RETRY_STATUSES or attempt == _MAX_RETRIES - 1:
                raise
            time.sleep(5 * (attempt + 1))
        except (TimeoutError, urllib.error.URLError):
            if attempt == _MAX_RETRIES - 1:
                raise
            time.sleep(5 * (attempt + 1))


def summarize(api_key: str, title: str, source_url: str) -> str | None:
    try:
        page_text = _extract_text(_fetch(source_url).decode("utf-8", errors="replace"))
    except Exception as e:
        print(f"  page fetch failed for {source_url}: {e}")
        return None
    if not page_text:
        return None
    payload = json.dumps(
        {
            "model": "gemini-3.5-flash-lite",
            "input": (
                "다음은 뉴스 기사 페이지에서 추출한 원시 텍스트다(광고, 메뉴 등 "
                "관련 없는 내용이 섞여 있을 수 있음). 기사의 핵심 내용만 한국어로 "
                "2~3문장으로 간결하게 요약해라. 다른 설명 없이 요약문만 출력해라.\n\n"
                f"제목: {title}\n\n본문 추출:\n{page_text}"
            ),
        }
    ).encode()
    try:
        data = json.loads(_fetch_gemini_with_retry(GEMINI_URL, api_key, payload))
    except Exception as e:
        print(f"  gemini call failed for {source_url}: {e}")
        return None
    for step in data.get("steps", []):
        if step.get("type") != "model_output":
            continue
        texts = [c.get("text", "") for c in step.get("content", []) if c.get("type") == "text"]
        summary = "".join(texts).strip()
        if summary:
            return summary
    return None


def main():
    api_key = os.environ["GEMINI_API_KEY"]
    with open("resolve_output.json", encoding="utf-8") as f:
        items = json.load(f)

    for i, item in enumerate(items):
        if i > 0:
            time.sleep(2)  # stay under the free-tier per-minute rate limit
        summary = summarize(api_key, item["title"], item["source_url"])
        item["ai_summary"] = summary
        print(f"{'ok' if summary else 'no summary'}: {item['title'][:50]}")

    with open("resolve_output.json", "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
