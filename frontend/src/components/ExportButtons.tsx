"use client";

import { useState } from "react";
import { downloadMarkdown } from "@/lib/api";

interface Props {
  resultId: string;
}

export default function ExportButtons({ resultId }: Props) {
  const [mdLoading, setMdLoading] = useState(false);

  const handleMarkdown = async () => {
    setMdLoading(true);
    try {
      await downloadMarkdown(resultId);
    } catch (e) {
      alert(e instanceof Error ? e.message : "ダウンロードに失敗しました");
    } finally {
      setMdLoading(false);
    }
  };

  const handlePdf = () => {
    window.open(`/results/${resultId}/print`, "_blank");
  };

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-gray-400">エクスポート:</span>

      <button
        onClick={handleMarkdown}
        disabled={mdLoading}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-300 bg-white text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 transition-colors"
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
        </svg>
        {mdLoading ? "生成中..." : "Markdown"}
      </button>

      <button
        onClick={handlePdf}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-300 bg-white text-xs font-medium text-gray-700 hover:bg-gray-50 transition-colors"
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
        </svg>
        PDF
      </button>
    </div>
  );
}
