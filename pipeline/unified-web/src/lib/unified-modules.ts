export type UnifiedModuleId = "qwen" | "scopesentry" | "observer";

export interface UnifiedModuleDefinition {
  id: UnifiedModuleId;
  label: string;
  prefix: `/${string}`;
}

export const UNIFIED_MODULES: readonly UnifiedModuleDefinition[] = [
  { id: "qwen", label: "AI Workspace", prefix: "/ai" },
  { id: "scopesentry", label: "ScopeSentry", prefix: "/scopesentry" },
  { id: "observer", label: "Observer", prefix: "/observer" },
];

export const SCOPE_SENTRY_ASSETS = {
  script: "/_modules/scopesentry/module.js",
  stylesheet: "/_modules/scopesentry/module.css",
} as const;

export function moduleForPath(pathname: string): UnifiedModuleDefinition | null {
  return (
    UNIFIED_MODULES.find(({ prefix }) => pathname === prefix || pathname.startsWith(`${prefix}/`)) ?? null
  );
}

export function modulePath(pathname: string, prefix: string, search = "", hash = ""): string {
  const suffix = pathname.slice(prefix.length);
  const localPath = suffix.length > 0 ? suffix : "/";
  return `${localPath.startsWith("/") ? localPath : `/${localPath}`}${search ? `?${search}` : ""}${hash}`;
}

export function namespacedModulePath(prefix: string, path: string): string {
  const [pathAndSearch, hash = ""] = path.split("#", 2);
  const [pathname, search = ""] = pathAndSearch.split("?", 2);
  const localPath = pathname.startsWith("/") ? pathname : `/${pathname}`;
  const suffix = localPath === "/" ? "" : localPath;
  return `${prefix}${suffix}${search ? `?${search}` : ""}${hash ? `#${hash}` : ""}`;
}
