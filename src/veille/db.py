"""Gestion du cache local SQLite pour les articles et briefings."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def normalize_url(url: str) -> str:
    """Normalise une URL et retourne son empreinte SHA-256."""
    cleaned = url.strip()
    # Supprime les paramètres de tracking courants (utm_*)
    cleaned = re.sub(r"[?&]utm_[^&]+", "", cleaned)
    cleaned = cleaned.rstrip("/?&")
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def normalize_title(title: str) -> str:
    """Normalise un titre pour la déduplication inter-flux."""
    lowered = title.lower().strip()
    return re.sub(r"[^a-z0-9àâäéèêëîïôöùûüç]+", " ", lowered).strip()


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Ouvre une connexion SQLite configurée avec Row factory."""
    conn = sqlite3.connect(str(db_path), timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    """Initialise les tables SQLite et migre les colonnes de traduction si nécessaire."""
    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url_hash TEXT UNIQUE NOT NULL,
                title_norm TEXT NOT NULL,
                category TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                published_at TEXT NOT NULL,
                fetched_date TEXT NOT NULL,
                raw_content TEXT NOT NULL,
                summary_short TEXT NOT NULL,
                summary_detail TEXT NOT NULL,
                title_fr TEXT NOT NULL DEFAULT '',
                summary_short_fr TEXT NOT NULL DEFAULT '',
                summary_detail_fr TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_articles_fetched_date
                ON articles(fetched_date);
            CREATE INDEX IF NOT EXISTS idx_articles_published_at
                ON articles(published_at);
            CREATE INDEX IF NOT EXISTS idx_articles_title_norm
                ON articles(title_norm);

            CREATE TABLE IF NOT EXISTS briefings (
                date TEXT PRIMARY KEY,
                global_summary TEXT NOT NULL,
                cyber_highlights TEXT NOT NULL,
                tech_highlights TEXT NOT NULL,
                article_count INTEGER NOT NULL,
                model_used TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        # Migration automatique si la table existait avant l'ajout de -fr
        existing_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(articles)").fetchall()
        }
        for col_name in ("title_fr", "summary_short_fr", "summary_detail_fr"):
            if col_name not in existing_cols:
                conn.execute(
                    f"ALTER TABLE articles ADD COLUMN {col_name} TEXT NOT NULL DEFAULT ''"
                )


def get_cached_article(
    db_path: Path, url: str, title: str
) -> dict[str, Any] | None:
    """Vérifie si un article est déjà en cache (par URL ou titre normalisé)."""
    init_db(db_path)
    u_hash = normalize_url(url)
    t_norm = normalize_title(title)
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM articles
            WHERE url_hash = ? OR (title_norm = ? AND length(title_norm) > 15)
            LIMIT 1
            """,
            (u_hash, t_norm),
        ).fetchone()
        return dict(row) if row else None


def save_article(db_path: Path, article: dict[str, Any]) -> None:
    """Insère ou met à jour un article (et sa traduction française) dans SQLite."""
    init_db(db_path)
    u_hash = normalize_url(article["url"])
    t_norm = normalize_title(article["title"])
    now_iso = datetime.now().isoformat(timespec="seconds")
    today_str = datetime.now().strftime("%Y-%m-%d")

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO articles (
                url_hash, title_norm, category, source, title, url,
                published_at, fetched_date, raw_content,
                summary_short, summary_detail,
                title_fr, summary_short_fr, summary_detail_fr,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url_hash) DO UPDATE SET
                fetched_date = excluded.fetched_date,
                summary_short = excluded.summary_short,
                summary_detail = excluded.summary_detail,
                title_fr = CASE
                    WHEN excluded.title_fr != '' THEN excluded.title_fr
                    ELSE articles.title_fr
                END,
                summary_short_fr = CASE
                    WHEN excluded.summary_short_fr != '' THEN excluded.summary_short_fr
                    ELSE articles.summary_short_fr
                END,
                summary_detail_fr = CASE
                    WHEN excluded.summary_detail_fr != '' THEN excluded.summary_detail_fr
                    ELSE articles.summary_detail_fr
                END
            """,
            (
                u_hash,
                t_norm,
                article["category"],
                article["source"],
                article["title"],
                article["url"],
                article["published_at"],
                article.get("fetched_date", today_str),
                article.get("raw_content", ""),
                article.get("summary_short", ""),
                article.get("summary_detail", ""),
                article.get("title_fr", ""),
                article.get("summary_short_fr", ""),
                article.get("summary_detail_fr", ""),
                now_iso,
            ),
        )


def update_article_translation(
    db_path: Path,
    article_id: int,
    title_fr: str,
    summary_short_fr: str,
    summary_detail_fr: str,
) -> None:
    """Met à jour la traduction française d'un article existant en cache."""
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE articles
            SET title_fr = ?, summary_short_fr = ?, summary_detail_fr = ?
            WHERE id = ?
            """,
            (title_fr, summary_short_fr, summary_detail_fr, article_id),
        )


def get_today_articles(
    db_path: Path, hours_window: int = 24
) -> list[dict[str, Any]]:
    """
    Récupère les articles des dernières 24h (ou de la dernière session de veille).
    Numérote les articles de manière cohérente (Cyber d'abord, puis Tech).
    """
    init_db(db_path)
    cutoff = (datetime.now() - timedelta(hours=hours_window)).isoformat(timespec="seconds")
    today_str = datetime.now().strftime("%Y-%m-%d")

    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM articles
            WHERE published_at >= ? OR fetched_date = ?
            ORDER BY
                CASE WHEN category = 'Cyber' THEN 0 ELSE 1 END ASC,
                published_at DESC
            """,
            (cutoff, today_str),
        ).fetchall()

        if not rows:
            rows = conn.execute(
                """
                SELECT * FROM articles
                WHERE fetched_date = (SELECT MAX(fetched_date) FROM articles)
                ORDER BY
                    CASE WHEN category = 'Cyber' THEN 0 ELSE 1 END ASC,
                    published_at DESC
                """
            ).fetchall()

    articles = [dict(r) for r in rows]
    for idx, art in enumerate(articles, start=1):
        art["display_id"] = idx
    return articles


def search_articles(
    db_path: Path, query: str, hours_window: int = 48
) -> list[dict[str, Any]]:
    """
    Recherche les articles pertinents pour un mot-clé (en anglais ou français),
    un sujet ou un numéro (#id).
    """
    today_articles = get_today_articles(db_path, hours_window=hours_window)
    if not today_articles:
        return []

    cleaned_q = query.strip()
    if re.fullmatch(r"#?\d+", cleaned_q):
        target_id = int(cleaned_q.lstrip("#"))
        for art in today_articles:
            if art.get("display_id") == target_id:
                return [art]

    tokens = [
        t.lower()
        for t in re.split(r"\s+", cleaned_q)
        if len(t) >= 2
    ]
    if not tokens:
        tokens = [cleaned_q.lower()]

    scored: list[tuple[int, dict[str, Any]]] = []
    for art in today_articles:
        haystack_title = f"{art['title']} {art.get('title_fr', '')}".lower()
        haystack_source = f"{art['source']} {art['category']}".lower()
        haystack_body = (
            f"{art['summary_short']} {art['summary_detail']} "
            f"{art.get('summary_short_fr', '')} {art.get('summary_detail_fr', '')} "
            f"{art['raw_content']}"
        ).lower()

        score = 0
        full_q_lower = cleaned_q.lower()
        if full_q_lower in haystack_title:
            score += 10
        if full_q_lower in haystack_body:
            score += 6
        if full_q_lower in haystack_source:
            score += 5

        for tok in tokens:
            if tok in haystack_title:
                score += 4
            if tok in haystack_source:
                score += 3
            if tok in haystack_body:
                score += 2

        if score > 0:
            scored.append((score, art))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:6]]


def save_briefing(
    db_path: Path,
    global_summary: str,
    cyber_highlights: str,
    tech_highlights: str,
    article_count: int,
    model_used: str,
    date_str: str | None = None,
) -> None:
    """Enregistre le Briefing Global du jour dans SQLite."""
    init_db(db_path)
    target_date = date_str or datetime.now().strftime("%Y-%m-%d")
    now_iso = datetime.now().isoformat(timespec="seconds")

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO briefings (
                date, global_summary, cyber_highlights, tech_highlights,
                article_count, model_used, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                global_summary = excluded.global_summary,
                cyber_highlights = excluded.cyber_highlights,
                tech_highlights = excluded.tech_highlights,
                article_count = excluded.article_count,
                model_used = excluded.model_used,
                updated_at = excluded.updated_at
            """,
            (
                target_date,
                global_summary,
                cyber_highlights,
                tech_highlights,
                article_count,
                model_used,
                now_iso,
            ),
        )


def get_latest_briefing(db_path: Path) -> dict[str, Any] | None:
    """Récupère le dernier briefing global en cache."""
    init_db(db_path)
    today_str = datetime.now().strftime("%Y-%m-%d")
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM briefings WHERE date = ? LIMIT 1",
            (today_str,),
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT * FROM briefings ORDER BY date DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None


def cleanup_old_articles(db_path: Path, retention_days: int = 14) -> int:
    """Purge les articles plus anciens que retention_days."""
    init_db(db_path)
    cutoff = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM articles WHERE fetched_date < ?",
            (cutoff,),
        )
        conn.execute(
            "DELETE FROM briefings WHERE date < ?",
            (cutoff,),
        )
        return cur.rowcount
