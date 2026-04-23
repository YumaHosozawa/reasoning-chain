"use client";

import { useState } from "react";
import {
  INVESTMENT_TIMING_LABELS,
  MANIFESTATION_LABELS,
  DURATION_LABELS,
  PRICE_REACTION_LABELS,
  EARNINGS_REFLECTION_LABELS,
  type ImpactNode,
  type CompanyMatch,
  type InvestmentTiming,
  type ManifestationTiming,
  type Duration,
  type PriceReactionTiming,
  type EarningsReflection,
} from "@/lib/api";

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
  matches?: CompanyMatch[];
  confidence: number;
  eventType: string;
}

export default function ChainViewer({ impacts, matches = [], confidence, eventType }: Props) {
  const [openLevels, setOpenLevels] = useState<Set<number>>(new Set([1, 2]));

  const maxLevel = Math.max(...impacts.map((n) => n.level), 0);

  const toggle = (level: number) =>
    setOpenLevels((prev) => {
      const next = new Set(prev);
      next.has(level) ? next.delete(level) : next.add(level);
      return next;
    });

  // 各影響ノードに紐づく企業を集計
  const matchesBySector = new Map<string, CompanyMatch[]>();
  for (const m of matches) {
    const key = `${m.impact_level}:${m.impact_sector || ""}`;
    if (!matchesBySector.has(key)) matchesBySector.set(key, []);
    matchesBySector.get(key)!.push(m);
  }

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
                {nodes.map((node, idx) => {
                  const key = `${node.level}:${node.sector}`;
                  const linkedMatches = matchesBySector.get(key) || [];

                  return (
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
                        {linkedMatches.length > 0 && (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-600 font-medium">
                            {linkedMatches.length} 社マッチ
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-gray-700 leading-relaxed">{node.description}</p>
                      {(node.expected_return_pct_low != null ||
                        node.time_horizon ||
                        node.probability != null ||
                        node.investment_timing) && (
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
                              反応 {HORIZON_LABEL[node.time_horizon] ?? node.time_horizon}
                            </span>
                          )}
                          {node.investment_timing && (
                            <span className="px-2 py-0.5 rounded bg-amber-100 text-amber-800 font-medium">
                              エントリ {INVESTMENT_TIMING_LABELS[node.investment_timing as InvestmentTiming] ?? node.investment_timing}
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
                      <TemporalAxes node={node} />
                      {node.timing_rationale && (
                        <p className="text-xs text-amber-800 leading-relaxed bg-amber-50/60 rounded px-2 py-1.5">
                          <span className="font-medium">タイミング根拠：</span>{node.timing_rationale}
                        </p>
                      )}
                      {node.example_companies.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {node.example_companies.map((c) => (
                            <span key={c} className="text-xs px-2 py-0.5 rounded bg-blue-50 text-blue-700">{c}</span>
                          ))}
                        </div>
                      )}
                      {/* マッチ企業サマリ */}
                      {linkedMatches.length > 0 && (
                        <LinkedCompanies matches={linkedMatches} />
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function TemporalAxes({ node }: { node: ImpactNode }) {
  const axes: { label: string; value?: string | null; color: string }[] = [
    {
      label: "発現時期",
      value: node.manifestation_timing
        ? MANIFESTATION_LABELS[node.manifestation_timing as ManifestationTiming]
        : null,
      color: "bg-cyan-50 text-cyan-700 border-cyan-200",
    },
    {
      label: "持続",
      value: node.duration ? DURATION_LABELS[node.duration as Duration] : null,
      color: "bg-teal-50 text-teal-700 border-teal-200",
    },
    {
      label: "株価反応",
      value: node.price_reaction_timing
        ? PRICE_REACTION_LABELS[node.price_reaction_timing as PriceReactionTiming]
        : null,
      color: "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200",
    },
    {
      label: "業績反映",
      value: node.earnings_reflection
        ? EARNINGS_REFLECTION_LABELS[node.earnings_reflection as EarningsReflection]
        : null,
      color: "bg-orange-50 text-orange-700 border-orange-200",
    },
  ];

  const hasAny = axes.some((a) => a.value);
  if (!hasAny) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
      {axes.map(
        (a) =>
          a.value && (
            <span
              key={a.label}
              className={`px-1.5 py-0.5 rounded border font-medium ${a.color}`}
            >
              {a.label}: {a.value}
            </span>
          ),
      )}
    </div>
  );
}

function LinkedCompanies({ matches }: { matches: CompanyMatch[] }) {
  const [open, setOpen] = useState(false);
  const sorted = [...matches].sort((a, b) => b.final_score - a.final_score);
  const preview = sorted.slice(0, 3);
  const rest = sorted.length - 3;

  return (
    <div className="bg-blue-50/50 rounded-lg px-3 py-2">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 text-xs text-blue-700 hover:text-blue-800 font-medium"
      >
        <span>紐づき企業</span>
        <span className="text-blue-400">{open ? "▲" : "▼"}</span>
      </button>
      {!open && (
        <div className="mt-1 flex flex-wrap gap-1.5">
          {preview.map((m) => (
            <span key={m.company_code} className="text-xs text-gray-600">
              {m.company_name}
              <span className="text-gray-400 ml-0.5">({m.final_score.toFixed(2)})</span>
            </span>
          ))}
          {rest > 0 && <span className="text-xs text-gray-400">+{rest}社</span>}
        </div>
      )}
      {open && (
        <div className="mt-2 space-y-1">
          {sorted.map((m) => (
            <div key={m.company_code} className="flex items-center gap-2 text-xs">
              <span className="font-medium text-gray-700 w-32 truncate">{m.company_name}</span>
              <span className="text-gray-400 font-mono">{m.company_code}</span>
              <span className="font-mono tabular-nums text-gray-600">{m.final_score.toFixed(2)}</span>
              <span className="text-gray-400 truncate flex-1">{m.rationale}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
