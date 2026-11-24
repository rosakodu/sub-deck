import unittest
from unittest.mock import MagicMock, patch

from core.speedtest import (
    country_code_to_flag,
    extract_flag_from_name,
    speedtest_node,
    speedtest_nodes,
)


class TestSpeedtest(unittest.TestCase):
    def test_country_code_to_flag(self):
        self.assertEqual(country_code_to_flag("PL"), "🇵🇱")
        self.assertEqual(country_code_to_flag("de"), "🇩🇪")
        self.assertIsNone(country_code_to_flag(""))
        self.assertIsNone(country_code_to_flag("A"))
        self.assertIsNone(country_code_to_flag("12"))
        self.assertIsNone(country_code_to_flag(None))

    def test_extract_flag_from_name(self):
        self.assertEqual(extract_flag_from_name("🇵🇱 Poland 1"), "🇵🇱")
        self.assertEqual(extract_flag_from_name("Poland 1"), "🇵🇱")
        self.assertEqual(extract_flag_from_name("RedShield | Польша | Game"), "🇵🇱")
        self.assertIsNone(extract_flag_from_name("NoFlagServer"))
        self.assertIsNone(extract_flag_from_name(None))

    @patch("core.speedtest.handshake_ping", return_value=None)
    def test_speedtest_node_unreachable(self, _mock_ping):
        node = {"name": "🇵🇱 PL-1", "server": "1.2.3.4", "port": 443, "type": "vless"}
        res = speedtest_node(node, xray_path="/usr/bin/xray")
        self.assertEqual(res["ping"], -1)
        self.assertIsNone(res["speed_down"])
        self.assertIsNone(res["speed_up"])
        self.assertEqual(res["country_flag"], "🇵🇱")

    @patch("core.speedtest.os.path.exists", return_value=True)
    @patch("core.speedtest._curl_upload_mbps", return_value=10.32)
    @patch("core.speedtest._curl_download_mbps", return_value=12.13)
    @patch("core.speedtest._curl_country_flag", return_value="🇵🇱")
    @patch("core.speedtest._wait_for_port", return_value=True)
    @patch("core.speedtest.subprocess.Popen")
    @patch("core.speedtest.handshake_ping", return_value=90.4)
    def test_speedtest_node_success_and_cleanup(
        self,
        _mock_ping,
        mock_popen,
        _mock_wait,
        _mock_flag,
        _mock_down,
        _mock_up,
        _mock_exists,
    ):
        proc = MagicMock()
        mock_popen.return_value = proc

        node = {
            "name": "Node-1",
            "server": "1.2.3.4",
            "port": 443,
            "type": "vless",
            "uuid": "00000000-0000-0000-0000-000000000000",
        }
        res = speedtest_node(node, xray_path="/usr/bin/xray")

        self.assertEqual(res["ping"], 90)
        self.assertEqual(res["speed_down"], 12.13)
        self.assertEqual(res["speed_up"], 10.32)
        self.assertEqual(res["country_flag"], "🇵🇱")
        proc.terminate.assert_called_once()

    def test_speedtest_nodes_empty(self):
        self.assertEqual(speedtest_nodes([]), [])


if __name__ == "__main__":
    unittest.main()
