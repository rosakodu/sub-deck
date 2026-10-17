#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# sub-deck release packager for Decky Loader
# Produces clean, self-contained, offline-ready release zip
# ──────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================================="
echo "  sub-deck — Сборка чистого релиза для Decky Loader"
echo "======================================================="

# 1. Извлечение версии
VERSION=$(grep -m1 '"version":' plugin.json | sed -E 's/.*"version": "([^"]+)".*/\1/')
echo "==> Версия плагина: $VERSION"

# 2. Проверка тестов
echo "==> 1. Запуск автоматических тестов..."
python3 -m unittest discover tests

# 3. Сборка фронтенда
echo "==> 2. Сборка фронтенда (Rollup)..."
pnpm run build

if [[ ! -s "dist/index.js" ]]; then
  echo "[-] ОШИБКА: dist/index.js отсутствует или пустой!" >&2
  exit 1
fi

# 4. Проверка обязательных бинарников в defaults/bin/
echo "==> 3. Верификация офлайн-бинарников в defaults/bin/..."
for bin in xray tun2socks sing-box; do
  BIN_PATH="defaults/bin/$bin"
  if [[ ! -f "$BIN_PATH" ]]; then
    echo "[-] ОШИБКА: Бинарник $BIN_PATH отсутствует!" >&2
    exit 1
  fi
  chmod 755 "$BIN_PATH"
  echo "    [✓] $bin ($(du -h "$BIN_PATH" | cut -f1))"
done

# 5. Проверка баз гео-данных в defaults/
echo "==> 4. Верификация гео-баз в defaults/..."
for dat in geoip.dat geosite.dat geoip.db geosite.db; do
  DAT_PATH="defaults/$dat"
  if [[ ! -f "$DAT_PATH" ]]; then
    echo "[-] ОШИБКА: База $DAT_PATH отсутствует!" >&2
    exit 1
  fi
  echo "    [✓] $dat ($(du -h "$DAT_PATH" | cut -f1))"
done

# 6. Подготовка чистого каталога дистрибуции
echo "==> 5. Формирование каталога релиза..."
OUT_DIR="$SCRIPT_DIR/out"
STAGING_DIR="/tmp/sub-deck-build-$$"
mkdir -p "$OUT_DIR" "$STAGING_DIR/sub-deck"
trap 'rm -rf "$STAGING_DIR"' EXIT

# Копирование файлов в структуру sub-deck/
cp -a main.py vpn_manager.py plugin.json package.json "$STAGING_DIR/sub-deck/"
cp -a LICENSE README*.md "$STAGING_DIR/sub-deck/" 2>/dev/null || true
cp -a logo.png screenshot.png "$STAGING_DIR/sub-deck/" 2>/dev/null || true

# Копирование директорий без кэшей
rsync -a --exclude '__pycache__' --exclude '*.pyc' dist/ "$STAGING_DIR/sub-deck/dist/"
rsync -a --exclude '__pycache__' --exclude '*.pyc' core/ "$STAGING_DIR/sub-deck/core/"
rsync -a --exclude '__pycache__' --exclude '*.pyc' tray/ "$STAGING_DIR/sub-deck/tray/"
rsync -a defaults/ "$STAGING_DIR/sub-deck/defaults/"

# Нормализация прав
find "$STAGING_DIR/sub-deck" -type d -exec chmod 755 {} +
find "$STAGING_DIR/sub-deck" -type f -exec chmod 644 {} +
chmod 755 "$STAGING_DIR/sub-deck/defaults/bin/"* 2>/dev/null || true

# 7. Упаковка в zip
echo "==> 6. Упаковка zip-архива..."
RELEASE_ZIP="$OUT_DIR/sub-deck-v${VERSION}.zip"
LATEST_ZIP="$OUT_DIR/sub-deck.zip"

rm -f "$RELEASE_ZIP" "$LATEST_ZIP"
(cd "$STAGING_DIR" && zip -r -9 "$RELEASE_ZIP" sub-deck)
cp "$RELEASE_ZIP" "$LATEST_ZIP"

# 8. Контрольная сумма SHA256
SHA256=$(sha256sum "$RELEASE_ZIP" | cut -d' ' -f1)

echo "======================================================="
echo "  [✓] Релиз успешно собран!"
echo "  Файл:   $RELEASE_ZIP ($(du -h "$RELEASE_ZIP" | cut -f1))"
echo "  Alias:  $LATEST_ZIP"
echo "  SHA256: $SHA256"
echo "======================================================="
