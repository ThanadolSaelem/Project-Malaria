"use client";
import { useState } from "react";
import { StandaloneHost } from "@qwen-code/web-shell/standalone-host";
import type { UnifiedModuleProps } from "../types";
export default function QwenModule({
  active,
  theme,
  path,
  onNavigate,
}: UnifiedModuleProps) {
  const [portalContainer, setPortalContainer] = useState<HTMLElement | null>(null);
  return (
    <>
      <div
        data-web-shell-portal-container
        ref={setPortalContainer}
        style={{ display: "contents" }}
      />
      {portalContainer && (
        <StandaloneHost
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
