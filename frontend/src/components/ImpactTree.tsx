"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import type { ImpactNode, CompanyMatch } from "@/lib/api";
import {
  buildTreeLayout,
  renderTreeSvgString,
  NODE_W,
  NODE_H,
  ROOT_W,
  ROOT_H,
  DIRECTION_BG,
  DIRECTION_BORDER,
  DIRECTION_LABEL,
  INTENSITY_COLOR,
  LEVEL_LABELS,
  type TreeNode,
} from "@/lib/tree-layout";

/* ------------------------------------------------------------------ */
/* コンポーネント                                                       */
/* ------------------------------------------------------------------ */

interface Props {
  impacts: ImpactNode[];
  matches?: CompanyMatch[];
  eventSummary: string;
}

export default function ImpactTree({ impacts, matches = [], eventSummary }: Props) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const layout = useMemo(
    () => buildTreeLayout(impacts, matches, eventSummary),
    [impacts, matches, eventSummary],
  );

  const { nodes, edges, rootX, rootY, width, height } = layout;

  const handleDownloadPng = useCallback(() => {
    const svgString = renderTreeSvgString(layout, eventSummary);
    const scale = 2; // Retina
    const canvas = document.createElement("canvas");
    canvas.width = width * scale;
    canvas.height = height * scale;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(scale, scale);

    const img = new Image();
    const blob = new Blob([svgString], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);

    img.onload = () => {
      ctx.fillStyle = "white";
      ctx.fillRect(0, 0, width, height);
      ctx.drawImage(img, 0, 0, width, height);
      URL.revokeObjectURL(url);

      const a = document.createElement("a");
      a.download = "impact_tree.png";
      a.href = canvas.toDataURL("image/png");
      a.click();
    };
    img.src = url;
  }, [layout, eventSummary, width, height]);

  const handleDownloadSvg = useCallback(() => {
    const svgString = renderTreeSvgString(layout, eventSummary);
    const blob = new Blob([svgString], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.download = "impact_tree.svg";
    a.href = url;
    a.click();
    URL.revokeObjectURL(url);
  }, [layout, eventSummary]);

  if (impacts.length === 0) {
    return <p className="text-sm text-gray-400 py-4 text-center">影響ノードがありません</p>;
  }

  const nodeMap = new Map(nodes.map((n) => [n.id, n]));

  // ハイライト対象
  const highlightSet = new Set<string>();
  if (hoveredId || selectedId) {
    const targetId = hoveredId || selectedId;
    highlightSet.add(targetId!);
    const queue = [targetId!];
    while (queue.length) {
      const cur = queue.shift()!;
      const n = nodeMap.get(cur);
      if (n) {
        for (const pid of n.parentIds) {
          highlightSet.add(pid);
          queue.push(pid);
        }
      }
    }
    const descQueue = [targetId!];
    while (descQueue.length) {
      const cur = descQueue.shift()!;
      for (const n of nodes) {
        if (n.parentIds.includes(cur) && !highlightSet.has(n.id)) {
          highlightSet.add(n.id);
          descQueue.push(n.id);
        }
      }
    }
  }

  const isHighlighting = highlightSet.size > 0;
  const selectedNode = selectedId ? nodeMap.get(selectedId) : null;

  // エッジにハイライト情報を付与
  const edgesWithHighlight = edges.map((e) => {
    const toNode = nodes.find(
      (n) => Math.abs(n.x - e.to.x) < 1 && Math.abs(n.y + NODE_H / 2 - e.to.y) < 1,
    );
    if (toNode && toNode.level === 1) {
      return { ...e, highlight: !isHighlighting || highlightSet.has(toNode.id) };
    }
    const fromNode = nodes.find(
      (n) => Math.abs(n.x + NODE_W - e.from.x) < 1 && Math.abs(n.y + NODE_H / 2 - e.from.y) < 1,
    );
    if (fromNode && toNode) {
      return {
        ...e,
        highlight: !isHighlighting || (highlightSet.has(toNode.id) && highlightSet.has(fromNode.id)),
      };
    }
    return { ...e, highlight: !isHighlighting };
  });

  return (
    <div className="space-y-3">
      {/* ダウンロードボタン */}
      <div className="flex justify-end gap-2">
        <button
          onClick={handleDownloadSvg}
          className="flex items-center gap-1 px-2.5 py-1 rounded-md border border-gray-300 bg-white text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors"
        >
          <DownloadIcon />
          SVG
        </button>
        <button
          onClick={handleDownloadPng}
          className="flex items-center gap-1 px-2.5 py-1 rounded-md border border-gray-300 bg-white text-xs font-medium text-gray-600 hover:bg-gray-50 transition-colors"
        >
          <DownloadIcon />
          PNG
        </button>
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <svg
          ref={svgRef}
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          className="block"
        >
          {/* エッジ */}
          {edgesWithHighlight.map((e, i) => {
            const midX = (e.from.x + e.to.x) / 2;
            return (
              <path
                key={i}
                d={`M ${e.from.x} ${e.from.y} C ${midX} ${e.from.y}, ${midX} ${e.to.y}, ${e.to.x} ${e.to.y}`}
                fill="none"
                stroke={e.highlight ? "#6366f1" : "#e5e7eb"}
                strokeWidth={e.highlight ? 2 : 1}
                opacity={isHighlighting && !e.highlight ? 0.25 : 1}
              />
            );
          })}

          {/* ルートノード */}
          <g>
            <rect x={rootX} y={rootY} width={ROOT_W} height={ROOT_H} rx={8} fill="#1d4ed8" />
            <text
              x={rootX + ROOT_W / 2}
              y={rootY + ROOT_H / 2}
              textAnchor="middle"
              dominantBaseline="central"
              fill="white"
              fontSize={11}
              fontWeight={600}
            >
              {eventSummary.length > 24 ? eventSummary.slice(0, 22) + "..." : eventSummary}
            </text>
          </g>

          {/* ノード */}
          {nodes.map((n) => {
            const dimmed = isHighlighting && !highlightSet.has(n.id);
            return (
              <g
                key={n.id}
                opacity={dimmed ? 0.25 : 1}
                style={{ cursor: "pointer" }}
                onMouseEnter={() => setHoveredId(n.id)}
                onMouseLeave={() => setHoveredId(null)}
                onClick={() => setSelectedId(selectedId === n.id ? null : n.id)}
              >
                <rect
                  x={n.x}
                  y={n.y}
                  width={NODE_W}
                  height={NODE_H}
                  rx={8}
                  fill={DIRECTION_BG[n.direction] || "#f3f4f6"}
                  stroke={
                    hoveredId === n.id || selectedId === n.id
                      ? "#6366f1"
                      : DIRECTION_BORDER[n.direction] || "#d1d5db"
                  }
                  strokeWidth={hoveredId === n.id || selectedId === n.id ? 2 : 1}
                />
                <rect x={n.x + 6} y={n.y + 6} width={28} height={16} rx={4} fill="#6366f1" />
                <text
                  x={n.x + 20}
                  y={n.y + 14}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fill="white"
                  fontSize={9}
                  fontWeight={600}
                >
                  {LEVEL_LABELS[n.level] || `${n.level}次`}
                </text>
                <text
                  x={n.x + 40}
                  y={n.y + 14}
                  dominantBaseline="central"
                  fontSize={10}
                  fontWeight={700}
                  fill={
                    n.direction === "positive"
                      ? "#059669"
                      : n.direction === "negative"
                      ? "#dc2626"
                      : "#d97706"
                  }
                >
                  {DIRECTION_LABEL[n.direction]}
                </text>
                <circle
                  cx={n.x + NODE_W - 14}
                  cy={n.y + 14}
                  r={4}
                  fill={INTENSITY_COLOR[n.intensity] || "#9ca3af"}
                />
                <text
                  x={n.x + NODE_W / 2}
                  y={n.y + 36}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize={12}
                  fontWeight={600}
                  fill="#1f2937"
                >
                  {n.sector.length > 14 ? n.sector.slice(0, 12) + "..." : n.sector}
                </text>
                {n.matchCount > 0 && (
                  <>
                    <rect
                      x={n.x + NODE_W / 2 - 20}
                      y={n.y + NODE_H - 20}
                      width={40}
                      height={14}
                      rx={7}
                      fill="#dbeafe"
                    />
                    <text
                      x={n.x + NODE_W / 2}
                      y={n.y + NODE_H - 13}
                      textAnchor="middle"
                      dominantBaseline="central"
                      fontSize={9}
                      fill="#2563eb"
                      fontWeight={500}
                    >
                      {n.matchCount}社
                    </text>
                  </>
                )}
                {n.probability != null && (
                  <text
                    x={n.x + NODE_W - 8}
                    y={n.y + NODE_H - 10}
                    textAnchor="end"
                    fontSize={9}
                    fill="#6b7280"
                  >
                    p={n.probability.toFixed(2)}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>

      {/* 選択ノードの詳細パネル */}
      {selectedNode && (
        <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-3 space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-indigo-600">
              {LEVEL_LABELS[selectedNode.level] || `${selectedNode.level}次`}影響
            </span>
            <span className="font-semibold text-sm text-gray-800">{selectedNode.sector}</span>
            {selectedNode.matchCount > 0 && (
              <span className="text-xs text-blue-600">{selectedNode.matchCount}社マッチ</span>
            )}
          </div>
          <p className="text-sm text-gray-700">{selectedNode.description}</p>
          <p className="text-xs text-gray-500">
            <span className="font-medium">因果根拠：</span>
            {selectedNode.rationale}
          </p>
          {selectedNode.parentIds.length > 0 && (
            <p className="text-xs text-gray-500">
              <span className="font-medium">上流セクター：</span>
              {selectedNode.parentIds
                .map((pid) => nodeMap.get(pid)?.sector)
                .filter(Boolean)
                .join("、")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function DownloadIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
      />
    </svg>
  );
}
