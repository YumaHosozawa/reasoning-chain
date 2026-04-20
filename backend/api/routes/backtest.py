"""
バックテスト API エンドポイント

GET  /api/backtest/events   — プリセットイベント一覧
POST /api/backtest/run      — 指定イベントで検証実行
POST /api/backtest/run-all  — 全プリセットを一括実行
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.backtest.evaluator import BACKTEST_EVENTS, BacktestEvaluator
from src.chain.generator import ReasoningChainGenerator
from src.matching.matcher import CompanyMatcher

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


# ---------------------------------------------------------------------------
# スキーマ
# ---------------------------------------------------------------------------

class PresetEvent(BaseModel):
    name: str
    event_date: str
    description: str
    ground_truth_sectors_positive: list[str]
    ground_truth_sectors_negative: list[str]


class LevelAccuracyResponse(BaseModel):
    level: int
    precision: float
    recall: float
    f1: float


class BacktestResult(BaseModel):
    event: str
    event_date: str
    chain_precision: float
    chain_recall: float
    chain_f1: float
    positive_hit_rate: float
    negative_hit_rate: float
    top10_return: float
    ground_truth_window: int
    level_accuracy: list[LevelAccuracyResponse]


class RunRequest(BaseModel):
    event: str = Field(..., min_length=5)
    event_date: str = Field(..., description="ISO 8601 形式")
    ground_truth_sectors_positive: list[str] = Field(default_factory=list)
    ground_truth_sectors_negative: list[str] = Field(default_factory=list)
    ground_truth_window: int = Field(default=30, ge=1, le=365)


class RunPresetRequest(BaseModel):
    name: str = Field(..., description="プリセットイベント名")
    ground_truth_window: int = Field(default=30, ge=1, le=365)


# ---------------------------------------------------------------------------
# エンドポイント
# ---------------------------------------------------------------------------

@router.get("/events", response_model=list[PresetEvent])
def list_events():
    """プリセットイベント一覧を返す。"""
    return [PresetEvent(**e) for e in BACKTEST_EVENTS]


@router.post("/run", response_model=BacktestResult)
async def run_backtest(request: RunRequest):
    """指定イベントでバックテストを実行する。"""
    evaluator = _get_evaluator()
    try:
        metrics = await asyncio.to_thread(
            evaluator.evaluate,
            event=request.event,
            event_date=request.event_date,
            ground_truth_positive_sectors=request.ground_truth_sectors_positive,
            ground_truth_negative_sectors=request.ground_truth_sectors_negative,
            ground_truth_window=request.ground_truth_window,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"バックテスト実行エラー: {e}")

    return _metrics_to_response(metrics)


@router.post("/run-preset", response_model=BacktestResult)
async def run_preset(request: RunPresetRequest):
    """プリセット名を指定してバックテストを実行する。"""
    event_def = next(
        (e for e in BACKTEST_EVENTS if e["name"] == request.name), None
    )
    if event_def is None:
        raise HTTPException(status_code=404, detail=f"プリセット '{request.name}' が見つかりません")

    evaluator = _get_evaluator()
    try:
        metrics = await asyncio.to_thread(
            evaluator.evaluate,
            event=event_def["description"],
            event_date=event_def["event_date"],
            ground_truth_positive_sectors=event_def["ground_truth_sectors_positive"],
            ground_truth_negative_sectors=event_def["ground_truth_sectors_negative"],
            ground_truth_window=request.ground_truth_window,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"バックテスト実行エラー: {e}")

    return _metrics_to_response(metrics)


@router.post("/run-all", response_model=list[BacktestResult])
async def run_all(ground_truth_window: int = 30):
    """全プリセットイベントを一括実行する。"""
    evaluator = _get_evaluator()
    try:
        all_metrics = await asyncio.to_thread(
            evaluator.evaluate_all_preset_events,
            ground_truth_window=ground_truth_window,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"一括バックテスト実行エラー: {e}")

    return [_metrics_to_response(m) for m in all_metrics]


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _get_evaluator() -> BacktestEvaluator:
    from backend.db.session import SessionLocal

    generator = ReasoningChainGenerator(
        model=os.environ.get("CHAIN_MODEL", "claude-sonnet-4-6"),
    )
    matcher = CompanyMatcher(
        score_threshold=float(os.environ.get("SCORE_THRESHOLD", "0.6")),
        use_redis_cache=False,
        db_session_factory=SessionLocal,
    )
    return BacktestEvaluator(generator=generator, matcher=matcher)


def _metrics_to_response(metrics) -> BacktestResult:
    level_accuracy = [
        LevelAccuracyResponse(level=level, **asdict(acc))
        for level, acc in sorted(metrics.level_accuracy.items())
    ]
    return BacktestResult(
        event=metrics.event,
        event_date=metrics.event_date,
        chain_precision=metrics.chain_precision,
        chain_recall=metrics.chain_recall,
        chain_f1=metrics.chain_f1,
        positive_hit_rate=metrics.positive_hit_rate,
        negative_hit_rate=metrics.negative_hit_rate,
        top10_return=metrics.top10_return,
        ground_truth_window=metrics.ground_truth_window,
        level_accuracy=level_accuracy,
    )
