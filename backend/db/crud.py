"""
CRUD操作
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.db.models import AnalysisResult
from backend.api.schemas import AnalysisResultCreate


def create_result(db: Session, data: AnalysisResultCreate) -> AnalysisResult:
    record = AnalysisResult(
        event_text=data.event_text,
        event_summary=data.event_summary,
        event_type=data.event_type,
        confidence=data.confidence,
        chain_json=data.chain_json,
        matches_json=data.matches_json,
        total_impacts=data.total_impacts,
        total_matches=data.total_matches,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_results(
    db: Session, skip: int = 0, limit: int = 50
) -> list[AnalysisResult]:
    return (
        db.query(AnalysisResult)
        .order_by(AnalysisResult.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_result(db: Session, result_id: str) -> AnalysisResult | None:
    return db.query(AnalysisResult).filter(AnalysisResult.id == result_id).first()


def count_results(db: Session) -> int:
    return db.query(AnalysisResult).count()
