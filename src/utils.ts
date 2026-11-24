import { NodeConfig, ProtocolCategory } from "./types";

export function getDomainLabel(url: string, lang: string): string {
  if (url.includes("igareck/vpn-configs-for-russia")) {
    if (lang === "russian") return "Подписка igareck";
    if (lang === "schinese") return "igareck 订阅";
    if (lang === "tchinese") return "igareck 訂閱";
    if (lang === "arabic") return "اشتراك igareck";
    if (lang === "persian" || lang === "farsi") return "اشتراک igareck";
    if (lang === "turkish") return "igareck Aboneliği";
    return "igareck Subscription";
  }
  if (url.toLowerCase().includes("avencores/goida-vpn-configs") || url.includes("goida-vpn-configs")) {
    if (lang === "russian") return "Подписка Goida VPN";
    if (lang === "schinese") return "Goida VPN 订阅";
    if (lang === "tchinese") return "Goida VPN 訂閱";
    if (lang === "arabic") return "اشتراك Goida VPN";
    if (lang === "persian" || lang === "farsi") return "اشتراک Goida VPN";
    if (lang === "turkish") return "Goida VPN Aboneliği";
    return "Goida VPN Subscription";
  }
  if (url.includes("zieng2/wl")) {
    if (lang === "russian") return "Подписка zieng2";
    if (lang === "schinese") return "zieng2 订阅";
    if (lang === "tchinese") return "zieng2 訂閱";
    if (lang === "arabic") return "اشتراك zieng2";
    if (lang === "persian" || lang === "farsi") return "اشتراک zieng2";
    if (lang === "turkish") return "zieng2 Aboneliği";
    return "zieng2 Subscription";
  }
  if (url === "redshield_vpn") {
    return "Red Shield VPN";
  }
  if (url === "amnezia_warp" || url === "cloudflare_warp") {
    return "Warp Generation";
  }
  try {
    const parsed = new URL(url);
    return parsed.hostname;
  } catch (e) {
    return url.length > 25 ? url.substring(0, 22) + "..." : url;
  }
}

export function getNodeMethodLabel(node: NodeConfig): string {
  const protocol = (node.type || "unknown").toUpperCase();

  if (protocol === "SHADOWSOCKS") {
    const method = (node.method || "unknown").toUpperCase();
    return `${protocol}/${method}`;
  }

  if (protocol === "AWG" || protocol === "WIREGUARD" || protocol === "WARP") {
    return `${protocol}/UDP`;
  }

  let transport = (node.transport || "tcp").toUpperCase();
  if (protocol === "HYSTERIA2") {
    transport = "UDP";
  }

  const security = (node.security || "none").toUpperCase();
  return `${protocol}/${transport}/${security}`;
}

export function getNodeCategory(node: NodeConfig): ProtocolCategory {
  const type = (node.type || "").toLowerCase();
  const sec = (node.security || "").toLowerCase();
  const sub = (node.subscription_url || "").toLowerCase();

  if (type === "hysteria2" || type === "hy2" || type === "tuic") {
    return "udp";
  }

  if (
    type === "awg" ||
    type === "wireguard" ||
    type === "warp" ||
    type === "shadowsocks" ||
    type === "ss" ||
    sub.includes("warp") ||
    sub.includes("amnezia")
  ) {
    return "obfs";
  }

  if (
    type === "vless" ||
    type === "trojan" ||
    type === "vmess" ||
    sec === "reality" ||
    sec === "tls"
  ) {
    return "tls";
  }

  return "all";
}

export async function readClipboardText(getBackendClipboard: () => Promise<any>): Promise<string> {
  // 1. Backend X11 / Gamescope and KDE Klipper
  try {
    const rawBackendText = await getBackendClipboard();
    const backendText = (rawBackendText as any)?.result ?? rawBackendText;
    if (backendText && typeof backendText === "string" && backendText.trim()) {
      return backendText.trim();
    }
  } catch (err) {
    console.warn("Backend clipboard read fallback error:", err);
  }

  // 2. Native Steam Client JS API
  try {
    if ((window as any).SteamClient?.System?.GetClipboardText) {
      const text = await (window as any).SteamClient.System.GetClipboardText();
      if (text && typeof text === "string" && text.trim()) {
        return text.trim();
      }
    }
  } catch (steamErr) {
    console.warn("SteamClient.System.GetClipboardText error:", steamErr);
  }

  // 3. Browser Clipboard API
  try {
    if (navigator.clipboard && typeof navigator.clipboard.readText === "function") {
      const text = await navigator.clipboard.readText();
      if (text && text.trim()) {
        return text.trim();
      }
    }
  } catch (clipErr) {
    console.warn("Browser clipboard read error:", clipErr);
  }

  return "";
}

export function formatBytes(bytes?: number): string {
  if (bytes === undefined || bytes === null || isNaN(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let val = bytes;
  let idx = 0;
  while (val >= 1024 && idx < units.length - 1) {
    val /= 1024;
    idx++;
  }
  return `${val.toFixed(1)} ${units[idx]}`;
}

export function formatExpiry(expireTimestamp?: number, lang?: string): string {
  if (!expireTimestamp || expireTimestamp <= 0) {
    return "";
  }
  const now = Math.floor(Date.now() / 1000);
  const diff = expireTimestamp - now;

  const isRu = lang === "russian";

  if (diff <= 0) {
    return isRu ? "Срок истёк" : "Expired";
  }

  const days = Math.floor(diff / 86400);
  if (days > 0) {
    return isRu ? `Осталось ${days} дн.` : `${days} days left`;
  }

  const hours = Math.floor(diff / 3600);
  return isRu ? `Осталось ${hours} ч.` : `${hours} hrs left`;
}

// Regex matching all Unicode emoji, pictographs, flags (regional indicator pairs), dingbats, symbols, and variation selectors
const EMOJI_REGEX = /[\u{1F000}-\u{1FAFF}\u{1F1E6}-\u{1F1FF}\u{2600}-\u{27BF}\u{FE00}-\u{FE0F}\u{1F300}-\u{1F5FF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{200D}\u{20E3}\u{2300}-\u{23FF}\u{2B50}\u{2B55}\u{2934}\u{2935}\u{25AA}\u{25AB}\u{25FE}\u{25FD}\u{25FB}\u{25FC}\u{25B6}\u{25C0}\u{E0020}-\u{E007F}]/gu;

export function stripEmojis(str?: string): string {
  if (!str) return "";
  const cleaned = str.replace(EMOJI_REGEX, "").replace(/\s+/g, " ").trim();
  return cleaned || str;
}


