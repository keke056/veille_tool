# 🛡 Veille — Agent IA Local de Veille Cybersécurité & Tech

Outil CLI autonome 100% local en Python qui collecte, déduplique et synthétise automatiquement l'actualité **Cybersécurité** et **Tech** grâce à un modèle IA ultra-léger local (**Ollama** `llama3.2:1b` / `qwen2.5:1.5b`) et un cache **SQLite** instantané.

---

## ✨ Fonctionnalités principales

- **100% Local & Privé :** Interroge l'API locale d'Ollama (`http://localhost:11434/api/generate`) avec un modèle ultra-léger (`llama3.2:1b` par défaut) économe en RAM et CPU.
- **Affichage instantané :** Lecture immédiate depuis la base de cache SQLite locale (`data/veille.db`), formatée dans le terminal avec `rich`.
- **Sources RSS pré-configurées (`config.json`) :**
  - **Cybersécurité :** CERT-FR, BleepingComputer, The Hacker News, Krebs on Security, ZATAZ.
  - **Tech :** Ars Technica, Hacker News (RSS), Korben, Next.ink.
- **Automatisation en arrière-plan (`systemd --user`) :** Lancement automatique au démarrage de la session et rafraîchissement toutes les **4 heures** via `veille.timer` et `veille.service`.

---

## 🚀 Commandes & Utilisation

| Commande | Description |
| :--- | :--- |
| `veille` | Affiche instantanément le **Résumé Synthétique du Jour** (Briefing Global + articles classés par catégories `Cyber` / `Tech` avec titres numérotés et points clés). |
| `veille -fr` | Affiche le résumé synthétique du jour avec la **traduction française intégrale** de chaque article (titre traduit, rappel du titre original `VO` et résumé traduit). |
| `veille -s [-fr]` / `--sources` | Affiche le tableau des articles du jour avec titres (traduits si `-fr`), dates, sources et **liens URL cliquables**. |
| `veille -d [-fr]` / `--detail` | Affiche le **résumé technique détaillé** de toutes les actualités du jour (en français intégral avec `-fr`). |
| `veille -d "mot-clé" [-fr]` | Recherche dans les articles du jour (en anglais et en français) et interroge l'IA locale pour fournir une **analyse approfondie**, les **impacts techniques (CVE, systèmes touchés)** et les recommandations. |
| `veille -u` / `--update` | Force une **mise à jour manuelle immédiate** des flux RSS, des résumés IA et des traductions françaises. |
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
        ├── cli.py           # Interface CLI & rendu Rich
        ├── config.py        # Chargement de config.json & résolution des chemins
        ├── db.py            # Cache SQLite, déduplication & recherche
        ├── ollama_client.py # Vérification Ollama, auto-pull & prompts IA
        ├── scraper.py       # Collecte RSS parallèle & nettoyage HTML
        └── worker.py        # Pipeline de mise à jour (arrière-plan & manuel)
```

---

## ⚙️ Installation & Service Systemd

### Installation en mode éditable
```bash
python3 -m venv .venv
.venv/bin/pip install -e .
ln -sf "$(pwd)/.venv/bin/veille" ~/.local/bin/veille
```

### Vérification des services `systemd --user`
```bash
systemctl --user status ollama.service
systemctl --user status veille.timer
systemctl --user status veille.service
```
