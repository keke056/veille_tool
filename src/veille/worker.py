"""Worker de collecte RSS, génération des résumés IA, traduction FR et mise en cache SQLite."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from veille.config import get_db_path, load_config
from veille.db import (
    cleanup_old_articles,
    get_cached_article,
    get_today_articles,
    init_db,
    save_article,
    save_briefing,
    update_article_translation,
)
from veille.ollama_client import (
    ensure_ollama_ready,
    generate_daily_briefing,
    is_refusal,
    summarize_articles_batch,
    translate_articles_parallel,
)
from veille.scraper import scrape_all_feeds

console = Console()


def ensure_articles_translated(
    db_path: Path,
    articles: list[dict[str, Any]],
    config: dict[str, Any],
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """
    Vérifie que tous les articles en cache disposent de leur traduction française
    (`title_fr`, `summary_short_fr`, `summary_detail_fr`).
    Traduit à la volée et sauvegarde dans SQLite ceux qui n'en ont pas encore.
    """
    missing = [
        art
        for art in articles
        if not art.get("title_fr")
        or not art.get("summary_short_fr")
        or not art.get("summary_detail_fr")
    ]
    if not missing:
        return articles

    if not quiet:
        with console.status(
            f"[bold cyan]Traduction française de {len(missing)} article(s) et mise en cache SQLite...[/bold cyan]",
            spinner="dots",
        ):
            translate_articles_parallel(missing, config=config)
            for art in missing:
                if "id" in art:
                    update_article_translation(
                        db_path=db_path,
                        article_id=int(art["id"]),
                        title_fr=art["title_fr"],
                        summary_short_fr=art["summary_short_fr"],
                        summary_detail_fr=art["summary_detail_fr"],
                    )
    else:
        translate_articles_parallel(missing, config=config)
        for art in missing:
            if "id" in art:
                update_article_translation(
                    db_path=db_path,
                    article_id=int(art["id"]),
                    title_fr=art["title_fr"],
                    summary_short_fr=art["summary_short_fr"],
                    summary_detail_fr=art["summary_detail_fr"],
                )

    return articles


def run_update_worker(quiet: bool = False) -> dict[str, Any]:
    """
    Exécute un cycle complet de veille :
    1. Vérifie Ollama et le modèle local.
    2. Récupère et déduplique les flux RSS des dernières 24h.
    3. Résume et traduit en français les nouveaux articles.
    4. Génère le Briefing Global du jour.
    5. Sauvegarde tout dans SQLite.
    """
    config = load_config()
    db_path = get_db_path(config)
    init_db(db_path)

    ollama_ok, model_name = ensure_ollama_ready(config, auto_pull=True, quiet=quiet)
    if not quiet:
        if ollama_ok:
            console.print(
                f"[bold green]✓[/bold green] Moteur IA local Ollama opérationnel "
                f"(modèle : [bold cyan]{model_name}[/bold cyan])"
            )
        else:
            console.print(
                "[bold yellow]⚠ Ollama indisponible : utilisation des extraits RSS structurés en repli.[/bold yellow]"
            )

    if not quiet:
        console.print("[bold cyan]↻[/bold cyan] Récupération parallèle des flux RSS Cybersécurité & Tech...")

    scraped_articles = scrape_all_feeds(config)
    today_str = datetime.now().strftime("%Y-%m-%d")
    new_articles: list[dict[str, Any]] = []
    cached_count = 0

    for art in scraped_articles:
        existing = get_cached_article(db_path, art["url"], art["title"])
        if (
            existing
            and existing.get("summary_short")
            and existing.get("summary_detail")
            and existing.get("title_fr")
            and existing.get("summary_short_fr")
            and existing.get("summary_detail_fr")
            and not is_refusal(existing["summary_short"])
            and not is_refusal(existing["summary_detail"])
        ):
            art["summary_short"] = existing["summary_short"]
            art["summary_detail"] = existing["summary_detail"]
            art["title_fr"] = existing["title_fr"]
            art["summary_short_fr"] = existing["summary_short_fr"]
            art["summary_detail_fr"] = existing["summary_detail_fr"]
            art["fetched_date"] = today_str
            save_article(db_path, art)
            cached_count += 1
        else:
            art["fetched_date"] = today_str
            new_articles.append(art)

    if new_articles:
        if not quiet:
            with console.status(
                f"[bold cyan]Synthèse & traduction FR de {len(new_articles)} articles...[/bold cyan]",
                spinner="dots",
            ):
                summarize_articles_batch(new_articles, config=config, ollama_ok=ollama_ok)
                for art in new_articles:
                    save_article(db_path, art)
        else:
            summarize_articles_batch(new_articles, config=config, ollama_ok=ollama_ok)
            for art in new_articles:
                save_article(db_path, art)

    new_count = len(new_articles)
    hours_window = int(config.get("scraping", {}).get("hours_window", 24))
    today_articles = get_today_articles(db_path, hours_window=hours_window)
    ensure_articles_translated(db_path, today_articles, config, quiet=quiet)

    if not quiet:
        with console.status(
            f"[bold cyan]Génération du Briefing Global du jour via Ollama ({model_name})...[/bold cyan]",
            spinner="dots",
        ):
            global_summary, cyber_hi, tech_hi = generate_daily_briefing(today_articles, config)
    else:
        global_summary, cyber_hi, tech_hi = generate_daily_briefing(today_articles, config)

    save_briefing(
        db_path=db_path,
        global_summary=global_summary,
        cyber_highlights=cyber_hi,
        tech_highlights=tech_hi,
        article_count=len(today_articles),
        model_used=model_name if ollama_ok else "rss-fallback",
        date_str=today_str,
    )

    retention_days = int(config.get("storage", {}).get("retention_days", 14))
    cleanup_old_articles(db_path, retention_days=retention_days)

    if not quiet:
        console.print(
            f"[bold green]✓ Veille mise à jour avec succès :[/bold green] "
            f"[bold]{len(today_articles)}[/bold] articles actifs "
            f"([green]{new_count} nouveaux/traduits[/green], [dim]{cached_count} en cache[/dim])."
        )

    return {
        "total_articles": len(today_articles),
        "new_articles": new_count,
        "cached_articles": cached_count,
        "model_used": model_name,
    }


if __name__ == "__main__":
    run_update_worker(quiet=True)
