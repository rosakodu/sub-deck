# SUB Deck: Нативная поддержка Amnezia VPN и AmneziaWG

## Цель проекта
Интегрировать полную поддержку Amnezia VPN (`vpn://`, `awg://`, WireGuard/AWG .conf) и трансформировать генератор WARP в генератор Amnezia WARP (AWG с обфускацией QUIC/Junk/SIP) непосредственно в плагин SUB Deck без сторонних приложений на SteamOS.

## Текущий статус
- Этап: Все задачи успешно завершены и протестированы.
- Бинарник: sing-box (amnezia-box) с поддержкой `with_awg` (46M) размещен в `defaults/bin/sing-box`.
- Сборка релиза: `out/sub-deck.zip` успешно скомпилирован и упакован (46M).
- Автотесты: 86 unit-тестов пройдены успешно (OK).

## Задачи (Milestones)
1. [x] **Бинарное ядро**: Сборка и интеграция sing-box с тегом `with_awg` (без необходимости внешних бинарников на Steam Deck).
2. [x] **Парсинг Amnezia**: Реализация поддержки `vpn://` (zlib + json контейнеры `awg`, `wireguard`, `xray`), `awg://` и WireGuard/AWG .conf INI в `core/parsers.py`.
3. [x] **Генератор Amnezia WARP**: Модернизация `core/warp_generator.py` на генерацию узлов с обфускацией AWG (Mini QUIC TLS Initial `I1`, AWG 2.0 handshake, SIP VoIP).
4. [x] **Конфигурация Sing-Box**: Поддержка эндпоинта `awg` с параметрами обфускации (jc, jmin, jmax, s1-s4, h1-h4, i1-i5) в `core/singbox_config.py` и `vpn_manager.py`.
5. [x] **UI и API**: Добавлены кнопки генерации Amnezia WARP в Decky UI (`src/index.tsx`, `src/i18n.ts`, `src/types.ts`) и в Desktop Mode Tray Companion (`tray/tray_app.py`).
6. [x] **Тестирование и релиз**: Добавлены юнит-тесты `tests/test_amnezia_parsers.py` и `tests/test_amnezia_warp.py`. Пройдена сборка релиза `./build_release.sh`.
7. [x] **Интеграция Red Shield VPN**:
   - Извлечение данных из Red Shield на подключенном телефоне (база SQLite `rsv_data` и преференции `appPreference.xml`).
   - Парсинг 77 узлов: 41 AWG (AmneziaWG) + 36 VLESS Reality (gRPC).
   - Модуль `core/redshield.py` и поддержка подписки `redshield_vpn` в `vpn_manager.py`.
   - Защита конфиденциальных данных и приватных ключей в `.gitignore`.
   - Добавлен fallback ICMP ping в `core/pinger.py` для UDP узлов (AWG/WireGuard).
   - Все 85 тестов пройдены успешно, ноды развернуты и проверены на Steam Deck.
8. [x] **Кнопка подключения/отключения и исправление CPS I1–I5**:
   - Реализована мастер-кнопка «Подключить/Отключить» в Decky UI (`src/index.tsx`, `src/types.ts`, `src/i18n.ts`).
   - Исправлена маршрутизация внутреннего DNS (`10.254.254.254/32` и порт 53 через proxy) в `core/singbox_config.py`.
   - Исправлен парсер `core/parsers.py`: сохранение параметров Amnezia Custom Protocol Signatures (`#I1`–`#I5`).
   - Обновлен `defaults/redshield_nodes.json` с полными заголовками обфускации. Все 85 тестов пройдены.
9. [x] **Прямое кабельное подключение по Type-C (USB Gadget)**:
   - Включен режим DRD в BIOS Steam Deck.
   - Запущен модуль ядра `g_ether` (`usb0`).
   - Настроена статическая адресация: Steam Deck `10.42.0.2`, ноутбук `10.42.0.1` (задержка <0.3мс).
   - Создана постоянная служба `usb-gadget-network.service` на Steam Deck.
   - В `deploy.sh` дефолтный IP установлен в `10.42.0.2`. Контрольный канал независим от Wi-Fi.
10. [x] **Диагностика белых списков и успешный обход через VLESS Reality**:
   - Проведена сетевая диагностика в режиме цензуры сотового оператора через USB-кабель.
   - Выявлена блокировка ТСПУ на входящие/исходящие UDP-пакеты к серверам обхода. Из-за этого AWG не получает ответные хэндшейки.
   - Протестирован узел «🏴‍☠️ RedShield | Обход БС - 1 (VLESS)».
   - Успешно запущена системная маршрутизация через Xray (`tun0`).
   - Доступ ко всем заблокированным ресурсам (Google, YouTube, Steam) на Steam Deck полностью восстановлен.
11. [x] **Визуальное переименование Amnezia WARP в Warp Generation**:
   - Текст кнопки в QuickAccess и трее изменен на лаконичное `Warp Generation` (без молнии и «Сгенерировать»).
   - Обновлены локализованные строки интерфейса во всех языках в `src/i18n.ts`.
   - Обновлено отображение заголовка подписки в `src/utils.ts` (`🛡️ Warp Generation`).
   - Обновлены названия действий и уведомлений в Desktop Mode Tray Companion (`tray/tray_app.py`).
   - Обновлены метаданные и названия генерируемых нод в `vpn_manager.py` и `core/warp_generator.py` (`🛡️ Warp Generation (QUIC)`, `🛡️ Warp Generation (AWG 2.0)`, `🛡️ Warp Generation (SIP)`).
   - Внутренний идентификатор (`amnezia_warp`) сохранен без изменений для совместимости.
   - Фронтенд пересобран, плагин развернут на Steam Deck, кэш настроек и нод обновлен.
12. [x] **Пакет серверов Red Shield VPN для переноса**:
   - Упакованы 82 узла Red Shield (41 AWG + 41 VLESS Reality) в архив `redshield-deck-nodes.zip`.
   - Написан авто-установщик `install.sh` и ярлык `.desktop` для установки в 1 клик без потери существующих подписок.
   - Архив скопирован на рабочий стол и в папку «Загрузки» Steam Deck.
13. [x] **Отказоустойчивая регистрация Warp Generation (устранение ошибки SSL _ssl.c:106...)**:
   - Реализована многоуровневая архитектура регистрации в Cloudflare в `core/warp_generator.py`.
   - Tier 1: Прямое HTTPS-соединение с гибким контекстом SSL (устраняет сбои CA-сертификатов на SteamOS).
   - Tier 2: Прямое TLS-подключение к пулу Anycast IP Cloudflare (162.159.192.1, 162.159.193.1, 188.114.96.1, 188.114.97.1) с сохранением SNI `api.cloudflareclient.com` (обход блокировок ТСПУ и DNS-подмен).
   - Tier 3: Резерв через локальный SOCKS5-прокси (127.0.0.1:10808) при активном туннеле.
   - Улучшена обработка ошибок с понятными сообщениями в интерфейсе.
   - Добавлены тесты в `tests/test_amnezia_warp.py`. Все 86 тестов пройдены успешно.
   - Плагин развернут на Steam Deck и протестирован. Версия повышена до v1.2.5.
