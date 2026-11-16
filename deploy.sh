#!/usr/bin/env bash
set -euo pipefail

if [ -n "${1:-}" ]; then
  DECK_IP="$1"
elif ping -c 1 -W 1 10.42.0.2 >/dev/null 2>&1; then
  DECK_IP="10.42.0.2"
elif ping -c 1 -W 1 steamdeck.local >/dev/null 2>&1; then
  DECK_IP="steamdeck.local"
else
  DECK_IP="10.42.0.2"
fi
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
# Include updated sing-box binary in defaults/bin for self-contained deployment
mkdir -p "$TMP_DIR/defaults/bin"
cp defaults/bin/sing-box "$TMP_DIR/defaults/bin/"
chmod 755 "$TMP_DIR/defaults/bin/sing-box"

SSH="sshpass -p $DECK_PASS ssh -o StrictHostKeyChecking=no"
SCP="sshpass -p $DECK_PASS scp -o StrictHostKeyChecking=no"

echo "==> 3. Остановка старых процессов трея и подготовка прав..."
$SSH "${DECK_USER}@${DECK_IP}" "echo '$DECK_PASS' | sudo -S pkill -9 -f '[t]ray_app.py' 2>/dev/null || true"
$SSH "${DECK_USER}@${DECK_IP}" "echo '$DECK_PASS' | sudo -S chown -R deck:deck '$DEST' && echo '$DECK_PASS' | sudo -S chmod -R u+rwX '$DEST'"

echo "==> 4. Копирование файлов на Steam Deck..."
$SCP -r "$TMP_DIR"/* "${DECK_USER}@${DECK_IP}:${DEST}/"

echo "==> 5. Перезапуск Decky Loader (plugin_loader.service)..."
$SSH "${DECK_USER}@${DECK_IP}" "echo '$DECK_PASS' | sudo -S systemctl restart plugin_loader.service"

rm -rf "$TMP_DIR"
echo "==> Успешно деплоировано на Steam Deck (${DECK_IP})!"
