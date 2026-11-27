"use client";

import * as React from "react";

import {
  CheckCircle2Icon,
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CopyIcon,
  DownloadIcon,
  FileTextIcon,
  Loader2Icon,
  RefreshCwIcon,
  ShieldCheckIcon,
  SparklesIcon,
  StarIcon,
  Trash2Icon,
  UploadIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Markdown } from "@/components/markdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api } from "@/lib/api";
import { cn, copyText } from "@/lib/utils";

interface TemplateSectionSummary {
  id: string;
  title: string;
  subsections: string[];
  table_headers: string[][];
  placeholders: string[];
}

interface ReportTemplateInfo {
  id: string;
  name: string;
  description: string;
  format: "docx" | "md";
  builtin: boolean;
  is_default: boolean;
  created_at: string;
  section_count: number;
  subsection_count: number;
  table_count: number;
  placeholder_count: number;
  sections: TemplateSectionSummary[];
}

interface GeneratedReportMeta {
  id: string;
  task_id: number;
  title: string;
  template_id: string;
  template_name: string;
  model: string;
  created_at: string;
  download_docx_url: string;
  download_md_url: string;
  warnings?: string[];
  stats?: {
    sections: number;
    subsections: number;
    tables: number;
    blocks: number;
    chars: number;
    gate_repairs: number;
    docx_size_bytes: number;
    md_size_bytes: number;
  };
}

interface ReportJobState {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  stage: string;
  completed_sections: number;
  total_sections: number;
  error?: string;
  report?: GeneratedReportMeta;
}

interface LinkedAssetRef {
  id: number;
  type: string;
  label: string;
  domain?: string;
  url?: string;
  ip?: string;
  port?: number | null;
}

interface SourceEvidenceRef {
  kind: "finding" | "fact";
  id?: number | string;
  title: string;
  excerpt: string;
}

interface CveIntelEntry {
  cve: string;
  cvss?: number | null;
  cvss_severity?: string;
  vector?: string;
  published?: string;
  epss_pct?: number | null;
  in_cisa_kev?: boolean;
  cwe?: string;
  mitre_techniques?: string[];
  summary?: string;
  thai_summary?: string;
  has_ai_summary?: boolean;
  vex_status?: string;
  risk_priority?: string;
  confirmation_status?: "confirmed" | "candidate";
  verification_note?: string;
  matched_software?: string[];
  affected_assets?: LinkedAssetRef[];
  affected_paths?: string[];
  source_refs?: SourceEvidenceRef[];
  reproduce_steps?: string;
}

interface FindingStandardEntry {
  finding_id?: number | string;
  title: string;
  severity: string;
  vulnclass: string;
  summary?: string;
  verification_status?: string;
  fix_group_subject?: string;
  cves: string[];
  cve_source: string;
  matched_software: string[];
  cwes: string[];
  owasp: string;
  mitre_attack: string[];
  affected_assets?: LinkedAssetRef[];
  affected_paths?: string[];
  evidence_excerpt?: string;
  http_traffic_excerpt?: string;
  reproduce_steps?: string;
}

interface ReconFactEntry {
  id?: number | string;
  origin?: string;
  source?: string;
  headline: string;
  detail: string;
  assets: LinkedAssetRef[];
  paths: string[];
}

interface TaskStandardsMapping {
  ok: boolean;
  task_id: number;
  task_title?: string;
  task_target?: string;
  active_finding_count: number;
  suppressed_noise_count?: number;
  cve_count: number;
  confirmed_cve_count?: number;
  candidate_cve_count?: number;
  kev_count: number;
  cwe_count: number;
  owasp_count: number;
  mitre_count: number;
  cwes: string[];
  owasp_categories: string[];
  mitre_techniques: string[];
  asset_counts?: {
    total: number;
    root_domains: number;
    subdomains: number;
    services: number;
    endpoints: number;
  };
  quality_gate?: {
    gate_status: string;
    exit_code: string;
    exit_reason: string;
  } | null;
  software_cves: { software: string; cves: string[] }[];
  cve_intel: CveIntelEntry[];
  findings: FindingStandardEntry[];
  recon_facts?: ReconFactEntry[];
}

async function reportStudioApi<T = Record<string, unknown>>(
  path: string,
  options?: { method?: "GET" | "POST"; body?: unknown },
): Promise<T> {
  const res = await fetch(`/model-studio-api/reports${path}`, {
    method: options?.method ?? "GET",
    headers: options?.body ? { "Content-Type": "application/json" } : undefined,
    body: options?.body ? JSON.stringify(options.body) : undefined,
    cache: "no-store",
  });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error(text || `HTTP ${res.status}`);
  }
  if (!res.ok) {
    const errObj = data as { error?: string; message?: string };
    throw new Error(errObj.error || errObj.message || `HTTP ${res.status}`);
  }
  return data as T;
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const res = String(reader.result || "");
      const comma = res.indexOf(",");
      resolve(comma >= 0 ? res.slice(comma + 1) : res);
    };
    reader.onerror = () => reject(new Error("อ่านไฟล์ไม่สำเร็จ"));
    reader.readAsDataURL(file);
  });
}

function fmtKb(bytes?: number): string {
  if (!bytes || bytes <= 0) return "";
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export function ReportTab({ taskId }: { taskId: string }) {
  const [templates, setTemplates] = React.useState<ReportTemplateInfo[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = React.useState<string>("");
  const [expandedTemplateId, setExpandedTemplateId] = React.useState<string | null>(null);
  const [uploadingTpl, setUploadingTpl] = React.useState(false);

  const [modelAlias, setModelAlias] = React.useState<string>("cyber-model");
  const [extraNotes, setExtraNotes] = React.useState<string>("");
  const [activeJob, setActiveJob] = React.useState<ReportJobState | null>(null);

  const [generatedReports, setGeneratedReports] = React.useState<GeneratedReportMeta[]>([]);
  const [selectedReportId, setSelectedReportId] = React.useState<string>("");
  const [previewMarkdown, setPreviewMarkdown] = React.useState<string>("");
  const [legacyReport, setLegacyReport] = React.useState<string>("");
  const [mappingData, setMappingData] = React.useState<TaskStandardsMapping | null>(null);
  const [refreshingMapping, setRefreshingMapping] = React.useState(false);
  const [expandedCves, setExpandedCves] = React.useState<Record<string, boolean>>({});
  const [expandedFindings, setExpandedFindings] = React.useState<Record<string, boolean>>({});
  const [expandedFacts, setExpandedFacts] = React.useState<Record<string, boolean>>({});
  const [aiSummaries, setAiSummaries] = React.useState<Record<string, string>>({});
  const [summarizingKey, setSummarizingKey] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [copied, setCopied] = React.useState(false);

  const tplInputRef = React.useRef<HTMLInputElement>(null);

  function toggleExpand(setter: React.Dispatch<React.SetStateAction<Record<string, boolean>>>, key: string) {
    setter((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  async function requestAiSummary(kind: "cve" | "finding", id: string, contextText: string) {
    const stateKey = `${kind}:${id}`;
    setSummarizingKey(stateKey);
    try {
      const res = await reportStudioApi<{ ok: boolean; thai_summary_ai: string }>("/summarize-item", {
        method: "POST",
        body: { kind, id, context: contextText },
      });
      if (res.thai_summary_ai) {
        setAiSummaries((prev) => ({ ...prev, [stateKey]: res.thai_summary_ai }));
        toast.success(`สรุปคำอธิบายเชิงลึกสำหรับ ${id} เรียบร้อย`);
      }
    } catch (e) {
      toast.error("เรียก Summarizer ไม่สำเร็จ: " + (e as Error).message);
    } finally {
      setSummarizingKey(null);
    }
  }

  const loadMapping = React.useCallback(async (showSpinner = false) => {
    if (showSpinner) setRefreshingMapping(true);
    try {
      const mRes = await reportStudioApi<TaskStandardsMapping>(
        `/mapping?task_id=${encodeURIComponent(taskId)}`,
      ).catch(() => null);
      if (mRes?.ok) setMappingData(mRes);
    } finally {
      if (showSpinner) setRefreshingMapping(false);
    }
  }, [taskId]);

  const loadAll = React.useCallback(async () => {
    setLoading(true);
    try {
      const [tplRes, listRes, jobsRes, mapRes, legacyTxt] = await Promise.all([
        reportStudioApi<{ ok: boolean; templates: ReportTemplateInfo[] }>("/templates").catch(() => ({
          ok: false,
          templates: [],
        })),
        reportStudioApi<{ ok: boolean; reports: GeneratedReportMeta[] }>(
          `/list?task_id=${encodeURIComponent(taskId)}`,
        ).catch(() => ({ ok: false, reports: [] })),
        reportStudioApi<{ ok: boolean; jobs: ReportJobState[]; active_job?: ReportJobState | null }>(
          `/jobs?task_id=${encodeURIComponent(taskId)}`,
        ).catch(() => ({ ok: false, jobs: [], active_job: null })),
        reportStudioApi<TaskStandardsMapping>(
          `/mapping?task_id=${encodeURIComponent(taskId)}`,
        ).catch(() => null),
        api.report(taskId).catch(() => ""),
      ]);

      if (mapRes?.ok) {
        setMappingData(mapRes);
      }

      // Automatically re-attach to any in-flight backend report job when returning to this tab or refreshing!
      if (jobsRes.active_job) {
        setActiveJob(jobsRes.active_job);
      }

      const tpls = tplRes.templates ?? [];
      setTemplates(tpls);
      setSelectedTemplateId((prev) => {
        if (prev && tpls.some((t) => t.id === prev)) return prev;
        return (tpls.find((t) => t.is_default) ?? tpls[0])?.id ?? "";
      });

      const rpts = listRes.reports ?? [];
      setGeneratedReports(rpts);
      setLegacyReport(legacyTxt || "");

      if (rpts.length > 0) {
        const chosenId = rpts[0].id;
        setSelectedReportId(chosenId);
        const contentRes = await reportStudioApi<{ ok: boolean; markdown?: string }>(
          `/content?id=${encodeURIComponent(chosenId)}`,
        ).catch(() => ({ ok: false, markdown: "" }));
        setPreviewMarkdown(contentRes.markdown || "");
      } else {
        setSelectedReportId("");
        setPreviewMarkdown(legacyTxt || "");
      }
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  React.useEffect(() => {
    void loadAll();
  }, [loadAll]);

  async function selectReportVersion(reportId: string) {
    setSelectedReportId(reportId);
    if (reportId === "__legacy__") {
      setPreviewMarkdown(legacyReport);
      return;
    }
    try {
      const res = await reportStudioApi<{ ok: boolean; markdown?: string }>(
        `/content?id=${encodeURIComponent(reportId)}`,
      );
      setPreviewMarkdown(res.markdown || "");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function handleUploadTemplate(files: File[]) {
    const file = files[0];
    if (!file) return;
    setUploadingTpl(true);
    try {
      const b64 = await readFileAsBase64(file);
      const baseName = file.name.replace(/\.(docx|md|markdown)$/i, "");
      const res = await reportStudioApi<{
        ok: boolean;
        template_id: string;
        templates: ReportTemplateInfo[];
      }>("/templates/upload", {
        method: "POST",
        body: {
          name: baseName,
          filename: file.name,
          content_base64: b64,
          set_default: true,
        },
      });
      setTemplates(res.templates ?? []);
      setSelectedTemplateId(res.template_id);
      setExpandedTemplateId(res.template_id);
      toast.success(`อัปโหลดและสกัดโครงสร้างแม่แบบ "${file.name}" สำเร็จ`);
    } catch (e) {
      toast.error("อัปโหลดแม่แบบไม่สำเร็จ: " + (e as Error).message);
    } finally {
      setUploadingTpl(false);
    }
  }

  async function handleSetDefault(id: string) {
    try {
      const res = await reportStudioApi<{ ok: boolean; templates: ReportTemplateInfo[] }>("/templates/default", {
        method: "POST",
        body: { id },
      });
      setTemplates(res.templates ?? []);
      setSelectedTemplateId(id);
      toast.success("ตั้งเป็นแม่แบบเริ่มต้นแล้ว");
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function handleDeleteTemplate(tpl: ReportTemplateInfo) {
    try {
      const res = await reportStudioApi<{ ok: boolean; templates: ReportTemplateInfo[] }>("/templates/delete", {
        method: "POST",
        body: { id: tpl.id },
      });
      const next = res.templates ?? [];
      setTemplates(next);
      if (selectedTemplateId === tpl.id) {
        setSelectedTemplateId((next.find((t) => t.is_default) ?? next[0])?.id ?? "");
      }
      toast.success(`ลบแม่แบบ "${tpl.name}" แล้ว`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function handleGenerateReport() {
    if (!selectedTemplateId) {
      toast.error("กรุณาเลือกแม่แบบรายงานก่อน");
      return;
    }
    try {
      const startRes = await reportStudioApi<{ ok: boolean; job_id: string; job: ReportJobState }>("/generate", {
        method: "POST",
        body: {
          task_id: Number(taskId) || 0,
          template_id: selectedTemplateId,
          model: modelAlias,
          extra_notes: extraNotes.trim(),
          wait: false,
        },
      });
      setActiveJob(startRes.job);
    } catch (e) {
      toast.error("เริ่มสร้างรายงานไม่สำเร็จ: " + (e as Error).message);
    }
  }

  // Poll active background report job
  React.useEffect(() => {
    if (!activeJob || activeJob.status === "completed" || activeJob.status === "failed") return;
    const timer = window.setInterval(async () => {
      try {
        const res = await reportStudioApi<{ ok: boolean; job: ReportJobState }>(
          `/job?job_id=${encodeURIComponent(activeJob.job_id)}`,
        );
        setActiveJob(res.job);
        if (res.job.status === "completed" && res.job.report) {
          toast.success("สร้างรายงานเชิงลึกครบทุกหัวข้อพร้อมดาวน์โหลดแล้ว");
          await loadAll();
          await selectReportVersion(res.job.report.id);
        } else if (res.job.status === "failed") {
          toast.error("สร้างรายงานไม่สำเร็จ: " + (res.job.error || res.job.stage));
        }
      } catch {
        /* retry next poll */
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [activeJob, loadAll]);

  async function copy() {
    if (!previewMarkdown) return;
    const ok = await copyText(previewMarkdown);
    if (ok) {
      setCopied(true);
      toast.success("คัดลอกเนื้อหา Markdown แล้ว");
      setTimeout(() => setCopied(false), 1500);
    } else {
      toast.error("คัดลอกไม่สำเร็จ");
    }
  }

  const activeMeta = generatedReports.find((r) => r.id === selectedReportId) ?? null;
  const isGenerating = activeJob !== null && (activeJob.status === "queued" || activeJob.status === "running");
  const progressPct =
    activeJob && activeJob.total_sections > 0
      ? Math.min(100, Math.round((activeJob.completed_sections / activeJob.total_sections) * 100))
      : 10;

  return (
    <div className="flex flex-col gap-4">
      {/* Card 1: Template Library (Upload .docx / .md + Extracted Blueprints) */}
      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 pb-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-sm">
              <FileTextIcon className="size-4" /> Report Templates & Completeness Blueprint
            </CardTitle>
            <p className="mt-1 text-muted-foreground text-xs">
              อัปโหลดไฟล์แม่แบบ Word (.docx) หรือ Markdown (.md) ของคุณเอง ระบบจะสกัดหัวข้อ หัวข้อย่อย และตารางทั้งหมดเพื่อบังคับให้โมเดลเติมข้อมูลจนครบ 100%
            </p>
          </div>
          <div className="flex items-center gap-2">
            <input
              ref={tplInputRef}
              type="file"
              accept=".docx,.md,.markdown"
              className="hidden"
              onChange={(e) => {
                const picked = Array.from(e.target.files ?? []);
                e.target.value = "";
                if (picked.length > 0) void handleUploadTemplate(picked);
              }}
            />
            <Button
              size="sm"
              variant="outline"
              disabled={uploadingTpl}
              onClick={() => tplInputRef.current?.click()}
            >
              {uploadingTpl ? <Loader2Icon className="size-3.5 animate-spin" /> : <UploadIcon className="size-3.5" />}
              Upload Template (.docx / .md)
            </Button>
          </div>
        </CardHeader>
        <CardContent className="grid gap-2">
          {templates.map((tpl) => {
            const isSelected = selectedTemplateId === tpl.id;
            const isExpanded = expandedTemplateId === tpl.id;
            return (
              <div
                key={tpl.id}
                className={cn(
                  "rounded-lg border p-3 transition-colors",
                  isSelected ? "border-foreground bg-muted/50" : "border-border bg-card/50 hover:border-foreground/40",
                )}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <button
                    type="button"
                    className="flex min-w-0 flex-1 items-center gap-2 text-left"
                    onClick={() => setSelectedTemplateId(tpl.id)}
                  >
                    <span
                      className={cn(
                        "flex size-4 shrink-0 items-center justify-center rounded-full border",
                        isSelected ? "border-foreground bg-foreground text-background" : "border-muted-foreground/40",
                      )}
                    >
                      {isSelected && <CheckIcon className="size-2.5" />}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="truncate font-medium text-sm">{tpl.name}</span>
                        <Badge variant="outline" className="font-mono text-[10px] uppercase">
                          .{tpl.format}
                        </Badge>
                        {tpl.is_default && (
                          <Badge className="bg-foreground text-background text-[10px] hover:bg-foreground">
                            Default
                          </Badge>
                        )}
                      </div>
                      <p className="mt-0.5 truncate text-muted-foreground text-xs">{tpl.description}</p>
                    </div>
                  </button>

                  <div className="flex shrink-0 items-center gap-1.5">
                    <span className="font-mono text-[11px] text-muted-foreground">
                      {tpl.section_count} บท · {tpl.subsection_count} ข้อย่อย · {tpl.table_count} ตาราง
                    </span>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 px-2 text-xs"
                      onClick={() => setExpandedTemplateId(isExpanded ? null : tpl.id)}
                    >
                      {isExpanded ? <ChevronDownIcon className="size-3.5" /> : <ChevronRightIcon className="size-3.5" />}
                      โครงสร้าง
                    </Button>
                    {!tpl.is_default && (
                      <Button
                        size="icon"
                        variant="ghost"
                        className="size-7"
                        title="ตั้งเป็นค่าเริ่มต้น"
                        onClick={() => void handleSetDefault(tpl.id)}
                      >
                        <StarIcon className="size-3.5" />
                      </Button>
                    )}
                    {!tpl.builtin && (
                      <Button
                        size="icon"
                        variant="ghost"
                        className="size-7 text-muted-foreground hover:text-foreground"
                        title="ลบแม่แบบ"
                        onClick={() => void handleDeleteTemplate(tpl)}
                      >
                        <Trash2Icon className="size-3.5" />
                      </Button>
                    )}
                  </div>
                </div>

                {isExpanded && (
                  <div className="mt-2.5 grid gap-1.5 border-t pt-2.5 text-xs">
                    {tpl.sections.map((sec) => (
                      <div key={sec.id} className="rounded-md bg-muted/40 px-2.5 py-2">
                        <div className="font-medium text-foreground">{sec.title}</div>
                        {sec.subsections.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] text-muted-foreground">
                            {sec.subsections.map((sub) => (
                              <span key={sub} className="rounded border bg-background px-1.5 py-0.5">
                                {sub}
                              </span>
                            ))}
                          </div>
                        )}
                        {sec.table_headers.length > 0 && (
                          <div className="mt-1 font-mono text-[11px] text-muted-foreground">
                            ตารางบังคับ:{" "}
                            {sec.table_headers.map((cols, idx) => `[${idx + 1}] ${cols.join(" | ")}`).join(" · ")}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </CardContent>
      </Card>

      {/* Card 2: Generate Detailed Report Controls */}
      <Card>
        <CardContent className="flex flex-col gap-3 pt-4">
          <div className="flex flex-wrap items-center gap-2">
            <Select value={modelAlias} onValueChange={setModelAlias} disabled={isGenerating}>
              <SelectTrigger className="w-48 text-xs">
                <SelectValue placeholder="Model" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="cyber-model">Cyber-Model (:8091 · Primary)</SelectItem>
                <SelectItem value="orchestrator">Orchestrator (:8090 · Secondary)</SelectItem>
              </SelectContent>
            </Select>
            <Input
              value={extraNotes}
              onChange={(e) => setExtraNotes(e.target.value)}
              disabled={isGenerating}
              placeholder="คำสั่งเน้นเพิ่มเติม (เช่น เน้นอธิบายสคริปต์ทีละไฟล์ + ตาราง IOC + วิธีแก้โค้ด)..."
              className="min-w-[220px] flex-1 text-xs"
            />
            <Button
              size="sm"
              disabled={isGenerating || !selectedTemplateId}
              onClick={() => void handleGenerateReport()}
            >
              {isGenerating ? (
                <Loader2Icon className="size-3.5 animate-spin" />
              ) : (
                <SparklesIcon className="size-3.5" />
              )}
              {isGenerating ? "กำลังเขียนและตรวจความครบถ้วน..." : "Generate Detailed Report"}
            </Button>
          </div>

          {activeJob && (
            <div className="rounded-lg border bg-muted/40 p-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 font-medium text-foreground">
                  {activeJob.status === "completed" ? (
                    <CheckCircle2Icon className="size-3.5" />
                  ) : activeJob.status === "failed" ? null : (
                    <Loader2Icon className="size-3.5 animate-spin" />
                  )}
                  {activeJob.stage}
                </span>
                {activeJob.total_sections > 0 && (
                  <span className="font-mono text-muted-foreground">
                    {activeJob.completed_sections} / {activeJob.total_sections} บท ({progressPct}%)
                  </span>
                )}
              </div>
              {isGenerating && (
                <>
                  <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full bg-foreground transition-all duration-500"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                  <p className="mt-1.5 text-[11px] text-muted-foreground">
                    งานกำลังประมวลผลเบื้องหลังบน Backend — สามารถสลับแท็บหรือไปหน้าอื่นได้เลย เมื่อกลับมาจะเห็นความคืบหน้าและไฟล์ดาวน์โหลดต่อเนื่องโดยไม่เริ่มใหม่
                  </p>
                </>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Card 2.5: Interactive Dossier — Expandable CVE, Finding, Asset/Path, Evidence & Reproduce Explorer */}
      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 pb-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-sm">
              <ShieldCheckIcon className="size-4" /> Mission Intelligence & Evidence Explorer (CVE · CWE · Asset/Path · PoC & Reproduce)
            </CardTitle>
            <p className="mt-1 text-muted-foreground text-xs">
              คลิกที่แต่ละแถวเพื่อกางดูคำอธิบายภาษาไทย, Asset และ Path ที่เกี่ยวข้อง, หลักฐานจริงจากเป้าหมาย, และขั้นตอนการตรวจสอบซ้ำ (Verify / Reproduce) ได้ครบในหน้าเดียว
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            disabled={refreshingMapping}
            onClick={() => void loadMapping(true)}
          >
            <RefreshCwIcon className={cn("size-3.5", refreshingMapping && "animate-spin")} />
            Re-Sync Dossier
          </Button>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 text-xs">
          {mappingData ? (
            <>
              {/* Executive Mission Summary Strip */}
              <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/20 p-2.5 font-mono">
                {mappingData.quality_gate && (
                  <Badge
                    className={cn(
                      "uppercase",
                      mappingData.quality_gate.gate_status === "ready"
                        ? "bg-foreground text-background"
                        : "border-foreground/50 text-foreground",
                    )}
                    variant={mappingData.quality_gate.gate_status === "ready" ? "default" : "outline"}
                    title={mappingData.quality_gate.exit_reason}
                  >
                    Gate: {mappingData.quality_gate.gate_status}
                  </Badge>
                )}
                {mappingData.asset_counts && (
                  <Badge variant="secondary">
                    Assets: {mappingData.asset_counts.total} ({mappingData.asset_counts.subdomains} sub · {mappingData.asset_counts.services} http)
                  </Badge>
                )}
                <Badge variant="secondary">Active Findings: {mappingData.active_finding_count}</Badge>
                <Badge
                  className={cn(mappingData.cve_count > 0 ? "bg-foreground text-background" : "")}
                  variant={mappingData.cve_count > 0 ? "default" : "outline"}
                >
                  CVEs: {mappingData.cve_count} ({mappingData.confirmed_cve_count ?? 0} confirmed · {mappingData.candidate_cve_count ?? 0} candidate)
                </Badge>
                {mappingData.kev_count > 0 && (
                  <Badge className="bg-foreground text-background">CISA KEV: {mappingData.kev_count}</Badge>
                )}
                <Badge variant="outline">CWEs: {mappingData.cwe_count}</Badge>
                <Badge variant="outline">OWASP: {mappingData.owasp_count}</Badge>
                <Badge variant="outline">MITRE ATT&CK: {mappingData.mitre_count}</Badge>
                {(mappingData.recon_facts?.length ?? 0) > 0 && (
                  <Badge variant="secondary">Recon Facts: {mappingData.recon_facts?.length}</Badge>
                )}
              </div>

              {/* Section A: Expandable CVE & Software Vulnerability Intelligence */}
              {mappingData.cve_intel.length > 0 && (
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-foreground">
                      1. รายการ CVE & ข้อมูลความเสี่ยงเชิงลึก (คลิกแถวเพื่อดู Asset, Path, หลักฐาน และวิธี Reproduce)
                    </span>
                    <span className="text-[11px] text-muted-foreground">
                      คลิกแถวใดก็ได้เพื่อกางรายละเอียด
                    </span>
                  </div>
                  <div className="divide-y rounded-md border">
                    {mappingData.cve_intel.map((c) => {
                      const isOpen = Boolean(expandedCves[c.cve]);
                      const aiText = aiSummaries[`cve:${c.cve}`];
                      const primaryAsset = c.affected_assets?.[0]?.label ?? c.matched_software?.[0] ?? "—";
                      const primaryPath = c.affected_paths?.[0] ?? "";
                      return (
                        <div key={c.cve} className="bg-card/40">
                          <button
                            type="button"
                            onClick={() => toggleExpand(setExpandedCves, c.cve)}
                            className="flex w-full flex-col gap-1.5 px-3 py-2.5 text-left transition-colors hover:bg-muted/40"
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="flex flex-wrap items-center gap-2">
                                {isOpen ? (
                                  <ChevronDownIcon className="size-4 shrink-0 text-foreground" />
                                ) : (
                                  <ChevronRightIcon className="size-4 shrink-0 text-muted-foreground" />
                                )}
                                <span className="font-mono font-semibold text-sm">{c.cve}</span>
                                <Badge
                                  variant={c.confirmation_status === "confirmed" ? "default" : "outline"}
                                  className={cn(
                                    "font-mono text-[10px] uppercase",
                                    c.confirmation_status === "confirmed" ? "bg-foreground text-background" : "",
                                  )}
                                >
                                  {c.confirmation_status === "confirmed" ? "Confirmed" : "Candidate (เทียบเวอร์ชัน)"}
                                </Badge>
                                {c.cvss != null && (
                                  <Badge variant="secondary" className="font-mono text-[10px]">
                                    CVSS {c.cvss} {c.cvss_severity || ""}
                                  </Badge>
                                )}
                                {c.epss_pct != null && (
                                  <Badge variant="outline" className="font-mono text-[10px]">
                                    EPSS {c.epss_pct}%
                                  </Badge>
                                )}
                                {c.in_cisa_kev && (
                                  <Badge className="bg-foreground text-background font-mono text-[10px]">
                                    CISA KEV
                                  </Badge>
                                )}
                                {c.cwe && (
                                  <Badge variant="outline" className="font-mono text-[10px]">
                                    {c.cwe}
                                  </Badge>
                                )}
                              </div>
                              <div className="flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
                                <span className="max-w-[260px] truncate" title={`${primaryAsset} ${primaryPath}`}>
                                  {primaryAsset}{primaryPath ? ` · ${primaryPath}` : ""}
                                </span>
                              </div>
                            </div>
                            <p className="pl-6 text-muted-foreground text-xs leading-relaxed line-clamp-2">
                              {aiText || c.thai_summary || c.summary || "คลิกเพื่อดูรายละเอียดช่องโหว่"}
                            </p>
                          </button>

                          {isOpen && (
                            <div className="grid gap-3 border-t bg-muted/20 px-4 py-3.5 lg:grid-cols-2">
                              {/* Box 1: What is it (Thai + NVD) */}
                              <div className="flex flex-col gap-2 rounded-md border bg-background p-3">
                                <div className="flex items-center justify-between gap-2">
                                  <span className="font-semibold text-foreground">Summary</span>
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    className="h-6 px-2 text-[11px]"
                                    disabled={summarizingKey === `cve:${c.cve}`}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      const ctx = [
                                        `CVE: ${c.cve} (CVSS: ${c.cvss ?? "N/A"} ${c.vector ?? ""}, CWE: ${c.cwe ?? "N/A"}, EPSS: ${c.epss_pct ?? "N/A"}%)`,
                                        `Status: ${c.verification_note || c.confirmation_status}`,
                                        `Matched Software: ${(c.matched_software ?? []).join(", ")}`,
                                        `Assets: ${(c.affected_assets ?? []).map((a) => a.label).join(", ")}`,
                                        `Paths: ${(c.affected_paths ?? []).join(", ")}`,
                                        `NVD Description: ${c.summary ?? ""}`,
                                        `Evidence: ${(c.source_refs ?? []).map((s) => s.excerpt).join("\n")}`,
                                      ].join("\n");
                                      void requestAiSummary("cve", c.cve, ctx);
                                    }}
                                  >
                                    {summarizingKey === `cve:${c.cve}` ? (
                                      <Loader2Icon className="size-3 animate-spin" />
                                    ) : (
                                      <SparklesIcon className="size-3" />
                                    )}
                                    สรุปด้วย Summarizer AI
                                  </Button>
                                </div>
                                <div className="whitespace-pre-wrap text-foreground leading-relaxed">
                                  {aiText || c.thai_summary || "—"}
                                </div>
                                {c.summary && (
                                  <div className="rounded border bg-muted/30 p-2 text-[11px] text-muted-foreground leading-relaxed">
                                    <span className="font-mono font-semibold text-foreground">NVD Official: </span>
                                    {c.summary}
                                  </div>
                                )}
                                <div className="flex flex-wrap gap-2 pt-1 font-mono text-[11px] text-muted-foreground">
                                  {c.vector && <span>Vector: {c.vector}</span>}
                                  {c.published && <span>· Published: {c.published}</span>}
                                  {c.risk_priority && <span>· {c.risk_priority}</span>}
                                </div>
                              </div>

                              {/* Box 2: Asset, Path & Status Note */}
                              <div className="flex flex-col gap-2 rounded-md border bg-background p-3">
                                <span className="font-semibold text-foreground">
                                  Information
                                </span>
                                {c.verification_note && (
                                  <div className="rounded border bg-muted/40 px-2.5 py-2 text-[11px] text-foreground leading-relaxed">
                                    <span className="font-semibold">สถานะการจับคู่: </span>
                                    {c.verification_note}
                                  </div>
                                )}
                                <div className="flex flex-col gap-1.5">
                                  <div>
                                    <span className="text-muted-foreground">Affected Assets: </span>
                                    {(c.affected_assets?.length ?? 0) > 0 ? (
                                      <span className="inline-flex flex-wrap gap-1">
                                        {c.affected_assets?.map((a) => (
                                          <Badge key={a.id} variant="secondary" className="font-mono text-[11px]">
                                            {a.label} (#{a.id} · {a.type})
                                          </Badge>
                                        ))}
                                      </span>
                                    ) : (
                                      <span className="text-muted-foreground">อ้างอิงจากระดับภารกิจ</span>
                                    )}
                                  </div>
                                  <div>
                                    <span className="text-muted-foreground">Observed Paths / Endpoints: </span>
                                    {(c.affected_paths?.length ?? 0) > 0 ? (
                                      <span className="inline-flex flex-wrap gap-1">
                                        {c.affected_paths?.map((p) => (
                                          <code key={p} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
                                            {p}
                                          </code>
                                        ))}
                                      </span>
                                    ) : (
                                      <span className="text-muted-foreground">—</span>
                                    )}
                                  </div>
                                  {(c.matched_software?.length ?? 0) > 0 && (
                                    <div>
                                      <span className="text-muted-foreground">Matched Software Banner: </span>
                                      <span className="font-mono font-medium">{c.matched_software?.join(", ")}</span>
                                    </div>
                                  )}
                                </div>
                              </div>

                              {/* Box 3: Raw Evidence from Recon/Finding */}
                              <div className="flex flex-col gap-2 rounded-md border bg-background p-3">
                                <span className="font-semibold text-foreground">
                                  Evidence
                                </span>
                                {(c.source_refs?.length ?? 0) > 0 ? (
                                  c.source_refs?.map((sr, i) => (
                                    <div key={`${sr.kind}-${sr.id ?? i}`} className="flex flex-col gap-1">
                                      <span className="font-mono text-[11px] font-medium text-muted-foreground">
                                        {sr.title}
                                      </span>
                                      <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded border bg-muted/40 p-2 font-mono text-[11px] leading-relaxed">
                                        {sr.excerpt}
                                      </pre>
                                    </div>
                                  ))
                                ) : (
                                  <span className="text-muted-foreground">ไม่มีข้อความหลักฐานแนบ</span>
                                )}
                              </div>

                              {/* Box 4: How to Verify / Reproduce */}
                              <div className="flex flex-col gap-2 rounded-md border bg-background p-3">
                                <div className="flex items-center justify-between gap-2">
                                  <span className="font-semibold text-foreground">
                                    Verification
                                  </span>
                                  {c.reproduce_steps && (
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      className="h-6 px-2 text-[11px]"
                                      onClick={() => {
                                        void copyText(c.reproduce_steps || "");
                                        toast.success("คัดลอกขั้นตอนตรวจสอบแล้ว");
                                      }}
                                    >
                                      <CopyIcon className="size-3" /> Copy
                                    </Button>
                                  )}
                                </div>
                                <pre className="max-h-44 overflow-auto whitespace-pre-wrap rounded border bg-muted/40 p-2.5 font-mono text-[11px] leading-relaxed">
                                  {c.reproduce_steps || "—"}
                                </pre>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Section B: Expandable Active Findings (Custom Logic / Config / Confirmed Vulns) */}
              <div className="flex flex-col gap-2">
                <span className="font-semibold text-foreground">
                  2. ช่องโหว่ที่ยืนยันแล้ว (Active Findings · คลิกแถวเพื่อดู Asset, Path, PoC Evidence และวิธี Reproduce)
                </span>
                {mappingData.findings.length === 0 ? (
                  <div className="rounded-md border border-dashed py-5 text-center text-muted-foreground">
                    ยังไม่มี Active Finding ที่ยืนยันแล้วในภารกิจนี้ (หากเป็น Candidate CVE จากเลขเวอร์ชันสามารถคลิกดูหลักฐานและวิธีตรวจสอบได้จากตารางที่ 1 ด้านบน หรือดูผลการสำรวจรายซับโดเมนในตารางที่ 3 ด้านล่าง)
                  </div>
                ) : (
                  <div className="divide-y rounded-md border">
                    {mappingData.findings.map((fm, idx) => {
                      const fKey = String(fm.finding_id ?? idx);
                      const isOpen = Boolean(expandedFindings[fKey]);
                      const aiText = aiSummaries[`finding:${fKey}`];
                      const primaryAsset = fm.affected_assets?.[0]?.label ?? "—";
                      const primaryPath = fm.affected_paths?.[0] ?? "";
                      return (
                        <div key={fKey} className="bg-card/40">
                          <button
                            type="button"
                            onClick={() => toggleExpand(setExpandedFindings, fKey)}
                            className="flex w-full flex-col gap-1 px-3 py-2.5 text-left transition-colors hover:bg-muted/40"
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="flex flex-wrap items-center gap-2">
                                {isOpen ? (
                                  <ChevronDownIcon className="size-4 shrink-0 text-foreground" />
                                ) : (
                                  <ChevronRightIcon className="size-4 shrink-0 text-muted-foreground" />
                                )}
                                <Badge className="bg-foreground text-background font-mono text-[10px] uppercase">
                                  {fm.severity}
                                </Badge>
                                <span className="font-medium text-sm">{fm.title}</span>
                                {fm.cves.length > 0 ? (
                                  <Badge variant="default" className="font-mono text-[10px]">
                                    {fm.cves.join(", ")}
                                  </Badge>
                                ) : (
                                  <Badge variant="outline" className="font-mono text-[10px]">
                                    {fm.cwes.join(", ")}
                                  </Badge>
                                )}
                                <span className="text-[11px] text-muted-foreground">{fm.owasp}</span>
                              </div>
                              <span className="max-w-[260px] truncate font-mono text-[11px] text-muted-foreground">
                                {primaryAsset}{primaryPath ? ` · ${primaryPath}` : ""}
                              </span>
                            </div>
                          </button>

                          {isOpen && (
                            <div className="grid gap-3 border-t bg-muted/20 px-4 py-3.5 lg:grid-cols-2">
                              <div className="flex flex-col gap-2 rounded-md border bg-background p-3">
                                <div className="flex items-center justify-between gap-2">
                                  <span className="font-semibold text-foreground">Summary</span>
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    className="h-6 px-2 text-[11px]"
                                    disabled={summarizingKey === `finding:${fKey}`}
                                    onClick={() => {
                                      const ctx = [
                                        `Title: ${fm.title} (${fm.severity})`,
                                        `Class: ${fm.vulnclass} | CWE: ${fm.cwes.join(", ")} | OWASP: ${fm.owasp}`,
                                        `Assets: ${(fm.affected_assets ?? []).map((a) => a.label).join(", ")}`,
                                        `Paths: ${(fm.affected_paths ?? []).join(", ")}`,
                                        `Summary: ${fm.summary ?? ""}`,
                                        `Evidence: ${fm.evidence_excerpt ?? ""}`,
                                      ].join("\n");
                                      void requestAiSummary("finding", fKey, ctx);
                                    }}
                                  >
                                    {summarizingKey === `finding:${fKey}` ? (
                                      <Loader2Icon className="size-3 animate-spin" />
                                    ) : (
                                      <SparklesIcon className="size-3" />
                                    )}
                                    สรุปด้วย Summarizer AI
                                  </Button>
                                </div>
                                <p className="whitespace-pre-wrap leading-relaxed">
                                  {aiText || fm.summary || fm.title}
                                </p>
                                <div className="flex flex-wrap gap-1.5 pt-1 font-mono text-[11px]">
                                  <Badge variant="outline">CVE: {fm.cves.length > 0 ? fm.cves.join(", ") : "N/A (Logic/Config)"}</Badge>
                                  <Badge variant="outline">{fm.cwes.join(", ")}</Badge>
                                  <Badge variant="secondary">{fm.mitre_attack.join(", ")}</Badge>
                                </div>
                              </div>

                              <div className="flex flex-col gap-2 rounded-md border bg-background p-3">
                                <span className="font-semibold text-foreground">Information</span>
                                <div>
                                  <span className="text-muted-foreground">Assets: </span>
                                  {(fm.affected_assets?.length ?? 0) > 0 ? (
                                    <span className="inline-flex flex-wrap gap-1">
                                      {fm.affected_assets?.map((a) => (
                                        <Badge key={a.id} variant="secondary" className="font-mono text-[11px]">
                                          {a.label} (#{a.id})
                                        </Badge>
                                      ))}
                                    </span>
                                  ) : (
                                    <span>—</span>
                                  )}
                                </div>
                                <div>
                                  <span className="text-muted-foreground">Paths / URLs: </span>
                                  {(fm.affected_paths?.length ?? 0) > 0 ? (
                                    <span className="inline-flex flex-wrap gap-1">
                                      {fm.affected_paths?.map((p) => (
                                        <code key={p} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
                                          {p}
                                        </code>
                                      ))}
                                    </span>
                                  ) : (
                                    <span>—</span>
                                  )}
                                </div>
                                {fm.fix_group_subject && (
                                  <div>
                                    <span className="text-muted-foreground">Root-Cause FixGroup: </span>
                                    <span className="font-mono">{fm.fix_group_subject}</span>
                                  </div>
                                )}
                              </div>

                              <div className="flex flex-col gap-2 rounded-md border bg-background p-3">
                                <span className="font-semibold text-foreground">Evidence</span>
                                <pre className="max-h-44 overflow-auto whitespace-pre-wrap rounded border bg-muted/40 p-2 font-mono text-[11px] leading-relaxed">
                                  {fm.evidence_excerpt || "—"}
                                </pre>
                                {fm.http_traffic_excerpt && (
                                  <pre className="max-h-36 overflow-auto whitespace-pre-wrap rounded border bg-muted/40 p-2 font-mono text-[11px]">
                                    {fm.http_traffic_excerpt}
                                  </pre>
                                )}
                              </div>

                              <div className="flex flex-col gap-2 rounded-md border bg-background p-3">
                                <span className="font-semibold text-foreground">Verification</span>
                                <pre className="max-h-44 overflow-auto whitespace-pre-wrap rounded border bg-muted/40 p-2.5 font-mono text-[11px] leading-relaxed">
                                  {fm.reproduce_steps || "—"}
                                </pre>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Section C: Expandable Technical Recon Facts & Attack Surface Dossier */}
              {(mappingData.recon_facts?.length ?? 0) > 0 && (
                <div className="flex flex-col gap-2">
                  <span className="font-semibold text-foreground">
                    3. บันทึกข้อเท็จจริงจากการสำรวจระบบ (Technical Recon Facts · คลิกเพื่อกางดูหลักฐานรายซับโดเมน/Path)
                  </span>
                  <div className="divide-y rounded-md border">
                    {mappingData.recon_facts?.map((rf, idx) => {
                      const rKey = String(rf.id ?? idx);
                      const isOpen = Boolean(expandedFacts[rKey]);
                      return (
                        <div key={rKey} className="bg-card/30">
                          <button
                            type="button"
                            onClick={() => toggleExpand(setExpandedFacts, rKey)}
                            className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left transition-colors hover:bg-muted/40"
                          >
                            <div className="flex min-w-0 items-center gap-2">
                              {isOpen ? (
                                <ChevronDownIcon className="size-4 shrink-0 text-foreground" />
                              ) : (
                                <ChevronRightIcon className="size-4 shrink-0 text-muted-foreground" />
                              )}
                              <Badge variant="outline" className="shrink-0 font-mono text-[10px]">
                                Fact #{rf.id}
                              </Badge>
                              <span className="truncate font-medium">{rf.headline}</span>
                            </div>
                            <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                              {rf.assets.length > 0 ? `${rf.assets.length} assets` : ""}{rf.paths.length > 0 ? ` · ${rf.paths.length} paths` : ""}
                            </span>
                          </button>
                          {isOpen && (
                            <div className="flex flex-col gap-2 border-t bg-muted/20 px-4 py-3">
                              {(rf.assets.length > 0 || rf.paths.length > 0) && (
                                <div className="flex flex-wrap items-center gap-1.5">
                                  {rf.assets.map((a) => (
                                    <Badge key={a.id} variant="secondary" className="font-mono text-[10px]">
                                      {a.label} (#{a.id})
                                    </Badge>
                                  ))}
                                  {rf.paths.map((p) => (
                                    <code key={p} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
                                      {p}
                                    </code>
                                  ))}
                                </div>
                              )}
                              <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded border bg-background p-3 font-mono text-[11px] leading-relaxed">
                                {rf.detail}
                              </pre>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="py-4 text-center text-muted-foreground">กำลังดึงข้อมูลภารกิจและหลักฐานการจับคู่...</div>
          )}
        </CardContent>
      </Card>

      {/* Card 3: Preview & 1-Click Download (.docx / .md) */}
      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <FileTextIcon className="size-4" /> Generated Report Preview & Download
            </CardTitle>
            {generatedReports.length > 0 && (
              <Select value={selectedReportId} onValueChange={(v) => void selectReportVersion(v)}>
                <SelectTrigger className="h-8 w-64 text-xs">
                  <SelectValue placeholder="เลือกเวอร์ชันรายงาน" />
                </SelectTrigger>
                <SelectContent>
                  {generatedReports.map((r) => (
                    <SelectItem key={r.id} value={r.id}>
                      {r.template_name.slice(0, 32)} · {new Date(r.created_at).toLocaleString("th-TH")}
                    </SelectItem>
                  ))}
                  {legacyReport && <SelectItem value="__legacy__">ARTEX Auto Summary (Legacy)</SelectItem>}
                </SelectContent>
              </Select>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {activeMeta && (
              <>
                <Button
                  size="sm"
                  onClick={() => window.open(activeMeta.download_docx_url, "_blank")}
                >
                  <DownloadIcon className="size-3.5" />
                  Download .docx {activeMeta.stats?.docx_size_bytes ? `(${fmtKb(activeMeta.stats.docx_size_bytes)})` : ""}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => window.open(activeMeta.download_md_url, "_blank")}
                >
                  <DownloadIcon className="size-3.5" />
                  Download .md
                </Button>
              </>
            )}
            {previewMarkdown && (
              <Button size="sm" variant="outline" onClick={() => void copy()}>
                {copied ? <CheckIcon className="size-3.5" /> : <CopyIcon className="size-3.5" />}
                Copy
              </Button>
            )}
          </div>
        </CardHeader>

        <CardContent className="flex flex-col gap-3">
          {activeMeta?.stats && (
            <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted-foreground">
              <Badge variant="secondary" className="font-mono text-[11px]">
                {activeMeta.stats.sections} หัวข้อหลัก
              </Badge>
              <Badge variant="secondary" className="font-mono text-[11px]">
                {activeMeta.stats.subsections} หัวข้อย่อย
              </Badge>
              <Badge variant="secondary" className="font-mono text-[11px]">
                {activeMeta.stats.tables} ตารางข้อมูล
              </Badge>
              <Badge variant="outline" className="font-mono text-[11px]">
                {activeMeta.stats.chars.toLocaleString()} ตัวอักษร
              </Badge>
              {activeMeta.stats.gate_repairs > 0 && (
                <Badge variant="outline" className="font-mono text-[11px]">
                  Completeness Gate Expanded {activeMeta.stats.gate_repairs}x
                </Badge>
              )}
            </div>
          )}

          {loading ? (
            <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed py-16 text-muted-foreground text-sm">
              <Loader2Icon className="size-7 animate-spin opacity-50" />
              กำลังโหลดข้อมูลรายงาน...
            </div>
          ) : previewMarkdown ? (
            <div className="max-h-[65vh] overflow-auto rounded-md border bg-muted/20 p-5">
              <Markdown text={previewMarkdown} />
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed py-16 text-muted-foreground text-sm">
              <FileTextIcon className="size-8 opacity-40" />
              <span>ยังไม่มีรายงานสำหรับ Task #{taskId} — เลือกแม่แบบด้านบนแล้วกด Generate Detailed Report ได้เลย</span>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
