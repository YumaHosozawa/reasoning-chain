"""
CRUD操作
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from backend.db.models import AnalysisResult, CompanyContextRecord
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


# ---------------------------------------------------------------------------
# CompanyContext CRUD
# ---------------------------------------------------------------------------


def upsert_company_context(
    db: Session,
    company_code: str,
    context_type: str,
    title: str,
    summary: str,
    source_url: str,
    published_date: str,
) -> CompanyContextRecord:
    """company_code + context_type + published_date で upsert する。"""
    existing = db.execute(
        select(CompanyContextRecord).where(
            and_(
                CompanyContextRecord.company_code == company_code,
                CompanyContextRecord.context_type == context_type,
                CompanyContextRecord.published_date == published_date,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.title = title
        existing.summary = summary
        existing.source_url = source_url
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    record = CompanyContextRecord(
        company_code=company_code,
        context_type=context_type,
        title=title,
        summary=summary,
        source_url=source_url,
        published_date=published_date,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_company_contexts(
    db: Session,
    company_code: str,
    limit: int = 5,
) -> list[CompanyContextRecord]:
    """指定企業の最新 N 件のコンテキストを返す。"""
    return (
        db.query(CompanyContextRecord)
        .filter(CompanyContextRecord.company_code == company_code)
        .order_by(CompanyContextRecord.published_date.desc())
        .limit(limit)
        .all()
    )


def get_contexts_batch(
    db: Session,
    company_codes: list[str],
    limit_per_company: int = 5,
) -> dict[str, list[CompanyContextRecord]]:
    """複数企業のコンテキストをまとめて取得する。"""
    if not company_codes:
        return {}

    rows = (
        db.query(CompanyContextRecord)
        .filter(CompanyContextRecord.company_code.in_(company_codes))
        .order_by(
            CompanyContextRecord.company_code,
            CompanyContextRecord.published_date.desc(),
        )
        .all()
    )

    result: dict[str, list[CompanyContextRecord]] = defaultdict(list)
    for row in rows:
        if len(result[row.company_code]) < limit_per_company:
            result[row.company_code].append(row)
    return dict(result)
