"""
Unit tests for Amnezia WARP generator and VPNManager integration.
Verifies Cloudflare registration mocking, node construction with AWG/QUIC/SIP
obfuscation parameters, sing-box validation, and settings/node cache persistence.
"""

import os
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from core.warp_generator import (
    generate_warp_identity,
    WARP_ENDPOINT_IPS,
    WARP_PORTS,
    QUIC_I1,
    AWG2_I1,
    SIP_I1,
    SIP_I2,
)
from core.singbox_config import build_singbox_config
from vpn_manager import VPNManager


class TestAmneziaWarpGenerator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.settings_dir = os.path.join(self.temp_dir, "settings")
        self.bin_dir = os.path.join(self.temp_dir, "bin")
        os.makedirs(self.settings_dir, exist_ok=True)
        os.makedirs(self.bin_dir, exist_ok=True)

        # Mock singbox binary path for tests
        self.singbox_path = os.path.join(self.bin_dir, "sing-box")
        with open(self.singbox_path, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(self.singbox_path, 0o755)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("subprocess.check_output")
    @patch("urllib.request.urlopen")
    def test_generate_amnezia_warp_nodes(self, mock_urlopen, mock_subp):
        mock_subp.return_value = (
            b"PrivateKey: YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=\n"
            b"PublicKey: YmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmI=\n"
        )

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "id": "device_12345",
            "token": "token_67890",
            "config": {
                "client_id": "AAAA",
                "peers": [{"public_key": "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="}],
                "interface": {"addresses": {"v4": "172.16.0.2", "v6": "2606:4700:110:8f81::"}}
            }
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = generate_warp_identity(self.bin_dir, self.settings_dir, force=True)
        self.assertTrue(res.get("success"), f"Failed: {res.get('error')}")
        self.assertIn("node", res)
        self.assertIn("nodes", res)

        nodes = res["nodes"]
        self.assertEqual(len(nodes), 3)

        # Check Node 1 (QUIC)
        quic_node = nodes[0]
        self.assertEqual(quic_node["type"], "awg")
        self.assertIn("QUIC", quic_node["name"])
        self.assertEqual(quic_node["jc"], 4)
        self.assertEqual(quic_node["jmin"], 40)
        self.assertEqual(quic_node["jmax"], 70)
        self.assertEqual(quic_node["h1"], "1")
        self.assertEqual(quic_node["i1"], QUIC_I1)
        self.assertEqual(quic_node["subscription_url"], "amnezia_warp")

        # Check Node 2 (AWG 2.0)
        awg_node = nodes[1]
        self.assertEqual(awg_node["type"], "awg")
        self.assertIn("AWG 2.0", awg_node["name"])
        self.assertEqual(awg_node["i1"], AWG2_I1)

        # Check Node 3 (SIP)
        sip_node = nodes[2]
        self.assertEqual(sip_node["type"], "awg")
        self.assertIn("SIP", sip_node["name"])
        self.assertEqual(sip_node["i1"], SIP_I1)
        self.assertEqual(sip_node["i2"], SIP_I2)

        # Check server and port pools
        for n in nodes:
            self.assertIn(n["server"], WARP_ENDPOINT_IPS)
            self.assertIn(n["port"], WARP_PORTS)

        # Test sing-box configuration builder on each node
        for n in nodes:
            cfg = build_singbox_config(n, n["server"])
            self.assertIn("endpoints", cfg)
            ep = cfg["endpoints"][0]
            self.assertEqual(ep["type"], "awg")
            self.assertEqual(ep["jc"], 4)
            self.assertEqual(ep["h1"], "1")
            self.assertEqual(ep["peers"][0]["address"], n["server"])
            self.assertEqual(ep["peers"][0]["port"], n["port"])

    @patch("subprocess.check_output")
    @patch("urllib.request.urlopen")
    def test_caching_behavior(self, mock_urlopen, mock_subp):
        mock_subp.return_value = (
            b"PrivateKey: YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=\n"
            b"PublicKey: YmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmI=\n"
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "id": "device_12345",
            "token": "token_67890",
            "config": {
                "client_id": "AAAA",
                "peers": [{"public_key": "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="}],
                "interface": {"addresses": {"v4": "172.16.0.2"}}
            }
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        # First call: generates new
        res1 = generate_warp_identity(self.bin_dir, self.settings_dir, force=True)
        self.assertFalse(res1.get("cached"))

        # Second call: uses cache
        res2 = generate_warp_identity(self.bin_dir, self.settings_dir, force=False)
        self.assertTrue(res2.get("cached"))
        self.assertEqual(len(res2.get("nodes")), 3)

    @patch("subprocess.check_output")
    @patch("urllib.request.urlopen")
    def test_vpn_manager_warp_integration(self, mock_urlopen, mock_subp):
        mock_subp.return_value = (
            b"PrivateKey: YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=\n"
            b"PublicKey: YmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmI=\n"
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "id": "device_12345",
            "token": "token_67890",
            "config": {
                "client_id": "AAAA",
                "peers": [{"public_key": "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo="}],
                "interface": {"addresses": {"v4": "172.16.0.2"}}
            }
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        mgr = VPNManager(plugin_dir=self.temp_dir, settings_dir=self.settings_dir)
        mgr.bin_dir = self.bin_dir
        res = mgr.generate_warp_node(force=True)
        self.assertTrue(res.get("success"))

        settings = mgr.load_settings()
        self.assertIn("amnezia_warp", settings.get("subscriptions", []))
        self.assertIn("amnezia_warp", settings.get("subscription_metadata", {}))

        nodes = mgr.load_nodes()
        warp_nodes = [n for n in nodes if n.get("subscription_url") == "amnezia_warp"]
        self.assertEqual(len(warp_nodes), 3)


if __name__ == "__main__":
    unittest.main()
