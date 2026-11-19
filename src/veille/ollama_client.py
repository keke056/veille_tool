"""Client d'interfaçage avec le moteur IA local Ollama et module de traduction française."""

from __future__ import annotations

import concurrent.futures
import html
import json
import os
import platform
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

console = Console()

REFUSAL_PATTERNS = (
    "je suis désolé",
    "je ne peux pas",
    "ne peux pas fournir",
    "ne peux pas répondre",
    "i cannot",
    "i can't",
    "i am sorry",
    "i'm sorry",
    "as an ai",
    "en tant qu'ia",
)

FRENCH_NATIVE_SOURCES = {"cert-fr", "zataz", "korben", "next.ink"}


def is_refusal(text: str) -> bool:
    """Détecte si le modèle léger a généré un faux-positif de refus de sécurité."""
    lower = text.lower().strip()
    if not lower:
        return True
    return any(pat in lower for pat in REFUSAL_PATTERNS)


def is_already_french(source: str, text: str) -> bool:
    """Détermine si un texte ou une source est déjà rédigé en français."""
    if source.strip().lower() in FRENCH_NATIVE_SOURCES:
        return True
    lower = f" {text.lower()} "
    if any(ch in lower for ch in ("é", "è", "ê", "à", "ù", "ç", "œ")):
        return True
    fr_markers = (" dans ", " pour ", " avec ", " sur ", " une ", " des ", " les ", " aux ", " est ")
    matches = sum(1 for m in fr_markers if m in lower)
    return matches >= 2


def find_ollama_binary() -> str | None:
    """Recherche l'exécutable ollama dans le PATH ou les emplacements standards (Linux, macOS, Windows)."""
    found = shutil.which("ollama")
    if found:
        return found

    current_os = platform.system()
    candidates: list[Path] = []
    if current_os == "Windows":
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        if local_appdata:
            candidates.append(Path(local_appdata) / "Programs" / "Ollama" / "ollama.exe")
        candidates.extend(
            [
                Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
                Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "Ollama" / "ollama.exe",
            ]
        )
    elif current_os == "Darwin":
        candidates.extend(
            [
                Path("/opt/homebrew/bin/ollama"),
                Path("/usr/local/bin/ollama"),
                Path("/Applications/Ollama.app/Contents/Resources/ollama"),
                Path.home() / ".local" / "bin" / "ollama",
            ]
        )
    else:
        candidates.extend(
            [
                Path.home() / ".local" / "bin" / "ollama",
                Path("/usr/local/bin/ollama"),
                Path("/usr/bin/ollama"),
            ]
        )

    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def print_ollama_install_instructions() -> None:
    """Affiche des instructions claires adaptées à l'OS (Linux, macOS, Windows) si Ollama n'est pas installé."""
    current_os = platform.system()
    if current_os == "Windows":
        os_section = (
            "[bold cyan]Installation rapide sous Windows (PowerShell / CMD) :[/bold cyan]\n"
            "  [green]winget install Ollama.Ollama[/green]\n"
            "  [dim]Ou téléchargez l'installateur sur : https://ollama.com/download/windows[/dim]\n\n"
        )
    elif current_os == "Darwin":
        os_section = (
            "[bold cyan]Installation rapide sous macOS :[/bold cyan]\n"
            "  [green]brew install --cask ollama[/green]\n"
            "  [dim]Ou téléchargez l'application sur : https://ollama.com/download/mac[/dim]\n\n"
        )
    else:
        os_section = (
            "[bold cyan]Installation rapide sous Linux :[/bold cyan]\n"
            "  [green]curl -fsSL https://ollama.com/install.sh | sh[/green]\n\n"
        )

    instructions = (
        f"[bold red]Ollama n'est pas détecté sur votre système ({current_os}).[/bold red]\n\n"
        f"{os_section}"
        "[bold cyan]Puis démarrez le serveur et téléchargez le modèle léger :[/bold cyan]\n"
        "  [green]ollama serve[/green]\n"
        "  [green]ollama pull llama3.2:1b[/green]"
    )
    console.print(
        Panel(
            instructions,
            title="[bold yellow]Installation d'Ollama requise[/bold yellow]",
            border_style="yellow",
        )
    )


def is_ollama_running(base_url: str = "http://localhost:11434") -> bool:
    """Vérifie si le démon Ollama répond sur son API locale."""
    try:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_ollama_server(ollama_bin: str, base_url: str = "http://localhost:11434") -> bool:
    """Tente de démarrer le serveur Ollama en arrière-plan (Linux, macOS, Windows)."""
    current_os = platform.system()

    if current_os == "Linux":
        try:
            subprocess.run(
                ["systemctl", "--user", "start", "ollama.service"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            if is_ollama_running(base_url):
                return True
        except Exception:
            pass
    elif current_os == "Darwin" and Path("/Applications/Ollama.app").exists():
        try:
            subprocess.run(
                ["open", "-a", "Ollama", "--args", "hidden"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            for _ in range(6):
                time.sleep(0.5)
                if is_ollama_running(base_url):
                    return True
        except Exception:
            pass

    try:
        popen_kwargs: dict[str, Any] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if current_os == "Windows":
            popen_kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            )
        else:
            popen_kwargs["start_new_session"] = True

        subprocess.Popen([ollama_bin, "serve"], **popen_kwargs)
        for _ in range(10):
            time.sleep(0.5)
            if is_ollama_running(base_url):
                return True
    except Exception:
        pass
    return is_ollama_running(base_url)


def list_local_models(base_url: str = "http://localhost:11434") -> list[str]:
    """Retourne la liste des modèles déjà téléchargés dans Ollama."""
    try:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return [m.get("name", "") for m in payload.get("models", []) if m.get("name")]
    except Exception:
        return []


def ensure_ollama_ready(
    config: dict[str, Any],
    auto_pull: bool = True,
    quiet: bool = False,
) -> tuple[bool, str]:
    """
    Vérifie qu'Ollama est installé, en cours d'exécution, et que le modèle
    ultra-léger configuré (ex: llama3.2:1b) est disponible localement.
    Télécharge automatiquement le modèle s'il est absent.
    """
    ollama_cfg = config.get("ollama", {})
    base_url = ollama_cfg.get("base_url", "http://localhost:11434")
    target_model = ollama_cfg.get("model", "llama3.2:1b")

    ollama_bin = find_ollama_binary()
    if not ollama_bin and not is_ollama_running(base_url):
        if not quiet:
            print_ollama_install_instructions()
        return False, target_model

    if not is_ollama_running(base_url) and ollama_bin:
        if not quiet:
            console.print("[dim]Démarrage automatique du serveur local Ollama...[/dim]")
        if not start_ollama_server(ollama_bin, base_url):
            if not quiet:
                print_ollama_install_instructions()
            return False, target_model

    local_models = list_local_models(base_url)
    model_found = any(
        m == target_model or m.startswith(f"{target_model}:")
        for m in local_models
    )

    if not model_found and auto_pull:
        if not ollama_bin:
            return False, target_model
        if not quiet:
            console.print(
                f"[bold cyan]Téléchargement automatique du modèle ultra-léger "
                f"[yellow]{target_model}[/yellow] via Ollama...[/bold cyan]"
            )
        try:
            subprocess.run(
                [ollama_bin, "pull", target_model],
                check=True,
                stdout=subprocess.DEVNULL if quiet else None,
                stderr=subprocess.DEVNULL if quiet else None,
            )
            model_found = True
        except Exception as exc:
            if not quiet:
                console.print(
                    f"[bold red]Erreur lors du téléchargement de {target_model} : {exc}[/bold red]"
                )
            return False, target_model

    return model_found, target_model


def generate_text(
    prompt: str,
    config: dict[str, Any],
    system: str | None = None,
    num_predict: int = 90,
    num_ctx: int = 1024,
) -> str:
    """Appelle l'API locale http://localhost:11434/api/generate."""
    ollama_cfg = config.get("ollama", {})
    api_url = ollama_cfg.get("api_url", "http://localhost:11434/api/generate")
    model = ollama_cfg.get("model", "llama3.2:1b")
    timeout = int(ollama_cfg.get("timeout_seconds", 45))
    temperature = float(ollama_cfg.get("temperature", 0.2))

    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "num_thread": 4,
        },
    }
    if system:
        body["system"] = system

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        api_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        return result.get("response", "").strip()


def build_extractive_summaries(article: dict[str, Any]) -> tuple[str, str]:
    """
    Construit un résumé court (point clé) et un résumé détaillé structuré
    à partir du contenu RSS nettoyé et des indicateurs techniques (CVE, avis).
    """
    title = article.get("title", "").strip()
    source = article.get("source", "").strip()
    category = article.get("category", "Cyber")
    raw = (article.get("raw_content") or "").strip()

    hm_points = ""
    m_pts = re.search(r"Points:\s*(\d+)\s*#\s*Comments:\s*(\d+)", raw)
    if m_pts:
        hm_points = f"Score HN : {m_pts.group(1)} pts ({m_pts.group(2)} commentaires). "

    raw = re.sub(r"Article URL:\s*\S+", "", raw)
    raw = re.sub(r"Comments URL:\s*\S+", "", raw)
    raw = re.sub(r"Points:\s*\d+\s*#\s*Comments:\s*\d+", "", raw)
    raw = re.sub(r"Cet article .*? est apparu en premier sur .*?\.?$", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"The post .*? appeared first on .*?\.?$", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s+", " ", raw).strip()

    cves = sorted(set(re.findall(r"CVE-\d{4}-\d{4,7}", f"{title} {raw}", flags=re.IGNORECASE)))
    cert_ids = sorted(set(re.findall(r"CERTFR-\d{4}-[A-Z]+-\d+", f"{title} {raw}", flags=re.IGNORECASE)))
    tags = [c.upper() for c in (cves[:3] + cert_ids[:2])]
    tag_badge = f" [{', '.join(tags)}]" if tags else ""

    if not raw or raw.lower() == title.lower():
        if category == "Cyber":
            short_s = f"[{source}]{tag_badge} Bulletin de sécurité : {title}."
            detail_s = (
                f"Alerte Cybersécurité publiée par {source} concernant « {title} »{tag_badge}. "
                f"{hm_points}Ce sujet figure parmi les bulletins prioritaires à vérifier pour l'évaluation des risques."
            )
        else:
            short_s = f"[{source}] Point clé Tech : {title}."
            detail_s = (
                f"Actualité technologique rapportée par {source} portant sur « {title} ». "
                f"{hm_points}Consultez l'article complet via le lien source pour les spécifications techniques."
            )
        return short_s, detail_s

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw) if len(s.strip()) > 18]
    first_sent = sentences[0] if sentences else raw[:180]
    if len(first_sent) > 175:
        first_sent = first_sent[:172].rsplit(" ", 1)[0] + "..."

    short_s = f"{first_sent}{tag_badge}"
    detail_body = " ".join(sentences[:3]) if sentences else raw[:460]
    if len(detail_body) > 480:
        detail_body = detail_body[:477].rsplit(" ", 1)[0] + "..."
    if tag_badge and tags[0] not in detail_body:
        detail_body = f"{detail_body} — Indicateurs : {', '.join(tags)}."

    return short_s, detail_body


def _clean_translated_str(text: str) -> str:
    """Nettoie les entités HTML et espaces insécables d'une chaîne traduite."""
    cleaned = html.unescape(text).replace("\xa0", " ").replace("\u202f", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def translate_article_to_french(
    article: dict[str, Any],
    config: dict[str, Any],
) -> tuple[str, str, str]:
    """
    Traduit le titre, le résumé court et le résumé détaillé d'un article en français.
    Retourne (title_fr, summary_short_fr, summary_detail_fr).
    """
    source = article.get("source", "")
    title = article.get("title", "").strip()
    short_s = article.get("summary_short", "").strip()
    detail_s = article.get("summary_detail", "").strip()

    if not short_s or not detail_s:
        short_s, detail_s = build_extractive_summaries(article)

    # Si l'article provient d'une source francophone, aucune traduction n'est requise
    if is_already_french(source, title) and is_already_french(source, detail_s):
        return title, short_s, detail_s

    # Extraction des badges CVE / CERT-FR à préserver
    cves = sorted(set(re.findall(r"CVE-\d{4}-\d{4,7}", f"{title} {short_s} {detail_s}", flags=re.IGNORECASE)))
    cve_badge = f" [{', '.join(c.upper() for c in cves[:3])}]" if cves else ""

    # Cas particulier des brèves Hacker News où le résumé ne contient que le titre
    is_hn_stub = f"portant sur « {title} »" in detail_s or f"Point clé Tech : {title}" in short_s

    if is_hn_stub:
        payload = title[:450]
    else:
        # Combine titre et résumé détaillé avec le séparateur || (max 480 octets)
        max_detail_len = max(120, 460 - len(title))
        detail_snippet = detail_s[:max_detail_len]
        if len(detail_s) > max_detail_len and " " in detail_snippet:
            detail_snippet = detail_snippet.rsplit(" ", 1)[0] + "..."
        payload = f"{title} || {detail_snippet}"

    title_fr = ""
    detail_fr = ""

    # 1. Traduction rapide EN -> FR
    try:
        url = (
            "https://api.mymemory.translated.net/get?q="
            + urllib.parse.quote(payload)
            + "&langpair=en|fr"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tr_text = _clean_translated_str(data.get("responseData", {}).get("translatedText", ""))
            if tr_text and "MYMEMORY WARNING" not in tr_text.upper():
                if is_hn_stub:
                    title_fr = tr_text
                elif "||" in tr_text:
                    parts = tr_text.split("||", 1)
                    title_fr = parts[0].strip()
                    detail_fr = parts[1].strip()
                else:
                    title_fr = tr_text
    except Exception:
        pass

    # 2. Repli 100% local via Ollama si hors-ligne ou échec
    if not title_fr:
        try:
            prompt = (
                "Traduis fidèlement ce titre et ce résumé de l'anglais vers le français "
                "en conservant le séparateur || :\n"
                f"{payload}"
            )
            tr_ollama = _clean_translated_str(
                generate_text(
                    prompt=prompt,
                    config=config,
                    system="Tu es un traducteur technique anglais-français. Réponds uniquement avec la traduction française.",
                    num_predict=110,
                    num_ctx=1024,
                )
            )
            if tr_ollama and not is_refusal(tr_ollama):
                if "||" in tr_ollama:
                    parts = tr_ollama.split("||", 1)
                    title_fr = parts[0].strip()
                    detail_fr = parts[1].strip()
                else:
                    title_fr = tr_ollama
        except Exception:
            pass

    if not title_fr:
        title_fr = title

    if is_hn_stub:
        hm_points = ""
        m_pts = re.search(r"Score HN : [^.]+\.", detail_s)
        if m_pts:
            hm_points = m_pts.group(0) + " "
        short_fr = f"[{source}] Point clé Tech : {title_fr}."
        detail_fr = (
            f"Actualité technologique rapportée par {source} portant sur « {title_fr} ». "
            f"{hm_points}Consultez l'article complet via le lien source pour les spécifications techniques."
        )
        return title_fr, short_fr, detail_fr

    if not detail_fr:
        detail_fr = short_s if is_already_french(source, short_s) else detail_s

    # Construction du résumé court français à partir de la 1re phrase du détail traduit
    if is_already_french(source, short_s) and not short_s.startswith("TL;DR"):
        short_fr = short_s
    else:
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", detail_fr) if len(s.strip()) > 12]
        short_fr = sents[0] if sents else detail_fr[:175]
        if len(short_fr) > 180:
            short_fr = short_fr[:177].rsplit(" ", 1)[0] + "..."
        if cve_badge and cve_badge.strip(" []") not in short_fr:
            short_fr = f"{short_fr}{cve_badge}"

    if cve_badge and cve_badge.strip(" []") not in detail_fr:
        detail_fr = f"{detail_fr}{cve_badge}"

    return title_fr, short_fr, detail_fr


def translate_articles_parallel(
    articles: list[dict[str, Any]],
    config: dict[str, Any],
    max_workers: int = 6,
) -> None:
    """
    Traduit en parallèle une liste d'articles en français et renseigne
    `title_fr`, `summary_short_fr`, `summary_detail_fr` sur chaque dictionnaire.
    """
    if not articles:
        return

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_art = {
            executor.submit(translate_article_to_french, art, config): art
            for art in articles
        }
        for future in concurrent.futures.as_completed(future_to_art):
            art = future_to_art[future]
            try:
                t_fr, s_fr, d_fr = future.result()
                art["title_fr"] = t_fr
                art["summary_short_fr"] = s_fr
                art["summary_detail_fr"] = d_fr
            except Exception:
                art["title_fr"] = art.get("title", "")
                art["summary_short_fr"] = art.get("summary_short", "")
                art["summary_detail_fr"] = art.get("summary_detail", "")


def summarize_articles_batch(
    articles: list[dict[str, Any]],
    config: dict[str, Any],
    ollama_ok: bool = True,
) -> None:
    """
    Génère les résumés courts, détaillés et les traductions françaises
    pour une liste d'articles.
    """
    for art in articles:
        short_s, detail_s = build_extractive_summaries(art)
        art["summary_short"] = short_s
        art["summary_detail"] = detail_s

    translate_articles_parallel(articles, config=config)


def summarize_article(
    title: str,
    source: str,
    category: str,
    raw_content: str,
    config: dict[str, Any],
) -> tuple[str, str]:
    """Résume un article individuel."""
    art = {
        "title": title,
        "source": source,
        "category": category,
        "raw_content": raw_content,
    }
    return build_extractive_summaries(art)


def generate_daily_briefing(
    articles: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[str, str, str]:
    """
    Génère le Briefing Global synthétique du jour via Ollama local (`llama3.2:1b`).
    Retourne (global_summary, cyber_highlights, tech_highlights).
    """
    if not articles:
        return (
            "Aucune actualité récente disponible dans le cache.",
            "Aucune alerte cyber.",
            "Aucune actualité tech.",
        )

    cyber_arts = [a for a in articles if a["category"] == "Cyber"]
    tech_arts = [a for a in articles if a["category"] == "Tech"]

    cyber_list = "\n".join(
        f"- [{a['source']}] {a.get('title_fr') or a['title']}"
        for a in cyber_arts[:5]
    )
    tech_list = "\n".join(
        f"- [{a['source']}] {a.get('title_fr') or a['title']}"
        for a in tech_arts[:5]
    )

    system_prompt = (
        "Tu es rédacteur en chef d'une revue de presse informatique francophone. "
        "Rédige en français une synthèse exécutive factuelle en 2 ou 3 phrases."
    )
    prompt = (
        f"Sécurité ({len(cyber_arts)} titres) :\n{cyber_list}\n\n"
        f"Tech ({len(tech_arts)} titres) :\n{tech_list}\n\n"
        "Rédige en français un court briefing de 3 phrases résumant les thèmes majeurs du jour."
    )

    try:
        global_summary = generate_text(
            prompt=prompt,
            config=config,
            system=system_prompt,
            num_predict=85,
            num_ctx=1024,
        )
        global_summary = re.sub(
            r"^voici[^\n:]*:\s*",
            "",
            global_summary.strip(),
            flags=re.IGNORECASE,
        ).strip()
        if not global_summary or is_refusal(global_summary):
            raise ValueError("Refusal or empty response")
    except Exception:
        top_cyber = ", ".join((a.get("title_fr") or a["title"]) for a in cyber_arts[:3])
        top_tech = ", ".join((a.get("title_fr") or a["title"]) for a in tech_arts[:3])
        global_summary = (
            f"La veille du jour consolide {len(cyber_arts)} alertes Cybersécurité "
            f"(notamment : {top_cyber}) ainsi que {len(tech_arts)} actualités Tech & Systèmes "
            f"({top_tech})."
        )

    return global_summary, cyber_list, tech_list


def generate_topic_analysis(
    query: str,
    matched_articles: list[dict[str, Any]],
    all_today_articles: list[dict[str, Any]],
    config: dict[str, Any],
) -> str:
    """
    Interroge l'IA locale sur un mot-clé ou sujet spécifique en s'appuyant
    sur le contexte des articles du jour pour fournir une analyse approfondie,
    les impacts techniques (CVE, systèmes touchés) et les recommandations.
    """
    context_articles = matched_articles if matched_articles else all_today_articles[:4]
    context_blocks: list[str] = []
    for art in context_articles[:3]:
        t_display = art.get("title_fr") or art["title"]
        d_display = art.get("summary_detail_fr") or art["summary_detail"]
        context_blocks.append(
            f"- [{art['category']} / {art['source']}] {t_display} : {d_display[:220]}"
        )
    context_text = "\n".join(context_blocks) if context_blocks else "Aucun article en cache."

    system_prompt = (
        "Tu es un ingénieur en sécurité informatique défensive (CERT/SOC). "
        "Rédige en français une analyse technique concise et défensive."
    )
    prompt = (
        f"Sujet analysé : « {query} »\n"
        f"Articles :\n{context_text}\n\n"
        f"Rédige en français une analyse technique concise sur « {query} » (maximum 2 phrases par section) :\n"
        "1. **Contexte & Résumé**\n"
        "2. **Impacts Techniques (CVE, systèmes concernés)**\n"
        "3. **Recommandations Défensives**"
    )

    try:
        analysis = generate_text(
            prompt=prompt,
            config=config,
            system=system_prompt,
            num_predict=260,
            num_ctx=1024,
        )
        if analysis and not is_refusal(analysis):
            if analysis[-1] not in ".!?»)\"`*":
                last_dot = max(analysis.rfind("."), analysis.rfind("!"), analysis.rfind("\n"))
                if last_dot > len(analysis) // 2:
                    analysis = analysis[: last_dot + 1].strip()
            return analysis
    except Exception:
        pass

    ref_lines = "\n".join(
        f"- **[{a['source']}] {a.get('title_fr') or a['title']}** : {a.get('summary_detail_fr') or a['summary_detail']}"
        for a in context_articles[:4]
    )
    return (
        f"### 1. Contexte & Synthèse sur « {query} »\n"
        f"Analyse consolidée à partir des flux de veille Cybersécurité & Tech du jour :\n"
        f"{ref_lines}\n\n"
        f"### 2. Impacts Techniques (CVE & Systèmes)\n"
        f"- **Périmètre identifié** : Les bulletins associés à « {query} » concernent la sécurité des infrastructures, "
        f"la gestion des dépendances logicielles ou la protection des accès.\n"
        f"- **Risques potentiels** : Compromission de composants tiers, contournement d'authentification ou exposition de données.\n\n"
        f"### 3. Recommandations & Mesures Défensives\n"
        f"- Vérifier l'application des derniers correctifs éditeurs et avis du **CERT-FR**.\n"
        f"- Surveiller les journaux d'audit et contrôler l'intégrité des paquets/systèmes exposés."
    )
