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
from collections import defaultdict
from typing import Any, Sequence

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
from src.matching.strategy import MatchingStrategy, get_strategy
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
        top_k_segments: int | None = None,
        max_per_industry: int | None = None,
        score_threshold: float | None = None,
        use_redis_cache: bool = True,
        db_session_factory: Any | None = None,
        strategy: str | None = None,
    ) -> None:
        self._embedder = embedder or Embedder()
        self._vector_store = vector_store or VectorStore()
        # 証券コード → CompanyProfile の辞書（LLMスコアリング用）
        self._profiles: dict[str, CompanyProfile] = company_profiles or {}
        self._top_k = top_k_per_impact or int(
            os.environ.get("TOP_K_PER_IMPACT", "100")
        )
        self._top_k_segments = top_k_segments or int(
            os.environ.get("TOP_K_SEGMENTS", "60")
        )
        self._max_llm_candidates = int(
            os.environ.get("MAX_LLM_CANDIDATES", "80")
        )
        self._vector_score_threshold = float(
            os.environ.get("VECTOR_SCORE_THRESHOLD", "0.1")
        )
        strategy_name = strategy or os.environ.get("MATCHING_STRATEGY", "default")
        self._strategy: MatchingStrategy = get_strategy(strategy_name)
        # 戦略固有の業種キャップがあればそちらを優先
        strategy_cap = self._strategy.max_per_industry
        self._max_per_industry = strategy_cap or max_per_industry or int(
            os.environ.get("MAX_PER_INDUSTRY", "8")
        )
        self._threshold = score_threshold or float(
            os.environ.get("SCORE_THRESHOLD", "0.6")
        )
        self._db_factory = db_session_factory
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
          2. 企業全体 + セグメント単位のベクトル検索 → union
          3. 業種多様性キャップ
          4. LLM スコアリングを並列実行
          5. final_score 計算 → 閾値フィルタリング
        """
        # Step 1: 埋め込みベクトル生成
        impact_vector = self._embedder.embed_impact(
            impact.description, impact.keywords
        )

        # Step 2: 企業全体 + セグメント単位の二段検索
        hits_full = self._vector_store.search(
            query_vector=impact_vector,
            top_k=self._top_k,
            score_threshold=self._vector_score_threshold,
        )
        hits_seg = self._vector_store.search_segments(
            query_vector=impact_vector,
            top_k=self._top_k_segments,
            score_threshold=self._vector_score_threshold,
        )
        hits = self._merge_hits(hits_full, hits_seg)

        if not hits:
            return []

        # Step 3: 戦略によるリランク
        hits = self._strategy.rerank(hits)

        # Step 3.5: 業種多様性キャップ
        hits = self._cap_per_industry(hits)

        # Step 3.5: LLM コスト制御のためのプリフィルタ
        hits = self._prefilter(hits)

        # Step 4: 企業コンテキストのバッチ取得
        company_codes = [h["company_code"] for h in hits]
        context_map = self._load_contexts_batch(company_codes)

        # Step 5: LLM スコアリングを並列実行
        scoring_tasks = [
            self._score_company_async(
                impact,
                hit,
                hit["vector_score"],
                company_context=context_map.get(hit["company_code"], ""),
            )
            for hit in hits
        ]
        scored = await asyncio.gather(*scoring_tasks)

        # Step 6: 閾値フィルタリング
        results = [r for r in scored if r is not None and r.final_score >= self._threshold]
        results.sort(key=lambda r: r.final_score, reverse=True)
        return results

    def _merge_hits(
        self,
        hits_full: list,
        hits_seg: list,
    ) -> list[dict]:
        """
        企業全体検索とセグメント検索の結果を company_code ベースで union する。
        重複はスコアの max を採用。
        """
        merged: dict[str, dict] = {}

        for hit in hits_full:
            if not hit.payload:
                continue
            code = hit.payload.get("company_code", "")
            if not code:
                continue
            merged[code] = {
                "company_code": code,
                "company_name": hit.payload.get("company_name", ""),
                "industry_code": hit.payload.get("industry_code", ""),
                "vector_score": hit.score,
                "matched_segment_name": None,
            }

        for hit in hits_seg:
            if not hit.payload:
                continue
            code = hit.payload.get("company_code", "")
            if not code:
                continue
            if code in merged:
                if hit.score > merged[code]["vector_score"]:
                    merged[code]["vector_score"] = hit.score
                    merged[code]["matched_segment_name"] = hit.payload.get("segment_name")
            else:
                merged[code] = {
                    "company_code": code,
                    "company_name": hit.payload.get("company_name", ""),
                    "industry_code": hit.payload.get("industry_code", ""),
                    "vector_score": hit.score,
                    "matched_segment_name": hit.payload.get("segment_name"),
                }

        return list(merged.values())

    def _cap_per_industry(self, hits: list[dict]) -> list[dict]:
        """同一業種コードの企業を上位 max_per_industry 件に制限し、多様性を確保する。

        strategy が出した順序を尊重し、各業種につき先着順で max_per_industry 件まで残す。
        （以前は業種内で vector_score 降順に再ソートしており、small_cap_first /
        diversity / mix-band な default が事実上無効化されていた）
        """
        counts: dict[str, int] = defaultdict(int)
        capped: list[dict] = []
        for h in hits:
            code = h.get("industry_code", "")
            if counts[code] < self._max_per_industry:
                capped.append(h)
                counts[code] += 1
        return capped

    def _prefilter(self, hits: list[dict]) -> list[dict]:
        """
        候補数が _max_llm_candidates を超える場合、strategy が出した順序の
        先頭から LLM スコアリング枠まで切り詰める。
        """
        if len(hits) <= self._max_llm_candidates:
            return hits
        return hits[: self._max_llm_candidates]

    def _load_contexts_batch(self, company_codes: list[str]) -> dict[str, str]:
        """企業コンテキストをバッチ取得してフォーマット済みテキストの dict を返す。"""
        if not self._db_factory or not company_codes:
            return {}
        try:
            from backend.db.crud import get_contexts_batch

            session = self._db_factory()
            try:
                batch = get_contexts_batch(session, company_codes)
                result: dict[str, str] = {}
                for code, records in batch.items():
                    lines = []
                    for r in records[:5]:
                        lines.append(f"・{r.published_date} {r.title}: {r.summary}")
                    if lines:
                        result[code] = "\n".join(lines)
                return result
            finally:
                session.close()
        except Exception:
            return {}

    async def _score_company_async(
        self,
        impact: ImpactNode,
        payload: dict,
        vector_similarity: float,
        company_context: str = "",
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
                company_context=company_context,
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
            impact_sector=impact.sector,
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
            company_context=company_context or None,
            investment_timing=impact.investment_timing,
            timing_rationale=impact.timing_rationale,
            manifestation_timing=impact.manifestation_timing,
            duration=impact.duration,
            price_reaction_timing=impact.price_reaction_timing,
            earnings_reflection=impact.earnings_reflection,
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
        company_context: str = "",
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
                        company_context=company_context or "最近の情報なし",
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
