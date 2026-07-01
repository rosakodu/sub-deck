# sub-deck

[English](README.md) | [Русский](README.ru.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md) | [العربية](README.ar.md) | [فارسی](README.fa.md) | [Türkçe](README.tr.md)

Steam Deck 的 Decky Loader 外掛程式，讓您能夠管理 VLESS、VMess、Trojan、Shadowsocks 和 Hysteria 2 訂閱，並使用 `sing-box` 透過自動系統級 TUN 路由連接它們。

![Screenshot](assets/screenshot.png)

## 📋 功能特色

- **多協定支援**：VLESS (Reality, TLS, None)、VMess、Trojan、Shadowsocks 以及 Hysteria 2 / Hy2。
- **多訂閱管理**：支援同時新增和管理多個訂閱連結。來自所有訂閱的節點將自動合併。
- **系統級 TUN 路由**：自動將所有 Steam Deck 的網路流量透過 `sing-box` TUN 介面 (`tun0`) 進行路由。
- **一鍵切換**：只需在清單中點擊伺服器即可連接，再次點擊已連接的伺服器即可斷開。
- **快速日誌**：點擊 **LOG** 按鈕可將外掛和核心的合併日誌寫入 `/home/deck/sub-deck.log`，並將其複製到剪貼簿。
- **Root 權限**：為了配置網路，外掛會正確地以 `root` 權限執行。
- **無需額外依賴**：首次連接時會自動下載 `sing-box` 核心二進位檔案。

## 📥 安裝

1. 從 [Releases](https://github.com/rosakodu/sub-deck/releases) 頁面下載最新版本 (`sub-deck.zip`) 或手動建置。
2. 將 ZIP 檔案複製到您的 Steam Deck 上。
3. 在 Steam 設定中啟用 **開發者模式 (Developer Mode)**，然後在 Decky Loader 設定中啟用 **Developer mode** 並選擇 "Install plugin from file" (從檔案安裝外掛程式)。

## 🚀 如何使用

1. 輸入您的訂閱 URL（例如 `https://...`）並點擊 **"Add Subscription"**。
2. 在 **"Available Servers"** 清單中點擊任何伺服器即可啟用連接。
3. 選中的伺服器將會反白顯示，並且頂部標籤會顯示 **"Connected to: <name>"**。
4. 如需斷開連接，只需再次點擊清單中目前啟用的伺服器即可。

## ⚖️ 授權條款

BSD-3-Clause License.
