export const SUPPORT_COMMUNITY_URL = "https://vk.ru/valvesteamdeck";

export const FREE_SUB_IDENTIFIERS = [
  "igareck/vpn-configs-for-russia",
  "avencores/goida-vpn-configs",
  "goida-vpn-configs",
  "zieng2/wl"
];

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
