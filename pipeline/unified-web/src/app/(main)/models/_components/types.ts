export interface GGUFInfo {
  path: string;
  display_path?: string;
  name: string;
  exists: boolean;
  size_bytes: number;
  size_gib: number;
  kind: "model" | "mmproj" | "drafter";
  architecture: string;
  model_name: string;
  block_count: number | null;
  context_length: number | null;
  file_type: string | null;
  quant_label: string;
  expert_count: number | null;
  expert_used_count: number | null;
}

export interface EngineInfo {
  id: string;
  label: string;
  path: string;
  available: boolean;
  version: string;
}

export interface TimingEntry {
  tokens: number;
  tg_tok_s: number;
  pp_tok_s: number | null;
  e2e_tok_s?: number | null;
}

export interface SlotMemoryEstimate {
  weights_gib: number;
  mmproj_gib: number;
  draft_gib: number;
  kv_cache_gib: number;
  compute_gib: number;
  total_gib: number;
}

export interface SlotLiveInfo {
  status: "running" | "loading" | "stopped";
  pid: number | null;
  rss_gib: number;
  cpu_pct: number;
  uptime: string;
  running_cmd: string;
  timings: {
    last_tg_tok_s: number | null;
    last_pp_tok_s: number | null;
    last_e2e_tok_s?: number | null;
    last_draft_acc: number | null;
    history: TimingEntry[];
  };
  model_meta: GGUFInfo;
  memory_estimate: SlotMemoryEstimate;
  command_preview: string;
}

export interface SlotConfig {
  id: string;
  node_config_key?: string;
  label: string;
  role: string;
  port: number;
  alias: string;
  target_alias?: string;
  aliases: string[];
  log_file: string;
  enabled: boolean;
  binary: string;
  model_path: string;
  mmproj_enabled: boolean;
  mmproj_path: string;
  ctx_size: number;
  gpu_layers: number;
  kv_cache_type: "f16" | "q8_0" | "q4_0";
  speculative_mode: "auto" | "dspark" | "off";
  draft_model_path: string;
  draft_n_max: number;
  parallel_slots: number;
  batch_size: number;
  ubatch_size: number;
  threads: number;
  threads_batch: number;
  reasoning_effort: string;
  reasoning_preserve: boolean;
  reasoning_budget: number;
  ctx_checkpoints: number;
  context_shift: boolean;
  flash_attn: boolean;
  sandbox: boolean;
  n_predict: number;
  extra_args: string;
  presets: Record<string, Partial<SlotConfig>>;
  live: SlotLiveInfo;
}

export interface CloudModelInfo {
  id: string;
  enabled: boolean;
  label: string;
  alias: string;
  aliases: string[];
  api_base: string;
  api_key_env: string;
  target_model: string;
  supports_vision: boolean;
  sensitive_safe: boolean;
  has_key: boolean;
}

export interface ModelStudioState {
  ok: boolean;
  system: {
    total_ram_gib: number;
    active_rss_gib: number;
    active_estimated_gib: number;
  };
  engines: EngineInfo[];
  ggufs: GGUFInfo[];
  slots: SlotConfig[];
  cloud_models: CloudModelInfo[];
}

export function estimateClientMemory(draft: SlotConfig, ggufs: GGUFInfo[]): SlotMemoryEstimate {
  const modelMeta = ggufs.find((g) => g.path === draft.model_path || g.display_path === draft.model_path);
  const weights_gib = modelMeta?.size_gib ?? draft.live?.model_meta?.size_gib ?? 16;

  let mmproj_gib = 0;
  if (draft.mmproj_enabled && draft.mmproj_path) {
    const mm = ggufs.find((g) => g.path === draft.mmproj_path || g.display_path === draft.mmproj_path);
    mmproj_gib = mm?.size_gib ?? 0.65;
  }

  let draft_gib = 0;
  if (draft.speculative_mode === "dspark" && draft.draft_model_path) {
    const df = ggufs.find((g) => g.path === draft.draft_model_path || g.display_path === draft.draft_model_path);
    draft_gib = df?.size_gib ?? 0.45;
  }

  const ctx = Math.max(1024, Number(draft.ctx_size) || 32768);
  const slotsN = Math.max(1, Number(draft.parallel_slots) || 1);
  const kvType = (draft.kv_cache_type || "f16").toLowerCase();
  const dtypeMult = kvType === "f16" ? 1.0 : kvType === "q8_0" ? 0.55 : 0.3;

  const arch = (modelMeta?.architecture || draft.live?.model_meta?.architecture || "").toLowerCase();
  let kvBase64k = 6.0;
  if (arch.includes("inkling2")) {
    kvBase64k = 2.24;
  } else {
    const blocks = modelMeta?.block_count ?? draft.live?.model_meta?.block_count ?? 32;
    kvBase64k = Math.max(1.0, (blocks / 32.0) * 6.0);
  }

  const kv_cache_gib = Number((kvBase64k * (ctx / 65536.0) * slotsN * dtypeMult).toFixed(2));
  const compute_gib = Number((1.5 + (arch.includes("inkling2") ? 2.5 : 0.8) * Math.min(2.0, ctx / 65536.0)).toFixed(2));
  const total_gib = Number((weights_gib + mmproj_gib + draft_gib + kv_cache_gib + compute_gib).toFixed(2));

  return {
    weights_gib: Number(weights_gib.toFixed(2)),
    mmproj_gib: Number(mmproj_gib.toFixed(2)),
    draft_gib: Number(draft_gib.toFixed(2)),
    kv_cache_gib,
    compute_gib,
    total_gib,
  };
}

export async function studioApi<T = Record<string, unknown>>(
  path: string,
  options?: { method?: "GET" | "POST"; body?: unknown },
): Promise<T> {
  const res = await fetch(`/model-studio-api${path}`, {
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
    const errObj = data as { message?: string; error?: string };
    throw new Error(errObj.message || errObj.error || `HTTP ${res.status}`);
  }
  return data as T;
}
