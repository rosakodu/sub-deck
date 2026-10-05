import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  TextField,
  Navigation,
  Focusable,
  staticClasses,
} from "@decky/ui";
import {
  callable,
  definePlugin,
  toaster,
} from "@decky/api";
import { useState, useEffect, useMemo, useCallback } from "react";
import { FaNetworkWired, FaClipboard } from "react-icons/fa";

import { NodeConfig, TranslationKeys } from "./types";
import { SUPPORT_COMMUNITY_URL, PASTE_BUTTON_CSS } from "./constants";
import { translations, getTranslation } from "./i18n";
import {
  isFreeSubscriptionUrl,
  getDomainLabel,
  getNodeMethodLabel,
  readClipboardText,
} from "./utils";

// Backend RPC bridge
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
const getClipboard = callable<[], string>("get_clipboard");

function unwrap<T>(payload: any): T {
  return payload && typeof payload === "object" && "result" in payload
    ? payload.result
    : payload;
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

  // Localization translator
  const t = useCallback(
    (key: TranslationKeys, params?: Record<string, string | number>) => {
      return getTranslation(lang, key, params);
    },
    [lang]
  );

  // Memoized nodes grouped by subscription URL to avoid O(N*M) filtration on render
  const nodesBySubscription = useMemo(() => {
    const map: Record<string, NodeConfig[]> = {};
    for (const node of nodes) {
      const url = node.subscription_url || "";
      if (!map[url]) {
        map[url] = [];
      }
      map[url].push(node);
    }
    return map;
  }, [nodes]);

  // Initialization lifecycle
  useEffect(() => {
    let mounted = true;

    const init = async () => {
      try {
        getSteamLanguage()
          .then((detectedLang) => {
            if (!mounted) return;
            const normalized = detectedLang?.toLowerCase();
            if (translations[normalized]) {
              setLang(normalized);
            }
          })
          .catch(console.error);

        const rawSettings = await getSettings();
        const settings = unwrap<any>(rawSettings);
        if (settings && mounted) {
          setSubscriptions(settings.subscriptions || []);
          setSelectedNode(settings.selected_node || null);
          if (settings.selected_preset) {
            setPreset(settings.selected_preset);
          }
        }

        const rawNodes = await getNodes();
        const cachedNodes = unwrap<NodeConfig[]>(rawNodes) || [];
        if (mounted) {
          setNodes(Array.isArray(cachedNodes) ? cachedNodes : []);
        }

        const rawRunning = await isConnected();
        if (mounted) {
          setConnected(!!unwrap<boolean>(rawRunning));
        }
      } catch (err) {
        console.error("Initialization error:", err);
      }
    };

    init();

    return () => {
      mounted = false;
    };
  }, []);

  const refreshSubscriptions = async () => {
    try {
      const rawSettings = await getSettings();
      const settings = unwrap<any>(rawSettings);
      if (settings?.subscriptions) {
        setSubscriptions(settings.subscriptions);
      }
    } catch (e) {
      console.error("Failed to refresh subscriptions:", e);
    }
  };

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
      const fetchedNodes = unwrap<NodeConfig[]>(raw) || [];
      setNodes(Array.isArray(fetchedNodes) ? fetchedNodes : []);
      setInputUrl("");
      toaster.toast({
        title: t("success"),
        body: t("freeConfigsUpdated"),
      });
      await refreshSubscriptions();
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
      const fetchedNodes = unwrap<NodeConfig[]>(raw) || [];
      const nodeArray = Array.isArray(fetchedNodes) ? fetchedNodes : [];

      setNodes(nodeArray);
      setInputUrl("");
      await refreshSubscriptions();

      const isFree = isFreeSubscriptionUrl(inputUrl);
      const addedCount = nodeArray.filter((n) => n.subscription_url === inputUrl).length;
      toaster.toast({
        title: t("success"),
        body: isFree ? t("freeConfigsUpdated") : t("loadedNodesForSub", { count: addedCount }),
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
      const fetchedNodes = unwrap<NodeConfig[]>(raw) || [];
      const nodeArray = Array.isArray(fetchedNodes) ? fetchedNodes : [];

      setNodes(nodeArray);

      if (selectedNode) {
        const stillExists = nodeArray.some(
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

      await refreshSubscriptions();
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
      const fetchedNodes = unwrap<NodeConfig[]>(raw) || [];
      const nodeArray = Array.isArray(fetchedNodes) ? fetchedNodes : [];

      setNodes(nodeArray);
      const isFree = isFreeSubscriptionUrl(urlToUpdate);
      const updatedCount = nodeArray.filter((n) => n.subscription_url === urlToUpdate).length;

      toaster.toast({
        title: t("success"),
        body: isFree ? t("freeConfigsUpdated") : t("loadedNodesForSub", { count: updatedCount }),
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
      if (connected) {
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
        const success = unwrap<boolean>(rawSuccess);
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
    setLoading(true);
    try {
      const raw = await exportLogs();
      const text = unwrap<string>(raw);
      if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        try {
          await navigator.clipboard.writeText(text);
        } catch (clipErr) {
          console.warn("Clipboard write not allowed:", clipErr);
        }
      }
      toaster.toast({
        title: t("logCreatedTitle"),
        body: t("logCreated"),
      });
    } catch (err) {
      toaster.toast({ title: t("error"), body: `${err}` });
    } finally {
      setLoading(false);
    }
  };

  const handlePasteFromClipboard = async () => {
    const pastedText = await readClipboardText(getClipboard);

    if (pastedText) {
      setInputUrl(pastedText);
      toaster.toast({
        title: t("success"),
        body: t("pastedFromClipboard"),
      });
    } else {
      toaster.toast({
        title: t("toastWarning"),
        body: t("clipboardEmptyOrBlocked"),
      });
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

      <style>{PASTE_BUTTON_CSS}</style>

      {/* Поле ввода URL подписки */}
      <PanelSectionRow>
        <div style={{ display: "flex", flexDirection: "column", width: "100%" }}>
          <div style={{ fontSize: "11px", fontWeight: "bold", color: "#a5a5a5", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "6px" }}>
            {t("subUrlLabel")}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", width: "100%" }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <TextField
                value={inputUrl}
                onChange={(e: any) => setInputUrl(e.target.value)}
              />
            </div>
            <Focusable
              className="paste-btn-clean"
              onClick={handlePasteFromClipboard}
              onActivate={handlePasteFromClipboard}
            >
              <FaClipboard size={14} />
            </Focusable>
          </div>
        </div>
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
      <div style={{ display: "flex", justifyContent: "center", width: "100%", padding: "12px 0 6px 0" }}>
        <span style={{ fontSize: "11px", fontWeight: "bold", color: "#a5a5a5", textTransform: "uppercase", letterSpacing: "0.5px" }}>
          {t("subscriptionsTitle")}
        </span>
      </div>

      <PanelSection>
        {subscriptions.length === 0 ? (
          <PanelSectionRow>
            <div style={{ color: "#888", fontSize: "14px", padding: "8px 0" }}>{t("noSubscriptions")}</div>
          </PanelSectionRow>
        ) : (
          subscriptions.map((url, idx) => {
            const subNodes = nodesBySubscription[url] || [];
            const isFreeConfigs = isFreeSubscriptionUrl(url);
            const domainLabel = getDomainLabel(url, lang);
            const isExpanded =
              expandedSubs[url] !== undefined
                ? expandedSubs[url]
                : connected && selectedNode?.subscription_url === url;

            return (
              <PanelSection key={idx}>
                {/* Заголовок подписки в виде кнопки раскрытия */}
                <PanelSectionRow>
                  <ButtonItem
                    layout="below"
                    onClick={() => setExpandedSubs((prev) => ({ ...prev, [url]: !prev[url] }))}
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

                    {/* Статус подключенного сервера */}
                    {connected && selectedNode && selectedNode.subscription_url === url && (
                      <PanelSectionRow>
                        <div style={{ color: "#1a9fff", fontWeight: "bold", padding: "4px 0", fontSize: "12px" }}>
                          {t("selectedServer", { name: selectedNode.name })}
                        </div>
                      </PanelSectionRow>
                    )}

                    {/* Кнопка Обновить */}
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

                    {/* Кнопка Удалить */}
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

      {/* Кнопка экспорта логов */}
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={handleExportLogs}
          disabled={loading}
        >
          {t("logButton")}
        </ButtonItem>
      </PanelSectionRow>

      {/* Кнопка Поддержка */}
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={() => {
            if (Navigation?.NavigateToExternalWeb) {
              Navigation.NavigateToExternalWeb(SUPPORT_COMMUNITY_URL);
            } else {
              window.open(SUPPORT_COMMUNITY_URL, "_blank");
            }
          }}
        >
          {t("supportBtn")}
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
    onDismount() {},
  };
});
