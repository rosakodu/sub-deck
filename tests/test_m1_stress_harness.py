"""
Empirical stress test harness for sub-deck Milestone 1:
1. Simulated power loss: corrupt settings.json / nodes.json with 0 bytes and malformed json -> verify recovery from .bak.
2. Network failure: HTTP 500 / DNS timeout / empty payload during update_subscription -> verify nodes never lost.
3. Concurrency: simultaneous calls to save_nodes, load_nodes, update_subscription across multiple threads.
"""

import concurrent.futures
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock
import urllib.error

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from vpn_manager import VPNManager


class TestMilestone1StressHarness(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_dir = self.temp_dir.name
        self.mgr = VPNManager(plugin_dir=BASE_DIR, settings_dir=self.settings_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    # ─────────────────────────────────────────────────────────────
    # 1. SIMULATED POWER LOSS & CORRUPTION
    # ─────────────────────────────────────────────────────────────

    def test_powerloss_settings_zero_bytes(self):
        """0-byte settings.json simulates sudden crash during write; must recover from .bak."""
        initial = {"subscriptions": ["https://sub1.com"], "selected_preset": "all"}
        self.mgr.save_settings(initial)
        # Second save ensures .bak exists
        updated = {"subscriptions": ["https://sub1.com", "https://sub2.com"], "selected_preset": "all"}
        self.mgr.save_settings(updated)

        # Simulate power loss truncating primary file to 0 bytes
        with open(self.mgr.settings_file, "w") as f:
            f.truncate(0)
        self.assertEqual(os.path.getsize(self.mgr.settings_file), 0)

        recovered = self.mgr.load_settings()
        self.assertIn("https://sub1.com", recovered.get("subscriptions", []))
        self.assertFalse(self.mgr._settings_read_failed)

    def test_powerloss_settings_malformed_json(self):
        """Malformed/truncated JSON in settings.json; must recover from .bak."""
        self.mgr.save_settings({"subscriptions": ["https://good-bak.com"]})
        self.mgr.save_settings({"subscriptions": ["https://good-bak.com", "https://good2.com"]})

        # Overwrite with broken partial JSON (interrupted write)
        with open(self.mgr.settings_file, "wb") as f:
            f.write(b'{"subscriptions": ["https://goo\x00\xff\xfe')

        recovered = self.mgr.load_settings()
        self.assertEqual(recovered.get("subscriptions"), ["https://good-bak.com"])
        self.assertFalse(self.mgr._settings_read_failed)

    def test_corrupted_primary_backup_pollution_on_save(self):
        """If primary is corrupt and .bak is valid, save_settings must not pollute .bak with corrupt primary."""
        # Step 1: Create good backup
        self.mgr.save_settings({"subscriptions": ["https://good-v1.com"]})
        self.mgr.save_settings({"subscriptions": ["https://good-v2.com"]})
        bak_file = self.mgr.settings_file + ".bak"

        # Step 2: Corrupt primary file with broken JSON (size > 0)
        with open(self.mgr.settings_file, "w") as f:
            f.write("corrupted json content")

        # Step 3: Call save_settings with v3
        self.mgr.save_settings({"subscriptions": ["https://good-v3.com"]})

        # Step 4: Check what is in bak_file now
        with open(bak_file, "r") as f:
            bak_content = f.read()

        # The backup should NEVER be corrupted JSON!
        try:
            bak_json = json.loads(bak_content)
            self.assertIn("subscriptions", bak_json)
        except json.JSONDecodeError:
            self.fail(f"Backup file was polluted with corrupted primary file! Content: {bak_content}")

    def test_powerloss_nodes_zero_bytes(self):
        """0-byte nodes.json simulates crash; must recover from .bak."""
        nodes1 = [{"name": "Node A", "server": "1.1.1.1", "port": 443, "type": "vless"}]
        nodes2 = [{"name": "Node B", "server": "2.2.2.2", "port": 443, "type": "vless"}]
        self.mgr.save_nodes(nodes1)
        self.mgr.save_nodes(nodes2)

        # Truncate to 0 bytes
        with open(self.mgr.nodes_cache_path, "w") as f:
            f.truncate(0)

        recovered = self.mgr.load_nodes()
        names = [n["name"] for n in recovered if n.get("type") != "auto_balancer"]
        self.assertIn("Node A", names)

    def test_powerloss_nodes_malformed_json(self):
        """Garbage/corrupt JSON in nodes.json; must recover from .bak."""
        nodes1 = [{"name": "Valid Backup Node", "server": "1.1.1.1", "port": 443, "type": "vless"}]
        self.mgr.save_nodes(nodes1)
        self.mgr.save_nodes([{"name": "Node 2", "server": "2.2.2.2", "port": 443, "type": "vless"}])

        with open(self.mgr.nodes_cache_path, "w") as f:
            f.write("[{corrupt json node garbage!#$@%")

        recovered = self.mgr.load_nodes()
        names = [n["name"] for n in recovered if n.get("type") != "auto_balancer"]
        self.assertIn("Valid Backup Node", names)

    def test_corrupted_primary_nodes_backup_pollution_on_save(self):
        """If nodes.json is corrupt and .bak is valid, save_nodes must not overwrite .bak with garbage."""
        self.mgr.save_nodes([{"name": "GoodNodeV1", "server": "1.1.1.1", "port": 443, "type": "vless"}])
        self.mgr.save_nodes([{"name": "GoodNodeV2", "server": "2.2.2.2", "port": 443, "type": "vless"}])
        bak_file = self.mgr.nodes_cache_path + ".bak"

        # Corrupt primary nodes file
        with open(self.mgr.nodes_cache_path, "w") as f:
            f.write("[{broken nodes json content")

        # Save new nodes
        self.mgr.save_nodes([{"name": "GoodNodeV3", "server": "3.3.3.3", "port": 443, "type": "vless"}])

        with open(bak_file, "r") as f:
            bak_content = f.read()

        try:
            bak_json = json.loads(bak_content)
            self.assertIsInstance(bak_json, list)
        except json.JSONDecodeError:
            self.fail(f"Nodes backup was polluted with corrupted primary file! Content: {bak_content}")

    # ─────────────────────────────────────────────────────────────
    # 2. NETWORK FAILURES (HTTP 500, DNS TIMEOUT, EMPTY PAYLOAD)
    # ─────────────────────────────────────────────────────────────

    def test_network_failures_during_update_subscription(self):
        """Verify existing nodes are never wiped under HTTP 500, DNS timeout, or socket error."""
        sub_url = "https://provider.com/sub"
        initial_nodes = [
            {"name": "Live Server 1", "server": "10.0.0.1", "port": 443, "type": "vless", "subscription_url": sub_url},
            {"name": "Live Server 2", "server": "10.0.0.2", "port": 443, "type": "vless", "subscription_url": sub_url},
            {"name": "Other Sub Server", "server": "10.0.0.3", "port": 443, "type": "vless", "subscription_url": "https://other.com/sub"}
        ]
        self.mgr.save_nodes(initial_nodes)

        failure_scenarios = [
            ("HTTP 500 Internal Error", urllib.error.HTTPError(sub_url, 500, "Internal Server Error", {}, None)),
            ("DNS Lookup Failure", urllib.error.URLError("Name or service not known")),
            ("Connection Timeout", TimeoutError("Connection timed out")),
            ("Empty Payload / Blocked", None),
        ]

        for desc, err in failure_scenarios:
            with self.subTest(scenario=desc):
                if err:
                    with patch("urllib.request.urlopen", side_effect=err):
                        res = self.mgr.update_subscription(sub_url)
                else:
                    with patch("core.parsers.download_subscription_payload", return_value=(b"", {})):
                        res = self.mgr.update_subscription(sub_url)

                # Nodes belonging to sub_url must STILL be present
                retained = [n for n in res if n.get("subscription_url") == sub_url]
                self.assertEqual(len(retained), 2, f"Failed scenario: {desc}")
                names = [n["name"] for n in retained]
                self.assertIn("Live Server 1", names)
                self.assertIn("Live Server 2", names)

                # Disk cache check
                disk_nodes = self.mgr.load_nodes()
                disk_retained = [n for n in disk_nodes if n.get("subscription_url") == sub_url]
                self.assertEqual(len(disk_retained), 2, f"Disk check failed for scenario: {desc}")

    # ─────────────────────────────────────────────────────────────
    # 3. CONCURRENT READS AND WRITES
    # ─────────────────────────────────────────────────────────────

    def test_concurrent_save_nodes_and_update_subscription(self):
        """Stress-test concurrent calls to save_nodes, load_nodes, and update_subscription."""
        sub_a = "https://sub-a.com/sub"
        sub_b = "https://sub-b.com/sub"
        initial_nodes = [
            {"name": "Node A0", "server": "1.1.1.1", "port": 443, "type": "vless", "subscription_url": sub_a},
            {"name": "Node B0", "server": "2.2.2.2", "port": 443, "type": "vless", "subscription_url": sub_b},
        ]
        self.mgr.save_nodes(initial_nodes)
        self.mgr.save_settings({"subscriptions": [sub_a, sub_b]})

        errors = []

        def worker_save_nodes(worker_id: int):
            try:
                for i in range(25):
                    nodes = [
                        {"name": f"WorkerNode_{worker_id}_{i}", "server": "3.3.3.3", "port": 443, "type": "vless", "subscription_url": sub_a}
                    ]
                    self.mgr.save_nodes(nodes)
                    time.sleep(0.002)
            except Exception as e:
                errors.append(f"worker_save_nodes_{worker_id}: {e}")

        def worker_update_sub(worker_id: int):
            try:
                for i in range(25):
                    # Simulate intermittent network success/fail
                    if i % 2 == 0:
                        new_node = [{"name": f"SubB_Node_{worker_id}_{i}", "server": "4.4.4.4", "port": 443, "type": "vless", "subscription_url": sub_b}]
                        with patch.object(self.mgr, "parse_subscription", return_value=(new_node, None, {})):
                            self.mgr.update_subscription(sub_b)
                    else:
                        with patch.object(self.mgr, "parse_subscription", return_value=([], None, {})):
                            self.mgr.update_subscription(sub_b)
                    time.sleep(0.002)
            except Exception as e:
                errors.append(f"worker_update_sub_{worker_id}: {e}")

        def worker_reader(worker_id: int):
            try:
                for _ in range(50):
                    nodes = self.mgr.load_nodes()
                    settings = self.mgr.load_settings()
                    # Ensure reader never gets empty/None or half-written corrupted files
                    self.assertIsInstance(nodes, list)
                    self.assertIsInstance(settings, dict)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"worker_reader_{worker_id}: {e}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(worker_save_nodes, 1),
                executor.submit(worker_save_nodes, 2),
                executor.submit(worker_update_sub, 1),
                executor.submit(worker_update_sub, 2),
                executor.submit(worker_reader, 1),
                executor.submit(worker_reader, 2),
                executor.submit(worker_reader, 3),
                executor.submit(worker_reader, 4),
            ]
            concurrent.futures.wait(futures)

        self.assertEqual(len(errors), 0, f"Concurrency errors occurred: {errors}")

    def test_concurrent_update_subscription_race(self):
        """Test race conditions when two different subscriptions are updated concurrently."""
        sub_a = "https://sub-a.com/sub"
        sub_b = "https://sub-b.com/sub"
        
        # Initial state: 1 node for sub_a, 1 node for sub_b
        self.mgr.save_nodes([
            {"name": "Node A0", "server": "1.1.1.1", "port": 443, "type": "vless", "subscription_url": sub_a},
            {"name": "Node B0", "server": "2.2.2.2", "port": 443, "type": "vless", "subscription_url": sub_b},
        ])
        self.mgr.save_settings({"subscriptions": [sub_a, sub_b]})

        new_a = [{"name": "Node A_NEW", "server": "10.1.1.1", "port": 443, "type": "vless", "subscription_url": sub_a}]
        new_b = [{"name": "Node B_NEW", "server": "10.2.2.2", "port": 443, "type": "vless", "subscription_url": sub_b}]

        def delayed_parse(url):
            time.sleep(0.01)  # Expand race window
            if url == sub_a:
                return new_a, None, {}
            return new_b, None, {}

        with patch.object(self.mgr, "parse_subscription", side_effect=delayed_parse):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                f1 = executor.submit(self.mgr.update_subscription, sub_a)
                f2 = executor.submit(self.mgr.update_subscription, sub_b)
                concurrent.futures.wait([f1, f2])

        final_nodes = self.mgr.load_nodes()
        names = [n["name"] for n in final_nodes if n.get("type") != "auto_balancer"]
        
        # In a race condition without locks, one update clobbers the other!
        # Both Node A_NEW and Node B_NEW should be present!
        self.assertIn("Node A_NEW", names, f"Node A_NEW was clobbered! Nodes: {names}")
        self.assertIn("Node B_NEW", names, f"Node B_NEW was clobbered! Nodes: {names}")


if __name__ == "__main__":
    unittest.main()
