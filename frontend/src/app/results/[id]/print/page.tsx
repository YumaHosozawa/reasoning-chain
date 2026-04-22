"use client";

import { useEffect, useMemo, useState, use } from "react";
import {
  fetchExportData,
  MANIFESTATION_LABELS,
  DURATION_LABELS,
  PRICE_REACTION_LABELS,
  EARNINGS_REFLECTION_LABELS,
  type ResultDetail,
  type ImpactNode,
  type CompanyMatch,
  type ManifestationTiming,
  type Duration,
  type PriceReactionTiming,
  type EarningsReflection,
} from "@/lib/api";
import { buildTreeLayout, renderTreeSvgString } from "@/lib/tree-layout";

const LEVEL_LABEL: Record<number, string> = { 1: "一次", 2: "二次", 3: "三次", 4: "四次" };
const DIRECTION_LABEL: Record<string, string> = {
  positive: "＋ ポジティブ",
  negative: "－ ネガティブ",
  mixed: "± 混在",
};
const INTENSITY_LABEL: Record<string, string> = { high: "高", medium: "中", low: "低" };
const TIMING_LABEL: Record<string, string> = {
  now: "今すぐ",
  "3-6m": "3〜6ヶ月後",
  "6-12m": "6〜12ヶ月後",
  "1-2y": "1〜2年後",
  "2-3y": "2〜3年後",
  "3-5y": "3〜5年後",
};
const DIRECTION_COLOR: Record<string, string> = {
  positive: "#d1fae5",
  negative: "#fee2e2",
  mixed: "#fef9c3",
};

function TreeDiagram({ impacts, matches, eventSummary }: { impacts: ImpactNode[]; matches: CompanyMatch[]; eventSummary: string }) {
  const layout = useMemo(() => buildTreeLayout(impacts, matches, eventSummary), [impacts, matches, eventSummary]);
  const svgString = useMemo(() => renderTreeSvgString(layout, eventSummary), [layout, eventSummary]);

  if (impacts.length === 0) return null;

  return (
    <div className="tree-section">
      <h2>影響ツリー</h2>
      <div className="tree-container" dangerouslySetInnerHTML={{ __html: svgString }} />
    </div>
  );
}

export default function PrintPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [data, setData] = useState<ResultDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchExportData(id)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [id]);

  useEffect(() => {
    if (data) {
      // データ読み込み後に少し待ってから印刷ダイアログを開く
      const timer = setTimeout(() => window.print(), 800);
      return () => clearTimeout(timer);
    }
  }, [data]);

  if (error) return <div style={{ padding: 32, color: "red" }}>エラー: {error}</div>;
  if (!data) return <div style={{ padding: 32 }}>読み込み中...</div>;

  const chain = data.chain_json as {
    impacts?: Array<{
      level: number; sector: string; description: string;
      direction: string; intensity: string; rationale: string;
      example_companies?: string[]; keywords?: string[];
      parent_sectors?: string[];
      expected_return_pct_low?: number | null;
      expected_return_pct_high?: number | null;
      time_horizon?: string | null;
      probability?: number | null;
      investment_timing?: string | null;
      timing_rationale?: string | null;
      manifestation_timing?: string | null;
      duration?: string | null;
      price_reaction_timing?: string | null;
      earnings_reflection?: string | null;
    }>;
    source_event?: string;
  };
  const impacts = (chain.impacts ?? []) as ImpactNode[];
  const matches = data.matches_json ?? [];
  const maxLevel = Math.max(...impacts.map((n) => n.level), 0);

  const positiveMatches = matches.filter((m) => m.direction === "positive");
  const negativeMatches = matches.filter((m) => m.direction === "negative");
  const mixedMatches = matches.filter((m) => m.direction === "mixed");

  return (
    <>
      <style>{`
        @media print {
          .no-print { display: none !important; }
          @page { margin: 20mm; size: A4; }
        }
        body { font-family: "Hiragino Sans", "Yu Gothic", sans-serif; font-size: 11pt; color: #111; }
        h1 { font-size: 18pt; border-bottom: 2px solid #1d4ed8; padding-bottom: 6px; margin-bottom: 4px; }
        h2 { font-size: 13pt; border-left: 4px solid #1d4ed8; padding-left: 8px; margin-top: 24px; }
        h3 { font-size: 11pt; margin-top: 16px; margin-bottom: 4px; }
        table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 9pt; }
        th { background: #1d4ed8; color: white; padding: 5px 8px; text-align: left; }
        td { border: 1px solid #ddd; padding: 4px 8px; vertical-align: top; }
        tr:nth-child(even) td { background: #f8f9fa; }
        .meta { color: #555; font-size: 10pt; margin-bottom: 16px; }
        .impact-card { border: 1px solid #ddd; border-radius: 4px; padding: 10px 12px; margin-bottom: 10px; }
        .tag { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 9pt; margin-right: 4px; }
        .footer { margin-top: 32px; font-size: 9pt; color: #888; border-top: 1px solid #ddd; padding-top: 8px; }
        .print-btn { position: fixed; top: 16px; right: 16px; background: #1d4ed8; color: white; border: none; padding: 8px 20px; border-radius: 6px; cursor: pointer; font-size: 13px; }
        .tree-section { break-inside: avoid; margin-top: 24px; }
        .tree-container { overflow-x: auto; border: 1px solid #ddd; border-radius: 4px; margin-top: 8px; }
        .tree-container svg { display: block; max-width: 100%; height: auto; }
      `}</style>

      <button className="print-btn no-print" onClick={() => window.print()}>
        PDFとして保存
      </button>

      <div style={{ maxWidth: 800, margin: "0 auto", padding: "32px 24px" }}>
        {/* ヘッダー */}
        <h1>推論チェーン分析レポート</h1>
        <div className="meta">
          <strong>生成日時</strong>: {new Date(data.created_at).toLocaleString("ja-JP")}&nbsp;&nbsp;
          <strong>イベント種別</strong>: {data.event_type}&nbsp;&nbsp;
          <strong>信頼度</strong>: {Math.round(data.confidence * 100)}%
        </div>

        {/* イベント */}
        <div style={{ background: "#1d4ed8", color: "white", borderRadius: 6, padding: "12px 16px", marginBottom: 24 }}>
          <div style={{ fontSize: "9pt", opacity: 0.7, marginBottom: 2 }}>分析イベント</div>
          <div style={{ fontSize: "13pt", fontWeight: "bold" }}>{data.event_summary}</div>
          {chain.source_event && (
            <div style={{ fontSize: "9pt", opacity: 0.8, marginTop: 4 }}>{chain.source_event}</div>
          )}
        </div>

        {/* 推論チェーン */}
        <h2>影響チェーン</h2>
        {Array.from({ length: maxLevel }, (_, i) => i + 1).map((level) => {
          const nodes = impacts.filter((n) => n.level === level);
          if (!nodes.length) return null;
          return (
            <div key={level}>
              <h3>{LEVEL_LABEL[level] ?? `${level}次`}影響</h3>
              {nodes.map((node, idx) => (
                <div key={idx} className="impact-card" style={{ borderLeftColor: node.direction === "positive" ? "#10b981" : node.direction === "negative" ? "#ef4444" : "#f59e0b", borderLeftWidth: 4 }}>
                  <div style={{ fontWeight: "bold", marginBottom: 4 }}>
                    {node.sector}
                    <span className="tag" style={{ background: DIRECTION_COLOR[node.direction] ?? "#f3f4f6", marginLeft: 8 }}>
                      {DIRECTION_LABEL[node.direction] ?? node.direction}
                    </span>
                    <span className="tag" style={{ background: "#f3f4f6" }}>
                      影響度: {INTENSITY_LABEL[node.intensity] ?? node.intensity}
                    </span>
                  </div>
                  <div style={{ marginBottom: 4 }}>{node.description}</div>
                  <div style={{ fontSize: "9pt", color: "#555" }}>
                    <strong>根拠:</strong> {node.rationale}
                  </div>
                  {node.investment_timing && (
                    <div style={{ fontSize: "9pt", marginTop: 4, background: "#fef3c7", padding: "4px 8px", borderRadius: 3 }}>
                      <strong>推奨エントリ:</strong>{" "}
                      <span style={{ fontWeight: "bold" }}>
                        {TIMING_LABEL[node.investment_timing] ?? node.investment_timing}
                      </span>
                      {node.timing_rationale && (
                        <div style={{ marginTop: 2, color: "#92400e" }}>
                          {node.timing_rationale}
                        </div>
                      )}
                    </div>
                  )}
                  {(node.manifestation_timing ||
                    node.duration ||
                    node.price_reaction_timing ||
                    node.earnings_reflection) && (
                    <div style={{ fontSize: "9pt", marginTop: 4, display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {node.manifestation_timing && (
                        <span className="tag" style={{ background: "#cffafe", color: "#155e75" }}>
                          発現: {MANIFESTATION_LABELS[node.manifestation_timing as ManifestationTiming] ?? node.manifestation_timing}
                        </span>
                      )}
                      {node.duration && (
                        <span className="tag" style={{ background: "#ccfbf1", color: "#115e59" }}>
                          持続: {DURATION_LABELS[node.duration as Duration] ?? node.duration}
                        </span>
                      )}
                      {node.price_reaction_timing && (
                        <span className="tag" style={{ background: "#fae8ff", color: "#86198f" }}>
                          株価反応: {PRICE_REACTION_LABELS[node.price_reaction_timing as PriceReactionTiming] ?? node.price_reaction_timing}
                        </span>
                      )}
                      {node.earnings_reflection && (
                        <span className="tag" style={{ background: "#ffedd5", color: "#9a3412" }}>
                          業績反映: {EARNINGS_REFLECTION_LABELS[node.earnings_reflection as EarningsReflection] ?? node.earnings_reflection}
                        </span>
                      )}
                    </div>
                  )}
                  {node.example_companies?.length ? (
                    <div style={{ fontSize: "9pt", marginTop: 4 }}>
                      <strong>関連企業例:</strong> {node.example_companies.join(" / ")}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          );
        })}

        {/* 影響ツリー図 */}
        <TreeDiagram impacts={impacts} matches={matches} eventSummary={data.event_summary} />

        {/* 企業マッチング */}
        {matches.length > 0 && (
          <>
            <h2>マッチング企業</h2>

            {[
              { group: positiveMatches, label: "ポジティブ影響" },
              { group: negativeMatches, label: "ネガティブ影響" },
              { group: mixedMatches, label: "混在" },
            ].map(({ group, label }) =>
              group.length === 0 ? null : (
                <div key={label}>
                  <h3>{label}</h3>
                  <table>
                    <thead>
                      <tr>
                        <th>企業名</th>
                        <th>コード</th>
                        <th>レベル</th>
                        <th>スコア</th>
                        <th>エントリ</th>
                        <th>強度</th>
                        <th>根拠</th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.map((m, i) => (
                        <tr key={i}>
                          <td>{m.company_name}</td>
                          <td>{m.company_code}</td>
                          <td>{m.impact_level}次</td>
                          <td>{Number(m.final_score).toFixed(2)}</td>
                          <td>{m.investment_timing ? (TIMING_LABEL[m.investment_timing] ?? m.investment_timing) : "—"}</td>
                          <td>{INTENSITY_LABEL[m.intensity] ?? m.intensity}</td>
                          <td>{m.rationale}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            )}

            <h3 style={{ marginTop: 20 }}>スコア内訳</h3>
            <table>
              <thead>
                <tr>
                  <th>企業名</th>
                  <th>総合スコア</th>
                  <th>ベクトル類似度</th>
                  <th>LLM関連度</th>
                  <th>セグメント構成比</th>
                </tr>
              </thead>
              <tbody>
                {[...matches]
                  .sort((a, b) => Number(b.final_score) - Number(a.final_score))
                  .map((m, i) => (
                    <tr key={i}>
                      <td>{m.company_name}</td>
                      <td>{Number(m.final_score).toFixed(2)}</td>
                      <td>{Number(m.vector_similarity).toFixed(2)}</td>
                      <td>{Number(m.llm_relevance_score).toFixed(2)}</td>
                      <td>{Number(m.segment_exposure_ratio).toFixed(2)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </>
        )}

        <div className="footer">
          このレポートは推論チェーン分析システムにより自動生成されました。
        </div>
      </div>
    </>
  );
}
