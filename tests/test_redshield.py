import unittest
import tempfile
import os
import json
from unittest.mock import patch, MagicMock

from core.redshield import (
    extract_redshield_nodes,
    load_redshield_nodes,
    REDSHIELD_SUB_KEY,
    REDSHIELD_SUB_NAME,
)
from core.singbox_config import build_singbox_config
from vpn_manager import VPNManager


class TestRedShieldIntegration(unittest.TestCase):
    def test_extract_redshield_nodes_from_tmp_or_mock(self):
        nodes = extract_redshield_nodes("/tmp/redshield")
        if nodes:
            # When /tmp/redshield exists with real data
            self.assertGreaterEqual(len(nodes), 40)
            awg_nodes = [n for n in nodes if n.get("type") == "awg"]
            vless_nodes = [n for n in nodes if n.get("type") == "vless"]
            self.assertGreaterEqual(len(awg_nodes), 35)
            self.assertGreaterEqual(len(vless_nodes), 20)

            sample_awg = awg_nodes[0]
            self.assertEqual(sample_awg["subscription_url"], REDSHIELD_SUB_KEY)
            self.assertTrue(sample_awg["private_key"])
            self.assertTrue(sample_awg["public_key"])
            self.assertEqual(sample_awg["jc"], 3)
            self.assertEqual(sample_awg["jmin"], 40)
            self.assertEqual(sample_awg["jmax"], 70)
            self.assertEqual(sample_awg["h1"], "158392-84592014")

            # Verify sing-box config generation for this AWG node
            cfg = build_singbox_config(sample_awg, sample_awg["server"])
            self.assertEqual(len(cfg["endpoints"]), 1)
            ep = cfg["endpoints"][0]
            self.assertEqual(ep["type"], "awg")
            self.assertEqual(ep["jc"], 3)
            self.assertEqual(ep["h1"], "158392-84592014")

    def test_load_redshield_nodes_from_settings(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_nodes = [
                {"name": "Node 1", "type": "awg", "subscription_url": REDSHIELD_SUB_KEY}
            ]
            rs_file = os.path.join(tmp_dir, "redshield_nodes.json")
            with open(rs_file, "w", encoding="utf-8") as f:
                json.dump(test_nodes, f)

            loaded = load_redshield_nodes(tmp_dir)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["name"], "Node 1")

    def test_vpn_manager_parse_redshield_subscription(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_nodes = [
                {"name": "RS AWG", "type": "awg", "server": "1.2.3.4", "port": 55777, "subscription_url": REDSHIELD_SUB_KEY}
            ]
            rs_file = os.path.join(tmp_dir, "redshield_nodes.json")
            with open(rs_file, "w", encoding="utf-8") as f:
                json.dump(test_nodes, f)

            mgr = VPNManager(plugin_dir=tmp_dir, settings_dir=tmp_dir)
            nodes, interval, meta = mgr.parse_subscription(REDSHIELD_SUB_KEY)
            self.assertEqual(len(nodes), 1)
            self.assertEqual(meta.get("name"), REDSHIELD_SUB_NAME)
            self.assertEqual(nodes[0]["name"], "RS AWG")


if __name__ == "__main__":
    unittest.main()
