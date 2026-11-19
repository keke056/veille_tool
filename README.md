# 🛡 Veille — Agent IA Local de Veille Cybersécurité & Tech

Outil CLI autonome 100% local et **multi-plateforme (Linux, macOS, Windows)** en Python qui collecte, déduplique, traduit et synthétise automatiquement l'actualité **Cybersécurité** et **Tech** grâce à un modèle IA ultra-léger local (**Ollama** `llama3.2:1b` / `qwen2.5:1.5b`) et un cache **SQLite** instantané.

---

## ✨ Fonctionnalités principales

- **100% Local & Privé :** Interroge l'API locale d'Ollama (`http://localhost:11434/api/generate`) avec un modèle ultra-léger (`llama3.2:1b` par défaut) économe en RAM et CPU.
- **Multi-OS (Linux, macOS, Windows) :** Détection automatique d'Ollama, gestion UTF-8 native sous Windows et configuration automatique du service d'arrière-plan (`systemd` sur Linux, `launchd` sur macOS, `Task Scheduler` sur Windows).
- **Affichage instantané :** Lecture immédiate depuis la base de cache SQLite locale (`data/veille.db`), formatée dans le terminal avec `rich`.
- **Sources RSS pré-configurées (`config.json`) :**
  - **Cybersécurité :** CERT-FR, BleepingComputer, The Hacker News, Krebs on Security, ZATAZ.
  - **Tech :** Ars Technica, Hacker News (RSS), Korben, Next.ink.

---

## 🚀 Commandes & Utilisation

| Commande | Description |
| :--- | :--- |
| `veille` | Affiche instantanément le **Résumé Synthétique du Jour** (Briefing Global + articles classés par catégories `Cyber` / `Tech` avec titres numérotés et points clés). |
| `veille -t [-fr]` / `--top` | Affiche uniquement le **Top 5 des informations les plus pertinentes à savoir** (classées par criticité : CVE, RCE, avis CERT-FR, impact majeur, en VO ou traduit avec `-fr`). |
| `veille -fr` | Affiche le résumé synthétique du jour avec la **traduction française intégrale** de chaque article (titre traduit, rappel du titre original `VO` et résumé traduit). |
| `veille -s [-fr]` / `--sources` | Affiche le tableau des articles du jour avec titres (traduits si `-fr`), dates, sources et **liens URL cliquables**. |
| `veille -d [-fr]` / `--detail` | Affiche le **résumé technique détaillé** de toutes les actualités du jour (en français intégral avec `-fr`). |
| `veille -d "mot-clé" [-fr]` | Recherche dans les articles du jour (en anglais et en français) et interroge l'IA locale pour fournir une **analyse approfondie**, les **impacts techniques (CVE, systèmes touchés)** et les recommandations. |
| `veille -u` / `--update` | Force une **mise à jour manuelle immédiate** des flux RSS, des résumés IA et des traductions françaises. |
| `veille --install-service` | Configure automatiquement le lancement au démarrage et le rafraîchissement toutes les 4h sur votre OS (**Linux / macOS / Windows**). |
| `veille man` | Affiche le **manuel d'utilisation complet** et l'emplacement de `config.json`. |

---

## 📦 Architecture du projet

```text
veille/
├── config.json              # Configuration des flux RSS et du modèle Ollama
├── pyproject.toml           # Packaging Python & entry_point CLI `veille`
├── README.md                # Documentation du projet
├── data/
│   └── veille.db            # Base de cache SQLite locale (générée automatiquement)
└── src/
    └── veille/
        ├── __init__.py
        ├── autostart.py     # Configuration auto-start multi-OS (systemd, launchd, schtasks)
        ├── cli.py           # Interface CLI & rendu Rich (UTF-8 multi-OS)
        ├── config.py        # Chargement de config.json & résolution des chemins
        ├── db.py            # Cache SQLite, déduplication, traductions FR & recherche
        ├── ollama_client.py # Vérification Ollama multi-OS, auto-pull & prompts IA
        ├── scraper.py       # Collecte RSS parallèle & nettoyage HTML
        └── worker.py        # Pipeline de mise à jour (arrière-plan & manuel)
```

---

## ⚙️ Installation (Linux, macOS, Windows)

### 1. Linux & macOS
```bash
git clone https://github.com/keke056/veille_tool.git
cd veille_tool
python3 -m venv .venv
.venv/bin/pip install -e .
mkdir -p ~/.local/bin && ln -sf "$(pwd)/.venv/bin/veille" ~/.local/bin/veille
veille --install-service
```

### 2. Windows (PowerShell)
```powershell
git clone https://github.com/keke056/veille_tool.git
cd veille_tool
python -m venv .venv
.\.venv\Scripts\pip install -e .
.\.venv\Scripts\veille --install-service
```
*(Ou installez globalement avec `pipx install -e .` pour avoir `veille` directement dans le PATH Windows/macOS/Linux).*
