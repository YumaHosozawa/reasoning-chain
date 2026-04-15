"use client";

import { useState } from "react";
import EventForm from "@/components/EventForm";
import ChainViewer from "@/components/ChainViewer";
import MatchTable from "@/components/MatchTable";
import HistorySidebar from "@/components/HistorySidebar";
import ExportButtons from "@/components/ExportButtons";
import { analyze, fetchResult, type AnalyzeResponse } from "@/lib/api";

export default function Home() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | undefined>();
  const [refreshSignal, setRefreshSignal] = useState(0);

  const handleSubmit = async (params: {
    event: string;
    chain_only: boolean;
    top_n: number;
    score_threshold: number;
  }) => {
    setLoading(true);
    setError(null);
    setResult(null);
    setSelectedId(undefined);
    try {
      const res = await analyze(params);
      setResult(res);
      setSelectedId(res.id);
      setRefreshSignal((n) => n + 1);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "不明なエラー");
    } finally {
      setLoading(false);
    }
  };

  const handleSelectHistory = async (id: string) => {
    setSelectedId(id);
    setError(null);
    try {
      const detail = await fetchResult(id);
      // ResultDetail → AnalyzeResponse 形式に変換
      const chain = detail.chain_json as { impacts?: unknown[]; generated_at?: string; [k: string]: unknown };
      setResult({
        id: detail.id,
        event_summary: detail.event_summary,
        event_type: detail.event_type,
        confidence: detail.confidence,
        generated_at: (chain.generated_at as string) ?? detail.created_at,
        impacts: (chain.impacts ?? []) as AnalyzeResponse["impacts"],
        matches: detail.matches_json as AnalyzeResponse["matches"],
        total_impacts: detail.total_impacts,
        total_matches: detail.total_matches,
        db_ready: true,
      });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "履歴の取得に失敗しました");
    }
  };

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      {/* サイドバー（履歴） */}
      <HistorySidebar
        onSelect={handleSelectHistory}
        selectedId={selectedId}
        refreshSignal={refreshSignal}
      />

      {/* メインエリア */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-6 py-6 space-y-6">
          {/* ヘッダー */}
          <div>
            <h1 className="text-xl font-bold text-gray-900">推論チェーン分析</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              マクロ経済イベントから企業への多段影響を自動推論します
            </p>
          </div>

          {/* 入力フォーム */}
          <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
            <EventForm onSubmit={handleSubmit} loading={loading} />
          </div>

          {/* エラー */}
          {error && (
            <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          {/* ローディング */}
          {loading && (
            <div className="bg-white rounded-xl border border-gray-200 p-8 flex flex-col items-center gap-3 shadow-sm">
              <div className="animate-spin h-8 w-8 rounded-full border-4 border-blue-200 border-t-blue-600" />
              <p className="text-sm text-gray-500">推論チェーンを生成中...</p>
            </div>
          )}

          {/* 結果 */}
          {result && !loading && (
            <div className="space-y-4">
              {/* エクスポートボタン */}
              <div className="flex justify-end">
                <ExportButtons resultId={result.id} />
              </div>

              {/* イベントサマリ */}
              <div className="bg-blue-600 rounded-xl px-5 py-4 text-white shadow-sm">
                <p className="text-xs font-medium opacity-70 mb-1">イベント</p>
                <p className="text-base font-semibold leading-snug">{result.event_summary}</p>
              </div>

              {/* 推論チェーン */}
              <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
                <h2 className="text-sm font-semibold text-gray-700 mb-3">影響チェーン</h2>
                <ChainViewer
                  impacts={result.impacts}
                  confidence={result.confidence}
                  eventType={result.event_type}
                />
              </div>

              {/* マッチング企業 */}
              <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
                <h2 className="text-sm font-semibold text-gray-700 mb-3">
                  マッチング企業
                  {result.total_matches > 0 && (
                    <span className="ml-2 text-xs font-normal text-gray-400">
                      {result.matches.length} 社表示 / 計 {result.total_matches} 社
                    </span>
                  )}
                </h2>
                <MatchTable matches={result.matches} dbReady={result.db_ready} />
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
