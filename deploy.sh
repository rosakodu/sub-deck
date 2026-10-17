#!/usr/bin/env bash
set -euo pipefail

DECK_IP="${1:-192.168.0.104}"
DECK_USER="deck"
DECK_PASS="0451"
DEST="/home/deck/homebrew/plugins/sub-deck"

echo "==> 1. Сборка фронтенда..."
pnpm run build

echo "==> 2. Подготовка временной директории..."
TMP_DIR="/tmp/subdeck_deploy"
rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"

cp plugin.json package.json main.py vpn_manager.py "$TMP_DIR/"
cp -r dist "$TMP_DIR/"
cp -r core "$TMP_DIR/"
cp -r tray "$TMP_DIR/"
[ -d assets ] && cp -r assets "$TMP_DIR/"
[ -d defaults ] && cp -r defaults "$TMP_DIR/"
rm -rf "$TMP_DIR/defaults/bin" 2>/dev/null || true

SSH="ssh -o StrictHostKeyChecking=no"
SCP="scp -o StrictHostKeyChecking=no"

echo "==> 3. Остановка старых процессов трея и подготовка прав..."
$SSH "${DECK_USER}@${DECK_IP}" "echo '$DECK_PASS' | sudo -S pkill -9 -f '[t]ray_app.py' 2>/dev/null || true"
$SSH "${DECK_USER}@${DECK_IP}" "echo '$DECK_PASS' | sudo -S chown -R deck:deck '$DEST'"

echo "==> 4. Копирование файлов на Steam Deck..."
$SCP -r "$TMP_DIR"/* "${DECK_USER}@${DECK_IP}:${DEST}/"

echo "==> 5. Перезапуск Decky Loader (plugin_loader.service)..."
$SSH "${DECK_USER}@${DECK_IP}" "echo '$DECK_PASS' | sudo -S systemctl restart plugin_loader.service"

rm -rf "$TMP_DIR"
echo "==> Успешно деплоировано на Steam Deck (${DECK_IP})!"
