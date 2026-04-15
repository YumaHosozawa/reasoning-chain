"""
セグメントパーサー

有報テキストからセグメント情報を構造化データに変換する。
LLMを使ってセグメント名・売上構成比・地域構成・キーワードを抽出する。
"""

from __future__ import annotations

import json
import os
import re

import anthropic
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, anthropic.RateLimitError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code >= 500
    return False

from src.models import Segment


_SEGMENT_EXTRACTION_SYSTEM = """\
あなたは企業アナリストです。
有価証券報告書のセグメント情報テキストから、構造化データを抽出してください。
必ず指定されたJSON形式のみを出力してください。
"""

_SEGMENT_EXTRACTION_USER = """\
以下の有価証券報告書のセグメント情報から、各セグメントの情報を抽出してください。

【セグメント情報テキスト】
{segment_text}

【事業全体の説明（参考）】
{business_description}

以下の形式でJSONを出力してください（コードブロックなし、JSONのみ）:

{{
  "segments": [
    {{
      "name": "セグメント名",
      "revenue_ratio": 0.0から1.0の数値（売上構成比、不明な場合は0.0）,
      "description": "セグメントの事業説明（2〜3文）",
      "geographic_exposure": {{
        "JP": 0.0から1.0,
        "CN": 0.0から1.0,
        "US": 0.0から1.0,
        "ASIA": 0.0から1.0,
        "EU": 0.0から1.0,
        "OTHER": 0.0から1.0
      }},
      "keywords": ["キーワード1", "キーワード2", "キーワード3"]
    }}
  ],
  "single_segment": true|false
}}

注意:
- revenue_ratio の合計は1.0になるようにしてください（不明な場合は均等配分）
- geographic_exposure が不明な場合は {{"JP": 1.0}} としてください
- 単一セグメント企業の場合は single_segment を true にしてください
- keywords は事業・技術・製品・顧客・地域のキーワードを含めてください（5〜10語）
"""


class SegmentParser:
    """有報テキストからセグメント情報を構造化するクラス"""

    def __init__(self, model: str | None = None) -> None:
        self._client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )
        # セグメント解析はコスト削減のためHaikuを使用
        self.model = model or os.environ.get(
            "SCORING_MODEL", "claude-haiku-4-5-20251001"
        )

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=10),
        reraise=True,
    )
    def parse(
        self,
        segment_text: str,
        business_description: str = "",
    ) -> list[Segment]:
        """
        セグメントテキストをSegmentリストに変換する。

        Args:
            segment_text: 有報のセグメント情報テキスト
            business_description: 有報の事業内容テキスト（補助情報）

        Returns:
            list[Segment]: 構造化されたセグメントリスト
        """
        if not segment_text and not business_description:
            return []

        # テキストが短すぎる場合はルールベースでフォールバック
        combined = segment_text or business_description
        if len(combined) < 50:
            return self._fallback_single_segment(combined)

        # 長すぎるテキストは先頭3,000文字に切り詰め
        segment_text_trimmed = (segment_text or "")[:3000]
        biz_desc_trimmed = (business_description or "")[:1500]

        response = self._client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=_SEGMENT_EXTRACTION_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": _SEGMENT_EXTRACTION_USER.format(
                        segment_text=segment_text_trimmed,
                        business_description=biz_desc_trimmed,
                    ),
                }
            ],
        )

        raw = response.content[0].text.strip()
        return self._parse_json(raw)

    def _parse_json(self, raw: str) -> list[Segment]:
        """LLM出力JSONをSegmentリストに変換する"""
        text = raw
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(l for l in lines if not l.startswith("```")).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []

        segments = []
        raw_segments = data.get("segments", [])

        # revenue_ratio の正規化
        total = sum(s.get("revenue_ratio", 0.0) for s in raw_segments)
        if total > 0 and abs(total - 1.0) > 0.05:
            for s in raw_segments:
                s["revenue_ratio"] = s.get("revenue_ratio", 0.0) / total

        for s in raw_segments:
            segments.append(
                Segment(
                    name=s.get("name", ""),
                    revenue_ratio=float(s.get("revenue_ratio", 0.0)),
                    description=s.get("description", ""),
                    geographic_exposure=s.get("geographic_exposure", {"JP": 1.0}),
                    keywords=s.get("keywords", []),
                )
            )

        return segments

    def _fallback_single_segment(self, text: str) -> list[Segment]:
        """テキストが短い場合の単一セグメントフォールバック"""
        keywords = _extract_keywords_simple(text)
        return [
            Segment(
                name="事業全体",
                revenue_ratio=1.0,
                description=text[:200],
                geographic_exposure={"JP": 1.0},
                keywords=keywords,
            )
        ]


def _extract_keywords_simple(text: str, max_words: int = 10) -> list[str]:
    """
    簡易キーワード抽出（形態素解析なし）。
    カタカナ語・漢字語を抽出するルールベース実装。
    """
    # カタカナ語（3文字以上）
    katakana = re.findall(r"[ァ-ヶー]{3,}", text)
    # 漢字を含む2文字以上の語
    kanji_words = re.findall(r"[\u4e00-\u9fff][\u4e00-\u9fff\u3040-\u309f]{1,}", text)

    candidates = list(dict.fromkeys(katakana + kanji_words))  # 順序保持の重複除去
    return candidates[:max_words]
