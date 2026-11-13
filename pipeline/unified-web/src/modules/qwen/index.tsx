"use client";

import { useEffect, useState } from "react";
import type { ComponentType } from "react";
import type { UnifiedModuleProps } from "../types";

let CachedStandaloneHost: ComponentType<any> | null = null;

export default function QwenModule({
  active,
  theme,
  path,
  onNavigate,
}: UnifiedModuleProps) {
  const [portalContainer, setPortalContainer] = useState<HTMLElement | null>(null);
  const [HostComponent, setHostComponent] = useState<ComponentType<any> | null>(() => CachedStandaloneHost);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (CachedStandaloneHost) return;
    import("@qwen-code/web-shell/standalone-host")
      .then((mod) => {
        const comp = (mod as any).StandaloneHost || (mod as any).default;
        CachedStandaloneHost = comp;
        setHostComponent(() => comp);
      })
      .catch((err) => {
        console.error("[QwenModule] failed to load StandaloneHost", err);
        setError(err instanceof Error ? err.message : String(err));
      });
  }, []);

  return (
    <>
      <div
        data-web-shell-portal-container
        ref={setPortalContainer}
        style={{ display: "contents" }}
      />
      {error && (
        <div className="flex h-full w-full items-center justify-center p-8 text-muted-foreground text-sm">
          Failed to load AI workspace: {error}
        </div>
      )}
      {portalContainer && HostComponent && (
        <HostComponent
          active={active}
          theme={theme}
          path={path}
          onNavigate={onNavigate}
          portalContainer={portalContainer}
        />
      )}
    </>
  );
}
