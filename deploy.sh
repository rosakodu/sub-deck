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
DEST="/home/deck/homebrew/plugins/sub-deck"

echo "==> 1. Сборка фронтенда..."
pnpm run build

echo "==> 2. Подготовка временной директории..."
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

cp plugin.json package.json main.py vpn_manager.py "$TMP_DIR/"
cp -r dist "$TMP_DIR/"
cp -r core "$TMP_DIR/"
cp -r tray "$TMP_DIR/"
[ -d assets ] && cp -r assets "$TMP_DIR/"
mkdir -p "$TMP_DIR/defaults"
for asset in defaults.txt geoip.dat geosite.dat geoip.db geosite.db; do
  if [[ -f "defaults/$asset" ]]; then
    cp "defaults/$asset" "$TMP_DIR/defaults/"
  fi
done
# Include updated sing-box binary in defaults/bin for self-contained deployment
mkdir -p "$TMP_DIR/defaults/bin"
for binary in xray tun2socks sing-box; do
  if [[ -f "defaults/bin/$binary" ]]; then
    cp "defaults/bin/$binary" "$TMP_DIR/defaults/bin/"
  fi
done
test -f "$TMP_DIR/defaults/bin/sing-box"
chmod 755 "$TMP_DIR/defaults/bin/sing-box"

SSH_TARGET="${DECK_USER}@${DECK_IP}"

echo "==> 3. Подготовка прав на Steam Deck..."
ssh -t -o StrictHostKeyChecking=yes "$SSH_TARGET" \
  "sudo chown -R deck:deck '$DEST' && sudo chmod -R u+rwX '$DEST'"

echo "==> 4. Копирование файлов на Steam Deck..."
scp -r -o StrictHostKeyChecking=yes "$TMP_DIR"/* "$SSH_TARGET:$DEST/"

echo "==> 5. Перезапуск Decky Loader (plugin_loader.service)..."
ssh -t -o StrictHostKeyChecking=yes "$SSH_TARGET" "sudo systemctl restart plugin_loader.service"

echo "==> Успешно деплоировано на Steam Deck (${DECK_IP})!"
