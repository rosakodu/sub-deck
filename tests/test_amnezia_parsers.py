"""
Unit tests for Amnezia VPN, AWG and WireGuard support in sub-deck.
Tests INI .conf parsing, awg:// parsing, vpn:// decoding/decompression,
sing-box awg configuration generation and binaries verification.
"""

import base64
import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

from core.binaries import check_singbox_has_awg, ensure_singbox
from core.constants import PRESET_DEFAULT, PRESET_BYPASS_RU
from core.parsers import (
    parse_wireguard_conf,
    parse_awg_link,
    parse_vpn_link,
    parse_amnezia_vpn_payload,
    parse_amnezia_vpn_link_all,
    parse_node_link,
    parse_subscription_nodes,
)
from core.singbox_config import build_singbox_config
from vpn_manager import VPNManager


SAMPLE_AWG_CONF = """
# AmneziaWG Configuration File
[Interface]
Address = 10.0.0.2/32, fd00::2/128
PrivateKey = aaaaaaaa_client_private_key_base64=
DNS = 1.1.1.1, 8.8.8.8
MTU = 1380
Jc = 4
Jmin = 40
Jmax = 70
S1 = 15
S2 = 25
S3 = 35
S4 = 45
H1 = 111111
H2 = 222222
H3 = 333333
H4 = 444444
I1 = 10
I2 = 20
I3 = 30
I4 = 40
I5 = 50

[Peer]
PublicKey = bbbbbbbb_server_public_key_base64=
PresharedKey = cccccccc_preshared_key_base64=
Endpoint = 198.51.100.10:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""

SAMPLE_MINIMAL_WG_CONF = """
[Interface]
PrivateKey = min_priv_key=
Address = 10.8.0.2/24

[Peer]
PublicKey = min_pub_key=
Endpoint = 203.0.113.5:51820
"""


def make_vpn_url(payload: dict, with_qt_header: bool = True) -> str:
    raw = json.dumps(payload).encode("utf-8")
    compressed = zlib.compress(raw)
    if with_qt_header:
        body = struct.pack(">I", len(raw)) + compressed
    else:
        body = compressed
    b64 = base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")
    return f"vpn://{b64}"


class TestAmneziaParsers(unittest.TestCase):

    def test_parse_wireguard_conf_full_awg(self):
        node = parse_wireguard_conf(SAMPLE_AWG_CONF, name="Custom AWG Node")
        self.assertIsNotNone(node)
        self.assertEqual(node["type"], "awg")
        self.assertEqual(node["name"], "Custom AWG Node")
        self.assertEqual(node["server"], "198.51.100.10")
        self.assertEqual(node["port"], 51820)
        self.assertEqual(node["private_key"], "aaaaaaaa_client_private_key_base64=")
        self.assertEqual(node["public_key"], "bbbbbbbb_server_public_key_base64=")
        self.assertEqual(node["preshared_key"], "cccccccc_preshared_key_base64=")
        self.assertEqual(node["local_address"], ["10.0.0.2/32", "fd00::2/128"])
        self.assertEqual(node["allowed_ips"], ["0.0.0.0/0", "::/0"])
        self.assertEqual(node["mtu"], 1380)
        self.assertEqual(node["jc"], 4)
        self.assertEqual(node["jmin"], 40)
        self.assertEqual(node["jmax"], 70)
        self.assertEqual(node["s1"], 15)
        self.assertEqual(node["s2"], 25)
        self.assertEqual(node["s3"], 35)
        self.assertEqual(node["s4"], 45)
        self.assertEqual(node["h1"], "111111")
        self.assertEqual(node["h2"], "222222")
        self.assertEqual(node["h3"], "333333")
        self.assertEqual(node["h4"], "444444")
        self.assertEqual(node["i1"], "10")
        self.assertEqual(node["i2"], "20")
        self.assertEqual(node["i3"], "30")
        self.assertEqual(node["i4"], "40")
        self.assertEqual(node["i5"], "50")

    def test_parse_wireguard_conf_minimal(self):
        node = parse_wireguard_conf(SAMPLE_MINIMAL_WG_CONF)
        self.assertIsNotNone(node)
        self.assertEqual(node["type"], "awg")
        self.assertEqual(node["server"], "203.0.113.5")
        self.assertEqual(node["port"], 51820)
        self.assertEqual(node["private_key"], "min_priv_key=")
        self.assertEqual(node["public_key"], "min_pub_key=")
        self.assertNotIn("jc", node)

    def test_parse_wireguard_conf_invalid(self):
        # Missing Peer
        invalid_conf = "[Interface]\nPrivateKey=abc\nAddress=10.0.0.1/32"
        self.assertIsNone(parse_wireguard_conf(invalid_conf))
        self.assertIsNone(parse_wireguard_conf(""))

    def test_parse_awg_link_direct(self):
        link = (
            "awg://client_priv_key=@198.51.100.20:51820"
            "?public_key=server_pub_key=&jc=5&jmin=30&jmax=60"
            "&s1=10&s2=20&h1=1&h2=2&h3=3&h4=4#Office%20AWG"
        )
        node = parse_awg_link(link)
        self.assertIsNotNone(node)
        self.assertEqual(node["type"], "awg")
        self.assertEqual(node["name"], "Office AWG")
        self.assertEqual(node["server"], "198.51.100.20")
        self.assertEqual(node["port"], 51820)
        self.assertEqual(node["private_key"], "client_priv_key=")
        self.assertEqual(node["public_key"], "server_pub_key=")
        self.assertEqual(node["jc"], 5)
        self.assertEqual(node["h1"], "1")

    def test_parse_awg_link_query_params(self):
        link = (
            "awg://198.51.100.25:51820"
            "?private_key=priv_key_val=&public_key=pub_key_val=&psk=psk_val="
            "&address=10.0.0.5/32&jc=3#QueryAWG"
        )
        node = parse_awg_link(link)
        self.assertIsNotNone(node)
        self.assertEqual(node["type"], "awg")
        self.assertEqual(node["name"], "QueryAWG")
        self.assertEqual(node["server"], "198.51.100.25")
        self.assertEqual(node["private_key"], "priv_key_val=")
        self.assertEqual(node["public_key"], "pub_key_val=")
        self.assertEqual(node["preshared_key"], "psk_val=")
        self.assertEqual(node["local_address"], ["10.0.0.5/32"])
        self.assertEqual(node["jc"], 3)

    def test_parse_awg_link_base64_conf(self):
        b64 = base64.b64encode(SAMPLE_AWG_CONF.encode("utf-8")).decode("ascii")
        link = f"awg://{b64}#B64Conf"
        node = parse_awg_link(link)
        self.assertIsNotNone(node)
        self.assertEqual(node["type"], "awg")
        self.assertEqual(node["name"], "B64Conf")
        self.assertEqual(node["server"], "198.51.100.10")
        self.assertEqual(node["jc"], 4)

    def test_parse_vpn_link_amnezia_qt_header(self):
        payload = {
            "containers": [
                {
                    "container": "amnezia-awg",
                    "awg": {
                        "last_config": json.dumps({"config": SAMPLE_AWG_CONF})
                    }
                }
            ],
            "defaultContainer": "amnezia-awg",
            "description": "Amnezia Europe",
            "hostName": "198.51.100.10"
        }
        url = make_vpn_url(payload, with_qt_header=True)
        node = parse_vpn_link(url)
        self.assertIsNotNone(node)
        self.assertEqual(node["type"], "awg")
        self.assertIn("Amnezia Europe", node["name"])
        self.assertEqual(node["server"], "198.51.100.10")
        self.assertEqual(node["jc"], 4)
        self.assertEqual(node["s1"], 15)
        self.assertEqual(node["h1"], "111111")

    def test_parse_vpn_link_zlib_scan_0x78(self):
        payload = {
            "containers": [
                {
                    "container": "awg",
                    "awg": {
                        "last_config": SAMPLE_AWG_CONF
                    }
                }
            ],
            "description": "Scan 0x78 Server",
            "hostName": "198.51.100.10"
        }
        # Prepend 7 arbitrary bytes before compressed stream to test 0x78 scan
        raw = json.dumps(payload).encode("utf-8")
        compressed = b"PADDING" + zlib.compress(raw)
        b64 = base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
        url = f"vpn://{b64}"

        node = parse_vpn_link(url)
        self.assertIsNotNone(node)
        self.assertEqual(node["type"], "awg")
        self.assertEqual(node["server"], "198.51.100.10")

    def test_parse_vpn_link_xray_container(self):
        payload = {
            "containers": [
                {
                    "container": "amnezia-xray",
                    "xray": {
                        "last_config": json.dumps({
                            "address": "203.0.113.88",
                            "port": 443,
                            "user_id": "11111111-2222-3333-4444-555555555555",
                            "flow": "xtls-rprx-vision",
                            "security": "reality",
                            "sni": "dl.google.com",
                            "fingerprint": "chrome",
                            "pbk": "test_public_key_reality",
                            "short_id": "1a2b3c4d",
                            "spider_x": "/download"
                        })
                    }
                }
            ],
            "defaultContainer": "amnezia-xray",
            "description": "Xray Server"
        }
        url = make_vpn_url(payload)
        node = parse_vpn_link(url)
        self.assertIsNotNone(node)
        self.assertEqual(node["type"], "vless")
        self.assertEqual(node["server"], "203.0.113.88")
        self.assertEqual(node["port"], 443)
        self.assertEqual(node["uuid"], "11111111-2222-3333-4444-555555555555")
        self.assertEqual(node["security"], "reality")
        self.assertEqual(node["sni"], "dl.google.com")
        self.assertEqual(node["pbk"], "test_public_key_reality")
        self.assertEqual(node["sid"], "1a2b3c4d")
        self.assertEqual(node["spx"], "/download")

    def test_parse_vpn_link_multi_containers(self):
        payload = {
            "containers": [
                {
                    "container": "amnezia-awg",
                    "awg": {
                        "last_config": json.dumps({"config": SAMPLE_AWG_CONF})
                    }
                },
                {
                    "container": "amnezia-xray",
                    "xray": {
                        "last_config": json.dumps({
                            "address": "203.0.113.88",
                            "port": 443,
                            "user_id": "uuid-xray",
                            "security": "reality"
                        })
                    }
                }
            ],
            "defaultContainer": "amnezia-awg",
            "description": "Dual Server"
        }
        url = make_vpn_url(payload)
        nodes = parse_amnezia_vpn_link_all(url)
        self.assertEqual(len(nodes), 2)
        types = [n["type"] for n in nodes]
        self.assertIn("awg", types)
        self.assertIn("vless", types)

        # parse_subscription_nodes should return both
        sub_nodes, _, meta = parse_subscription_nodes(url)
        self.assertEqual(len(sub_nodes), 2)
        self.assertEqual(sub_nodes[0]["subscription_url"], url)

    def test_parse_node_link_dispatch(self):
        # AWG URI
        awg_uri = "awg://client@1.2.3.4:51820?public_key=server&jc=2"
        self.assertEqual(parse_node_link(awg_uri)["type"], "awg")

        # INI direct
        conf_node = parse_node_link(SAMPLE_AWG_CONF)
        self.assertEqual(conf_node["type"], "awg")

        # VPN URI
        payload = {"containers": [{"container": "awg", "awg": {"last_config": SAMPLE_MINIMAL_WG_CONF}}]}
        vpn_uri = make_vpn_url(payload)
        self.assertEqual(parse_node_link(vpn_uri)["type"], "awg")

    def test_build_singbox_awg_config_structure(self):
        valid_priv = base64.b64encode(b"\x01" * 32).decode("ascii")
        valid_pub = base64.b64encode(b"\x02" * 32).decode("ascii")
        valid_psk = base64.b64encode(b"\x03" * 32).decode("ascii")
        node = {
            "type": "awg",
            "name": "AWG Node",
            "server": "198.51.100.50",
            "port": 51820,
            "private_key": valid_priv,
            "public_key": valid_pub,
            "preshared_key": valid_psk,
            "local_address": ["10.0.0.2/32"],
            "allowed_ips": ["0.0.0.0/0", "::/0"],
            "mtu": 1420,
            "jc": 4,
            "jmin": 40,
            "jmax": 70,
            "s1": 15,
            "s2": 25,
            "s3": 35,
            "s4": 45,
            "h1": "10",
            "h2": "20",
            "h3": "30",
            "h4": "40",
            "i1": "1",
            "i2": "2",
            "i3": "3",
            "i4": "4",
            "i5": "5",
        }
        cfg = build_singbox_config(node, "198.51.100.50", preset=PRESET_BYPASS_RU)
        self.assertIn("endpoints", cfg)
        endpoints = cfg["endpoints"]
        self.assertEqual(len(endpoints), 1)

        ep = endpoints[0]
        self.assertEqual(ep["type"], "awg")
        self.assertEqual(ep["tag"], "proxy")
        self.assertEqual(ep["address"], ["10.0.0.2/32"])
        self.assertEqual(ep["private_key"], valid_priv)
        self.assertEqual(ep["mtu"], 1420)

        # Check types of obfuscation parameters
        self.assertIsInstance(ep["jc"], int)
        self.assertIsInstance(ep["jmin"], int)
        self.assertIsInstance(ep["jmax"], int)
        self.assertIsInstance(ep["s1"], int)
        self.assertIsInstance(ep["s2"], int)
        self.assertIsInstance(ep["s3"], int)
        self.assertIsInstance(ep["s4"], int)

        self.assertIsInstance(ep["h1"], str)
        self.assertIsInstance(ep["h2"], str)
        self.assertIsInstance(ep["h3"], str)
        self.assertIsInstance(ep["h4"], str)
        self.assertIsInstance(ep["i1"], str)
        self.assertIsInstance(ep["i2"], str)
        self.assertIsInstance(ep["i3"], str)
        self.assertIsInstance(ep["i4"], str)
        self.assertIsInstance(ep["i5"], str)

        self.assertEqual(ep["jc"], 4)
        self.assertEqual(ep["h1"], "10")

        # Check peers
        self.assertIn("peers", ep)
        peer = ep["peers"][0]
        self.assertEqual(peer["address"], "198.51.100.50")
        self.assertEqual(peer["port"], 51820)
        self.assertEqual(peer["public_key"], valid_pub)
        self.assertEqual(peer["preshared_key"], valid_psk)
        self.assertEqual(peer["allowed_ips"], ["0.0.0.0/0", "::/0"])

        # Check routing rule for proxy
        route_rules = cfg["route"]["rules"]
        has_proxy_route = any(
            r.get("action") == "route" and r.get("outbound") == "proxy"
            for r in route_rules
        )
        self.assertTrue(has_proxy_route)

        # Validate with bundled amnezia sing-box binary if available
        singbox_bin = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "defaults", "bin", "sing-box")
        if os.path.isfile(singbox_bin) and os.access(singbox_bin, os.X_OK):
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                json.dump(cfg, f)
                tmp_cfg = f.name
            try:
                res = subprocess.run([singbox_bin, "check", "-c", tmp_cfg], capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, f"sing-box check failed: {res.stderr}")
            finally:
                if os.path.exists(tmp_cfg):
                    os.remove(tmp_cfg)

    def test_singbox_with_awg_tag_and_ensure(self):
        plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        default_sb = os.path.join(plugin_root, "defaults", "bin", "sing-box")
        if os.path.isfile(default_sb) and os.access(default_sb, os.X_OK):
            # 1. Bundled sing-box must report with_awg tag
            self.assertTrue(check_singbox_has_awg(default_sb))

            # 2. Test ensure_singbox restoration when target binary lacks with_awg
            with tempfile.TemporaryDirectory() as tmp_dir:
                target_sb = os.path.join(tmp_dir, "sing-box")
                # Create dummy binary without with_awg
                with open(target_sb, "w") as f:
                    f.write("#!/bin/sh\necho 'sing-box version 1.0.0 (no awg)'\n")
                os.chmod(target_sb, 0o755)

                self.assertFalse(check_singbox_has_awg(target_sb))
                # ensure_singbox should detect absence of with_awg and overwrite from defaults
                success = ensure_singbox(tmp_dir, target_sb, plugin_dir=plugin_root)
                self.assertTrue(success)
                self.assertTrue(check_singbox_has_awg(target_sb))

    def test_vpn_manager_singbox_awg_protocol_support(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            mgr = VPNManager(plugin_dir=tmp_dir, settings_dir=tmp_dir)
            mgr.bin_dir = tmp_dir
            mgr.singbox_path = os.path.join(tmp_dir, "sing-box")
            mgr.singbox_config_path = os.path.join(tmp_dir, "singbox-config.json")

            node = {
                "type": "awg",
                "name": "AWG Test",
                "server": "198.51.100.99",
                "port": 51820,
                "private_key": "my_priv=",
                "public_key": "my_pub=",
                "local_address": ["10.0.0.2/32"],
                "allowed_ips": ["0.0.0.0/0", "::/0"],
                "jc": 4,
            }

            # generate_config should route type: awg to build_singbox_config and singbox_config_path
            server_ips = mgr.generate_config(node)
            self.assertTrue(os.path.isfile(mgr.singbox_config_path))
            with open(mgr.singbox_config_path, "r", encoding="utf-8") as f:
                sb_cfg = json.load(f)
            self.assertEqual(sb_cfg["endpoints"][0]["type"], "awg")
            self.assertEqual(sb_cfg["endpoints"][0]["jc"], 4)


if __name__ == "__main__":
    unittest.main()
