"""
Unit tests for Subscription & Settings Persistence (Milestone 1).
Tests:
- Non-destructive caching in update_subscription & parse_all_subscriptions
- Empty list save_nodes guard (force=False vs force=True)
- Atomic persistence with fsync, .bak creation, and fallback on corruption
- Single direct node URL parsing without urlopen
- Proxy fallback in download_subscription_payload
- Settings directory resolution and migration
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.parsers import (
    parse_subscription_nodes,
    download_subscription_payload,
    is_proxy_reachable,
    parse_endpoint,
    parse_vless_link,
    parse_node_link,
)
from vpn_manager import VPNManager
from main import resolve_and_migrate_settings_dir, Plugin


class TestSubscriptionPersistence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_dir = self.temp_dir.name
        self.mgr = VPNManager(plugin_dir=BASE_DIR, settings_dir=self.settings_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_single_node_url_parsing_no_urlopen(self):
        """Single node URLs (vless://, vmess://, etc.) must be parsed directly without calling urlopen."""
        vless_link = "vless://b831381d-6324-4d53-ad4f-8cda48b30811@example.com:443?security=reality&sni=test.com#TestServer"
        
        with patch("urllib.request.urlopen") as mock_urlopen:
            nodes, interval, meta = parse_subscription_nodes(vless_link)
            self.assertEqual(mock_urlopen.call_count, 0)
            self.assertEqual(len(nodes), 1)
            self.assertEqual(nodes[0]["server"], "example.com")
            self.assertEqual(nodes[0]["port"], 443)
            self.assertEqual(nodes[0]["subscription_url"], vless_link)
            self.assertEqual(meta.get("name"), "TestServer")

    def test_download_subscription_proxy_fallback(self):
        """When direct download fails and 127.0.0.1:10808 is reachable, retry via proxy."""
        url = "https://example.com/sub.txt"

        # 1. Direct fails, proxy is reachable, proxy download succeeds
        with patch("urllib.request.urlopen", side_effect=Exception("Direct blocked")), \
             patch("core.parsers.is_proxy_reachable", return_value=True), \
             patch("urllib.request.build_opener") as mock_build_opener:

            mock_opener = MagicMock()
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"vless://uuid@host:443#Node1\n"
            mock_resp.info.return_value = {"Content-Type": "text/plain"}
            mock_opener.open.return_value.__enter__.return_value = mock_resp
            mock_build_opener.return_value = mock_opener

            content, headers = download_subscription_payload(url)
            self.assertIsNotNone(content)
            self.assertIn(b"vless://", content)

        # 2. When proxy is not reachable, returns None, None
        with patch("urllib.request.urlopen", side_effect=Exception("Direct blocked")), \
             patch("core.parsers.is_proxy_reachable", return_value=False):
            content, headers = download_subscription_payload(url)
            self.assertIsNone(content)
            self.assertIsNone(headers)

    def test_non_destructive_node_caching_on_update_failure(self):
        """If update_subscription returns 0 nodes (network failure), old cached nodes are NOT wiped."""
        sub_url = "https://blocked.example.com/sub"
        initial_nodes = [
            {"name": "Valid Server 1", "server": "1.1.1.1", "port": 443, "type": "vless", "subscription_url": sub_url},
            {"name": "Other Sub Server", "server": "2.2.2.2", "port": 443, "type": "vless", "subscription_url": "https://other.com/sub"},
        ]
        self.mgr.save_nodes(initial_nodes)

        # Simulate update_subscription returning empty due to network timeout or blocking
        with patch.object(self.mgr, "parse_subscription", return_value=([], None, {})):
            updated = self.mgr.update_subscription(sub_url)
            
            # The result must retain the existing nodes for sub_url
            retained = [n for n in updated if n.get("subscription_url") == sub_url]
            self.assertEqual(len(retained), 1)
            self.assertEqual(retained[0]["name"], "Valid Server 1")

            # Check nodes on disk
            disk_nodes = self.mgr.load_nodes()
            disk_sub_nodes = [n for n in disk_nodes if n.get("subscription_url") == sub_url]
            self.assertEqual(len(disk_sub_nodes), 1)

    def test_parse_all_subscriptions_preserves_cached_nodes_on_failure(self):
        """parse_all_subscriptions must retain cached nodes for URLs that fail to update."""
        url1 = "https://failing.com/sub"
        url2 = "https://working.com/sub"
        self.mgr.save_settings({"subscriptions": [url1, url2]})

        cached_nodes = [
            {"name": "Node 1", "server": "1.1.1.1", "port": 443, "type": "vless", "subscription_url": url1},
            {"name": "Old Node 2", "server": "2.2.2.2", "port": 443, "type": "vless", "subscription_url": url2},
        ]
        self.mgr.save_nodes(cached_nodes)

        new_node_2 = {"name": "New Node 2", "server": "3.3.3.3", "port": 443, "type": "vless", "subscription_url": url2}

        def mock_parse(url):
            if url == url1:
                return [], None, {}
            return [new_node_2], None, {}

        with patch.object(self.mgr, "parse_subscription", side_effect=mock_parse):
            all_nodes = self.mgr.parse_all_subscriptions()

            # Node 1 was preserved from cache, Node 2 was updated
            names = [n["name"] for n in all_nodes if n.get("type") != "auto_balancer"]
            self.assertIn("Node 1", names)
            self.assertIn("New Node 2", names)
            self.assertNotIn("Old Node 2", names)

    def test_save_nodes_empty_guard(self):
        """save_nodes must never overwrite existing nodes with empty list unless force=True."""
        initial = [{"name": "Node 1", "server": "1.1.1.1", "port": 443, "type": "vless"}]
        self.mgr.save_nodes(initial)

        # Attempt to save empty without force
        self.mgr.save_nodes([], force=False)
        self.assertEqual(len(self.mgr.load_nodes()), 1)

        # Attempt to save empty with force=True
        self.mgr.save_nodes([], force=True)
        self.assertEqual(len(self.mgr.load_nodes()), 0)

    def test_save_settings_and_nodes_fsync_and_backup(self):
        """save_settings and save_nodes must use fsync and create .bak copies."""
        with patch("os.fsync") as mock_fsync:
            # 1. First save
            self.mgr.save_settings({"subscriptions": ["https://sub1.com"]})
            self.assertTrue(mock_fsync.called)

            # 2. Second save creates .bak
            self.mgr.save_settings({"subscriptions": ["https://sub1.com", "https://sub2.com"]})
            bak_file = self.mgr.settings_file + ".bak"
            self.assertTrue(os.path.exists(bak_file))
            with open(bak_file, "r", encoding="utf-8") as f:
                bak_content = json.load(f)
            self.assertEqual(bak_content["subscriptions"], ["https://sub1.com"])

            # 3. Nodes save and .bak
            self.mgr.save_nodes([{"name": "N1", "server": "1.1.1.1", "port": 443, "type": "vless"}])
            self.mgr.save_nodes([{"name": "N2", "server": "2.2.2.2", "port": 443, "type": "vless"}])
            nodes_bak = self.mgr.nodes_cache_path + ".bak"
            self.assertTrue(os.path.exists(nodes_bak))
            with open(nodes_bak, "r", encoding="utf-8") as f:
                nodes_bak_content = json.load(f)
            self.assertEqual(len(nodes_bak_content), 1)
            self.assertEqual(nodes_bak_content[0]["name"], "N1")

    def test_corrupt_settings_and_nodes_fallback_to_bak(self):
        """If primary settings.json or nodes.json is corrupt or 0 bytes, load from .bak."""
        # Setup settings and .bak
        valid_settings = {"subscriptions": ["https://recovered.com"]}
        self.mgr.save_settings(valid_settings)
        self.mgr.save_settings({"subscriptions": ["https://primary.com"]})

        # Corrupt primary settings.json
        with open(self.mgr.settings_file, "w") as f:
            f.write("{corrupt json !!!")

        loaded_settings = self.mgr.load_settings()
        self.assertEqual(loaded_settings.get("subscriptions"), ["https://recovered.com"])
        self.assertFalse(self.mgr._settings_read_failed)

        # Setup nodes and .bak
        self.mgr.save_nodes([{"name": "BakNode", "server": "1.1.1.1", "port": 443, "type": "vless"}])
        self.mgr.save_nodes([{"name": "PrimaryNode", "server": "2.2.2.2", "port": 443, "type": "vless"}])

        # Truncate primary nodes.json to 0 bytes
        with open(self.mgr.nodes_cache_path, "w") as f:
            f.truncate(0)

        loaded_nodes = self.mgr.load_nodes()
        names = [n["name"] for n in loaded_nodes if n.get("type") != "auto_balancer"]
        self.assertIn("BakNode", names)

    def test_startup_guard_prevents_overwriting_corrupted_settings(self):
        """Plugin startup must not overwrite corrupt settings.json with empty defaults."""
        # Create corrupted settings with no backup
        with open(self.mgr.settings_file, "w") as f:
            f.write("{bad json")

        settings = self.mgr.load_settings()
        self.assertTrue(self.mgr._settings_read_failed)

        # Simulate main.py startup check
        if not getattr(self.mgr, "_settings_read_failed", False):
            settings["desktop_tray_enabled"] = True
            self.mgr.save_settings(settings)

        # Primary file must remain untouched with the corrupt content for recovery
        with open(self.mgr.settings_file, "r") as f:
            content = f.read()
        self.assertEqual(content, "{bad json")

    def test_dual_persistence_sync_and_fallback(self):
        """Dual-persistence must write to both directories and recover if one is deleted."""
        with tempfile.TemporaryDirectory() as primary_dir, tempfile.TemporaryDirectory() as fallback_dir:
            mgr = VPNManager(
                plugin_dir=BASE_DIR,
                settings_dir=primary_dir,
                fallback_settings_dir=fallback_dir
            )

            # Save settings and nodes
            mgr.save_settings({"subscriptions": ["https://dual.com"], "desktop_tray_enabled": True})
            mgr.save_nodes([{"name": "DualNode", "server": "1.1.1.1", "port": 443, "type": "vless"}])

            # Verify both locations have the files
            self.assertTrue(os.path.exists(os.path.join(primary_dir, "settings.json")))
            self.assertTrue(os.path.exists(os.path.join(fallback_dir, "settings.json")))
            self.assertTrue(os.path.exists(os.path.join(primary_dir, "nodes.json")))
            self.assertTrue(os.path.exists(os.path.join(fallback_dir, "nodes.json")))

            # Delete primary files completely (simulate Decky reset)
            os.remove(os.path.join(primary_dir, "settings.json"))
            os.remove(os.path.join(primary_dir, "nodes.json"))

            # Load should recover from fallback
            loaded_settings = mgr.load_settings()
            self.assertEqual(loaded_settings.get("subscriptions"), ["https://dual.com"])
            loaded_nodes = mgr.load_nodes()
            names = [n["name"] for n in loaded_nodes]
            self.assertIn("DualNode", names)

            # And primary files should be re-created during sync recovery
            self.assertTrue(os.path.exists(os.path.join(primary_dir, "settings.json")))
            self.assertTrue(os.path.exists(os.path.join(primary_dir, "nodes.json")))

    def test_settings_dir_resolution_and_migration(self):
        """resolve_and_migrate_settings_dir must copy legacy ~/.config/sub-deck files to target."""
        with tempfile.TemporaryDirectory() as fake_home, tempfile.TemporaryDirectory() as target_dir:
            legacy_config_dir = os.path.join(fake_home, ".config", "sub-deck")
            os.makedirs(legacy_config_dir, exist_ok=True)

            legacy_settings = os.path.join(legacy_config_dir, "settings.json")
            with open(legacy_settings, "w") as f:
                json.dump({"subscriptions": ["https://migrated.com"]}, f)

            with patch("main.get_user_home", return_value=fake_home), \
                 patch.dict(os.environ, {"DECKY_PLUGIN_SETTINGS_DIR": target_dir}):
                resolved = resolve_and_migrate_settings_dir()
                self.assertEqual(resolved, target_dir)

                migrated_file = os.path.join(target_dir, "settings.json")
                self.assertTrue(os.path.exists(migrated_file))
                with open(migrated_file, "r") as f:
                    data = json.load(f)
                self.assertEqual(data["subscriptions"], ["https://migrated.com"])

    def test_endpoint_ipv6_port_robustness(self):
        """parse_endpoint with IPv6 bracket notation handles missing/invalid ports safely."""
        host, port = parse_endpoint("[::1]:")
        self.assertEqual(host, "::1")
        self.assertEqual(port, 443)

        host, port = parse_endpoint("[::1]:invalid")
        self.assertEqual(host, "::1")
        self.assertEqual(port, 443)

        host, port = parse_endpoint("[2001:db8::1]:8443")
        self.assertEqual(host, "2001:db8::1")
        self.assertEqual(port, 8443)

    def test_vless_parsing_and_decode_loop_exception_protection(self):
        """Malformed VLESS links or unparseable lines do not raise or abort parsing."""
        # Malformed vless URI without valid structure returns None without exception
        self.assertIsNone(parse_vless_link("vless://invalid_no_netloc"))
        self.assertIsNone(parse_vless_link("vless://"))

        # Valid IPv6 VLESS link with empty port defaults to 443
        node = parse_node_link("vless://b831381d-6324-4d53-ad4f-8cda48b30811@[::1]:?security=reality#TestIPv6")
        self.assertIsNotNone(node)
        self.assertEqual(node["server"], "::1")
        self.assertEqual(node["port"], 443)

        # Multi-line subscription with a corrupted line in between valid lines
        lines_payload = (
            "vless://uuid-1@1.1.1.1:443#GoodNode1\n"
            "garbage_unparseable_line_here\n"
            "vless://uuid-2@2.2.2.2:443#GoodNode2\n"
        )
        with patch("core.parsers.download_subscription_payload", return_value=(lines_payload.encode(), {})):
            nodes, interval, meta = parse_subscription_nodes("https://example.com/mixed-sub")
            names = [n["name"] for n in nodes]
            self.assertIn("GoodNode1", names)
            self.assertIn("GoodNode2", names)
            self.assertEqual(len(nodes), 2)

    def test_update_subscription_exception_handling(self):
        """update_subscription handles exceptions in parse_subscription gracefully and preserves cache."""
        sub_url = "https://broken-sub.com/sub"
        self.mgr.save_nodes([{"name": "PreservedNode", "server": "1.1.1.1", "port": 443, "type": "vless", "subscription_url": sub_url}])

        with patch.object(self.mgr, "parse_subscription", side_effect=ValueError("Unexpected parser failure")):
            updated = self.mgr.update_subscription(sub_url)
            names = [n["name"] for n in updated if n.get("type") != "auto_balancer"]
            self.assertIn("PreservedNode", names)


if __name__ == "__main__":
    unittest.main()
