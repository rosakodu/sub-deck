# План внедрения: Улучшения подписок и сетевого стека Sub-Deck

Данный план описывает внедрение улучшений из анализа DeckyClash:
- **Пункт 2:** Парсинг и отображение остатка трафика и срока подписки (`Subscription-Userinfo`).
- **Пункт 3:** Продвинутая ротация User-Agent и автоопределение имени подписки из заголовков (`Content-Disposition`).
- **Пункт 5:** Атомарное обновление подписок и кэша через временные файлы (`tempfile` + `os.replace`).

---

## Архитектура решения

```
                  [HTTP Request с продвинутыми User-Agent]
                                   │
                                   ▼
                   [Ответ сервера с заголовками]
               ┌───────────────────┴───────────────────┐
               ▼                                       ▼
  [Subscription-Userinfo]                     [Content-Disposition / Название]
  (upload, download, total, expire)           (filename="ИмяПодписки.txt")
               │                                       │
               └───────────────────┬───────────────────┘
                                   │
                                   ▼
                  [Парсинг нод + Атомарная запись]
                  (tempfile -> os.replace)
                                   │
                                   ▼
                [Сохранение метаданных в settings.json]
             (user_info, custom_names / sub_metadata)
                                   │
               ┌───────────────────┴───────────────────┐
               ▼                                       ▼
       [Decky Loader UI]                       [Desktop Mode Tray]
  (Индикатор GB и дней в карточке)            (Тултип и подменю серверов)
```

---

## Этап 1. Backend: HTTP-заголовки, User-Agent и атомарность (`core/parsers.py`, `core/constants.py`)

1. **Расширение списка User-Agents (`core/constants.py`)**:
   - Добавить актуальные и доверенные клиенты для обхода Cloudflare/WAF и антибот-фильтров:
     ```python
     SUBSCRIPTION_USER_AGENTS = [
         "clash-verge/v1.6.6",
         "v2rayN/6.42",
         "sing-box/1.9.0",
         "FlClash/0.14.0",
         "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
     ]
     ```

2. **Парсинг `Subscription-Userinfo` и `Content-Disposition` (`core/parsers.py`)**:
   - Реализовать функцию `parse_subscription_userinfo(header_val: str) -> dict`:
     - Извлечение полей: `upload`, `download`, `total`, `expire`.
     - Хранение в сырых байтах и секундах (`upload_bytes`, `download_bytes`, `total_bytes`, `expire_timestamp`).
   - Реализовать функцию `parse_content_disposition_filename(header_val: str) -> Optional[str]`:
     - Поддержка форматов `filename="..."` и RFC 5987 `filename*=UTF-8''...` (с декодированием URL-encoded имен).
   - Обновить функцию `download_subscription_payload(url: str, timeout: float = 15.0)`:
     - Возвращать кортеж `(payload_bytes, headers_dict, error)`.

3. **Атомарная запись и защита от сбоев (`core/parsers.py` / `vpn_manager.py`)**:
   - При сохранении кэша нод (`save_nodes`) и настроек (`save_settings`) использовать `tempfile.NamedTemporaryFile` в рабочей директории плагина.
   - Проверять размер и валидность структуры перед вызовом `os.replace(...)`. Если загрузка прервалась или вернула пустой ответ, старые ноды и кэш гарантированно сохраняются.

---

## Этап 2. Менеджер данных: Хранение метаданных подписок (`vpn_manager.py`)

1. **Структура хранения в `settings.json`**:
   - Добавить секцию `subscription_metadata`:
     ```json
     {
       "subscriptions": ["https://my-sub-domain.com/sub/token"],
       "subscription_metadata": {
         "https://my-sub-domain.com/sub/token": {
           "name": "Личный VPS",
           "upload": 1073741824,
           "download": 5368709120,
           "total": 53687091200,
           "expire": 1735689600,
           "last_updated": 1728900000
         }
       }
     }
     ```
2. **Обновление методов**:
   - `parse_subscription(url)` и `update_subscription(url)`: обновляют и сохраняют метаданные в `settings["subscription_metadata"][url]`.
   - `remove_subscription(url)`: подчищает метаданные удаляемой подписки.
   - `get_settings()`: возвращает обновленный словарь клиенту.

---

## Этап 3. Frontend (UI в Decky Loader): Отображение квоты и имени

1. **Обновление интерфейсов (`src/types.ts`)**:
   - Добавить интерфейс `SubscriptionMetadata`:
     ```typescript
     export interface SubscriptionMetadata {
       name?: string;
       upload?: number;
       download?: number;
       total?: number;
       expire?: number;
       last_updated?: number;
     }
     ```
   - Добавить поле `subscription_metadata?: Record<string, SubscriptionMetadata>` в интерфейс настроек.

2. **Форматирование данных (`src/utils.ts`)**:
   - Функция форматирования трафика: `formatBytes(bytes: number): string` (байты → MB / GB).
   - Функция форматирования срока действия: `formatExpiry(timestamp: number, lang: string): string` («Осталось 12 дн.» / «Истекло»).

3. **Отрисовка в карточке подписки (`src/index.tsx`)**:
   - В блоке заголовка подписки (аккордеона):
     - Если провайдер вернул имя в `Content-Disposition`, показывать его (с fallback на домен).
     - Если есть данные о трафике: показывать компактный бейдж `Использовано: 6.4 / 50.0 GB`.
     - Если есть `expire`: показывать плашку `Истекает: 31 дек 2026` или оставшиеся дни.

---

## Этап 4. Desktop Tray Companion: Интеграция в трей рабочего стола (`tray/tray_app.py`)

1. **Обновление `ToolTip` и пунктов меню**:
   - В тултипе трея при наведении показывать не только активный сервер, но и остаток трафика по текущей активной подписке.
   - В подменю выбора серверов выводить рядом с заголовком подписки оставшийся трафик.

---

## Этап 5. Тестирование и верификация

1. **Тесты Python (`tests/test_subscription_info.py`)**:
   - Модульные тесты для парсера `Subscription-Userinfo` (различные варианты форматирования заголовков).
   - Тест атомарной записи при сбое сети.
   - Тест парсинга `Content-Disposition` с кириллицей и спецсимволами (`UTF-8''...`).
2. **Сборка фронтенда**: `pnpm run build` (контроль отсутствия предупреждений типов TypeScript).
3. **Тестирование на Steam Deck**:
   - Деплой на `192.168.0.104`.
   - Проверка реальной подписки: корректность отображения гигабайт и дней до окончания.
