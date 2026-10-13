"""
Desktop environment integration for Sub-Deck on SteamOS / KDE Plasma.
Handles .desktop file creation, desktop application menu registration,
and KDE autostart management.
"""

import os
import shutil
import subprocess
from typing import Dict, Any

from core.system import get_user_home, run_command


def get_desktop_paths() -> Dict[str, str]:
    """Returns absolute paths for desktop entry and autostart files."""
    user_home = get_user_home()
    apps_dir = os.path.join(user_home, ".local", "share", "applications")
    autostart_dir = os.path.join(user_home, ".config", "autostart")
    return {
        "apps_dir": apps_dir,
        "app_file": os.path.join(apps_dir, "sub-deck-tray.desktop"),
        "autostart_dir": autostart_dir,
        "autostart_file": os.path.join(autostart_dir, "sub-deck-tray.desktop"),
    }


def generate_desktop_file_content(plugin_dir: str) -> str:
    """Generates FreeDesktop .desktop entry content."""
    script_path = os.path.join(plugin_dir, "tray", "tray_app.py")
    icon_path = os.path.join(plugin_dir, "assets", "logo.png")

    content = f"""[Desktop Entry]
Type=Application
Name=Sub-Deck VPN
GenericName=VPN Tray Manager
Comment=Manage Sub-Deck proxy and VPN subscriptions directly from the system tray
Exec=python3 "{script_path}"
Icon={icon_path}
Terminal=false
Categories=Network;VPN;Utility;
Keywords=vpn;vless;proxy;subdeck;steamdeck;
StartupNotify=false
X-KDE-autostart-after=panel
"""
    return content


def _get_target_uid_gid() -> tuple:
    """Discovers target non-root uid and gid for desktop files."""
    user_home = get_user_home()
    try:
        st = os.stat(user_home)
        return st.st_uid, st.st_gid
    except Exception:
        return 1000, 1000


def _safe_write_file(target_path: str, content: str) -> bool:
    """Writes desktop file and ensures proper non-root ownership if run as root."""
    try:
        # Avoid writing if identical
        if os.path.isfile(target_path):
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    if f.read() == content:
                        return True
            except Exception:
                pass

        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(target_path, 0o755)

        # Chown to normal user if executed by root (Decky daemon)
        if os.geteuid() == 0:
            uid, gid = _get_target_uid_gid()
            os.chown(target_path, uid, gid)
        return True
    except PermissionError:
        return True
    except Exception as e:
        print(f"Error writing {target_path}: {e}")
        return False


def ensure_desktop_entry(plugin_dir: str) -> bool:
    """Installs or updates the desktop menu entry."""
    try:
        paths = get_desktop_paths()
        os.makedirs(paths["apps_dir"], exist_ok=True)
        if os.geteuid() == 0:
            uid, gid = _get_target_uid_gid()
            try:
                os.chown(paths["apps_dir"], uid, gid)
            except Exception:
                pass

        content = generate_desktop_file_content(plugin_dir)
        success = _safe_write_file(paths["app_file"], content)
        if success:
            subprocess.run(["update-desktop-database", paths["apps_dir"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return success
    except Exception as e:
        print(f"Failed to create desktop entry: {e}")
        return False


def set_autostart(plugin_dir: str, enable: bool) -> bool:
    """Enables or disables KDE Plasma / XDG autostart."""
    paths = get_desktop_paths()
    try:
        if enable:
            ensure_desktop_entry(plugin_dir)
            os.makedirs(paths["autostart_dir"], exist_ok=True)
            if os.geteuid() == 0:
                uid, gid = _get_target_uid_gid()
                try:
                    os.chown(paths["autostart_dir"], uid, gid)
                except Exception:
                    pass

            content = generate_desktop_file_content(plugin_dir)
            return _safe_write_file(paths["autostart_file"], content)
        else:
            if os.path.exists(paths["autostart_file"]):
                try:
                    os.remove(paths["autostart_file"])
                except Exception:
                    pass
            return True
    except Exception as e:
        print(f"Failed to set autostart={enable}: {e}")
        return False


def get_desktop_integration_status(plugin_dir: str) -> Dict[str, Any]:
    """Checks whether the desktop entry and autostart are currently active."""
    paths = get_desktop_paths()
    return {
        "installed": os.path.exists(paths["app_file"]),
        "autostart": os.path.exists(paths["autostart_file"]),
    }


def kill_tray_process() -> bool:
    """Terminates any running tray_app.py instances."""
    try:
        subprocess.run(["pkill", "-f", "tray/tray_app.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def launch_tray_process(plugin_dir: str) -> bool:
    """Launches tray_app.py in the user's graphical desktop session."""
    script_path = os.path.join(plugin_dir, "tray", "tray_app.py")
    if not os.path.exists(script_path):
        return False

    # Check if already running
    try:
        res = subprocess.run(["pgrep", "-f", "tray/tray_app.py"], stdout=subprocess.PIPE)
        if res.returncode == 0 and res.stdout.strip():
            return True
    except Exception:
        pass

    user_home = get_user_home()
    user_name = os.path.basename(user_home) or "deck"

    # Identify graphical display / DBus environment
    env = os.environ.copy()
    display = env.get("DISPLAY", ":0")
    wayland_display = env.get("WAYLAND_DISPLAY", "wayland-0")

    cmd = ["python3", script_path]

    # If running as root (Decky daemon), drop privileges to user
    if os.geteuid() == 0:
        uid = 1000
        try:
            import pwd
            uid = pwd.getpwnam(user_name).pw_uid
        except Exception:
            pass

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
        print(f"Failed to launch tray process: {e}")
        return False
