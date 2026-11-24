export const SUPPORT_COMMUNITY_URL = "https://vk.ru/valvesteamdeck";

export const FREE_SUB_IDENTIFIERS = [
  "igareck/vpn-configs-for-russia",
  "avencores/goida-vpn-configs",
  "goida-vpn-configs",
  "zieng2/wl"
];

export const SELECTED_BUTTON_CSS = `
  /* 1. Подавление внешних рамок, теней и зазоров у контейнеров строк и полей */
  .sub-deck-root :is(
    .PanelSectionRow,
    [class*="PanelSectionRow"],
    [class*="Field"],
    [class*="FieldChildren"],
    [class*="ChildrenContainer"],
    [class*="ItemFocusAnim"],
    [class*="FocusRing"],
    [class*="focusRing"],
    [class*="focus-ring"],
    [class*="focusAnimation"],
    [class*="highlight"],
    [class*="Highlight"],
    .sub-deck-selected
  ) {
    outline: none !important;
    box-shadow: none !important;
    border: none !important;
    animation: none !important;
    background: transparent !important;
    background-color: transparent !important;
  }

  /* 2. Подавление псевдоэлементов ::before / ::after (источник серых/белых вылезающих рамок в SteamOS) */
  .sub-deck-root :is(
    .PanelSectionRow,
    [class*="PanelSectionRow"],
    [class*="Field"],
    [class*="FieldChildren"],
    [class*="ChildrenContainer"],
    [class*="ItemFocusAnim"],
    [class*="FocusRing"],
    [class*="focusRing"],
    [class*="focus-ring"],
    [class*="focusAnimation"],
    [class*="highlight"],
    [class*="Highlight"],
    button,
    [role="button"],
    .DialogButton,
    [class*="DialogButton"],
    [class*="_DialogLayout"]
  ):is(::before, ::after) {
    display: none !important;
    content: none !important;
    outline: none !important;
    box-shadow: none !important;
    border: none !important;
    background: transparent !important;
  }

  /* 3. Подавление подсветки контейнера при фокусе геймпада или наведении */
  .sub-deck-root :is(
    .PanelSectionRow,
    [class*="PanelSectionRow"],
    [class*="Field"],
    [class*="ItemFocusAnim"]
  ):is(:focus, :focus-visible, :focus-within, .gpfocus, .gpfocuswithin, :hover) {
    background: transparent !important;
    background-color: transparent !important;
    outline: none !important;
    box-shadow: none !important;
    border: none !important;
    animation: none !important;
  }

  /* 4. Базовый вид кнопок плагина: полупрозрачный серый фон, без внешних контуров */
  .sub-deck-root :is(button, [role="button"], .DialogButton, [class*="DialogButton"], [class*="_DialogLayout"]):not(.paste-btn-clean) {
    background: rgba(255, 255, 255, 0.08) !important;
    background-color: rgba(255, 255, 255, 0.08) !important;
    color: #ffffff !important;
    border: 1.5px solid transparent !important;
    outline: none !important;
    box-shadow: none !important;
    border-radius: 4px !important;
    box-sizing: border-box !important;
    transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease !important;
  }

  /* 5. Выбранный элемент в списке (сервер, пресет, авто-балансировщик) в состоянии покоя */
  :is(.sub-deck-root .sub-deck-selected, .sub-deck-selected) :is(button, [role="button"], .DialogButton, [class*="DialogButton"], [class*="_DialogLayout"]) {
    border: 1.5px solid #1a9fff !important;
    background: rgba(26, 159, 255, 0.15) !important;
    background-color: rgba(26, 159, 255, 0.15) !important;
    color: #ffffff !important;
  }

  /* 6. Кнопка при наведении или фокусе геймпада: белый фон, темный текст, БЕЗ выступающей обводки */
  :is(.sub-deck-root, .sub-deck-selected) :is(button, [role="button"], .DialogButton, [class*="DialogButton"], [class*="_DialogLayout"]):not(.paste-btn-clean):is(
    :focus,
    :focus-visible,
    :focus-within,
    .gpfocus,
    .gpfocuswithin,
    [data-gpfocus="true"],
    :hover,
    :active
  ),
  :is(.sub-deck-root, .sub-deck-selected) :is(
    .PanelSectionRow,
    [class*="PanelSectionRow"],
    [class*="Field"],
    .sub-deck-selected
  ):is(:focus, :focus-visible, :focus-within, .gpfocus, .gpfocuswithin, [data-gpfocus="true"], :hover) :is(button, [role="button"], .DialogButton, [class*="DialogButton"], [class*="_DialogLayout"]):not(.paste-btn-clean) {
    background: #ffffff !important;
    background-color: #ffffff !important;
    background-image: none !important;
    color: #1a1f26 !important;
    border: 1.5px solid #ffffff !important;
    outline: none !important;
    box-shadow: none !important;
  }

  /* 7. Все вложенные элементы (текст, иконки) сфокусированной/наведенной кнопки: темный контрастный цвет */
  :is(.sub-deck-root, .sub-deck-selected) :is(button, [role="button"], .DialogButton, [class*="DialogButton"], [class*="_DialogLayout"]):not(.paste-btn-clean):is(
    :focus,
    :focus-visible,
    :focus-within,
    .gpfocus,
    .gpfocuswithin,
    [data-gpfocus="true"],
    :hover,
    :active
  ) *,
  :is(.sub-deck-root, .sub-deck-selected) :is(
    .PanelSectionRow,
    [class*="PanelSectionRow"],
    [class*="Field"],
    .sub-deck-selected
  ):is(:focus, :focus-visible, :focus-within, .gpfocus, .gpfocuswithin, [data-gpfocus="true"], :hover) :is(button, [role="button"], .DialogButton, [class*="DialogButton"], [class*="_DialogLayout"]):not(.paste-btn-clean) * {
    color: #1a1f26 !important;
    fill: #1a1f26 !important;
  }
`;

export const PASTE_BUTTON_CSS = `
  .paste-btn-clean {
    width: 38px !important;
    height: 38px !important;
    min-width: 38px !important;
    max-width: 38px !important;
    padding: 0 !important;
    margin: 0 !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    border-radius: 0px !important;
    border: none !important;
    outline: none !important;
    box-shadow: none !important;
    background: rgba(255, 255, 255, 0.08) !important;
    color: #ffffff !important;
    cursor: pointer !important;
    transition: background-color 0.15s ease, color 0.15s ease !important;
  }
  .paste-btn-clean svg {
    fill: #ffffff !important;
    color: #ffffff !important;
    transition: fill 0.15s ease, color 0.15s ease !important;
  }
  .paste-btn-clean:focus,
  .paste-btn-clean:hover,
  .paste-btn-clean:active,
  .paste-btn-clean:focus-within {
    background: #ffffff !important;
    color: #1a1f24 !important;
    border: none !important;
    outline: none !important;
    box-shadow: none !important;
    border-radius: 0px !important;
  }
  .paste-btn-clean:focus svg,
  .paste-btn-clean:hover svg,
  .paste-btn-clean:active svg,
  .paste-btn-clean:focus-within svg {
    fill: #1a1f24 !important;
    color: #1a1f24 !important;
  }
`;
