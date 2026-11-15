"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";

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

export function MainContent({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  if (isFullBleed(pathname)) {
    return <>{children}</>;
  }

  return (
    <div className="min-h-0 min-w-0 flex-1 overflow-x-hidden p-4 has-data-[content-padding=false]:p-0 md:p-6 md:has-data-[content-padding=false]:p-0">
      {children}
    </div>
  );
}
