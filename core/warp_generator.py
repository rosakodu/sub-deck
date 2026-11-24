"""
Cloudflare WARP to AmneziaWG (AWG) account and profile generator.
Registers authentic Cloudflare WARP credentials and constructs
DPI-bypassing AmneziaWG profiles (Mini QUIC TLS Initial, AWG 2.0, SIP).
"""

import os
import json
import random
import subprocess
import datetime
import secrets
import base64
import socket
import ssl
import http.client
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional

CLOUDFLARE_REG_API = "https://api.cloudflareclient.com/v0a4471/reg"
DEFAULT_WARP_PEER_KEY = "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="

CLOUDFLARE_REG_IPS = [
    "162.159.192.1",
    "162.159.193.1",
    "188.114.96.1",
    "188.114.97.1",
    "162.159.195.1",
]

# Resilient Cloudflare WARP endpoint IPs and ports pool
WARP_ENDPOINT_IPS = [
    "162.159.192.1", "162.159.192.2", "162.159.192.3", "162.159.192.4", "162.159.192.5",
    "162.159.193.1", "162.159.193.2", "162.159.193.3", "162.159.193.4", "162.159.193.5",
    "162.159.195.1", "162.159.195.2", "162.159.195.3", "162.159.195.4", "162.159.195.5",
    "188.114.96.1", "188.114.96.2", "188.114.96.3",
    "188.114.97.1", "188.114.97.2", "188.114.97.3",
]

WARP_PORTS = [
    500, 854, 859, 864, 878, 880, 890, 891, 894, 903, 908, 928, 934, 939, 942, 943,
    945, 946, 955, 968, 987, 988, 1002, 1010, 1014, 1018, 1070, 1074, 1180, 1387,
    1701, 1843, 2371, 2408, 2506, 3138, 3476, 3581, 3854, 4177, 4198, 4233, 4500,
    5279, 5956, 7103, 7152, 7156, 7281, 7559, 8319, 8742, 8854, 8886,
]

# Obfuscation templates
QUIC_I1 = "<b 0xcf00000001015d00002815edf9616e6a9db180e5847ba3c117b2490160ad35e4c24b><r 16>"
AWG2_I1 = "<b 0xce000000010897a297ecc34cd6dd000044d0ec2e2e1ea2991f467ace4222129b5a098823784694b4897b9986ae0b7280135fa85e196d9ad980b150122129ce2a9379531b0fd3e871ca5fdb883c369832f730e272d7b8b74f393f9f0fa43f11e510ecb2219a52984410c204cf875585340c62238e14ad04dff382f2c200e0ee22fe743b9c6b8b043121c5710ec289f471c91ee414fca8b8be8419ae8ce7ffc53837f6ade262891895f3f4cecd31bc93ac5599e18e4f01b472362b8056c3172b513051f8322d1062997ef4a383b01706598d08d48c221d30e74c7ce000cdad36b706b1bf9b0607c32ec4b3203a4ee21ab64df336212b9758280803fcab14933b0e7ee1e04a7becce3e2633f4852585c567894a5f9efe9706a151b615856647e8b7dba69ab357b3982f554549bef9256111b2d67afde0b496f16962d4957ff654232aa9e845b61463908309cfd9de0a6abf5f425f577d7e5f6440652aa8da5f73588e82e9470f3b21b27b28c649506ae1a7f5f15b876f56abc4615f49911549b9bb39dd804fde182bd2dcec0c33bad9b138ca07d4a4a1650a2c2686acea05727e2a78962a840ae428f55627516e73c83dd8893b02358e81b524b4d99fda6df52b3a8d7a5291326e7ac9d773c5b43b8444554ef5aea104a738ed650aa979674bbed38da58ac29d87c29d387d80b526065baeb073ce65f075ccb56e47533aef357dceaa8293a523c5f6f790be90e4731123d3c6152a70576e90b4ab5bc5ead01576c68ab633ff7d36dcde2a0b2c68897e1acfc4d6483aaaeb635dd63c96b2b6a7a2bfe042f6aed82e5363aa850aace12ee3b1a93f30d8ab9537df483152a5527faca21efc9981b304f11fc95336f5b9637b174c5a0659e2b22e159a9fed4b8e93047371175b1d6d9cc8ab745f3b2281537d1c75fb9451871864efa5d184c38c185fd203de206751b92620f7c369e031d2041e152040920ac2c5ab5340bfc9d0561176abf10a147287ea90758575ac6a9f5ac9f390d0d5b23ee12af583383d994e22c0cf42383834bcd3ada1b3825a0664d8f3fb678261d57601ddf94a8a68a7c273a18c08aa99c7ad8c6c42eab67718843597ec9930457359dfdfbce024afc2dcf9348579a57d8d3490b2fa99f278f1c37d87dad9b221acd575192ffae1784f8e60ec7cee4068b6b988f0433d96d6a1b1865f4e155e9fe020279f434f3bf1bd117b717b92f6cd1cc9bea7d45978bcc3f24bda631a36910110a6ec06da35f8966c9279d130347594f13e9e07514fa370754d1424c0a1545c5070ef9fb2acd14233e8a50bfc5978b5bdf8bc1714731f798d21e2004117c61f2989dd44f0cf027b27d4019e81ed4b5c31db347c4a3a4d85048d7093cf16753d7b0d15e078f5c7a5205dc2f87e330a1f716738dce1c6180e9d02869b5546f1c4d2748f8c90d9693cba4e0079297d22fd61402dea32ff0eb69ebd65a5d0b687d87e3a8b2c42b648aa723c7c7daf37abcc4bb85caea2ee8f55bec20e913b3324ab8f5c3304f820d42ad1b9f2ffc1a3af9927136b4419e1e579ab4c2ae3c776d293d397d575df181e6cae0a4ada5d67ecea171cca3288d57c7bbdaee3befe745fb7d634f70386d873b90c4d6c6596bb65af68f9e5121e67ebf0d89d3c909ceedfb32ce9575a7758ff080724e1ab5d5f43074ecb53a479af21ed03d7b6899c36631c0166f9d47e5e1d4528a5d3d3f744029c4b1c190cbfbad06f5f83f7ad0429fa9a2719c56ffe3783460e166de2d8>"
SIP_I1 = "<b 0x494e56495445207369703a626f624062696c6f78692e636f6d205349502f322e300d0a5669613a205349502f322e302f55445020706333332e61746c616e74612e636f6d3b6272616e63683d7a39684734624b3737366173646864730d0a4d61782d466f7277617264733a2037300d0a546f3a20426f62203c7369703a626f624062696c6f78692e636f6d3e0d0a46726f6d3a20416c696365203c7369703a616c6963654061746c616e74612e636f6d3e3b7461673d313932383330313737340d0a43616c6c2d49443a20613834623463373665363637313040706333332e61746c616e74612e636f6d0d0a435365713a2033313431353920494e564954450d0a436f6e74656e742d547970653a206170706c69636174696f6e2f7364700d0a436f6e74656e742d4c656e6774683a20300d0a0d0a>"
SIP_I2 = "<b 0x5349502f322e302031303020547279696e670d0a5669613a205349502f322e302f55445020706333332e61746c616e74612e636f6d3b6272616e63683d7a39684734624b3737366173646864730d0a546f3a20426f62203c7369703a626f624062696c6f78692e636f6d3e0d0a46726f6d3a20416c696365203c7369703a616c6963654061746c616e74612e636f6d3e3b7461673d313932383330313737340d0a43616c6c2d49443a20613834623463373665363637313040706333332e61746c616e74612e636f6d0d0a435365713a2033313431353920494e564954450d0a436f6e74656e742d4c656e6774683a20300d0a0d0a>"


def get_warp_identity_path(settings_dir: str) -> str:
    return os.path.join(settings_dir, "warp_identity.json")


def _build_amnezia_nodes(
    priv_key: str,
    peer_pub: str,
    local_addrs: List[str],
    device_id: str,
    token: str,
    reserved: List[int],
) -> List[Dict[str, Any]]:
    """Builds resilient AmneziaWG / WARP node variants (QUIC, AWG 2.0, SIP)."""
    chosen_ips = random.sample(WARP_ENDPOINT_IPS, min(3, len(WARP_ENDPOINT_IPS)))
    chosen_ports = random.sample(WARP_PORTS, min(3, len(WARP_PORTS)))

    # Node 1: Mini QUIC Initial TLS 1.3 ClientHello masking
    quic_node = {
        "type": "awg",
        "name": "Warp Generation (QUIC)",
        "server": chosen_ips[0],
        "port": chosen_ports[0],
        "private_key": priv_key,
        "peer_public_key": peer_pub,
        "local_address": local_addrs,
        "allowed_ips": ["0.0.0.0/0", "::/0"],
        "subscription_url": "amnezia_warp",
        "device_id": device_id,
        "token": token,
        "reserved": reserved,
        "mtu": 1280,
        "jc": 4,
        "jmin": 40,
        "jmax": 70,
        "s1": 0,
        "s2": 0,
        "h1": "1",
        "h2": "2",
        "h3": "3",
        "h4": "4",
        "i1": QUIC_I1,
    }

    # Node 2: AWG 2.0 Handshake Obfuscation
    awg2_node = {
        "type": "awg",
        "name": "Warp Generation (AWG 2.0)",
        "server": chosen_ips[1] if len(chosen_ips) > 1 else chosen_ips[0],
        "port": chosen_ports[1] if len(chosen_ports) > 1 else chosen_ports[0],
        "private_key": priv_key,
        "peer_public_key": peer_pub,
        "local_address": local_addrs,
        "allowed_ips": ["0.0.0.0/0", "::/0"],
        "subscription_url": "amnezia_warp",
        "device_id": device_id,
        "token": token,
        "reserved": reserved,
        "mtu": 1280,
        "jc": 4,
        "jmin": 40,
        "jmax": 70,
        "s1": 0,
        "s2": 0,
        "h1": "1",
        "h2": "2",
        "h3": "3",
        "h4": "4",
        "i1": AWG2_I1,
    }

    # Node 3: SIP VoIP Header Masking
    sip_node = {
        "type": "awg",
        "name": "Warp Generation (SIP)",
        "server": chosen_ips[2] if len(chosen_ips) > 2 else chosen_ips[0],
        "port": chosen_ports[2] if len(chosen_ports) > 2 else chosen_ports[0],
        "private_key": priv_key,
        "peer_public_key": peer_pub,
        "local_address": local_addrs,
        "allowed_ips": ["0.0.0.0/0", "::/0"],
        "subscription_url": "amnezia_warp",
        "device_id": device_id,
        "token": token,
        "reserved": reserved,
        "mtu": 1280,
        "jc": 4,
        "jmin": 40,
        "jmax": 70,
        "s1": 0,
        "s2": 0,
        "h1": "1",
        "h2": "2",
        "h3": "3",
        "h4": "4",
        "i1": SIP_I1,
        "i2": SIP_I2,
    }

    return [quic_node, awg2_node, sip_node]


class DirectIPHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection to a specific IP address while preserving the SNI hostname."""
    def __init__(self, ip: str, sni: str, **kwargs):
        super().__init__(ip, 443, **kwargs)
        self.sni = sni

    def connect(self):
        super(http.client.HTTPSConnection, self).connect()
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.sni)


def register_cloudflare_account(pub_key: str, log_func=None) -> Dict[str, Any]:
    """
    Registers a Cloudflare WARP account with multi-tier resilience:
    1. Direct HTTPS via urllib with unverified SSL context (fixes SteamOS CA bundle issues).
    2. Direct Anycast IP connection with custom SNI (bypasses DNS blocks and TSPU resets).
    3. Active local SOCKS5 proxy fallback (127.0.0.1:10808).
    """
    def _log(msg: str):
        if log_func:
            log_func(f"[Warp Registration] {msg}")

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
    payload_bytes = json.dumps(payload).encode("utf-8")

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    except Exception:
        ctx = ssl._create_unverified_context()

    last_error = None

    # Tier 1: Direct HTTPS via urllib with unverified SSL context
    req = urllib.request.Request(
        CLOUDFLARE_REG_API,
        data=payload_bytes,
        headers={
            "User-Agent": "WARP for Android",
            "CF-Client-Version": "a-6.35-4471",
            "Content-Type": "application/json; charset=UTF-8"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=8.0, context=ctx) as resp:
            data = json.loads(resp.read().decode())
            if data and data.get("id"):
                _log("Registration successful via primary Cloudflare endpoint")
                return {"success": True, "data": data}
    except Exception as e:
        last_error = e
        _log(f"Primary endpoint failed: {e}. Trying direct Cloudflare IPs...")

    # Tier 2: Direct TLS connection to Cloudflare Anycast IPs with SNI
    for ip in CLOUDFLARE_REG_IPS:
        conn = None
        try:
            conn = DirectIPHTTPSConnection(ip, "api.cloudflareclient.com", context=ctx, timeout=6.0)
            conn.request(
                "POST",
                "/v0a4471/reg",
                body=payload_bytes,
                headers={
                    "Host": "api.cloudflareclient.com",
                    "User-Agent": "WARP for Android",
                    "CF-Client-Version": "a-6.35-4471",
                    "Content-Type": "application/json; charset=UTF-8",
                    "Connection": "close"
                }
            )
            resp = conn.getresponse()
            if resp.status in (200, 201):
                body = resp.read().decode()
                data = json.loads(body)
                if data and data.get("id"):
                    _log(f"Registration successful via Cloudflare IP {ip}")
                    return {"success": True, "data": data}
            else:
                _log(f"Cloudflare IP {ip} returned HTTP {resp.status}")
        except Exception as e:
            last_error = e
            _log(f"Cloudflare IP {ip} failed: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    # Tier 3: Local SOCKS5 proxy fallback (127.0.0.1:10808) if active
    try:
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.settimeout(1.0)
        proxy_available = (test_sock.connect_ex(("127.0.0.1", 10808)) == 0)
        test_sock.close()

        if proxy_available:
            _log("Attempting registration via active local proxy (127.0.0.1:10808)...")
            import socks
            proxy_sock = socks.create_connection(
                ("api.cloudflareclient.com", 443),
                timeout=8.0,
                proxy_type=socks.SOCKS5,
                proxy_addr="127.0.0.1",
                proxy_port=10808
            )
            tls_sock = ctx.wrap_socket(proxy_sock, server_hostname="api.cloudflareclient.com")
            http_req = (
                f"POST /v0a4471/reg HTTP/1.1\r\n"
                f"Host: api.cloudflareclient.com\r\n"
                f"User-Agent: WARP for Android\r\n"
                f"CF-Client-Version: a-6.35-4471\r\n"
                f"Content-Type: application/json; charset=UTF-8\r\n"
                f"Content-Length: {len(payload_bytes)}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode("utf-8") + payload_bytes
            tls_sock.sendall(http_req)

            resp_data = b""
            while True:
                chunk = tls_sock.recv(4096)
                if not chunk:
                    break
                resp_data += chunk
            tls_sock.close()

            header, _, body = resp_data.partition(b"\r\n\r\n")
            if b"200 OK" in header or b"201 Created" in header:
                data = json.loads(body.decode())
                if data and data.get("id"):
                    _log("Registration successful via local proxy")
                    return {"success": True, "data": data}
    except Exception as e:
        last_error = e
        _log(f"Local proxy fallback failed: {e}")

    err_msg = f"Ошибка подключения к Cloudflare ({last_error}). Проверьте интернет-соединение."
    return {"success": False, "error": err_msg}


def generate_warp_identity(
    bin_dir: str,
    settings_dir: str,
    force: bool = False,
    log_func=None
) -> Dict[str, Any]:
    """
    Registers a Cloudflare account and builds AmneziaWG obfuscated profiles.
    Returns node dictionary and full nodes list.
    """
    identity_file = get_warp_identity_path(settings_dir)
    singbox_bin = os.path.join(bin_dir, "sing-box")

    def _log(msg: str):
        if log_func:
            log_func(f"[Warp Generation] {msg}")

    # 1. Return cached profile if exists and not forced
    if not force and os.path.exists(identity_file):
        try:
            with open(identity_file, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
            if saved_data:
                nodes = saved_data.get("nodes")
                primary_node = saved_data.get("node") or (nodes[0] if nodes else None)
                if primary_node and primary_node.get("private_key") and primary_node.get("type") == "awg":
                    _log("Using cached Warp Generation identity")
                    return {
                        "success": True,
                        "node": primary_node,
                        "nodes": nodes or [primary_node],
                        "cached": True
                    }
        except Exception as e:
            _log(f"Error reading cached WARP identity: {e}")

    # 2. Locate sing-box binary (bin_dir or fallback to defaults/bin/sing-box)
    candidate_bins = [
        singbox_bin,
        os.path.join(settings_dir, "bin", "sing-box"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "defaults", "bin", "sing-box"),
    ]
    actual_singbox = None
    for cand in candidate_bins:
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            actual_singbox = cand
            break

    if not actual_singbox:
        _log(f"sing-box binary missing at {singbox_bin}")
        return {"success": False, "error": "sing-box binary not found"}

    try:
        out = subprocess.check_output([actual_singbox, "generate", "wg-keypair"], timeout=10).decode()
        lines = out.strip().splitlines()
        priv_key = lines[0].split(":", 1)[1].strip()
        pub_key = lines[1].split(":", 1)[1].strip()
    except Exception as e:
        _log(f"Failed to generate wg-keypair via sing-box: {e}")
        return {"success": False, "error": f"Keypair generation failed: {e}"}

    # 3. Register with Cloudflare WARP API
    reg_res = register_cloudflare_account(pub_key, log_func=_log)
    if not reg_res.get("success"):
        return reg_res

    data = reg_res["data"]

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

    device_id = data.get("id", "")
    token = data.get("token", "")

    nodes = _build_amnezia_nodes(
        priv_key=priv_key,
        peer_pub=peer_pub,
        local_addrs=local_addrs,
        device_id=device_id,
        token=token,
        reserved=reserved
    )
    primary_node = nodes[0]

    # Save to disk
    try:
        os.makedirs(settings_dir, exist_ok=True)
        with open(identity_file, "w", encoding="utf-8") as f:
            json.dump({
                "node": primary_node,
                "nodes": nodes,
                "device_id": device_id,
                "token": token,
                "updated_at": int(datetime.datetime.now().timestamp())
            }, f, indent=2)
        os.chmod(identity_file, 0o666)
    except Exception as e:
        _log(f"Failed to persist warp identity: {e}")

    _log("Successfully registered and created Warp Generation nodes")
    return {
        "success": True,
        "node": primary_node,
        "nodes": nodes,
        "cached": False
    }
