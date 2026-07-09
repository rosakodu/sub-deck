# sub-deck

[English](README.md) | [Русский](README.ru.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md) | [العربية](README.ar.md) | [فارسی](README.fa.md) | [Türkçe](README.tr.md)

A Decky Loader plugin for Steam Deck that allows you to manage VLESS, VMess, Trojan, Shadowsocks, and Hysteria 2 subscriptions and connect to them with automatic system-wide TUN routing using `sing-box`.

![Screenshot](assets/screenshot.png)

## 📋 Features

- **Multi-Protocol Support**: VLESS (Reality, TLS, None), VMess, Trojan, Shadowsocks, and Hysteria 2 / Hy2.
- **Multiple Subscriptions**: Add and manage different subscription URLs simultaneously. Nodes from all subscriptions are automatically combined.
- **System-wide TUN Routing**: Automatically routes all Steam Deck internet traffic through `sing-box` TUN interface (`tun0`).
- **Routing Presets**: Support for **"Default"** mode (all traffic through VPN) and **[RoscomVPN](https://github.com/hydraponique/roscomvpn-routing)** mode (smart routing bypass: Steam, Twitch, and RU/BY websites directly, blocked resources via VPN, ads & telemetry are blocked).
- **One-click Toggle**: Connect by simply clicking the server in the list, click again to disconnect.
- **Quick Logging**: Click the **LOG** button to write combined plugin & core logs to `/home/deck/sub-deck.log` and copy them to your clipboard.
- **Root Privileges**: Correctly runs as `root` for network configuration.
- **No Dependencies Needed**: Automatically downloads `sing-box` core binary on first connection.

## 🎁 Built-in Free Subscriptions

The plugin includes a **"Free Subscriptions"** button that adds three pre-verified, automatically updated sources:
- [igareck Subscription](https://github.com/igareck/vpn-configs-for-russia): The classic, verified configuration source for Russia (formerly "Free Configs").
- [Goida VPN (AvenCores)](https://github.com/AvenCores/goida-vpn-configs): Frequently updated VLESS configurations from the Goida VPN project.
- [zieng2/wl Subscription](https://github.com/zieng2/wl): High-quality universal VLESS configurations from the zieng2 wl repository.

*Note: For performance and speed, free subscriptions are automatically filtered to show only the top 5 fastest nodes based on parallel TCP ping.*

## 📥 Installation

1. Download the latest release (`sub-deck.zip`) from [Releases](https://github.com/rosakodu/sub-deck/releases) or build it manually.
2. Copy the ZIP file to your Steam Deck.
3. Enable **Developer Mode** in Steam Settings, then in Decky Loader settings, enable **Developer mode** and choose "Install plugin from file".

## 🚀 How to Use

1. Enter your subscription URL (e.g. `https://...`) and click **"Add Subscription"**.
2. Click any server in the **"Available Servers"** list to activate the connection.
3. The selected server will highlight, and the top label will show **"Connected to: <name>"**.
4. To disconnect, simply click the active server in the list again.

## ⚖️ License

BSD-3-Clause License.
