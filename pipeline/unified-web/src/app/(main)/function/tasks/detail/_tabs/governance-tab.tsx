"use client";

import * as React from "react";

import {
  BrainIcon,
  CheckCircle2Icon,
  CircleAlertIcon,
  GitBranchIcon,
  LayersIcon,
  Loader2Icon,
  PlayIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  ShieldCheckIcon,
  SquareIcon,
  TerminalIcon,
  Trash2Icon,
  UploadIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type OverviewData = Awaited<ReturnType<typeof api.enterpriseTaskOverview>>;
type CveIntelItem = Awaited<ReturnType<typeof api.enterpriseEnrichCves>>["items"][number];
type PlaybookItem = Awaited<ReturnType<typeof api.enterpriseListPlaybooks>>["playbooks"][number];
type SandboxInfo = Awaited<ReturnType<typeof api.sandboxStatus>>["sandbox"];

const SCAN_MODES = [
  { id: "full", label: "Full Scan", desc: "Explore → Test → Correlate → Gate" },
  { id: "explore_only", label: "Explore Only", desc: "เก็บแผนที่ระบบและบันทึกเป็น Baseline" },
  { id: "test_only", label: "Test Only", desc: "ข้าม Recon ใช้ Baseline เดิมแล้วยิง Test ทันที" },
  { id: "retest", label: "Re-Test Open", desc: "ตรวจซ้ำเฉพาะช่องโหว่เดิมเพื่อยืนยัน Fixed/Reopened" },
  { id: "report_only", label: "Report Only", desc: "ไม่สแกนใหม่ อัปเดต Gate + เตรียมออกรายงานทันที" },
];

const TRIAGE_OPTIONS = ["new", "open", "in_progress", "noise", "fixed", "reopened"];
const VEX_OPTIONS = [
  { value: "none", label: "— VEX —" },
  { value: "affected", label: "Affected" },
  { value: "not_affected", label: "Not Affected" },
  { value: "fixed", label: "Fixed" },
  { value: "under_investigation", label: "Investigating" },
];

export function GovernanceTab({ taskId, onOpenReport }: { taskId: string; onOpenReport?: () => void }) {
  const [data, setData] = React.useState<OverviewData | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [cveIntel, setCveIntel] = React.useState<Record<string, CveIntelItem>>({});

  // Bundle editor state
  const [showNewBundle, setShowNewBundle] = React.useState(false);
  const [bName, setBName] = React.useState("");
  const [bPattern, setBPattern] = React.useState("");
  const [bAuthType, setBAuthType] = React.useState("bearer_token");
  const [bAuthHeader, setBAuthHeader] = React.useState("");
  const [bOpenAPI, setBOpenAPI] = React.useState("");
  const [bPostman, setBPostman] = React.useState("");
  const [bPolicy, setBPolicy] = React.useState("standard");
  const [bRateLimit, setBRateLimit] = React.useState("5");
  const [bExcludes, setBExcludes] = React.useState("");
  const [bNotes, setBNotes] = React.useState("");

  // PentAGI-inspired Semantic Playbooks & Per-Task Kali Sandbox state
  const [playbooks, setPlaybooks] = React.useState<PlaybookItem[]>([]);
  const [playbookTotal, setPlaybookTotal] = React.useState(0);
  const [pbQuery, setPbQuery] = React.useState("");
  const [showNewPlaybook, setShowNewPlaybook] = React.useState(false);
  const [pbTitle, setPbTitle] = React.useState("");
  const [pbTags, setPbTags] = React.useState("");
  const [pbBody, setPbBody] = React.useState("");

  const [sandbox, setSandbox] = React.useState<SandboxInfo | null>(null);
  const [sbCommand, setSbCommand] = React.useState("");
  const [sbOutput, setSbOutput] = React.useState("");

  const openApiInputRef = React.useRef<HTMLInputElement>(null);
  const postmanInputRef = React.useRef<HTMLInputElement>(null);

  const loadPentagiModules = React.useCallback(
    async (searchQ?: string) => {
      const [pbRes, sbRes] = await Promise.all([
        api.enterpriseListPlaybooks({ q: searchQ ?? pbQuery, task_id: taskId }).catch(() => null),
        api.sandboxStatus(taskId).catch(() => null),
      ]);
      if (pbRes?.ok) {
        setPlaybooks(pbRes.playbooks ?? []);
        setPlaybookTotal(pbRes.total_store ?? 0);
      }
      if (sbRes?.ok) {
        setSandbox(sbRes.sandbox);
      }
    },
    [pbQuery, taskId],
  );

  const loadOverview = React.useCallback(async () => {
    setLoading(true);
    try {
      const ov = await api.enterpriseTaskOverview(taskId);
      setData(ov);
      // Collect unique CVEs and enrich with EPSS + CISA KEV + VEX
      const cves = new Set<string>();
      const vexMap: Record<string, { status: string; justification: string }> = {};
      for (const f of ov.findings ?? []) {
        for (const c of f.cves ?? []) {
          cves.add(c);
          if (f.vex_status) {
            vexMap[c] = { status: f.vex_status, justification: f.vex_justification || "" };
          }
        }
      }
      if (cves.size > 0) {
        api
          .enterpriseEnrichCves([...cves], vexMap)
          .then((res) => {
            const byId: Record<string, CveIntelItem> = {};
            for (const it of res.items ?? []) byId[it.cve] = it;
            setCveIntel(byId);
          })
          .catch(() => {});
      }
    } catch (e) {
      toast.error("โหลดข้อมูล Governance ไม่สำเร็จ: " + (e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  React.useEffect(() => {
    void loadOverview();
    void loadPentagiModules("");
  }, [loadOverview, loadPentagiModules]);

  async function runAction(key: string, fn: () => Promise<void>) {
    setBusy(key);
    try {
      await fn();
      await loadOverview();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function uploadSpec(kind: "openapi" | "postman", file: File) {
    setBusy(`upload-${kind}`);
    try {
      const res = await api.enterpriseUploadBundleSpec(kind, file);
      if (kind === "openapi") setBOpenAPI(res.path);
      else setBPostman(res.path);
      toast.success(`อัปโหลดไฟล์ ${res.name} ลง ${res.path} สำเร็จ`);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function saveNewBundle() {
    if (!bName.trim()) {
      toast.error("กรุณากรอกชื่อ Bundle");
      return;
    }
    await runAction("save-bundle", async () => {
      const authConfig: Record<string, unknown> = {};
      if (bAuthType !== "none" && bAuthHeader.trim()) {
        if (bAuthType === "cookie_session") authConfig.cookie = bAuthHeader.trim();
        else if (bAuthType === "api_key") authConfig.api_key = bAuthHeader.trim();
        else if (bAuthType === "login_sequence") authConfig.login_steps = bAuthHeader.trim();
        else authConfig.authorization = bAuthHeader.trim();
      }
      const excludes = bExcludes
        .split(/[\n,]/)
        .map((x) => x.trim())
        .filter(Boolean);
      const saved = await api.enterpriseSaveBundle({
        name: bName.trim(),
        target_pattern: bPattern.trim(),
        auth_type: bAuthType,
        auth_config: authConfig,
        openapi_path: bOpenAPI.trim(),
        postman_path: bPostman.trim(),
        test_policy: bPolicy,
        exclude_paths: excludes,
        rate_limit_rps: Number(bRateLimit) || 5,
        notes: bNotes.trim(),
      });
      await api.enterpriseAttachBundle({ bundle_id: saved.id, task_id: Number(taskId) || 0 });
      setShowNewBundle(false);
      setBName("");
      setBPattern("");
      setBAuthHeader("");
      setBOpenAPI("");
      setBPostman("");
      setBExcludes("");
      setBNotes("");
      toast.success("บันทึกและผูก Scan Context Bundle กับภารกิจนี้แล้ว");
    });
  }

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center py-16 text-muted-foreground text-sm">
        <Loader2Icon className="mr-2 size-4 animate-spin" /> กำลังโหลด Enterprise Governance...
      </div>
    );
  }

  const gate = data?.gate;
  const profile = data?.profile;
  const corr = data?.correlation;
  const fixGroups = data?.fix_groups ?? [];
  const findings = data?.findings ?? [];
  const baselines = data?.baselines ?? [];
  const bundles = data?.bundles ?? [];

  return (
    <div className="flex flex-col gap-4">
      {/* 1. Control-Plane Quality Gate (Engine != Ready) */}
      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 pb-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-sm">
              <ShieldCheckIcon className="size-4" /> Control-Plane Quality Gate (Engine ≠ Ready)
            </CardTitle>
            <CardDescription className="text-xs">
              Control Plane ตรวจความสมบูรณ์ของ Auth, WAF, Asset Coverage, หลักฐาน PoC และ Goals แยกขาดจากโมเดล AI ก่อนอนุมัติสถานะ Ready
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {gate && (
              <>
                <Badge
                  variant={gate.gate_status === "ready" ? "default" : "outline"}
                  className={cn(
                    "font-mono text-xs uppercase",
                    gate.gate_status === "ready"
                      ? "bg-foreground text-background"
                      : "border-foreground/50 text-foreground",
                  )}
                >
                  {gate.gate_status}
                </Badge>
                <Badge variant="secondary" className="font-mono text-xs">
                  Exit: {gate.exit_code}
                </Badge>
              </>
            )}
            <Button
              size="sm"
              variant="outline"
              disabled={busy !== null}
              onClick={() =>
                void runAction("eval-gate", async () => {
                  await api.enterpriseEvaluateGate(taskId);
                  toast.success("ประเมิน Control-Plane Quality Gate ใหม่เรียบร้อย");
                })
              }
            >
              {busy === "eval-gate" ? <Loader2Icon className="size-3.5 animate-spin" /> : <RefreshCwIcon className="size-3.5" />}
              Re-Evaluate Gate
            </Button>
            {gate && gate.gate_status !== "ready" && (
              <Button
                size="sm"
                disabled={busy !== null}
                onClick={() =>
                  void runAction("override-gate", async () => {
                    await api.enterpriseOverrideGate(taskId, {
                      gate_status: "ready",
                      exit_code: "OperatorApproved",
                      exit_reason: "ผู้ปฏิบัติงานตรวจสอบแล้วและอนุมัติสถานะ Ready",
                    });
                    toast.success("อนุมัติสถานะ Ready โดยผู้ปฏิบัติงานแล้ว");
                  })
                }
              >
                Approve Ready
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="grid gap-3">
          {gate?.exit_reason && (
            <div className="rounded-md border bg-muted/40 px-3 py-2 text-xs text-foreground">
              <span className="font-semibold">คำวินิจฉัย: </span>
              {gate.exit_reason}
              <span className="ml-2 font-mono text-muted-foreground">({gate.evaluated_by})</span>
            </div>
          )}
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {(gate?.checks ?? []).map((chk) => (
              <div key={chk.name} className="rounded-lg border bg-card/60 p-2.5 text-xs">
                <div className="flex items-center justify-between gap-1 font-mono font-medium">
                  <span className="truncate">{chk.name}</span>
                  {chk.passed ? (
                    <CheckCircle2Icon className="size-3.5 shrink-0 text-foreground" />
                  ) : (
                    <CircleAlertIcon className="size-3.5 shrink-0 text-muted-foreground" />
                  )}
                </div>
                <p className="mt-1 text-[11px] text-muted-foreground leading-snug">{chk.detail}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* 2. Scan Operation Modes & Incremental Reference Baseline */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <GitBranchIcon className="size-4" /> Scan Operation Modes & Incremental Reference Baseline
          </CardTitle>
          <CardDescription className="text-xs">
            เลือกโหมดทำงานแบบ AppScan เพื่อลดเวลาและ RAM บนเครื่อง (ExploreOnly เก็บ Baseline → TestOnly ข้าม Recon → ReTest ยืนยันการแก้ → ReportOnly ออกรายงานทันที)
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {SCAN_MODES.map((m) => {
              const active = (profile?.scan_mode || "full") === m.id;
              return (
                <button
                  key={m.id}
                  type="button"
                  disabled={busy !== null}
                  onClick={() =>
                    void runAction(`op-${m.id}`, async () => {
                      const res = await api.enterpriseRunScanOperation(taskId, {
                        operation: m.id,
                        baseline_task_id: profile?.baseline_task_id || 0,
                        bundle_id: profile?.bundle_id || 0,
                      });
                      toast.success(res.message || `รันโหมด ${m.label} เรียบร้อย`);
                      if (m.id === "report_only" && onOpenReport) onOpenReport();
                    })
                  }
                  className={cn(
                    "flex flex-col gap-1 rounded-lg border p-2.5 text-left transition-colors",
                    active ? "border-foreground bg-muted/60" : "border-border bg-card/50 hover:border-foreground/50",
                  )}
                >
                  <div className="flex items-center justify-between gap-1 text-xs font-medium">
                    <span>{m.label}</span>
                    <PlayIcon className="size-3 text-muted-foreground" />
                  </div>
                  <span className="text-[11px] text-muted-foreground leading-snug">{m.desc}</span>
                </button>
              );
            })}
          </div>

          <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-muted/20 p-3 text-xs">
            <div className="flex items-center gap-2">
              <span className="font-medium text-muted-foreground">Reference Baseline:</span>
              <Select
                value={String(profile?.baseline_task_id || 0)}
                onValueChange={(v) =>
                  void runAction("set-baseline", async () => {
                    const res = await api.enterpriseUpdateScanProfile(taskId, { baseline_task_id: Number(v) });
                    toast.success(
                      res.baseline_assets_inherited
                        ? `ผูก Baseline และสืบทอด ${res.baseline_assets_inherited} assets เรียบร้อย`
                        : "อัปเดต Reference Baseline แล้ว",
                    );
                  })
                }
              >
                <SelectTrigger className="h-8 w-64 text-xs">
                  <SelectValue placeholder="เลือก Baseline Task" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="0">— ไม่ใช้ Baseline —</SelectItem>
                  {baselines
                    .filter((b) => String(b.task_id) !== String(taskId))
                    .map((b) => (
                      <SelectItem key={b.task_id} value={String(b.task_id)}>
                        #{b.task_id} · {(b.name || b.description).slice(0, 34)} ({b.asset_count} assets)
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-center gap-2">
              <span className="font-medium text-muted-foreground">Scan Bundle:</span>
              <Select
                value={String(profile?.bundle_id || 0)}
                onValueChange={(v) =>
                  void runAction("attach-bundle", async () => {
                    await api.enterpriseAttachBundle({ bundle_id: Number(v), task_id: Number(taskId) || 0 });
                    toast.success("อัปเดต Auth / OpenAPI Bundle สำหรับภารกิจนี้แล้ว");
                  })
                }
              >
                <SelectTrigger className="h-8 w-56 text-xs">
                  <SelectValue placeholder="เลือก Scan Bundle" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="0">— ไม่ผูก Bundle —</SelectItem>
                  {bundles.map((b) => (
                    <SelectItem key={b.id} value={String(b.id)}>
                      {b.name} ({b.test_policy})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="ml-auto flex items-center gap-2">
              <Switch
                checked={Boolean(profile?.is_reference_baseline)}
                onCheckedChange={(checked) =>
                  void runAction("toggle-ref", async () => {
                    await api.enterpriseUpdateScanProfile(taskId, { is_reference_baseline: checked });
                    toast.success(checked ? "บันทึก Task นี้เป็น Reference Baseline แล้ว" : "ยกเลิก Reference Baseline แล้ว");
                  })
                }
              />
              <span className="font-medium">Preserve as Reference Baseline</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 3. Root-Cause FixGroups & Cross-Run Correlation */}
      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 pb-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-sm">
              <LayersIcon className="size-4" /> Root-Cause FixGroups & Cross-Run Issue Correlation
            </CardTitle>
            <CardDescription className="text-xs">
              จัดกลุ่มช่องโหว่ตามจุดแก้ไขจริง ("แก้ 1 จุด ปิดได้ N ช่องโหว่") และจับคู่ Fingerprint ข้ามรอบเพื่อคัดกรอง Noise / ตรวจจับ Reopened / ปิด Fixed อัตโนมัติ
            </CardDescription>
          </div>
          <Button
            size="sm"
            variant="outline"
            disabled={busy !== null}
            onClick={() =>
              void runAction("correlate", async () => {
                await api.enterpriseCorrelateTask(taskId);
                toast.success("รัน Cross-Run Correlation และจัดกลุ่ม FixGroups เรียบร้อย");
              })
            }
          >
            {busy === "correlate" ? <Loader2Icon className="size-3.5 animate-spin" /> : <RefreshCwIcon className="size-3.5" />}
            Run Correlation
          </Button>
        </CardHeader>
        <CardContent className="grid gap-3">
          {corr && (
            <div className="flex flex-wrap gap-2 font-mono text-xs">
              <Badge variant="secondary">Total: {corr.total}</Badge>
              <Badge variant="outline">New: {corr.new_count}</Badge>
              <Badge variant="outline">Open: {corr.open_count}</Badge>
              <Badge variant="outline">Reopened: {corr.reopened_count}</Badge>
              <Badge variant="outline">Fixed: {corr.fixed_count}</Badge>
              <Badge variant="secondary">Noise Suppressed: {corr.noise_count}</Badge>
              <Badge className="bg-foreground text-background hover:bg-foreground">FixGroups: {corr.fix_group_count}</Badge>
            </div>
          )}

          {fixGroups.length === 0 ? (
            <div className="rounded-md border border-dashed py-8 text-center text-muted-foreground text-xs">
              ยังไม่มี FixGroup สำหรับ Task #{taskId}
            </div>
          ) : (
            <div className="grid gap-2">
              {fixGroups.map((fg) => (
                <div key={fg.fix_group_key} className="rounded-lg border bg-card/50 p-3 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline" className="font-mono text-[10px] uppercase">
                        {fg.highest_severity}
                      </Badge>
                      <Badge variant="secondary" className="font-mono text-[10px]">
                        {fg.type}
                      </Badge>
                      <span className="font-medium text-foreground">{fg.subject}</span>
                    </div>
                    <Badge className="bg-foreground text-background font-mono text-[10px] hover:bg-foreground">
                      แก้จุดเดียว ปิดได้ {fg.active_count} ช่องโหว่ (รวม {fg.total_count})
                    </Badge>
                  </div>
                  <p className="mt-1.5 text-muted-foreground">{fg.remediation_hint}</p>
                  {fg.cves && fg.cves.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5 font-mono text-[10px]">
                      {fg.cves.map((c) => {
                        const intel = cveIntel[c];
                        return (
                          <Badge key={c} variant="outline" className="font-mono text-[10px]">
                            {c}
                            {intel?.epss_pct != null ? ` · EPSS ${intel.epss_pct}%` : ""}
                            {intel?.in_cisa_kev ? " · CISA KEV" : ""}
                          </Badge>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 4. Finding Lifecycle Triage, Fingerprints, VEX & Live EPSS/KEV */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Finding Fingerprint Lifecycle, VEX & EPSS / CISA KEV</CardTitle>
          <CardDescription className="text-xs">
            ตั้งสถานะเป็น <code className="font-mono">noise</code> เพื่อปิด False Positive ถาวรข้ามรอบสแกน หรือระบุ VEX (<code className="font-mono">not_affected</code>) เพื่อให้ Report Studio นำไปคำนวณความเสี่ยงจริง
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2">
          {findings.length === 0 ? (
            <div className="rounded-md border border-dashed py-8 text-center text-muted-foreground text-xs">
              ยังไม่มี Finding ใน Task #{taskId}
            </div>
          ) : (
            findings.map((f) => (
              <div
                key={f.id}
                className={cn(
                  "flex flex-col gap-2 rounded-lg border p-3 text-xs",
                  f.triage_status === "noise" ? "border-dashed bg-muted/20 opacity-70" : "bg-card/60",
                )}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
                    <Badge variant="outline" className="font-mono text-[10px] uppercase">
                      {f.severity || "info"}
                    </Badge>
                    <span className="truncate font-medium text-foreground">
                      #{f.id} {f.name || f.vulnclass}
                    </span>
                    <span className="font-mono text-[10px] text-muted-foreground">fp:{f.fingerprint.slice(0, 10)}</span>
                    {f.seen_count > 1 && (
                      <Badge variant="secondary" className="font-mono text-[10px]">
                        seen {f.seen_count}x
                      </Badge>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Select
                      value={f.triage_status || "new"}
                      onValueChange={(v) =>
                        void runAction(`triage-${f.id}`, async () => {
                          await api.enterpriseTriageFinding(f.id, { triage_status: v });
                          toast.success(`อัปเดต Finding #${f.id} เป็น ${v}`);
                        })
                      }
                    >
                      <SelectTrigger className="h-7 w-32 font-mono text-[11px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {TRIAGE_OPTIONS.map((opt) => (
                          <SelectItem key={opt} value={opt} className="font-mono text-xs">
                            {opt}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>

                    <Select
                      value={f.vex_status || "none"}
                      onValueChange={(v) =>
                        void runAction(`vex-${f.id}`, async () => {
                          await api.enterpriseTriageFinding(f.id, { vex_status: v === "none" ? "" : v });
                          toast.success(`บันทึก VEX ของ Finding #${f.id} แล้ว`);
                        })
                      }
                    >
                      <SelectTrigger className="h-7 w-32 font-mono text-[11px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {VEX_OPTIONS.map((opt) => (
                          <SelectItem key={opt.value} value={opt.value} className="text-xs">
                            {opt.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                {f.cves && f.cves.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 font-mono text-[10px]">
                    {f.cves.map((c) => {
                      const intel = cveIntel[c];
                      return (
                        <Badge
                          key={c}
                          variant={intel?.in_cisa_kev ? "default" : "secondary"}
                          className={cn(
                            "font-mono text-[10px]",
                            intel?.in_cisa_kev && "bg-foreground text-background",
                          )}
                        >
                          {c}
                          {intel?.cvss ? ` · CVSS ${intel.cvss}` : ""}
                          {intel?.epss_pct != null ? ` · EPSS ${intel.epss_pct}%` : ""}
                          {intel?.in_cisa_kev ? " · CISA KEV" : ""}
                        </Badge>
                      );
                    })}
                  </div>
                )}
                {f.triage_note && <p className="text-[11px] text-muted-foreground">{f.triage_note}</p>}
              </div>
            ))
          )}
        </CardContent>
      </Card>

      {/* 5. Reusable Auth, OpenAPI / Postman & TestPolicy Bundles */}
      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 pb-3">
          <div>
            <CardTitle className="text-sm">Reusable Auth, OpenAPI / Postman & TestPolicy Bundles</CardTitle>
            <CardDescription className="text-xs">
              บันทึกข้อมูล Login / API Key / OpenAPI / Postman และ Exclude Paths ครั้งเดียว ใช้ซ้ำได้ทั้งใน Graph Chat (`/chat`), ARTEX Workers และ Deep Agent IDE (`/ai`)
            </CardDescription>
          </div>
          <Button size="sm" variant="outline" onClick={() => setShowNewBundle((v) => !v)}>
            <PlusIcon className="size-3.5" /> {showNewBundle ? "ปิดฟอร์ม" : "New Bundle"}
          </Button>
        </CardHeader>
        <CardContent className="grid gap-3">
          {showNewBundle && (
            <div className="grid gap-2.5 rounded-lg border bg-muted/30 p-3 text-xs">
              <div className="grid gap-2 sm:grid-cols-2">
                <Input placeholder="ชื่อ Bundle เช่น Staging API Admin" value={bName} onChange={(e) => setBName(e.target.value)} className="h-8 text-xs" />
                <Input placeholder="Target Pattern เช่น api.example.com" value={bPattern} onChange={(e) => setBPattern(e.target.value)} className="h-8 text-xs" />
              </div>
              <div className="grid gap-2 sm:grid-cols-3">
                <Select value={bAuthType} onValueChange={setBAuthType}>
                  <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Auth Type" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">No Auth</SelectItem>
                    <SelectItem value="bearer_token">Bearer Token</SelectItem>
                    <SelectItem value="api_key">API Key Header</SelectItem>
                    <SelectItem value="cookie_session">Cookie Session</SelectItem>
                    <SelectItem value="login_sequence">Login Sequence</SelectItem>
                  </SelectContent>
                </Select>
                <Select value={bPolicy} onValueChange={setBPolicy}>
                  <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Test Policy" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="standard">Standard Balanced</SelectItem>
                    <SelectItem value="fast_passive">Fast / Passive Only</SelectItem>
                    <SelectItem value="owasp_api_top10">OWASP API Top 10</SelectItem>
                    <SelectItem value="owasp_web_full">OWASP Web Full</SelectItem>
                    <SelectItem value="code_script_audit">Code & Script Audit</SelectItem>
                  </SelectContent>
                </Select>
                <Input placeholder="Rate Limit (RPS)" value={bRateLimit} onChange={(e) => setBRateLimit(e.target.value)} className="h-8 text-xs" />
              </div>

              {bAuthType !== "none" && (
                <Input
                  placeholder="Authorization header / Cookie / API Key หรือขั้นตอน Login"
                  value={bAuthHeader}
                  onChange={(e) => setBAuthHeader(e.target.value)}
                  className="h-8 font-mono text-xs"
                />
              )}

              <div className="grid gap-2 sm:grid-cols-2">
                <div className="flex gap-1.5">
                  <Input placeholder="/workspace/profiles/openapi.json" value={bOpenAPI} onChange={(e) => setBOpenAPI(e.target.value)} className="h-8 font-mono text-xs" />
                  <input ref={openApiInputRef} type="file" accept=".json,.yaml,.yml" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void uploadSpec("openapi", f); }} />
                  <Button size="sm" variant="outline" className="h-8 shrink-0" onClick={() => openApiInputRef.current?.click()}>
                    <UploadIcon className="size-3.5" /> OpenAPI
                  </Button>
                </div>
                <div className="flex gap-1.5">
                  <Input placeholder="/workspace/profiles/postman.json" value={bPostman} onChange={(e) => setBPostman(e.target.value)} className="h-8 font-mono text-xs" />
                  <input ref={postmanInputRef} type="file" accept=".json" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void uploadSpec("postman", f); }} />
                  <Button size="sm" variant="outline" className="h-8 shrink-0" onClick={() => postmanInputRef.current?.click()}>
                    <UploadIcon className="size-3.5" /> Postman
                  </Button>
                </div>
              </div>

              <Input placeholder="Exclude Paths คั่นด้วยลูกน้ำ เช่น /logout, /admin/delete, /billing/charge" value={bExcludes} onChange={(e) => setBExcludes(e.target.value)} className="h-8 font-mono text-xs" />
              <Textarea rows={2} placeholder="หมายเหตุ Policy / ขอบเขตเพิ่มเติม" value={bNotes} onChange={(e) => setBNotes(e.target.value)} className="text-xs" />
              <div className="flex justify-end">
                <Button size="sm" disabled={busy !== null} onClick={() => void saveNewBundle()}>
                  Save & Attach Bundle
                </Button>
              </div>
            </div>
          )}

          {bundles.length === 0 ? (
            <div className="rounded-md border border-dashed py-6 text-center text-muted-foreground text-xs">
              ยังไม่มี Scan Context Bundle — กด New Bundle เพื่อเก็บ Auth / OpenAPI / Postman ไว้ใช้ซ้ำ
            </div>
          ) : (
            <div className="grid gap-2">
              {bundles.map((b) => {
                const isAttached = profile?.bundle_id === b.id;
                return (
                  <div
                    key={b.id}
                    className={cn(
                      "flex flex-wrap items-center justify-between gap-2 rounded-lg border p-2.5 text-xs",
                      isAttached ? "border-foreground bg-muted/50" : "bg-card/50",
                    )}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="font-medium text-foreground">{b.name}</span>
                        <Badge variant="outline" className="font-mono text-[10px]">{b.auth_type}</Badge>
                        <Badge variant="secondary" className="font-mono text-[10px]">{b.test_policy} · {b.rate_limit_rps} rps</Badge>
                        {isAttached && <Badge className="bg-foreground text-background text-[10px]">Attached</Badge>}
                      </div>
                      <div className="mt-1 flex flex-wrap gap-2 font-mono text-[10px] text-muted-foreground">
                        {b.target_pattern && <span>target: {b.target_pattern}</span>}
                        {b.openapi_path && <span>openapi: {b.openapi_path.split("/").pop()}</span>}
                        {b.postman_path && <span>postman: {b.postman_path.split("/").pop()}</span>}
                        {b.exclude_paths?.length > 0 && <span>exclude: {b.exclude_paths.join(", ")}</span>}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5">
                      {!isAttached && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs"
                          onClick={() =>
                            void runAction(`att-${b.id}`, async () => {
                              await api.enterpriseAttachBundle({ bundle_id: b.id, task_id: Number(taskId) || 0 });
                              toast.success(`ผูก Bundle "${b.name}" แล้ว`);
                            })
                          }
                        >
                          Attach
                        </Button>
                      )}
                      <Button
                        size="icon"
                        variant="ghost"
                        className="size-7 text-muted-foreground hover:text-foreground"
                        onClick={() =>
                          void runAction(`del-${b.id}`, async () => {
                            await api.enterpriseDeleteBundle(b.id);
                            toast.success(`ลบ Bundle "${b.name}" แล้ว`);
                          })
                        }
                      >
                        <Trash2Icon className="size-3.5" />
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 6. pgvector Semantic Playbook Memory */}
      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 pb-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-sm">
              <BrainIcon className="size-4" /> pgvector Semantic Playbook Memory
            </CardTitle>
            <CardDescription className="text-xs">
              หน่วยความจำเชิงความหมายบน PostgreSQL (pgvector + pg_trgm) ดึงเทคนิคเจาะและรูปแบบ CMS/Tech ที่เคยสำเร็จจากเคสเก่ามาฉีดให้ Cyber-Tiel อัตโนมัติ
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary" className="font-mono text-xs">
              Indexed: {playbookTotal}
            </Badge>
            <Button
              size="sm"
              variant="outline"
              disabled={busy !== null}
              onClick={() =>
                void runAction("sync-pb", async () => {
                  const res = await api.enterpriseSyncPlaybooks(0);
                  await loadPentagiModules(pbQuery);
                  toast.success(`ซิงก์บทเรียนเข้า pgvector เพิ่ม ${res.synced} รายการ (รวม ${res.total_store})`);
                })
              }
            >
              {busy === "sync-pb" ? <Loader2Icon className="size-3.5 animate-spin" /> : <RefreshCwIcon className="size-3.5" />}
              Sync History
            </Button>
            <Button size="sm" variant="outline" onClick={() => setShowNewPlaybook((v) => !v)}>
              <PlusIcon className="size-3.5" /> Add Playbook
            </Button>
          </div>
        </CardHeader>
        <CardContent className="grid gap-3">
          <div className="flex gap-2">
            <Input
              value={pbQuery}
              onChange={(e) => setPbQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void loadPentagiModules(pbQuery);
              }}
              placeholder="ค้นหา Playbook เชิงความหมาย เช่น Laravel, WordPress, custom PHP PHPSESSID, JWT, IDOR..."
              className="h-8 text-xs"
            />
            <Button size="sm" variant="outline" className="h-8" onClick={() => void loadPentagiModules(pbQuery)}>
              <SearchIcon className="size-3.5" /> Search
            </Button>
          </div>

          {showNewPlaybook && (
            <div className="grid gap-2 rounded-lg border bg-muted/20 p-3 text-xs">
              <div className="grid gap-2 sm:grid-cols-2">
                <Input placeholder="หัวข้อ Playbook เช่น Laravel XSRF + Route Bypass" value={pbTitle} onChange={(e) => setPbTitle(e.target.value)} className="h-8 text-xs" />
                <Input placeholder="Tech Tags คั่นด้วยลูกน้ำ เช่น laravel, php, waf" value={pbTags} onChange={(e) => setPbTags(e.target.value)} className="h-8 font-mono text-xs" />
              </div>
              <Textarea rows={3} placeholder="ขั้นตอน เทคนิค หรือ payload ที่พิสูจน์แล้วว่าได้ผล..." value={pbBody} onChange={(e) => setPbBody(e.target.value)} className="font-mono text-xs" />
              <div className="flex justify-end">
                <Button
                  size="sm"
                  disabled={busy !== null}
                  onClick={() =>
                    void runAction("save-pb", async () => {
                      if (!pbTitle.trim() || !pbBody.trim()) {
                        toast.error("กรุณากรอกหัวข้อและเนื้อหา Playbook");
                        return;
                      }
                      await api.enterpriseSavePlaybook({
                        title: pbTitle.trim(),
                        playbook_text: pbBody.trim(),
                        tech_tags: pbTags.split(",").map((x) => x.trim()).filter(Boolean),
                        task_id: Number(taskId) || 0,
                      });
                      setPbTitle("");
                      setPbTags("");
                      setPbBody("");
                      setShowNewPlaybook(false);
                      await loadPentagiModules(pbQuery);
                      toast.success("บันทึก Playbook ลง pgvector เรียบร้อย");
                    })
                  }
                >
                  Save to pgvector
                </Button>
              </div>
            </div>
          )}

          {playbooks.length === 0 ? (
            <div className="rounded-md border border-dashed py-6 text-center text-muted-foreground text-xs">
              ยังไม่มี Playbook ที่ตรงเงื่อนไข — กด Sync History เพื่อสกัดบทเรียนจาก Findings และ Recon Facts เดิมเข้า pgvector
            </div>
          ) : (
            <div className="grid gap-2">
              {playbooks.slice(0, 6).map((pb) => (
                <div key={pb.id} className="rounded-lg border bg-card/50 p-3 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="font-medium text-foreground">{pb.title}</span>
                      {pb.similarity != null && (
                        <Badge className="bg-foreground text-background font-mono text-[10px]">
                          {Math.round(pb.similarity * 100)}% match
                        </Badge>
                      )}
                      <Badge variant="outline" className="font-mono text-[10px]">{pb.source_kind}</Badge>
                      {(pb.tech_tags ?? []).map((t) => (
                        <Badge key={t} variant="secondary" className="font-mono text-[10px]">{t}</Badge>
                      ))}
                    </div>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="size-6 text-muted-foreground hover:text-foreground"
                      onClick={() =>
                        void runAction(`del-pb-${pb.id}`, async () => {
                          await api.enterpriseDeletePlaybook(pb.id);
                          await loadPentagiModules(pbQuery);
                          toast.success("ลบ Playbook แล้ว");
                        })
                      }
                    >
                      <Trash2Icon className="size-3.5" />
                    </Button>
                  </div>
                  <p className="mt-1.5 line-clamp-3 whitespace-pre-wrap font-mono text-[11px] text-muted-foreground leading-relaxed">
                    {pb.playbook_text}
                  </p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 7. Isolated Per-Task Ephemeral Kali Sandbox */}
      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 pb-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-sm">
              <TerminalIcon className="size-4" /> Isolated Per-Task Kali Sandbox Worker
            </CardTitle>
            <CardDescription className="text-xs">
              คอนเทนเนอร์ Kali Linux ชั่วคราวแยกขาดเฉพาะ Task #{taskId} (จำกัด 2 CPU · 2 GiB RAM · ไม่มี docker.sock) สำหรับคอมไพล์ exploit หรือรันเครื่องมือเฉพาะกิจโดยไม่ทำให้ระบบหลักรก
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              variant={sandbox?.running ? "default" : "outline"}
              className={cn("font-mono text-xs uppercase", sandbox?.running ? "bg-foreground text-background" : "")}
            >
              {sandbox?.running ? `RUNNING · ${sandbox.container}` : "NOT SPAWNED"}
            </Badge>
            {!sandbox?.running ? (
              <Button
                size="sm"
                disabled={busy !== null}
                onClick={() =>
                  void runAction("spawn-sb", async () => {
                    await api.sandboxSpawn(taskId);
                    await loadPentagiModules(pbQuery);
                    toast.success(`เปิด Kali Sandbox แยกสำหรับ Task #${taskId} แล้ว`);
                  })
                }
              >
                {busy === "spawn-sb" ? <Loader2Icon className="size-3.5 animate-spin" /> : <PlayIcon className="size-3.5" />}
                Spawn Kali Sandbox
              </Button>
            ) : (
              <Button
                size="sm"
                variant="outline"
                disabled={busy !== null}
                onClick={() =>
                  void runAction("destroy-sb", async () => {
                    await api.sandboxDestroy(taskId, false);
                    setSbOutput("");
                    await loadPentagiModules(pbQuery);
                    toast.success("ทำลายคอนเทนเนอร์ชั่วคราวเรียบร้อย (คืนทรัพยากรทันที)");
                  })
                }
              >
                {busy === "destroy-sb" ? <Loader2Icon className="size-3.5 animate-spin" /> : <SquareIcon className="size-3.5" />}
                Destroy Sandbox
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="grid gap-3 text-xs">
          {sandbox && (
            <div className="flex flex-wrap gap-2 font-mono text-[11px] text-muted-foreground">
              <span>Image: {sandbox.image}</span>
              <span>· Limits: {sandbox.limits.cpus} CPU / {sandbox.limits.memory} RAM / {sandbox.limits.pids} PIDs</span>
              <span>· Scratch files (/sandbox): {sandbox.scratch_files}</span>
              <span>· Auto-Reap TTL: {sandbox.ttl_minutes}m</span>
            </div>
          )}
          <div className="flex gap-2">
            <Input
              value={sbCommand}
              onChange={(e) => setSbCommand(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && sbCommand.trim()) {
                  void runAction("exec-sb", async () => {
                    const res = await api.sandboxExec(taskId, sbCommand, 60);
                    setSbOutput(
                      `[exit=${res.exit_code ?? "?"} · ${res.duration_ms ?? 0}ms · ${res.container ?? ""}]\n` +
                        (res.stdout || "") +
                        (res.stderr ? `\n[stderr]\n${res.stderr}` : "") +
                        (res.error ? `\n[error] ${res.error}` : ""),
                    );
                    await loadPentagiModules(pbQuery);
                  });
                }
              }}
              placeholder="รันคำสั่งทดสอบใน Kali Sandbox เฉพาะกิจ เช่น uname -a; which nmap sqlmap ffuf gcc..."
              className="h-8 font-mono text-xs"
            />
            <Button
              size="sm"
              variant="outline"
              className="h-8"
              disabled={busy !== null || !sbCommand.trim()}
              onClick={() =>
                void runAction("exec-sb", async () => {
                  const res = await api.sandboxExec(taskId, sbCommand, 60);
                  setSbOutput(
                    `[exit=${res.exit_code ?? "?"} · ${res.duration_ms ?? 0}ms · ${res.container ?? ""}]\n` +
                      (res.stdout || "") +
                      (res.stderr ? `\n[stderr]\n${res.stderr}` : "") +
                      (res.error ? `\n[error] ${res.error}` : ""),
                  );
                  await loadPentagiModules(pbQuery);
                })
              }
            >
              {busy === "exec-sb" ? <Loader2Icon className="size-3.5 animate-spin" /> : <PlayIcon className="size-3.5" />}
              Exec
            </Button>
          </div>
          {sbOutput && (
            <pre className="max-h-52 overflow-auto whitespace-pre-wrap rounded-md border bg-muted/40 p-2.5 font-mono text-[11px] leading-relaxed">
              {sbOutput}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
