# sub-deck

[Русский](README.ru.md)

A Decky Loader plugin for Steam Deck that allows you to manage VLESS, VMess, Trojan, Shadowsocks, and Hysteria 2 subscriptions and connect to them with automatic system-wide TUN routing using `sing-box`.

![Screenshot](assets/screenshot.png)

## 📋 Features

- **Multi-Protocol Support**: VLESS (Reality, TLS, None), VMess, Trojan, Shadowsocks, and Hysteria 2 / Hy2.
- **Multiple Subscriptions**: Add and manage different subscription URLs simultaneously. Nodes from all subscriptions are automatically combined.
- **System-wide TUN Routing**: Automatically routes all Steam Deck internet traffic through `sing-box` TUN interface (`tun0`).
- **One-click Toggle**: Connect by simply clicking the server in the list, click again to disconnect.
- **Quick Logging**: Click the **LOG** button to write combined plugin & core logs to `/home/deck/sub-deck.log` and copy them to your clipboard.
- **Root Privileges**: Correctly runs as `root` for network configuration.
- **No Dependencies Needed**: Automatically downloads `sing-box` core binary on first connection.

## 📥 Installation

1. Download the latest release (`sub-deck.zip`) from [Releases](https://github.com/rosakodu/sub-deck/releases) or build it manually.
2. Copy the ZIP file to your Steam Deck.
3. Enable **Developer Mode** in Steam Settings, then in Decky Loader settings, enable **Developer mode** and choose "Install plugin from file".

## 🚀 How to Use

1. Enter your subscription URL (e.g. `https://s.subdeck.shop/...`) and click **"Add Subscription"**.
2. Click any server in the **"Available Servers"** list to activate the connection.
3. The selected server will highlight, and the top label will show **"Connected to: <name>"**.
4. To disconnect, simply click the active server in the list again.

## ⚖️ License

BSD-3-Clause License.
