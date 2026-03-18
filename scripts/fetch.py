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
from readability import Document

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_PATH = REPO_ROOT / "sources.yaml"
OUTPUT_DIR = REPO_ROOT / "docs" / "data"
OUTPUT_PATH = OUTPUT_DIR / "feed.json"
STATE_PATH = OUTPUT_DIR / "fetch_state.json"

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FeedFetcher/1.0; +https://github.com)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 25
MAX_FULL_ARTICLES_PER_SOURCE = 20
ARTICLE_FETCH_TIMEOUT = 15
TELEGRAM_POST_TIMEOUT = 8
MAX_FULL_POST_FETCH_PER_CHANNEL = 25


def fetch_telegram_post_content(post_url: str) -> str:
    """Fetch single Telegram post page and return full message text (no truncation)."""
    if not post_url or not post_url.startswith("https://t.me/"):
        return ""
    try:
        resp = requests.get(
            post_url,
            headers=REQUEST_HEADERS,
            timeout=TELEGRAM_POST_TIMEOUT,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        text_el = soup.select_one(".tgme_widget_message_text")
        if not text_el:
            return ""
        return text_el.get_text(separator="\n", strip=True)
    except Exception:
        return ""


def extract_article_content(url: str) -> str:
    """Fetch URL and extract main article text using readability. Returns empty string on failure."""
    if not url or not url.startswith("http"):
        return ""
    try:
        resp = requests.get(
            url,
            headers=REQUEST_HEADERS,
            timeout=ARTICLE_FETCH_TIMEOUT,
        )
        resp.raise_for_status()
        doc = Document(resp.content)
        summary_html = doc.summary()
        if not summary_html:
            return ""
        soup = BeautifulSoup(summary_html, "html.parser")
        return soup.get_text(separator="\n", strip=True)
    except Exception:
        return ""


def load_sources() -> dict:
    """Load sources.yaml from repo root. Normalize telegram to list of {name, full_fetch?, max_items?}."""
    if not SOURCES_PATH.exists():
        return {"telegram": [], "websites": []}
    with open(SOURCES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    telegram_raw = data.get("telegram") or []
    telegram = []
    for t in telegram_raw:
        if isinstance(t, str) and t.strip():
            telegram.append({"name": t.strip(), "full_fetch": False, "max_items": 50})
        elif isinstance(t, dict) and (t.get("name") or "").strip():
            name = (t.get("name") or "").strip()
            full_fetch = bool(t.get("full_fetch"))
            max_items = int(t.get("max_items") or 100) if full_fetch else 50
            telegram.append({"name": name, "full_fetch": full_fetch, "max_items": min(max(1, max_items), 100)})
    return {
        "telegram": telegram,
        "websites": data.get("websites") or [],
    }


def _parse_telegram_page(soup: BeautifulSoup, base_url: str, channel_title: str) -> list[tuple[str, dict]]:
    """Parse telegram channel page; return list of (post_id, item_dict)."""
    items = []
    for msg in soup.select(".tgme_widget_message"):
        if "tgme_widget_message_error" in msg.get("class", []):
            continue
        data_post = msg.get("data-post")
        if not data_post or "/" not in data_post:
            continue
        post_id = data_post.split("/")[-1]
        post_url = f"https://t.me/{data_post}"
        text_el = msg.select_one(".tgme_widget_message_text")
        text = (text_el.get_text(separator=" ", strip=True) if text_el else "") or "(media)"
        time_el = msg.select_one("time")
        date_str = time_el.get("datetime", "") if time_el else ""
        if not date_str and time_el:
            date_str = time_el.get_text(strip=True) or ""
        item = {
            "title": (text[:120] + "…") if len(text) > 120 else text or "Post",
            "url": post_url,
            "date": date_str,
            "snippet": text[:300] if text else "",
            "content": text or "",
            "_post_id": post_id,
        }
        items.append((post_id, item))
    return items


def fetch_telegram_channel(
    channel_spec: dict,
    previous_items: list[dict] | None = None,
    state: dict | None = None,
) -> tuple[dict, dict]:
    """Fetch public channel posts from t.me/s/<username>. Returns (source_dict, state_update for this source)."""
    username = (channel_spec.get("name") or "").strip()
    full_fetch = bool(channel_spec.get("full_fetch"))
    max_items = int(channel_spec.get("max_items") or 50)
    source_id = f"telegram/{username}"
    url = f"https://t.me/s/{username}"
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        return ({"id": source_id, "title": username, "url": url, "items": [], "error": str(e)}, {})

    soup = BeautifulSoup(resp.text, "html.parser")
    title = username
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    else:
        header = soup.select_one(".tgme_channel_info_header")
        if header:
            title = header.get_text(strip=True) or title

    parsed = _parse_telegram_page(soup, url, title)
    state_update = {}

    if full_fetch:
        previous_items = previous_items or []
        last_id_str = (state or {}).get(source_id, {}).get("last_message_id") or "0"
        try:
            last_id = int(last_id_str)
        except ValueError:
            last_id = 0
        new_items = []
        seen_urls = {it["url"] for it in previous_items}
        for post_id_str, item in parsed:
            try:
                pid = int(post_id_str)
            except ValueError:
                pid = 0
            if pid > last_id and item["url"] not in seen_urls:
                new_items.append(item)
                seen_urls.add(item["url"])
        max_id = last_id
        for post_id_str, _ in parsed:
            try:
                max_id = max(max_id, int(post_id_str))
            except ValueError:
                pass
        for it in new_items:
            it["is_new"] = True
        for it in previous_items:
            it["is_new"] = False
        merged = new_items + [it for it in previous_items if it.get("url") not in {i["url"] for i in new_items}]
        for it in merged:
            it.pop("_post_id", None)
        merged.sort(key=lambda x: (x.get("date") or ""), reverse=True)
        merged = merged[:max_items]
        state_update = {source_id: {"last_message_id": str(max_id)}}
        items = merged
    else:
        items = [it for _, it in parsed]
        for it in items:
            it.pop("_post_id", None)
            it["is_new"] = True
        items = items[:max_items]

    for i, it in enumerate(items):
        if i >= MAX_FULL_POST_FETCH_PER_CHANNEL:
            break
        post_url = it.get("url") or ""
        if post_url.startswith("https://t.me/"):
            full_text = fetch_telegram_post_content(post_url)
            if full_text:
                it["content"] = full_text

    return (
        {"id": source_id, "title": title, "url": url, "items": items},
        state_update,
    )


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
    for i, entry in enumerate(parsed.entries[:50]):
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
        snippet = summary[:300] if summary else ""
        content = snippet
        if i < MAX_FULL_ARTICLES_PER_SOURCE and link:
            extracted = extract_article_content(link)
            if extracted:
                content = extracted
        items.append({
            "title": (entry.get("title") or "Untitled")[:200],
            "url": link,
            "date": published,
            "snippet": snippet,
            "content": content,
            "is_new": i < 15,
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
        for i, el in enumerate(soup.select(selector)[:50]):
            a = el.find("a", href=True)
            if a:
                href = a.get("href", "")
                href = urljoin(url, href) if href else ""
                text = a.get_text(separator=" ", strip=True)[:200] if a else ""
                snippet = text[:300]
                content = snippet
                if i < MAX_FULL_ARTICLES_PER_SOURCE and href:
                    extracted = extract_article_content(href)
                    if extracted:
                        content = extracted
                items.append({"title": text or href, "url": href, "date": "", "snippet": snippet, "content": content, "is_new": i < 15})
    else:
        seen = set()
        count = 0
        for a in soup.select("a[href]"):
            if count >= 50:
                break
            href = urljoin(url, a.get("href", ""))
            if not href or href.startswith("#") or href in seen:
                continue
            if any(href.startswith(p) for p in ("javascript:", "mailto:", "tel:")):
                continue
            seen.add(href)
            text = a.get_text(separator=" ", strip=True)[:200] or href
            snippet = text[:300]
            content = snippet
            if count < MAX_FULL_ARTICLES_PER_SOURCE and href:
                extracted = extract_article_content(href)
                if extracted:
                    content = extracted
            items.append({"title": text, "url": href, "date": "", "snippet": snippet, "content": content, "is_new": count < 15})
            count += 1

    return {
        "id": _website_id(url),
        "title": title,
        "url": url,
        "items": items,
    }


def _parse_iso_date(s: str) -> datetime | None:
    """Parse ISO-like date string to datetime; return None on failure."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(s.replace("Z", "+00:00"), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_previous_feed() -> dict | None:
    """Load existing feed.json if present."""
    if not OUTPUT_PATH.exists():
        return None
    try:
        return json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_state() -> dict:
    """Load fetch_state.json if present."""
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    """Write fetch_state.json."""
    if not state:
        return
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def build_feed(
    sources: dict,
    previous_feed: dict | None = None,
    state: dict | None = None,
) -> tuple[dict, dict]:
    """Build unified feed from all sources. Returns (feed_dict, new_state)."""
    updated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    out_sources = []
    new_state = dict(state) if state else {}

    prev_by_id = {}
    if previous_feed:
        for src in previous_feed.get("sources") or []:
            sid = src.get("id")
            if sid:
                prev_by_id[sid] = src.get("items") or []

    for channel_spec in sources.get("telegram") or []:
        name = (channel_spec.get("name") or "").strip()
        if not name:
            continue
        source_id = f"telegram/{name}"
        previous_items = prev_by_id.get(source_id)
        result, state_update = fetch_telegram_channel(channel_spec, previous_items, new_state)
        out_sources.append(result)
        new_state.update(state_update)

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

    date_min: datetime | None = None
    date_max: datetime | None = None
    for src in out_sources:
        for item in src.get("items") or []:
            d = _parse_iso_date(item.get("date") or "")
            if d:
                if date_min is None or d < date_min:
                    date_min = d
                if date_max is None or d > date_max:
                    date_max = d
    date_range = {}
    if date_min is not None:
        date_range["min"] = date_min.isoformat().replace("+00:00", "Z")
    if date_max is not None:
        date_range["max"] = date_max.isoformat().replace("+00:00", "Z")

    new_count = sum(1 for src in out_sources for it in (src.get("items") or []) if it.get("is_new"))

    return (
        {
            "updated": updated,
            "date_range": date_range,
            "new_count": new_count,
            "sources": out_sources,
        },
        new_state,
    )


def main() -> None:
    sources = load_sources()
    previous_feed = load_previous_feed()
    state = load_state()
    feed, new_state = build_feed(sources, previous_feed, state)
    payload = json.dumps(feed, ensure_ascii=False, indent=2)
    new_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    existing_hash = None
    if OUTPUT_PATH.exists():
        existing_hash = hashlib.sha256(OUTPUT_PATH.read_bytes()).hexdigest()
    if existing_hash == new_hash:
        return
    OUTPUT_PATH.write_text(payload, encoding="utf-8")
    save_state(new_state)


if __name__ == "__main__":
    main()
