# Gemini Guidance for sub-deck

This guide is written for the agent developers to quickly understand the codebase of **sub-deck**.

## 🚀 Architecture Overview

The plugin utilizes Decky Loader's hybrid architecture:
1.  **Frontend (React)**: `/src/index.tsx`
    *   UI with multi-subscription inputs, server list, and direct connection triggers.
    *   Localized dynamically in 7 languages (English, Russian, Turkish, Arabic, Persian, Simplified/Traditional Chinese) by matching Steam's detected locale.
    *   Communicates with the backend using `@decky/api`'s `callable`.
2.  **Backend (Python)**: `main.py` & `vpn_manager.py`
    *   Runs with **root** privileges (required for `tun0` interface routing).
    *   Manages the lifecycle of the `sing-box` binary.
    *   Uses `ssl._create_unverified_context()` to bypass SSL certificate validation on SteamOS (since subscription hosts might fail standard SSL chain verification).

## 📂 Key Files & Directories

*   `/plugin.json` — Metadata. Correctly uses `"flags": ["root"]` for root privileges and `"api_version": 1`.
*   `/main.py` — Entrypoint for Decky python daemon. Initializes `VPNManager` in `_main()` (not `__init__`!).
*   `/vpn_manager.py` — Core management. Holds logic for base64 subscription parsing, JSON config generation, and Popen orchestration.
*   `/src/index.tsx` — Front-end view.
*   `/dist/` — Folder containing the bundled JS output. Compiled with Rollup.
*   `/out/sub-deck.zip` — Bundled release package for deployment.

## 🛠️ Debugging & Log Locations

*   **Plugin logs** (python stdout + error output): `/home/deck/homebrew/logs/sub-deck/sub-deck.log`
*   **sing-box core logs** (redirected stdout/stderr): `/home/deck/homebrew/settings/sub-deck/sing-box.log` (avoids PIPE buffer locks!).
*   **Exported combined log**: `/home/deck/sub-deck.log` (written on clicking the **LOG** button).

## ⚠️ Important Pitfalls (Keep in Mind)

1.  **PyInstaller Environment Lock**: 
    `vpn_manager.py` cleans the inherited `LD_LIBRARY_PATH` by filtering out `/tmp/_MEI*` directories. **Never bypass this filter when starting subprocesses!** Otherwise, `sing-box` will immediately crash with linking errors.
2.  **sing-box versioning**:
    Uses version `1.9.3`. Generated config must use `"inet4_address": "172.19.0.1/30"` for the tun inbound (previously `"address"` in old versions).
3.  **Process management**:
    Always query `pgrep -x sing-box` and kill with `pkill -x sing-box` to avoid false positives.
