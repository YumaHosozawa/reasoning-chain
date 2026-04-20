"""
SQLAlchemy ORM モデル

推論チェーン分析の結果を SQLite に永続化する。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AnalysisResult(Base):
    """推論チェーン分析結果テーブル"""

    __tablename__ = "analysis_results"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    event_text: Mapped[str] = mapped_column(Text, nullable=False)
    event_summary: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    # 推論チェーン全体をJSONで保存
    chain_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    # マッチング企業リストをJSONで保存（空リストの場合もあり）
    matches_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # 統計サマリ
    total_impacts: Mapped[int] = mapped_column(nullable=False, default=0)
    total_matches: Mapped[int] = mapped_column(nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ------------------------------------------------------------------
    # 実績検証 (outcome validation) 用カラム
    # ------------------------------------------------------------------

    # "pending" | "validated" | "expired" (予測ウィンドウ経過前は pending)
    validation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )

    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    # RealizedMetrics の JSON ダンプ (brier_score / mae_return / coverage_rate / per_match)
    realized_metrics_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, default=None
    )


class CompanyContextRecord(Base):
    """企業の定性情報コンテキスト（決算短信・中計・IRニュース等）"""

    __tablename__ = "company_contexts"
    __table_args__ = (
        Index("ix_company_contexts_code", "company_code"),
        Index("ix_company_contexts_code_type", "company_code", "context_type"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    company_code: Mapped[str] = mapped_column(String(10), nullable=False)
    context_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    published_date: Mapped[str] = mapped_column(String(30), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
