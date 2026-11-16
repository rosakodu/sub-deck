"""
Red Shield VPN node extractor and loader for sub-deck.
Extracts AWG (AmneziaWG) and VLESS Reality nodes from Red Shield app data.
"""

import os
import json
import sqlite3
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional

from core.parsers import parse_wireguard_conf, parse_vless_link

REDSHIELD_SUB_KEY = "redshield_vpn"
REDSHIELD_SUB_NAME = "🛡️ Red Shield VPN"

FLAG_MAP = {
    "LT": "🇱🇹", "LV": "🇱🇻", "FIN": "🇫🇮", "AMS": "🇳🇱", "STM": "🇸🇪",
    "PRA": "🇨🇿", "FR": "🇫🇷", "IT": "🇮🇹", "FRA": "🇩🇪", "PO": "🇵🇱",
    "AU": "🇦🇹", "BU": "🇭🇺", "RS": "🇷🇸", "SW": "🇨🇭", "LON": "🇬🇧",
    "TR": "🇹🇷", "CY": "🇨🇾", "ES": "🇪🇸", "IL": "🇮🇱", "AG": "🇦🇷",
    "PT": "🇵🇹", "AE": "🇦🇪", "CA": "🇨🇦", "NY": "🇺🇸", "HK": "🇭🇰",
    "JP": "🇯🇵", "TH": "🇹🇭", "LA": "🇺🇸", "BR": "🇧🇷", "SG": "🇸🇬",
    "RU": "🇷🇺", "GE": "🇬🇪", "KZ": "🇰🇿", "RB": "🇧🇾", "UA": "🇺🇦",
    "AM": "🇦🇲", "UZ": "🇺🇿",
    "PZ-WL1": "🏴‍☠️", "PZ-WL2": "🏴‍☠️", "PZ-WL3": "🏴‍☠️", "PZ-WL5": "🏴‍☠️",
}


def extract_redshield_nodes(source_dir: str = "/tmp/redshield") -> List[Dict[str, Any]]:
    """Extracts all AWG and VLESS Reality nodes from Red Shield app data directory."""
    xml_path = os.path.join(source_dir, "appPreference.xml")
    db_path = os.path.join(source_dir, "rsv_data")

    if not os.path.exists(xml_path) or not os.path.exists(db_path):
        return []

    # 1. Parse appPreference.xml
    tree = ET.parse(xml_path)
    prefs = {}
    for elem in tree.getroot():
        prefs[elem.attrib.get("name")] = elem.text or elem.attrib.get("value", "")

    awg_tpl = prefs.get("awg_template", "")
    rec_awg_port = int(prefs.get("rec_awg_port", 55777))

    # 2. Parse SQLite database
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cols = [c[1] for c in cur.execute("PRAGMA table_info(Location);").fetchall()]
    locations = [dict(zip(cols, r)) for r in cur.execute("SELECT * FROM Location").fetchall()]
    conn.close()

    nodes: List[Dict[str, Any]] = []

    # 3. Extract AWG nodes
    if awg_tpl:
        for loc in locations:
            code = loc.get("code")
            flag = FLAG_MAP.get(code, "🌐")
            name_ru = loc.get("nameRu") or loc.get("name", code)
            hosts = loc.get("hosts")
            awg_ip = loc.get("awgIp") or hosts

            # For whitelist nodes (PZ-WL1, PZ-WL2), generate active DB port 3479 and 55777
            if str(code).startswith("PZ-WL"):
                if loc.get("protoPriorities") == "awg" or loc.get("shadowAwg") == 1:
                    for p in (3479, 55777):
                        conf = awg_tpl.replace("{ENDPOINT}", f"{awg_ip}:{p}")
                        node_name = f"{flag} RedShield | {name_ru} (AWG:{p})"
                        node = parse_wireguard_conf(conf, name=node_name)
                        if node:
                            node["subscription_url"] = REDSHIELD_SUB_KEY
                            nodes.append(node)
            else:
                forced_port = loc.get("forcedAwgPort")
                port = int(forced_port) if forced_port else rec_awg_port
                conf = awg_tpl.replace("{ENDPOINT}", f"{awg_ip}:{port}")
                node_name = f"{flag} RedShield | {name_ru} (AWG)"
                node = parse_wireguard_conf(conf, name=node_name)
                if node:
                    node["subscription_url"] = REDSHIELD_SUB_KEY
                    nodes.append(node)

    # 4. Extract VLESS Reality nodes
    for loc in locations:
        code = loc.get("code")
        flag = FLAG_MAP.get(code, "🌐")
        name_ru = loc.get("nameRu") or loc.get("name", code)
        xray_ip = loc.get("xrayIp") or (loc.get("hosts") if loc.get("xraySni") or str(code).startswith("PZ-WL") else None)
        xray_port = loc.get("xrayPort") or 443
        xray_sni = loc.get("xraySni") or "node44.lmdscdn.ru"
        if xray_ip:
            node_name = f"{flag} RedShield | {name_ru} (VLESS)"
            link = (
                f"vless://658de489-4568-4e55-b4a6-cfb9169e7198@{xray_ip}:{xray_port}"
                f"?security=reality&encryption=none&pbk=PVlnR_I9tZ8hKhOHW6ySpSofhsaShcBQ_JV2-0TePVA"
                f"&sid=901945f2519a4fbe&sni={xray_sni}&fp=firefox&type=grpc&serviceName=livestreamcontent"
                f"#{node_name}"
            )
            v_node = parse_vless_link(link)
            if v_node:
                v_node["subscription_url"] = REDSHIELD_SUB_KEY
                v_node["dns"] = ["10.254.254.254"]
                nodes.append(v_node)

    return nodes


def load_redshield_nodes(settings_dir: str, plugin_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Loads Red Shield nodes from settings or defaults, fallback to /tmp/redshield extraction."""
    # 1. Check settings_dir
    target_file = os.path.join(settings_dir, "redshield_nodes.json")
    if os.path.exists(target_file):
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                nodes = json.load(f)
                if isinstance(nodes, list) and nodes:
                    return nodes
        except Exception:
            pass

    # 2. Check plugin defaults
    if plugin_dir:
        def_file = os.path.join(plugin_dir, "defaults", "redshield_nodes.json")
        if os.path.exists(def_file):
            try:
                with open(def_file, "r", encoding="utf-8") as f:
                    nodes = json.load(f)
                    if isinstance(nodes, list) and nodes:
                        return nodes
            except Exception:
                pass

    # 3. Fallback to /tmp/redshield
    if os.path.exists("/tmp/redshield/rsv_data"):
        nodes = extract_redshield_nodes("/tmp/redshield")
        if nodes:
            try:
                os.makedirs(settings_dir, exist_ok=True)
                with open(target_file, "w", encoding="utf-8") as f:
                    json.dump(nodes, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
            return nodes

    return []
