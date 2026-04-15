"""
企業マッチングエンジン

推論チェーンの各影響ノードに対して、
ベクトル検索 + LLMスコアリング + セグメント構成比の3軸で
関連企業をスコアリングする。
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Sequence

import anthropic
import redis
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, anthropic.RateLimitError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code >= 500
    return False

from src.models import (
    CompanyMatchResult,
    CompanyProfile,
    ImpactNode,
    ReasoningChain,
    horizon_to_days,
)
from src.matching.embedder import Embedder
from src.matching.vector_store import VectorStore
from src.chain.prompt_templates import (
    RELEVANCE_SCORING_SYSTEM,
    RELEVANCE_SCORING_USER,
)

# スコアリングの重み（合計 = 1.0）
_W_VECTOR = 0.35
_W_LLM = 0.40
_W_SEGMENT = 0.25

# Redisキャッシュの有効期間（秒）= 24時間
_CACHE_TTL = 86400


class CompanyMatcher:
    """推論チェーンと企業プロファイルをマッチングするクラス"""

    def __init__(
        self,
        embedder: Embedder | None = None,
        vector_store: VectorStore | None = None,
        company_profiles: dict[str, CompanyProfile] | None = None,
        top_k_per_impact: int | None = None,
        score_threshold: float | None = None,
        use_redis_cache: bool = True,
    ) -> None:
        self._embedder = embedder or Embedder()
        self._vector_store = vector_store or VectorStore()
        # 証券コード → CompanyProfile の辞書（LLMスコアリング用）
        self._profiles: dict[str, CompanyProfile] = company_profiles or {}
        self._top_k = top_k_per_impact or int(
            os.environ.get("TOP_K_PER_IMPACT", "20")
        )
        self._threshold = score_threshold or float(
            os.environ.get("SCORE_THRESHOLD", "0.6")
        )
        self._llm = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )
        self._scoring_model = os.environ.get(
            "SCORING_MODEL", "claude-haiku-4-5-20251001"
        )

        self._redis: redis.Redis | None = None
        if use_redis_cache:
            try:
                self._redis = redis.from_url(
                    os.environ.get("REDIS_URL", "redis://localhost:6379/0")
                )
                self._redis.ping()
            except Exception:
                self._redis = None

    # ------------------------------------------------------------------
    # パブリックAPI
    # ------------------------------------------------------------------

    def is_db_ready(self) -> bool:
        """Qdrantに企業データが1件以上登録されているか確認する"""
        try:
            return self._vector_store.count() > 0
        except Exception:
            return False

    def match(self, chain: ReasoningChain) -> list[CompanyMatchResult]:
        """
        推論チェーン全体に対して企業マッチングを実行する。

        各ImpactNodeを並列処理し、全結果をfinal_scoreの降順で返す。
        Qdrantが未構築の場合は空リストを返す。

        Returns:
            list[CompanyMatchResult]: スコア付き企業リスト（閾値以上のみ）
        """
        if not self.is_db_ready():
            return []
        return asyncio.run(self._match_async(chain))

    async def _match_async(self, chain: ReasoningChain) -> list[CompanyMatchResult]:
        tasks = [
            self._match_impact_async(impact)
            for impact in chain.impacts
        ]
        nested = await asyncio.gather(*tasks)
        all_results: list[CompanyMatchResult] = []
        for results in nested:
            all_results.extend(results)

        # final_scoreの降順でソート
        all_results.sort(key=lambda r: r.final_score, reverse=True)
        return all_results

    def match_impact(self, impact: ImpactNode) -> list[CompanyMatchResult]:
        """単一の影響ノードに対して企業をマッチングする"""
        return asyncio.run(self._match_impact_async(impact))

    # ------------------------------------------------------------------
    # 内部処理
    # ------------------------------------------------------------------

    async def _match_impact_async(
        self, impact: ImpactNode
    ) -> list[CompanyMatchResult]:
        """
        影響ノード1件に対するマッチングフロー:
          1. 影響テキストをベクトル化
          2. ベクトルDB で top_k 検索
          3. LLM スコアリングを並列実行
          4. final_score 計算 → 閾値フィルタリング
        """
        # Step 1: 埋め込みベクトル生成
        impact_vector = self._embedder.embed_impact(
            impact.description, impact.keywords
        )

        # Step 2: ベクトル検索
        hits = self._vector_store.search(
            query_vector=impact_vector,
            top_k=self._top_k,
        )

        if not hits:
            return []

        # Step 3: LLM スコアリングを並列実行
        scoring_tasks = [
            self._score_company_async(impact, hit.payload, hit.score)
            for hit in hits
            if hit.payload
        ]
        scored = await asyncio.gather(*scoring_tasks)

        # Step 4: 閾値フィルタリング
        results = [r for r in scored if r is not None and r.final_score >= self._threshold]
        results.sort(key=lambda r: r.final_score, reverse=True)
        return results

    async def _score_company_async(
        self,
        impact: ImpactNode,
        payload: dict,
        vector_similarity: float,
    ) -> CompanyMatchResult | None:
        """
        1企業の LLMスコアリングを実行し CompanyMatchResult を返す。
        Redisキャッシュがあればキャッシュから返す。
        """
        company_code = payload.get("company_code", "")
        company_name = payload.get("company_name", "")

        # キャッシュキー
        cache_key = f"llm_score:{impact.description[:80]}:{company_code}"
        cached = self._get_cache(cache_key)

        if cached is not None:
            llm_score = cached["score"]
            reason = cached["reason"]
            affected_segments = cached["affected_segments"]
        else:
            profile = self._profiles.get(company_code)
            biz_desc = profile.business_description[:800] if profile else ""
            segments_summary = _format_segments(profile) if profile else ""

            llm_result = await self._call_llm_scoring(
                impact=impact,
                company_name=company_name,
                company_code=company_code,
                business_description=biz_desc,
                segments_summary=segments_summary,
            )
            llm_score = llm_result.get("score", 0.0)
            reason = llm_result.get("reason", "")
            affected_segments = llm_result.get("affected_segments", [])

            self._set_cache(cache_key, {"score": llm_score, "reason": reason, "affected_segments": affected_segments})

        # セグメント構成比の取得
        segment_exposure = self._get_segment_exposure(
            company_code, affected_segments
        )

        # final_score 計算
        final_score = (
            vector_similarity * _W_VECTOR
            + llm_score * _W_LLM
            + segment_exposure * _W_SEGMENT
        )

        # 定量予測値の伝播: 親ImpactNode のレンジ中央値 × segment 露出で希釈
        expected_return_pct: float | None = None
        if (
            impact.expected_return_pct_low is not None
            and impact.expected_return_pct_high is not None
        ):
            midpoint = (
                impact.expected_return_pct_low + impact.expected_return_pct_high
            ) / 2.0
            expected_return_pct = round(midpoint * segment_exposure, 4)

        prediction_window_days = (
            horizon_to_days(impact.time_horizon)
            if impact.time_horizon is not None
            else None
        )

        return CompanyMatchResult(
            company_code=company_code,
            company_name=company_name,
            impact_level=impact.level,
            impact_description=impact.description,
            direction=impact.direction,
            final_score=round(final_score, 4),
            vector_similarity=round(vector_similarity, 4),
            llm_relevance_score=round(llm_score, 4),
            segment_exposure_ratio=round(segment_exposure, 4),
            affected_segments=affected_segments,
            rationale=reason,
            intensity=impact.intensity,
            expected_return_pct=expected_return_pct,
            time_horizon=impact.time_horizon,
            prediction_window_days=prediction_window_days,
            probability=impact.probability,
        )

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=5),
        reraise=True,
    )
    async def _call_llm_scoring(
        self,
        impact: ImpactNode,
        company_name: str,
        company_code: str,
        business_description: str,
        segments_summary: str,
    ) -> dict:
        """Haiku API を呼び出してスコアリングJSONを取得する"""
        async_client = anthropic.AsyncAnthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )
        response = await async_client.messages.create(
            model=self._scoring_model,
            max_tokens=256,
            system=RELEVANCE_SCORING_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": RELEVANCE_SCORING_USER.format(
                        impact_description=impact.description,
                        direction=impact.direction,
                        intensity=impact.intensity,
                        keywords=", ".join(impact.keywords),
                        company_name=company_name,
                        company_code=company_code,
                        business_description=business_description,
                        segments_summary=segments_summary,
                    ),
                }
            ],
        )
        raw = response.content[0].text.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"score": 0.0, "reason": raw[:200], "affected_segments": []}

    def _get_segment_exposure(
        self, company_code: str, affected_segments: list[str]
    ) -> float:
        """
        指定セグメントの合計売上構成比を返す。

        プロファイルが存在しない場合や、影響セグメントが未指定の場合は 0.5 を返す。
        """
        profile = self._profiles.get(company_code)
        if not profile or not profile.segments:
            return 0.5  # プロファイル不明の場合はデフォルト値

        if not affected_segments:
            return 0.3  # セグメント不明は低めのデフォルト値

        total_ratio = 0.0
        for seg in profile.segments:
            for affected in affected_segments:
                if affected.lower() in seg.name.lower() or seg.name.lower() in affected.lower():
                    total_ratio += seg.revenue_ratio
                    break

        return min(total_ratio, 1.0)

    # ------------------------------------------------------------------
    # Redisキャッシュ
    # ------------------------------------------------------------------

    def _get_cache(self, key: str) -> dict | None:
        if self._redis is None:
            return None
        try:
            value = self._redis.get(key)
            if value:
                return json.loads(value)
        except Exception:
            pass
        return None

    def _set_cache(self, key: str, value: dict) -> None:
        if self._redis is None:
            return
        try:
            self._redis.setex(key, _CACHE_TTL, json.dumps(value, ensure_ascii=False))
        except Exception:
            pass


# ------------------------------------------------------------------
# ヘルパー
# ------------------------------------------------------------------

def _format_segments(profile: CompanyProfile) -> str:
    """CompanyProfileのセグメントをサマリテキストに変換する"""
    if not profile.segments:
        return "セグメント情報なし"
    parts = []
    for seg in profile.segments[:5]:
        ratio_pct = int(seg.revenue_ratio * 100)
        parts.append(f"{seg.name}（{ratio_pct}%）")
    return " / ".join(parts)
