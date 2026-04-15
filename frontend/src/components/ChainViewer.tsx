"use client";

import { useState } from "react";
import type { ImpactNode } from "@/lib/api";

const LEVEL_LABELS: Record<number, string> = { 1: "一次", 2: "二次", 3: "三次", 4: "四次" };
const DIRECTION_COLOR: Record<string, string> = {
  positive: "bg-emerald-100 text-emerald-800 border-emerald-200",
  negative: "bg-red-100 text-red-800 border-red-200",
  mixed: "bg-yellow-100 text-yellow-800 border-yellow-200",
};
const INTENSITY_DOT: Record<string, string> = {
  high: "bg-red-500",
  medium: "bg-yellow-500",
  low: "bg-green-500",
};
const DIRECTION_LABEL: Record<string, string> = {
  positive: "＋ ポジティブ",
  negative: "－ ネガティブ",
  mixed: "± 混在",
};
const INTENSITY_LABEL: Record<string, string> = { high: "高", medium: "中", low: "低" };

const HORIZON_LABEL: Record<string, string> = {
  immediate: "即時",
  "1-4w": "1–4週",
  "1-3m": "1–3ヶ月",
  "3-12m": "3–12ヶ月",
};

function formatPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(1)}%`;
}

interface Props {
  impacts: ImpactNode[];
  confidence: number;
  eventType: string;
}

export default function ChainViewer({ impacts, confidence, eventType }: Props) {
  const [openLevels, setOpenLevels] = useState<Set<number>>(new Set([1, 2]));

  const maxLevel = Math.max(...impacts.map((n) => n.level), 0);

  const toggle = (level: number) =>
    setOpenLevels((prev) => {
      const next = new Set(prev);
      next.has(level) ? next.delete(level) : next.add(level);
      return next;
    });

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 text-sm text-gray-500">
        <span className="px-2 py-0.5 rounded-full bg-gray-100 font-mono">{eventType}</span>
        <span>信頼度 <strong className="text-gray-700">{Math.round(confidence * 100)}%</strong></span>
        <span>{impacts.length} 件の影響ノード</span>
      </div>

      {Array.from({ length: maxLevel }, (_, i) => i + 1).map((level) => {
        const nodes = impacts.filter((n) => n.level === level);
        if (!nodes.length) return null;
        const isOpen = openLevels.has(level);

        return (
          <div key={level} className="rounded-xl border border-gray-200 overflow-hidden">
            <button
              onClick={() => toggle(level)}
              className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
            >
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-gray-400 uppercase tracking-wider w-12">
                  {LEVEL_LABELS[level] ?? `${level}次`}影響
                </span>
                <span className="text-sm text-gray-600">{nodes.length} 件</span>
              </div>
              <span className="text-gray-400 text-xs">{isOpen ? "▲" : "▼"}</span>
            </button>

            {isOpen && (
              <div className="divide-y divide-gray-100">
                {nodes.map((node, idx) => (
                  <div key={idx} className="px-4 py-3 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-gray-800 text-sm">{node.sector}</span>
                      <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${DIRECTION_COLOR[node.direction]}`}>
                        {DIRECTION_LABEL[node.direction]}
                      </span>
                      <span className="flex items-center gap-1 text-xs text-gray-500">
                        <span className={`inline-block w-2 h-2 rounded-full ${INTENSITY_DOT[node.intensity]}`} />
                        影響度 {INTENSITY_LABEL[node.intensity]}
                      </span>
                    </div>
                    <p className="text-sm text-gray-700 leading-relaxed">{node.description}</p>
                    {(node.expected_return_pct_low != null ||
                      node.time_horizon ||
                      node.probability != null) && (
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        {node.expected_return_pct_low != null &&
                          node.expected_return_pct_high != null && (
                            <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-mono tabular-nums">
                              期待リターン {formatPct(node.expected_return_pct_low)} 〜{" "}
                              {formatPct(node.expected_return_pct_high)}
                            </span>
                          )}
                        {node.time_horizon && (
                          <span className="px-2 py-0.5 rounded bg-indigo-50 text-indigo-700">
                            {HORIZON_LABEL[node.time_horizon] ?? node.time_horizon}
                          </span>
                        )}
                        {node.probability != null && (
                          <span className="px-2 py-0.5 rounded bg-purple-50 text-purple-700 font-mono tabular-nums">
                            p = {node.probability.toFixed(2)}
                          </span>
                        )}
                      </div>
                    )}
                    <p className="text-xs text-gray-500 leading-relaxed">
                      <span className="font-medium">根拠：</span>{node.rationale}
                    </p>
                    {node.example_companies.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {node.example_companies.map((c) => (
                          <span key={c} className="text-xs px-2 py-0.5 rounded bg-blue-50 text-blue-700">{c}</span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
