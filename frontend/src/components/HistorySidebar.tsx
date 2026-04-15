"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchResults, type ResultSummary } from "@/lib/api";

const EVENT_TYPE_LABEL: Record<string, string> = {
  geopolitical: "地政学",
  monetary: "金融政策",
  commodity: "商品",
  regulatory: "規制",
  natural_disaster: "自然災害",
  other: "その他",
};

interface Props {
  onSelect: (id: string) => void;
  selectedId?: string;
  refreshSignal: number;
}

export default function HistorySidebar({ onSelect, selectedId, refreshSignal }: Props) {
  const [results, setResults] = useState<ResultSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchResults(0, 30)
      .then((data) => setResults(data.results))
      .catch(() => setResults([]))
      .finally(() => setLoading(false));
  }, [refreshSignal]);

  return (
    <aside className="w-64 shrink-0 border-r border-gray-200 flex flex-col h-full">
      <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-700">分析履歴</h2>
        <Link
          href="/calibration"
          className="text-xs text-blue-600 hover:underline"
          title="予測精度ダッシュボード"
        >
          精度▸
        </Link>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && (
          <p className="text-xs text-gray-400 px-4 py-3">読み込み中...</p>
        )}
        {!loading && results.length === 0 && (
          <p className="text-xs text-gray-400 px-4 py-3">履歴はありません</p>
        )}
        {results.map((r) => (
          <button
            key={r.id}
            onClick={() => onSelect(r.id)}
            className={`w-full text-left px-4 py-3 border-b border-gray-100 hover:bg-gray-50 transition-colors ${
              selectedId === r.id ? "bg-blue-50 border-l-2 border-l-blue-500" : ""
            }`}
          >
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">
                {EVENT_TYPE_LABEL[r.event_type] ?? r.event_type}
              </span>
              <span className="text-xs text-gray-400">
                {Math.round(r.confidence * 100)}%
              </span>
            </div>
            <p className="text-xs font-medium text-gray-700 line-clamp-2 leading-relaxed">
              {r.event_summary}
            </p>
            <p className="text-xs text-gray-400 mt-1">
              {new Date(r.created_at).toLocaleString("ja-JP", {
                month: "2-digit", day: "2-digit",
                hour: "2-digit", minute: "2-digit",
              })}
              {" · "}
              影響{r.total_impacts}件 / マッチ{r.total_matches}社
            </p>
          </button>
        ))}
      </div>
    </aside>
  );
}
