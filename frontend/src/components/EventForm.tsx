"use client";

import { useState } from "react";

interface Props {
  onSubmit: (params: {
    event: string;
    chain_only: boolean;
    top_n: number;
    score_threshold: number;
  }) => void;
  loading: boolean;
}

export default function EventForm({ onSubmit, loading }: Props) {
  const [event, setEvent] = useState("");
  const [chainOnly, setChainOnly] = useState(false);
  const [topN, setTopN] = useState(10);
  const [threshold, setThreshold] = useState(0.6);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!event.trim()) return;
    onSubmit({ event: event.trim(), chain_only: chainOnly, top_n: topN, score_threshold: threshold });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          マクロ経済イベント
        </label>
        <textarea
          value={event}
          onChange={(e) => setEvent(e.target.value)}
          placeholder="例: 米国が対中半導体輸出規制を強化した。EDA・製造装置・素材に広範な制限が適用される。"
          rows={4}
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          disabled={loading}
        />
      </div>

      <div className="flex flex-wrap gap-4 text-sm">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={chainOnly}
            onChange={(e) => setChainOnly(e.target.checked)}
            className="rounded"
            disabled={loading}
          />
          <span className="text-gray-600">推論チェーンのみ（企業マッチングをスキップ）</span>
        </label>

        <label className="flex items-center gap-2">
          <span className="text-gray-600">表示企業数</span>
          <select
            value={topN}
            onChange={(e) => setTopN(Number(e.target.value))}
            className="rounded border border-gray-300 px-2 py-1 text-sm"
            disabled={loading}
          >
            {[5, 10, 20, 30].map((n) => (
              <option key={n} value={n}>{n}社</option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-2">
          <span className="text-gray-600">スコア閾値</span>
          <select
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="rounded border border-gray-300 px-2 py-1 text-sm"
            disabled={loading}
          >
            {[0.4, 0.5, 0.6, 0.7, 0.8].map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        </label>
      </div>

      <button
        type="submit"
        disabled={loading || !event.trim()}
        className="w-full rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {loading ? "分析中..." : "分析を実行"}
      </button>
    </form>
  );
}
