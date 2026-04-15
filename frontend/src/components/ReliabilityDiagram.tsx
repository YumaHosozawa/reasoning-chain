"use client";

import type { ReliabilityBin } from "@/lib/api";

interface Props {
  bins: ReliabilityBin[];
  /** 表示サイズ (正方形) */
  size?: number;
}

/**
 * Reliability diagram:
 *   x軸 = 予測確率 (bin 中央値), y軸 = 実現頻度
 *   完全カリブレーションは y=x 線上。
 *   点のサイズ = そのbinに属する予測数。
 */
export default function ReliabilityDiagram({ bins, size = 320 }: Props) {
  const padding = 36;
  const plot = size - padding * 2;

  // 描画対象binのみ (count > 0)
  const valid = bins.filter(
    (b) => b.count > 0 && b.mean_predicted != null && b.realized_frequency != null,
  );

  const maxCount = Math.max(1, ...valid.map((b) => b.count));

  const toX = (p: number) => padding + p * plot;
  const toY = (p: number) => padding + (1 - p) * plot;

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="rounded-lg border border-gray-200 bg-white"
      role="img"
      aria-label="Reliability diagram"
    >
      {/* 外枠 */}
      <rect
        x={padding}
        y={padding}
        width={plot}
        height={plot}
        fill="#fafafa"
        stroke="#e5e7eb"
      />

      {/* 0.1刻みグリッド */}
      {Array.from({ length: 9 }, (_, i) => (i + 1) / 10).map((v) => (
        <g key={v}>
          <line
            x1={toX(v)}
            y1={padding}
            x2={toX(v)}
            y2={padding + plot}
            stroke="#f3f4f6"
          />
          <line
            x1={padding}
            y1={toY(v)}
            x2={padding + plot}
            y2={toY(v)}
            stroke="#f3f4f6"
          />
        </g>
      ))}

      {/* y=x 基準線 */}
      <line
        x1={toX(0)}
        y1={toY(0)}
        x2={toX(1)}
        y2={toY(1)}
        stroke="#9ca3af"
        strokeDasharray="4 4"
      />

      {/* 軸ラベル */}
      <text x={padding - 6} y={toY(0) + 4} fontSize="10" textAnchor="end" fill="#6b7280">
        0.0
      </text>
      <text x={padding - 6} y={toY(1) + 4} fontSize="10" textAnchor="end" fill="#6b7280">
        1.0
      </text>
      <text x={toX(0)} y={toY(0) + 18} fontSize="10" textAnchor="middle" fill="#6b7280">
        0.0
      </text>
      <text x={toX(1)} y={toY(0) + 18} fontSize="10" textAnchor="middle" fill="#6b7280">
        1.0
      </text>
      <text
        x={padding + plot / 2}
        y={size - 6}
        fontSize="10"
        textAnchor="middle"
        fill="#4b5563"
      >
        予測確率
      </text>
      <text
        x={12}
        y={padding + plot / 2}
        fontSize="10"
        textAnchor="middle"
        fill="#4b5563"
        transform={`rotate(-90 12 ${padding + plot / 2})`}
      >
        実現頻度
      </text>

      {/* データ点 */}
      {valid.map((b, i) => {
        const r = 3 + 7 * (b.count / maxCount);
        return (
          <g key={i}>
            <circle
              cx={toX(b.mean_predicted as number)}
              cy={toY(b.realized_frequency as number)}
              r={r}
              fill="#2563eb"
              fillOpacity={0.6}
              stroke="#1d4ed8"
              strokeWidth={1}
            >
              <title>
                bin {b.bin_lower.toFixed(1)}–{b.bin_upper.toFixed(1)} ({b.count}件): predicted=
                {b.mean_predicted?.toFixed(2)}, realized={b.realized_frequency?.toFixed(2)}
              </title>
            </circle>
          </g>
        );
      })}

      {/* 折れ線 (実現曲線) */}
      {valid.length > 1 && (
        <polyline
          fill="none"
          stroke="#2563eb"
          strokeWidth={1.5}
          points={valid
            .map(
              (b) =>
                `${toX(b.mean_predicted as number)},${toY(b.realized_frequency as number)}`,
            )
            .join(" ")}
        />
      )}
    </svg>
  );
}
