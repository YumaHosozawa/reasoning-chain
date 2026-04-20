"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  fetchPresetEvents,
  runBacktestPreset,
  runBacktestAll,
  type PresetEvent,
  type BacktestResult,
} from "@/lib/api";

function fmtPct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

export default function BacktestPage() {
  const [events, setEvents] = useState<PresetEvent[]>([]);
  const [results, setResults] = useState<BacktestResult[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPresetEvents()
      .then(setEvents)
      .catch((e) => setError(e.message));
  }, []);

  const handleRunOne = async (name: string) => {
    setRunning(name);
    setError(null);
    try {
      const result = await runBacktestPreset(name);
      setResults((prev) => {
        const filtered = prev.filter((r) => r.event_date !== result.event_date);
        return [...filtered, result].sort(
          (a, b) => a.event_date.localeCompare(b.event_date),
        );
      });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "実行エラー");
    } finally {
      setRunning(null);
    }
  };

  const handleRunAll = async () => {
    setRunning("__all__");
    setError(null);
    try {
      const all = await runBacktestAll();
      setResults(all);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "一括実行エラー");
    } finally {
      setRunning(null);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <main className="max-w-6xl mx-auto px-6 py-8 space-y-6">
        <header className="flex items-center justify-between">
          <div>
            <Link href="/" className="text-xs text-blue-600 hover:underline">
              ← 分析に戻る
            </Link>
            <h1 className="text-xl font-bold text-gray-900 mt-1">
              バックテスト
            </h1>
            <p className="text-sm text-gray-500 mt-0.5">
              過去のマクロイベントで推論チェーンの精度を検証
            </p>
          </div>
          <button
            onClick={handleRunAll}
            disabled={running !== null}
            className="text-xs font-medium rounded-md px-4 py-2 bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {running === "__all__" ? "全件実行中..." : "全プリセットを一括実行"}
          </button>
        </header>

        {error && (
          <div className="rounded-md bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* プリセットイベント一覧 */}
        <section className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">
            プリセットイベント ({events.length}件)
          </h2>
          <div className="space-y-2">
            {events.map((ev) => (
              <div
                key={ev.name}
                className="flex items-center justify-between gap-4 rounded-lg border border-gray-100 px-4 py-3 hover:bg-gray-50"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-gray-800">
                      {ev.name}
                    </span>
                    <span className="text-xs text-gray-400">{ev.event_date}</span>
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5 truncate">
                    {ev.description}
                  </p>
                  <div className="flex gap-1 mt-1 flex-wrap">
                    {ev.ground_truth_sectors_positive.map((s) => (
                      <span
                        key={s}
                        className="px-1.5 py-0.5 rounded text-xs bg-emerald-50 text-emerald-700"
                      >
                        +{s}
                      </span>
                    ))}
                    {ev.ground_truth_sectors_negative.map((s) => (
                      <span
                        key={s}
                        className="px-1.5 py-0.5 rounded text-xs bg-red-50 text-red-700"
                      >
                        -{s}
                      </span>
                    ))}
                  </div>
                </div>
                <button
                  onClick={() => handleRunOne(ev.name)}
                  disabled={running !== null}
                  className="shrink-0 text-xs font-medium rounded px-3 py-1.5 bg-gray-100 text-gray-700 hover:bg-gray-200 disabled:opacity-50"
                >
                  {running === ev.name ? "実行中..." : "実行"}
                </button>
              </div>
            ))}
          </div>
        </section>

        {/* 結果テーブル */}
        {results.length > 0 && (
          <section className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-700 mb-3">
              検証結果
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs text-gray-400 uppercase tracking-wide">
                  <tr>
                    <th className="text-left font-normal py-1 px-2">イベント</th>
                    <th className="text-left font-normal py-1 px-2">日付</th>
                    <th className="text-right font-normal py-1 px-2">Chain F1</th>
                    <th className="text-right font-normal py-1 px-2">Precision</th>
                    <th className="text-right font-normal py-1 px-2">Recall</th>
                    <th className="text-right font-normal py-1 px-2">+Hit Rate</th>
                    <th className="text-right font-normal py-1 px-2">-Hit Rate</th>
                    <th className="text-right font-normal py-1 px-2">Top10 Return</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {results.map((r) => (
                    <tr key={r.event_date} className="hover:bg-gray-50">
                      <td className="py-2 px-2 text-gray-800 max-w-xs truncate">
                        {r.event.length > 40
                          ? r.event.slice(0, 40) + "..."
                          : r.event}
                      </td>
                      <td className="py-2 px-2 text-gray-500 text-xs whitespace-nowrap">
                        {r.event_date}
                      </td>
                      <td className="py-2 px-2 text-right font-mono tabular-nums">
                        <ScoreBadge value={r.chain_f1} />
                      </td>
                      <td className="py-2 px-2 text-right font-mono tabular-nums text-gray-600">
                        {fmtPct(r.chain_precision)}
                      </td>
                      <td className="py-2 px-2 text-right font-mono tabular-nums text-gray-600">
                        {fmtPct(r.chain_recall)}
                      </td>
                      <td className="py-2 px-2 text-right font-mono tabular-nums text-gray-600">
                        {fmtPct(r.positive_hit_rate)}
                      </td>
                      <td className="py-2 px-2 text-right font-mono tabular-nums text-gray-600">
                        {fmtPct(r.negative_hit_rate)}
                      </td>
                      <td className="py-2 px-2 text-right font-mono tabular-nums">
                        <ReturnBadge value={r.top10_return} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

function ScoreBadge({ value }: { value: number }) {
  const color =
    value >= 0.7
      ? "text-emerald-700 bg-emerald-50"
      : value >= 0.4
        ? "text-yellow-700 bg-yellow-50"
        : "text-red-700 bg-red-50";
  return (
    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${color}`}>
      {(value * 100).toFixed(0)}%
    </span>
  );
}

function ReturnBadge({ value }: { value: number }) {
  const sign = value > 0 ? "+" : "";
  const color = value > 0 ? "text-emerald-700" : value < 0 ? "text-red-700" : "text-gray-600";
  return (
    <span className={`text-xs font-medium ${color}`}>
      {sign}{(value * 100).toFixed(1)}%
    </span>
  );
}
