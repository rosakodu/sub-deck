"""
Desktop environment integration for Sub-Deck on SteamOS / KDE Plasma.
Handles KDE autostart management and background tray process control
without cluttering the desktop Application Launcher menu.
"""

import os
import shutil
import subprocess
from typing import Dict, Any, Optional

from core.system import get_user_home, get_target_uid_gid


def get_desktop_paths() -> Dict[str, str]:
    """Returns absolute paths for autostart, systemd user unit, and legacy app entries."""
    user_home = get_user_home()
    apps_dir = os.path.join(user_home, ".local", "share", "applications")
    autostart_dir = os.path.join(user_home, ".config", "autostart")
    systemd_user_dir = os.path.join(user_home, ".config", "systemd", "user")
    return {
        "apps_dir": apps_dir,
        "app_file": os.path.join(apps_dir, "sub-deck-tray.desktop"),
        "autostart_dir": autostart_dir,
        "autostart_file": os.path.join(autostart_dir, "sub-deck-tray.desktop"),
        "systemd_user_dir": systemd_user_dir,
        "service_file": os.path.join(systemd_user_dir, "sub-deck-tray.service"),
    }


def generate_autostart_content(plugin_dir: str) -> str:
    """Generates KDE autostart FreeDesktop entry with NoDisplay=true."""
    script_path = os.path.abspath(os.path.join(plugin_dir, "tray", "tray_app.py"))
    icon_path = os.path.abspath(os.path.join(plugin_dir, "assets", "logo.png"))

    content = f"""[Desktop Entry]
Type=Application
Name=Sub-Deck VPN Tray
Comment=Sub-Deck system tray background companion
Exec=python3 "{script_path}"
Icon={icon_path}
Terminal=false
NoDisplay=true
StartupNotify=false
X-KDE-autostart-after=panel
"""
    return content


def generate_systemd_service_content(plugin_dir: str) -> str:
    """Generates systemd user service unit for tray companion in KDE Plasma."""
    script_path = os.path.abspath(os.path.join(plugin_dir, "tray", "tray_app.py"))
    content = f"""[Unit]
Description=Sub-Deck Desktop Tray Companion
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 "{script_path}"
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=graphical-session.target
"""
    return content


def _get_target_uid_gid() -> tuple:
    """Discovers target non-root uid and gid."""
    return get_target_uid_gid()


def _safe_write_file(target_path: str, content: str, mode: int = 0o755) -> bool:
    """Writes target file and ensures proper non-root ownership if run as root."""
    try:
        parent_dir = os.path.dirname(target_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
            if os.geteuid() == 0:
                uid, gid = _get_target_uid_gid()
                try:
                    os.chown(parent_dir, uid, gid)
                except Exception:
                    pass

        if os.path.isfile(target_path):
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    if f.read() == content:
                        os.chmod(target_path, mode)
                        if os.geteuid() == 0:
                            uid, gid = _get_target_uid_gid()
                            os.chown(target_path, uid, gid)
                        return True
            except Exception:
                pass

        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(target_path, mode)

        if os.geteuid() == 0:
            uid, gid = _get_target_uid_gid()
            os.chown(target_path, uid, gid)
        return True
    except PermissionError:
        return True
    except Exception as e:
        print(f"Error writing {target_path}: {e}")
        return False


def remove_app_menu_entry() -> None:
    """Removes legacy .desktop file from applications menu if present."""
    try:
        paths = get_desktop_paths()
        if os.path.exists(paths["app_file"]):
            os.remove(paths["app_file"])
            subprocess.run(
                ["update-desktop-database", paths["apps_dir"]],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
    except Exception:
        pass


def ensure_desktop_autostart_and_service(plugin_dir: str) -> None:
    """
    Ensures autostart entry (~/.config/autostart/sub-deck-tray.desktop)
    and systemd user service (~/.config/systemd/user/sub-deck-tray.service)
    are always written, valid, and owned by user deck.
    """
    paths = get_desktop_paths()
    remove_app_menu_entry()

    # 1. Ensure autostart .desktop file
    autostart_content = generate_autostart_content(plugin_dir)
    _safe_write_file(paths["autostart_file"], autostart_content, mode=0o755)

    # 2. Ensure systemd user service file
    service_content = generate_systemd_service_content(plugin_dir)
    _safe_write_file(paths["service_file"], service_content, mode=0o644)

    # Reload systemd user daemon if possible
    user_home = get_user_home()
    user_name = os.path.basename(user_home) or "deck"
    uid, _ = _get_target_uid_gid()
    try:
        if os.geteuid() == 0:
            subprocess.run(
                ["sudo", "-u", user_name, "env", f"XDG_RUNTIME_DIR=/run/user/{uid}", "systemctl", "--user", "daemon-reload"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3
            )
        else:
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3
            )
    except Exception:
        pass


def set_autostart(plugin_dir: str, enable: bool) -> bool:
    """Enables or disables KDE Plasma autostart."""
    paths = get_desktop_paths()
    remove_app_menu_entry()
    try:
        if enable:
            ensure_desktop_autostart_and_service(plugin_dir)
            return True
        else:
            if os.path.exists(paths["autostart_file"]):
                try:
                    os.remove(paths["autostart_file"])
                except Exception:
                    pass
            if os.path.exists(paths["service_file"]):
                try:
                    os.remove(paths["service_file"])
                except Exception:
                    pass
            return True
    except Exception as e:
        print(f"Failed to set autostart={enable}: {e}")
        return False


def get_desktop_integration_status(plugin_dir: str) -> Dict[str, Any]:
    """Checks whether autostart is currently configured."""
    paths = get_desktop_paths()
    return {
        "autostart": os.path.exists(paths["autostart_file"]),
    }


def kill_tray_process(plugin_dir: Optional[str] = None) -> bool:
    """Terminates any running tray_app.py instances via systemd user unit and pkill fallback."""
    user_home = get_user_home()
    user_name = os.path.basename(user_home) or "deck"

    uid = 1000
    try:
        import pwd
        uid = pwd.getpwnam(user_name).pw_uid
    except Exception:
        pass

    # 1. Stop systemd user unit if managed
    try:
        if os.geteuid() == 0:
            subprocess.run(
                ["sudo", "-u", user_name, "env", f"XDG_RUNTIME_DIR=/run/user/{uid}", "systemctl", "--user", "stop", "sub-deck-tray.service"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3
            )
        else:
            subprocess.run(
                ["systemctl", "--user", "stop", "sub-deck-tray.service"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3
            )
    except Exception:
        pass

    # 2. Targeted process kill fallback using dynamic script path and pattern matching
    try:
        if plugin_dir:
            script_path = os.path.abspath(os.path.join(plugin_dir, "tray", "tray_app.py"))
            subprocess.run(["pkill", "-f", script_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-f", "tray/tray_app.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def launch_tray_process(plugin_dir: str) -> bool:
    """
    Launches tray_app.py in the user's graphical desktop session.
    Uses 'systemd-run --user --unit=sub-deck-tray' with fallback to subprocess.Popen.
    Ensures the tray process survives Decky session changes and desktop switching.
    """
    script_path = os.path.abspath(os.path.join(plugin_dir, "tray", "tray_app.py"))
    if not os.path.exists(script_path):
        return False

    # Check if already running using dynamic script path or pattern
    try:
        res = subprocess.run(["pgrep", "-f", script_path], stdout=subprocess.PIPE)
        if res.returncode == 0 and res.stdout.strip():
            return True
        res = subprocess.run(["pgrep", "-f", "tray/tray_app.py"], stdout=subprocess.PIPE)
        if res.returncode == 0 and res.stdout.strip():
            return True
    except Exception:
        pass

    user_home = get_user_home()
    user_name = os.path.basename(user_home) or "deck"

    uid = 1000
    try:
        import pwd
        uid = pwd.getpwnam(user_name).pw_uid
    except Exception:
        pass

    # Discover active user display / wayland environment
    display = os.environ.get("DISPLAY", ":0")
    wayland_display = os.environ.get("WAYLAND_DISPLAY", "wayland-0")

    # 1. Try launching via systemd-run --user (prevents process termination on session changes)
    systemd_cmd = [
        "systemd-run",
        "--user",
        "--unit=sub-deck-tray",
        f"--setenv=DISPLAY={display}",
        f"--setenv=WAYLAND_DISPLAY={wayland_display}",
        "python3", script_path
    ]

    try:
        if os.geteuid() == 0:
            res = subprocess.run(
                [
                    "sudo", "-u", user_name,
                    "env",
                    f"XDG_RUNTIME_DIR=/run/user/{uid}",
                    f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
                ] + systemd_cmd,
                capture_output=True,
                timeout=5
            )
        else:
            res = subprocess.run(systemd_cmd, capture_output=True, timeout=5)

        if res.returncode == 0:
            return True
    except Exception as e:
        print(f"[SubDeckDesktop] systemd-run error, falling back to direct spawn: {e}")

    # 2. Fallback to direct subprocess.Popen
    cmd = ["python3", script_path]
    if os.geteuid() == 0:
        cmd = [
            "sudo", "-u", user_name,
            f"DISPLAY={display}",
            f"WAYLAND_DISPLAY={wayland_display}",
            f"XDG_RUNTIME_DIR=/run/user/{uid}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
            "python3", script_path
        ]

    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        return True
    except Exception as e:
        print(f"[SubDeckDesktop] Failed to launch tray process: {e}")
        return False
