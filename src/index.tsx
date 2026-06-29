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
}

// Связываем функции бэкенда с фронтендом
const getSettings = callable<[], { subscriptions: string[]; selected_node: NodeConfig | null }>("get_settings");
const addSubscription = callable<[url: string], NodeConfig[]>("add_subscription");
const removeSubscription = callable<[url: string], NodeConfig[]>("remove_subscription");
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
  | "deleteBtn";

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
    deleteBtn: "Delete"
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
    deleteBtn: "Удалить"
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
    deleteBtn: "删除"
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
    deleteBtn: "刪除"
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
    deleteBtn: "حذف"
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
    deleteBtn: "حذف"
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
    deleteBtn: "Sil"
  }
};

translations.farsi = translations.persian;

// Хелпер получения читаемого домена из URL подписки
function getDomainLabel(url: string): string {
  try {
    const parsed = new URL(url);
    return parsed.hostname;
  } catch (e) {
    return url.length > 25 ? url.substring(0, 22) + "..." : url;
  }
}

function Content() {
  const [lang, setLang] = useState<string>("english");
  const [inputUrl, setInputUrl] = useState<string>("");
  const [subscriptions, setSubscriptions] = useState<string[]>([]);
  const [nodes, setNodes] = useState<NodeConfig[]>([]);
  const [selectedNode, setSelectedNode] = useState<NodeConfig | null>(null);
  const [connected, setConnected] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(false);

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

      toaster.toast({
        title: t("success"),
        body: t("loadedNodes", { count: fetchedNodes.length })
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

      {/* Список добавленных подписок */}
      <PanelSection title={t("subscriptionsTitle")}>
        {subscriptions.length === 0 ? (
          <PanelSectionRow>
            <div style={{ color: "#888", fontSize: "14px", padding: "8px 0" }}>{t("noSubscriptions")}</div>
          </PanelSectionRow>
        ) : (
          subscriptions.map((url, idx) => (
            <PanelSectionRow key={idx}>
              <div style={{ fontSize: "14px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", width: "100%", padding: "4px 0" }}>
                {getDomainLabel(url)}
              </div>
              <div style={{ marginTop: "4px" }}>
                <ButtonItem
                  layout="below"
                  onClick={() => handleDeleteSubscription(url)}
                  disabled={loading}
                >
                  {t("deleteBtn")}
                </ButtonItem>
              </div>
            </PanelSectionRow>
          ))
        )}
      </PanelSection>

      {/* Статус подключенного сервера */}
      {connected && selectedNode && (
        <PanelSectionRow>
          <div style={{ color: "#1a9fff", fontWeight: "bold", padding: "8px 0" }}>
            {t("selectedServer", { name: selectedNode.name })}
          </div>
        </PanelSectionRow>
      )}

      {/* Список нод */}
      {nodes.length > 0 && (
        <PanelSection title={t("nodesTitle", { count: nodes.length })}>
          <div style={{ maxHeight: "250px", overflowY: "auto", paddingRight: "4px" }}>
            {nodes.map((node, idx) => {
              const isSelected = selectedNode?.name === node.name;
              const isActive = isSelected && connected;
              return (
                <PanelSectionRow key={idx}>
                  <div style={{
                    border: isActive ? "1px solid #1a9fff" : "1px solid transparent",
                    borderRadius: "4px",
                    backgroundColor: isActive ? "rgba(26, 159, 255, 0.1)" : "transparent"
                  }}>
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
                            <div style={{ fontSize: "0.8em", color: "#888" }}>{node.server}:{node.port}</div>
                          </div>
                        </div>
                      </div>
                    </ButtonItem>
                  </div>
                </PanelSectionRow>
              );
            })}
          </div>
        </PanelSection>
      )}

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
