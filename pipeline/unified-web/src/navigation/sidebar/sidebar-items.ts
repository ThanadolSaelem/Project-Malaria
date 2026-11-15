import {
  Activity,
  Ban,
  BellRing,
  Bot,
  Brain,
  Bug,
  ClipboardList,
  Compass,
  Eye,
  FolderOpen,
  FolderSync,
  Globe,
  LayoutDashboard,
  type LucideIcon,
  MessageSquare,
  Network,
  Plug,
  Radar,
  Radio,
  ScrollText,
  Settings2,
  ShieldAlert,
  Sparkles,
  Target,
  Terminal,
  Wrench,
} from "lucide-react";

export type NavBadge = "new" | "soon";

export interface NavSubItem {
  id: string;
  title: string;
  url: string;
  icon?: LucideIcon;
  badge?: NavBadge;
  disabled?: boolean;
  newTab?: boolean;
}

interface NavItemBase {
  id: string;
  title: string;
  icon?: LucideIcon;
  badge?: NavBadge;
  disabled?: boolean;
  newTab?: boolean;
}

export interface NavMainLinkItem extends NavItemBase {
  url: string;
  subItems?: never;
}

export interface NavMainParentItem extends NavItemBase {
  url?: string;
  subItems: NavSubItem[];
}

export type NavMainItem = NavMainLinkItem | NavMainParentItem;

export interface NavGroup {
  id: number;
  label?: string;
  items: NavMainItem[];
}

export const sidebarItems: NavGroup[] = [
  {
    id: 0,
    label: "Operations",
    items: [
      { id: "dashboard", title: "Dashboard", url: "/dashboard", icon: LayoutDashboard },
      {
        id: "workspace-ai",
        title: "AI Studio",
        url: "/ai",
        icon: Sparkles,
        subItems: [
          { id: "ai-chat", title: "Agent Sessions", url: "/ai", icon: MessageSquare },
          { id: "ai-plugins", title: "Subagents & Plugins", url: "/ai/plugins", icon: Bot },
          { id: "ai-goals", title: "Autonomous Goals", url: "/ai/goals", icon: Target },
          { id: "ai-scheduled", title: "Scheduled Workflows", url: "/ai/scheduled-tasks", icon: ClipboardList },
          { id: "ai-live", title: "Live Stream", url: "/ai/live", icon: Activity },
          { id: "ai-channels", title: "Channels", url: "/ai/channels", icon: Radio },
        ],
      },
      { id: "chat", title: "Pentest Chat", url: "/chat", icon: MessageSquare },
      { id: "tasks", title: "Pentest Tasks", url: "/function/tasks", icon: Target },
      { id: "findings", title: "Findings", url: "/function/findings", icon: Bug },
      { id: "workspace-observer", title: "Live Monitor", url: "/observer", icon: Eye },
    ],
  },
  {
    id: 1,
    label: "Attack Surface & Recon",
    items: [
      { id: "ss-dashboard", title: "Recon Overview", url: "/scopesentry/dashboard/index", icon: Radar },
      { id: "ss-projects", title: "Projects", url: "/scopesentry/project-management/index", icon: FolderOpen },
      { id: "ss-assets", title: "Asset Inventory", url: "/scopesentry/asset-information/index", icon: Globe },
      { id: "assets", title: "Target Assets", url: "/function/assets", icon: Network },
      { id: "ss-map", title: "Attack Surface Map", url: "/scopesentry/map", icon: Compass },
      { id: "sync", title: "Asset Sync", url: "/function/sync", icon: FolderSync },
      {
        id: "ss-scans-group",
        title: "Scan Operations",
        url: "/scopesentry/task-management/ScanTask",
        icon: Target,
        subItems: [
          { id: "ss-tasks", title: "Scan Tasks", url: "/scopesentry/task-management/ScanTask", icon: Target },
          { id: "ss-scheduled", title: "Scheduled Scans", url: "/scopesentry/task-management/ScheduledTask", icon: ClipboardList },
          { id: "ss-templates", title: "Scan Templates", url: "/scopesentry/task-management/ScanTemplate", icon: ScrollText },
        ],
      },
      {
        id: "ss-arsenal-group",
        title: "Recon Arsenal",
        url: "/scopesentry/poc-management/index",
        icon: Wrench,
        subItems: [
          { id: "ss-poc", title: "POC Library", url: "/scopesentry/poc-management/index", icon: Bug },
          { id: "ss-fingerprints", title: "Fingerprints", url: "/scopesentry/fingerprint-management/index", icon: Wrench },
          { id: "ss-plugins", title: "Scanner Plugins", url: "/scopesentry/plugin-management/index", icon: Plug },
          { id: "ss-nodes", title: "Scanner Nodes", url: "/scopesentry/node-management/index", icon: Network },
        ],
      },
    ],
  },
  {
    id: 2,
    label: "Telemetry & Workspace",
    items: [
      { id: "traffic", title: "HTTP Traffic", url: "/function/traffic", icon: Activity },
      { id: "commands", title: "Tool Execution", url: "/function/commands", icon: Terminal },
      { id: "llm-records", title: "LLM Recording", url: "/function/llm-records", icon: Radio },
      { id: "workspace", title: "Workspace Files", url: "/function/workspace", icon: FolderOpen },
    ],
  },
  {
    id: 3,
    label: "System",
    items: [
      { id: "llm", title: "LLM Models", url: "/system/llm", icon: Brain },
      { id: "agents", title: "Agents", url: "/system/agents", icon: Bot },
      { id: "mcp", title: "MCP Servers", url: "/system/mcp", icon: Plug },
      { id: "skills", title: "Skills", url: "/system/skills", icon: Sparkles },
      { id: "tools", title: "Custom Tools", url: "/system/tools", icon: Wrench },
      { id: "ai-settings", title: "AI Studio Settings", url: "/ai/settings", icon: Settings2 },
      { id: "notify", title: "Notifications", url: "/system/notify", icon: BellRing },
      { id: "intercept", title: "Interception Rules", url: "/system/intercept", icon: ShieldAlert },
      { id: "asset-intercept", title: "Asset Interception", url: "/system/intercept/assets", icon: Ban },
      { id: "approvals", title: "Approval Records", url: "/system/intercept/approvals", icon: ClipboardList },
      { id: "logs", title: "System Logs", url: "/system/logs", icon: ScrollText },
      { id: "settings", title: "System Settings", url: "/system/settings", icon: Settings2 },
    ],
  },
];
