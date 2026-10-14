import { NodeConfig } from "./types";
import { FREE_SUB_IDENTIFIERS } from "./constants";

export function isFreeSubscriptionUrl(url: string): boolean {
  if (!url) return false;
  const lower = url.toLowerCase();
  return FREE_SUB_IDENTIFIERS.some((id) => lower.includes(id));
}

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
    if (lang === "russian") return "Подписка Goida VPN AvenCores";
    if (lang === "schinese") return "Goida VPN AvenCores 订阅";
    if (lang === "tchinese") return "Goida VPN AvenCores 訂閱";
    if (lang === "arabic") return "اشتراك Goida VPN AvenCores";
    if (lang === "persian" || lang === "farsi") return "اشتراک Goida VPN AvenCores";
    if (lang === "turkish") return "Goida VPN AvenCores Aboneliği";
    return "Goida VPN AvenCores Subscription";
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

  let transport = (node.transport || "tcp").toUpperCase();
  if (protocol === "HYSTERIA2") {
    transport = "UDP";
  }

  const security = (node.security || "none").toUpperCase();
  return `${protocol}/${transport}/${security}`;
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

