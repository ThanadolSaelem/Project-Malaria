"use client";

import * as React from "react";

import {
  ArrowUpIcon,
  CheckIcon,
  FileIcon,
  FolderIcon,
  FolderOpenIcon,
  HardDriveIcon,
  Loader2Icon,
  SearchIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { type GGUFInfo, studioApi } from "./types";

export type FileBrowserFilter = ".gguf" | "binary" | "all";

interface FsRoot {
  label: string;
  path: string;
}

interface FsEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size_bytes: number;
  size_gib?: number;
  mtime: number;
  is_gguf?: boolean;
  executable?: boolean;
}

interface FsListResponse {
  ok: boolean;
  error?: string;
  path: string;
  parent: string;
  roots: FsRoot[];
  entries: FsEntry[];
  truncated?: boolean;
}

function formatSize(bytes: number, gib?: number): string {
  if (gib !== undefined && gib >= 0.05) return `${gib} GiB`;
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KiB`;
  return `${bytes} B`;
}

function parentDirOf(rawPath: string): string {
  const trimmed = rawPath.trim();
  if (!trimmed) return "";
  if (trimmed === "/") return "/";
  const idx = trimmed.lastIndexOf("/");
  if (idx <= 0) return idx === 0 ? "/" : "";
  return trimmed.slice(0, idx);
}

export function FileBrowserModal({
  open,
  onOpenChange,
  title,
  initialPath,
  filterMode,
  onSelect,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  initialPath?: string;
  filterMode: FileBrowserFilter;
  onSelect: (path: string, info?: GGUFInfo) => void;
}) {
  const [currentPath, setCurrentPath] = React.useState("");
  const [pathInput, setPathInput] = React.useState("");
  const [parentPath, setParentPath] = React.useState("");
  const [roots, setRoots] = React.useState<FsRoot[]>([]);
  const [entries, setEntries] = React.useState<FsEntry[]>([]);
  const [truncated, setTruncated] = React.useState(false);
  const [activeFilter, setActiveFilter] = React.useState<FileBrowserFilter>(filterMode);
  const [searchQuery, setSearchQuery] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [pickingFinder, setPickingFinder] = React.useState(false);
  const [inspecting, setInspecting] = React.useState(false);
  const [errorMsg, setErrorMsg] = React.useState("");
  const [selectedEntry, setSelectedEntry] = React.useState<FsEntry | null>(null);
  const [inspectedInfo, setInspectedInfo] = React.useState<GGUFInfo | null>(null);

  const loadDirectory = React.useCallback(async (dir: string, mode: FileBrowserFilter) => {
    setLoading(true);
    setErrorMsg("");
    try {
      const qs = new URLSearchParams({ dir, filter: mode });
      const res = await studioApi<FsListResponse>(`/fs?${qs.toString()}`);
      setRoots(res.roots ?? []);
      setParentPath(res.parent ?? "");
      if (res.path) {
        setCurrentPath(res.path);
        setPathInput(res.path);
      }
      if (!res.ok) {
        setEntries([]);
        setTruncated(false);
        setErrorMsg(res.error ?? "ไม่สามารถเปิดโฟลเดอร์นี้ได้");
        return;
      }
      setEntries(res.entries ?? []);
      setTruncated(Boolean(res.truncated));
      setSelectedEntry(null);
      setInspectedInfo(null);
    } catch (err) {
      setErrorMsg((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    if (!open) return;
    setActiveFilter(filterMode);
    setSearchQuery("");
    setSelectedEntry(null);
    setInspectedInfo(null);
    const startDir = initialPath ? parentDirOf(initialPath) : "";
    void loadDirectory(startDir, filterMode);
  }, [open, initialPath, filterMode, loadDirectory]);

  async function inspectAndSelect(entry: FsEntry, confirmNow: boolean) {
    setSelectedEntry(entry);
    if (entry.is_gguf || activeFilter === ".gguf") {
      setInspecting(true);
      try {
        const res = await studioApi<{ ok: boolean; info?: GGUFInfo; error?: string }>(
          `/inspect?path=${encodeURIComponent(entry.path)}`,
        );
        const info = res.ok ? res.info : undefined;
        setInspectedInfo(info ?? null);
        if (confirmNow) {
          onSelect(entry.path, info);
          onOpenChange(false);
        }
      } catch {
        setInspectedInfo(null);
        if (confirmNow) {
          onSelect(entry.path);
          onOpenChange(false);
        }
      } finally {
        setInspecting(false);
      }
      return;
    }

    setInspectedInfo(null);
    if (confirmNow) {
      onSelect(entry.path);
      onOpenChange(false);
    }
  }

  async function handleOpenFinder() {
    setPickingFinder(true);
    try {
      const res = await studioApi<{
        ok: boolean;
        canceled?: boolean;
        path?: string;
        info?: GGUFInfo;
        error?: string;
      }>("/pick-file", {
        method: "POST",
        body: { filter: filterMode === "binary" ? "binary" : ".gguf" },
      });
      if (res.canceled) return;
      if (!res.ok || !res.path) {
        throw new Error(res.error ?? "Finder selection failed");
      }
      onSelect(res.path, res.info);
      onOpenChange(false);
    } catch (err) {
      toast.error(`เปิด Finder ไม่สำเร็จ: ${(err as Error).message}`);
    } finally {
      setPickingFinder(false);
    }
  }

  function handleConfirmSelection() {
    if (!selectedEntry || selectedEntry.is_dir) return;
    if (selectedEntry.is_gguf && !inspectedInfo && !inspecting) {
      void inspectAndSelect(selectedEntry, true);
      return;
    }
    onSelect(selectedEntry.path, inspectedInfo ?? undefined);
    onOpenChange(false);
  }

  const visibleEntries = React.useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((e) => e.name.toLowerCase().includes(q));
  }, [entries, searchQuery]);

  const filterLabel = activeFilter === ".gguf" ? ".gguf only" : activeFilter === "binary" ? "Executables" : "All files";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-base">{title}</DialogTitle>
          <DialogDescription>
            เลือกไฟล์จาก path ใดก็ได้ในเครื่อง หรือเปิด Finder เพื่อเลือกไฟล์โดยตรง
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3">
          {/* Quick Roots */}
          {roots.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              {roots.map((r) => (
                <button
                  key={r.path}
                  type="button"
                  onClick={() => void loadDirectory(r.path, activeFilter)}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs transition-colors",
                    currentPath === r.path
                      ? "border-foreground bg-foreground text-background"
                      : "border-border bg-muted/40 text-muted-foreground hover:text-foreground",
                  )}
                >
                  <HardDriveIcon className="size-3" />
                  {r.label}
                </button>
              ))}
            </div>
          )}

          {/* Path Bar + Finder */}
          <div className="flex items-center gap-1.5">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!parentPath || loading}
              onClick={() => void loadDirectory(parentPath, activeFilter)}
              title="ขึ้นไป 1 ชั้น"
            >
              <ArrowUpIcon className="size-3.5" />
            </Button>
            <Input
              value={pathInput}
              onChange={(e) => setPathInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void loadDirectory(pathInput, activeFilter);
                }
              }}
              placeholder="~/Downloads/models/..."
              className="h-8 flex-1 font-mono text-xs"
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={loading}
              onClick={() => void loadDirectory(pathInput, activeFilter)}
            >
              Go
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={pickingFinder}
              onClick={() => void handleOpenFinder()}
            >
              {pickingFinder ? (
                <Loader2Icon className="mr-1.5 size-3.5 animate-spin" />
              ) : (
                <FolderOpenIcon className="mr-1.5 size-3.5" />
              )}
              Open Finder
            </Button>
          </div>

          {/* Search & Filter Toggle */}
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <SearchIcon className="pointer-events-none absolute top-2 left-2.5 size-3.5 text-muted-foreground" />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="ค้นหาชื่อไฟล์หรือโฟลเดอร์ใน path ปัจจุบัน..."
                className="h-8 pl-8 text-xs"
              />
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                const nextMode: FileBrowserFilter = activeFilter === "all" ? filterMode : "all";
                setActiveFilter(nextMode);
                void loadDirectory(currentPath, nextMode);
              }}
              className="h-8 text-xs"
            >
              Filter: {filterLabel}
            </Button>
          </div>

          {/* Directory Listing */}
          <div className="max-h-72 overflow-y-auto rounded-lg border bg-background">
            {loading && (
              <div className="flex items-center justify-center gap-2 py-12 text-muted-foreground text-xs">
                <Loader2Icon className="size-4 animate-spin" />
                กำลังอ่านโฟลเดอร์...
              </div>
            )}

            {!loading && errorMsg && (
              <div className="px-4 py-8 text-center text-muted-foreground text-xs">{errorMsg}</div>
            )}

            {!loading && !errorMsg && visibleEntries.length === 0 && (
              <div className="px-4 py-10 text-center text-muted-foreground text-xs">
                ไม่พบไฟล์ที่ตรงเงื่อนไข ({filterLabel}) ในโฟลเดอร์นี้
              </div>
            )}

            {!loading && !errorMsg && visibleEntries.length > 0 && (
              <div className="divide-y divide-border/60">
                {visibleEntries.map((entry) => {
                  const isSelected = selectedEntry?.path === entry.path;
                  return (
                    <button
                      key={entry.path}
                      type="button"
                      onClick={() => {
                        if (entry.is_dir) {
                          void loadDirectory(entry.path, activeFilter);
                        } else {
                          void inspectAndSelect(entry, false);
                        }
                      }}
                      onDoubleClick={() => {
                        if (!entry.is_dir) {
                          void inspectAndSelect(entry, true);
                        }
                      }}
                      className={cn(
                        "flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-xs transition-colors",
                        isSelected
                          ? "bg-foreground text-background"
                          : "text-foreground hover:bg-muted/60",
                      )}
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        {entry.is_dir ? (
                          <FolderIcon className="size-4 shrink-0 text-muted-foreground" />
                        ) : (
                          <FileIcon
                            className={cn(
                              "size-4 shrink-0",
                              isSelected ? "text-background" : "text-muted-foreground",
                            )}
                          />
                        )}
                        <span className={cn("truncate", entry.is_dir ? "font-medium" : "font-mono")}>
                          {entry.name}
                        </span>
                      </span>
                      <span
                        className={cn(
                          "shrink-0 font-mono text-[11px]",
                          isSelected ? "text-background/80" : "text-muted-foreground",
                        )}
                      >
                        {entry.is_dir ? "Folder" : formatSize(entry.size_bytes, entry.size_gib)}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {truncated && (
            <div className="text-muted-foreground text-[11px]">
              แสดงสูงสุด 500 รายการแรก — พิมพ์ชื่อไฟล์ในช่องค้นหาหรือใช้ Finder ได้
            </div>
          )}

          {/* Selected File Inspection Preview */}
          {selectedEntry && !selectedEntry.is_dir && (
            <div className="rounded-lg border bg-muted/30 p-3 text-xs">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="truncate font-mono font-medium text-foreground">{selectedEntry.path}</span>
                {inspecting ? (
                  <span className="inline-flex items-center gap-1 text-muted-foreground">
                    <Loader2Icon className="size-3 animate-spin" /> Inspecting GGUF...
                  </span>
                ) : (
                  inspectedInfo && (
                    <div className="flex flex-wrap items-center gap-1.5">
                      {inspectedInfo.architecture && (
                        <Badge variant="outline" className="font-mono text-[10px]">
                          {inspectedInfo.architecture}
                        </Badge>
                      )}
                      {inspectedInfo.quant_label && (
                        <Badge variant="outline" className="font-mono text-[10px]">
                          {inspectedInfo.quant_label}
                        </Badge>
                      )}
                      {inspectedInfo.block_count !== null && (
                        <Badge variant="outline" className="font-mono text-[10px]">
                          {inspectedInfo.block_count} layers
                        </Badge>
                      )}
                      <Badge variant="outline" className="font-mono text-[10px]">
                        {inspectedInfo.size_gib} GiB
                      </Badge>
                    </div>
                  )
                )}
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center justify-end gap-2 pt-1">
            <Button type="button" variant="outline" size="sm" onClick={() => onOpenChange(false)}>
              ยกเลิก
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!selectedEntry || selectedEntry.is_dir || inspecting}
              onClick={handleConfirmSelection}
            >
              <CheckIcon className="mr-1.5 size-3.5" />
              เลือกไฟล์นี้
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
