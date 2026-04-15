"use client";

import { useState } from "react";
import type { CompanyMatch } from "@/lib/api";

const DIRECTION_BADGE: Record<string, string> = {
  positive: "bg-emerald-100 text-emerald-700",
  negative: "bg-red-100 text-red-700",
  mixed: "bg-yellow-100 text-yellow-700",
};
const DIRECTION_LABEL: Record<string, string> = {
  positive: "＋",
  negative: "－",
  mixed: "±",
};
const INTENSITY_LABEL: Record<string, string> = { high: "高", medium: "中", low: "低" };
const HORIZON_LABEL: Record<string, string> = {
  immediate: "即時",
  "1-4w": "1–4w",
  "1-3m": "1–3m",
  "3-12m": "3–12m",
};

function formatPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(1)}%`;
}

interface Props {
  matches: CompanyMatch[];
  dbReady?: boolean;
}

type FilterDir = "all" | "positive" | "negative" | "mixed";

export default function MatchTable({ matches, dbReady = true }: Props) {
  const [filter, setFilter] = useState<FilterDir>("all");
  const [sortKey, setSortKey] = useState<"final_score" | "impact_level">("final_score");

  if (!dbReady) {
    return (
      <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-4 text-sm text-amber-800 space-y-2">
        <p className="font-semibold">企業プロファイルDBが未構築です</p>
        <p className="text-xs leading-relaxed">
          以下のコマンドを実行してEDINETから企業データを取得・登録してください。
        </p>
        <pre className="bg-amber-100 rounded px-3 py-2 text-xs font-mono">
          cd backend{"\n"}
          python -m scripts.build_company_db --limit 100
        </pre>
        <p className="text-xs text-amber-700">
          ※ <code>--limit 100</code> は動作確認用です。全社登録は <code>--limit</code> を省略してください（数時間かかります）。
        </p>
      </div>
    );
  }

  if (!matches.length) {
    return (
      <p className="text-sm text-gray-400 py-4 text-center">
        マッチング企業なし（スコア閾値を下げると表示される場合があります）
      </p>
    );
  }

  const filtered = matches
    .filter((m) => filter === "all" || m.direction === filter)
    .sort((a, b) => {
      if (sortKey === "final_score") return b.final_score - a.final_score;
      return a.impact_level - b.impact_level;
    });

  const counts = {
    positive: matches.filter((m) => m.direction === "positive").length,
    negative: matches.filter((m) => m.direction === "negative").length,
    mixed: matches.filter((m) => m.direction === "mixed").length,
  };

  return (
    <div className="space-y-3">
      {/* フィルタバー */}
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {(["all", "positive", "negative", "mixed"] as const).map((d) => (
          <button
            key={d}
            onClick={() => setFilter(d)}
            className={`px-3 py-1 rounded-full border text-xs font-medium transition-colors ${
              filter === d
                ? "bg-blue-600 text-white border-blue-600"
                : "bg-white text-gray-600 border-gray-300 hover:bg-gray-50"
            }`}
          >
            {d === "all"
              ? `すべて (${matches.length})`
              : d === "positive"
              ? `＋ ポジティブ (${counts.positive})`
              : d === "negative"
              ? `－ ネガティブ (${counts.negative})`
              : `± 混在 (${counts.mixed})`}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <span className="text-gray-500 text-xs">並び替え:</span>
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as typeof sortKey)}
            className="text-xs rounded border border-gray-300 px-2 py-1"
          >
            <option value="final_score">スコア順</option>
            <option value="impact_level">影響レベル順</option>
          </select>
        </div>
      </div>

      {/* テーブル */}
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
            <tr>
              <th className="px-3 py-2 text-left">企業</th>
              <th className="px-3 py-2 text-center">影響</th>
              <th className="px-3 py-2 text-center">レベル</th>
              <th className="px-3 py-2 text-center">スコア</th>
              <th className="px-3 py-2 text-center">期待リターン</th>
              <th className="px-3 py-2 text-center">Horizon</th>
              <th className="px-3 py-2 text-center">強度</th>
              <th className="px-3 py-2 text-left">根拠</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.map((m) => (
              <tr key={`${m.company_code}-${m.impact_level}`} className="hover:bg-gray-50">
                <td className="px-3 py-2">
                  <div className="font-medium text-gray-800">{m.company_name}</div>
                  <div className="text-xs text-gray-400">{m.company_code}</div>
                </td>
                <td className="px-3 py-2 text-center">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${DIRECTION_BADGE[m.direction]}`}>
                    {DIRECTION_LABEL[m.direction]}
                  </span>
                </td>
                <td className="px-3 py-2 text-center text-gray-600">{m.impact_level}次</td>
                <td className="px-3 py-2 text-center">
                  <ScoreBar value={m.final_score} />
                </td>
                <td className="px-3 py-2 text-center text-xs font-mono tabular-nums text-gray-700">
                  {formatPct(m.expected_return_pct)}
                </td>
                <td className="px-3 py-2 text-center text-xs text-gray-600">
                  {m.time_horizon ? HORIZON_LABEL[m.time_horizon] ?? m.time_horizon : "—"}
                </td>
                <td className="px-3 py-2 text-center text-xs text-gray-600">
                  {INTENSITY_LABEL[m.intensity]}
                </td>
                <td className="px-3 py-2 text-xs text-gray-600 max-w-xs">
                  <p className="line-clamp-2">{m.rationale}</p>
                  {m.affected_segments.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {m.affected_segments.map((s) => (
                        <span key={s} className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 text-xs">{s}</span>
                      ))}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ScoreBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.8 ? "bg-blue-500" : value >= 0.6 ? "bg-blue-400" : "bg-blue-200";
  return (
    <div className="flex items-center gap-1.5 justify-center">
      <div className="w-16 bg-gray-200 rounded-full h-1.5">
        <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-600 tabular-nums w-8">{(value).toFixed(2)}</span>
    </div>
  );
}
