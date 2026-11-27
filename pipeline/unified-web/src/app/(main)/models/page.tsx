"use client";

import * as React from "react";

import {
  CloudIcon,
  CpuIcon,
  HardDriveIcon,
  Loader2Icon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  Trash2Icon,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

import { CloudProviderModal } from "./_components/cloud-modal";
import { RunSettingsPanel } from "./_components/run-settings-panel";
import { type CloudModelInfo, type ModelStudioState, studioApi } from "./_components/types";

export default function ModelStudioPage() {
  const [state, setState] = React.useState<ModelStudioState | null>(null);
  const [selectedSlotId, setSelectedSlotId] = React.useState("orchestrator");
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = React.useState(true);
  const [cloudOpen, setCloudOpen] = React.useState(false);
  const [editingCloud, setEditingCloud] = React.useState<CloudModelInfo | null>(null);

  const loadState = React.useCallback(async () => {
    try {
      const res = await studioApi<ModelStudioState>("/state");
      setState(res);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void loadState();
  }, [loadState]);

  React.useEffect(() => {
    if (!autoRefresh) return;
    const t = setInterval(() => void loadState(), 8000);
    return () => clearInterval(t);
  }, [autoRefresh, loadState]);

  async function rescanGgufs() {
    try {
      await studioApi("/ggufs");
      await loadState();
      toast.success("สแกนไฟล์ .gguf ใหม่เรียบร้อยแล้ว");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function toggleCloud(c: CloudModelInfo, enabled: boolean) {
    try {
      await studioApi("/cloud/save", {
        method: "POST",
        body: { ...c, enabled },
      });
      await loadState();
      toast.success(`${c.label}: ${enabled ? "เปิดใช้งาน" : "ปิดใช้งาน"}`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function removeCloud(c: CloudModelInfo) {
    try {
      await studioApi("/cloud/delete", { method: "POST", body: { id: c.id } });
      await loadState();
      toast.success(`ลบ ${c.label} แล้ว`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  const slots = state?.slots ?? [];
  const selectedSlot = slots.find((s) => s.id === selectedSlotId) ?? slots[0] ?? null;
  const totalRam = state?.system.total_ram_gib ?? 128;
  const activeRss = state?.system.active_rss_gib ?? 0;
  const ramPct = Math.min(100, Math.round((activeRss / totalRam) * 100));

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-4 md:gap-5">
      {/* Top Studio Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="flex items-center gap-2 font-semibold text-xl tracking-tight">
          <CpuIcon className="size-5 text-foreground" />
          Model Studio
        </h1>

        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-muted-foreground text-xs">
            <Switch checked={autoRefresh} onCheckedChange={setAutoRefresh} />
            Auto-refresh (8s)
          </label>
          <Button size="sm" variant="outline" onClick={() => void loadState()}>
            <RefreshCwIcon className="mr-1 size-3.5" /> Refresh
          </Button>
        </div>
      </div>

      {state && (
        <Card className="py-3">
          <CardContent className="grid gap-2 px-4">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
              <div className="flex items-center gap-2 font-medium">
                <HardDriveIcon className="size-4 text-foreground" />
                <span>Unified Memory Overview</span>
                <span className="font-mono text-muted-foreground">
                  ({slots.filter((s) => s.live.status === "running").length} / {slots.length} slots active)
                </span>
              </div>
              <div className="font-mono">
                <span className="font-semibold text-foreground">{activeRss.toFixed(1)} GiB</span>
                <span className="text-muted-foreground"> / {totalRam} GiB ({ramPct}%)</span>
              </div>
            </div>
            <Progress value={ramPct} className="h-2" />
          </CardContent>
        </Card>
      )}

      {error && (
        <Card className="border-foreground/40 bg-muted/40 py-3">
          <CardContent className="px-4 text-foreground text-sm">
            เชื่อมต่อ Model Studio API ไม่ได้ ({error}) — ตรวจสอบว่า <code className="font-mono">control_plane.py</code> กำลังรันบนพอร์ต :8010
          </CardContent>
        </Card>
      )}

      {loading && !state ? (
        <div className="flex h-64 items-center justify-center text-muted-foreground text-sm">
          <Loader2Icon className="mr-2 size-4 animate-spin" /> กำลังสแกนโมเดล GGUF และโหลดสถานะเครื่อง...
        </div>
      ) : (
        <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[310px_minmax(0,1fr)]">
          {/* Left column: Local Slots + Cloud Providers */}
          <div className="flex min-w-0 w-full flex-col gap-4 overflow-hidden">
            <div className="grid min-w-0 gap-2">
              <div className="px-1 font-semibold text-muted-foreground text-xs uppercase tracking-wider">
                Local GGUF Slots
              </div>
              {slots.map((s) => {
                const isSelected = selectedSlot?.id === s.id;
                const fileName = s.model_path.split("/").pop() || s.model_path;
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => setSelectedSlotId(s.id)}
                    className={cn(
                      "flex min-w-0 w-full flex-col gap-1.5 overflow-hidden rounded-xl border p-3 text-left transition-all",
                      isSelected
                        ? "border-foreground bg-muted/60 shadow-xs"
                        : "border-border bg-card/60 hover:border-foreground/40",
                    )}
                  >
                    <div className="flex min-w-0 w-full items-center justify-between gap-2">
                      <span className="min-w-0 flex-1 truncate font-medium text-sm">{s.label}</span>
                      <Badge
                        variant="outline"
                        className={cn(
                          "shrink-0 font-mono text-[10px]",
                          s.live.status === "running" && "border-foreground/40 bg-foreground text-background",
                          s.live.status === "loading" && "border-foreground/40 text-foreground",
                          s.live.status === "stopped" && "border-border text-muted-foreground",
                        )}
                      >
                        :{s.port} · {s.live.status}
                      </Badge>
                    </div>
                    <div className="w-full truncate font-mono text-muted-foreground text-xs">{fileName}</div>
                    <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted-foreground">
                      <span>{Math.round(s.ctx_size / 1024)}K ctx</span>
                      <span>· {s.kv_cache_type}</span>
                      {s.live.rss_gib > 0 && <span className="text-foreground">· {s.live.rss_gib} GiB</span>}
                      {s.live.timings.last_tg_tok_s !== null && (
                        <span
                          className="text-foreground"
                          title="Gen = ความเร็วสร้างโทเคนล้วน (Decode) · E2E = ความเร็วใช้งานจริงรวมอ่าน Prompt (ตรงกับใน Deep Agent IDE)"
                        >
                          · Gen {s.live.timings.last_tg_tok_s}
                          {s.live.timings.last_e2e_tok_s ? ` / E2E ${s.live.timings.last_e2e_tok_s}` : ""} tok/s
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>

            <div className="grid min-w-0 gap-2">
              <div className="flex items-center justify-between px-1">
                <span className="font-semibold text-muted-foreground text-xs uppercase tracking-wider">
                  Cloud Providers (:4000)
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 px-2 text-xs"
                  onClick={() => {
                    setEditingCloud(null);
                    setCloudOpen(true);
                  }}
                >
                  <PlusIcon className="mr-1 size-3" /> Add
                </Button>
              </div>
              {(state?.cloud_models ?? []).map((c) => (
                <div key={c.id} className="flex min-w-0 w-full flex-col gap-1.5 overflow-hidden rounded-xl border bg-card/50 p-3">
                  <div className="flex min-w-0 items-center justify-between gap-2">
                    <div className="flex min-w-0 flex-1 items-center gap-1.5">
                      <CloudIcon className="size-3.5 shrink-0 text-foreground" />
                      <span className="min-w-0 flex-1 truncate font-medium text-xs">{c.label}</span>
                    </div>
                    <Switch checked={c.enabled} onCheckedChange={(v) => void toggleCloud(c, v)} />
                  </div>
                  <div className="w-full truncate font-mono text-[11px] text-muted-foreground">{c.target_model}</div>
                  <div className="flex items-center justify-end gap-1 pt-1">
                    <Button
                      size="icon"
                      variant="ghost"
                      className="size-6"
                      onClick={() => {
                        setEditingCloud(c);
                        setCloudOpen(true);
                      }}
                    >
                      <PencilIcon className="size-3" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="size-6 text-muted-foreground hover:text-foreground"
                      onClick={() => void removeCloud(c)}
                    >
                      <Trash2Icon className="size-3" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Right column: Unsloth-style Run Settings Panel */}
          <div className="min-w-0 w-full overflow-hidden">
            {selectedSlot && state && (
              <RunSettingsPanel
                slot={selectedSlot}
                engines={state.engines}
                ggufs={state.ggufs}
                totalRamGib={totalRam}
                onReloadState={loadState}
                onRescanGgufs={rescanGgufs}
              />
            )}
          </div>
        </div>
      )}

      <CloudProviderModal
        open={cloudOpen}
        onOpenChange={setCloudOpen}
        editing={editingCloud}
        onSaved={loadState}
      />
    </div>
  );
}
