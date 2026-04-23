"""
推論チェーン生成エンジン

マクロ経済イベントから一次〜四次影響チェーンを生成する。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import AsyncIterator

import anthropic
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from src.models import HistoricalAnalogue, ImpactNode, ReasoningChain
from src.chain.prompt_templates import (
    CHAIN_GENERATION_SYSTEM,
    CHAIN_GENERATION_USER,
    EVENT_IMPORTANCE_SYSTEM,
    EVENT_IMPORTANCE_USER,
)


_VALID_HORIZONS = {"immediate", "1-4w", "1-3m", "3-12m"}
_VALID_INVESTMENT_TIMINGS = {"now", "3-6m", "6-12m", "1-2y", "2-3y", "3-5y"}
_VALID_MANIFESTATIONS = {"immediate", "1-3m", "3-12m", "1y+"}
_VALID_DURATIONS = {"short", "medium", "long"}
_VALID_PRICE_REACTIONS = {"leading", "coincident", "lagging"}
_VALID_EARNINGS_REFLECTIONS = {"orders", "revenue", "profit", "cash"}


def _to_float_or_none(value: object) -> float | None:
    """LLM出力の数値フィールドを float に変換。欠損・変換不能は None。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _validate_horizon(value: object) -> str | None:
    """time_horizon が許容値のいずれかに一致すれば返す。それ以外は None。"""
    if isinstance(value, str) and value in _VALID_HORIZONS:
        return value
    return None


def _validate_investment_timing(value: object) -> str | None:
    """investment_timing が許容値のいずれかに一致すれば返す。それ以外は None。"""
    if isinstance(value, str) and value in _VALID_INVESTMENT_TIMINGS:
        return value
    return None


def _validate_in(value: object, allowed: set[str]) -> str | None:
    """汎用バリデータ: value が allowed に含まれれば返す。それ以外は None。"""
    if isinstance(value, str) and value in allowed:
        return value
    return None


def _to_str_or_none(value: object) -> str | None:
    """LLM出力のテキストフィールドを str に正規化。空文字・None は None。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_bool_or_none(value: object) -> bool | None:
    """LLM出力の真偽フィールドを bool に変換。欠損は None。"""
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "1"):
            return True
        if lowered in ("false", "no", "0"):
            return False
    return None


def _parse_analogues(items: object) -> list[HistoricalAnalogue]:
    """LLM 出力の historical_analogues 配列を HistoricalAnalogue リストへ変換する。

    各要素は最低限 event_name と event_date と similarity_reason を持つことを要求し、
    欠落する場合はその要素をスキップする。最大 3 件まで採用。
    """
    if not isinstance(items, list):
        return []

    parsed: list[HistoricalAnalogue] = []
    for item in items[:3]:
        if not isinstance(item, dict):
            continue
        name = item.get("event_name")
        date = item.get("event_date")
        reason = item.get("similarity_reason")
        if not (isinstance(name, str) and isinstance(date, str) and isinstance(reason, str)):
            continue
        parsed.append(
            HistoricalAnalogue(
                event_name=name.strip(),
                event_date=date.strip(),
                similarity_reason=reason.strip(),
                outcome_summary=str(item.get("outcome_summary", "")).strip(),
                sector_return_pct=_to_float_or_none(item.get("sector_return_pct")),
                direction_matched=_to_bool_or_none(item.get("direction_matched")),
            )
        )
    return parsed


def _is_retryable(exc: BaseException) -> bool:
    """
    リトライ対象のエラーかどうかを判定する。

    - RateLimitError (429): リトライする
    - APIStatusError で 5xx: リトライする
    - BadRequestError (400), AuthenticationError (401), PermissionDeniedError (403): リトライしない
    """
    if isinstance(exc, anthropic.RateLimitError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code >= 500
    return False


class ReasoningChainGenerator:
    """マクロイベントから推論チェーンを生成するクラス"""

    def __init__(
        self,
        model: str | None = None,
        max_levels: int = 4,
        max_tokens: int = 8192,
    ) -> None:
        self._client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )
        self.model = model or os.environ.get("CHAIN_MODEL", "claude-opus-4-6")
        self.max_levels = max_levels
        self.max_tokens = max_tokens

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=10),
        reraise=True,
    )
    def generate(self, event_description: str) -> ReasoningChain:
        """
        マクロイベントから推論チェーンを生成する。

        Args:
            event_description: マクロ経済イベントの説明テキスト

        Returns:
            ReasoningChain: 構造化された推論チェーン
        """
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=CHAIN_GENERATION_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": CHAIN_GENERATION_USER.format(
                        event_description=event_description
                    ),
                }
            ],
        )

        raw_text = response.content[0].text
        return self._parse_chain(raw_text, event_description)

    async def generate_async(self, event_description: str) -> ReasoningChain:
        """非同期版: マクロイベントから推論チェーンを生成する"""
        async_client = anthropic.AsyncAnthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )
        response = await async_client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=CHAIN_GENERATION_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": CHAIN_GENERATION_USER.format(
                        event_description=event_description
                    ),
                }
            ],
        )
        raw_text = response.content[0].text
        return self._parse_chain(raw_text, event_description)

    async def generate_stream(
        self, event_description: str
    ) -> AsyncIterator[str]:
        """
        ストリーミングで推論チェーンを生成する（テキスト断片を逐次yield）。

        使用例:
            async for chunk in generator.generate_stream(event):
                print(chunk, end="", flush=True)
        """
        async_client = anthropic.AsyncAnthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )
        async with async_client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=CHAIN_GENERATION_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": CHAIN_GENERATION_USER.format(
                        event_description=event_description
                    ),
                }
            ],
        ) as stream:
            async for text in stream.text_stream:
                yield text

    def assess_importance(self, event_description: str) -> dict:
        """
        イベントの市場インパクト重要度を評価する。

        Returns:
            dict: {"importance": "high|medium|low", "scope": ..., "sectors_affected": [...], "rationale": ...}
        """
        response = self._client.messages.create(
            model=self.model,
            max_tokens=512,
            system=EVENT_IMPORTANCE_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": EVENT_IMPORTANCE_USER.format(
                        event_description=event_description
                    ),
                }
            ],
        )
        raw_text = response.content[0].text
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            return {
                "importance": "medium",
                "scope": "unknown",
                "sectors_affected": [],
                "rationale": raw_text,
            }

    def _parse_chain(self, raw_text: str, source_event: str) -> ReasoningChain:
        """LLM出力JSONをReasoningChainに変換する"""
        # コードブロックが混入した場合のフォールバック
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                line for line in lines
                if not line.startswith("```")
            ).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 末尾が切れている場合、impacts配列の閉じ括弧を補完して再試行
            fixed = text.rstrip().rstrip(",")
            for suffix in ["]}", "\n]}", "\n  ]\n}"]:
                try:
                    data = json.loads(fixed + suffix)
                    break
                except json.JSONDecodeError:
                    continue
            else:
                raise

        impacts = [
            ImpactNode(
                level=item["level"],
                sector=item["sector"],
                description=item["description"],
                direction=item["direction"],
                intensity=item["intensity"],
                rationale=item["rationale"],
                example_companies=item.get("example_companies", []),
                keywords=item.get("keywords", []),
                parent_sectors=item.get("parent_sectors", []),
                # 定量予測フィールド (旧フォーマットでは欠落する可能性があるため get)
                expected_return_pct_low=_to_float_or_none(item.get("expected_return_pct_low")),
                expected_return_pct_high=_to_float_or_none(item.get("expected_return_pct_high")),
                time_horizon=_validate_horizon(item.get("time_horizon")),
                probability=_to_float_or_none(item.get("probability")),
                investment_timing=_validate_investment_timing(item.get("investment_timing")),
                timing_rationale=_to_str_or_none(item.get("timing_rationale")),
                manifestation_timing=_validate_in(item.get("manifestation_timing"), _VALID_MANIFESTATIONS),
                duration=_validate_in(item.get("duration"), _VALID_DURATIONS),
                price_reaction_timing=_validate_in(item.get("price_reaction_timing"), _VALID_PRICE_REACTIONS),
                earnings_reflection=_validate_in(item.get("earnings_reflection"), _VALID_EARNINGS_REFLECTIONS),
                historical_analogues=_parse_analogues(item.get("historical_analogues")),
            )
            for item in data.get("impacts", [])
            if item.get("level", 0) <= self.max_levels
        ]

        return ReasoningChain(
            event_summary=data.get("event_summary", source_event[:80]),
            event_type=data.get("event_type", "other"),
            confidence=float(data.get("confidence", 0.7)),
            impacts=impacts,
            generated_at=datetime.now(timezone.utc).isoformat(),
            source_event=source_event,
        )
