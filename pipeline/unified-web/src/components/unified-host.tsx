"use client";

import dynamic from "next/dynamic";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { ComponentType, CSSProperties, ReactNode } from "react";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import type { UnifiedModuleProps } from "@/modules/types";
import { AccountSwitcher } from "@/app/(main)/_components/sidebar/account-switcher";
import { AppSidebar } from "@/app/(main)/_components/sidebar/app-sidebar";
import { LayoutControls } from "@/app/(main)/_components/sidebar/layout-controls";
import { SearchDialog } from "@/app/(main)/_components/sidebar/search-dialog";
import { ThemeSwitcher } from "@/app/(main)/_components/sidebar/theme-switcher";
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
      className={active ? "block min-h-[calc(100dvh-2.5rem)]" : "hidden"}
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

  const isAuthRoute =
    pathname === "/login" ||
    pathname === "/setup" ||
    pathname.startsWith("/login/") ||
    pathname.startsWith("/setup/");

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
          "min-w-0 overflow-x-hidden",
        )}
      >
        {!fullBleed && (
          <header
            className={cn(
              "flex h-12 shrink-0 items-center gap-2 border-b transition-[width,height] ease-linear group-has-data-[collapsible=icon]/sidebar-wrapper:h-12",
              "[html[data-navbar-style=sticky]_&]:sticky [html[data-navbar-style=sticky]_&]:top-0 [html[data-navbar-style=sticky]_&]:z-50 [html[data-navbar-style=sticky]_&]:overflow-hidden [html[data-navbar-style=sticky]_&]:rounded-t-[inherit] [html[data-navbar-style=sticky]_&]:bg-background/50 [html[data-navbar-style=sticky]_&]:backdrop-blur-md",
            )}
          >
            <div className="flex w-full items-center justify-between px-4 lg:px-6">
              <div className="flex items-center gap-1 lg:gap-2">
                <SidebarTrigger className="-ml-1" />
                <Separator
                  orientation="vertical"
                  className="mx-2 data-[orientation=vertical]:h-4 data-[orientation=vertical]:self-center"
                />
                <SearchDialog />
              </div>
              <div className="flex items-center gap-2">
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
        {!isModuleRoute && children}
        {moduleSurfaces}
      </SidebarInset>
    </SidebarProvider>
  );
}

export function UnifiedHost({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={children}>
      <UnifiedHostInner>{children}</UnifiedHostInner>
    </Suspense>
  );
}
