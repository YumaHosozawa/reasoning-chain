"""
Pydantic スキーマ（APIリクエスト/レスポンス）
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# リクエスト
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    event: str = Field(..., min_length=5, max_length=1000, description="マクロ経済イベントの説明")
    max_levels: int = Field(default=4, ge=1, le=4)
    top_n: int = Field(default=80, ge=1, le=300, description="表示企業数の全体上限")
    top_n_per_impact: int = Field(
        default=8,
        ge=1,
        le=30,
        description="各影響ノードあたりの最大表示企業数",
    )
    score_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    chain_only: bool = Field(default=False, description="推論チェーン生成のみ（企業マッチングをスキップ）")
    strategy: str = Field(default="default", description="マッチング戦略名 (default / small_cap_first / diversity)")


# ---------------------------------------------------------------------------
# DB保存用
# ---------------------------------------------------------------------------

class AnalysisResultCreate(BaseModel):
    event_text: str
    event_summary: str
    event_type: str
    confidence: float
    chain_json: dict[str, Any]
    matches_json: list[dict[str, Any]]
    total_impacts: int
    total_matches: int


# ---------------------------------------------------------------------------
# レスポンス
# ---------------------------------------------------------------------------

class ImpactNodeResponse(BaseModel):
    level: int
    sector: str
    parent_sectors: list[str] = []
    description: str
    direction: str
    intensity: str
    rationale: str
    example_companies: list[str]
    keywords: list[str]
    # 定量予測フィールド (予測モデル化のため追加・旧データでは null になる)
    expected_return_pct_low: float | None = None
    expected_return_pct_high: float | None = None
    time_horizon: str | None = None
    probability: float | None = None


class CompanyMatchResponse(BaseModel):
    company_code: str
    company_name: str
    impact_level: int
    impact_sector: str = ""
    impact_description: str = ""
    direction: str
    final_score: float
    vector_similarity: float
    llm_relevance_score: float
    segment_exposure_ratio: float
    affected_segments: list[str]
    rationale: str
    intensity: str
    # 定量予測フィールド (旧データでは null)
    expected_return_pct: float | None = None
    time_horizon: str | None = None
    prediction_window_days: int | None = None
    probability: float | None = None
    # 企業コンテキスト (最近の動向)
    company_context: str | None = None


class AnalyzeResponse(BaseModel):
    id: str
    event_summary: str
    event_type: str
    confidence: float
    generated_at: str
    impacts: list[ImpactNodeResponse]
    matches: list[CompanyMatchResponse]
    total_impacts: int
    total_matches: int
    db_ready: bool = True  # Falseのとき企業DBが未構築


class ResultSummary(BaseModel):
    id: str
    event_text: str
    event_summary: str
    event_type: str
    confidence: float
    total_impacts: int
    total_matches: int
    created_at: datetime

    class Config:
        from_attributes = True


class ResultDetail(ResultSummary):
    chain_json: dict[str, Any]
    matches_json: list[dict[str, Any]]


class ResultListResponse(BaseModel):
    total: int
    results: list[ResultSummary]
