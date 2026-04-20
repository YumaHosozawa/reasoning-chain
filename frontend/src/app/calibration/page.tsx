"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import ReliabilityDiagram from "@/components/ReliabilityDiagram";
import {
  fetchCalibrationSummary,
  runValidationSweep,
  type CalibrationSummary,
  type HorizonLevelCross,
} from "@/lib/api";

const HORIZON_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "全ホライズン" },
  { value: "immediate", label: "即時" },
  { value: "1-4w", label: "1–4週" },
  { value: "1-3m", label: "1–3ヶ月" },
  { value: "3-12m", label: "3–12ヶ月" },
];

const HORIZON_LABEL: Record<string, string> = {
  immediate: "即時",
  "1-4w": "1–4週",
  "1-3m": "1–3ヶ月",
  "3-12m": "3–12ヶ月",
};

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function fmtNum(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

export default function CalibrationPage() {
  const [summary, setSummary] = useState<CalibrationSummary | null>(null);
  const [horizon, setHorizon] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [sweeping, setSweeping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sweepMsg, setSweepMsg] = useState<string | null>(null);

  const load = async (h: string) => {
    setLoading(true);
    setError(null);
    try {
      const s = await fetchCalibrationSummary(100, h || undefined);
      setSummary(s);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "取得失敗");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(horizon);
  }, [horizon]);

  const handleSweep = async () => {
    setSweeping(true);
    setSweepMsg(null);
    try {
      const r = await runValidationSweep();
      setSweepMsg(`${r.count} 件を検証しました`);
      await load(horizon);
    } catch (e: unknown) {
      setSweepMsg(e instanceof Error ? e.message : "検証失敗");
    } finally {
      setSweeping(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <main className="max-w-5xl mx-auto px-6 py-8 space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <Link href="/" className="text-xs text-blue-600 hover:underline">
              ← 分析に戻る
            </Link>
            <h1 className="text-xl font-bold text-gray-900 mt-1">
              キャリブレーションダッシュボード
            </h1>
            <p className="text-sm text-gray-500 mt-0.5">
              実績リターンとの突合による予測精度の可視化
            </p>
          </div>

          <div className="flex items-center gap-2">
            <select
              value={horizon}
              onChange={(e) => setHorizon(e.target.value)}
              className="text-sm rounded-md border border-gray-300 px-3 py-1.5 bg-white"
            >
              {HORIZON_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <button
              onClick={handleSweep}
              disabled={sweeping}
              className="text-xs font-medium rounded-md px-3 py-1.5 bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {sweeping ? "検証実行中..." : "検証を実行"}
            </button>
          </div>
        </header>

        {error && (
          <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
        {sweepMsg && (
          <div className="rounded-md bg-blue-50 border border-blue-200 px-4 py-3 text-sm text-blue-700">
            {sweepMsg}
          </div>
        )}

        {loading && !summary && (
          <div className="py-12 text-center text-sm text-gray-500">読み込み中...</div>
        )}

        {summary && (
          <>
            {/* KPI cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <KpiCard
                title="検証済み件数"
                value={String(summary.validated_count)}
                subtitle={`pending ${summary.pending_count}`}
              />
              <KpiCard
                title="Rolling Brier"
                value={fmtNum(summary.rolling_brier)}
                subtitle="低いほど良い (0–1)"
              />
              <KpiCard
                title="Coverage rate"
                value={fmtPct(summary.overall_coverage_rate)}
                subtitle="実績がレンジに入った割合"
              />
              <KpiCard
                title="MAE (return)"
                value={fmtPct(summary.overall_mae_return)}
                subtitle="期待 vs 実績の絶対誤差"
              />
            </div>

            {/* Reliability diagram + explanation */}
            <section className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
              <h2 className="text-sm font-semibold text-gray-700 mb-3">
                Reliability diagram
              </h2>
              <div className="flex flex-col md:flex-row items-start gap-6">
                <ReliabilityDiagram bins={summary.reliability_bins} />
                <div className="flex-1 text-xs text-gray-600 leading-relaxed space-y-2">
                  <p>
                    x軸: 予測確率, y軸: 実現頻度 (directional_hit)。 点の大きさは bin 内の予測数。
                  </p>
                  <p>
                    点が <span className="font-mono">y = x</span> に乗っていれば well-calibrated。
                    線より下なら過信 (overconfident)、上なら過小評価 (underconfident)。
                  </p>
                  <table className="w-full text-xs mt-2">
                    <thead className="text-gray-400">
                      <tr>
                        <th className="text-left font-normal pb-1">bin</th>
                        <th className="text-right font-normal pb-1">件数</th>
                        <th className="text-right font-normal pb-1">平均予測</th>
                        <th className="text-right font-normal pb-1">実現率</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {summary.reliability_bins
                        .filter((b) => b.count > 0)
                        .map((b) => (
                          <tr key={b.bin_lower}>
                            <td className="py-1">
                              {b.bin_lower.toFixed(1)}–{b.bin_upper.toFixed(1)}
                            </td>
                            <td className="py-1 text-right tabular-nums">{b.count}</td>
                            <td className="py-1 text-right tabular-nums">
                              {b.mean_predicted?.toFixed(2) ?? "—"}
                            </td>
                            <td className="py-1 text-right tabular-nums">
                              {b.realized_frequency?.toFixed(2) ?? "—"}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            {/* MAE by horizon */}
            <section className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
              <h2 className="text-sm font-semibold text-gray-700 mb-3">
                時間軸別 MAE
              </h2>
              {summary.mae_by_horizon.length === 0 ? (
                <p className="text-xs text-gray-400">該当データなし</p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="text-xs text-gray-400 uppercase tracking-wide">
                    <tr>
                      <th className="text-left font-normal py-1">Horizon</th>
                      <th className="text-right font-normal py-1">件数</th>
                      <th className="text-right font-normal py-1">MAE</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {summary.mae_by_horizon.map((h) => (
                      <tr key={h.time_horizon}>
                        <td className="py-1.5">
                          {HORIZON_LABEL[h.time_horizon] ?? h.time_horizon}
                        </td>
                        <td className="py-1.5 text-right tabular-nums">{h.count}</td>
                        <td className="py-1.5 text-right tabular-nums font-mono">
                          {fmtPct(h.mae_return)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            {/* MAE by impact level */}
            <section className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
              <h2 className="text-sm font-semibold text-gray-700 mb-3">
                影響レベル別 精度
              </h2>
              {summary.mae_by_level.length === 0 ? (
                <p className="text-xs text-gray-400">該当データなし</p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="text-xs text-gray-400 uppercase tracking-wide">
                    <tr>
                      <th className="text-left font-normal py-1">レベル</th>
                      <th className="text-right font-normal py-1">件数</th>
                      <th className="text-right font-normal py-1">MAE</th>
                      <th className="text-right font-normal py-1">Brier</th>
                      <th className="text-right font-normal py-1">Coverage</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {summary.mae_by_level.map((l) => (
                      <tr key={l.impact_level}>
                        <td className="py-1.5">{l.impact_level}次影響</td>
                        <td className="py-1.5 text-right tabular-nums">{l.count}</td>
                        <td className="py-1.5 text-right tabular-nums font-mono">
                          {fmtPct(l.mae_return)}
                        </td>
                        <td className="py-1.5 text-right tabular-nums font-mono">
                          {fmtNum(l.brier_score)}
                        </td>
                        <td className="py-1.5 text-right tabular-nums font-mono">
                          {fmtPct(l.coverage_rate)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            {/* Horizon × Level cross heatmap */}
            <section className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
              <h2 className="text-sm font-semibold text-gray-700 mb-3">
                時間軸 × 影響レベル MAE ヒートマップ
              </h2>
              {summary.horizon_level_cross.length === 0 ? (
                <p className="text-xs text-gray-400">該当データなし</p>
              ) : (
                <CrossHeatmap data={summary.horizon_level_cross} />
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}

function KpiCard({
  title,
  value,
  subtitle,
}: {
  title: string;
  value: string;
  subtitle?: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
      <p className="text-xs text-gray-500">{title}</p>
      <p className="text-xl font-bold text-gray-900 mt-1 tabular-nums">{value}</p>
      {subtitle && <p className="text-xs text-gray-400 mt-0.5">{subtitle}</p>}
    </div>
  );
}

const LEVEL_LABEL: Record<number, string> = {
  1: "1次",
  2: "2次",
  3: "3次",
  4: "4次",
};

function CrossHeatmap({ data }: { data: HorizonLevelCross[] }) {
  const horizons = [...new Set(data.map((d) => d.time_horizon))].sort();
  const levels = [...new Set(data.map((d) => d.impact_level))].sort();

  const lookup = new Map<string, HorizonLevelCross>();
  for (const d of data) {
    lookup.set(`${d.time_horizon}:${d.impact_level}`, d);
  }

  const maxMae = Math.max(...data.map((d) => d.mae_return), 0.01);

  function cellColor(mae: number): string {
    const ratio = Math.min(mae / maxMae, 1);
    if (ratio < 0.33) return "bg-emerald-100 text-emerald-800";
    if (ratio < 0.66) return "bg-yellow-100 text-yellow-800";
    return "bg-red-100 text-red-800";
  }

  return (
    <div className="overflow-x-auto">
      <table className="text-sm">
        <thead>
          <tr>
            <th className="text-left text-xs text-gray-400 font-normal px-2 py-1" />
            {levels.map((l) => (
              <th
                key={l}
                className="text-center text-xs text-gray-400 font-normal px-3 py-1"
              >
                {LEVEL_LABEL[l] ?? `${l}次`}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {horizons.map((h) => (
            <tr key={h}>
              <td className="text-xs text-gray-600 px-2 py-1 whitespace-nowrap">
                {HORIZON_LABEL[h] ?? h}
              </td>
              {levels.map((l) => {
                const cell = lookup.get(`${h}:${l}`);
                if (!cell) {
                  return (
                    <td
                      key={l}
                      className="text-center text-xs text-gray-300 px-3 py-1.5"
                    >
                      —
                    </td>
                  );
                }
                return (
                  <td
                    key={l}
                    className={`text-center text-xs font-mono tabular-nums px-3 py-1.5 rounded ${cellColor(cell.mae_return)}`}
                    title={`n=${cell.count}`}
                  >
                    {(cell.mae_return * 100).toFixed(1)}%
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
