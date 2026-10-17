"""
Cloudflare WARP account generator and WireGuard profile manager.
Uses sing-box native Curve25519 key generator and Cloudflare API
to register and maintain authentic WARP WireGuard identities.
"""

import os
import json
import subprocess
import datetime
import secrets
import base64
import urllib.request
import urllib.error
from typing import Dict, Any, Optional

CLOUDFLARE_REG_API = "https://api.cloudflareclient.com/v0a4471/reg"
DEFAULT_WARP_PEER_KEY = "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="
DEFAULT_WARP_ENDPOINT_IP = "162.159.192.1"
DEFAULT_WARP_ENDPOINT_PORT = 2408


def get_warp_identity_path(settings_dir: str) -> str:
    return os.path.join(settings_dir, "warp_identity.json")


def generate_warp_identity(
    bin_dir: str,
    settings_dir: str,
    force: bool = False,
    log_func=None
) -> Dict[str, Any]:
    """
    Registers a Cloudflare WARP account or loads the cached identity.
    Returns node dictionary ready for sing-box WireGuard endpoint.
    """
    identity_file = get_warp_identity_path(settings_dir)
    singbox_bin = os.path.join(bin_dir, "sing-box")

    def _log(msg: str):
        if log_func:
            log_func(f"[WARP] {msg}")

    # 1. Return cached profile if exists and not forced
    if not force and os.path.exists(identity_file):
        try:
            with open(identity_file, "r", encoding="utf-8") as f:
                saved_node = json.load(f)
            if saved_node and saved_node.get("private_key"):
                _log("Using cached Cloudflare WARP identity")
                return {"success": True, "node": saved_node, "cached": True}
        except Exception as e:
            _log(f"Error reading cached WARP identity: {e}")

    # 2. Generate Curve25519 WireGuard keypair using sing-box
    if not os.path.isfile(singbox_bin) or not os.access(singbox_bin, os.X_OK):
        _log(f"sing-box binary missing at {singbox_bin}")
        return {"success": False, "error": "sing-box binary not found"}

    try:
        out = subprocess.check_output([singbox_bin, "generate", "wg-keypair"], timeout=10).decode()
        lines = out.strip().splitlines()
        priv_key = lines[0].split(":", 1)[1].strip()
        pub_key = lines[1].split(":", 1)[1].strip()
    except Exception as e:
        _log(f"Failed to generate wg-keypair via sing-box: {e}")
        return {"success": False, "error": f"Keypair generation failed: {e}"}

    # 3. Register with Cloudflare WARP API
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    serial_num = secrets.token_hex(8)

    payload = {
        "key": pub_key,
        "tos": now_str,
        "model": "PC",
        "serial_number": serial_num,
        "key_type": "curve25519",
        "tunnel_type": "wireguard",
        "locale": "en_US"
    }

    req = urllib.request.Request(
        CLOUDFLARE_REG_API,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "User-Agent": "WARP for Android",
            "CF-Client-Version": "a-6.35-4471",
            "Content-Type": "application/json; charset=UTF-8"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        _log(f"Cloudflare registration request failed: {e}")
        return {"success": False, "error": f"Cloudflare API error: {e}"}

    cfg = data.get("config", {})
    client_id_b64 = cfg.get("client_id", "")
    reserved = list(base64.b64decode(client_id_b64)) if client_id_b64 else [0, 0, 0]

    addrs = cfg.get("interface", {}).get("addresses", {})
    ipv4 = addrs.get("v4", "172.16.0.2")
    ipv6 = addrs.get("v6", "")
    local_addrs = [f"{ipv4}/32"]
    if ipv6:
        local_addrs.append(f"{ipv6}/128")

    peer_pub = DEFAULT_WARP_PEER_KEY
    if cfg.get("peers") and len(cfg["peers"]) > 0:
        peer_pub = cfg["peers"][0].get("public_key") or DEFAULT_WARP_PEER_KEY

    node = {
        "type": "warp",
        "name": "🌐 Cloudflare WARP",
        "server": DEFAULT_WARP_ENDPOINT_IP,
        "port": DEFAULT_WARP_ENDPOINT_PORT,
        "private_key": priv_key,
        "peer_public_key": peer_pub,
        "reserved": reserved,
        "local_address": local_addrs,
        "subscription_url": "cloudflare_warp",
        "device_id": data.get("id", ""),
        "token": data.get("token", ""),
        "mtu": 1280
    }

    # Save to disk
    try:
        os.makedirs(settings_dir, exist_ok=True)
        with open(identity_file, "w", encoding="utf-8") as f:
            json.dump(node, f, indent=2)
        os.chmod(identity_file, 0o666)
    except Exception as e:
        _log(f"Failed to persist warp identity: {e}")

    _log("Successfully registered and created Cloudflare WARP node")
    return {"success": True, "node": node, "cached": False}
