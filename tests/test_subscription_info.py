"""
Unit tests for Subscription-Userinfo, Content-Disposition, and atomic metadata handling.
"""

import os
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.parsers import (
    parse_subscription_userinfo,
    parse_content_disposition_filename,
)
from vpn_manager import VPNManager


class TestSubscriptionMetadata(unittest.TestCase):
    def test_parse_subscription_userinfo_standard(self):
        headers = {
            "subscription-userinfo": "upload=1073741824; download=5368709120; total=53687091200; expire=1735689600"
        }
        res = parse_subscription_userinfo(headers)
        self.assertEqual(res.get("upload"), 1073741824)
        self.assertEqual(res.get("download"), 5368709120)
        self.assertEqual(res.get("total"), 53687091200)
        self.assertEqual(res.get("expire"), 1735689600)

    def test_parse_subscription_userinfo_spaces_and_case(self):
        headers = {
            "Subscription-UserInfo": " upload = 2000 ; download = 3000 ; total = 10000; expire = 1800000000 "
        }
        res = parse_subscription_userinfo(headers)
        self.assertEqual(res.get("upload"), 2000)
        self.assertEqual(res.get("download"), 3000)
        self.assertEqual(res.get("total"), 10000)
        self.assertEqual(res.get("expire"), 1800000000)

    def test_parse_subscription_userinfo_empty(self):
        self.assertEqual(parse_subscription_userinfo({}), {})
        self.assertEqual(parse_subscription_userinfo({"content-type": "text/plain"}), {})

    def test_parse_content_disposition_filename_quoted(self):
        headers = {
            "Content-Disposition": 'attachment; filename="My_Vless_Servers.txt"'
        }
        name = parse_content_disposition_filename(headers)
        self.assertEqual(name, "My_Vless_Servers.txt")

    def test_parse_content_disposition_filename_rfc5987_utf8(self):
        headers = {
            "content-disposition": "attachment; filename*=UTF-8''%D0%9C%D0%BE%D1%8F%20%D0%9F%D0%BE%D0%B4%D0%BF%D0%B8%D1%81%D0%BA%D0%B0.txt"
        }
        name = parse_content_disposition_filename(headers)
        self.assertEqual(name, "Моя Подписка.txt")

    def test_atomic_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = VPNManager(plugin_dir=BASE_DIR, settings_dir=tmpdir)
            settings = {
                "subscriptions": ["https://test.local/sub"],
                "subscription_metadata": {
                    "https://test.local/sub": {
                        "name": "Test Sub",
                        "total": 1000,
                        "upload": 100,
                        "download": 200,
                    }
                }
            }
            mgr.save_settings(settings)
            loaded = mgr.load_settings()
            self.assertEqual(loaded["subscription_metadata"]["https://test.local/sub"]["name"], "Test Sub")

            # Verify remove_subscription cleans up metadata
            mgr.remove_subscription("https://test.local/sub")
            loaded_after_rm = mgr.load_settings()
            self.assertNotIn("https://test.local/sub", loaded_after_rm.get("subscription_metadata", {}))


if __name__ == "__main__":
    unittest.main()
