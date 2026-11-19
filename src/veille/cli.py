"""Interface en ligne de commande (CLI) avec Rich pour l'agent Veille."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from veille import __version__
from veille.autostart import get_os_service_help, setup_autostart
from veille.config import get_config_path, get_db_path, load_config
from veille.db import get_latest_briefing, get_today_articles, search_articles
from veille.ollama_client import ensure_ollama_ready, generate_topic_analysis
from veille.worker import ensure_articles_translated, run_update_worker

# Garantit l'encodage UTF-8 sur les terminaux Windows (PowerShell / CMD)
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

console = Console()


def ensure_cache_populated(
    config: dict[str, Any],
    db_path: Path,
    lang_fr: bool = False,
) -> list[dict[str, Any]]:
    """Récupère les articles du jour en cache (et leurs traductions FR si -fr est actif)."""
    hours_window = int(config.get("scraping", {}).get("hours_window", 24))
    articles = get_today_articles(db_path, hours_window=hours_window)
    if not articles:
        console.print(
            "[yellow]Cache local vide. Initialisation de la première collecte de veille...[/yellow]"
        )
        run_update_worker(quiet=False)
        articles = get_today_articles(db_path, hours_window=hours_window)
    if lang_fr and articles:
        ensure_articles_translated(db_path, articles, config, quiet=False)
    return articles


def _get_article_texts(art: dict[str, Any], lang_fr: bool) -> tuple[str, str, str, bool]:
    """
    Retourne (title, summary_short, summary_detail, is_translated) selon l'option -fr.
    """
    orig_title = art["title"]
    if not lang_fr:
        return orig_title, art["summary_short"], art["summary_detail"], False

    t_fr = (art.get("title_fr") or orig_title).strip()
    s_fr = (art.get("summary_short_fr") or art["summary_short"]).strip()
    d_fr = (art.get("summary_detail_fr") or art["summary_detail"]).strip()
    is_tr = t_fr.lower() != orig_title.lower()
    return t_fr, s_fr, d_fr, is_tr


def render_synthetic_briefing(
    config: dict[str, Any],
    db_path: Path,
    lang_fr: bool = False,
) -> None:
    """Commande `veille` (et `veille -fr`) : Affiche le résumé synthétique du jour depuis le cache."""
    articles = ensure_cache_populated(config, db_path, lang_fr=lang_fr)
    briefing = get_latest_briefing(db_path)

    cyber_arts = [a for a in articles if a["category"] == "Cyber"]
    tech_arts = [a for a in articles if a["category"] == "Tech"]

    date_str = briefing["date"] if briefing else "Aujourd'hui"
    updated_at = briefing["updated_at"].replace("T", " ") if briefing else "N/A"
    model_used = briefing["model_used"] if briefing else config.get("ollama", {}).get("model", "llama3.2:1b")
    lang_badge = "  │  [bold bright_cyan]🇫🇷 TRADUCTION FRANÇAISE INTÉGRALE (-fr)[/bold bright_cyan]" if lang_fr else ""

    header_text = (
        f"[bold white]VEILLE CYBERSÉCURITÉ & TECH[/bold white] — [cyan]{date_str}[/cyan]{lang_badge}\n"
        f"[dim]Articles en cache : {len(articles)} ({len(cyber_arts)} Cyber, {len(tech_arts)} Tech) "
        f"| Modèle IA local : {model_used} | MàJ : {updated_at}[/dim]"
    )
    console.print(Panel(header_text, border_style="bright_blue", box=box.DOUBLE_EDGE))

    if briefing and briefing.get("global_summary"):
        console.print(
            Panel(
                f"[italic white]{briefing['global_summary']}[/italic white]",
                title="[bold yellow]Briefing Exécutif du Jour[/bold yellow]",
                border_style="yellow",
                padding=(1, 2),
            )
        )

    # Catégorie CYBER
    console.print()
    console.print(Rule("[bold red]🛡  CYBERSÉCURITÉ (Alertes, CVE & Menaces)[/bold red]", style="red"))
    if cyber_arts:
        for art in cyber_arts:
            idx = art["display_id"]
            title_disp, short_disp, _, is_tr = _get_article_texts(art, lang_fr)
            console.print(
                f" [bold red][{idx:02d}][/bold red] [bold white]{title_disp}[/bold white] "
                f"[dim]({art['source']} • {art['published_at']})[/dim]"
            )
            if is_tr:
                console.print(f"      [dim italic]VO : {art['title']}[/dim italic]")
            console.print(f"      [cyan]↳[/cyan] {short_disp}")
    else:
        console.print("  [dim]Aucune actualité Cybersécurité dans la fenêtre actuelle.[/dim]")

    # Catégorie TECH
    console.print()
    console.print(Rule("[bold green]⚡ TECH & SYSTÈMES (Actualités & Innovations)[/bold green]", style="green"))
    if tech_arts:
        for art in tech_arts:
            idx = art["display_id"]
            title_disp, short_disp, _, is_tr = _get_article_texts(art, lang_fr)
            console.print(
                f" [bold green][{idx:02d}][/bold green] [bold white]{title_disp}[/bold white] "
                f"[dim]({art['source']} • {art['published_at']})[/dim]"
            )
            if is_tr:
                console.print(f"      [dim italic]VO : {art['title']}[/dim italic]")
            console.print(f"      [green]↳[/green] {short_disp}")
    else:
        console.print("  [dim]Aucune actualité Tech dans la fenêtre actuelle.[/dim]")

    console.print()
    console.print(
        Panel(
            "[bold cyan]veille -fr[/bold cyan] : Traduction FR  │  "
            "[bold cyan]veille -s[/bold cyan] : Sources & URLs  │  "
            "[bold cyan]veille -d[/bold cyan] : Détails  │  "
            "[bold cyan]veille -d \"sujet\"[/bold cyan] : Analyse IA  │  "
            "[bold cyan]veille -u[/bold cyan] : Rafraîchir  │  "
            "[bold cyan]veille man[/bold cyan] : Manuel",
            border_style="dim",
            box=box.ROUNDED,
        )
    )


def render_sources(
    config: dict[str, Any],
    db_path: Path,
    lang_fr: bool = False,
) -> None:
    """Commande `veille -s` (et `veille -s -fr`) : Affiche la liste des articles avec liens cliquables."""
    articles = ensure_cache_populated(config, db_path, lang_fr=lang_fr)
    title_suffix = " — [bold bright_cyan]Traduction Française (-fr)[/bold bright_cyan]" if lang_fr else ""

    table = Table(
        title=f"[bold bright_blue]Sources & Articles du Jour (Liens URL cliquables)[/bold bright_blue]{title_suffix}",
        box=box.ROUNDED,
        show_lines=True,
        expand=True,
    )
    table.add_column("#", justify="right", style="bold yellow", width=4)
    table.add_column("Cat.", style="bold", width=7)
    table.add_column("Source", style="cyan", width=18)
    table.add_column("Date", style="dim", width=16)
    table.add_column("Titre & Lien URL", ratio=1, overflow="fold", no_wrap=False)

    for art in articles:
        cat_badge = (
            "[bold red]Cyber[/bold red]"
            if art["category"] == "Cyber"
            else "[bold green]Tech[/bold green]"
        )
        url = art["url"]
        title_disp, _, _, is_tr = _get_article_texts(art, lang_fr)
        vo_line = f"\n[dim italic]VO : {art['title']}[/dim italic]" if is_tr else ""
        title_and_link = (
            f"[bold white]{title_disp}[/bold white]{vo_line}\n"
            f"[link={url}][underline bright_cyan]{url}[/underline bright_cyan][/link]"
        )
        table.add_row(
            f"{art['display_id']:02d}",
            cat_badge,
            art["source"],
            art["published_at"],
            title_and_link,
        )

    console.print(table)


def render_all_details(
    config: dict[str, Any],
    db_path: Path,
    lang_fr: bool = False,
) -> None:
    """Commande `veille -d` (et `veille -d -fr`) : Affiche le résumé détaillé de toutes les actualités."""
    articles = ensure_cache_populated(config, db_path, lang_fr=lang_fr)
    briefing = get_latest_briefing(db_path)
    lang_tag = " — [bold bright_cyan]🇫🇷 TRADUCTION FRANÇAISE (-fr)[/bold bright_cyan]" if lang_fr else ""

    console.print(
        Panel(
            f"[bold white]RAPPORT DÉTAILLÉ DES ACTUALITÉS DU JOUR[/bold white] "
            f"([cyan]{len(articles)} articles analysés[/cyan]){lang_tag}",
            border_style="bright_blue",
            box=box.DOUBLE_EDGE,
        )
    )

    if briefing and briefing.get("global_summary"):
        console.print(
            Panel(
                briefing["global_summary"],
                title="[bold yellow]Synthèse Globale[/bold yellow]",
                border_style="yellow",
            )
        )

    for category, color, icon in [
        ("Cyber", "red", "🛡  CYBERSÉCURITÉ — ANALYSES DÉTAILLÉES"),
        ("Tech", "green", "⚡ TECH & INNOVATION — ANALYSES DÉTAILLÉES"),
    ]:
        cat_articles = [a for a in articles if a["category"] == category]
        console.print()
        console.print(Rule(f"[bold {color}]{icon}[/bold {color}]", style=color))
        for art in cat_articles:
            url = art["url"]
            title_disp, _, detail_disp, is_tr = _get_article_texts(art, lang_fr)
            vo_block = f"[dim italic]Titre original (VO) : {art['title']}[/dim italic]\n\n" if is_tr else ""
            body = (
                f"{vo_block}[bold white]Résumé technique :[/bold white]\n{detail_disp}\n\n"
                f"[dim]Source :[/dim] [cyan]{art['source']}[/cyan]  │  "
                f"[dim]Publié :[/dim] {art['published_at']}  │  "
                f"[dim]Lien :[/dim] [link={url}][underline bright_cyan]{url}[/underline bright_cyan][/link]"
            )
            console.print(
                Panel(
                    body,
                    title=(
                        f"[bold {color}][{art['display_id']:02d}][/bold {color}] "
                        f"[bold white]{title_disp}[/bold white]"
                    ),
                    title_align="left",
                    border_style=color,
                    padding=(0, 2),
                )
            )


def render_topic_detail(
    query: str,
    config: dict[str, Any],
    db_path: Path,
    lang_fr: bool = False,
) -> None:
    """
    Commande `veille -d "mot-clé ou sujet"` (et `veille -d "sujet" -fr`) :
    Recherche dans les articles du jour et interroge l'IA locale pour fournir
    une analyse approfondie, les impacts techniques (CVE, systèmes touchés) et détails.
    """
    all_articles = ensure_cache_populated(config, db_path, lang_fr=lang_fr)
    matched = search_articles(db_path, query, hours_window=48)
    if lang_fr and matched:
        ensure_articles_translated(db_path, matched, config, quiet=True)

    console.print(
        Panel(
            f"[bold white]ANALYSE APPROFONDIE & RECHERCHE IA[/bold white] — "
            f"Sujet : [bold yellow]« {query} »[/bold yellow]",
            border_style="bright_magenta",
            box=box.DOUBLE_EDGE,
        )
    )

    if matched:
        console.print(
            f"[bold green]✓ {len(matched)} article(s) correspondant(s) trouvé(s) dans le cache local :[/bold green]"
        )
        for art in matched:
            url = art["url"]
            title_disp, _, detail_disp, is_tr = _get_article_texts(art, lang_fr)
            vo_line = f"\n[dim italic]VO : {art['title']}[/dim italic]" if is_tr else ""
            console.print(
                Panel(
                    f"[bold]Synthèse en cache :[/bold] {detail_disp}{vo_line}\n"
                    f"[dim]Source : {art['source']} ({art['category']}) • {art['published_at']}[/dim]\n"
                    f"[link={url}][underline bright_cyan]{url}[/underline bright_cyan][/link]",
                    title=f"[bold yellow][{art['display_id']:02d}][/bold yellow] [bold white]{title_disp}[/bold white]",
                    title_align="left",
                    border_style="cyan",
                )
            )
    else:
        console.print(
            f"[yellow]ℹ Aucun article du jour ne contient littéralement « {query} ». "
            "Interrogation du modèle IA local avec le contexte global du jour...[/yellow]"
        )

    ollama_ok, model_name = ensure_ollama_ready(config, auto_pull=True, quiet=False)
    if not ollama_ok:
        console.print(
            "[bold red]Impossible de générer l'analyse approfondie car Ollama n'est pas disponible.[/bold red]"
        )
        return

    with console.status(
        f"[bold magenta]Génération de l'analyse technique approfondie via Ollama ({model_name})...[/bold magenta]",
        spinner="dots",
    ):
        analysis_md = generate_topic_analysis(
            query=query,
            matched_articles=matched,
            all_today_articles=all_articles,
            config=config,
        )

    console.print(
        Panel(
            Markdown(analysis_md),
            title=f"[bold magenta]Analyse Technique IA ({model_name}) — « {query} »[/bold magenta]",
            border_style="magenta",
            padding=(1, 2),
        )
    )


def render_manual() -> None:
    """Commande `veille man` : Affiche le manuel complet de l'outil."""
    cfg_path = get_config_path()
    config = load_config()
    db_path = get_db_path(config)
    model_name = config.get("ollama", {}).get("model", "llama3.2:1b")

    feeds = config.get("feeds", {})
    cyber_sources = ", ".join(f["name"] for f in feeds.get("Cyber", []) if f.get("enabled", True))
    tech_sources = ", ".join(f["name"] for f in feeds.get("Tech", []) if f.get("enabled", True))

    man_text = f"""# VEILLE(1) — Manuel de l'Agent IA Local de Veille Cybersécurité & Tech

## NOM
**veille** — Agent IA local autonome de veille Cybersécurité & Tech propulsé par **Ollama** (`{model_name}`) et cache **SQLite**.

## SYNOPSIS
- `veille`
- `veille -fr` | `veille --french`
- `veille -s [-fr]` | `veille --sources [-fr]`
- `veille -d [-fr]` | `veille --detail [-fr]`
- `veille -d "<mot-clé, CVE, sujet ou numéro>" [-fr]`
- `veille -u` | `veille --update`
- `veille man`

## COMMANDES ET OPTIONS
1. **`veille`** *(sans argument)*
   Affiche instantanément le **Résumé Synthétique du Jour** depuis le cache SQLite local :
   - **Briefing Exécutif Global** généré par l'IA locale.
   - **Actualités classées par catégories** (`Cybersécurité` / `Tech`) avec **titres numérotés** (`[01]`, `[02]`...) et **points clés**.

2. **`veille -fr`** *(ou `--fr` / `--french`, combinable avec `-s` et `-d`)*
   Affiche une **traduction française complète** de chaque article (titre traduit en français + rappel discret du titre original `VO` + résumé court ou détaillé intégralement traduit en français).

3. **`veille -s`** *(ou `--sources`, combinable avec `-fr`)*
   Affiche le tableau complet des articles du jour avec leurs **numéros**, **catégories**, **sources**, **dates de publication** et **liens URL cliquables** directement dans le terminal.

4. **`veille -d`** *(ou `--detail`, combinable avec `-fr`)*
   Affiche le **rapport détaillé** de toutes les actualités du jour (résumé technique complet de 2-3 phrases par article, source et lien).

5. **`veille -d "mot-clé ou sujet"`** *(ou `--detail "mot-clé"`, combinable avec `-fr`)*
   Recherche dans les articles du jour (en anglais et en français, par mot-clé, CVE, technologie ou numéro d'article ex: `veille -d 1`) et interroge le moteur IA local **Ollama** pour fournir une **analyse approfondie** :
   - Contexte & synthèse de l'incident ou de la technologie.
   - Impacts techniques (CVE, systèmes touchés, vecteurs d'attaque).
   - Recommandations de sécurité et mesures de remédiation.

6. **`veille -u`** *(ou `--update`)*
   Force une **mise à jour manuelle immédiate** : récupère tous les flux RSS en parallèle, déduplique, génère les résumés et les traductions françaises en cache SQLite et met à jour le Briefing Global du jour.

7. **`veille man`**
   Affiche ce manuel d'utilisation complet.

## EXEMPLES D'UTILISATION
```bash
# Consulter le briefing du jour instantanément
veille

# Consulter le briefing avec traduction française intégrale de chaque article
veille -fr

# Lister toutes les sources avec titres traduits en français et liens URL cliquables
veille -s -fr

# Lire les résumés détaillés traduits en français de tous les articles du jour
veille -d -fr

# Obtenir une analyse technique approfondie sur un sujet, une CVE ou l'article #2
veille -d "NGINX" -fr
veille -d "CERT-FR"
veille -d "2" -fr

# Forcer le rafraîchissement immédiat des flux RSS, résumés IA et traductions FR
veille -u
```

## FICHIERS & CONFIGURATION
- **Fichier de configuration (`config.json`) :** `{cfg_path}`
- **Base de données cache SQLite (`veille.db`) :** `{db_path}`
- **Modèle Ollama actif :** `{model_name}` (`http://localhost:11434/api/generate`)
- **Sources Cybersécurité actives :** {cyber_sources}
- **Sources Tech actives :** {tech_sources}

## SERVICE D'ARRIÈRE-PLAN (MULTI-OS : LINUX / MACOS / WINDOWS)
{get_os_service_help()}
"""
    console.print(
        Panel(
            Markdown(man_text),
            title=f"[bold bright_blue]MANUEL D'UTILISATION — VEILLE v{__version__}[/bold bright_blue]",
            border_style="bright_blue",
            padding=(1, 2),
        )
    )


def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur d'arguments CLI."""
    parser = argparse.ArgumentParser(
        prog="veille",
        description="Agent IA local de veille Cybersécurité & Tech (100% local via Ollama & SQLite).",
        add_help=True,
    )
    parser.add_argument(
        "subcommand",
        nargs="?",
        default=None,
        help="Sous-commande optionnelle : 'man' pour afficher le manuel complet.",
    )
    parser.add_argument(
        "-fr",
        "--fr",
        "--french",
        action="store_true",
        dest="french",
        help="Affiche la traduction française intégrale de chaque article (titres et résumés).",
    )
    parser.add_argument(
        "-s",
        "--sources",
        action="store_true",
        help="Affiche la liste des articles du jour avec titres, dates, sources et liens URL cliquables.",
    )
    parser.add_argument(
        "-d",
        "--detail",
        nargs="?",
        const="__ALL__",
        default=None,
        metavar="SUJET",
        help="Affiche le résumé détaillé de toutes les actualités (sans argument) ou une analyse IA approfondie sur un mot-clé/sujet.",
    )
    parser.add_argument(
        "-u",
        "--update",
        action="store_true",
        help="Force une mise à jour manuelle immédiate des flux RSS, résumés IA et traductions FR.",
    )
    parser.add_argument(
        "--install-service",
        action="store_true",
        help="Configure automatiquement le service d'arrière-plan (systemd sur Linux, launchd sur macOS, Task Scheduler sur Windows).",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Mode silencieux (utilisé par le service en arrière-plan).",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"veille {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée principal de la commande `veille`."""
    args_list = argv if argv is not None else sys.argv[1:]

    if args_list and args_list[0].lower() in ("man", "manual", "help"):
        render_manual()
        return 0

    parser = build_parser()
    args = parser.parse_args(args_list)

    if args.subcommand and args.subcommand.lower() in ("man", "manual", "help"):
        render_manual()
        return 0

    if args.install_service:
        ok, msg = setup_autostart()
        style = "bold green" if ok else "bold yellow"
        console.print(f"[{style}]{msg}[/{style}]")
        return 0 if ok else 1

    if args.detail == "__ALL__" and args.subcommand:
        args.detail = args.subcommand

    config = load_config()
    db_path = get_db_path(config)
    lang_fr = bool(args.french)

    if args.update:
        run_update_worker(quiet=args.quiet)
        if not args.quiet and not args.sources and args.detail is None:
            console.print()
            render_synthetic_briefing(config, db_path, lang_fr=lang_fr)
        return 0

    if args.sources:
        render_sources(config, db_path, lang_fr=lang_fr)
        return 0

    if args.detail is not None:
        if args.detail == "__ALL__":
            render_all_details(config, db_path, lang_fr=lang_fr)
        else:
            render_topic_detail(args.detail, config, db_path, lang_fr=lang_fr)
        return 0

    render_synthetic_briefing(config, db_path, lang_fr=lang_fr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
