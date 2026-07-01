# sub-deck

[English](README.md) | [Русский](README.ru.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md) | [العربية](README.ar.md) | [فارسی](README.fa.md) | [Türkçe](README.tr.md)

Steam Deck 的 Decky Loader 插件，允许您管理 VLESS、VMess、Trojan、Shadowsocks 和 Hysteria 2 订阅，并使用 `sing-box` 通过自动系统级 TUN 路由连接它们。

![Screenshot](assets/screenshot.png)

## 📋 功能特性

- **多协议支持**：VLESS (Reality, TLS, None), VMess, Trojan, Shadowsocks, 以及 Hysteria 2 / Hy2。
- **多订阅管理**：支持同时添加和管理多个订阅链接。来自所有订阅的节点将自动合并。
- **系统级 TUN 路由**：自动将所有 Steam Deck 的网络流量通过 `sing-box` TUN 接口 (`tun0`) 进行路由。
- **一键切换**：只需在列表中点击服务器即可连接，再次点击已连接的服务器即可断开。
- **快速日志**：点击 **LOG** 按钮可将插件和核心的合并日志写入 `/home/deck/sub-deck.log`，并将其复制到剪贴板。
- **Root 权限**：为了配置网络，插件会正确地以 `root` 权限运行。
- **无需额外依赖**：首次连接时会自动下载 `sing-box` 核心二进制文件。

## 📥 安装

1. 从 [Releases](https://github.com/rosakodu/sub-deck/releases) 页面下载最新版本 (`sub-deck.zip`) 或手动构建。
2. 将 ZIP 文件复制到您的 Steam Deck 上。
3. 在 Steam 设置中启用 **开发者模式**，然后在 Decky Loader 设置中启用 **Developer mode** 并选择 "Install plugin from file" (从文件安装插件)。

## 🚀 如何使用

1. 输入您的订阅 URL（例如 `https://...`）并点击 **"Add Subscription"**。
2. 在 **"Available Servers"** 列表中点击任何服务器即可激活连接。
3. 选中的服务器将会高亮显示，并且顶部标签会显示 **"Connected to: <name>"**。
4. 如需断开连接，只需再次点击列表中当前激活的服务器即可。

## ⚖️ 许可证

BSD-3-Clause License.
