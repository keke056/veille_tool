"""Gestion de la configuration de l'agent Veille."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "ollama": {
        "base_url": "http://localhost:11434",
        "api_url": "http://localhost:11434/api/generate",
        "model": "llama3.2:1b",
        "fallback_models": ["qwen2.5:1.5b", "qwen2.5:0.5b"],
        "timeout_seconds": 90,
        "temperature": 0.2,
        "num_ctx": 2048,
        "num_predict_article": 140,
        "num_predict_briefing": 450,
        "num_predict_detail": 600,
    },
    "scraping": {
        "hours_window": 24,
        "max_articles_per_feed": 3,
        "max_total_articles": 24,
        "request_timeout_seconds": 12,
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64) Veille-CyberTech-Agent/1.0",
    },
    "storage": {
        "db_path": "data/veille.db",
        "retention_days": 14,
    },
    "feeds": {
        "Cyber": [
            {"name": "CERT-FR", "url": "https://www.cert.ssi.gouv.fr/feed/", "enabled": True},
            {"name": "BleepingComputer", "url": "https://www.bleepingcomputer.com/feed/", "enabled": True},
            {"name": "The Hacker News", "url": "https://feeds.feedburner.com/TheHackersNews", "enabled": True},
            {"name": "Krebs on Security", "url": "https://krebsonsecurity.com/feed/", "enabled": True},
            {"name": "ZATAZ", "url": "https://www.zataz.com/feed/", "enabled": True},
        ],
        "Tech": [
            {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index", "enabled": True},
            {"name": "Hacker News (RSS)", "url": "https://hnrss.org/frontpage", "enabled": True},
            {"name": "Korben", "url": "https://korben.info/feed", "enabled": True},
            {"name": "Next.ink", "url": "https://next.ink/feed/", "enabled": True},
        ],
    },
}


def get_config_path() -> Path:
    """Retourne le chemin vers le fichier config.json actif."""
    env_path = os.environ.get("VEILLE_CONFIG")
    if env_path:
        return Path(env_path).expanduser().resolve()
    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH
    user_cfg = Path.home() / ".config" / "veille" / "config.json"
    if user_cfg.exists():
        return user_cfg
    # Crée le fichier de configuration par défaut dans le projet s'il est absent
    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_CONFIG_PATH.write_text(
        json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return DEFAULT_CONFIG_PATH


def load_config() -> dict[str, Any]:
    """Charge et fusionne la configuration depuis config.json."""
    cfg_path = get_config_path()
    merged: dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        user_data = json.loads(cfg_path.read_text(encoding="utf-8"))
        for section, values in user_data.items():
            if isinstance(values, dict) and isinstance(merged.get(section), dict):
                merged[section].update(values)
            else:
                merged[section] = values
    except Exception:
        pass
    return merged


def get_db_path(config: dict[str, Any] | None = None) -> Path:
    """Retourne le chemin absolu vers la base SQLite locale."""
    cfg = config or load_config()
    raw_path = cfg.get("storage", {}).get("db_path", "data/veille.db")
    db_path = Path(raw_path).expanduser()
    if not db_path.is_absolute():
        base_dir = get_config_path().parent
        db_path = (base_dir / db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path
