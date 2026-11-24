import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  TextField,
  ToggleField,
  Navigation,
  Focusable,
  staticClasses,
  showModal,
  ConfirmModal,
} from "@decky/ui";
import {
  callable,
  definePlugin,
  toaster,
  useQuickAccessVisible,
} from "@decky/api";
import { FC, useState, useEffect, useMemo, useCallback, useRef } from "react";
import { FaNetworkWired, FaClipboard } from "react-icons/fa";

import { NodeConfig, TranslationKeys, SubscriptionMetadata, Settings, ProtocolCategory } from "./types";
import { SUPPORT_COMMUNITY_URL, PASTE_BUTTON_CSS, SELECTED_BUTTON_CSS } from "./constants";
import { translations, getTranslation } from "./i18n";
import {
  getDomainLabel,
  getNodeMethodLabel,
  getNodeCategory,
  readClipboardText,
  formatBytes,
  formatExpiry,
  stripEmojis,
} from "./utils";

// Backend RPC bridge
const getSettings = callable<[], Settings>("get_settings");
const addSubscription = callable<[url: string], NodeConfig[]>("add_subscription");
const generateWarpNode = callable<[], any>("generate_warp_node");
const removeSubscription = callable<[url: string], NodeConfig[]>("remove_subscription");
const updateSubscription = callable<[url: string], NodeConfig[]>("update_subscription");
const savePreset = callable<[preset: string], boolean>("save_preset");
const getNodes = callable<[], NodeConfig[]>("get_nodes");
const connectNode = callable<[node: NodeConfig], boolean>("connect_node");
const autoSelectBestNode = callable<[], { success: boolean; node_name?: string; ping?: number; server?: string; error?: string }>("auto_select_best_node");
const disconnect = callable<[], boolean>("disconnect");
const isConnected = callable<[], boolean>("is_connected");
const getSteamLanguage = callable<[], string>("get_steam_language");
const exportLogs = callable<[], string>("export_logs");
const getClipboard = callable<[], string>("get_clipboard");
const getDesktopStatus = callable<[], { installed: boolean; autostart: boolean; enabled?: boolean }>("get_desktop_status");
const setDesktopAutostart = callable<[enable: boolean], boolean>("set_desktop_autostart");
const pingNodes = callable<[subscription_url?: string], NodeConfig[]>("ping_nodes");
const getRealDelay = callable<[], { success: boolean; delay_ms: number }>("get_real_delay");

const PRESET_OPTIONS: Array<{ key: string; labelKey: TranslationKeys }> = [
  { key: "default", labelKey: "presetDefault" },
  { key: "bypass_ru", labelKey: "presetBypassRu" },
  { key: "gaming", labelKey: "presetGaming" },
  { key: "roscomvpn", labelKey: "presetRoscom" },
];

const PROTOCOL_OPTIONS: Array<{ key: ProtocolCategory; labelKey: TranslationKeys }> = [
  { key: "all", labelKey: "protocolFilterAll" },
  { key: "tls", labelKey: "protocolFilterTls" },
  { key: "obfs", labelKey: "protocolFilterObfs" },
  { key: "udp", labelKey: "protocolFilterUdp" },
];

function unwrap<T>(payload: any): T {
  return payload && typeof payload === "object" && "result" in payload
    ? payload.result
    : payload;
}

interface AddSubscriptionModalProps {
  closeModal?: () => void;
  onAdd: (url: string) => Promise<boolean | void>;
  t: (key: TranslationKeys, params?: Record<string, string | number>) => string;
}

const AddSubscriptionModal: FC<AddSubscriptionModalProps> = ({ closeModal, onAdd, t }) => {
  const [url, setUrl] = useState<string>("");
  const [submitting, setSubmitting] = useState<boolean>(false);
  const submittingRef = useRef<boolean>(false);

  const handlePaste = async () => {
    if (submitting || submittingRef.current) return;
    const pastedText = await readClipboardText(getClipboard);
    if (pastedText) {
      setUrl(pastedText.trim());
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

  const handleConfirm = async () => {
    if (submitting || submittingRef.current) return;
    const trimmed = url.trim();
    if (!trimmed) {
      toaster.toast({ title: t("error"), body: t("subUrlLabel") });
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    try {
      const ok = await onAdd(trimmed);
      if (ok !== false) {
        closeModal?.();
      }
    } catch (err) {
      console.error("Add subscription modal error:", err);
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <ConfirmModal
      {...({ bCloseAfterOK: false } as any)}
      strTitle={t("addSubBtn")}
      strOKButtonText={t("confirmAddBtn")}
      strCancelButtonText={t("cancelBtn")}
      bOKDisabled={submitting || !url.trim()}
      bCancelDisabled={submitting}
      onOK={handleConfirm}
      onCancel={closeModal}
      closeModal={closeModal}
      onEscKeypress={closeModal}
    >
      <style>{PASTE_BUTTON_CSS}</style>
      <div style={{ display: "flex", flexDirection: "column", gap: "10px", width: "100%", padding: "10px 0" }}>
        <div style={{ fontSize: "12px", color: "#a5a5a5", textTransform: "uppercase", letterSpacing: "0.5px" }}>
          {t("subUrlLabel")}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", width: "100%" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <TextField
              value={url}
              disabled={submitting}
              onChange={(e: any) => setUrl(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  e.stopPropagation();
                  if (url.trim() && !submitting && !submittingRef.current) {
                    handleConfirm();
                  }
                }
              }}
              focusOnMount
            />
          </div>
          <Focusable
            className="paste-btn-clean"
            onClick={submitting ? undefined : handlePaste}
            onActivate={submitting ? undefined : handlePaste}
            style={submitting ? { opacity: 0.5, pointerEvents: "none" } : undefined}
          >
            <FaClipboard size={14} />
          </Focusable>
        </div>
      </div>
    </ConfirmModal>
  );
};

function findSteamNavNode(el: HTMLElement | null): any {
  if (!el) return null;
  if ((el as any).__nav_node) return (el as any).__nav_node;
  if ((el as any).__virtual_node) return (el as any).__virtual_node;

  const navCtrl =
    (window as any).FocusNavController ||
    (window as any).GamepadNavTree?.m_context?.m_controller;
  if (navCtrl?.FindNavNodeForElement) {
    try {
      const node = navCtrl.FindNavNodeForElement(el);
      if (node) return node;
    } catch {}
  }

  try {
    const reactKey = Object.keys(el).find(
      (k) => k.startsWith("__reactFiber") || k.startsWith("__reactInternalInstance")
    );
    let curr = (el as any)[reactKey || ""];
    while (curr) {
      if (curr.memoizedProps?.node?.BTakeFocus || curr.memoizedProps?.node?.TakeFocus) {
        return curr.memoizedProps.node;
      }
      if (curr.memoizedProps?.focusNav?.TakeFocus) {
        return curr.memoizedProps.focusNav;
      }
      if (curr.stateNode?.BTakeFocus || curr.stateNode?.TakeFocus) {
        return curr.stateNode;
      }
      curr = curr.return;
    }
  } catch {}

  return null;
}

function focusSteamElement(el: HTMLElement | null) {
  if (!el) return;
  const navNode = findSteamNavNode(el);
  if (navNode) {
    try {
      if (typeof navNode.BTakeFocus === "function") {
        navNode.BTakeFocus();
        return;
      }
      if (typeof navNode.TakeFocus === "function") {
        navNode.TakeFocus();
        return;
      }
    } catch (e) {
      console.warn("[sub-deck] navNode focus error:", e);
    }
  }

  try {
    el.focus({ preventScroll: true });
  } catch {
    try {
      el.focus();
    } catch {}
  }
}

function scrollToTop(el: HTMLElement | null) {
  if (!el) return;
  try {
    el.scrollIntoView({ block: "start", inline: "nearest", behavior: "instant" as any });
  } catch {}

  try {
    let parent = el.parentElement;
    while (parent) {
      if (parent.scrollTop !== undefined && parent.scrollTop > 0) {
        parent.scrollTop = 0;
      }
      if (parent.scrollLeft !== undefined && parent.scrollLeft > 0) {
        parent.scrollLeft = 0;
      }
      parent = parent.parentElement;
    }
  } catch {}

  try {
    document
      .querySelectorAll<HTMLElement>(
        '[class*="ScrollPanel"], [class*="scrollPanel"], [class*="basicscrollpanel"], [class*="BasicScrollPanel"], [class*="ScrollContainer"], [class*="scrollContainer"], [class*="DialogBody"], [class*="dialogbody"], [class*="GamepadDialogContent"], [class*="gamepaddialogcontent"], [class*="quickaccessmenu"], [class*="QuickAccessMenu"], [class*="TabGroupPanel"], [class*="PanelSection"]'
      )
      .forEach((c) => {
        if (c.scrollTop > 0) c.scrollTop = 0;
      });
  } catch {}

  try {
    window.scrollTo({ top: 0, left: 0, behavior: "instant" as any });
  } catch {}
}

function Content() {
  const [lang, setLang] = useState<string>("english");
  const [subscriptions, setSubscriptions] = useState<string[]>([]);
  const [nodes, setNodes] = useState<NodeConfig[]>([]);
  const [selectedNode, setSelectedNode] = useState<NodeConfig | null>(null);
  const [connected, setConnected] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(false);
  const [preset, setPreset] = useState<string>("default");
  const [expandedSubs, setExpandedSubs] = useState<Record<string, boolean>>({});
  const [presetExpanded, setPresetExpanded] = useState<boolean>(false);
  const [protocolFilter, setProtocolFilter] = useState<ProtocolCategory>("all");
  const [protocolExpanded, setProtocolExpanded] = useState<boolean>(false);
  const [trayAutostart, setTrayAutostart] = useState<boolean>(true);
  const [subMetadata, setSubMetadata] = useState<Record<string, SubscriptionMetadata>>({});
  const [pingingSubUrl, setPingingSubUrl] = useState<string | null>(null);
  const [realDelay, setRealDelay] = useState<number | null>(null);
  const isModalOpenRef = useRef<boolean>(false);
  const isQAMVisible = useQuickAccessVisible();
  const connectBtnRef = useRef<HTMLDivElement | null>(null);
  const wasVisibleRef = useRef<boolean>(false);

  const resetScrollAndFocus = useCallback(() => {
    const rootEl = connectBtnRef.current;
    if (!rootEl) return;
    const btn =
      (rootEl.querySelector(
        "button, [role='button'], .DialogButton, [class*='DialogButton'], [class*='Focusable'], [tabindex]"
      ) as HTMLElement) || rootEl;
    scrollToTop(rootEl);
    focusSteamElement(btn);
  }, []);

  useEffect(() => {
    resetScrollAndFocus();
    const raf = typeof requestAnimationFrame === "function" ? requestAnimationFrame(resetScrollAndFocus) : null;
    const t1 = setTimeout(resetScrollAndFocus, 50);
    const t2 = setTimeout(resetScrollAndFocus, 150);
    const t3 = setTimeout(resetScrollAndFocus, 300);
    const t4 = setTimeout(resetScrollAndFocus, 500);

    return () => {
      if (raf) cancelAnimationFrame(raf);
      clearTimeout(t1);
      clearTimeout(t2);
      clearTimeout(t3);
      clearTimeout(t4);
    };
  }, [resetScrollAndFocus]);

  useEffect(() => {
    let raf: number | null = null;
    let t1: any = null;
    let t2: any = null;
    let t3: any = null;
    let t4: any = null;
    if (isQAMVisible && !wasVisibleRef.current) {
      resetScrollAndFocus();
      raf = typeof requestAnimationFrame === "function" ? requestAnimationFrame(resetScrollAndFocus) : null;
      t1 = setTimeout(resetScrollAndFocus, 50);
      t2 = setTimeout(resetScrollAndFocus, 150);
      t3 = setTimeout(resetScrollAndFocus, 300);
      t4 = setTimeout(resetScrollAndFocus, 500);
    }
    wasVisibleRef.current = !!isQAMVisible;
    return () => {
      if (raf) cancelAnimationFrame(raf);
      if (t1) clearTimeout(t1);
      if (t2) clearTimeout(t2);
      if (t3) clearTimeout(t3);
      if (t4) clearTimeout(t4);
    };
  }, [isQAMVisible, resetScrollAndFocus]);

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

  const autoNode: NodeConfig = useMemo(() => {
    const existing = nodes.find(
      (n) => n.type === "auto_balancer" || n.server === "auto" || n.name?.includes("Авто-выбор") || n.name?.includes("Auto-Select")
    );
    if (existing) {
      return {
        ...existing,
        uuid: existing.uuid || "auto-balancer",
        security: existing.security || "",
        sni: existing.sni || "",
        pbk: existing.pbk || "",
        sid: existing.sid || "",
        flow: existing.flow || "",
        fp: existing.fp || "",
        name: t("autoBalancerBtn"),
      };
    }
    return {
      name: t("autoBalancerBtn"),
      server: "auto",
      port: 0,
      type: "auto_balancer",
      security: "",
      sni: "",
      pbk: "",
      sid: "",
      flow: "",
      fp: "",
      uuid: "auto-balancer",
    };
  }, [nodes, t]);

  const isAutoSelected = Boolean(
    selectedNode &&
      (selectedNode.type === "auto_balancer" ||
        selectedNode.server === "auto" ||
        selectedNode.name === autoNode.name ||
        selectedNode.name?.includes("Авто-выбор") ||
        selectedNode.name?.includes("Auto-Select") ||
        selectedNode.name === t("autoBalancerBtn"))
  );

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

        getDesktopStatus()
          .then((res) => {
            const data = unwrap<any>(res);
            if (data && mounted) {
              setTrayAutostart(data.enabled !== false);
            }
          })
          .catch(console.error);

        const rawSettings = await getSettings();
        const settings = unwrap<Settings>(rawSettings);
        let initialSelected = settings?.selected_node || null;
        if (settings && mounted) {
          setSubscriptions(settings.subscriptions || []);
          if (settings.selected_preset) {
            setPreset(settings.selected_preset);
          }
          if (settings.subscription_metadata) {
            setSubMetadata(settings.subscription_metadata);
          }
        }

        const rawNodes = await getNodes();
        const cachedNodes = unwrap<NodeConfig[]>(rawNodes) || [];
        const validNodes = Array.isArray(cachedNodes) ? cachedNodes : [];
        if (!initialSelected && validNodes.length > 0) {
          initialSelected = validNodes[0];
        }
        if (mounted) {
          setNodes(validNodes);
          setSelectedNode(initialSelected);
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

  const handleToggleTrayAutostart = async (enable: boolean) => {
    setTrayAutostart(enable);
    try {
      await setDesktopAutostart(enable);
    } catch (err) {
      console.error("Failed to toggle desktop tray:", err);
    }
  };



  const refreshSubscriptions = async () => {
    try {
      const rawSettings = await getSettings();
      const settings = unwrap<Settings>(rawSettings);
      if (settings?.subscriptions) {
        setSubscriptions(settings.subscriptions);
      }
      if (settings?.subscription_metadata) {
        setSubMetadata(settings.subscription_metadata);
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

  const handleGenerateWarp = async () => {
    setLoading(true);
    try {
      const raw = await generateWarpNode();
      const res = unwrap<any>(raw);
      if (res && res.success) {
        toaster.toast({
          title: t("success"),
          body: t("warpGeneratedSuccess"),
        });
        await refreshSubscriptions();
      } else {
        toaster.toast({ title: t("error"), body: res?.error || t("warpFailed") });
      }
    } catch (err) {
      toaster.toast({ title: t("error"), body: `${err}` });
    } finally {
      setLoading(false);
    }
  };

  const handleAddSubscription = async (urlToAdd: string) => {
    if (!urlToAdd) {
      toaster.toast({ title: t("error"), body: t("subUrlLabel") });
      return false;
    }
    setLoading(true);
    try {
      const raw = await addSubscription(urlToAdd);
      const fetchedNodes = unwrap<NodeConfig[]>(raw) || [];
      const nodeArray = Array.isArray(fetchedNodes) ? fetchedNodes : [];

      setNodes(nodeArray);
      await refreshSubscriptions();

      const addedCount = nodeArray.filter((n) => n.subscription_url === urlToAdd).length;
      toaster.toast({
        title: t("success"),
        body: t("loadedNodesForSub", { count: addedCount }),
      });
      return true;
    } catch (err) {
      toaster.toast({ title: t("error"), body: `${err}` });
      return false;
    } finally {
      setLoading(false);
    }
  };

  const openAddSubscriptionModal = () => {
    if (isModalOpenRef.current) return;
    isModalOpenRef.current = true;

    let modalResult: any = null;
    const closeModal = () => {
      isModalOpenRef.current = false;
      if (modalResult?.Close) {
        modalResult.Close();
      }
    };

    modalResult = showModal(
      <AddSubscriptionModal
        closeModal={closeModal}
        onAdd={handleAddSubscription}
        t={t}
      />,
      undefined,
      { fnOnClose: closeModal }
    );
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

  const renderPingBadge = (node: NodeConfig, isSubPinging: boolean) => {
    if (isSubPinging) {
      return (
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            fontSize: "11px",
            lineHeight: "14px",
            color: "#1a9fff",
            fontWeight: "bold",
            padding: "2px 6px",
            borderRadius: "3px",
            backgroundColor: "rgba(26, 159, 255, 0.1)",
          }}
        >
          •••
        </span>
      );
    }

    const ping = node.ping;
    if (ping === undefined || ping === null || typeof ping !== "number" || !Number.isFinite(ping)) {
      return null;
    }

    if (ping < 0) {
      return (
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            fontSize: "11px",
            lineHeight: "14px",
            color: "#888888",
            fontWeight: "normal",
            padding: "2px 6px",
            borderRadius: "3px",
            backgroundColor: "rgba(255, 255, 255, 0.05)",
          }}
        >
          Unavailable
        </span>
      );
    }

    let pingColor = "#52c41a"; // green (<110ms)
    if (ping > 280) {
      pingColor = "#ff4d4f"; // red (>280ms)
    } else if (ping > 180) {
      pingColor = "#fa8c16"; // orange (181-280ms)
    } else if (ping > 110) {
      pingColor = "#faad14"; // amber/yellow (111-180ms)
    }

    const flagPart = node.country_flag ? `${node.country_flag} ` : "";
    const pingPart = ping === 0 ? "<1 ms" : `${ping} ms`;
    const downPart =
      typeof node.speed_down === "number" && Number.isFinite(node.speed_down) && node.speed_down >= 0
        ? ` ↓${node.speed_down.toFixed(2)}Mbps`
        : "";
    const upPart =
      typeof node.speed_up === "number" && Number.isFinite(node.speed_up) && node.speed_up >= 0
        ? ` ↑${node.speed_up.toFixed(2)}Mbps`
        : "";

    return (
      <div
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "5px",
          padding: "2px 6px",
          borderRadius: "3px",
          backgroundColor: "rgba(255, 255, 255, 0.06)",
          lineHeight: "14px",
          whiteSpace: "nowrap",
        }}
      >
        <span
          style={{
            display: "inline-block",
            width: "3px",
            height: "10px",
            borderRadius: "1px",
            backgroundColor: pingColor,
          }}
        />
        <span
          style={{
            fontSize: "11px",
            fontWeight: "bold",
            color: pingColor,
            fontFamily: "monospace",
            lineHeight: "14px",
          }}
        >
          {`${flagPart}${pingPart}${downPart}${upPart}`}
        </span>
      </div>
    );
  };

  const handleCheckPing = async (subUrl: string) => {
    if (pingingSubUrl) return;
    setPingingSubUrl(subUrl);
    try {
      const raw = await pingNodes(subUrl);
      const updatedNodes = unwrap<NodeConfig[]>(raw);
      if (Array.isArray(updatedNodes) && updatedNodes.length > 0) {
        setNodes(updatedNodes);
      }
      if (connected && selectedNode?.subscription_url === subUrl) {
        const rawDelay = await getRealDelay();
        const delayData = unwrap<{ success: boolean; delay_ms: number }>(rawDelay);
        if (delayData?.success && delayData?.delay_ms) {
          setRealDelay(delayData.delay_ms);
        }
      }
    } catch (err) {
      console.error("handleCheckPing error:", err);
    } finally {
      setPingingSubUrl(null);
    }
  };

  const handleUpdateSubscription = async (urlToUpdate: string) => {
    setLoading(true);
    try {
      const raw = await updateSubscription(urlToUpdate);
      const fetchedNodes = unwrap<NodeConfig[]>(raw) || [];
      const nodeArray = Array.isArray(fetchedNodes) ? fetchedNodes : [];

      setNodes(nodeArray);
      const updatedCount = nodeArray.filter((n) => n.subscription_url === urlToUpdate).length;

      toaster.toast({
        title: t("success"),
        body: t("loadedNodesForSub", { count: updatedCount }),
      });
    } catch (err) {
      toaster.toast({ title: t("error"), body: `${err}` });
    } finally {
      setLoading(false);
    }
  };

  const handleAutoSelectBest = async () => {
    if (isAutoSelected && connected) {
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
      return;
    }

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
    setSelectedNode(autoNode);

    try {
      const raw = await autoSelectBestNode();
      const res = unwrap<{ success: boolean; node_name?: string; ping?: number; server?: string; error?: string; best_node?: NodeConfig }>(raw);
      if (res && res.success) {
        setConnected(true);
        if (res.best_node) {
          setSelectedNode({
            ...autoNode,
            best_node: res.best_node,
          });
        }
        const serverName = stripEmojis(res.node_name || autoNode.name);
        const pingStr = res.ping ? ` (${res.ping} ms)` : "";
        const bodyMsg = lang === "russian"
          ? `Выбран сервер: ${serverName}${pingStr}`
          : t("toastSelectedNode", { name: `${serverName}${pingStr}` });
        toaster.toast({
          title: t("autoBalancerBtn"),
          body: bodyMsg,
        });
      } else {
        toaster.toast({ title: t("error"), body: res?.error || t("tunnelStartFailed") });
        setConnected(false);
      }
    } catch (err) {
      toaster.toast({ title: t("error"), body: `${err}` });
      setConnected(false);
    } finally {
      setLoading(false);
    }
  };

  const handleSelectNode = async (node: NodeConfig) => {
    if (node.type === "auto_balancer" || node.server === "auto") {
      return handleAutoSelectBest();
    }

    const isCurrentActive =
      selectedNode &&
      (selectedNode.name === node.name ||
        (selectedNode.type === "auto_balancer" && node.type === "auto_balancer") ||
        (selectedNode.server === "auto" && node.server === "auto")) &&
      (!selectedNode.subscription_url ||
        !node.subscription_url ||
        selectedNode.subscription_url === node.subscription_url) &&
      connected;

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
          toaster.toast({ title: t("tunnelStarted"), body: t("tunnelStartedBody", { name: stripEmojis(node.name) }) });
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

  const handleToggleConnect = async () => {
    if (connected) {
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
      let targetNode = selectedNode;
      if (!targetNode && nodes.length > 0) {
        targetNode = nodes[0];
        setSelectedNode(targetNode);
      }
      if (!targetNode) {
        toaster.toast({ title: t("toastWarning"), body: t("noNodeSelected") });
        return;
      }
      if (targetNode.type === "auto_balancer" || targetNode.server === "auto" || isAutoSelected) {
        return handleAutoSelectBest();
      }
      setLoading(true);
      try {
        const rawSuccess = await connectNode(targetNode);
        const success = unwrap<boolean>(rawSuccess);
        if (success) {
          setConnected(true);
          toaster.toast({ title: t("tunnelStarted"), body: t("tunnelStartedBody", { name: stripEmojis(targetNode.name) }) });
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

  return (
    <PanelSection>
      <style>{SELECTED_BUTTON_CSS}</style>
      <div className="sub-deck-root">
        {/* Кнопка Подключить / Отключить */}
        <PanelSectionRow>
          <div ref={connectBtnRef} style={{ width: "100%" }} tabIndex={-1}>
            <ButtonItem
              layout="below"
              highlightOnFocus={false}
              onClick={handleToggleConnect}
              disabled={loading}
              bottomSeparator="none"
            >
              <span style={{ color: connected ? "#ff6b6b" : "#4ade80", fontWeight: "bold" }}>
                {connected ? t("disconnectVpn") : t("connectVpn")}
              </span>
            </ButtonItem>
          </div>
        </PanelSectionRow>

        {selectedNode && (
          <div
            style={{
              textAlign: "center",
              fontSize: "11px",
              color: "#a5a5a5",
              marginTop: "6px",
              marginBottom: "8px",
              padding: "0 6px",
              lineHeight: "1.4",
              wordBreak: "break-word",
            }}
          >
            {connected
              ? `${t("tunnelStarted")}: ${isAutoSelected ? (selectedNode.best_node?.name ? `${t("autoBalancerBtn")} (${stripEmojis(selectedNode.best_node.name)})` : t("autoBalancerBtn")) : stripEmojis(selectedNode.name)}`
              : t("selectedServer", { name: isAutoSelected ? (selectedNode.best_node?.name ? `${t("autoBalancerBtn")} (${stripEmojis(selectedNode.best_node.name)})` : t("autoBalancerBtn")) : stripEmojis(selectedNode.name) })}
          </div>
        )}
        {!connected && !selectedNode && (
          <div
            style={{
              textAlign: "center",
              fontSize: "11px",
              color: "#888",
              marginTop: "6px",
              marginBottom: "8px",
              padding: "0 6px",
              lineHeight: "1.4",
            }}
          >
            {t("noNodeSelected")}
          </div>
        )}

        {/* Разделитель строго ПОД надписью статуса сервера */}
        <div
          style={{
            width: "100%",
            height: "1px",
            backgroundColor: "rgba(255, 255, 255, 0.12)",
            margin: "4px 0 10px 0",
          }}
        />

        {/* Выбор пресета маршрутизации */}
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            highlightOnFocus={false}
            onClick={() => setPresetExpanded(!presetExpanded)}
          >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%", overflow: "hidden" }}>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, textAlign: "left" }}>
              {t("presetLabel")}
            </span>
            <span style={{ fontSize: "10px", color: "#888", marginLeft: "6px", flexShrink: 0 }}>
              {presetExpanded ? "▼" : "▶"}
            </span>
          </div>
        </ButtonItem>
      </PanelSectionRow>

      {presetExpanded && (
        <>
          {PRESET_OPTIONS.map((item) => {
            const isSelected = preset === item.key;
            const label = t(item.labelKey);
            return (
              <PanelSectionRow key={item.key}>
                <div className={isSelected ? "sub-deck-selected" : ""} style={{ width: "100%" }}>
                  <ButtonItem
                    layout="below"
                    highlightOnFocus={false}
                    onClick={() => {
                      handlePresetChange(item.key, label);
                      setPresetExpanded(false);
                    }}
                  >
                    <div
                      style={{
                        fontWeight: isSelected ? "bold" : "normal",
                        color: isSelected ? "#1a9fff" : "inherit",
                      }}
                    >
                      {label}
                    </div>
                  </ButtonItem>
                </div>
              </PanelSectionRow>
            );
          })}
        </>
      )}

      {/* Выбор фильтра протоколов */}
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          highlightOnFocus={false}
          onClick={() => setProtocolExpanded(!protocolExpanded)}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%", overflow: "hidden" }}>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, textAlign: "left" }}>
              {t("protocolFilterLabel")}
            </span>
            <span style={{ fontSize: "10px", color: "#888", marginLeft: "6px", flexShrink: 0 }}>
              {protocolExpanded ? "▼" : "▶"}
            </span>
          </div>
        </ButtonItem>
      </PanelSectionRow>

      {protocolExpanded && (
        <>
          {PROTOCOL_OPTIONS.map((item) => {
            const isSelected = protocolFilter === item.key;
            const label = t(item.labelKey);
            return (
              <PanelSectionRow key={item.key}>
                <div className={isSelected ? "sub-deck-selected" : ""} style={{ width: "100%" }}>
                  <ButtonItem
                    layout="below"
                    highlightOnFocus={false}
                    onClick={() => {
                      setProtocolFilter(item.key);
                      setProtocolExpanded(false);
                    }}
                  >
                    <div
                      style={{
                        fontWeight: isSelected ? "bold" : "normal",
                        color: isSelected ? "#1a9fff" : "inherit",
                      }}
                    >
                      {label}
                    </div>
                  </ButtonItem>
                </div>
              </PanelSectionRow>
            );
          })}
        </>
      )}

      {/* Кнопка выбора авто-балансировщика */}
      <PanelSectionRow>
        <div className={isAutoSelected ? "sub-deck-selected" : ""} style={{ width: "100%" }}>
          <ButtonItem
            layout="below"
            highlightOnFocus={false}
            onClick={handleAutoSelectBest}
            disabled={loading}
          >
            <span style={{ color: isAutoSelected ? "#1a9fff" : "inherit", fontWeight: isAutoSelected ? "bold" : "normal" }}>
              {t("autoBalancerBtn")}
            </span>
          </ButtonItem>
        </div>
      </PanelSectionRow>

      {/* Кнопка добавления подписки через модальное окно */}
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          highlightOnFocus={false}
          onClick={openAddSubscriptionModal}
          disabled={loading}
        >
          {loading ? t("updating") : t("addSubBtn")}
        </ButtonItem>
      </PanelSectionRow>

      <PanelSectionRow>
        <ButtonItem
          layout="below"
          highlightOnFocus={false}
          onClick={handleGenerateWarp}
          disabled={loading}
        >
          {t("generateWarpBtn")}
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
            const filteredSubNodes =
              protocolFilter === "all"
                ? subNodes
                : subNodes.filter((node) => getNodeCategory(node) === protocolFilter);
            const meta = subMetadata[url] || {};
            const domainLabel = meta.name ? meta.name : getDomainLabel(url, lang);
            const isExpanded =
              expandedSubs[url] !== undefined
                ? expandedSubs[url]
                : connected && selectedNode?.subscription_url === url;

            const usedBytes = (meta.upload || 0) + (meta.download || 0);
            const hasTrafficInfo = meta.total && meta.total > 0;
            const expiryLabel = meta.expire ? formatExpiry(meta.expire, lang) : "";
            const isSubPinging = pingingSubUrl === url;

            return (
              <PanelSection key={idx}>
                {/* Заголовок подписки в виде кнопки раскрытия */}
                <PanelSectionRow>
                  <ButtonItem
                    layout="below"
                    highlightOnFocus={false}
                    onClick={() => setExpandedSubs((prev) => ({ ...prev, [url]: !prev[url] }))}
                  >
                    <div style={{ display: "flex", flexDirection: "column", width: "100%", gap: "4px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%", minWidth: 0 }}>
                        <span
                          style={{
                            fontSize: "12px",
                            fontWeight: "bold",
                            color: "#e0e0e0",
                            textAlign: "left",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                            flex: 1,
                            minWidth: 0,
                          }}
                          title={domainLabel}
                        >
                          {stripEmojis(domainLabel)}
                          <span style={{ fontSize: "11px", fontWeight: "normal", color: "#888", marginLeft: "6px" }}>
                            {protocolFilter === "all" ? `(${subNodes.length})` : `(${filteredSubNodes.length}/${subNodes.length})`}
                          </span>
                        </span>
                        <span style={{ fontSize: "10px", color: "#888", marginLeft: "6px", flexShrink: 0 }}>
                          {isExpanded ? "▼" : "▶"}
                        </span>
                      </div>

                      {(hasTrafficInfo || expiryLabel) && (
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "10px", color: "#888" }}>
                          {hasTrafficInfo && (
                            <span>
                              {formatBytes(usedBytes)} / {formatBytes(meta.total)}
                            </span>
                          )}
                          {expiryLabel && (
                            <span style={{ color: expiryLabel.includes("истёк") || expiryLabel.includes("Expired") ? "#ff4d4f" : "#1a9fff" }}>
                              {expiryLabel}
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  </ButtonItem>
                </PanelSectionRow>

                {isExpanded && (
                  <>
                    {/* Список нод этой подписки */}
                    {filteredSubNodes.length > 0 ? (
                      <div style={{ maxHeight: "250px", overflowY: "auto", overflowX: "hidden", paddingRight: "4px", marginBottom: "8px" }}>
                        {filteredSubNodes.map((node, nIdx) => {
                          const isSelected = Boolean(
                            selectedNode &&
                              selectedNode.name === node.name &&
                              (!selectedNode.subscription_url ||
                                !node.subscription_url ||
                                selectedNode.subscription_url === node.subscription_url)
                          );
                          const pingBadge = renderPingBadge(node, isSubPinging);
                          const cleanName = stripEmojis(node.name);
                          return (
                            <PanelSectionRow key={`${node.name}-${node.server}-${node.port}-${nIdx}`}>
                              <div
                                className="sub-deck-node-item"
                                style={{
                                  width: "100%",
                                  display: "flex",
                                  flexDirection: "column",
                                  marginBottom: nIdx < filteredSubNodes.length - 1 ? "10px" : "2px",
                                }}
                              >
                                <div
                                  className={
                                    isSelected
                                      ? "sub-deck-selected sub-deck-node-btn-wrap"
                                      : "sub-deck-node-btn-wrap"
                                  }
                                  style={{ width: "100%" }}
                                >
                                  <ButtonItem
                                    {...({ className: "sub-deck-node-field" } as any)}
                                    layout="below"
                                    highlightOnFocus={false}
                                    bottomSeparator="none"
                                    onClick={() => handleSelectNode(node)}
                                    disabled={loading}
                                  >
                                    <div style={{ width: "100%", minWidth: 0, textAlign: "left" }}>
                                      <div
                                        style={{
                                          fontWeight: isSelected ? "bold" : "normal",
                                          color: isSelected ? "#1a9fff" : "inherit",
                                          overflow: "hidden",
                                          textOverflow: "ellipsis",
                                          whiteSpace: "nowrap",
                                        }}
                                        title={cleanName}
                                      >
                                        {cleanName}
                                      </div>
                                      <div
                                        style={{
                                          fontSize: "0.8em",
                                          color: "#888",
                                          overflow: "hidden",
                                          textOverflow: "ellipsis",
                                          whiteSpace: "nowrap",
                                        }}
                                      >
                                        {getNodeMethodLabel(node)}
                                      </div>
                                    </div>
                                  </ButtonItem>
                                </div>
                                {pingBadge && (
                                  <div
                                    className="sub-deck-node-ping"
                                    style={{
                                      display: "flex",
                                      justifyContent: "flex-start",
                                      alignItems: "center",
                                      marginTop: "3px",
                                      paddingLeft: "2px",
                                    }}
                                  >
                                    {pingBadge}
                                  </div>
                                )}
                              </div>
                            </PanelSectionRow>
                          );
                        })}
                      </div>
                    ) : (
                      <PanelSectionRow>
                        <div style={{ color: "#888", fontSize: "12px", padding: "4px 0" }}>
                          {subNodes.length === 0 ? t("noNodesFound") : t("noNodesForFilter")}
                        </div>
                      </PanelSectionRow>
                    )}

                    {/* Статус подключенного сервера */}
                    {connected && selectedNode && selectedNode.subscription_url === url && (
                      <PanelSectionRow>
                        <div style={{ color: "#1a9fff", fontWeight: "bold", padding: "4px 0", fontSize: "12px" }}>
                          {t("selectedServer", { name: stripEmojis(selectedNode.name) }) + (realDelay ? ` • ${realDelay} ms` : "")}
                        </div>
                      </PanelSectionRow>
                    )}

                    {/* Кнопка Обновить */}
                    <PanelSectionRow>
                      <ButtonItem
                        layout="below"
                        highlightOnFocus={false}
                        onClick={() => handleUpdateSubscription(url)}
                        disabled={loading}
                      >
                        {t("updateBtn")}
                      </ButtonItem>
                    </PanelSectionRow>

                    <PanelSectionRow>
                      <ButtonItem
                        layout="below"
                        highlightOnFocus={false}
                        onClick={() => handleCheckPing(url)}
                        disabled={loading || pingingSubUrl !== null}
                      >
                        {isSubPinging ? t("measuringPing") : t("checkPing")}
                      </ButtonItem>
                    </PanelSectionRow>

                    {/* Кнопка Удалить */}
                    <PanelSectionRow>
                      <div style={{ color: "#ff6347" }}>
                        <ButtonItem
                          layout="below"
                          highlightOnFocus={false}
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

      {/* Секция интеграции с Desktop Mode */}
      <PanelSection title={t("desktopTitle")}>
        <PanelSectionRow>
          <ToggleField
            label={t("desktopTrayToggle")}
            description={t("desktopTrayToggleDesc")}
            checked={trayAutostart}
            onChange={handleToggleTrayAutostart}
          />
        </PanelSectionRow>
      </PanelSection>

      {/* Кнопка экспорта логов */}
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          highlightOnFocus={false}
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
          highlightOnFocus={false}
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
      </div>
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
