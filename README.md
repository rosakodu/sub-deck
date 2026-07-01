# sub-deck

[Русский](README.ru.md)

A Decky Loader plugin for Steam Deck that allows you to manage VLESS, VMess, Trojan, Shadowsocks, and Hysteria 2 subscriptions and connect to them with automatic system-wide TUN routing using `sing-box`.

![Screenshot](assets/screenshot.png)

## 📋 Features

### 🛠️ Routing Presets
*   **"Default"** — all traffic is routed through the VPN.
*   **"RoscomVPN"** — smart routing bypass (RU/BY websites and BitTorrent directly, blocked resources via VPN, advertisements and Windows telemetry are blocked).
*   **Offline Databases & Auto-Update:** Automatic download and update of geofiles by Python in the background every 6 hours (ensuring instant VPN start thanks to bundled databases).

### 🔍 Smart Server Filtering
*   **Fast Ping:** Parallel TCP ping during subscription updates (1.0 sec timeout).
*   **Top 15 Selection:** Automatic selection and display of the top 15 fastest working nodes (even if the subscription contains over 100,000 keys, with a limit of 5 nodes for Free Configs).
*   **Deduplication:** Automatic removal of duplicate servers with identical names or network endpoints (`ip:port`).

### 📱 Updated Vertical Interface
*   **Grouping:** Servers are no longer mixed together; they are grouped strictly under their respective subscriptions.
*   **Convenient Management:** The "Update" button is placed vertically above the "Delete" button for each subscription.
*   **Compact Design:** Compact typography (11px, uppercase) is used for subscription headers.
*   **Pixel-Perfect Outline:** The blue outline highlight of the selected node and routing preset fits pixel-to-pixel over button boundaries.

### 🎁 "Free Configs" Button
*   Add a pre-verified, daily-updated database of free configurations for Russia (VPN VLESS Configs Russia) in a single click.

### 🔄 Background Subscription Auto-Update
*   Support for the `profile-update-interval` HTTP header to automatically refresh servers in the background.

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
