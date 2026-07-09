import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  TextField,
  staticClasses
} from "@decky/ui";
import {
  callable,
  definePlugin,
  toaster
} from "@decky/api";
import { useState, useEffect, useMemo } from "react";
import { FaNetworkWired } from "react-icons/fa";

interface NodeConfig {
  name: string;
  uuid: string;
  server: string;
  port: number;
  type: string;
  security: string;
  sni: string;
  pbk: string;
  sid: string;
  flow: string;
  fp: string;
  subscription_url?: string;
  transport?: string;
  method?: string;
}

// Связываем функции бэкенда с фронтендом
const getSettings = callable<[], { subscriptions: string[]; selected_node: NodeConfig | null; selected_preset?: string }>("get_settings");
const addSubscription = callable<[url: string], NodeConfig[]>("add_subscription");
const addFreeSubscriptions = callable<[], NodeConfig[]>("add_free_subscriptions");
const removeSubscription = callable<[url: string], NodeConfig[]>("remove_subscription");
const updateSubscription = callable<[url: string], NodeConfig[]>("update_subscription");
const savePreset = callable<[preset: string], boolean>("save_preset");
const getNodes = callable<[], NodeConfig[]>("get_nodes");
const connectNode = callable<[node: NodeConfig], boolean>("connect_node");
const disconnect = callable<[], boolean>("disconnect");
const isConnected = callable<[], boolean>("is_connected");
const getSteamLanguage = callable<[], string>("get_steam_language");
const exportLogs = callable<[], string>("export_logs");

type TranslationKeys =
  | "title"
  | "subUrlLabel"
  | "addSubBtn"
  | "updating"
  | "selectedServer"
  | "nodesTitle"
  | "selectNodeFirst"
  | "deactivateFirst"
  | "success"
  | "error"
  | "loadedNodes"
  | "noNodesFound"
  | "tunnelStartFailed"
  | "tunnelStarted"
  | "tunnelStartedBody"
  | "tunnelStopped"
  | "tunnelStoppedBody"
  | "toastWarning"
  | "toastSelectedNode"
  | "logButton"
  | "subscriptionsTitle"
  | "noSubscriptions"
  | "deleteBtn"
  | "updateBtn"
  | "presetLabel"
  | "presetDefault"
  | "presetRoscom"
  | "addFreeBtn"
  | "loadedNodesForSub"
  | "freeConfigsUpdated";

const translations: Record<string, Record<TranslationKeys, string>> = {
  english: {
    title: "VLESS Management",
    subUrlLabel: "Subscription Link",
    addSubBtn: "Add Subscription",
    updating: "Loading...",
    selectedServer: "Connected to: {name}",
    nodesTitle: "Available Servers ({count})",
    selectNodeFirst: "Select a server first",
    deactivateFirst: "Deactivate current connection first",
    success: "Success",
    error: "Error",
    loadedNodes: "Loaded servers: {count}",
    noNodesFound: "No servers found. Check LOG.",
    tunnelStartFailed: "Failed to start tunnel",
    tunnelStarted: "VPN Connected",
    tunnelStartedBody: "Server: {name}",
    tunnelStopped: "VPN Disconnected",
    tunnelStoppedBody: "Tunnel stopped",
    toastWarning: "Warning",
    toastSelectedNode: "Server selected: {name}",
    logButton: "LOG",
    subscriptionsTitle: "My Subscriptions",
    noSubscriptions: "No subscriptions added",
    deleteBtn: "Delete",
    updateBtn: "Update",
    presetLabel: "Routing Preset",
    presetDefault: "Default",
    presetRoscom: "RoscomVPN",
    addFreeBtn: "Free Subscriptions",
    loadedNodesForSub: "Subscription nodes updated: {count}",
    freeConfigsUpdated: "Free subscriptions updated"
  },
  russian: {
    title: "Управление VLESS",
    subUrlLabel: "Ссылка на подписку",
    addSubBtn: "Добавить подписку",
    updating: "Загрузка...",
    selectedServer: "Подключено к: {name}",
    nodesTitle: "Доступные серверы ({count})",
    selectNodeFirst: "Сначала выберите ноду для подключения",
    deactivateFirst: "Сначала отключите текущее соединение",
    success: "Успех",
    error: "Ошибка",
    loadedNodes: "Загружено нод: {count}",
    noNodesFound: "Нод не найдено. Проверьте LOG.",
    tunnelStartFailed: "Не удалось запустить туннель",
    tunnelStarted: "VPN Подключен",
    tunnelStartedBody: "Сервер: {name}",
    tunnelStopped: "VPN Отключен",
    tunnelStoppedBody: "Туннель остановлен",
    toastWarning: "Внимание",
    toastSelectedNode: "Сервер выбран: {name}",
    logButton: "LOG",
    subscriptionsTitle: "Мои подписки",
    noSubscriptions: "Нет добавленных подписок",
    deleteBtn: "Удалить",
    updateBtn: "Обновить",
    presetLabel: "Режим маршрутизации",
    presetDefault: "По умолчанию",
    presetRoscom: "RoscomVPN",
    addFreeBtn: "Бесплатные подписки",
    loadedNodesForSub: "Обновлено нод в этой подписке: {count}",
    freeConfigsUpdated: "Бесплатные подписки обновлены"
  },
  schinese: {
    title: "VLESS 管理",
    subUrlLabel: "订阅链接",
    addSubBtn: "添加订阅",
    updating: "正在加载...",
    selectedServer: "已连接: {name}",
    nodesTitle: "可用服务器 ({count})",
    selectNodeFirst: "请先选择一个连接服务器",
    deactivateFirst: "请先断开当前连接",
    success: "成功",
    error: "错误",
    loadedNodes: "已加载服务器数量: {count}",
    noNodesFound: "未找到节点。请检查 LOG。",
    tunnelStartFailed: "启动隧道失败",
    tunnelStarted: "VPN 已连接",
    tunnelStartedBody: "服务器: {name}",
    tunnelStopped: "VPN 已断开",
    tunnelStoppedBody: "隧道已停止",
    toastWarning: "警告",
    toastSelectedNode: "已选择服务器: {name}",
    logButton: "LOG",
    subscriptionsTitle: "我的订阅",
    noSubscriptions: "无订阅链接",
    deleteBtn: "删除",
    updateBtn: "更新",
    presetLabel: "分流规则",
    presetDefault: "默认",
    presetRoscom: "RoscomVPN",
    addFreeBtn: "免费订阅",
    loadedNodesForSub: "此订阅已更新节点: {count}",
    freeConfigsUpdated: "免费订阅已更新"
  },
  tchinese: {
    title: "VLESS 管理",
    subUrlLabel: "訂閱連結",
    addSubBtn: "添加訂閱",
    updating: "正在載入...",
    selectedServer: "已連線: {name}",
    nodesTitle: "可用伺服器 ({count})",
    selectNodeFirst: "請先選擇一個連線伺服器",
    deactivateFirst: "請先中斷當前連線",
    success: "成功",
    error: "錯誤",
    loadedNodes: "已載入伺服器數量: {count}",
    noNodesFound: "未找到節點。請檢查 LOG。",
    tunnelStartFailed: "啟動隧道失敗",
    tunnelStarted: "VPN 已連線",
    tunnelStartedBody: "伺服器: {name}",
    tunnelStopped: "VPN 已斷開",
    tunnelStoppedBody: "隧道已停止",
    toastWarning: "警告",
    toastSelectedNode: "已選擇伺服器: {name}",
    logButton: "LOG",
    subscriptionsTitle: "我的訂閱",
    noSubscriptions: "無訂閱連結",
    deleteBtn: "刪除",
    updateBtn: "更新",
    presetLabel: "分流規則",
    presetDefault: "默認",
    presetRoscom: "RoscomVPN",
    addFreeBtn: "免費訂閱",
    loadedNodesForSub: "此訂閱已更新節點: {count}",
    freeConfigsUpdated: "免費訂閱已更新"
  },
  arabic: {
    title: "إدارة VLESS",
    subUrlLabel: "رابط الاشتراك",
    addSubBtn: "إضافة اشتراك",
    updating: "جاري التحميل...",
    selectedServer: "متصل بـ: {name}",
    nodesTitle: "الخوادم المتاحة ({count})",
    selectNodeFirst: "الرجاء اختيار خادم أولاً للاتصال",
    deactivateFirst: "الرجاء إيقاف الاتصال الحالي أولاً",
    success: "نجاح",
    error: "خطأ",
    loadedNodes: "عدد الخوادم المحملة: {count}",
    noNodesFound: "لم يتم العثور على خوادم. تحقق من السجل LOG.",
    tunnelStartFailed: "فشل بدء النفق",
    tunnelStarted: "تم تفعيل الـ VPN",
    tunnelStartedBody: "الخادم: {name}",
    tunnelStopped: "تم إيقاف الـ VPN",
    tunnelStoppedBody: "تم إيقاف النفق",
    toastWarning: "تحذير",
    toastSelectedNode: "تم اختيار الخادم: {name}",
    logButton: "LOG",
    subscriptionsTitle: "اشتراكاتي",
    noSubscriptions: "لا توجد اشتراكات مضافة",
    deleteBtn: "حذف",
    updateBtn: "تحديث",
    presetLabel: "وضع التوجيه",
    presetDefault: "الافتراضي",
    presetRoscom: "RoscomVPN",
    addFreeBtn: "اشتراكات مجانية",
    loadedNodesForSub: "تم تحديث عقد الاشتراك: {count}",
    freeConfigsUpdated: "تم تحديث الاشتراكات المجانية"
  },
  persian: {
    title: "مدیریت VLESS",
    subUrlLabel: "لینک اشتراک",
    addSubBtn: "افزودن اشتراک",
    updating: "در حال بارگذاری...",
    selectedServer: "متصل به: {name}",
    nodesTitle: "سرورهای در دسترس ({count})",
    selectNodeFirst: "ابتدا سروری را برای اتصال انتخاب کنید",
    deactivateFirst: "ابتدا اتصال فعلی را قطع کنید",
    success: "موفقیت",
    error: "خطا",
    loadedNodes: "سرورهای بارگذاری شده: {count}",
    noNodesFound: "هیچ گره‌ای یافت نشد. لاگ (LOG) را بررسی کنید.",
    tunnelStartFailed: "شروع تونل ناموفق بود",
    tunnelStarted: "VPN متصل شد",
    tunnelStartedBody: "سرور: {name}",
    tunnelStopped: "VPN قطع شد",
    tunnelStoppedBody: "تونل متوقف شد",
    toastWarning: "هشدار",
    toastSelectedNode: "سرور انتخاب شد: {name}",
    logButton: "LOG",
    subscriptionsTitle: "اشتراک‌های من",
    noSubscriptions: "هیچ اشتراکی اضافه نشده است",
    deleteBtn: "حذف",
    updateBtn: "به‌روزرسانی",
    presetLabel: "حالت مسیریابی",
    presetDefault: "پیش‌فرض",
    presetRoscom: "RoscomVPN",
    addFreeBtn: "اشتراک‌های رایگان",
    loadedNodesForSub: "گره‌های اشتراک به‌روزرسانی شد: {count}",
    freeConfigsUpdated: "اشتراک‌های رایگان به‌روزرسانی شدند"
  },
  turkish: {
    title: "VPN Yapılandırmaları",
    subUrlLabel: "Abonelik Bağlantısı",
    addSubBtn: "Abonelik Ekle",
    updating: "Yükleniyor...",
    selectedServer: "Bağlanılan: {name}",
    nodesTitle: "Kullanılabilir Sunucular ({count})",
    selectNodeFirst: "Önce bir sunucu seçin",
    deactivateFirst: "Önce mevcut bağlantıyı kapatın",
    success: "Başarılı",
    error: "Hata",
    loadedNodes: "Yüklenen sunucu sayısı: {count}",
    noNodesFound: "Sunucu bulunamadı. LOG dosyasını kontrol edin.",
    tunnelStartFailed: "Tünel başlatılamadı",
    tunnelStarted: "VPN Bağlandı",
    tunnelStartedBody: "Sunucu: {name}",
    tunnelStopped: "VPN Bağlantısı Kesildi",
    tunnelStoppedBody: "Tünel durduruldu",
    toastWarning: "Uyarı",
    toastSelectedNode: "Sunucu seçildi: {name}",
    logButton: "LOG",
    subscriptionsTitle: "Aboneliklerim",
    noSubscriptions: "Eklenmiş abonelik yok",
    deleteBtn: "Sil",
    updateBtn: "Güncelle",
    presetLabel: "Yönlendirme Modu",
    presetDefault: "Varsayılan",
    presetRoscom: "RoscomVPN",
    addFreeBtn: "Ücretsiz Abonelikler",
    loadedNodesForSub: "Bu abonelikteki sunucular güncellendi: {count}",
    freeConfigsUpdated: "Ücretsiz abonelikler güncellendi"
  }
};

translations.farsi = translations.persian;

// Хелпер получения читаемого домена из URL подписки
function getDomainLabel(url: string, lang: string): string {
  if (url.includes("igareck/vpn-configs-for-russia")) {
    if (lang === "russian") return "Подписка igareck";
    if (lang === "schinese") return "igareck 订阅";
    if (lang === "tchinese") return "igareck 訂閱";
    if (lang === "arabic") return "اشتراك igareck";
    if (lang === "persian") return "اشتراک igareck";
    if (lang === "turkish") return "igareck Aboneliği";
    return "igareck Subscription";
  }
  if (url.includes("AvenCores/goida-vpn-configs")) {
    if (lang === "russian") return "Подписка Goida VPN AvenCores";
    if (lang === "schinese") return "Goida VPN AvenCores 订阅";
    if (lang === "tchinese") return "Goida VPN AvenCores 訂閱";
    if (lang === "arabic") return "اشتراك Goida VPN AvenCores";
    if (lang === "persian") return "اشتراک Goida VPN AvenCores";
    if (lang === "turkish") return "Goida VPN AvenCores Aboneliği";
    return "Goida VPN AvenCores Subscription";
  }
  if (url.includes("zieng2/wl")) {
    if (lang === "russian") return "Подписка zieng2";
    if (lang === "schinese") return "zieng2 订阅";
    if (lang === "tchinese") return "zieng2 訂閱";
    if (lang === "arabic") return "اشتراك zieng2";
    if (lang === "persian") return "اشتراک zieng2";
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

// Хелпер для форматирования метода подключения (Protocol/Transport/Security)
function getNodeMethodLabel(node: NodeConfig): string {
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

function Content() {
  const [lang, setLang] = useState<string>("english");
  const [inputUrl, setInputUrl] = useState<string>("");
  const [subscriptions, setSubscriptions] = useState<string[]>([]);
  const [nodes, setNodes] = useState<NodeConfig[]>([]);
  const [selectedNode, setSelectedNode] = useState<NodeConfig | null>(null);
  const [connected, setConnected] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(false);
  const [preset, setPreset] = useState<string>("default");
  const [expandedSubs, setExpandedSubs] = useState<Record<string, boolean>>({});
  const [presetExpanded, setPresetExpanded] = useState<boolean>(false);

  // Хук локализации
  const t = useMemo(() => {
    return (key: TranslationKeys, params?: Record<string, string | number>) => {
      const dict = translations[lang] || translations.english;
      let val = dict[key] || translations.english[key] || String(key);
      if (params) {
        Object.entries(params).forEach(([k, v]) => {
          val = val.replace(`{${k}}`, String(v));
        });
      }
      return val;
    };
  }, [lang]);

  // Инициализация
  useEffect(() => {
    const init = async () => {
      try {
        getSteamLanguage()
          .then((detectedLang) => {
            const normalized = detectedLang?.toLowerCase();
            if (translations[normalized]) {
              setLang(normalized);
            }
          })
          .catch(console.error);

        const rawSettings = await getSettings();
        const settings = (rawSettings as any)?.result ?? rawSettings;
        if (settings) {
          setSubscriptions(settings.subscriptions || []);
          setSelectedNode(settings.selected_node || null);
          if (settings.selected_preset) {
            setPreset(settings.selected_preset);
          }
        }

        const rawNodes = await getNodes();
        const cachedNodes: NodeConfig[] = Array.isArray(rawNodes)
          ? rawNodes
          : (rawNodes as any)?.result ?? [];
        setNodes(cachedNodes);

        const running = await isConnected();
        const rawRunning: any = running;
        setConnected(!!(rawRunning?.result ?? rawRunning));
      } catch (err) {
        console.error("Initialization error:", err);
      }
    };
    init();
  }, []);

  const handlePresetChange = async (presetName: string, presetLabel: string) => {
    setPreset(presetName);
    try {
      await savePreset(presetName);
      toaster.toast({ title: t("success"), body: `${t("presetLabel")}: ${presetLabel}` });
    } catch (err) {
      toaster.toast({ title: t("error"), body: `${err}` });
    }
  };

  const handleAddFreeVless = async () => {
    setLoading(true);
    try {
      const raw = await addFreeSubscriptions();
      const fetchedNodes = Array.isArray(raw) ? raw : (raw as any)?.result ?? [];
      setNodes(fetchedNodes);
      setInputUrl("");
      toaster.toast({
        title: t("success"),
        body: t("freeConfigsUpdated")
      });
      
      const rawSettings = await getSettings();
      const settings = (rawSettings as any)?.result ?? rawSettings;
      if (settings) {
        setSubscriptions(settings.subscriptions || []);
      }
    } catch (err) {
      toaster.toast({ title: t("error"), body: `${err}` });
    } finally {
      setLoading(false);
    }
  };

  const handleAddSubscription = async () => {
    if (!inputUrl) {
      toaster.toast({ title: t("error"), body: t("subUrlLabel") });
      return;
    }
    setLoading(true);
    try {
      const raw = await addSubscription(inputUrl);
      const fetchedNodes: NodeConfig[] = Array.isArray(raw)
        ? raw
        : (raw as any)?.result ?? [];

      setNodes(fetchedNodes);
      setInputUrl("");

      // Перезапрашиваем актуальный список подписок
      const rawSettings = await getSettings();
      const settings = (rawSettings as any)?.result ?? rawSettings;
      if (settings) {
        setSubscriptions(settings.subscriptions || []);
      }

      const isFree = (
        inputUrl.includes("igareck/vpn-configs-for-russia") ||
        inputUrl.includes("AvenCores/goida-vpn-configs") ||
        inputUrl.includes("zieng2/wl")
      );
      const addedCount = fetchedNodes.filter((n: any) => n.subscription_url === inputUrl).length;
      toaster.toast({
        title: t("success"),
        body: isFree ? t("freeConfigsUpdated") : t("loadedNodesForSub", { count: addedCount })
      });
    } catch (err) {
      toaster.toast({ title: t("error"), body: `${err}` });
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteSubscription = async (urlToDelete: string) => {
    setLoading(true);
    try {
      const raw = await removeSubscription(urlToDelete);
      const fetchedNodes: NodeConfig[] = Array.isArray(raw)
        ? raw
        : (raw as any)?.result ?? [];

      setNodes(fetchedNodes);

      // Проверяем, осталась ли выбранная нода в списке доступных
      if (selectedNode) {
        const stillExists = fetchedNodes.some(
          (n) => n.name === selectedNode.name && n.server === selectedNode.server
        );
        if (!stillExists) {
          if (connected) {
            try {
              await disconnect();
            } catch (e) {
              console.error("Disconnect on delete error:", e);
            }
            setConnected(false);
            toaster.toast({ title: t("tunnelStopped"), body: t("tunnelStoppedBody") });
          }
          setSelectedNode(null);
        }
      }

      // Перезапрашиваем актуальный список подписок
      const rawSettings = await getSettings();
      const settings = (rawSettings as any)?.result ?? rawSettings;
      if (settings) {
        setSubscriptions(settings.subscriptions || []);
      }
    } catch (err) {
      toaster.toast({ title: t("error"), body: `${err}` });
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateSubscription = async (urlToUpdate: string) => {
    setLoading(true);
    try {
      const raw = await updateSubscription(urlToUpdate);
      const fetchedNodes: NodeConfig[] = Array.isArray(raw)
        ? raw
        : (raw as any)?.result ?? [];

      setNodes(fetchedNodes);
      const isFree = (
        urlToUpdate.includes("igareck/vpn-configs-for-russia") ||
        urlToUpdate.includes("AvenCores/goida-vpn-configs") ||
        urlToUpdate.includes("zieng2/wl")
      );
      const updatedCount = fetchedNodes.filter((n: any) => n.subscription_url === urlToUpdate).length;
      toaster.toast({
        title: t("success"),
        body: isFree ? t("freeConfigsUpdated") : t("loadedNodesForSub", { count: updatedCount })
      });
    } catch (err) {
      toaster.toast({ title: t("error"), body: `${err}` });
    } finally {
      setLoading(false);
    }
  };

  const handleNodeClick = async (node: NodeConfig) => {
    const isCurrentActive = selectedNode && selectedNode.name === node.name && connected;

    if (isCurrentActive) {
      // Клик на уже подключенную ноду -> Отключаем
      setLoading(true);
      try {
        await disconnect();
        setConnected(false);
        toaster.toast({ title: t("tunnelStopped"), body: t("tunnelStoppedBody") });
      } catch (err) {
        toaster.toast({ title: t("error"), body: `${err}` });
      } finally {
        setLoading(false);
      }
    } else {
      // Клик на новую ноду (или неподключенную) -> Подключаем
      if (connected) {
        // Если уже было активно другое соединение, гасим его перед стартом нового
        setLoading(true);
        try {
          await disconnect();
          setConnected(false);
        } catch (err) {
          console.error("Disconnect error:", err);
        }
      }

      setLoading(true);
      setSelectedNode(node);

      try {
        const rawSuccess = await connectNode(node);
        const success = (rawSuccess as any)?.result ?? rawSuccess;
        if (success) {
          setConnected(true);
          toaster.toast({ title: t("tunnelStarted"), body: t("tunnelStartedBody", { name: node.name }) });
        } else {
          toaster.toast({ title: t("error"), body: t("tunnelStartFailed") });
          setConnected(false);
        }
      } catch (err) {
        toaster.toast({ title: t("error"), body: `${err}` });
        setConnected(false);
      } finally {
        setLoading(false);
      }
    }
  };

  const handleExportLogs = async () => {
    try {
      const raw = await exportLogs();
      const text = (raw as any)?.result ?? raw;
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(text);
      }
    } catch (err) {
      console.error("Export logs error:", err);
    }
  };

  return (
    <PanelSection title={t("title")}>
      {/* Выбор пресета маршрутизации */}
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => setPresetExpanded(!presetExpanded)}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
              <span style={{ fontSize: "11px", fontWeight: "bold", color: "#a5a5a5", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                {t("presetLabel")}
              </span>
              <span style={{ fontSize: "10px", color: "#888" }}>
                {presetExpanded ? "▼" : "▶"}
              </span>
            </div>
          </ButtonItem>
        </PanelSectionRow>

        {presetExpanded && (
          <>
            {/* Опция Default */}
            <PanelSectionRow>
              <div style={{ position: "relative", width: "100%" }}>
                <ButtonItem
                  layout="below"
                  onClick={() => { handlePresetChange("default", t("presetDefault")); setPresetExpanded(false); }}
                >
                  <div style={{ fontWeight: preset === "default" ? "bold" : "normal", color: preset === "default" ? "#1a9fff" : "inherit" }}>
                    {t("presetDefault")}
                  </div>
                </ButtonItem>
                {preset === "default" && (
                  <div style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    border: "1.5px solid #1a9fff",
                    borderRadius: "4px",
                    pointerEvents: "none",
                    backgroundColor: "rgba(26, 159, 255, 0.1)"
                  }} />
                )}
              </div>
            </PanelSectionRow>

            {/* Опция RoscomVPN */}
            <PanelSectionRow>
              <div style={{ position: "relative", width: "100%" }}>
                <ButtonItem
                  layout="below"
                  onClick={() => { handlePresetChange("roscomvpn", t("presetRoscom")); setPresetExpanded(false); }}
                >
                  <div style={{ fontWeight: preset === "roscomvpn" ? "bold" : "normal", color: preset === "roscomvpn" ? "#1a9fff" : "inherit" }}>
                    {t("presetRoscom")}
                  </div>
                </ButtonItem>
                {preset === "roscomvpn" && (
                  <div style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    border: "1.5px solid #1a9fff",
                    borderRadius: "4px",
                    pointerEvents: "none",
                    backgroundColor: "rgba(26, 159, 255, 0.1)"
                  }} />
                )}
              </div>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>

      {/* Поле добавления новой подписки */}
      <PanelSectionRow>
        <TextField
          label={t("subUrlLabel")}
          value={inputUrl}
          onChange={(e: any) => setInputUrl(e.target.value)}
        />
      </PanelSectionRow>
      
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={handleAddSubscription}
          disabled={loading}
        >
          {loading ? t("updating") : t("addSubBtn")}
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={handleAddFreeVless}
          disabled={loading}
        >
          {t("addFreeBtn")}
        </ButtonItem>
      </PanelSectionRow>

      {/* Список добавленных подписок */}
      <PanelSection title={t("subscriptionsTitle")}>
        {subscriptions.length === 0 ? (
          <PanelSectionRow>
            <div style={{ color: "#888", fontSize: "14px", padding: "8px 0" }}>{t("noSubscriptions")}</div>
          </PanelSectionRow>
        ) : (
          subscriptions.map((url, idx) => {
            const subNodes = nodes.filter(n => n.subscription_url === url);
            const isFreeConfigs = (
              url.includes("igareck/vpn-configs-for-russia") ||
              url.includes("AvenCores/goida-vpn-configs") ||
              url.includes("zieng2/wl")
            );
            const domainLabel = getDomainLabel(url, lang);
            const isExpanded = expandedSubs[url] !== undefined ? expandedSubs[url] : (connected && selectedNode?.subscription_url === url);
            
            return (
              <PanelSection key={idx}>
                {/* Заголовок подписки в виде кнопки раскрытия */}
                <PanelSectionRow>
                  <ButtonItem
                    layout="below"
                    onClick={() => setExpandedSubs(prev => ({ ...prev, [url]: !prev[url] }))}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
                      <span style={{ fontSize: "11px", fontWeight: "bold", color: "#a5a5a5", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                        {domainLabel}
                      </span>
                      <span style={{ fontSize: "10px", color: "#888" }}>
                        {isExpanded ? "▼" : "▶"}
                      </span>
                    </div>
                  </ButtonItem>
                </PanelSectionRow>

                {isExpanded && (
                  <>
                    {/* Список нод этой подписки */}
                    {subNodes.length > 0 ? (
                      <div style={{ maxHeight: "250px", overflowY: "auto", paddingRight: "4px", marginBottom: "8px" }}>
                        {subNodes.map((node, nIdx) => {
                          const isSelected = selectedNode?.name === node.name;
                          const isActive = isSelected && connected;
                          return (
                            <PanelSectionRow key={nIdx}>
                              <div style={{ position: "relative", width: "100%" }}>
                                <ButtonItem
                                  layout="below"
                                  onClick={() => handleNodeClick(node)}
                                >
                                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: "8px", textAlign: "left" }}>
                                      <div>
                                        <div style={{ fontWeight: isActive ? "bold" : "normal", color: isActive ? "#1a9fff" : "inherit" }}>
                                          {node.name}
                                        </div>
                                        <div style={{ fontSize: "0.8em", color: "#888" }}>{getNodeMethodLabel(node)}</div>
                                      </div>
                                    </div>
                                  </div>
                                </ButtonItem>
                                {isActive && (
                                  <div style={{
                                    position: "absolute",
                                    top: 0,
                                    left: 0,
                                    right: 0,
                                    bottom: 0,
                                    border: "1.5px solid #1a9fff",
                                    borderRadius: "4px",
                                    pointerEvents: "none",
                                    backgroundColor: "rgba(26, 159, 255, 0.1)"
                                  }} />
                                )}
                              </div>
                            </PanelSectionRow>
                          );
                        })}
                      </div>
                    ) : (
                      <PanelSectionRow>
                        <div style={{ color: "#888", fontSize: "12px", padding: "4px 0" }}>
                          {t("noNodesFound")}
                        </div>
                      </PanelSectionRow>
                    )}

                    {/* Статус подключенного сервера внутри конкретной подписки */}
                    {connected && selectedNode && selectedNode.subscription_url === url && (
                      <PanelSectionRow>
                        <div style={{ color: "#1a9fff", fontWeight: "bold", padding: "4px 0", fontSize: "12px" }}>
                          {t("selectedServer", { name: selectedNode.name })}
                        </div>
                      </PanelSectionRow>
                    )}
                    
                    {/* Кнопки управления подпиской столбиком (Обновить НАД Удалить) */}
                    {!isFreeConfigs && (
                      <PanelSectionRow>
                        <ButtonItem
                          layout="below"
                          onClick={() => handleUpdateSubscription(url)}
                          disabled={loading}
                        >
                          {t("updateBtn")}
                        </ButtonItem>
                      </PanelSectionRow>
                    )}
                    <PanelSectionRow>
                      <div style={{ color: "#ff6347" }}>
                        <ButtonItem
                          layout="below"
                          onClick={() => handleDeleteSubscription(url)}
                          disabled={loading}
                        >
                          {t("deleteBtn")}
                        </ButtonItem>
                      </div>
                    </PanelSectionRow>
                  </>
                )}
              </PanelSection>
            );
          })
        )}
      </PanelSection>

      {/* Кнопка LOG перемещена в самый низ */}
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={handleExportLogs}
          disabled={loading}
        >
          {t("logButton")}
        </ButtonItem>
      </PanelSectionRow>
    </PanelSection>
  );
}

export default definePlugin(() => {
  return {
    name: "SUB Deck",
    titleView: <div className={staticClasses.Title}>SUB Deck</div>,
    content: <Content />,
    icon: <FaNetworkWired />,
    onDismount() {
      // Здесь можно вызвать деинициализацию при необходимости
    },
  };
});
