"""Tests unitaires de l'agent Veille (config, SQLite, extraction, traduction -fr et CLI)."""

from __future__ import annotations

from pathlib import Path

from veille.autostart import get_os_service_help, get_python_executable
from veille.cli import build_parser
from veille.config import get_config_path, load_config
from veille.db import (
    get_cached_article,
    get_today_articles,
    init_db,
    normalize_title,
    normalize_url,
    save_article,
    save_briefing,
    search_articles,
    update_article_translation,
)
from veille.ollama_client import build_extractive_summaries, is_already_french, is_refusal
from veille.scraper import clean_html


def test_config_loads() -> None:
    cfg = load_config()
    assert "ollama" in cfg
    assert "feeds" in cfg
    assert "Cyber" in cfg["feeds"]
    assert "Tech" in cfg["feeds"]
    assert get_config_path().exists()


def test_clean_html_and_normalization() -> None:
    assert clean_html("<p>Alerte <b>CERT-FR</b> &amp; CVE</p>") == "Alerte CERT-FR & CVE"
    assert normalize_url("https://example.com/post/?utm_source=rss") == normalize_url(
        "https://example.com/post"
    )
    assert normalize_title("Alerte: CVE-2026-1234 !") == "alerte cve 2026 1234"


def test_extractive_summaries_and_refusal_filter() -> None:
    assert is_refusal("Je suis désolé, mais je ne peux pas fournir d'informations.")
    assert not is_refusal("Une vulnérabilité critique CVE-2026-1111 affecte le noyau Linux.")
    assert is_already_french("CERT-FR", "Multiples vulnérabilités dans Microsoft Edge")
    assert not is_already_french("BleepingComputer", "Data breach impacts 40 credit unions")

    short_s, detail_s = build_extractive_summaries(
        {
            "title": "Critical RCE in OpenSSH CVE-2026-9999",
            "source": "CERT-FR",
            "category": "Cyber",
            "raw_content": "A critical remote code execution flaw CVE-2026-9999 was patched in OpenSSH.",
        }
    )
    assert "CVE-2026-9999" in short_s
    assert "CVE-2026-9999" in detail_s


def test_cli_fr_option_parsing() -> None:
    parser = build_parser()
    assert parser.parse_args(["-fr"]).french is True
    assert parser.parse_args(["-s", "-fr"]).french is True
    assert parser.parse_args(["-s", "-fr"]).sources is True
    args_d_fr = parser.parse_args(["-d", "-fr"])
    assert args_d_fr.french is True
    assert args_d_fr.detail == "__ALL__"
    args_topic_fr = parser.parse_args(["-d", "NGINX", "-fr"])
    assert args_topic_fr.french is True
    assert args_topic_fr.detail == "NGINX"
    assert parser.parse_args(["--install-service"]).install_service is True
    assert "--install-service" in get_os_service_help()
    assert Path(get_python_executable()).exists()


def test_sqlite_cache_and_fr_translation(tmp_path: Path) -> None:
    db_file = tmp_path / "test_veille.db"
    init_db(db_file)
    art = {
        "category": "Cyber",
        "source": "The Hacker News",
        "title": "10-Year-Old NGINX HTTP/2 Flaw Lets Attackers Execute Code",
        "url": "https://thehackernews.com/2026/11/nginx-flaw.html",
        "published_at": "2026-11-18 10:00",
        "fetched_date": "2026-11-18",
        "raw_content": "A flaw in NGINX HTTP/2 support allows remote code execution.",
        "summary_short": "A flaw in NGINX HTTP/2 support allows RCE [CVE-2026-123007].",
        "summary_detail": "A flaw in NGINX HTTP/2 support allows remote code execution.",
    }
    save_article(db_file, art)
    cached = get_cached_article(db_file, art["url"], art["title"])
    assert cached is not None

    update_article_translation(
        db_file,
        int(cached["id"]),
        "Une faille HTTP/2 de NGINX vieille de 10 ans permet d'exécuter du code",
        "Une faille dans la prise en charge HTTP/2 de NGINX permet une RCE [CVE-2026-123007].",
        "Une faille dans la prise en charge HTTP/2 de NGINX permet d'exécuter du code à distance.",
    )

    today = get_today_articles(db_file)
    assert len(today) == 1
    assert "vieille de 10 ans" in today[0]["title_fr"]

    # Recherche avec un mot-clé français présent uniquement dans la traduction
    results = search_articles(db_file, "vieille")
    assert len(results) == 1
    assert results[0]["title_fr"].startswith("Une faille HTTP/2")

    save_briefing(
        db_path=db_file,
        global_summary="Synthèse globale de test.",
        cyber_highlights="- NGINX HTTP/2",
        tech_highlights="- Tech news",
        article_count=1,
        model_used="llama3.2:1b",
    )
