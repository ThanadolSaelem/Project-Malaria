"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { ComponentType, CSSProperties, ReactNode } from "react";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CopyIcon, MessageSquareIcon, NetworkIcon, RefreshCwIcon, ShieldAlertIcon, TerminalIcon } from "lucide-react";
import { toast } from "sonner";

import type { UnifiedModuleProps } from "@/modules/types";
import type { SharedContextResponse } from "@/lib/types";
import { AccountSwitcher } from "@/app/(main)/_components/sidebar/account-switcher";
import { AppSidebar } from "@/app/(main)/_components/sidebar/app-sidebar";
import { LayoutControls } from "@/app/(main)/_components/sidebar/layout-controls";
import { SearchDialog } from "@/app/(main)/_components/sidebar/search-dialog";
import { ThemeSwitcher } from "@/app/(main)/_components/sidebar/theme-switcher";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { useCurrentUser } from "@/hooks/use-current-user";
import { api } from "@/lib/api";
import { auth } from "@/lib/auth";
import { getClientCookie } from "@/lib/cookie.client";
import {
  SIDEBAR_COLLAPSIBLE_VALUES,
  SIDEBAR_VARIANT_VALUES,
  type SidebarCollapsible,
  type SidebarVariant,
} from "@/lib/preferences/layout";
import { PREFERENCE_DEFAULTS } from "@/lib/preferences/preferences-config";
import { ARTEX_AUTH_REQUIRED_EVENT } from "@/lib/unified-auth-navigation";
import {
  moduleForPath,
  modulePath,
  namespacedModulePath,
  SCOPE_SENTRY_ASSETS,
  type UnifiedModuleId,
  UNIFIED_MODULES,
} from "@/lib/unified-modules";
import { applyUnifiedTheme } from "@/lib/unified-theme";
import { cn } from "@/lib/utils";
import { usePreferencesStore } from "@/stores/preferences/preferences-provider";

function isFullBleed(pathname: string) {
  const p = (() => {
    try {
      return decodeURIComponent(pathname);
    } catch {
      return pathname;
    }
  })();
  const normalized = p.replace(/\/+$/, "");
  return normalized.startsWith("/function/tasks/");
}

interface WorkspaceModeTab {
  id: string;
  label: string;
  subtitle: string;
  url: string;
}

interface WorkspaceModeGroup {
  id: string;
  title: string;
  showSyncButton?: boolean;
  tabs: WorkspaceModeTab[];
}

const UNIFIED_WORKSPACE_GROUPS: readonly WorkspaceModeGroup[] = [
  {
    id: "ai-pentest-studio",
    title: "AI Pentest Studio",
    showSyncButton: true,
    tabs: [
      {
        id: "pentest-chat",
        label: "Pentest Graph Chat",
        subtitle: "Interactive Pentest Agent + Knowledge Graph + Safety Gate",
        url: "/chat",
      },
      {
        id: "deep-agent-ide",
        label: "Deep Agent IDE & Terminal",
        subtitle: "Multi-Session Sandbox + Code Audit + 7 MCP Servers",
        url: "/ai",
      },
    ],
  },
  {
    id: "pentest-missions",
    title: "Pentest Missions",
    tabs: [
      {
        id: "pentest-tasks",
        label: "Pentest Tasks & Graphs",
        subtitle: "Autonomous Planner/Worker Missions & Coverage Graph",
        url: "/function/tasks",
      },
      {
        id: "autonomous-goals",
        label: "Autonomous Goals",
        subtitle: "Long-Running Verify-Loop Objectives",
        url: "/ai/goals",
      },
      {
        id: "scheduled-workflows",
        label: "Scheduled Workflows",
        subtitle: "Recurring Cron & Playbook Automation",
        url: "/ai/scheduled-tasks",
      },
    ],
  },
  {
    id: "live-monitor",
    title: "Live Monitor",
    tabs: [
      {
        id: "observer",
        label: "Telemetry & Subagent Graph",
        subtitle: "Real-Time Orchestration & Subagent Status",
        url: "/observer",
      },
      {
        id: "live-stream",
        label: "Live Agent Stream",
        subtitle: "Live Terminal & Tool Execution Stream",
        url: "/ai/live",
      },
    ],
  },
  {
    id: "target-assets",
    title: "Target Assets & Inventory",
    showSyncButton: true,
    tabs: [
      {
        id: "target-assets",
        label: "Target Assets & Scope",
        subtitle: "Pentest Scope, Companies & Attack Graph Assets",
        url: "/function/assets",
      },
      {
        id: "recon-inventory",
        label: "Recon Asset Inventory",
        subtitle: "Subdomains, Ports, Fingerprints & Screenshots",
        url: "/scopesentry/asset-information/index",
      },
      {
        id: "recon-sync",
        label: "Recon Sync Control",
        subtitle: "ScopeSentry MCP Data Source & Selective Sync",
        url: "/function/sync",
      },
    ],
  },
  {
    id: "safety-approvals",
    title: "Safety & Approvals",
    tabs: [
      {
        id: "approvals",
        label: "Approval Records",
        subtitle: "Human-in-the-Loop Command Decisions",
        url: "/system/intercept/approvals",
      },
      {
        id: "intercept-rules",
        label: "Command Interception Rules",
        subtitle: "Regex & Tool Safety Policies",
        url: "/system/intercept",
      },
      {
        id: "asset-blocklist",
        label: "Asset Blocklist",
        subtitle: "Out-of-Scope Domains, IPs & CIDRs",
        url: "/system/intercept/assets",
      },
    ],
  },
  {
    id: "llm-models",
    title: "LLM Models",
    tabs: [
      {
        id: "llm-pool",
        label: "Model Pool & Failover Profiles",
        subtitle: "LiteLLM Profiles, Routing & Rate Limits",
        url: "/system/llm",
      },
      {
        id: "ide-runtime",
        label: "Agent Runtime Settings",
        subtitle: "Deep Agent IDE Runtime & Environment",
        url: "/ai/settings",
      },
    ],
  },
  {
    id: "agents-subagents",
    title: "Agents & Subagents",
    tabs: [
      {
        id: "pentest-agents",
        label: "Pentest Agents & Prompts",
        subtitle: "Planner, Worker, Retester & Custom Triggers",
        url: "/system/agents",
      },
      {
        id: "ide-subagents",
        label: "IDE Subagents & Extensions",
        subtitle: "Subagent Roles, Extensions & Runtime Bindings",
        url: "/ai/plugins",
      },
    ],
  },
  {
    id: "skills-tools",
    title: "Skills & Tools",
    tabs: [
      {
        id: "skills",
        label: "Agent Skills (SKILL.md)",
        subtitle: "Playbooks, Workflows & Agent Skill Visibility",
        url: "/system/skills",
      },
      {
        id: "custom-tools",
        label: "Custom & Built-in Tools",
        subtitle: "Python/Shell Custom Tools & Schemas",
        url: "/system/tools",
      },
    ],
  },
  {
    id: "notifications-channels",
    title: "Notifications & Channels",
    tabs: [
      {
        id: "webhooks",
        label: "Alert Webhooks",
        subtitle: "Vulnerability Push Notifications",
        url: "/system/notify",
      },
      {
        id: "bot-channels",
        label: "Interactive Bot Channels",
        subtitle: "Two-Way ChatOps & Messaging Channels",
        url: "/ai/channels",
      },
    ],
  },
  {
    id: "system-settings-logs",
    title: "System Settings & Logs",
    tabs: [
      {
        id: "system-settings",
        label: "System Settings",
        subtitle: "Concurrency, Confinement & Global Engine Config",
        url: "/system/settings",
      },
      {
        id: "system-logs",
        label: "System Logs",
        subtitle: "Live Backend Audit & Engine Logs",
        url: "/system/logs",
      },
    ],
  },
];

function isModeTabActive(pathname: string, tabUrl: string): boolean {
  if (tabUrl === "/ai") {
    return (
      pathname === "/ai" ||
      pathname.startsWith("/ai/s/") ||
      pathname.startsWith("/ai/session")
    );
  }
  if (tabUrl === "/system/intercept") {
    return pathname === "/system/intercept";
  }
  if (tabUrl === "/function/tasks") {
    return pathname === "/function/tasks";
  }
  return pathname === tabUrl || pathname.startsWith(`${tabUrl}/`);
}

function resolveWorkspaceGroup(pathname: string): WorkspaceModeGroup | null {
  for (const group of UNIFIED_WORKSPACE_GROUPS) {
    if (group.tabs.some((tab) => isModeTabActive(pathname, tab.url))) {
      return group;
    }
  }
  return null;
}

function readPref<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  if (typeof document === "undefined") return fallback;
  const value = getClientCookie(key);
  return value && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
}

const QwenModule = dynamic(() => import("@/modules/qwen").then((module) => module.default), {
  ssr: false,
  loading: () => <ModuleLoading label="Loading AI Studio…" />,
});
const ScopeSentryModule = dynamic(() => import("@/modules/scopesentry").then((module) => module.default), {
  ssr: false,
  loading: () => <ModuleLoading label="Loading Attack Surface & Recon…" />,
});
const ObserverModule = dynamic(() => import("@/modules/observer").then((module) => module.default), {
  ssr: false,
  loading: () => <ModuleLoading label="Loading Live Monitor…" />,
});

const MODULE_COMPONENTS: Record<UnifiedModuleId, ComponentType<UnifiedModuleProps>> = {
  qwen: QwenModule,
  scopesentry: ScopeSentryModule,
  observer: ObserverModule,
};

function ModuleLoading({ label }: { label: string }) {
  return (
    <div className="flex min-h-[calc(100dvh-2.5rem)] items-center justify-center bg-[var(--qwen-background)] p-8 text-sm text-[var(--qwen-foreground)]">
      {label}
    </div>
  );
}

function useHash(pathname: string, search: string) {
  const [hash, setHash] = useState("");

  useEffect(() => {
    const sync = () => setHash(window.location.hash);
    sync();
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    return () => {
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
    };
  }, [pathname, search]);

  return { hash, setHash };
}

function ModuleSurface({
  id,
  active,
  theme,
  path,
  onNavigate,
}: UnifiedModuleProps & { id: UnifiedModuleId }) {
  const Module = MODULE_COMPONENTS[id];

  useEffect(() => {
    if (active) window.dispatchEvent(new Event("resize"));
  }, [active]);

  return (
    <section
      aria-hidden={!active}
      data-unified-module={id}
      className={active ? "flex min-h-[calc(100dvh-3rem)] w-full min-w-0 flex-1 flex-col" : "hidden"}
    >
      <Module active={active} theme={theme} path={path} onNavigate={onNavigate} />
    </section>
  );
}

function UnifiedHostInner({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const currentUser = useCurrentUser();
  const currentSearch = searchParams.toString();
  const { hash, setHash } = useHash(pathname, currentSearch);
  const resolvedThemeMode = usePreferencesStore((state) => state.resolvedThemeMode);
  const currentModule = moduleForPath(pathname);
  const activeModuleRef = useRef<UnifiedModuleId | null>(currentModule?.id ?? null);
  activeModuleRef.current = currentModule?.id ?? null;
  const currentPath = currentModule
    ? modulePath(pathname, currentModule.prefix, currentSearch, hash)
    : "/";
  const [visited, setVisited] = useState<ReadonlySet<UnifiedModuleId>>(() =>
    currentModule ? new Set([currentModule.id]) : new Set(),
  );
  const [modulePaths, setModulePaths] = useState<Partial<Record<UnifiedModuleId, string>>>(() =>
    currentModule ? { [currentModule.id]: currentPath } : {},
  );
  const [version, setVersion] = useState("");
  const [syncing, setSyncing] = useState(false);
  const autoSyncedRef = useRef(false);
  const activeWorkspaceGroup = useMemo(() => resolveWorkspaceGroup(pathname), [pathname]);

  const isAuthRoute =
    pathname === "/login" ||
    pathname === "/setup" ||
    pathname.startsWith("/login/") ||
    pathname.startsWith("/setup/");

  const runUnifiedSync = useCallback(async (silent = false) => {
    if (!auth.getToken()) return;
    if (!silent) setSyncing(true);
    try {
      const res = await api.syncUnified();
      if (!silent) {
        const assetTotal = Object.values(res.synced ?? {}).reduce((a, b) => a + b, 0);
        const findingsCount = res.findings_synced ?? 0;
        toast.success(
          `Synced ${assetTotal} recon assets and ${findingsCount} new findings across Malaria engines`,
        );
      }
    } catch (err) {
      if (!silent) {
        toast.error(`Sync failed: ${(err as Error).message}`);
      }
    } finally {
      if (!silent) setSyncing(false);
    }
  }, []);

  useEffect(() => {
    if (isAuthRoute || autoSyncedRef.current || !auth.getToken()) return;
    autoSyncedRef.current = true;
    void runUnifiedSync(true);
  }, [isAuthRoute, runUnifiedSync]);

  useEffect(() => {
    applyUnifiedTheme(resolvedThemeMode);
  }, [resolvedThemeMode]);

  useEffect(() => {
    if (isAuthRoute) return;
    if (!auth.getToken()) {
      auth.clearToken();
      router.replace("/login");
      router.refresh();
    }
  }, [isAuthRoute, pathname, router]);

  useEffect(() => {
    if (isAuthRoute) return;
    api
      .health()
      .then((h) => setVersion((h.version ?? "").replace(/^v(?=\d)/, "")))
      .catch(() => setVersion(""));
  }, [isAuthRoute]);

  useEffect(() => {
    const login = () => {
      router.replace("/login");
      router.refresh();
    };
    window.addEventListener(ARTEX_AUTH_REQUIRED_EVENT, login);
    return () => window.removeEventListener(ARTEX_AUTH_REQUIRED_EVENT, login);
  }, [router]);

  useEffect(() => {
    if (!currentModule) return;
    setVisited((previous) => {
      if (previous.has(currentModule.id)) return previous;
      return new Set([...previous, currentModule.id]);
    });
  }, [currentModule]);

  useEffect(() => {
    if (!currentModule) return;
    setModulePaths((previous) => {
      if (previous[currentModule.id] === currentPath) return previous;
      return { ...previous, [currentModule.id]: currentPath };
    });
  }, [currentModule, currentPath]);

  useEffect(() => {
    if (!visited.has("scopesentry")) return;
    const existing = document.querySelector<HTMLLinkElement>('link[data-unified-module="scopesentry-styles"]');
    if (existing) return;

    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = SCOPE_SENTRY_ASSETS.stylesheet;
    link.dataset.unifiedModule = "scopesentry-styles";
    document.head.appendChild(link);
  }, [visited]);

  const navigateModule = useMemo(
    () =>
      (id: UnifiedModuleId, path: string, replace = false) => {
        const definition = UNIFIED_MODULES.find((module) => module.id === id);
        if (!definition) return;
        setModulePaths((previous) =>
          previous[id] === path ? previous : { ...previous, [id]: path },
        );
        // A background module may reconcile its route, but cannot take over
        // another module's active document or carry its auth state across it.
        if (activeModuleRef.current !== id) return;
        const target = namespacedModulePath(definition.prefix, path);
        setHash(new URL(target, window.location.origin).hash);
        if (replace) router.replace(target);
        else router.push(target);
      },
    [router, setHash],
  );
  const moduleNavigation = useMemo(() => {
    const callbacks = {} as Record<UnifiedModuleId, UnifiedModuleProps["onNavigate"]>;
    for (const definition of UNIFIED_MODULES) {
      callbacks[definition.id] = (path, replace) => navigateModule(definition.id, path, replace);
    }
    return callbacks;
  }, [navigateModule]);

  const theme = resolvedThemeMode;
  const isModuleRoute = currentModule !== null;
  const fullBleed = !isModuleRoute && isFullBleed(pathname);

  const defaultOpen = typeof document === "undefined" ? true : getClientCookie("sidebar_state") !== "false";
  const variant = readPref<SidebarVariant>(
    "sidebar_variant",
    SIDEBAR_VARIANT_VALUES,
    PREFERENCE_DEFAULTS.sidebar_variant,
  );
  const collapsible = readPref<SidebarCollapsible>(
    "sidebar_collapsible",
    SIDEBAR_COLLAPSIBLE_VALUES,
    PREFERENCE_DEFAULTS.sidebar_collapsible,
  );

  const moduleSurfaces = UNIFIED_MODULES.map((definition) => {
    if (!visited.has(definition.id)) return null;
    const active = currentModule?.id === definition.id;
    const path = modulePaths[definition.id] ?? "/";
    return (
      <ModuleSurface
        key={definition.id}
        id={definition.id}
        active={active}
        theme={theme}
        path={path}
        onNavigate={moduleNavigation[definition.id]}
      />
    );
  });

  if (isAuthRoute) {
    return <div className="min-h-dvh">{children}</div>;
  }

  return (
    <SidebarProvider
      defaultOpen={defaultOpen}
      style={
        {
          "--sidebar-width": "calc(var(--spacing) * 68)",
        } as CSSProperties
      }
    >
      <AppSidebar variant={variant} collapsible={collapsible} />
      <SidebarInset
        className={cn(
          !isModuleRoute && "[html[data-content-layout=centered]_&>*]:mx-auto",
          !isModuleRoute && "[html[data-content-layout=centered]_&>*]:w-full",
          !isModuleRoute && "[html[data-content-layout=centered]_&>*]:max-w-screen-2xl",
          "peer-data-[variant=inset]:border",
          "[--dashboard-header-height:--spacing(12)]",
          "min-w-0 overflow-x-clip",
        )}
      >
        {!fullBleed && (
          <header
            className={cn(
              "flex h-12 shrink-0 items-center gap-2 border-b transition-[width,height] ease-linear group-has-data-[collapsible=icon]/sidebar-wrapper:h-12",
              "[html[data-navbar-style=sticky]_&]:sticky [html[data-navbar-style=sticky]_&]:top-0 [html[data-navbar-style=sticky]_&]:z-50 [html[data-navbar-style=sticky]_&]:overflow-hidden [html[data-navbar-style=sticky]_&]:rounded-t-[inherit] [html[data-navbar-style=sticky]_&]:bg-background/50 [html[data-navbar-style=sticky]_&]:backdrop-blur-md",
            )}
          >
            <div className="flex w-full min-w-0 items-center justify-between gap-2 px-4 lg:px-6">
              <div className="flex min-w-0 items-center gap-1 lg:gap-2">
                <SidebarTrigger className="-ml-1 shrink-0" />
                <Separator
                  orientation="vertical"
                  className="mx-2 data-[orientation=vertical]:h-4 data-[orientation=vertical]:self-center"
                />
                <SearchDialog />
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {version && (
                  <span className="font-medium text-muted-foreground text-xs tabular-nums">Version · {version}</span>
                )}
                <LayoutControls />
                <ThemeSwitcher />
                <AccountSwitcher users={[currentUser]} />
              </div>
            </div>
          </header>
        )}
        {!fullBleed && activeWorkspaceGroup && (
          <div
            data-unified-mode-bar={activeWorkspaceGroup.id}
            className="flex min-h-11 shrink-0 flex-wrap items-center justify-between gap-2 border-b bg-muted/30 px-4 py-1.5 lg:px-6"
          >
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="mr-1.5 font-semibold text-muted-foreground text-xs uppercase tracking-wider">
                {activeWorkspaceGroup.title}
              </span>
              {activeWorkspaceGroup.tabs.map((tab) => {
                const active = isModeTabActive(pathname, tab.url);
                return (
                  <Link
                    key={tab.id}
                    href={tab.url}
                    prefetch={false}
                    title={tab.subtitle}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 font-medium text-xs transition-colors",
                      active
                        ? "bg-primary text-primary-foreground shadow-xs"
                        : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                    )}
                  >
                    <span>{tab.label}</span>
                  </Link>
                );
              })}
            </div>
            <div className="flex items-center gap-2">
              {activeWorkspaceGroup.tabs.map((tab) =>
                isModeTabActive(pathname, tab.url) ? (
                  <span key={tab.id} className="hidden text-muted-foreground text-xs lg:inline">
                    {tab.subtitle}
                  </span>
                ) : null,
              )}
              {activeWorkspaceGroup.showSyncButton && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 gap-1.5 px-2.5 text-xs"
                  disabled={syncing}
                  onClick={() => void runUnifiedSync(false)}
                >
                  <RefreshCwIcon className={cn("size-3.5", syncing && "animate-spin")} />
                  <span>{syncing ? "Syncing…" : "Sync Recon & Findings"}</span>
                </Button>
              )}
            </div>
          </div>
        )}
        {!fullBleed && (
          <SharedTaskContextBar active={isModeTabActive(pathname, "/ai")} pathname={pathname} />
        )}
        {!isModuleRoute && children}
        {moduleSurfaces}
      </SidebarInset>
    </SidebarProvider>
  );
}

function SharedTaskContextBar({ active, pathname }: { active: boolean; pathname: string }) {
  const router = useRouter();
  const [ctx, setCtx] = useState<SharedContextResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [openingChat, setOpeningChat] = useState(false);

  const loadContext = useCallback(async () => {
    if (!auth.getToken()) return;
    setLoading(true);
    try {
      const res = await api.sharedContext();
      setCtx(res);
    } catch {
      /* best-effort context strip */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!active) return;
    void loadContext();
    const timer = setInterval(() => void loadContext(), 8000);
    return () => clearInterval(timer);
  }, [active, pathname, loadContext]);

  if (!active) return null;

  const taskId = ctx?.task_id ?? 0;
  const tasks = ctx?.recent_tasks ?? [];

  async function selectTask(nextId: number) {
    try {
      const picked = tasks.find((t) => t.id === nextId);
      const next = await api.setSharedContext({
        task_id: nextId,
        target: picked?.target || "",
        source: "ai-bar",
      });
      setCtx(next);
      toast.success(nextId > 0 ? `Shared ARTEX Task switched to #${nextId}` : "Cleared active shared task");
    } catch (e) {
      toast.error(`Failed to switch task: ${(e as Error).message}`);
    }
  }

  async function openGraphChat() {
    if (taskId <= 0) {
      router.push("/chat");
      return;
    }
    setOpeningChat(true);
    try {
      const res = await api.ensureTaskChat(taskId);
      router.push(`/chat?c=${res.conversation_id}`);
    } catch (e) {
      toast.error(`Failed to open Graph Chat: ${(e as Error).message}`);
    } finally {
      setOpeningChat(false);
    }
  }

  async function copyTaskHandoff() {
    const label =
      taskId > 0
        ? `Continue ARTEX Task #${taskId}${ctx?.target ? ` (${ctx.target})` : ""} using artex MCP (get_active_context)`
        : "Start shared ARTEX assessment via artex MCP (start_target_assessment)";
    try {
      await navigator.clipboard.writeText(label);
      toast.success("Copied ARTEX task handoff instruction");
    } catch {
      toast.info(label);
    }
  }

  return (
    <div
      data-shared-task-bar
      className="flex min-h-9 shrink-0 flex-wrap items-center justify-between gap-2 border-b bg-background/80 px-4 py-1 text-xs lg:px-6"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1 font-medium text-muted-foreground">
          <TerminalIcon className="size-3.5 text-emerald-500" />
          Shared ARTEX Task:
        </span>
        <select
          aria-label="Select shared ARTEX task"
          value={taskId}
          onChange={(e) => void selectTask(Number(e.target.value))}
          className="h-6 max-w-64 rounded-md border bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-ring"
        >
          <option value={0}>None selected (pick or start in chat)</option>
          {tasks.map((t) => (
            <option key={t.id} value={t.id}>
              #{t.id} · {t.name || t.description} ({t.asset_count}a / {t.finding_count}f)
            </option>
          ))}
        </select>
        {taskId > 0 && ctx ? (
          <span className="hidden items-center gap-2 text-muted-foreground sm:inline-flex">
            {ctx.company_name && <span className="font-medium text-foreground">{ctx.company_name}</span>}
            {ctx.task_status && (
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase">{ctx.task_status}</span>
            )}
            <span className="tabular-nums">
              {ctx.asset_count} assets · {ctx.finding_count} findings · {ctx.node_count} nodes
            </span>
          </span>
        ) : (
          <span className="hidden text-muted-foreground sm:inline">
            Uses artex MCP automatically when starting or picking a task
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-6 px-1.5 text-xs"
          onClick={() => void loadContext()}
          disabled={loading}
          title="Refresh shared ARTEX task context"
        >
          <RefreshCwIcon className={cn("size-3", loading && "animate-spin")} />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-6 gap-1 px-2 text-[11px]"
          onClick={() => void copyTaskHandoff()}
          title="Copy shared task handoff instruction to paste into Deep Agent"
        >
          <CopyIcon className="size-3" />
          <span className="hidden sm:inline">Copy Prompt</span>
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-6 gap-1 px-2 text-[11px]"
          onClick={() => void openGraphChat()}
          disabled={openingChat}
          title="Switch to Graph Chat (/chat) on this exact task"
        >
          <MessageSquareIcon className="size-3 text-sky-500" />
          <span>{taskId > 0 ? "Graph Chat" : "Open Graph Chat"}</span>
        </Button>
        {taskId > 0 && (
          <Button asChild variant="outline" size="sm" className="h-6 gap-1 px-2 text-[11px]">
            <Link href={`/function/tasks/detail?id=${taskId}`} title="View Task & Exploration Graph">
              <NetworkIcon className="size-3 text-violet-500" />
              <span>Task #{taskId} Graph</span>
            </Link>
          </Button>
        )}
        <Button asChild variant="outline" size="sm" className="h-6 gap-1 px-2 text-[11px]">
          <Link href="/function/findings" title="Open Unified Findings">
            <ShieldAlertIcon className="size-3 text-amber-500" />
            <span>Findings</span>
          </Link>
        </Button>
      </div>
    </div>
  );
}

export function UnifiedHost({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={children}>
      <UnifiedHostInner>{children}</UnifiedHostInner>
    </Suspense>
  );
}
