"""
Routing profile and ruleset updater for sub-deck.
Fetches, verifies, and atomically overwrites routing profiles from Throne sources.
Guarantees clean replacement without duplicates.
"""

import os
import json
import tempfile
import urllib.request
from typing import Dict, Any, Optional, Callable

from core.constants import (
    THRONE_ROUTING_PROFILES,
    GEOIP_DAT_URL,
    GEOSITE_DAT_URL,
)


def download_file_atomic(url: str, dest_path: str, timeout: float = 20.0, mode: int = 0o666) -> bool:
    """Downloads a file to a temporary location and atomically replaces the destination file."""
    dest_dir = os.path.dirname(dest_path)
    os.makedirs(dest_dir, exist_ok=True)
    tmp_path = None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 sub-deck/1.1.3"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            data = resp.read()
            if not data:
                return False

        with tempfile.NamedTemporaryFile("wb", dir=dest_dir, delete=False) as f:
            tmp_path = f.name
            f.write(data)

        try:
            os.chmod(tmp_path, mode)
        except Exception:
            pass

        # Atomic replace overwrites existing file cleanly with NO duplicates
        os.replace(tmp_path, dest_path)
        try:
            os.chmod(dest_path, mode)
        except Exception:
            pass
        return True
    except Exception:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return False


def update_throne_routing(
    settings_dir: str,
    bin_dir: str,
    log_func: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Downloads and updates all routing profiles from Throne repository.
    Overwrites previous versions cleanly to prevent any duplicate rules or files.
    """
    routes_dir = os.path.join(settings_dir, "throne_routes")
    os.makedirs(routes_dir, exist_ok=True)

    if log_func:
        log_func("Starting download/update of Throne routing profiles...")

    downloaded = []
    failed = []

    # 1. Download each Throne profile JSON
    for name, url in THRONE_ROUTING_PROFILES.items():
        fname = f"{name}.json"
        dest_file = os.path.join(routes_dir, fname)
        if download_file_atomic(url, dest_file, timeout=15.0, mode=0o666):
            downloaded.append(name)
            if log_func:
                log_func(f"Updated Throne route profile: {name}")
        else:
            failed.append(name)
            if log_func:
                log_func(f"Failed to download Throne profile: {name}")

    # 2. Download latest geosite.dat & geoip.dat for Xray/singbox
    geo_updated = 0
    for gname, gurl in [("geosite.dat", GEOSITE_DAT_URL), ("geoip.dat", GEOIP_DAT_URL)]:
        dest_bin = os.path.join(bin_dir, gname)
        if download_file_atomic(gurl, dest_bin, timeout=40.0, mode=0o755):
            geo_updated += 1
            if log_func:
                log_func(f"Updated geo asset: {gname}")

    success = len(downloaded) > 0
    return {
        "success": success,
        "downloaded_profiles": downloaded,
        "failed_profiles": failed,
        "geo_updated": geo_updated,
        "message": "Пресеты маршрутизации Throne успешно обновлены" if success else "Ошибка обновления пресетов маршрутизации",
    }
