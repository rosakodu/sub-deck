"""
System utilities for SteamOS / Linux environment.
Handles routing, process execution, user detection and network helpers.
"""

import os
import re
import socket
import subprocess
import time
import ipaddress
from typing import Optional, Tuple, Dict


def get_user_home() -> str:
    """Accurately discovers non-root user home directory on SteamOS."""
    env_home = os.environ.get("DECKY_USER_HOME")
    if env_home and os.path.isdir(env_home):
        return env_home

    # Check decky module attribute if loaded
    try:
        import decky
        if hasattr(decky, "DECKY_USER_HOME") and decky.DECKY_USER_HOME:
            if os.path.isdir(decky.DECKY_USER_HOME):
                return decky.DECKY_USER_HOME
    except Exception:
        pass

    if os.path.isdir("/home/deck"):
        return "/home/deck"

    if os.path.isdir("/home"):
        try:
            for user in os.listdir("/home"):
                if user not in ("lost+found", "root"):
                    user_path = f"/home/{user}"
                    if os.path.isdir(user_path):
                        return user_path
        except Exception:
            pass

    return os.path.expanduser("~")


def run_command(cmd_list, as_root: bool = True, timeout: Optional[float] = None) -> Optional[subprocess.CompletedProcess]:
    """Runs a system command with optional root elevation (sudo -n)."""
    cmd = list(cmd_list)
    if as_root and os.geteuid() != 0:
        cmd = ["sudo", "-n"] + cmd
    try:
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )
    except Exception:
        return None


def get_default_gateway() -> Tuple[Optional[str], Optional[str]]:
    """Discovers the active default gateway IP and outbound network interface."""
    try:
        res = subprocess.run(["ip", "route", "show", "default"], stdout=subprocess.PIPE, text=True, timeout=2)
        for line in res.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] == "default" and parts[1] == "via":
                gw = parts[2]
                iface = parts[4]
                return gw, iface
    except Exception:
        pass
    return None, None


def resolve_host(host: str) -> Optional[str]:
    """Resolves hostname to IP to prevent routing loops. Returns IP or original host."""
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    try:
        return socket.gethostbyname(host)
    except Exception:
        return host


def is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """Checks if a TCP port is open and accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def wait_for_port(host: str, port: int, timeout: float = 2.0, interval: float = 0.05) -> bool:
    """Polls a TCP port until open or timeout reached."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_port_open(host, port, timeout=interval):
            return True
        time.sleep(interval)
    return False


def is_interface_present(interface_name: str) -> bool:
    """Checks whether a network interface exists in the system."""
    res = subprocess.run(["ip", "link", "show", "dev", interface_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return res.returncode == 0


def wait_for_interface(interface_name: str, timeout: float = 2.0, interval: float = 0.05) -> bool:
    """Polls for network interface existence until created or timeout reached."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_interface_present(interface_name):
            return True
        time.sleep(interval)
    return False


def get_clean_env(extra_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Cleans environment variables of PyInstaller / MEI paths for child processes."""
    env = os.environ.copy()
    if "LD_LIBRARY_PATH" in env:
        paths = [p for p in env["LD_LIBRARY_PATH"].split(":") if "/tmp/" not in p and "_MEI" not in p]
        if paths:
            env["LD_LIBRARY_PATH"] = ":".join(paths)
        else:
            del env["LD_LIBRARY_PATH"]
    if extra_env:
        env.update(extra_env)
    return env


def read_system_clipboard() -> str:
    """
    Reads the system clipboard on Steam Deck.
    Supports Gamescope / X11 (Gaming Mode) and KDE Klipper (Desktop Mode).
    """
    # 1. Gamescope / X11 clipboard via deck user
    x11_helper = (
        "import ctypes\n"
        "x11 = ctypes.cdll.LoadLibrary('libX11.so.6')\n"
        "x11.XOpenDisplay.argtypes = [ctypes.c_char_p]\n"
        "x11.XOpenDisplay.restype = ctypes.c_void_p\n"
        "x11.XCloseDisplay.argtypes = [ctypes.c_void_p]\n"
        "x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]\n"
        "x11.XInternAtom.restype = ctypes.c_ulong\n"
        "x11.XCreateSimpleWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_ulong]\n"
        "x11.XCreateSimpleWindow.restype = ctypes.c_ulong\n"
        "x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]\n"
        "x11.XDefaultRootWindow.restype = ctypes.c_ulong\n"
        "x11.XConvertSelection.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]\n"
        "x11.XConvertSelection.restype = ctypes.c_int\n"
        "x11.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]\n"
        "x11.XNextEvent.restype = ctypes.c_int\n"
        "x11.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long, ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_char_p)]\n"
        "x11.XGetWindowProperty.restype = ctypes.c_int\n"
        "x11.XFree.argtypes = [ctypes.c_void_p]\n"
        "x11.XDestroyWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]\n"
        "display = x11.XOpenDisplay(b':0')\n"
        "if display:\n"
        "    try:\n"
        "        root = x11.XDefaultRootWindow(display)\n"
        "        win = x11.XCreateSimpleWindow(display, root, 0, 0, 1, 1, 0, 0, 0)\n"
        "        clip_atom = x11.XInternAtom(display, b'CLIPBOARD', False)\n"
        "        utf8_atom = x11.XInternAtom(display, b'UTF8_STRING', False)\n"
        "        prop_atom = x11.XInternAtom(display, b'SUBDECK_CLIP', False)\n"
        "        x11.XConvertSelection(display, clip_atom, utf8_atom, prop_atom, win, 0)\n"
        "        buf = (ctypes.c_char * 192)()\n"
        "        x11.XNextEvent(display, buf)\n"
        "        a_type, a_fmt, n_items, b_after, p_val = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_char_p()\n"
        "        x11.XGetWindowProperty(display, win, prop_atom, 0, 1024*1024, False, 0, ctypes.byref(a_type), ctypes.byref(a_fmt), ctypes.byref(n_items), ctypes.byref(b_after), ctypes.byref(p_val))\n"
        "        if p_val.value:\n"
        "            print(p_val.value.decode('utf-8', errors='ignore'))\n"
        "            x11.XFree(p_val)\n"
        "        x11.XDestroyWindow(display, win)\n"
        "    finally:\n"
        "        x11.XCloseDisplay(display)\n"
    )
    try:
        res = subprocess.run(
            ["sudo", "-u", "deck", "python3", "-c", x11_helper],
            capture_output=True, text=True, timeout=2
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    # 2. KDE Klipper via qdbus (Desktop Mode)
    for qdbus_bin in ("qdbus", "qdbus-qt5"):
        try:
            res = subprocess.run(
                [
                    "sudo", "-u", "deck",
                    "env", "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus",
                    qdbus_bin, "org.kde.klipper", "/klipper", "getClipboardContents"
                ],
                capture_output=True, text=True, timeout=2
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass

    # 3. KDE Klipper via dbus-send fallback
    try:
        res = subprocess.run(
            [
                "sudo", "-u", "deck",
                "env", "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus",
                "dbus-send", "--session", "--dest=org.kde.klipper",
                "--type=method_call", "--print-reply",
                "/klipper", "org.kde.klipper.klipper.getClipboardContents"
            ],
            capture_output=True, text=True, timeout=2
        )
        if res.returncode == 0 and "string" in res.stdout:
            for line in res.stdout.splitlines():
                if "string" in line:
                    parts = line.split("string", 1)
                    if len(parts) > 1:
                        val = parts[1].strip().strip('"')
                        if val:
                            return val
    except Exception:
        pass

    return ""
