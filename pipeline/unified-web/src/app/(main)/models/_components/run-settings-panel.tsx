"use client";

import * as React from "react";

import {
  ActivityIcon,
  BookmarkPlusIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  ChevronUpIcon,
  CpuIcon,
  FolderOpenIcon,
  FolderSearchIcon,
  GaugeIcon,
  Loader2Icon,
  PlayIcon,
  RotateCcwIcon,
  SaveIcon,
  ShieldCheckIcon,
  SquareIcon,
  TerminalIcon,
  Trash2Icon,
  ZapIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import { FileBrowserModal, type FileBrowserFilter } from "./file-browser-modal";
import {
  type EngineInfo,
  estimateClientMemory,
  type GGUFInfo,
  type SlotConfig,
  studioApi,
} from "./types";

const CTX_PRESETS = [8192, 16384, 32768, 65536, 131072, 262144];
const EFFORT_CHOICES = [
  { value: "", label: "Default" },
  { value: "none", label: "None" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];

interface LogsResponse {
  ok: boolean;
  log_file: string;
  text: string;
  timings: {
    last_tg_tok_s: number | null;
    last_pp_tok_s: number | null;
    last_draft_acc: number | null;
    history: { tokens: number; tg_tok_s: number; e2e_tok_s?: number | null; pp_tok_s: number | null }[];
  };
}

interface TestResponse {
  ok: boolean;
  error?: string;
  wall_s: number;
  pp_tok_s?: number;
  tg_tok_s?: number;
  predicted_n?: number;
  content?: string;
}

export function RunSettingsPanel({
  slot,
  engines,
  ggufs,
  totalRamGib,
  onReloadState,
  onRescanGgufs,
}: {
  slot: SlotConfig;
  engines: EngineInfo[];
  ggufs: GGUFInfo[];
  totalRamGib: number;
  onReloadState: () => Promise<void>;
  onRescanGgufs: () => Promise<void>;
}) {
  const [draft, setDraft] = React.useState<SlotConfig>(slot);
  const [advancedOpen, setAdvancedOpen] = React.useState(true);
  const [cmdOpen, setCmdOpen] = React.useState(false);
  const [dirty, setDirty] = React.useState(false);
  const [busyAction, setBusyAction] = React.useState<string | null>(null);
  const [presetName, setPresetName] = React.useState("");
  const [logs, setLogs] = React.useState<LogsResponse | null>(null);
  const [logsLoading, setLogsLoading] = React.useState(false);
  const [testResult, setTestResult] = React.useState<TestResponse | null>(null);
  const [testPrompt, setTestPrompt] = React.useState("");
  const [aliasesText, setAliasesText] = React.useState(() => (slot.aliases ?? []).join(", "));
  const [extraGgufs, setExtraGgufs] = React.useState<Record<string, GGUFInfo>>({});
  const [browserTarget, setBrowserTarget] = React.useState<{
    field: "model_path" | "binary" | "mmproj_path" | "draft_model_path";
    title: string;
    filterMode: FileBrowserFilter;
    initialPath: string;
  } | null>(null);

  React.useEffect(() => {
    setDraft(slot);
    setAliasesText((slot.aliases ?? []).join(", "));
    setDirty(false);
    setTestResult(null);
  }, [slot]);

  const patch = React.useCallback((partial: Partial<SlotConfig>) => {
    setDraft((prev) => ({ ...prev, ...partial }));
    setDirty(true);
  }, []);

  const loadLogs = React.useCallback(async () => {
    setLogsLoading(true);
    try {
      const res = await studioApi<LogsResponse>(`/logs?slot=${encodeURIComponent(slot.id)}&lines=140`);
      setLogs(res);
    } catch (e) {
      toast.error(`อ่าน log ไม่สำเร็จ: ${(e as Error).message}`);
    } finally {
      setLogsLoading(false);
    }
  }, [slot.id]);

  const allGgufs = React.useMemo(() => {
    const merged = [...ggufs];
    const seen = new Set(ggufs.flatMap((g) => [g.path, g.display_path].filter(Boolean) as string[]));
    for (const extra of Object.values(extraGgufs)) {
      if (!seen.has(extra.path) && (!extra.display_path || !seen.has(extra.display_path))) {
        merged.push(extra);
        seen.add(extra.path);
      }
    }
    return merged;
  }, [ggufs, extraGgufs]);

  const modelFiles = React.useMemo(() => allGgufs.filter((g) => g.kind === "model"), [allGgufs]);
  const mmprojFiles = React.useMemo(() => allGgufs.filter((g) => g.kind === "mmproj"), [allGgufs]);
  const drafterFiles = React.useMemo(() => allGgufs.filter((g) => g.kind === "drafter"), [allGgufs]);

  const memEst = React.useMemo(() => estimateClientMemory(draft, allGgufs), [draft, allGgufs]);
  const activeMeta = React.useMemo(
    () => allGgufs.find((g) => g.path === draft.model_path || g.display_path === draft.model_path) ?? slot.live.model_meta,
    [allGgufs, draft.model_path, slot.live.model_meta],
  );

  const totalLayers = (activeMeta?.block_count ?? 24) + 1;
  const gpuLayersPlaced = draft.gpu_layers >= 99 ? totalLayers : Math.min(totalLayers, Math.max(0, draft.gpu_layers));

  async function saveOnly(): Promise<boolean> {
    setBusyAction("save");
    try {
      const res = await studioApi<{ ok: boolean; error?: string; litellm?: string }>("/slot/save", {
        method: "POST",
        body: { id: slot.id, config: draft },
      });
      if (!res.ok) throw new Error(res.error || "Save failed");
      setDirty(false);
      toast.success(
        res.litellm === "restarted"
          ? `บันทึก ${slot.label} และรีสตาร์ท LiteLLM พร้อม aliases ใหม่แล้ว`
          : `บันทึกการตั้งค่า ${slot.label} และซิงก์เข้าระบบแล้ว`,
      );
      await onReloadState();
      return true;
    } catch (e) {
      toast.error(`บันทึกไม่สำเร็จ: ${(e as Error).message}`);
      return false;
    } finally {
      setBusyAction(null);
    }
  }

  async function runAction(action: "start" | "stop" | "reload") {
    if ((action === "start" || action === "reload") && dirty) {
      const saved = await saveOnly();
      if (!saved) return;
    }
    setBusyAction(action);
    try {
      const res = await studioApi<{ ok: boolean; error?: string; log_tail?: string }>("/slot/action", {
        method: "POST",
        body: { id: slot.id, action },
      });
      if (!res.ok) {
        throw new Error(res.log_tail ? `${res.error}\n${res.log_tail.slice(-300)}` : res.error || "Action failed");
      }
      toast.success(
        action === "stop"
          ? `หยุดพอร์ต :${slot.port} แล้ว`
          : action === "reload"
            ? `รีโหลด ${slot.label} บน :${slot.port} สำเร็จ`
            : `สตาร์ต ${slot.label} บน :${slot.port} สำเร็จ`,
      );
      await onReloadState();
      void loadLogs();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusyAction(null);
    }
  }

  async function runSpeedTest() {
    setBusyAction("test");
    try {
      const res = await studioApi<TestResponse>("/slot/test", {
        method: "POST",
        body: { id: slot.id, prompt: testPrompt },
      });
      setTestResult(res);
      if (!res.ok) {
        toast.error(`ทดสอบไม่สำเร็จ: ${res.error}`);
      } else {
        toast.success(`ทดสอบเสร็จใน ${res.wall_s}s · ${res.tg_tok_s} tok/s`);
        await onReloadState();
        void loadLogs();
      }
    } catch (e) {
      toast.error(`ทดสอบไม่สำเร็จ: ${(e as Error).message}`);
    } finally {
      setBusyAction(null);
    }
  }

  async function handlePreset(action: "save" | "apply" | "delete", name: string) {
    if (!name.trim()) return;
    setBusyAction("preset");
    try {
      const res = await studioApi<{ ok: boolean; error?: string }>("/slot/preset", {
        method: "POST",
        body: { id: slot.id, action, name: name.trim(), config: draft },
      });
      if (!res.ok) throw new Error(res.error || "Preset failed");
      toast.success(`Preset "${name.trim()}": ${action} สำเร็จ`);
      if (action === "save") setPresetName("");
      await onReloadState();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusyAction(null);
    }
  }

  const isRunning = slot.live.status === "running" || slot.live.status === "loading";
  const ramWarn = memEst.total_gib > totalRamGib * 0.85;
  const presetNames = Object.keys(slot.presets || {});

  return (
    <div className="flex min-w-0 w-full flex-col gap-4">
      {/* Header bar */}
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3 rounded-xl border bg-card/60 px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate font-semibold text-base tracking-tight">{slot.label}</h2>
            <Badge variant="outline" className="font-mono text-xs">
              :{slot.port}
            </Badge>
            <Badge
              variant="outline"
              className={cn(
                "text-xs",
                slot.live.status === "running" && "border-foreground/40 bg-foreground text-background",
                slot.live.status === "loading" && "border-foreground/40 text-foreground",
                slot.live.status === "stopped" && "border-border text-muted-foreground",
              )}
            >
              {slot.live.status === "running"
                ? `Running · PID ${slot.live.pid}`
                : slot.live.status === "loading"
                  ? "Loading..."
                  : "Stopped"}
            </Badge>
            {dirty && (
              <Badge variant="outline" className="border-foreground/50 text-foreground text-xs">
                Unsaved changes
              </Badge>
            )}
          </div>
          <p className="mt-1 truncate font-mono text-muted-foreground text-xs">
            alias: {slot.alias} ({slot.aliases.join(", ")})
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {slot.live.timings.last_tg_tok_s !== null && (
            <Badge
              variant="secondary"
              className="gap-1 font-mono text-xs"
              title="ความเร็วสร้างโทเคนล้วน (Token Generation / Decode) จาก llama-server ไม่รวมเวลาอ่าน Prompt"
            >
              <GaugeIcon className="size-3.5 text-foreground" />
              Gen {slot.live.timings.last_tg_tok_s} tok/s
            </Badge>
          )}
          {slot.live.timings.last_e2e_tok_s != null && (
            <Badge
              variant="outline"
              className="gap-1 border-foreground/30 font-mono text-xs"
              title="ความเร็วใช้งานจริงต่อรอบ (End-to-End = tokens / [prefill + decode]) ซึ่งเป็นค่าเดียวกับที่แสดงใน Deep Agent IDE"
            >
              E2E {slot.live.timings.last_e2e_tok_s} tok/s
            </Badge>
          )}
          {slot.live.rss_gib > 0 && (
            <Badge variant="secondary" className="font-mono text-xs">
              Live RSS {slot.live.rss_gib} GiB
            </Badge>
          )}
          <Button
            size="sm"
            variant="outline"
            disabled={!isRunning || busyAction !== null}
            onClick={() => void runSpeedTest()}
          >
            {busyAction === "test" ? <Loader2Icon className="animate-spin" /> : <ZapIcon />}
            Test Speed
          </Button>
          {isRunning ? (
            <Button
              size="sm"
              variant="outline"
              disabled={busyAction !== null}
              onClick={() => void runAction("stop")}
            >
              {busyAction === "stop" ? <Loader2Icon className="animate-spin" /> : <SquareIcon />}
              Stop
            </Button>
          ) : (
            <Button
              size="sm"
              disabled={busyAction !== null}
              onClick={() => void runAction("start")}
            >
              {busyAction === "start" ? <Loader2Icon className="animate-spin" /> : <PlayIcon />}
              Start
            </Button>
          )}
        </div>
      </div>

      {/* Test speed result banner */}
      {testResult && (
        <Card className={cn("py-3", testResult.ok ? "border-foreground/40 bg-muted/40" : "border-foreground/60 bg-muted/60")}>
          <CardContent className="flex flex-col gap-1.5 px-4 text-xs">
            <div className="flex flex-wrap items-center gap-3 font-mono">
              <span className="font-semibold text-sm">
                {testResult.ok ? "ผลทดสอบความเร็ว" : "ทดสอบไม่ผ่าน"}
              </span>
              {testResult.ok && (
                <>
                  <Badge variant="outline" className="border-foreground/40 text-foreground">
                    Decode: {testResult.tg_tok_s} tok/s
                  </Badge>
                  <Badge variant="outline">Prefill: {testResult.pp_tok_s} tok/s</Badge>
                  <Badge variant="outline">Wall: {testResult.wall_s}s</Badge>
                </>
              )}
            </div>
            {testResult.content && <p className="text-muted-foreground">{testResult.content}</p>}
            {testResult.error && <p className="text-foreground">{testResult.error}</p>}
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue="settings" onValueChange={(v) => { if (v === "logs") void loadLogs(); }}>
        <TabsList>
          <TabsTrigger value="settings">Run Settings</TabsTrigger>
          <TabsTrigger value="logs">Live Logs & Timings</TabsTrigger>
        </TabsList>

        <TabsContent value="settings" className="mt-4 flex flex-col gap-4">
          {/* Unsloth-style Estimated Memory Card */}
          <Card className={cn("py-4", ramWarn && "border-foreground/60 bg-muted/50")}>
            <CardContent className="grid gap-3 px-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-semibold text-muted-foreground text-xs uppercase tracking-wider">
                    Estimated Unified Memory
                  </div>
                  <div className="mt-0.5 text-muted-foreground text-xs">
                    Weight placement:{" "}
                    <span className="font-medium text-foreground">
                      {gpuLayersPlaced} / {totalLayers} layers on Metal GPU
                    </span>
                    {activeMeta?.architecture && (
                      <span className="ml-2 font-mono text-xs">
                        ({activeMeta.architecture}
                        {activeMeta.quant_label ? ` · ${activeMeta.quant_label}` : ""})
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-right">
                  <span
                    className={cn(
                      "rounded-full border px-3 py-1 font-mono font-semibold text-sm",
                      ramWarn ? "border-foreground bg-foreground text-background" : "border-border bg-muted/50 text-foreground",
                    )}
                  >
                    {memEst.total_gib} GiB
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 font-mono text-muted-foreground text-xs sm:grid-cols-4">
                <div className="rounded-md bg-muted/40 px-2.5 py-1.5">
                  Weights: <span className="text-foreground">{memEst.weights_gib} GiB</span>
                </div>
                <div className="rounded-md bg-muted/40 px-2.5 py-1.5">
                  KV Cache ({draft.kv_cache_type}): <span className="text-foreground">{memEst.kv_cache_gib} GiB</span>
                </div>
                <div className="rounded-md bg-muted/40 px-2.5 py-1.5">
                  Compute: <span className="text-foreground">{memEst.compute_gib} GiB</span>
                </div>
                <div className="rounded-md bg-muted/40 px-2.5 py-1.5">
                  Add-ons:{" "}
                  <span className="text-foreground">
                    {(memEst.mmproj_gib + memEst.draft_gib).toFixed(2)} GiB
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Model File & Engine */}
          <Card className="py-4">
            <CardContent className="grid gap-4 px-4">
              <div className="flex items-center justify-between">
                <Label className="font-semibold text-muted-foreground text-xs uppercase tracking-wider">
                  Model & Engine
                </Label>
                <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={() => void onRescanGgufs()}>
                  <FolderSearchIcon className="mr-1 size-3.5" /> Rescan .gguf
                </Button>
              </div>

              <div className="grid min-w-0 gap-3 md:grid-cols-2">
                <div className="grid min-w-0 gap-1.5">
                  <Label className="text-xs">GGUF Model File</Label>
                  <Select
                    value={
                      modelFiles.some((g) => g.display_path === draft.model_path || g.path === draft.model_path)
                        ? draft.model_path
                        : "__custom__"
                    }
                    onValueChange={(v) => {
                      if (v !== "__custom__") patch({ model_path: v });
                    }}
                  >
                    <SelectTrigger className="w-full min-w-0">
                      <SelectValue placeholder="เลือกไฟล์ GGUF..." />
                    </SelectTrigger>
                    <SelectContent>
                      {modelFiles.map((g) => (
                        <SelectItem key={g.path} value={g.display_path || g.path}>
                          {g.name} ({g.size_gib} GiB{g.architecture ? ` · ${g.architecture}` : ""})
                        </SelectItem>
                      ))}
                      <SelectItem value="__custom__">กำหนด Path เองด้านล่าง...</SelectItem>
                    </SelectContent>
                  </Select>
                  <div className="flex items-center gap-1.5">
                    <Input
                      value={draft.model_path}
                      onChange={(e) => patch({ model_path: e.target.value })}
                      placeholder="/Users/.../model.gguf"
                      className="flex-1 font-mono text-xs"
                    />
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="shrink-0 text-xs"
                      onClick={() =>
                        setBrowserTarget({
                          field: "model_path",
                          title: "เลือกไฟล์ GGUF Model",
                          filterMode: ".gguf",
                          initialPath: draft.model_path,
                        })
                      }
                    >
                      <FolderOpenIcon className="mr-1.5 size-3.5" />
                      Browse...
                    </Button>
                  </div>
                </div>

                <div className="grid min-w-0 gap-1.5">
                  <Label className="text-xs">Inference Engine Binary (llama-server)</Label>
                  <Select
                    value={engines.some((e) => e.path === draft.binary) ? draft.binary : "__custom__"}
                    onValueChange={(v) => {
                      if (v !== "__custom__") patch({ binary: v });
                    }}
                  >
                    <SelectTrigger className="w-full min-w-0">
                      <SelectValue placeholder="เลือก Engine..." />
                    </SelectTrigger>
                    <SelectContent>
                      {engines.map((eng) => (
                        <SelectItem key={eng.id} value={eng.path} disabled={!eng.available}>
                          {eng.label} {!eng.available ? "(ไม่พบไฟล์)" : ""}
                        </SelectItem>
                      ))}
                      <SelectItem value="__custom__">Custom binary path...</SelectItem>
                    </SelectContent>
                  </Select>
                  <div className="flex items-center gap-1.5">
                    <Input
                      value={draft.binary}
                      onChange={(e) => patch({ binary: e.target.value })}
                      className="flex-1 font-mono text-xs"
                    />
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="shrink-0 text-xs"
                      onClick={() =>
                        setBrowserTarget({
                          field: "binary",
                          title: "เลือกไฟล์ Inference Engine (llama-server)",
                          filterMode: "binary",
                          initialPath: draft.binary,
                        })
                      }
                    >
                      <FolderOpenIcon className="mr-1.5 size-3.5" />
                      Browse...
                    </Button>
                  </div>
                </div>
              </div>

              <div className="grid min-w-0 gap-1.5">
                <Label className="text-xs">
                  LiteLLM Model Aliases (คั่นด้วยจุลภาค — รีสตาร์ท LiteLLM อัตโนมัติเมื่อ Save)
                </Label>
                <Input
                  value={aliasesText}
                  onChange={(e) => {
                    const text = e.target.value;
                    setAliasesText(text);
                    const parsed = text
                      .split(",")
                      .map((x) => x.trim())
                      .filter(Boolean);
                    patch({ aliases: parsed });
                  }}
                  placeholder="orchestrator, inkling, inkling-2-mini"
                  className="font-mono text-xs"
                />
              </div>
            </CardContent>
          </Card>

          {/* Basic Run Settings */}
          <Card className="py-4">
            <CardContent className="grid gap-4 px-4">
              <div className="grid gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Label className="font-medium text-sm">Context Length</Label>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {CTX_PRESETS.map((c) => (
                      <button
                        key={c}
                        type="button"
                        onClick={() => patch({ ctx_size: c })}
                        className={cn(
                          "rounded-md border px-2 py-0.5 font-mono text-xs transition-colors",
                          draft.ctx_size === c
                            ? "border-foreground bg-foreground text-background"
                            : "border-border text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {c >= 1024 ? `${Math.round(c / 1024)}K` : c}
                      </button>
                    ))}
                    <Input
                      type="number"
                      min={2048}
                      max={1048576}
                      step={1024}
                      value={draft.ctx_size}
                      onChange={(e) => patch({ ctx_size: Math.max(2048, Number(e.target.value) || 8192) })}
                      className="h-7 w-24 font-mono text-xs"
                    />
                  </div>
                </div>
                <Slider
                  min={4096}
                  max={262144}
                  step={4096}
                  value={[Math.min(262144, draft.ctx_size)]}
                  onValueChange={(vals) => patch({ ctx_size: vals[0] ?? 32768 })}
                />
              </div>

              <div className="grid min-w-0 gap-4 md:grid-cols-2">
                <div className="grid gap-2">
                  <Label className="text-xs">Reasoning Effort</Label>
                  <div className="grid grid-cols-5 gap-1 rounded-lg border bg-muted/30 p-1">
                    {EFFORT_CHOICES.map((opt) => (
                      <button
                        key={opt.label}
                        type="button"
                        onClick={() => patch({ reasoning_effort: opt.value })}
                        className={cn(
                          "rounded-md py-1.5 font-medium text-xs transition-colors",
                          (draft.reasoning_effort || "") === opt.value
                            ? "bg-foreground text-background shadow-xs"
                            : "text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="grid min-w-0 gap-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-xs">Vision (mmproj)</Label>
                    <Switch
                      checked={draft.mmproj_enabled}
                      onCheckedChange={(v) => patch({ mmproj_enabled: v })}
                    />
                  </div>
                  {draft.mmproj_enabled && (
                    <div className="grid gap-1.5">
                      <Select
                        value={
                          mmprojFiles.some((g) => g.display_path === draft.mmproj_path || g.path === draft.mmproj_path)
                            ? draft.mmproj_path
                            : "__none__"
                        }
                        onValueChange={(v) => {
                          if (v !== "__none__") patch({ mmproj_path: v });
                        }}
                      >
                        <SelectTrigger className="h-8 w-full min-w-0 text-xs">
                          <SelectValue placeholder="เลือกไฟล์ mmproj..." />
                        </SelectTrigger>
                        <SelectContent>
                          {mmprojFiles.map((g) => (
                            <SelectItem key={g.path} value={g.display_path || g.path}>
                              {g.name} ({g.size_gib} GiB)
                            </SelectItem>
                          ))}
                          <SelectItem value="__none__">(ยังไม่เลือก / ใส่เอง)</SelectItem>
                        </SelectContent>
                      </Select>
                      <div className="flex items-center gap-1.5">
                        <Input
                          value={draft.mmproj_path}
                          onChange={(e) => patch({ mmproj_path: e.target.value })}
                          placeholder="/Users/.../mmproj.gguf"
                          className="h-8 flex-1 font-mono text-xs"
                        />
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-8 shrink-0 text-xs"
                          onClick={() =>
                            setBrowserTarget({
                              field: "mmproj_path",
                              title: "เลือกไฟล์ Vision (mmproj.gguf)",
                              filterMode: ".gguf",
                              initialPath: draft.mmproj_path,
                            })
                          }
                        >
                          <FolderOpenIcon className="mr-1.5 size-3.5" />
                          Browse...
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Advanced Settings Toggle */}
          <div className="rounded-xl border bg-card">
            <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <CpuIcon className="size-4 text-foreground" />
                <span className="font-medium text-sm">Advanced Settings</span>
                <Badge variant="outline" className="font-mono text-xs">
                  KV: {draft.kv_cache_type} · Spec: {draft.speculative_mode} · -np {draft.parallel_slots}
                </Badge>
              </div>
              <Switch checked={advancedOpen} onCheckedChange={setAdvancedOpen} />
            </div>

            {advancedOpen && (
              <div className="grid gap-5 border-t px-4 py-4">
                {/* MEMORY */}
                <div className="grid gap-3">
                  <div className="font-semibold text-muted-foreground text-xs uppercase tracking-wider">Memory</div>
                  <div className="grid min-w-0 gap-4 md:grid-cols-3">
                    <div className="grid min-w-0 gap-1.5">
                      <Label className="text-xs">KV Cache Dtype</Label>
                      <Select
                        value={draft.kv_cache_type}
                        onValueChange={(v) => patch({ kv_cache_type: v as SlotConfig["kv_cache_type"] })}
                      >
                        <SelectTrigger className="w-full min-w-0">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="f16">f16 (เร็วสุดบน Inkling 2 / แม่นสุด)</SelectItem>
                          <SelectItem value="q8_0">q8_0 (สมดุล ประหยัด RAM 50%)</SelectItem>
                          <SelectItem value="q4_0">q4_0 (ประหยัด RAM สูงสุด)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="grid gap-1.5">
                      <Label className="text-xs">GPU Layers (-ngl)</Label>
                      <Input
                        type="number"
                        min={0}
                        max={200}
                        value={draft.gpu_layers}
                        onChange={(e) => patch({ gpu_layers: Math.max(0, Number(e.target.value) || 0) })}
                        className="font-mono"
                      />
                    </div>

                    <div className="grid gap-1.5">
                      <Label className="text-xs">Context Checkpoints</Label>
                      <Input
                        type="number"
                        min={0}
                        max={64}
                        value={draft.ctx_checkpoints}
                        onChange={(e) => patch({ ctx_checkpoints: Math.max(0, Number(e.target.value) || 0) })}
                        className="font-mono"
                      />
                    </div>
                  </div>

                  <div className="grid gap-3 md:grid-cols-3">
                    <div className="flex items-center justify-between rounded-lg border p-2.5">
                      <span className="text-xs">Flash Attention (-fa)</span>
                      <Switch checked={draft.flash_attn} onCheckedChange={(v) => patch({ flash_attn: v })} />
                    </div>
                    <div className="flex items-center justify-between rounded-lg border p-2.5">
                      <span className="text-xs">Context Shift</span>
                      <Switch checked={draft.context_shift} onCheckedChange={(v) => patch({ context_shift: v })} />
                    </div>
                    <div className="flex items-center justify-between rounded-lg border p-2.5">
                      <span className="flex items-center gap-1 text-xs">
                        <ShieldCheckIcon className="size-3.5 text-foreground" />
                        Network Sandbox
                      </span>
                      <Switch checked={draft.sandbox} onCheckedChange={(v) => patch({ sandbox: v })} />
                    </div>
                  </div>
                </div>

                <Separator />

                {/* PERFORMANCE */}
                <div className="grid gap-3">
                  <div className="font-semibold text-muted-foreground text-xs uppercase tracking-wider">Performance</div>
                  <div className="grid min-w-0 gap-4 md:grid-cols-3">
                    <div className="grid min-w-0 gap-1.5">
                      <Label className="text-xs">Speculative Decoding</Label>
                      <Select
                        value={draft.speculative_mode}
                        onValueChange={(v) => patch({ speculative_mode: v as SlotConfig["speculative_mode"] })}
                      >
                        <SelectTrigger className="w-full min-w-0">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="auto">Auto (ngram-mod · เร็วสุดบน Mac)</SelectItem>
                          <SelectItem value="dspark">DSpark Drafter (sidecar .gguf)</SelectItem>
                          <SelectItem value="off">Off</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="grid gap-1.5">
                      <Label className="text-xs">Parallel Slots (-np)</Label>
                      <Input
                        type="number"
                        min={1}
                        max={8}
                        value={draft.parallel_slots}
                        onChange={(e) => patch({ parallel_slots: Math.max(1, Number(e.target.value) || 1) })}
                        className="font-mono"
                      />
                    </div>

                    <div className="grid gap-1.5">
                      <Label className="text-xs">Threads / Batch Threads (-t / -tb)</Label>
                      <div className="grid grid-cols-2 gap-2">
                        <Input
                          type="number"
                          min={1}
                          max={16}
                          value={draft.threads}
                          onChange={(e) => patch({ threads: Math.max(1, Number(e.target.value) || 8) })}
                          className="font-mono"
                        />
                        <Input
                          type="number"
                          min={1}
                          max={16}
                          value={draft.threads_batch}
                          onChange={(e) => patch({ threads_batch: Math.max(1, Number(e.target.value) || 10) })}
                          className="font-mono"
                        />
                      </div>
                    </div>
                  </div>

                  {draft.speculative_mode === "dspark" && (
                    <div className="grid min-w-0 gap-3 rounded-lg border bg-muted/20 p-3 md:grid-cols-3">
                      <div className="grid min-w-0 gap-1.5 md:col-span-2">
                        <Label className="text-xs">DSpark Drafter File (.gguf)</Label>
                        <Select
                          value={
                            drafterFiles.some(
                              (g) => g.display_path === draft.draft_model_path || g.path === draft.draft_model_path,
                            )
                              ? draft.draft_model_path
                              : "__none__"
                          }
                          onValueChange={(v) => {
                            if (v !== "__none__") patch({ draft_model_path: v });
                          }}
                        >
                          <SelectTrigger className="h-8 w-full min-w-0 text-xs">
                            <SelectValue placeholder="เลือกไฟล์ DSpark..." />
                          </SelectTrigger>
                          <SelectContent>
                            {drafterFiles.map((g) => (
                              <SelectItem key={g.path} value={g.display_path || g.path}>
                                {g.name} ({g.size_gib} GiB)
                              </SelectItem>
                            ))}
                            <SelectItem value="__none__">(ไม่มี)</SelectItem>
                          </SelectContent>
                        </Select>
                        <div className="flex items-center gap-1.5">
                          <Input
                            value={draft.draft_model_path}
                            onChange={(e) => patch({ draft_model_path: e.target.value })}
                            placeholder="/Users/.../drafter.gguf"
                            className="h-8 flex-1 font-mono text-xs"
                          />
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-8 shrink-0 text-xs"
                            onClick={() =>
                              setBrowserTarget({
                                field: "draft_model_path",
                                title: "เลือกไฟล์ DSpark Drafter (.gguf)",
                                filterMode: ".gguf",
                                initialPath: draft.draft_model_path,
                              })
                            }
                          >
                            <FolderOpenIcon className="mr-1.5 size-3.5" />
                            Browse...
                          </Button>
                        </div>
                      </div>
                      <div className="grid gap-1.5">
                        <Label className="text-xs">Draft N-Max</Label>
                        <Input
                          type="number"
                          min={1}
                          max={7}
                          value={draft.draft_n_max}
                          onChange={(e) => patch({ draft_n_max: Math.max(1, Number(e.target.value) || 2) })}
                          className="h-8 font-mono text-xs"
                        />
                      </div>
                    </div>
                  )}

                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="grid gap-1.5">
                      <Label className="text-xs">Batch Size (-b, 0 = auto)</Label>
                      <Input
                        type="number"
                        min={0}
                        step={128}
                        value={draft.batch_size}
                        onChange={(e) => patch({ batch_size: Math.max(0, Number(e.target.value) || 0) })}
                        className="font-mono"
                      />
                    </div>
                    <div className="grid gap-1.5">
                      <Label className="text-xs">Micro-batch Size (-ub, 0 = auto)</Label>
                      <Input
                        type="number"
                        min={0}
                        step={64}
                        value={draft.ubatch_size}
                        onChange={(e) => patch({ ubatch_size: Math.max(0, Number(e.target.value) || 0) })}
                        className="font-mono"
                      />
                    </div>
                  </div>
                </div>

                <Separator />

                {/* OUTPUT & SERVER */}
                <div className="grid gap-3">
                  <div className="font-semibold text-muted-foreground text-xs uppercase tracking-wider">
                    Output & Server
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="flex items-center justify-between rounded-lg border p-3">
                      <div className="grid gap-0.5">
                        <span className="font-medium text-xs">Preserve Reasoning in History</span>
                        <span className="text-[11px] text-muted-foreground">
                          ปิด (--no-reasoning-preserve) เพื่อกัน context บวมใน Agent Loop
                        </span>
                      </div>
                      <Switch
                        checked={draft.reasoning_preserve}
                        onCheckedChange={(v) => patch({ reasoning_preserve: v })}
                      />
                    </div>

                    <div className="grid gap-1.5">
                      <Label className="text-xs">Reasoning Budget Tokens (-1 = unlimited)</Label>
                      <Input
                        type="number"
                        min={-1}
                        step={512}
                        value={draft.reasoning_budget}
                        onChange={(e) => patch({ reasoning_budget: Number(e.target.value) })}
                        className="font-mono"
                      />
                    </div>
                  </div>

                  <div className="grid gap-1.5">
                    <Label className="text-xs">Extra Arguments</Label>
                    <Textarea
                      rows={2}
                      value={draft.extra_args}
                      onChange={(e) => patch({ extra_args: e.target.value })}
                      placeholder="--rope-scaling yarn --yarn-orig-ctx 32768"
                      className="font-mono text-xs"
                    />
                  </div>
                </div>

                {/* Presets & Command Preview */}
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-muted/20 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Input
                      value={presetName}
                      onChange={(e) => setPresetName(e.target.value)}
                      placeholder="ชื่อ Preset เช่น fast-agent"
                      className="h-8 w-44 text-xs"
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-8"
                      disabled={!presetName.trim() || busyAction !== null}
                      onClick={() => void handlePreset("save", presetName)}
                    >
                      <BookmarkPlusIcon className="mr-1 size-3.5" /> Save Preset
                    </Button>
                    {presetNames.map((pname) => (
                      <div key={pname} className="flex items-center gap-0.5 rounded-md border bg-background px-1.5 py-0.5">
                        <button
                          type="button"
                          onClick={() => void handlePreset("apply", pname)}
                          className="px-1 font-mono text-xs hover:underline"
                        >
                          {pname}
                        </button>
                        <button
                          type="button"
                          aria-label={`Delete preset ${pname}`}
                          onClick={() => void handlePreset("delete", pname)}
                          className="text-muted-foreground hover:text-foreground"
                        >
                          <Trash2Icon className="size-3" />
                        </button>
                      </div>
                    ))}
                  </div>

                  <Button size="sm" variant="ghost" className="h-8 text-xs" onClick={() => setCmdOpen((v) => !v)}>
                    <TerminalIcon className="mr-1 size-3.5" />
                    Command Preview
                    {cmdOpen ? <ChevronUpIcon className="ml-1 size-3.5" /> : <ChevronDownIcon className="ml-1 size-3.5" />}
                  </Button>
                </div>

                {cmdOpen && (
                  <pre className="overflow-x-auto rounded-lg border bg-muted/50 p-3 font-mono text-foreground text-xs">
                    {slot.live.command_preview}
                  </pre>
                )}
              </div>
            )}
          </div>

          {/* Sticky Action Footer */}
          <div className="sticky bottom-2 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-background/95 p-3 shadow-lg backdrop-blur">
            <div className="flex items-center gap-2 text-muted-foreground text-xs">
              {dirty ? (
                <span>มีการแก้ไขที่ยังไม่บันทึก — กด Save หรือ Reload Model เพื่อใช้งานจริง</span>
              ) : (
                <span className="flex items-center gap-1 text-foreground">
                  <CheckCircle2Icon className="size-3.5" /> ซิงก์กับ llama.studio.env, LiteLLM และ Qwen Code แล้ว
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" disabled={busyAction !== null} onClick={() => void saveOnly()}>
                {busyAction === "save" ? <Loader2Icon className="animate-spin" /> : <SaveIcon />}
                Save
              </Button>
              <Button size="sm" disabled={busyAction !== null} onClick={() => void runAction("reload")}>
                {busyAction === "reload" ? <Loader2Icon className="animate-spin" /> : <RotateCcwIcon />}
                Reload Model
              </Button>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="logs" className="mt-4 flex flex-col gap-4">
          <Card className="py-4">
            <CardContent className="grid gap-3 px-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <ActivityIcon className="size-4 text-foreground" />
                  <span className="font-medium text-sm">Live Telemetry & Benchmark</span>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Input
                    value={testPrompt}
                    onChange={(e) => setTestPrompt(e.target.value)}
                    placeholder="ข้อความทดสอบ (ค่าเริ่มต้น: ตอบสั้นๆ 1 ประโยค)"
                    className="h-8 w-64 text-xs"
                  />
                  <Button size="sm" disabled={!isRunning || busyAction !== null} onClick={() => void runSpeedTest()}>
                    {busyAction === "test" ? <Loader2Icon className="animate-spin" /> : <ZapIcon />}
                    Run Test
                  </Button>
                  <Button size="sm" variant="outline" disabled={logsLoading} onClick={() => void loadLogs()}>
                    {logsLoading ? <Loader2Icon className="animate-spin" /> : "Refresh Logs"}
                  </Button>
                </div>
              </div>

              {logs?.timings.history && logs.timings.history.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {logs.timings.history.map((h, i) => (
                    <Badge key={`${h.tokens}-${i}`} variant="secondary" className="font-mono text-xs">
                      {h.tokens} tok · Gen {h.tg_tok_s}
                      {h.e2e_tok_s ? ` · E2E ${h.e2e_tok_s}` : ""} tok/s
                      {h.pp_tok_s ? ` (pp ${h.pp_tok_s})` : ""}
                    </Badge>
                  ))}
                </div>
              )}

              <pre className="max-h-[420px] overflow-auto rounded-lg border bg-muted/50 p-3 font-mono text-[11px] text-foreground leading-relaxed">
                {logs?.text || "ยังไม่มี log หรือยังไม่ได้โหลด log..."}
              </pre>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {browserTarget && (
        <FileBrowserModal
          open={browserTarget !== null}
          onOpenChange={(v) => {
            if (!v) setBrowserTarget(null);
          }}
          title={browserTarget.title}
          initialPath={browserTarget.initialPath}
          filterMode={browserTarget.filterMode}
          onSelect={(pickedPath, info) => {
            const field = browserTarget.field;
            if (info) {
              setExtraGgufs((prev) => ({
                ...prev,
                [info.path]: info,
                [pickedPath]: info,
              }));
            }
            patch({ [field]: pickedPath } as Partial<SlotConfig>);
          }}
        />
      )}
    </div>
  );
}
