"use client";

import dynamic from "next/dynamic";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { ComponentType, ReactNode } from "react";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import type { UnifiedModuleProps } from "@/modules/types";
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
import { usePreferencesStore } from "@/stores/preferences/preferences-provider";

import { UnifiedNavigation } from "./unified-navigation";

const QwenModule = dynamic(() => import("@/modules/qwen").then((module) => module.default), {
  ssr: false,
  loading: () => <ModuleLoading label="Loading AI Workspace" />,
});
const ScopeSentryModule = dynamic(() => import("@/modules/scopesentry").then((module) => module.default), {
  ssr: false,
  loading: () => <ModuleLoading label="Loading ScopeSentry" />,
});
const ObserverModule = dynamic(() => import("@/modules/observer").then((module) => module.default), {
  ssr: false,
  loading: () => <ModuleLoading label="Loading Observer" />,
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
  const [artexPath, setArtexPath] = useState("/artex");

  useEffect(() => {
    applyUnifiedTheme(resolvedThemeMode);
  }, [resolvedThemeMode]);

  useEffect(() => {
    const login = () => {
      setArtexPath("/login");
      if (activeModuleRef.current !== null) return;
      router.replace("/login");
      router.refresh();
    };
    window.addEventListener(ARTEX_AUTH_REQUIRED_EVENT, login);
    return () => window.removeEventListener(ARTEX_AUTH_REQUIRED_EVENT, login);
  }, [router]);

  useEffect(() => {
    if (!currentModule) {
      setArtexPath(`${pathname}${currentSearch ? `?${currentSearch}` : ""}${hash}`);
      return;
    }
    setVisited((previous) => {
      if (previous.has(currentModule.id)) return previous;
      return new Set([...previous, currentModule.id]);
    });
  }, [currentModule, pathname, currentSearch, hash]);

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

  return (
    <div className={isModuleRoute ? "min-h-dvh" : undefined}>
      <UnifiedNavigation modulePaths={modulePaths} artexPath={artexPath} />
      {!isModuleRoute && children}
      {UNIFIED_MODULES.map((definition) => {
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
      })}
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
