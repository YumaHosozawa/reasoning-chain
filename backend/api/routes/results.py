"""
結果一覧・詳細エンドポイント

GET /api/results          - 過去の分析結果一覧
GET /api/results/{id}     - 分析結果詳細
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.api.schemas import ResultDetail, ResultListResponse, ResultSummary
from backend.db.session import get_db
from backend.db import crud

router = APIRouter(prefix="/api/results", tags=["results"])


@router.get("", response_model=ResultListResponse)
def list_results(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """過去の分析結果一覧を返す（新しい順）"""
    total = crud.count_results(db)
    results = crud.list_results(db, skip=skip, limit=limit)
    return ResultListResponse(
        total=total,
        results=[ResultSummary.model_validate(r) for r in results],
    )


@router.get("/{result_id}", response_model=ResultDetail)
def get_result(result_id: str, db: Session = Depends(get_db)):
    """指定IDの分析結果詳細を返す"""
    record = crud.get_result(db, result_id)
    if record is None:
        raise HTTPException(status_code=404, detail="結果が見つかりません")
    return ResultDetail.model_validate(record)
