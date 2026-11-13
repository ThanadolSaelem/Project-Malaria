"use client";

import { useEffect, useRef } from "react";
import type { UnifiedModuleProps } from "../types";

type ScopeSentryModule = {
  createScopeSentryModule: (
    container: Element,
    options: {
      active: boolean;
      theme: "light" | "dark";
      path: string;
      onNavigate: (path: string, replace?: boolean) => void;
    },
  ) => ScopeSentryModuleHandle;
};

type ScopeSentryModuleHandle = {
  setTheme(theme: "light" | "dark"): void;
  setPath(path: string): void;
  setActive?(active: boolean): void;
  dispose(): void;
};

const MODULE_ASSET_URL = "/_modules/scopesentry/module.js";

const loadScopeSentryModule = async (): Promise<ScopeSentryModule> => {
  return import(/* webpackIgnore: true */ MODULE_ASSET_URL) as Promise<ScopeSentryModule>;
};

export default function ScopeSentryModuleView({
  active,
  theme,
  path,
  onNavigate,
}: UnifiedModuleProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const moduleRef = useRef<ScopeSentryModuleHandle | null>(null);
  const onNavigateRef = useRef(onNavigate);
  const activeRef = useRef(active);
  const themeRef = useRef(theme);
  const pathRef = useRef(path);
  onNavigateRef.current = onNavigate;
  activeRef.current = active;
  themeRef.current = theme;
  pathRef.current = path;

  useEffect(() => {
    let cancelled = false;
    const container = containerRef.current;
    if (!container) return;

    const load = async () => {
      try {
        const module = await loadScopeSentryModule();
        if (cancelled) return;
        const mountContainer = containerRef.current;
        if (!mountContainer) return;
        const handle = module.createScopeSentryModule(mountContainer, {
          active: activeRef.current,
          theme: themeRef.current,
          path: pathRef.current,
          onNavigate: (nextPath, replace) => onNavigateRef.current(nextPath, replace),
        });
        if (cancelled) {
          handle.dispose();
          return;
        }
        moduleRef.current = handle;
        handle.setActive?.(activeRef.current);
        handle.setTheme(themeRef.current);
        handle.setPath(pathRef.current);
      } catch (error) {
        if (!cancelled) {
          console.error("[ScopeSentry] module load or mount failed", error);
        }
      }
    };
    void load();

    return () => {
      cancelled = true;
      // The host keeps this component mounted across module switches. This cleanup
      // only runs when the host itself removes the module permanently.
      const handle = moduleRef.current;
      moduleRef.current = null;
      handle?.dispose();
    };
  }, []);

  useEffect(() => {
    moduleRef.current?.setActive?.(active);
  }, [active]);

  useEffect(() => {
    moduleRef.current?.setTheme(theme);
  }, [theme]);

  useEffect(() => {
    moduleRef.current?.setPath(path);
  }, [path]);

  return (
    <div
      ref={containerRef}
      data-unified-module="scopesentry"
      data-active={active ? "true" : "false"}
      aria-hidden={!active}
      style={{
        width: "100%",
        height: "100%",
        visibility: active ? "visible" : "hidden",
        pointerEvents: active ? "auto" : "none",
      }}
    />
  );
}
