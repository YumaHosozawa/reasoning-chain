const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Direction = "positive" | "negative" | "mixed";
export type Intensity = "high" | "medium" | "low";
export type TimeHorizon = "immediate" | "1-4w" | "1-3m" | "3-12m";

export interface ImpactNode {
  level: number;
  sector: string;
  description: string;
  direction: Direction;
  intensity: Intensity;
  rationale: string;
  example_companies: string[];
  keywords: string[];
  // 定量予測フィールド (旧データでは null)
  expected_return_pct_low?: number | null;
  expected_return_pct_high?: number | null;
  time_horizon?: TimeHorizon | null;
  probability?: number | null;
}

export interface CompanyMatch {
  company_code: string;
  company_name: string;
  impact_level: number;
  direction: Direction;
  final_score: number;
  vector_similarity: number;
  llm_relevance_score: number;
  segment_exposure_ratio: number;
  affected_segments: string[];
  rationale: string;
  intensity: Intensity;
  expected_return_pct?: number | null;
  time_horizon?: TimeHorizon | null;
  prediction_window_days?: number | null;
  probability?: number | null;
  company_context?: string | null;
}

export interface ReliabilityBin {
  bin_lower: number;
  bin_upper: number;
  mean_predicted: number | null;
  realized_frequency: number | null;
  count: number;
}

export interface HorizonMAE {
  time_horizon: string;
  mae_return: number;
  count: number;
}

export interface LevelMAE {
  impact_level: number;
  mae_return: number;
  brier_score: number | null;
  coverage_rate: number | null;
  count: number;
}

export interface HorizonLevelCross {
  time_horizon: string;
  impact_level: number;
  mae_return: number;
  count: number;
}

export interface CalibrationSummary {
  validated_count: number;
  pending_count: number;
  overall_coverage_rate: number | null;
  overall_mae_return: number | null;
  rolling_brier: number | null;
  reliability_bins: ReliabilityBin[];
  mae_by_horizon: HorizonMAE[];
  mae_by_level: LevelMAE[];
  horizon_level_cross: HorizonLevelCross[];
}

export interface SweepResponse {
  validated_ids: string[];
  count: number;
  swept_at: string;
}

export interface AnalyzeResponse {
  id: string;
  event_summary: string;
  event_type: string;
  confidence: number;
  generated_at: string;
  impacts: ImpactNode[];
  matches: CompanyMatch[];
  total_impacts: number;
  total_matches: number;
  db_ready: boolean;
}

export interface ResultSummary {
  id: string;
  event_text: string;
  event_summary: string;
  event_type: string;
  confidence: number;
  total_impacts: number;
  total_matches: number;
  created_at: string;
}

export interface ResultDetail extends ResultSummary {
  chain_json: Record<string, unknown>;
  matches_json: CompanyMatch[];
}

export interface ResultListResponse {
  total: number;
  results: ResultSummary[];
}

export async function analyze(params: {
  event: string;
  max_levels?: number;
  top_n?: number;
  score_threshold?: number;
  chain_only?: boolean;
  strategy?: string;
}): Promise<AnalyzeResponse> {
  const res = await fetch(`${BASE}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "分析エラー");
  }
  return res.json();
}

export async function fetchResults(skip = 0, limit = 50): Promise<ResultListResponse> {
  const res = await fetch(`${BASE}/api/results?skip=${skip}&limit=${limit}`);
  if (!res.ok) throw new Error("結果一覧の取得に失敗しました");
  return res.json();
}

export async function fetchResult(id: string): Promise<ResultDetail> {
  const res = await fetch(`${BASE}/api/results/${id}`);
  if (!res.ok) throw new Error("結果の取得に失敗しました");
  return res.json();
}

export async function downloadMarkdown(id: string): Promise<void> {
  const res = await fetch(`${BASE}/api/results/${id}/export/markdown`);
  if (!res.ok) throw new Error("Markdownの生成に失敗しました");

  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = disposition.match(/filename\*=UTF-8''(.+)/);
  const filename = match ? decodeURIComponent(match[1]) : "reasoning_chain.md";

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function fetchExportData(id: string): Promise<ResultDetail> {
  const res = await fetch(`${BASE}/api/results/${id}/export/data`);
  if (!res.ok) throw new Error("エクスポートデータの取得に失敗しました");
  return res.json();
}

export async function fetchCalibrationSummary(
  lastN = 100,
  horizon?: string,
): Promise<CalibrationSummary> {
  const params = new URLSearchParams({ last_n: String(lastN) });
  if (horizon) params.set("horizon", horizon);
  const res = await fetch(`${BASE}/api/validation/summary?${params.toString()}`);
  if (!res.ok) throw new Error("キャリブレーション集計の取得に失敗しました");
  return res.json();
}

export async function runValidationSweep(limit?: number): Promise<SweepResponse> {
  const params = new URLSearchParams();
  if (limit !== undefined) params.set("limit", String(limit));
  const url = `${BASE}/api/validation/run${params.toString() ? "?" + params.toString() : ""}`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) throw new Error("検証の実行に失敗しました");
  return res.json();
}
