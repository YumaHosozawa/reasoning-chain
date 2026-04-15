"""
分析エンドポイント

POST /api/analyze       - 推論チェーン生成 + 企業マッチング
GET  /api/analyze/stream - SSEで推論チェーンをストリーミング生成
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    AnalysisResultCreate,
    ImpactNodeResponse,
    CompanyMatchResponse,
)
from backend.db.session import get_db
from backend.db import crud
from src.chain.generator import ReasoningChainGenerator
from src.matching.matcher import CompanyMatcher

router = APIRouter(prefix="/api/analyze", tags=["analyze"])


def _get_generator() -> ReasoningChainGenerator:
    return ReasoningChainGenerator(
        model=os.environ.get("CHAIN_MODEL", "claude-sonnet-4-6"),
    )


def _get_matcher() -> CompanyMatcher:
    return CompanyMatcher(
        score_threshold=float(os.environ.get("SCORE_THRESHOLD", "0.6")),
        use_redis_cache=False,
    )


@router.post("", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest, db: Session = Depends(get_db)):
    """
    マクロイベントを分析し、推論チェーンと影響企業を返す。
    結果はDBに保存される。
    """
    generator = _get_generator()

    try:
        chain = await asyncio.to_thread(generator.generate, request.event)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"推論チェーン生成エラー: {e}")

    matches = []
    db_ready = True
    if not request.chain_only:
        matcher = _get_matcher()
        try:
            db_ready = await asyncio.to_thread(matcher.is_db_ready)
            if db_ready:
                matches = await asyncio.to_thread(matcher.match, chain)
        except Exception:
            db_ready = False
            matches = []

    # レスポンス構築
    impact_responses = [
        ImpactNodeResponse(
            level=n.level,
            sector=n.sector,
            description=n.description,
            direction=n.direction,
            intensity=n.intensity,
            rationale=n.rationale,
            example_companies=n.example_companies,
            keywords=n.keywords,
            expected_return_pct_low=n.expected_return_pct_low,
            expected_return_pct_high=n.expected_return_pct_high,
            time_horizon=n.time_horizon,
            probability=n.probability,
        )
        for n in chain.impacts
    ]

    match_responses = [
        CompanyMatchResponse(
            company_code=m.company_code,
            company_name=m.company_name,
            impact_level=m.impact_level,
            direction=m.direction,
            final_score=m.final_score,
            vector_similarity=m.vector_similarity,
            llm_relevance_score=m.llm_relevance_score,
            segment_exposure_ratio=m.segment_exposure_ratio,
            affected_segments=m.affected_segments,
            rationale=m.rationale,
            intensity=m.intensity,
            expected_return_pct=m.expected_return_pct,
            time_horizon=m.time_horizon,
            prediction_window_days=m.prediction_window_days,
            probability=m.probability,
        )
        for m in matches[: request.top_n]
    ]

    # DB保存用にJSONシリアライズ
    chain_dict = {
        "event_summary": chain.event_summary,
        "event_type": chain.event_type,
        "confidence": chain.confidence,
        "generated_at": chain.generated_at,
        "source_event": chain.source_event,
        "impacts": [
            {
                "level": n.level,
                "sector": n.sector,
                "description": n.description,
                "direction": n.direction,
                "intensity": n.intensity,
                "rationale": n.rationale,
                "example_companies": n.example_companies,
                "keywords": n.keywords,
                "expected_return_pct_low": n.expected_return_pct_low,
                "expected_return_pct_high": n.expected_return_pct_high,
                "time_horizon": n.time_horizon,
                "probability": n.probability,
            }
            for n in chain.impacts
        ],
    }

    matches_list = [
        {
            "company_code": m.company_code,
            "company_name": m.company_name,
            "impact_level": m.impact_level,
            "impact_description": m.impact_description,
            "direction": m.direction,
            "final_score": m.final_score,
            "vector_similarity": m.vector_similarity,
            "llm_relevance_score": m.llm_relevance_score,
            "segment_exposure_ratio": m.segment_exposure_ratio,
            "affected_segments": m.affected_segments,
            "rationale": m.rationale,
            "intensity": m.intensity,
            "expected_return_pct": m.expected_return_pct,
            "time_horizon": m.time_horizon,
            "prediction_window_days": m.prediction_window_days,
            "probability": m.probability,
        }
        for m in matches[: request.top_n]
    ]

    record = crud.create_result(
        db,
        AnalysisResultCreate(
            event_text=request.event,
            event_summary=chain.event_summary,
            event_type=chain.event_type,
            confidence=chain.confidence,
            chain_json=chain_dict,
            matches_json=matches_list,
            total_impacts=len(chain.impacts),
            total_matches=len(matches),
        ),
    )

    return AnalyzeResponse(
        id=record.id,
        event_summary=chain.event_summary,
        event_type=chain.event_type,
        confidence=chain.confidence,
        generated_at=chain.generated_at,
        impacts=impact_responses,
        matches=match_responses,
        total_impacts=len(chain.impacts),
        total_matches=len(matches),
        db_ready=db_ready,
    )


@router.get("/stream")
async def analyze_stream(event: str):
    """
    SSEで推論チェーンをストリーミング生成する。

    使用例（curl）:
        curl -N "http://localhost:8000/api/analyze/stream?event=原油高騰"
    """
    if not event or len(event) < 5:
        raise HTTPException(status_code=422, detail="event パラメータが短すぎます")

    generator = _get_generator()

    async def event_stream():
        accumulated = ""
        try:
            async for chunk in generator.generate_stream(event):
                accumulated += chunk
                data = json.dumps({"type": "chunk", "text": chunk}, ensure_ascii=False)
                yield f"data: {data}\n\n"

            # 完了イベント
            done = json.dumps({"type": "done"}, ensure_ascii=False)
            yield f"data: {done}\n\n"

        except Exception as e:
            error = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
            yield f"data: {error}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
