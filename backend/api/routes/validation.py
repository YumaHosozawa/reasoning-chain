"""
予測の実績検証エンドポイント。

POST /api/validation/run         - pending な予測を一括検証
POST /api/validation/{id}/run    - 指定IDを強制検証
GET  /api/validation/summary     - キャリブレーションダッシュボード用の集計
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import AnalysisResult
from backend.db.session import get_db
from src.validation.outcome_tracker import sweep_pending, validate_result


router = APIRouter(prefix="/api/validation", tags=["validation"])


# ---------------------------------------------------------------------------
# レスポンススキーマ
# ---------------------------------------------------------------------------

class SweepResponse(BaseModel):
    validated_ids: list[str]
    count: int
    swept_at: str


class ValidateOneResponse(BaseModel):
    id: str
    brier_score: float | None
    mae_return: float | None
    coverage_rate: float | None
    n_matches: int
    n_with_return: int


class ReliabilityBin(BaseModel):
    bin_lower: float
    bin_upper: float
    mean_predicted: float | None
    realized_frequency: float | None
    count: int


class HorizonMAE(BaseModel):
    time_horizon: str
    mae_return: float
    count: int


class SummaryResponse(BaseModel):
    validated_count: int
    pending_count: int
    overall_coverage_rate: float | None
    overall_mae_return: float | None
    rolling_brier: float | None
    reliability_bins: list[ReliabilityBin]
    mae_by_horizon: list[HorizonMAE]


# ---------------------------------------------------------------------------
# エンドポイント
# ---------------------------------------------------------------------------

@router.post("/run", response_model=SweepResponse)
def run_sweep(
    limit: int | None = Query(default=None, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """pending 状態で予測ウィンドウを経過した行を一括検証する。"""
    now = datetime.now(timezone.utc)
    ids = sweep_pending(db, now=now, limit=limit)
    return SweepResponse(
        validated_ids=ids,
        count=len(ids),
        swept_at=now.isoformat(),
    )


@router.post("/{result_id}/run", response_model=ValidateOneResponse)
def run_one(result_id: str, db: Session = Depends(get_db)):
    """指定 result_id を即時検証 (ウィンドウ未経過でも強制実行)。"""
    record = db.get(AnalysisResult, result_id)
    if record is None:
        raise HTTPException(status_code=404, detail="result not found")

    metrics = validate_result(record, db)
    db.commit()
    return ValidateOneResponse(
        id=record.id,
        brier_score=metrics.brier_score,
        mae_return=metrics.mae_return,
        coverage_rate=metrics.coverage_rate,
        n_matches=metrics.n_matches,
        n_with_return=metrics.n_with_return,
    )


@router.get("/summary", response_model=SummaryResponse)
def summary(
    last_n: int = Query(default=100, ge=1, le=1000),
    horizon: str | None = Query(default=None, description="特定 horizon に絞り込む"),
    db: Session = Depends(get_db),
):
    """
    キャリブレーションダッシュボード用の集計を返す。

    - reliability diagram 用に probability を 10 bin に分割し、bin 内の平均予測確率と
      実現率 (directional_hit の割合) を返す
    - coverage_rate, MAE, rolling Brier の全体平均を返す
    - horizon 別 MAE をリストで返す
    """
    validated_stmt = (
        select(AnalysisResult)
        .where(AnalysisResult.validation_status == "validated")
        .order_by(AnalysisResult.validated_at.desc())
        .limit(last_n)
    )
    validated = db.execute(validated_stmt).scalars().all()
    pending_count = db.execute(
        select(AnalysisResult).where(AnalysisResult.validation_status == "pending")
    ).scalars().all()

    # Reliability bin: [0.0,0.1) ... [0.9,1.0]
    bin_count = 10
    bins_pred: list[list[float]] = [[] for _ in range(bin_count)]
    bins_hit: list[list[int]] = [[] for _ in range(bin_count)]

    coverage_flags: list[bool] = []
    abs_errors: list[float] = []
    brier_terms: list[float] = []
    per_horizon_errors: dict[str, list[float]] = defaultdict(list)

    for r in validated:
        metrics = r.realized_metrics_json or {}
        for m in metrics.get("per_match", []):
            if horizon is not None and m.get("time_horizon") != horizon:
                continue

            realized = m.get("realized_return_pct")
            expected_point = m.get("expected_return_pct")
            probability = m.get("probability")
            directional_hit = m.get("directional_hit")
            in_range = m.get("in_range")
            horizon_str = m.get("time_horizon")

            if realized is not None and expected_point is not None:
                err = abs(float(realized) - float(expected_point))
                abs_errors.append(err)
                if horizon_str:
                    per_horizon_errors[horizon_str].append(err)

            if in_range is not None:
                coverage_flags.append(bool(in_range))

            if probability is not None and directional_hit is not None:
                p = float(probability)
                hit = 1.0 if directional_hit else 0.0
                brier_terms.append((p - hit) ** 2)
                idx = min(int(p * bin_count), bin_count - 1)
                bins_pred[idx].append(p)
                bins_hit[idx].append(int(hit))

    reliability_bins: list[ReliabilityBin] = []
    for i in range(bin_count):
        lo = i / bin_count
        hi = (i + 1) / bin_count
        count = len(bins_pred[i])
        reliability_bins.append(
            ReliabilityBin(
                bin_lower=lo,
                bin_upper=hi,
                mean_predicted=(sum(bins_pred[i]) / count) if count else None,
                realized_frequency=(sum(bins_hit[i]) / count) if count else None,
                count=count,
            )
        )

    mae_by_horizon = [
        HorizonMAE(
            time_horizon=h,
            mae_return=sum(errs) / len(errs),
            count=len(errs),
        )
        for h, errs in sorted(per_horizon_errors.items())
    ]

    return SummaryResponse(
        validated_count=len(validated),
        pending_count=len(pending_count),
        overall_coverage_rate=(
            sum(1 for f in coverage_flags if f) / len(coverage_flags)
            if coverage_flags
            else None
        ),
        overall_mae_return=(
            sum(abs_errors) / len(abs_errors) if abs_errors else None
        ),
        rolling_brier=(
            sum(brier_terms) / len(brier_terms) if brier_terms else None
        ),
        reliability_bins=reliability_bins,
        mae_by_horizon=mae_by_horizon,
    )
