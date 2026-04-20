/**
 * 影響ツリーのレイアウト計算 (純粋なデータ変換、React非依存)
 *
 * ImpactTree コンポーネントとプリントページの両方で使用する。
 */

import type { ImpactNode, CompanyMatch } from "@/lib/api";

/* ------------------------------------------------------------------ */
/* 定数                                                                */
/* ------------------------------------------------------------------ */

export const NODE_W = 180;
export const NODE_H = 72;
export const H_GAP = 60;
export const V_GAP = 24;
export const ROOT_W = 200;
export const ROOT_H = 40;
export const PADDING = 24;

export const DIRECTION_BG: Record<string, string> = {
  positive: "#d1fae5",
  negative: "#fee2e2",
  mixed: "#fef9c3",
};
export const DIRECTION_BORDER: Record<string, string> = {
  positive: "#6ee7b7",
  negative: "#fca5a5",
  mixed: "#fde68a",
};
export const DIRECTION_LABEL: Record<string, string> = {
  positive: "+",
  negative: "-",
  mixed: "+-",
};
export const INTENSITY_COLOR: Record<string, string> = {
  high: "#ef4444",
  medium: "#f59e0b",
  low: "#22c55e",
};
export const LEVEL_LABELS: Record<number, string> = {
  1: "1次",
  2: "2次",
  3: "3次",
  4: "4次",
};

/* ------------------------------------------------------------------ */
/* 型                                                                  */
/* ------------------------------------------------------------------ */

export interface TreeNode {
  id: string;
  level: number;
  sector: string;
  direction: string;
  intensity: string;
  description: string;
  rationale: string;
  probability: number | null | undefined;
  parentIds: string[];
  matchCount: number;
  x: number;
  y: number;
}

export interface TreeEdge {
  from: { x: number; y: number };
  to: { x: number; y: number };
}

export interface TreeLayout {
  nodes: TreeNode[];
  edges: TreeEdge[];
  rootX: number;
  rootY: number;
  width: number;
  height: number;
}

/* ------------------------------------------------------------------ */
/* レイアウト計算                                                       */
/* ------------------------------------------------------------------ */

export function buildTreeLayout(
  impacts: ImpactNode[],
  matches: CompanyMatch[],
  eventSummary: string,
): TreeLayout {
  // マッチ数集計
  const matchCountMap = new Map<string, number>();
  for (const m of matches) {
    const key = m.impact_sector || "";
    matchCountMap.set(key, (matchCountMap.get(key) || 0) + 1);
  }

  // レベル別に分類
  const byLevel = new Map<number, ImpactNode[]>();
  for (const n of impacts) {
    if (!byLevel.has(n.level)) byLevel.set(n.level, []);
    byLevel.get(n.level)!.push(n);
  }

  const levels = Array.from(byLevel.keys()).sort((a, b) => a - b);
  if (levels.length === 0) {
    return { nodes: [], edges: [], rootX: PADDING, rootY: PADDING, width: ROOT_W + PADDING * 2, height: ROOT_H + PADDING * 2 };
  }

  const maxNodesPerLevel = Math.max(...levels.map((l) => byLevel.get(l)!.length), 1);

  const nodes: TreeNode[] = [];
  const sectorToId = new Map<string, string>();

  const totalHeight = maxNodesPerLevel * (NODE_H + V_GAP) - V_GAP + PADDING * 2;
  const rootX = PADDING;
  const rootY = totalHeight / 2 - ROOT_H / 2;

  for (const level of levels) {
    const levelNodes = byLevel.get(level)!;
    const x = PADDING + ROOT_W + H_GAP + (level - 1) * (NODE_W + H_GAP);
    const blockH = levelNodes.length * (NODE_H + V_GAP) - V_GAP;
    const offsetY = (totalHeight - blockH) / 2;

    for (let i = 0; i < levelNodes.length; i++) {
      const n = levelNodes[i];
      const y = offsetY + i * (NODE_H + V_GAP);
      const id = `${n.level}:${n.sector}`;
      sectorToId.set(n.sector, id);

      const parentIds: string[] = [];
      if (n.parent_sectors && n.parent_sectors.length > 0) {
        for (const ps of n.parent_sectors) {
          const pid = sectorToId.get(ps);
          if (pid) parentIds.push(pid);
        }
      } else if (n.level > 1) {
        const prevLevel = byLevel.get(n.level - 1);
        if (prevLevel) {
          for (const pn of prevLevel) {
            const pid = sectorToId.get(pn.sector);
            if (pid) parentIds.push(pid);
          }
        }
      }

      nodes.push({
        id,
        level: n.level,
        sector: n.sector,
        direction: n.direction,
        intensity: n.intensity,
        description: n.description,
        rationale: n.rationale,
        probability: n.probability,
        parentIds,
        matchCount: matchCountMap.get(n.sector) || 0,
        x,
        y,
      });
    }
  }

  // エッジ
  const edges: TreeEdge[] = [];

  // ルート → level1
  for (const n of nodes) {
    if (n.level === 1) {
      edges.push({
        from: { x: rootX + ROOT_W, y: rootY + ROOT_H / 2 },
        to: { x: n.x, y: n.y + NODE_H / 2 },
      });
    }
  }

  // ノード間
  const nodeMap = new Map(nodes.map((n) => [n.id, n]));
  for (const n of nodes) {
    for (const pid of n.parentIds) {
      const parent = nodeMap.get(pid);
      if (parent) {
        edges.push({
          from: { x: parent.x + NODE_W, y: parent.y + NODE_H / 2 },
          to: { x: n.x, y: n.y + NODE_H / 2 },
        });
      }
    }
  }

  const maxX = Math.max(...nodes.map((n) => n.x + NODE_W), ROOT_W + PADDING);

  return { nodes, edges, rootX, rootY, width: maxX + PADDING, height: totalHeight };
}

/* ------------------------------------------------------------------ */
/* SVG 文字列生成 (プリント / PNG 出力用)                               */
/* ------------------------------------------------------------------ */

export function renderTreeSvgString(layout: TreeLayout, eventSummary: string): string {
  const { nodes, edges, rootX, rootY, width, height } = layout;

  const edgePaths = edges
    .map((e) => {
      const midX = (e.from.x + e.to.x) / 2;
      return `<path d="M ${e.from.x} ${e.from.y} C ${midX} ${e.from.y}, ${midX} ${e.to.y}, ${e.to.x} ${e.to.y}" fill="none" stroke="#6366f1" stroke-width="1.5"/>`;
    })
    .join("\n");

  const truncatedSummary = eventSummary.length > 24 ? eventSummary.slice(0, 22) + "..." : eventSummary;

  const rootGroup = `
    <rect x="${rootX}" y="${rootY}" width="${ROOT_W}" height="${ROOT_H}" rx="8" fill="#1d4ed8"/>
    <text x="${rootX + ROOT_W / 2}" y="${rootY + ROOT_H / 2}" text-anchor="middle" dominant-baseline="central" fill="white" font-size="11" font-weight="600">${escapeXml(truncatedSummary)}</text>
  `;

  const nodeGroups = nodes
    .map((n) => {
      const sectorText = n.sector.length > 14 ? n.sector.slice(0, 12) + "..." : n.sector;
      const dirColor = n.direction === "positive" ? "#059669" : n.direction === "negative" ? "#dc2626" : "#d97706";

      let matchBadge = "";
      if (n.matchCount > 0) {
        matchBadge = `
          <rect x="${n.x + NODE_W / 2 - 20}" y="${n.y + NODE_H - 20}" width="40" height="14" rx="7" fill="#dbeafe"/>
          <text x="${n.x + NODE_W / 2}" y="${n.y + NODE_H - 13}" text-anchor="middle" dominant-baseline="central" font-size="9" fill="#2563eb" font-weight="500">${n.matchCount}社</text>
        `;
      }

      let probText = "";
      if (n.probability != null) {
        probText = `<text x="${n.x + NODE_W - 8}" y="${n.y + NODE_H - 10}" text-anchor="end" font-size="9" fill="#6b7280">p=${n.probability.toFixed(2)}</text>`;
      }

      return `
        <g>
          <rect x="${n.x}" y="${n.y}" width="${NODE_W}" height="${NODE_H}" rx="8" fill="${DIRECTION_BG[n.direction] || "#f3f4f6"}" stroke="${DIRECTION_BORDER[n.direction] || "#d1d5db"}" stroke-width="1"/>
          <rect x="${n.x + 6}" y="${n.y + 6}" width="28" height="16" rx="4" fill="#6366f1"/>
          <text x="${n.x + 20}" y="${n.y + 14}" text-anchor="middle" dominant-baseline="central" fill="white" font-size="9" font-weight="600">${LEVEL_LABELS[n.level] || n.level + "次"}</text>
          <text x="${n.x + 40}" y="${n.y + 14}" dominant-baseline="central" font-size="10" font-weight="700" fill="${dirColor}">${DIRECTION_LABEL[n.direction] || ""}</text>
          <circle cx="${n.x + NODE_W - 14}" cy="${n.y + 14}" r="4" fill="${INTENSITY_COLOR[n.intensity] || "#9ca3af"}"/>
          <text x="${n.x + NODE_W / 2}" y="${n.y + 36}" text-anchor="middle" dominant-baseline="central" font-size="12" font-weight="600" fill="#1f2937">${escapeXml(sectorText)}</text>
          ${matchBadge}
          ${probText}
        </g>
      `;
    })
    .join("\n");

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" style="background:white;font-family:'Hiragino Sans','Yu Gothic',sans-serif">
  ${edgePaths}
  ${rootGroup}
  ${nodeGroups}
</svg>`;
}

function escapeXml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
