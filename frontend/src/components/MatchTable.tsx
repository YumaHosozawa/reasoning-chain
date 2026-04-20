"use client";

import { useState, useRef, useEffect } from "react";
import type { CompanyMatch, ImpactNode } from "@/lib/api";

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
const LEVEL_LABELS: Record<number, string> = { 1: "一次", 2: "二次", 3: "三次", 4: "四次" };

function formatPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(1)}%`;
}

interface Props {
  matches: CompanyMatch[];
  impacts?: ImpactNode[];
  dbReady?: boolean;
}

type FilterDir = "all" | "positive" | "negative" | "mixed";

export default function MatchTable({ matches, impacts = [], dbReady = true }: Props) {
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
              <th className="px-3 py-2 text-left">紐づきノード</th>
              <th className="px-3 py-2 text-center">スコア</th>
              <th className="px-3 py-2 text-center">期待リターン</th>
              <th className="px-3 py-2 text-center">Horizon</th>
              <th className="px-3 py-2 text-center">強度</th>
              <th className="px-3 py-2 text-left">根拠</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.map((m) => (
              <MatchRow key={`${m.company_code}-${m.impact_level}`} match={m} impacts={impacts} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 企業行コンポーネント                                                */
/* ------------------------------------------------------------------ */

function MatchRow({ match: m, impacts }: { match: CompanyMatch; impacts: ImpactNode[] }) {
  // 紐づく影響ノードを特定
  const linkedImpact = impacts.find(
    (n) =>
      n.level === m.impact_level &&
      (m.impact_sector ? n.sector === m.impact_sector : n.description === m.impact_description),
  );

  return (
    <tr className="hover:bg-gray-50 align-top">
      <td className="px-3 py-2">
        <div className="font-medium text-gray-800">{m.company_name}</div>
        <div className="text-xs text-gray-400">{m.company_code}</div>
      </td>
      <td className="px-3 py-2 text-center">
        <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${DIRECTION_BADGE[m.direction]}`}>
          {DIRECTION_LABEL[m.direction]}
        </span>
      </td>
      {/* 紐づきノード */}
      <td className="px-3 py-2 max-w-[200px]">
        <ImpactLinkBadge match={m} linkedImpact={linkedImpact} />
      </td>
      {/* スコア (クリックで算出根拠) */}
      <td className="px-3 py-2 text-center">
        <ScoreWithBreakdown match={m} />
      </td>
      {/* 期待リターン (クリックで算出根拠) */}
      <td className="px-3 py-2 text-center">
        <ReturnWithRationale match={m} linkedImpact={linkedImpact} />
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
        {m.company_context && <ContextToggle text={m.company_context} />}
      </td>
    </tr>
  );
}

/* ------------------------------------------------------------------ */
/* 紐づきノード表示                                                    */
/* ------------------------------------------------------------------ */

function ImpactLinkBadge({
  match,
  linkedImpact,
}: {
  match: CompanyMatch;
  linkedImpact: ImpactNode | undefined;
}) {
  const [open, setOpen] = useState(false);
  const sector = match.impact_sector || linkedImpact?.sector || "—";
  const levelLabel = LEVEL_LABELS[match.impact_level] ?? `${match.impact_level}次`;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="text-left w-full group"
      >
        <span className="text-xs font-medium text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded">
          {levelLabel}
        </span>
        <span className="ml-1 text-xs text-gray-700 group-hover:text-indigo-600 transition-colors">
          {sector}
        </span>
        <span className="ml-0.5 text-xs text-gray-400">▾</span>
      </button>

      {open && linkedImpact && (
        <Popover onClose={() => setOpen(false)}>
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold text-indigo-700">{levelLabel}影響</span>
              <span className="font-semibold text-sm text-gray-800">{linkedImpact.sector}</span>
              <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${DIRECTION_BADGE[linkedImpact.direction]}`}>
                {DIRECTION_LABEL[linkedImpact.direction]}
              </span>
            </div>
            <p className="text-xs text-gray-700 leading-relaxed">{linkedImpact.description}</p>
            <div className="border-t border-gray-100 pt-2">
              <p className="text-xs text-gray-500">
                <span className="font-medium">因果根拠：</span>
                {linkedImpact.rationale}
              </p>
            </div>
            {(linkedImpact.expected_return_pct_low != null || linkedImpact.probability != null) && (
              <div className="flex flex-wrap gap-2 text-xs">
                {linkedImpact.expected_return_pct_low != null &&
                  linkedImpact.expected_return_pct_high != null && (
                    <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-mono">
                      セクター期待リターン {formatPct(linkedImpact.expected_return_pct_low)} 〜{" "}
                      {formatPct(linkedImpact.expected_return_pct_high)}
                    </span>
                  )}
                {linkedImpact.probability != null && (
                  <span className="px-2 py-0.5 rounded bg-purple-50 text-purple-700 font-mono">
                    p = {linkedImpact.probability.toFixed(2)}
                  </span>
                )}
              </div>
            )}
            {linkedImpact.example_companies.length > 0 && (
              <div className="border-t border-gray-100 pt-2">
                <p className="text-xs text-gray-400 mb-1">LLM例示企業:</p>
                <div className="flex flex-wrap gap-1">
                  {linkedImpact.example_companies.map((c) => (
                    <span key={c} className="text-xs px-1.5 py-0.5 rounded bg-blue-50 text-blue-700">{c}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Popover>
      )}

      {open && !linkedImpact && (
        <Popover onClose={() => setOpen(false)}>
          <p className="text-xs text-gray-500">
            {levelLabel}影響「{sector}」に紐づく企業です。
            {match.impact_description && (
              <span className="block mt-1 text-gray-600">{match.impact_description}</span>
            )}
          </p>
        </Popover>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* スコア算出根拠ポップアップ                                           */
/* ------------------------------------------------------------------ */

function ScoreWithBreakdown({ match: m }: { match: CompanyMatch }) {
  const [open, setOpen] = useState(false);

  const wVector = 0.35;
  const wLlm = 0.40;
  const wSegment = 0.25;

  const vectorContrib = m.vector_similarity * wVector;
  const llmContrib = m.llm_relevance_score * wLlm;
  const segmentContrib = m.segment_exposure_ratio * wSegment;

  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} className="group">
        <ScoreBar value={m.final_score} />
        <span className="text-xs text-gray-400 group-hover:text-indigo-500 transition-colors">詳細 ▾</span>
      </button>

      {open && (
        <Popover onClose={() => setOpen(false)}>
          <div className="space-y-2">
            <p className="text-xs font-semibold text-gray-700">スコア算出根拠</p>
            <p className="text-xs text-gray-500">
              最終スコア = ベクトル類似度×{wVector} + LLM関連度×{wLlm} + セグメント構成比×{wSegment}
            </p>
            <table className="w-full text-xs">
              <thead className="text-gray-400">
                <tr>
                  <th className="text-left font-normal pb-1">要素</th>
                  <th className="text-right font-normal pb-1">値</th>
                  <th className="text-right font-normal pb-1">重み</th>
                  <th className="text-right font-normal pb-1">寄与</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 font-mono tabular-nums">
                <tr>
                  <td className="py-1 font-sans">ベクトル類似度</td>
                  <td className="py-1 text-right">{m.vector_similarity.toFixed(3)}</td>
                  <td className="py-1 text-right text-gray-400">×{wVector}</td>
                  <td className="py-1 text-right">{vectorContrib.toFixed(3)}</td>
                </tr>
                <tr>
                  <td className="py-1 font-sans">LLM 関連度</td>
                  <td className="py-1 text-right">{m.llm_relevance_score.toFixed(3)}</td>
                  <td className="py-1 text-right text-gray-400">×{wLlm}</td>
                  <td className="py-1 text-right">{llmContrib.toFixed(3)}</td>
                </tr>
                <tr>
                  <td className="py-1 font-sans">セグメント構成比</td>
                  <td className="py-1 text-right">{m.segment_exposure_ratio.toFixed(3)}</td>
                  <td className="py-1 text-right text-gray-400">×{wSegment}</td>
                  <td className="py-1 text-right">{segmentContrib.toFixed(3)}</td>
                </tr>
              </tbody>
              <tfoot className="border-t border-gray-200 font-bold">
                <tr>
                  <td className="py-1 font-sans" colSpan={3}>最終スコア</td>
                  <td className="py-1 text-right">{m.final_score.toFixed(3)}</td>
                </tr>
              </tfoot>
            </table>
            <div className="pt-1 space-y-1 text-xs text-gray-400">
              <p><span className="font-medium text-gray-500">ベクトル類似度:</span> 影響ノードの埋め込みと企業プロファイルのコサイン類似度</p>
              <p><span className="font-medium text-gray-500">LLM 関連度:</span> Claude が事業内容と影響の関連性を0-1で評価</p>
              <p><span className="font-medium text-gray-500">セグメント構成比:</span> 影響を受けるセグメントの売上構成比率</p>
            </div>
          </div>
        </Popover>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 期待リターン算出根拠ポップアップ                                      */
/* ------------------------------------------------------------------ */

function ReturnWithRationale({
  match: m,
  linkedImpact,
}: {
  match: CompanyMatch;
  linkedImpact: ImpactNode | undefined;
}) {
  const [open, setOpen] = useState(false);
  const hasValue = m.expected_return_pct != null;

  return (
    <div className="relative">
      <button
        onClick={() => hasValue && setOpen(!open)}
        className={`text-xs font-mono tabular-nums ${
          hasValue ? "text-gray-700 hover:text-indigo-600 cursor-pointer" : "text-gray-400 cursor-default"
        }`}
      >
        {formatPct(m.expected_return_pct)}
        {hasValue && <span className="text-gray-400 ml-0.5 text-xs">▾</span>}
      </button>

      {open && (
        <Popover onClose={() => setOpen(false)}>
          <div className="space-y-2">
            <p className="text-xs font-semibold text-gray-700">期待リターン算出根拠</p>

            {linkedImpact &&
              linkedImpact.expected_return_pct_low != null &&
              linkedImpact.expected_return_pct_high != null ? (
              <>
                <div className="text-xs text-gray-600 space-y-1">
                  <p>
                    <span className="font-medium">セクター期待レンジ:</span>{" "}
                    <span className="font-mono">{formatPct(linkedImpact.expected_return_pct_low)}</span>
                    {" 〜 "}
                    <span className="font-mono">{formatPct(linkedImpact.expected_return_pct_high)}</span>
                  </p>
                  <p>
                    <span className="font-medium">レンジ中央値:</span>{" "}
                    <span className="font-mono">
                      {formatPct(
                        (linkedImpact.expected_return_pct_low + linkedImpact.expected_return_pct_high) / 2,
                      )}
                    </span>
                  </p>
                  <p>
                    <span className="font-medium">セグメント構成比:</span>{" "}
                    <span className="font-mono">{(m.segment_exposure_ratio * 100).toFixed(1)}%</span>
                  </p>
                </div>
                <div className="bg-slate-50 rounded px-3 py-2 text-xs font-mono text-slate-700">
                  企業期待リターン = レンジ中央値 × セグメント構成比
                  <br />
                  = {formatPct(
                    (linkedImpact.expected_return_pct_low + linkedImpact.expected_return_pct_high) / 2,
                  )}{" "}
                  × {m.segment_exposure_ratio.toFixed(3)}
                  <br />
                  = <span className="font-bold">{formatPct(m.expected_return_pct)}</span>
                </div>
              </>
            ) : (
              <p className="text-xs text-gray-500">
                影響ノードのセクター期待リターンのレンジ中央値に、
                この企業の該当セグメント売上構成比を乗じて算出しています。
              </p>
            )}

            {m.probability != null && (
              <div className="border-t border-gray-100 pt-2 text-xs text-gray-600">
                <p>
                  <span className="font-medium">発生確率:</span>{" "}
                  <span className="font-mono">{(m.probability * 100).toFixed(0)}%</span>
                </p>
                <p className="text-gray-400 mt-0.5">
                  影響ノードでLLMが推定した、この影響が実現する確率です。
                  キャリブレーションダッシュボードで予測精度を検証できます。
                </p>
              </div>
            )}

            {m.time_horizon && (
              <div className="border-t border-gray-100 pt-2 text-xs text-gray-600">
                <p>
                  <span className="font-medium">時間軸:</span>{" "}
                  {HORIZON_LABEL[m.time_horizon] ?? m.time_horizon}
                  {m.prediction_window_days && (
                    <span className="text-gray-400 ml-1">（検証ウィンドウ: {m.prediction_window_days}日）</span>
                  )}
                </p>
                <p className="text-gray-400 mt-0.5">
                  影響が顕在化するまでの想定期間。実績検証はこの期間の株価リターンで行います。
                </p>
              </div>
            )}
          </div>
        </Popover>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 共通コンポーネント                                                   */
/* ------------------------------------------------------------------ */

function Popover({
  onClose,
  children,
}: {
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="absolute z-50 mt-1 left-0 w-80 bg-white rounded-lg border border-gray-200 shadow-lg p-4"
    >
      <button
        onClick={onClose}
        className="absolute top-2 right-2 text-gray-400 hover:text-gray-600 text-xs"
      >
        ✕
      </button>
      {children}
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
      <span className="text-xs text-gray-600 tabular-nums w-8">{value.toFixed(2)}</span>
    </div>
  );
}

function ContextToggle({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-1.5">
      <button
        onClick={() => setOpen(!open)}
        className="text-xs text-blue-600 hover:underline"
      >
        {open ? "動向を閉じる ▲" : "最近の動向 ▼"}
      </button>
      {open && (
        <div className="mt-1 px-2 py-1.5 rounded bg-blue-50 text-xs text-gray-700 leading-relaxed whitespace-pre-line">
          {text}
        </div>
      )}
    </div>
  );
}
