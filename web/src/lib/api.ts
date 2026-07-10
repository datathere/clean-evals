// Strict TypeScript mirror of the FastAPI Pydantic schemas (web/schemas.py).

export interface Dataset {
  id: number;
  name: string;
  version: string;
  description: string | null;
  scorer: string;
  case_count: number;
  locked_count: number;
  has_runs: boolean;
  scorer_config: Record<string, unknown>;
  request_shape: "raw" | "templated" | "chat";
  system_prompt: string | null;
  shared_context: string | null;
  user_template: string | null;
  locked_at: string | null;
  created_at: string;
}

export interface RequestPreview {
  case_id_external: string;
  system: string | null;
  user: string;
  history: { role: string; content: string }[] | null;
}

export interface GenerationStatus {
  status: "idle" | "running" | "done" | "error" | "aborted_cost";
  total: number;
  done: number;
  errors: number;
  cost_usd: number;
  detail: string | null;
  candidate_count: number;
}

export interface Candidate {
  id: number;
  case_id: number;
  case_id_external: string;
  model: string;
  content: string;
  parsed: Record<string, unknown> | null;
  status: string;
  error: string | null;
  latency_ms: number | null;
  cost_usd: number | null;
  rating: number | null;
  feedback: string | null;
}

export interface ModelCapabilities {
  supports_temperature: boolean;
  supports_seed: boolean;
  reasoning_efforts: string[];
  supports_max_output_tokens: boolean;
}

export interface CatalogModel {
  id: string;
  input_per_mtok: number | null;
  output_per_mtok: number | null;
  overridden: boolean;
  listed: boolean;
  excluded: boolean;
  description: string | null;
  context_length: number | null;
  capabilities: ModelCapabilities;
}

export interface ModelParams {
  temperature?: number;
  reasoning_effort?: "low" | "medium" | "high";
  max_output_tokens?: number;
}

export interface ModelPick {
  model: string;
  tier: string;
  reason: string;
}

export interface PriceProposal {
  provider: string;
  model: string;
  current_input: number | null;
  current_output: number | null;
  new_input: number;
  new_output: number;
  source: string;
}

export interface Provider {
  provider: string;
  env_var: string;
  status: "connected" | "invalid_key" | "unreachable" | "not_configured";
  connected: boolean;
  models: CatalogModel[];
}

export interface JudgeConfig {
  id: number;
  dataset_id: number;
  version: number;
  judge_model: string;
  agreement: {
    summary: { n: number; exact: number; within_one: number; kappa: number };
    rows: { case_id: string; model: string; human: number; judge: number; reason: string }[];
  };
  created_at: string;
}

export interface Case {
  id: number;
  case_id_external: string;
  input: Record<string, unknown>;
  expected: Record<string, unknown> | null;
  tags: string[];
  locked: boolean;
  rev: number;
}

export interface RunSummaryRow {
  model: string;
  cases_run: number;
  cases_passed: number;
  score_mean: number;
  score_p50: number;
  latency_p95_ms: number;
  error_rate: number;
  total_cost_usd: number;
  cost_per_correct_usd: number | null;
  pricing_version: string;
}

export interface Run {
  id: string;
  dataset: string;
  dataset_id: number;
  dataset_version: string;
  config: Record<string, unknown>;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  summary: Record<string, RunSummaryRow>;
  artifact_uri: string | null;
  pricing_version: string;
  triggered_by: string;
  created_at: string;
}

export interface CaseResult {
  case_id: string;
  model: string;
  status: string;
  score: number | null;
  passed: boolean | null;
  latency_ms: number | null;
  cost_usd: number | null;
  error: string | null;
  started_at: string;
  finished_at: string;
  input: Record<string, unknown> | null;
  expected: Record<string, unknown> | null;
  response: { content?: string; parsed?: Record<string, unknown> | null } | null;
}

export interface Recommendation {
  kind: "max_accuracy" | "price_performance" | "lowest_cost";
  model: string | null;
  rationale: string;
  summary: RunSummaryRow | null;
}

export interface Schedule {
  id: number;
  dataset_id: number;
  cron: string;
  enabled: boolean;
  config: Record<string, unknown>;
  last_run_at: string | null;
  next_run_at: string | null;
}

export interface CostProjectionRow {
  model: string;
  score_mean: number;
  qualifies: boolean;
  projected_monthly_usd: number;
}

export interface TelemetryExchange {
  id: number;
  interaction_id: string;
  source: string;
  dataset: string;
  kind: "structured" | "transcript";
  occurred_at: string;
  outcome: string | null;
  turn_index: number;
  context: { role: string; text: string }[];
  request_text: string;
  request_input: Record<string, unknown> | null;
  response_text: string;
  response_parsed: Record<string, unknown> | null;
  response_model: string;
  alternatives: { text: string; model: string | null }[];
  regen_count: number;
  label: string | null;
  verdict: "positive" | "negative" | "incomplete" | "unrated" | null;
  rating: number | null;
  feedback: string | null;
  proposed_expected: Record<string, unknown> | null;
  judge_score: number | null;
  status: "derived" | "promoted" | "discarded";
  promoted_case_id: number | null;
  auto_locked: boolean;
  spot_check: boolean;
  spot_check_resolved: "confirmed" | "overturned" | null;
}

export interface TelemetryInbox {
  total: number;
  exchanges: TelemetryExchange[];
}

export interface TelemetryIngestResult {
  accepted: number;
  duplicates: string[];
  rejected: { index: number; error: string }[];
  scrubber: string | null;
}

export interface TelemetrySeriesRow {
  date: string;
  source: string;
  model: string;
  exchanges: number;
  positive: number;
  negative: number;
  incomplete: number;
  unrated: number;
  acceptance_rate: number;
  correction_rate: number;
  mean_rating: number | null;
  mean_regens: number;
  judge_scored: number;
  mean_judge_score: number | null;
}

export interface TelemetrySourceRow {
  source: string;
  interactions: number;
  accept_rate: number;
  mean_turns_to_accept: number | null;
}

export interface TelemetryStats {
  days: number;
  series: TelemetrySeriesRow[];
  sources: TelemetrySourceRow[];
}

export interface AutolockState {
  enabled: boolean;
  checked: number;
  overturned: number;
  overturn_rate: number;
  disable_threshold: number;
  self_disabled: boolean;
}

export interface TelemetryDeriveResult {
  interactions: number;
  exchanges: number;
  auto_locked: number;
  classifier_cost_usd: number;
  skipped_budget: number;
  errors: number;
}

const API = "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API}${path}`, {
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${body}`);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

export const api = {
  listDatasets: () => request<Dataset[]>("/datasets"),
  getDataset: (id: number) => request<Dataset>(`/datasets/${id}`),
  listCases: (id: number) => request<Case[]>(`/datasets/${id}/cases`),
  editCase: (datasetId: number, caseId: number, expected: Record<string, unknown> | null, rev: number) =>
    request<Case>(`/datasets/${datasetId}/cases/${caseId}`, {
      method: "PATCH",
      body: JSON.stringify({ expected, rev }),
    }),
  lockCase: (datasetId: number, caseId: number) =>
    request<Case>(`/datasets/${datasetId}/cases/${caseId}/lock`, { method: "POST" }),

  listRuns: (datasetId?: number) =>
    request<Run[]>(`/runs${datasetId ? `?dataset_id=${datasetId}` : ""}`),
  getRun: (id: string) => request<Run>(`/runs/${id}`),
  getCaseResults: (id: string) => request<CaseResult[]>(`/runs/${id}/cases`),
  getRecommendations: (id: string, threshold = 0.8) =>
    request<Recommendation[]>(`/runs/${id}/recommendations?threshold=${threshold}`),
  costProjection: (id: string, callsPerMonth: number, scoreFloor: number) =>
    request<CostProjectionRow[]>(`/runs/${id}/cost-projection`, {
      method: "POST",
      body: JSON.stringify({ run_id: id, calls_per_month: callsPerMonth, score_floor: scoreFloor }),
    }),
  triggerRun: (datasetId: number, config: Record<string, unknown>, mode: "inline" | "queue" = "inline") =>
    request<{ mode: string; task_id: string | null }>("/runs", {
      method: "POST",
      body: JSON.stringify({ dataset_id: datasetId, config, mode }),
    }),
  inlineRunStatus: (datasetId: number) =>
    request<{ status: string; run_id: string | null; detail: string | null }>(
      `/runs/inline-status/${datasetId}`,
    ),
  getProviders: () => request<Provider[]>("/models"),
  setPrice: (provider: string, model: string, inputPerMtok: number, outputPerMtok: number) =>
    request<Provider[]>("/models/pricing", {
      method: "PUT",
      body: JSON.stringify({
        provider,
        model,
        input_per_mtok: inputPerMtok,
        output_per_mtok: outputPerMtok,
      }),
    }),
  removePrice: (provider: string, model: string) =>
    request<Provider[]>(
      `/models/pricing?provider=${encodeURIComponent(provider)}&model=${encodeURIComponent(model)}`,
      { method: "DELETE" },
    ),
  refreshPrices: () => request<PriceProposal[]>("/models/pricing/refresh", { method: "POST" }),
  setExcluded: (provider: string, model: string, excluded: boolean) =>
    request<Provider[]>("/models/excluded", {
      method: "PUT",
      body: JSON.stringify({ provider, model, excluded }),
    }),
  applyPrices: (items: PriceProposal[]) =>
    request<Provider[]>("/models/pricing/apply", {
      method: "POST",
      body: JSON.stringify({
        items: items.map((p) => ({
          provider: p.provider,
          model: p.model,
          input_per_mtok: p.new_input,
          output_per_mtok: p.new_output,
        })),
      }),
    }),

  listSchedules: () => request<Schedule[]>("/schedules"),
  createSchedule: (body: Omit<Schedule, "id" | "last_run_at" | "next_run_at">) =>
    request<Schedule>("/schedules", { method: "POST", body: JSON.stringify(body) }),
  updateSchedule: (id: number, body: Omit<Schedule, "id" | "last_run_at" | "next_run_at">) =>
    request<Schedule>(`/schedules/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteSchedule: (id: number) =>
    request<void>(`/schedules/${id}`, { method: "DELETE" }),

  uploadInputs: async (
    name: string,
    version: string,
    scorer: string,
    file: File,
    spec?: {
      request_shape: "raw" | "templated";
      system_prompt?: string;
      shared_context?: string;
      user_template?: string;
    },
  ): Promise<{ dataset_id: number; case_count: number }> => {
    const fd = new FormData();
    fd.append("name", name);
    fd.append("version", version);
    fd.append("scorer", scorer);
    fd.append("file", file);
    if (spec) {
      fd.append("request_shape", spec.request_shape);
      if (spec.system_prompt) fd.append("system_prompt", spec.system_prompt);
      if (spec.shared_context) fd.append("shared_context", spec.shared_context);
      if (spec.user_template) fd.append("user_template", spec.user_template);
    }
    const resp = await fetch(`${API}/builder/upload`, { method: "POST", body: fd });
    if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
    return resp.json();
  },

  previewRequest: (datasetId: number) =>
    request<RequestPreview>(`/datasets/${datasetId}/preview-request`),
  startGeneration: (
    datasetId: number,
    models: string[],
    maxCostUsd: number,
    modelParams: Record<string, ModelParams> = {},
  ) =>
    request<GenerationStatus>(`/datasets/${datasetId}/candidates`, {
      method: "POST",
      body: JSON.stringify({ models, max_cost_usd: maxCostUsd, model_params: modelParams }),
    }),
  generationStatus: (datasetId: number) =>
    request<GenerationStatus>(`/datasets/${datasetId}/candidates/status`),
  listCandidates: (datasetId: number) =>
    request<Candidate[]>(`/datasets/${datasetId}/candidates`),
  rateCandidate: (datasetId: number, candidateId: number, rating: number, feedback: string | null) =>
    request<Candidate>(`/datasets/${datasetId}/candidates/${candidateId}/rating`, {
      method: "PUT",
      body: JSON.stringify({ rating, feedback }),
    }),
  editSettings: (
    datasetId: number,
    settings: {
      system_prompt?: string;
      shared_context?: string;
      user_template?: string;
      scorer_config?: Record<string, unknown>;
    },
  ) =>
    request<Dataset>(`/datasets/${datasetId}/settings`, {
      method: "PATCH",
      body: JSON.stringify(settings),
    }),
  unlockCase: (datasetId: number, caseId: number) =>
    request<Case>(`/datasets/${datasetId}/cases/${caseId}/unlock`, { method: "POST" }),
  newVersion: (datasetId: number) =>
    request<Dataset>(`/datasets/${datasetId}/versions`, { method: "POST" }),
  pickGolden: (datasetId: number, caseId: number, candidateId: number) =>
    request<Case>(`/datasets/${datasetId}/cases/${caseId}/golden`, {
      method: "POST",
      body: JSON.stringify({ candidate_id: candidateId }),
    }),
  calibrateJudge: (datasetId: number, judgeModel: string) =>
    request<JudgeConfig>(`/datasets/${datasetId}/judge/calibrate`, {
      method: "POST",
      body: JSON.stringify({ judge_model: judgeModel }),
    }),
  getJudgeConfig: (datasetId: number) =>
    request<JudgeConfig | null>(`/datasets/${datasetId}/judge`),
  suggestModels: (datasetId: number) =>
    request<{ picks: ModelPick[]; picked_by: string | null }>(
      `/datasets/${datasetId}/suggest-models`,
      { method: "POST" },
    ),

  telemetryInbox: (filters: { dataset?: string; source?: string; status?: string } = {}) => {
    const params = new URLSearchParams();
    if (filters.dataset) params.set("dataset", filters.dataset);
    if (filters.source) params.set("source", filters.source);
    if (filters.status) params.set("status", filters.status);
    const qs = params.toString();
    return request<TelemetryInbox>(`/telemetry/inbox${qs ? `?${qs}` : ""}`);
  },
  telemetrySpotChecks: () => request<TelemetryInbox>("/telemetry/spot-checks"),
  telemetryPromote: (exchangeId: number, lock: boolean) =>
    request<{ case_id: number; dataset_id: number }>(
      `/telemetry/exchanges/${exchangeId}/promote`,
      { method: "POST", body: JSON.stringify({ lock }) },
    ),
  telemetryDiscard: (exchangeId: number) =>
    request<void>(`/telemetry/exchanges/${exchangeId}/discard`, { method: "POST" }),
  telemetrySpotCheckResolve: (exchangeId: number, resolution: "confirmed" | "overturned") =>
    request<void>(`/telemetry/exchanges/${exchangeId}/spot-check`, {
      method: "POST",
      body: JSON.stringify({ resolution }),
    }),
  telemetryDerive: () => request<TelemetryDeriveResult>("/telemetry/derive", { method: "POST" }),
  telemetryStats: (days = 30) => request<TelemetryStats>(`/telemetry/stats?days=${days}`),
  telemetryAutolock: () => request<AutolockState>("/telemetry/autolock"),
  telemetryUpload: async (file: File): Promise<TelemetryIngestResult> => {
    const fd = new FormData();
    fd.append("file", file);
    const resp = await fetch(`${API}/telemetry/upload`, { method: "POST", body: fd });
    if (!resp.ok) {
      const body = await resp.text();
      throw new Error(`${resp.status} ${resp.statusText}: ${body}`);
    }
    return resp.json();
  },
};
