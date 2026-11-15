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
  matchUrls?: string[];
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
        id: "chat",
        title: "AI Pentest Studio",
        url: "/chat",
        icon: Sparkles,
        matchUrls: ["/chat", "/ai"],
      },
      {
        id: "tasks",
        title: "Pentest Missions",
        url: "/function/tasks",
        icon: Target,
        matchUrls: ["/function/tasks", "/ai/goals", "/ai/scheduled-tasks"],
      },
      { id: "findings", title: "Findings", url: "/function/findings", icon: Bug },
      {
        id: "workspace-observer",
        title: "Live Monitor",
        url: "/observer",
        icon: Eye,
        matchUrls: ["/observer", "/ai/live"],
      },
    ],
  },
  {
    id: 1,
    label: "Attack Surface & Recon",
    items: [
      { id: "ss-dashboard", title: "Recon Overview", url: "/scopesentry/dashboard/index", icon: Radar },
      { id: "ss-projects", title: "Projects", url: "/scopesentry/project-management/index", icon: FolderOpen },
      {
        id: "assets",
        title: "Target Assets & Inventory",
        url: "/function/assets",
        icon: Globe,
        matchUrls: ["/function/assets", "/scopesentry/asset-information/index", "/function/sync"],
      },
      { id: "ss-map", title: "Attack Surface Map", url: "/scopesentry/map", icon: Compass },
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
    label: "Telemetry & Safety",
    items: [
      { id: "traffic", title: "HTTP Traffic", url: "/function/traffic", icon: Activity },
      { id: "commands", title: "Tool Execution", url: "/function/commands", icon: Terminal },
      { id: "llm-records", title: "LLM Recording", url: "/function/llm-records", icon: Radio },
      {
        id: "approvals",
        title: "Safety & Approvals",
        url: "/system/intercept/approvals",
        icon: ShieldAlert,
        matchUrls: ["/system/intercept/approvals", "/system/intercept", "/system/intercept/assets"],
      },
      { id: "workspace", title: "Workspace Files", url: "/function/workspace", icon: FolderOpen },
    ],
  },
  {
    id: 3,
    label: "System & AI Config",
    items: [
      {
        id: "llm",
        title: "LLM Models",
        url: "/system/llm",
        icon: Brain,
        matchUrls: ["/system/llm", "/ai/settings"],
      },
      {
        id: "agents",
        title: "Agents & Subagents",
        url: "/system/agents",
        icon: Bot,
        matchUrls: ["/system/agents", "/ai/plugins"],
      },
      { id: "mcp", title: "MCP Servers", url: "/system/mcp", icon: Plug },
      {
        id: "skills",
        title: "Skills & Tools",
        url: "/system/skills",
        icon: Wrench,
        matchUrls: ["/system/skills", "/system/tools"],
      },
      {
        id: "notify",
        title: "Notifications & Channels",
        url: "/system/notify",
        icon: BellRing,
        matchUrls: ["/system/notify", "/ai/channels"],
      },
      {
        id: "settings",
        title: "System Settings & Logs",
        url: "/system/settings",
        icon: Settings2,
        matchUrls: ["/system/settings", "/system/logs"],
      },
    ],
  },
];
