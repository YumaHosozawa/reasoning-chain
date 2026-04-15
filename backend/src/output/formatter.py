"""
アラート出力フォーマッター

推論チェーンと企業マッチング結果を
Markdown / JSON / Slack形式に変換して出力する。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Sequence

from src.models import CompanyMatchResult, ReasoningChain

_INTENSITY_LABEL = {"high": "高", "medium": "中", "low": "低"}
_DIRECTION_LABEL = {
    "positive": "ポジティブ",
    "negative": "ネガティブ",
    "mixed": "混在",
}
_DIRECTION_SIGN = {"positive": "+", "negative": "-", "mixed": "±"}
_LEVEL_LABEL = {1: "一次", 2: "二次", 3: "三次", 4: "四次"}


class AlertFormatter:
    """推論チェーンアラートを各形式に変換するクラス"""

    def __init__(
        self,
        chain: ReasoningChain,
        matches: list[CompanyMatchResult],
        top_n: int = 10,
    ) -> None:
        self._chain = chain
        self._matches = matches
        self._top_n = top_n

    # ------------------------------------------------------------------
    # Markdown 形式
    # ------------------------------------------------------------------

    def to_markdown(self) -> str:
        """推論チェーンアラートをMarkdown形式に変換する"""
        lines: list[str] = []
        now = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M UTC")

        lines.append("## 【推論チェーンアラート】")
        lines.append("")
        lines.append(f"**イベント**: {self._chain.event_summary}")
        lines.append(f"**発生日時**: {now}")
        lines.append(f"**イベント種別**: {self._chain.event_type}")
        lines.append(f"**推論信頼度**: {int(self._chain.confidence * 100)}%")
        lines.append("")

        # --- 影響チェーン ---
        lines.append("### 影響チェーン")
        lines.append("")
        for level in range(1, self._chain.max_level + 1):
            nodes = self._chain.impacts_by_level(level)
            if not nodes:
                continue
            level_label = _LEVEL_LABEL.get(level, f"{level}次")
            for node in nodes:
                sign = _DIRECTION_SIGN.get(node.direction, "")
                intensity = _INTENSITY_LABEL.get(node.intensity, node.intensity)
                lines.append(
                    f"  **{level_label}影響** [{sign} {node.sector}]（影響度: {intensity}）"
                )
                lines.append(f"  > {node.description}")
                lines.append(f"  > 根拠: {node.rationale}")
                lines.append("")

        # --- マッチング企業 ---
        if self._matches:
            lines.append("### マッチング企業（上位）")
            lines.append("")

            pos = [m for m in self._matches if m.direction == "positive"]
            neg = [m for m in self._matches if m.direction == "negative"]
            mix = [m for m in self._matches if m.direction == "mixed"]

            if pos:
                lines.append("**ポジティブ影響:**")
                for m in pos[: self._top_n]:
                    lines.append(_format_match_line(m))
                lines.append("")

            if neg:
                lines.append("**ネガティブ影響:**")
                for m in neg[: self._top_n]:
                    lines.append(_format_match_line(m))
                lines.append("")

            if mix:
                lines.append("**混在（要注意）:**")
                for m in mix[: self._top_n // 2]:
                    lines.append(_format_match_line(m))
                lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # JSON 形式
    # ------------------------------------------------------------------

    def to_json(self, indent: int = 2) -> str:
        """推論チェーンアラートをJSON形式に変換する"""
        data = {
            "event_summary": self._chain.event_summary,
            "event_type": self._chain.event_type,
            "confidence": self._chain.confidence,
            "generated_at": self._chain.generated_at,
            "impacts": [
                {
                    "level": n.level,
                    "sector": n.sector,
                    "description": n.description,
                    "direction": n.direction,
                    "intensity": n.intensity,
                    "rationale": n.rationale,
                    "keywords": n.keywords,
                }
                for n in self._chain.impacts
            ],
            "matches": [
                {
                    "company_code": m.company_code,
                    "company_name": m.company_name,
                    "impact_level": m.impact_level,
                    "direction": m.direction,
                    "final_score": m.final_score,
                    "vector_similarity": m.vector_similarity,
                    "llm_relevance_score": m.llm_relevance_score,
                    "segment_exposure_ratio": m.segment_exposure_ratio,
                    "affected_segments": m.affected_segments,
                    "rationale": m.rationale,
                    "intensity": m.intensity,
                }
                for m in self._matches[: self._top_n * 3]
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=indent)

    # ------------------------------------------------------------------
    # Slack 形式（Block Kit）
    # ------------------------------------------------------------------

    def to_slack_blocks(self) -> list[dict]:
        """
        Slack Block Kit 形式のブロックリストを生成する。

        Slack の chat.postMessage API の blocks パラメータに渡す。
        """
        blocks: list[dict] = []

        # ヘッダー
        blocks.append({
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "推論チェーンアラート",
            },
        })

        # イベント概要
        blocks.append({
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*イベント*\n{self._chain.event_summary}"},
                {"type": "mrkdwn", "text": f"*種別*\n{self._chain.event_type}"},
                {
                    "type": "mrkdwn",
                    "text": f"*信頼度*\n{int(self._chain.confidence * 100)}%",
                },
            ],
        })

        blocks.append({"type": "divider"})

        # 影響チェーンサマリ（一次・二次のみ）
        chain_text = "*影響チェーン*\n"
        for level in (1, 2, 3):
            nodes = self._chain.impacts_by_level(level)
            label = _LEVEL_LABEL.get(level, f"{level}次")
            for node in nodes[:3]:
                sign = _DIRECTION_SIGN.get(node.direction, "")
                chain_text += f"  • *{label}* {sign} {node.sector}: {node.description[:60]}…\n"

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": chain_text},
        })

        blocks.append({"type": "divider"})

        # ポジティブ企業上位5社
        pos_matches = [m for m in self._matches if m.direction == "positive"][:5]
        if pos_matches:
            pos_text = "*ポジティブ影響（上位5社）*\n"
            for m in pos_matches:
                pos_text += f"  • {m.company_name}（{m.company_code}）スコア: {m.final_score:.2f} — {m.rationale[:50]}\n"
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": pos_text},
            })

        # ネガティブ企業上位5社
        neg_matches = [m for m in self._matches if m.direction == "negative"][:5]
        if neg_matches:
            neg_text = "*ネガティブ影響（上位5社）*\n"
            for m in neg_matches:
                neg_text += f"  • {m.company_name}（{m.company_code}）スコア: {m.final_score:.2f} — {m.rationale[:50]}\n"
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": neg_text},
            })

        return blocks

    def post_to_slack(self, webhook_url: str) -> bool:
        """
        Slack Incoming Webhook でアラートを送信する。

        Args:
            webhook_url: Slack Incoming Webhook URL

        Returns:
            bool: 送信成功かどうか
        """
        import httpx

        payload = {"blocks": self.to_slack_blocks()}
        try:
            resp = httpx.post(webhook_url, json=payload, timeout=10.0)
            return resp.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # print ヘルパー
    # ------------------------------------------------------------------

    def print_alert(self) -> None:
        """コンソールにMarkdownアラートを出力する"""
        print(self.to_markdown())


# ------------------------------------------------------------------
# ヘルパー
# ------------------------------------------------------------------

def _format_match_line(m: CompanyMatchResult) -> str:
    intensity = _INTENSITY_LABEL.get(m.intensity, m.intensity)
    segments = "、".join(m.affected_segments[:2]) or "—"
    return (
        f"  - **{m.company_name}**（{m.company_code}）"
        f" スコア: {m.final_score:.2f} | 影響度: {intensity} | "
        f"対象セグメント: {segments}\n"
        f"    {m.rationale}"
    )
