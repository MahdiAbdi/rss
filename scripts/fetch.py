#!/usr/bin/env python3
"""
Fetch content from Telegram channels (t.me/s) and websites (RSS/HTML),
merge into a single feed JSON. No Telegram API or secrets required.
Output: docs/data/feed.json (served by GitHub Pages).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_PATH = REPO_ROOT / "sources.yaml"
OUTPUT_DIR = REPO_ROOT / "docs" / "data"
OUTPUT_PATH = OUTPUT_DIR / "feed.json"

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FeedFetcher/1.0; +https://github.com)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 25


def load_sources() -> dict:
    """Load sources.yaml from repo root."""
    if not SOURCES_PATH.exists():
        return {"telegram": [], "websites": []}
    with open(SOURCES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {
        "telegram": data.get("telegram") or [],
        "websites": data.get("websites") or [],
    }


def fetch_telegram_channel(username: str) -> dict:
    """Fetch public channel posts from t.me/s/<username>. No API key required."""
    url = f"https://t.me/s/{username.strip()}"
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"id": f"telegram/{username}", "title": username, "url": url, "items": [], "error": str(e)}

    soup = BeautifulSoup(resp.text, "html.parser")

    # Channel title: og:title or .tgme_channel_info_header
    title = username
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    else:
        header = soup.select_one(".tgme_channel_info_header")
        if header:
            title = header.get_text(strip=True) or title

    items = []
    for msg in soup.select(".tgme_widget_message"):
        if "tgme_widget_message_error" in msg.get("class", []):
            continue
        data_post = msg.get("data-post")
        if not data_post or "/" not in data_post:
            continue
        # data-post is like "channel/123"
        post_id = data_post.split("/")[-1]
        post_url = f"https://t.me/{data_post}"

        text_el = msg.select_one(".tgme_widget_message_text")
        text = (text_el.get_text(separator=" ", strip=True) if text_el else "") or "(media)"

        time_el = msg.select_one("time")
        date_str = ""
        if time_el and time_el.get("datetime"):
            date_str = time_el["datetime"]
        elif time_el:
            date_str = time_el.get_text(strip=True)

        items.append({
            "title": (text[:120] + "…") if len(text) > 120 else text or "Post",
            "url": post_url,
            "date": date_str,
            "snippet": text[:300] if text else "",
        })

    return {
        "id": f"telegram/{username}",
        "title": title,
        "url": url,
        "items": items[:50],
    }


def fetch_rss(feed_url: str) -> dict:
    """Fetch RSS feed and return normalized source dict."""
    try:
        parsed = feedparser.parse(
            feed_url,
            request_headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as e:
        return {
            "id": _website_id(feed_url),
            "title": feed_url,
            "url": feed_url,
            "items": [],
            "error": str(e),
        }

    title = (parsed.feed.get("title") or "").strip() or _website_id(feed_url)
    items = []
    for entry in parsed.entries[:50]:
        link = entry.get("link") or ""
        if not link and entry.get("links"):
            link = entry["links"][0].get("href", "")
        published = ""
        if entry.get("published_parsed"):
            try:
                from time import mktime
                from datetime import datetime as dt
                published = dt.fromtimestamp(mktime(entry.published_parsed), tz=timezone.utc).isoformat()
            except Exception:
                published = entry.get("published", "")
        elif entry.get("published"):
            published = entry.get("published", "")
        summary = (entry.get("summary") or entry.get("description") or "")
        if hasattr(summary, "strip"):
            summary = summary.strip()
        else:
            summary = str(summary)[:300]
        items.append({
            "title": (entry.get("title") or "Untitled")[:200],
            "url": link,
            "date": published,
            "snippet": summary[:300] if summary else "",
        })

    return {
        "id": _website_id(feed_url),
        "title": title,
        "url": feed_url,
        "items": items,
    }


def _website_id(url: str) -> str:
    """Stable id from URL (host + path slug)."""
    p = urlparse(url)
    netloc = (p.netloc or "").replace("www.", "")
    path = (p.path or "").strip("/").replace("/", "_")[:40]
    return f"website/{netloc}_{path}" if path else f"website/{netloc}"


def fetch_html_page(site: dict) -> dict:
    """Fetch HTML page and extract links (or items by selector)."""
    url = site.get("url", "").strip()
    if not url:
        return {"id": "website/unknown", "title": "", "url": "", "items": [], "error": "Missing url"}
    selector = site.get("selector")
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"id": _website_id(url), "title": url, "url": url, "items": [], "error": str(e)}

    soup = BeautifulSoup(resp.text, "html.parser")
    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    if not title and soup.title:
        title = soup.title.get_text(strip=True) or ""
    if not title:
        title = _website_id(url)

    items = []
    if selector:
        for el in soup.select(selector)[:50]:
            a = el.find("a", href=True)
            if a:
                href = a.get("href", "")
                href = urljoin(url, href) if href else ""
                text = a.get_text(separator=" ", strip=True)[:200] if a else ""
                items.append({"title": text or href, "url": href, "date": "", "snippet": text[:300]})
    else:
        seen = set()
        for a in soup.select("a[href]"):
            href = urljoin(url, a.get("href", ""))
            if not href or href.startswith("#") or href in seen:
                continue
            if any(href.startswith(p) for p in ("javascript:", "mailto:", "tel:")):
                continue
            seen.add(href)
            text = a.get_text(separator=" ", strip=True)[:200] or href
            items.append({"title": text, "url": href, "date": "", "snippet": text[:300]})
            if len(items) >= 50:
                break

    return {
        "id": _website_id(url),
        "title": title,
        "url": url,
        "items": items,
    }


def build_feed(sources: dict) -> dict:
    """Build unified feed from all sources."""
    updated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    out_sources = []

    for username in sources.get("telegram") or []:
        if not isinstance(username, str) or not username.strip():
            continue
        result = fetch_telegram_channel(username)
        out_sources.append(result)

    for site in sources.get("websites") or []:
        if not isinstance(site, dict):
            continue
        url = (site.get("url") or "").strip()
        if not url:
            continue
        kind = (site.get("type") or "rss").lower()
        if kind == "rss":
            out_sources.append(fetch_rss(url))
        else:
            out_sources.append(fetch_html_page(site))

    return {"updated": updated, "sources": out_sources}


def main() -> None:
    sources = load_sources()
    feed = build_feed(sources)
    payload = json.dumps(feed, ensure_ascii=False, indent=2)
    new_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    existing_hash = None
    if OUTPUT_PATH.exists():
        existing_hash = hashlib.sha256(OUTPUT_PATH.read_bytes()).hexdigest()
    if existing_hash == new_hash:
        return
    OUTPUT_PATH.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
