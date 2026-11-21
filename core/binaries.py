"""
Binary and asset manager for Xray-core, tun2socks and GeoIP/Geosite databases.
Handles defaults restoration, downloads, and permission management.
"""

import hashlib
import http.client
import os
import shutil
import ssl
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from typing import Optional, Callable

from core.constants import (
    XRAY_RELEASE_SHA256,
    XRAY_RELEASE_URL,
    TUN2SOCKS_RELEASE_SHA256,
    TUN2SOCKS_RELEASE_URL,
    GEOIP_RELEASE_URL,
    GEOSITE_RELEASE_URL,
    MIN_GEO_FILE_SIZE,
    GEO_UPDATE_INTERVAL_SECONDS,
)
from core.system import run_command


def is_executable(path: str) -> bool:
    """Checks whether the file exists and is executable."""
    return os.path.isfile(path) and os.access(path, os.X_OK)


def download_file(
    url: str,
    target_path: str,
    min_size: int = 0,
    timeout: float = 60.0,
    *,
    expected_sha256: Optional[str] = None,
) -> bool:
    """Downloads over verified TLS and checks the payload before replacing the target."""
    tmp_path = None
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            data = resp.read()
        if len(data) < min_size:
            return False
        if expected_sha256 is not None and hashlib.sha256(data).hexdigest() != expected_sha256:
            return False

        with tempfile.NamedTemporaryFile(dir=os.path.dirname(target_path) or ".", delete=False) as output:
            tmp_path = output.name
            output.write(data)
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, target_path)
        tmp_path = None
        return True
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def copy_from_defaults(src_path: str, dst_path: str, make_executable: bool = False) -> bool:
    """Copies bundled default asset if present."""
    if os.path.isfile(src_path) and os.path.getsize(src_path) > 0:
        try:
            shutil.copy2(src_path, dst_path)
            if make_executable:
                os.chmod(dst_path, 0o755)
            return True
        except Exception:
            pass
    return False


def ensure_xray_and_tun(
    plugin_dir: str,
    settings_dir: str,
    bin_dir: str,
    xray_path: str,
    tun2socks_path: str,
    log_func: Optional[Callable[[str], None]] = None,
) -> bool:
    """Ensures Xray and tun2socks binaries and GeoDATs are present and executable."""
    os.makedirs(bin_dir, exist_ok=True)
    os.makedirs(settings_dir, exist_ok=True)

    need_xray = not is_executable(xray_path)
    need_tun = not is_executable(tun2socks_path)

    if not need_xray and not need_tun:
        return True

    # 1. Try copying from plugin defaults
    defaults_dir = os.path.join(plugin_dir, "defaults")
    default_xray = os.path.join(defaults_dir, "bin", "xray")
    default_tun = os.path.join(defaults_dir, "bin", "tun2socks")

    if need_xray and copy_from_defaults(default_xray, xray_path, make_executable=True):
        if log_func:
            log_func("xray binary restored from plugin defaults.")
        need_xray = False

    if need_tun and copy_from_defaults(default_tun, tun2socks_path, make_executable=True):
        run_command(["setcap", "cap_net_admin,cap_net_raw+ep", tun2socks_path])
        if log_func:
            log_func("tun2socks binary restored from plugin defaults.")
        need_tun = False

    # Copy bundled Geo DATs if not already present
    for dat in ("geoip.dat", "geosite.dat"):
        dat_target = os.path.join(bin_dir, dat)
        dat_default = os.path.join(defaults_dir, dat)
        if not os.path.exists(dat_target) and os.path.exists(dat_default):
            copy_from_defaults(dat_default, dat_target)

    if not need_xray and not need_tun:
        return True

    # 2. Remote download fallback
    if need_xray:
        if log_func:
            log_func("Downloading Xray-core binary...")
        zip_path = os.path.join(bin_dir, "xray.zip")
        if download_file(
            XRAY_RELEASE_URL, zip_path, timeout=90.0, expected_sha256=XRAY_RELEASE_SHA256
        ):
            try:
                with zipfile.ZipFile(zip_path, "r") as z:
                    z.extract("xray", path=bin_dir)
                    for dat in ("geoip.dat", "geosite.dat"):
                        if dat in z.namelist():
                            z.extract(dat, path=bin_dir)
                os.chmod(xray_path, 0o755)
                need_xray = False
                if log_func:
                    log_func("Xray-core downloaded and extracted successfully.")
            except Exception as e:
                if log_func:
                    log_func(f"Failed to unpack Xray archive: {e}")
            finally:
                if os.path.exists(zip_path):
                    try:
                        os.remove(zip_path)
                    except Exception:
                        pass
        if need_xray:
            return False

    if need_tun:
        if log_func:
            log_func("Downloading tun2socks binary...")
        zip_path = os.path.join(bin_dir, "tun2socks.zip")
        if download_file(
            TUN2SOCKS_RELEASE_URL, zip_path, timeout=60.0, expected_sha256=TUN2SOCKS_RELEASE_SHA256
        ):
            try:
                with zipfile.ZipFile(zip_path, "r") as z:
                    for name in z.namelist():
                        if "tun2socks" in name and not name.endswith(".zip"):
                            with open(tun2socks_path, "wb") as f_out:
                                f_out.write(z.read(name))
                            break
                os.chmod(tun2socks_path, 0o755)
                run_command(["setcap", "cap_net_admin,cap_net_raw+ep", tun2socks_path])
                need_tun = False
                if log_func:
                    log_func("tun2socks downloaded and installed successfully.")
            except Exception as e:
                if log_func:
                    log_func(f"Failed to unpack tun2socks archive: {e}")
            finally:
                if os.path.exists(zip_path):
                    try:
                        os.remove(zip_path)
                    except Exception:
                        pass
        if need_tun:
            return False

    return True


def check_singbox_has_awg(singbox_path: str) -> bool:
    """Checks whether the sing-box binary has the with_awg tag in its version output."""
    try:
        res = subprocess.run(
            [singbox_path, "version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5.0,
        )
        return "with_awg" in (res.stdout or "")
    except Exception:
        return False


def ensure_singbox(
    bin_dir: str,
    singbox_path: str,
    log_func: Optional[Callable[[str], None]] = None,
    plugin_dir: Optional[str] = None,
) -> bool:
    """Ensures sing-box binary is present, executable, and contains with_awg support."""
    defaults_dir = (
        os.path.join(plugin_dir, "defaults")
        if plugin_dir
        else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "defaults")
    )
    default_singbox = os.path.join(defaults_dir, "bin", "sing-box")

    if is_executable(singbox_path):
        if check_singbox_has_awg(singbox_path):
            return True
        if log_func:
            log_func("sing-box binary lacks with_awg tag; replacing from plugin defaults...")
        if copy_from_defaults(default_singbox, singbox_path, make_executable=True):
            if log_func:
                log_func("sing-box binary restored from plugin defaults with with_awg support.")
            if check_singbox_has_awg(singbox_path):
                return True

    # 1. Try copying from plugin defaults
    if copy_from_defaults(default_singbox, singbox_path, make_executable=True):
        if log_func:
            log_func("sing-box binary restored from plugin defaults.")
        if check_singbox_has_awg(singbox_path):
            return True

    # 2. Remote download fallback
    import tarfile
    from core.constants import SINGBOX_RELEASE_SHA256, SINGBOX_RELEASE_URL
    tar_path = os.path.join(bin_dir, "sing-box.tar.gz")
    if log_func:
        log_func("Downloading sing-box binary for Hysteria 2 / TUIC / AWG protocols...")
    if download_file(
        SINGBOX_RELEASE_URL, tar_path, timeout=60.0, expected_sha256=SINGBOX_RELEASE_SHA256
    ):
        try:
            with tarfile.open(tar_path, "r:gz") as tar:
                for member in tar.getmembers():
                    if member.name.endswith("/sing-box") or member.name == "sing-box":
                        member.name = "sing-box"
                        tar.extract(member, path=bin_dir)
                        break
            os.chmod(singbox_path, 0o755)
            if log_func:
                log_func("sing-box downloaded and installed successfully.")
            return True
        except Exception as e:
            if log_func:
                log_func(f"Failed to unpack sing-box archive: {e}")
        finally:
            if os.path.exists(tar_path):
                try:
                    os.remove(tar_path)
                except Exception:
                    pass
    return False


def update_geofiles(
    plugin_dir: str,
    settings_dir: str,
    force: bool = False,
    log_func: Optional[Callable[[str], None]] = None,
) -> bool:
    """Updates geoip.db and geosite.db files used by RoscomVPN preset."""
    geoip_path = os.path.join(settings_dir, "geoip.db")
    geosite_path = os.path.join(settings_dir, "geosite.db")
    defaults_dir = os.path.join(plugin_dir, "defaults")

    now = time.time()

    need_geoip = force or not os.path.exists(geoip_path) or os.path.getsize(geoip_path) < MIN_GEO_FILE_SIZE
    if not need_geoip and (now - os.path.getmtime(geoip_path) >= GEO_UPDATE_INTERVAL_SECONDS):
        need_geoip = True

    need_geosite = force or not os.path.exists(geosite_path) or os.path.getsize(geosite_path) < MIN_GEO_FILE_SIZE
    if not need_geosite and (now - os.path.getmtime(geosite_path) >= GEO_UPDATE_INTERVAL_SECONDS):
        need_geosite = True

    updated = False

    # Check defaults first
    default_geoip = os.path.join(defaults_dir, "geoip.db")
    default_geosite = os.path.join(defaults_dir, "geosite.db")

    if need_geoip and copy_from_defaults(default_geoip, geoip_path):
        need_geoip = False
        updated = True

    if need_geosite and copy_from_defaults(default_geosite, geosite_path):
        need_geosite = False
        updated = True

    # Remote download if needed
    if need_geoip:
        if log_func:
            log_func("Downloading geoip.db from SagerNet...")
        if download_file(GEOIP_RELEASE_URL, geoip_path, min_size=MIN_GEO_FILE_SIZE, timeout=30.0):
            updated = True
            if log_func:
                log_func("geoip.db downloaded successfully.")

    if need_geosite:
        if log_func:
            log_func("Downloading geosite.db from SagerNet...")
        if download_file(GEOSITE_RELEASE_URL, geosite_path, min_size=MIN_GEO_FILE_SIZE, timeout=30.0):
            updated = True
            if log_func:
                log_func("geosite.db downloaded successfully.")

    return updated
