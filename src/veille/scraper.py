"""Module de récupération et de nettoyage des flux RSS Cybersécurité & Tech."""

from __future__ import annotations

import calendar
import concurrent.futures
import html
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser

from veille.db import normalize_title, normalize_url


def clean_html(raw_html: str) -> str:
    """Supprime les balises HTML et normalise les espaces."""
    if not raw_html:
        return ""
    text = re.sub(r"<script[^>]*>.*?</script>", " ", raw_html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_entry_datetime(entry: Any) -> datetime:
    """Extrait la date de publication d'une entrée RSS en heure locale."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        struct_time = getattr(entry, attr, None) or entry.get(attr)
        if struct_time:
            try:
                ts = calendar.timegm(struct_time)
                return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().replace(tzinfo=None)
            except Exception:
                continue
    return datetime.now()


def fetch_single_feed(
    category: str,
    feed_info: dict[str, Any],
    hours_window: int,
    max_per_feed: int,
    timeout: int,
    user_agent: str,
) -> list[dict[str, Any]]:
    """Récupère et filtre les articles d'un flux RSS unique."""
    if not feed_info.get("enabled", True):
        return []

    name = feed_info.get("name", "Source inconnue")
    url = feed_info.get("url", "")
    if not url:
        return []

    try:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_bytes = resp.read()
    except Exception:
        return []

    parsed = feedparser.parse(raw_bytes)
    entries = getattr(parsed, "entries", [])
    if not entries:
        return []

    now = datetime.now()
    cutoff_now = now - timedelta(hours=hours_window)

    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for entry in entries[:15]:
        title = clean_html(getattr(entry, "title", "") or entry.get("title", ""))
        link = (getattr(entry, "link", "") or entry.get("link", "")).strip()
        if not title or not link:
            continue

        summary_raw = (
            getattr(entry, "summary", "")
            or entry.get("summary", "")
            or getattr(entry, "description", "")
            or entry.get("description", "")
        )
        content_list = getattr(entry, "content", None) or entry.get("content")
        if content_list and isinstance(content_list, list) and isinstance(content_list[0], dict):
            summary_raw = content_list[0].get("value", summary_raw) or summary_raw

        cleaned_content = clean_html(summary_raw)
        pub_dt = parse_entry_datetime(entry)

        candidates.append(
            (
                pub_dt,
                {
                    "category": category,
                    "source": name,
                    "title": title,
                    "url": link,
                    "published_at": pub_dt.strftime("%Y-%m-%d %H:%M"),
                    "fetched_date": now.strftime("%Y-%m-%d"),
                    "raw_content": cleaned_content[:1500] if cleaned_content else title,
                },
            )
        )

    if not candidates:
        return []

    # Tri du plus récent au plus ancien
    candidates.sort(key=lambda item: item[0], reverse=True)

    # Filtre sur les dernières 24h (par rapport à l'horloge système ou à l'article le plus récent du flux)
    newest_feed_dt = candidates[0][0]
    cutoff_feed = newest_feed_dt - timedelta(hours=hours_window)

    selected: list[dict[str, Any]] = []
    for pub_dt, art in candidates:
        if pub_dt >= cutoff_now or pub_dt >= cutoff_feed:
            selected.append(art)
        if len(selected) >= max_per_feed:
            break

    if not selected:
        selected = [item[1] for item in candidates[:max_per_feed]]

    return selected


def scrape_all_feeds(config: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Récupère en parallèle tous les flux RSS configurés, filtre sur 24h
    et déduplique par URL et par titre normalisé.
    """
    scraping_cfg = config.get("scraping", {})
    hours_window = int(scraping_cfg.get("hours_window", 24))
    max_per_feed = int(scraping_cfg.get("max_articles_per_feed", 3))
    max_total = int(scraping_cfg.get("max_total_articles", 24))
    timeout = int(scraping_cfg.get("request_timeout_seconds", 12))
    user_agent = scraping_cfg.get(
        "user_agent",
        "Mozilla/5.0 (X11; Linux x86_64) Veille-CyberTech-Agent/1.0",
    )

    feeds_by_category: dict[str, list[dict[str, Any]]] = config.get("feeds", {})
    tasks: list[tuple[str, dict[str, Any]]] = []
    for category, feed_list in feeds_by_category.items():
        if isinstance(feed_list, list):
            for feed_info in feed_list:
                if isinstance(feed_info, dict):
                    tasks.append((category, feed_info))

    raw_articles: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(tasks) or 1)) as executor:
        future_map = {
            executor.submit(
                fetch_single_feed,
                cat,
                f_info,
                hours_window,
                max_per_feed,
                timeout,
                user_agent,
            ): (cat, f_info.get("name", ""))
            for cat, f_info in tasks
        }
        for future in concurrent.futures.as_completed(future_map):
            try:
                raw_articles.extend(future.result())
            except Exception:
                continue

    # Déduplication stricte par URL et par titre normalisé
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    deduped: list[dict[str, Any]] = []

    # Tri par catégorie (Cyber puis Tech) et par date décroissante
    raw_articles.sort(
        key=lambda a: (0 if a["category"] == "Cyber" else 1, a["published_at"]),
    )
    # Tri décroissant par date à l'intérieur de chaque catégorie
    cyber_raw = sorted(
        [a for a in raw_articles if a["category"] == "Cyber"],
        key=lambda a: a["published_at"],
        reverse=True,
    )
    tech_raw = sorted(
        [a for a in raw_articles if a["category"] == "Tech"],
        key=lambda a: a["published_at"],
        reverse=True,
    )

    for art in cyber_raw + tech_raw:
        u_hash = normalize_url(art["url"])
        t_norm = normalize_title(art["title"])
        if u_hash in seen_urls or (t_norm and t_norm in seen_titles):
            continue
        seen_urls.add(u_hash)
        if t_norm:
            seen_titles.add(t_norm)
        deduped.append(art)
        if len(deduped) >= max_total:
            break

    return deduped
