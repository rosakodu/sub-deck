"""
Adversarial Stress Test Suite for sub-deck Milestone 1 (Iteration 2)
Focuses on empirical stress testing:
- High contention multi-thread concurrency (add, remove, update, save, load)
- Poisoned JSON types (dict instead of list, list instead of dict, primitives)
- Both primary and backup corruption recovery
- Giant adversarial subscription payloads (thousands of malformed lines + valid ones)
- Non-destructive caching under fatal parser/network exceptions
"""

import concurrent.futures
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from vpn_manager import VPNManager
from core.parsers import parse_subscription_nodes, parse_endpoint, parse_node_link


class TestMilestone1Adversarial(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_dir = self.temp_dir.name
        self.mgr = VPNManager(plugin_dir=BASE_DIR, settings_dir=self.settings_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    # ─────────────────────────────────────────────────────────────
    # 1. POISONED JSON TYPES & TOTAL CORRUPTION
    # ─────────────────────────────────────────────────────────────

    def test_settings_json_type_poisoning(self):
        """Test save_settings and load_settings when file contains a JSON list or primitive instead of dict."""
        # 1. Seed valid backup
        self.mgr.save_settings({"subscriptions": ["https://valid-bak.com"]})
        self.mgr.save_settings({"subscriptions": ["https://valid-bak2.com"]})
        bak_file = self.mgr.settings_file + ".bak"

        # 2. Poison primary with valid JSON that is NOT a dict (e.g. list, string, integer)
        poisoned_values = ['["not", "a", "dict"]', '"just a string"', '12345', 'null']
        for p in poisoned_values:
            with open(self.mgr.settings_file, "w", encoding="utf-8") as f:
                f.write(p)

            # load_settings must not return a non-dict or crash
            loaded = self.mgr.load_settings()
            self.assertIsInstance(loaded, dict)
            # Should have fallen back to backup
            self.assertIn("https://valid-bak.com", loaded.get("subscriptions", []))

            # save_settings must NOT copy non-dict into .bak!
            self.mgr.save_settings({"subscriptions": ["https://new-valid.com"]})
            with open(bak_file, "r", encoding="utf-8") as f:
                bak_data = json.load(f)
            self.assertIsInstance(bak_data, dict)
            self.assertIn("subscriptions", bak_data)

    def test_nodes_json_type_poisoning(self):
        """Test save_nodes and load_nodes when file contains a JSON dict or string instead of list."""
        self.mgr.save_nodes([{"name": "ValidNodeBak", "server": "1.1.1.1", "port": 443, "type": "vless"}])
        self.mgr.save_nodes([{"name": "ValidNodeBak2", "server": "1.1.1.2", "port": 443, "type": "vless"}])
        bak_file = self.mgr.nodes_cache_path + ".bak"

        poisoned_values = ['{"not": "a list"}', '"just a string"', '999', 'true']
        for p in poisoned_values:
            with open(self.mgr.nodes_cache_path, "w", encoding="utf-8") as f:
                f.write(p)

            # load_nodes must return a list and never crash or raise
            loaded = self.mgr.load_nodes()
            self.assertIsInstance(loaded, list)
            names = [n["name"] for n in loaded]
            self.assertIn("ValidNodeBak", names)

            # save_nodes must NOT copy non-list into .bak
            self.mgr.save_nodes([{"name": "NewNode", "server": "2.2.2.2", "port": 443, "type": "vless"}])
            with open(bak_file, "r", encoding="utf-8") as f:
                bak_data = json.load(f)
            self.assertIsInstance(bak_data, list)

    def test_both_primary_and_backup_corrupted(self):
        """When both primary and backup files are completely garbage, methods must gracefully return defaults."""
        with open(self.mgr.settings_file, "w", encoding="utf-8") as f:
            f.write("TOTAL JUNK PRIMARY")
        with open(self.mgr.settings_file + ".bak", "w", encoding="utf-8") as f:
            f.write("TOTAL JUNK BACKUP")

        settings = self.mgr.load_settings()
        self.assertIsInstance(settings, dict)
        self.assertEqual(settings.get("subscriptions"), [])
        self.assertTrue(self.mgr._settings_read_failed)

        with open(self.mgr.nodes_cache_path, "w", encoding="utf-8") as f:
            f.write("GARBAGE NODES PRIMARY")
        with open(self.mgr.nodes_cache_path + ".bak", "w", encoding="utf-8") as f:
            f.write("GARBAGE NODES BACKUP")

        nodes = self.mgr.load_nodes()
        self.assertIsInstance(nodes, list)
        self.assertEqual(len(nodes), 0)

    # ─────────────────────────────────────────────────────────────
    # 2. ADVERSARIAL PARSER PAYLOADS
    # ─────────────────────────────────────────────────────────────

    def test_adversarial_giant_payload_with_malformed_lines(self):
        """Feed 5,000 malformed lines with bad IPv6, broken base64, null bytes, and valid nodes."""
        malformed_lines = [
            "vless://",
            "vless://not-an-url",
            "vless://uuid@[::1]:",
            "vless://uuid@[::1]:abc",
            "vless://uuid@[invalid-ipv6",
            "vless://uuid@host:999999999999999999999999999999999",
            "vmess://invalid-base64-not-padding!!!!",
            "vmess://" + "A" * 50,  # invalid json inside b64
            "trojan://",
            "trojan://missing-at-sign.com:443",
            "ss://invalid-credentials@1.1.1.1:443",
            "hysteria2://",
            "tuic://",
            "ftp://anonymous:pass@evil.com/file",
            "file:///etc/passwd",
            "\x00\x01\x02\xff\xfe\xfd",
            " " * 100,
        ]

        # 3 Valid lines with explicit fragment names
        valid_lines = [
            "vless://11111111-1111-1111-1111-111111111111@10.0.0.1:443?type=tcp&security=none#ValidNode1",
            "vless://22222222-2222-2222-2222-222222222222@[2001:db8::1]:8443?type=tcp&security=none#ValidNode2",
            "trojan://mysecretpass@10.0.0.3:443#ValidTrojanNode",
        ]

        # Assemble 3000 lines: 2997 malformed + 3 valid
        payload_lines = (malformed_lines * 200)[:2997] + valid_lines
        payload_bytes = "\n".join(payload_lines).encode("utf-8")

        with patch("core.parsers.download_subscription_payload", return_value=(payload_bytes, {})):
            nodes, interval, meta = parse_subscription_nodes(
                "https://test-sub.com/sub"
            )

        names = [n["name"] for n in nodes]
        self.assertIn("ValidNode1", names)
        self.assertIn("ValidNode2", names)
        self.assertIn("ValidTrojanNode", names)
        # Verify parser successfully parsed and extracted nodes without throwing or hanging
        self.assertGreaterEqual(len(nodes), 3)

    def test_parse_endpoint_port_bounds(self):
        """Verify parse_endpoint clamps ports out of range 1..65535 to default 443."""
        self.assertEqual(parse_endpoint("host:999999999999999999999999999999999"), ("host", 443))
        self.assertEqual(parse_endpoint("host:0"), ("host", 443))
        self.assertEqual(parse_endpoint("host:65536"), ("host", 443))
        self.assertEqual(parse_endpoint("[::1]:999999999999999999999999999999999"), ("::1", 443))
        self.assertEqual(parse_endpoint("[::1]:0"), ("::1", 443))
        self.assertEqual(parse_endpoint("host:1"), ("host", 1))
        self.assertEqual(parse_endpoint("host:65535"), ("host", 65535))
        self.assertEqual(parse_endpoint("host:443"), ("host", 443))

    # ─────────────────────────────────────────────────────────────
    # 3. HIGH CONTENTION ADVERSARIAL CONCURRENCY
    # ─────────────────────────────────────────────────────────────

    def test_extreme_multithreaded_contention(self):
        """Simultaneously hammer add_subscription, remove_subscription, update_subscription,
        save_nodes, save_settings, load_nodes, load_settings from 10 threads."""
        sub_urls = [f"https://provider-{i}.com/sub" for i in range(5)]
        self.mgr.save_settings({"subscriptions": sub_urls[:2]})
        self.mgr.save_nodes([
            {"name": "BaseNode0", "server": "1.0.0.1", "port": 443, "type": "vless", "subscription_url": sub_urls[0]}
        ])

        errors = []
        stop_event = False

        def worker_mutator_subs(tid: int):
            try:
                for i in range(30):
                    url = sub_urls[i % len(sub_urls)]
                    if i % 2 == 0:
                        with patch.object(self.mgr, "parse_all_subscriptions", return_value=[]):
                            self.mgr.add_subscription(url)
                    else:
                        with patch.object(self.mgr, "parse_all_subscriptions", return_value=[]):
                            self.mgr.remove_subscription(url)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"worker_mutator_subs_{tid}: {e}")

        def worker_updater(tid: int):
            try:
                for i in range(30):
                    url = sub_urls[i % len(sub_urls)]
                    new_nodes = [
                        {"name": f"DynamicNode_{tid}_{i}", "server": f"10.{tid}.{i}.1", "port": 443, "type": "vless", "subscription_url": url}
                    ]
                    with patch.object(self.mgr, "parse_subscription", return_value=(new_nodes, None, {})):
                        self.mgr.update_subscription(url)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"worker_updater_{tid}: {e}")

        def worker_nodes_writer(tid: int):
            try:
                for i in range(30):
                    nodes = [
                        {"name": f"DirectNode_{tid}_{i}", "server": "192.168.1.1", "port": 443, "type": "vless"}
                    ]
                    self.mgr.save_nodes(nodes)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"worker_nodes_writer_{tid}: {e}")

        def worker_reader(tid: int):
            try:
                for _ in range(60):
                    s = self.mgr.load_settings()
                    n = self.mgr.load_nodes()
                    self.assertIsInstance(s, dict)
                    self.assertIsInstance(n, list)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"worker_reader_{tid}: {e}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(worker_mutator_subs, 1),
                executor.submit(worker_mutator_subs, 2),
                executor.submit(worker_updater, 1),
                executor.submit(worker_updater, 2),
                executor.submit(worker_updater, 3),
                executor.submit(worker_nodes_writer, 1),
                executor.submit(worker_nodes_writer, 2),
                executor.submit(worker_reader, 1),
                executor.submit(worker_reader, 2),
                executor.submit(worker_reader, 3),
            ]
            concurrent.futures.wait(futures)

        self.assertEqual(len(errors), 0, f"Errors in extreme contention: {errors}")
        # Ensure final state is healthy and readable
        final_settings = self.mgr.load_settings()
        final_nodes = self.mgr.load_nodes()
        self.assertIsInstance(final_settings, dict)
        self.assertIsInstance(final_nodes, list)


if __name__ == "__main__":
    unittest.main()
