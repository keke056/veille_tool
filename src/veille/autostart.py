"""Configuration multi-plateforme (Linux, macOS, Windows) du lancement automatique en arrière-plan."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

from veille.config import PROJECT_ROOT


def get_python_executable() -> str:
    """Retourne l'exécutable Python du virtualenv actif (ou pythonw sous Windows)."""
    exe = Path(sys.executable).resolve()
    if platform.system() == "Windows":
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.exists():
            return str(pythonw)
    return str(exe)


def get_veille_executable() -> str:
    """Retourne le chemin vers la commande `veille` installée."""
    venv_bin = Path(sys.executable).resolve().parent
    candidate = venv_bin / ("veille.exe" if platform.system() == "Windows" else "veille")
    if candidate.exists():
        return str(candidate)
    found = shutil.which("veille")
    if found:
        return found
    return f"{get_python_executable()} -m veille.cli"


def setup_linux_systemd() -> tuple[bool, str]:
    """Configure et active le service + timer systemd --user sous Linux (toutes les 4h)."""
    systemd_dir = Path.home() / ".config" / "systemd" / "user"
    systemd_dir.mkdir(parents=True, exist_ok=True)

    veille_cmd = get_veille_executable()
    service_path = systemd_dir / "veille.service"
    timer_path = systemd_dir / "veille.timer"

    service_content = f"""[Unit]
Description=Veille Cybersecurite & Tech - Collecte RSS et Synthese IA Locale
After=network-online.target ollama.service
Wants=ollama.service

[Service]
Type=oneshot
WorkingDirectory={PROJECT_ROOT}
Environment="PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart={veille_cmd} -u --quiet

[Install]
WantedBy=default.target
"""

    timer_content = """[Unit]
Description=Rafraichissement automatique de la veille Cyber & Tech (au demarrage et toutes les 4h)

[Timer]
OnBootSec=1min
OnStartupSec=30s
OnUnitActiveSec=4h
Persistent=true
Unit=veille.service

[Install]
WantedBy=timers.target
"""

    service_path.write_text(service_content, encoding="utf-8")
    timer_path.write_text(timer_content, encoding="utf-8")

    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "veille.service"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", "veille.timer"], check=True)
        return True, f"Service Linux systemd configuré et activé ({timer_path})"
    except Exception as exc:
        return False, f"Fichiers systemd créés dans {systemd_dir}, mais erreur d'activation : {exc}"


def setup_macos_launchd() -> tuple[bool, str]:
    """Configure et active l'agent launchd sous macOS (au démarrage et toutes les 4h)."""
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    plist_path = agents_dir / "com.veille.agent.plist"

    python_exe = get_python_executable()
    log_dir = Path.home() / "Library" / "Logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "veille.log"

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.veille.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_exe}</string>
        <string>-m</string>
        <string>veille.cli</string>
        <string>-u</string>
        <string>--quiet</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{PROJECT_ROOT}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>14400</integer>
    <key>StandardOutPath</key>
    <string>{log_file}</string>
    <key>StandardErrorPath</key>
    <string>{log_file}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
"""
    plist_path.write_text(plist_content, encoding="utf-8")

    try:
        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(["launchctl", "load", "-w", str(plist_path)], check=True)
        return True, f"Agent macOS launchd configuré et activé ({plist_path})"
    except Exception as exc:
        return False, f"Plist créé dans {plist_path}, mais erreur launchctl : {exc}"


def setup_windows_task_scheduler() -> tuple[bool, str]:
    """Configure une tâche planifiée Windows (au démarrage de session et toutes les 4h)."""
    python_exe = get_python_executable()
    task_name = "VeilleCyberTechAgent"
    tr_cmd = f'"{python_exe}" -m veille.cli -u --quiet'

    try:
        # Planification toutes les 4 heures
        subprocess.run(
            [
                "schtasks",
                "/Create",
                "/SC",
                "HOURLY",
                "/MO",
                "4",
                "/TN",
                task_name,
                "/TR",
                tr_cmd,
                "/F",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Ajout d'un script .cmd dans le dossier Démarrage (Startup) de l'utilisateur
        startup_dir = (
            Path.home()
            / "AppData"
            / "Roaming"
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
        )
        if startup_dir.exists():
            vbs_path = startup_dir / "veille_startup.vbs"
            vbs_content = (
                'Set WshShell = CreateObject("WScript.Shell")\n'
                f'WshShell.Run "{python_exe} -m veille.cli -u --quiet", 0, False\n'
            )
            vbs_path.write_text(vbs_content, encoding="utf-8")
        return True, f"Tâche planifiée Windows '{task_name}' configurée (toutes les 4h + démarrage)."
    except Exception as exc:
        return False, f"Erreur lors de la création de la tâche planifiée Windows : {exc}"


def setup_autostart() -> tuple[bool, str]:
    """Détecte l'OS courant et configure le service de démarrage automatique."""
    current_os = platform.system()
    if current_os == "Linux":
        return setup_linux_systemd()
    if current_os == "Darwin":
        return setup_macos_launchd()
    if current_os == "Windows":
        return setup_windows_task_scheduler()
    return False, f"OS non reconnu pour l'autostart automatique : {current_os}"


def get_os_service_help() -> str:
    """Retourne la documentation du service d'arrière-plan adaptée à l'OS actuel."""
    current_os = platform.system()
    if current_os == "Darwin":
        return (
            "L'agent `veille` s'exécute automatiquement à l'ouverture de session et toutes les **4 heures** :\n"
            "- **Activer/Réinstaller le service :** `veille --install-service`\n"
            "- **macOS (`launchd`) :** `launchctl list | grep com.veille.agent` (`~/Library/LaunchAgents/com.veille.agent.plist`)\n"
            "- **Logs macOS :** `tail -n 50 ~/Library/Logs/veille.log`"
        )
    if current_os == "Windows":
        return (
            "L'agent `veille` s'exécute automatiquement à l'ouverture de session et toutes les **4 heures** :\n"
            "- **Activer/Réinstaller le service :** `veille --install-service`\n"
            "- **Windows (`Task Scheduler`) :** `schtasks /Query /TN VeilleCyberTechAgent`\n"
            "- **Forcer l'exécution :** `schtasks /Run /TN VeilleCyberTechAgent`"
        )
    return (
        "L'agent `veille` s'exécute automatiquement au démarrage de la session et toutes les **4 heures** :\n"
        "- **Activer/Réinstaller le service (Linux/macOS/Windows) :** `veille --install-service`\n"
        "- **Vérifier le timer (Linux `systemd`) :** `systemctl --user status veille.timer`\n"
        "- **Voir les logs du worker :** `journalctl --user -u veille.service -n 50`"
    )
