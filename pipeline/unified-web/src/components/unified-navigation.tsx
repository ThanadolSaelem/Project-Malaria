"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";
import { moduleForPath, namespacedModulePath, type UnifiedModuleId } from "@/lib/unified-modules";

const NAV_ITEMS = [
  { id: "qwen", label: "AI Workspace", href: "/ai" },
  { id: "artex", label: "ARTEX", href: "/artex" },
  { id: "scopesentry", label: "ScopeSentry", href: "/scopesentry" },
  { id: "observer", label: "Observer", href: "/observer" },
] as const;

function activeItem(pathname: string): string {
  const module = moduleForPath(pathname);
  if (module) return module.id;
  return "artex";
}

export function UnifiedNavigation({
  placement = "top",
  modulePaths = {},
  artexPath = "/artex",
}: {
  placement?: "top" | "sidebar";
  modulePaths?: Partial<Record<UnifiedModuleId, string>>;
  artexPath?: string;
}) {
  const pathname = usePathname();
  const active = activeItem(pathname);
  const sidebar = placement === "sidebar";

  return (
    <nav
      aria-label="Project modules"
      className={cn(
        sidebar
          ? "flex flex-col gap-1 border-b px-2 py-2"
          : "flex min-h-10 items-center gap-1 border-b bg-background/95 px-3 text-xs backdrop-blur supports-[backdrop-filter]:bg-background/75",
      )}
    >
      <Link
        href={namespacedModulePath("/ai", modulePaths.qwen ?? "/")}
        prefetch={false}
        className={cn(
          "mr-2 shrink-0 font-semibold tracking-tight",
          sidebar ? "px-2 py-1.5 text-sm" : "px-2 py-1",
        )}
      >
        Project-Malaria
      </Link>
      <div className={cn("flex gap-1", sidebar && "flex-col")}>
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.id}
            href={item.id === "artex" ? artexPath : namespacedModulePath(item.href, modulePaths[item.id] ?? "/")}
            prefetch={false}
            aria-current={active === item.id ? "page" : undefined}
            className={cn(
              "rounded-md px-2 py-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
              active === item.id && "bg-accent text-accent-foreground",
              sidebar && "w-full",
            )}
          >
            {item.label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
