export interface NodeConfig {
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

export interface SubscriptionMetadata {
  name?: string;
  upload?: number;
  download?: number;
  total?: number;
  expire?: number;
  last_updated?: number;
}

export interface Settings {
  subscriptions: string[];
  selected_node: NodeConfig | null;
  selected_preset?: string;
  subscription_metadata?: Record<string, SubscriptionMetadata>;
  update_intervals?: Record<string, number>;
  last_update_times?: Record<string, number>;
}

export type TranslationKeys =
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
  | "presetBypassRu"
  | "presetGaming"
  | "presetRoscom"
  | "addFreeBtn"
  | "loadedNodesForSub"
  | "freeConfigsUpdated"
  | "supportBtn"
  | "logCreatedTitle"
  | "logCreated"
  | "pasteBtn"
  | "pastedFromClipboard"
  | "clipboardEmptyOrBlocked"
  | "desktopTitle"
  | "desktopTrayToggle"
  | "desktopTrayToggleDesc";

