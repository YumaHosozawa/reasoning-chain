"""
共通データモデル定義

推論チェーンシステム全体で使用するデータクラスを定義する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

# ---------------------------------------------------------------------------
# 時間軸 → 検証ウィンドウ (日数) のマッピング
#
# LLMが選択した time_horizon から、validation で使う株価観察ウィンドウを機械的
# に導出する。ここで「immediate」 = 1週間程度の即時反応、「3-12m」 = 9ヶ月を
# 代表値として扱う。
# ---------------------------------------------------------------------------

TimeHorizon = Literal["immediate", "1-4w", "1-3m", "3-12m"]

HORIZON_WINDOW_DAYS: dict[str, int] = {
    "immediate": 5,
    "1-4w": 28,
    "1-3m": 90,
    "3-12m": 270,
}


def horizon_to_days(horizon: str | None) -> int:
    """time_horizon 文字列を検証ウィンドウ日数に変換する。未知値は 1-3m 扱い。"""
    if horizon is None:
        return HORIZON_WINDOW_DAYS["1-3m"]
    return HORIZON_WINDOW_DAYS.get(horizon, HORIZON_WINDOW_DAYS["1-3m"])


# ---------------------------------------------------------------------------
# 推論チェーン
# ---------------------------------------------------------------------------

@dataclass
class ImpactNode:
    """推論チェーンの各影響ノード（一次/二次/三次/四次影響）"""

    level: int
    """影響レベル: 1=一次, 2=二次, 3=三次, 4=四次"""

    sector: str
    """影響を受けるセクター/業界"""

    description: str
    """影響の詳細説明"""

    direction: Literal["positive", "negative", "mixed"]
    """影響の方向性"""

    intensity: Literal["high", "medium", "low"]
    """影響の強さ"""

    rationale: str
    """因果関係の説明（なぜこの影響が生じるか）"""

    example_companies: list[str] = field(default_factory=list)
    """LLMが例示した企業名リスト"""

    keywords: list[str] = field(default_factory=list)
    """マッチング用キーワード"""

    embedding: list[float] | None = field(default=None, repr=False)
    """埋め込みベクトル（生成後に付与）"""

    # ------------------------------------------------------------------
    # 定量予測フィールド (予測モデル化のため追加)
    # ------------------------------------------------------------------

    expected_return_pct_low: float | None = None
    """代表企業における期待株価リターン下限 (例: -0.15 = -15%)"""

    expected_return_pct_high: float | None = None
    """代表企業における期待株価リターン上限 (例: -0.05 = -5%)"""

    time_horizon: TimeHorizon | None = None
    """影響が顕在化する時間軸。immediate / 1-4w / 1-3m / 3-12m"""

    probability: float | None = None
    """このインパクトが実現する確率 (0.0–1.0)。キャリブレーションの対象。"""


@dataclass
class ReasoningChain:
    """マクロイベントから生成された推論チェーン全体"""

    event_summary: str
    """イベントの要約"""

    event_type: Literal[
        "geopolitical", "monetary", "commodity", "regulatory", "natural_disaster", "other"
    ]
    """イベント種別"""

    confidence: float
    """推論の信頼度（0.0–1.0）"""

    impacts: list[ImpactNode]
    """影響ノードのリスト（複数レベル混在）"""

    generated_at: str
    """生成日時（ISO 8601）"""

    source_event: str
    """元のイベントテキスト（入力値）"""

    def impacts_by_level(self, level: int) -> list[ImpactNode]:
        """指定レベルの影響ノードのみ返す"""
        return [n for n in self.impacts if n.level == level]

    @property
    def max_level(self) -> int:
        """推論チェーンの最大レベル"""
        return max((n.level for n in self.impacts), default=0)


# ---------------------------------------------------------------------------
# 企業プロファイル
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    """企業のセグメント情報"""

    name: str
    """セグメント名"""

    revenue_ratio: float
    """売上構成比（0.0–1.0）"""

    description: str
    """セグメント説明"""

    geographic_exposure: dict[str, float] = field(default_factory=dict)
    """地域別売上比率 例: {"JP": 0.6, "CN": 0.3, "US": 0.1}"""

    keywords: list[str] = field(default_factory=list)
    """セグメントキーワード"""


@dataclass
class CompanyProfile:
    """日本上場企業のプロファイル（EDINET有報ベース）"""

    company_code: str
    """証券コード（例: "6337"）"""

    company_name: str
    """企業名"""

    business_description: str
    """有報「事業の内容」原文"""

    segments: list[Segment] = field(default_factory=list)
    """セグメント情報リスト"""

    keywords: list[str] = field(default_factory=list)
    """抽出済みキーワード"""

    embedding: list[float] | None = field(default=None, repr=False)
    """埋め込みベクトル（text-embedding-3-large, dim=3072）"""

    last_updated: str = ""
    """最終更新日時（ISO 8601）"""

    edinet_code: str = ""
    """EDINETコード"""

    industry_code: str = ""
    """業種コード（東証33業種）"""


# ---------------------------------------------------------------------------
# マッチング結果
# ---------------------------------------------------------------------------

@dataclass
class CompanyMatchResult:
    """企業マッチングの結果"""

    company_code: str
    """証券コード"""

    company_name: str
    """企業名"""

    impact_level: int
    """対応する影響レベル（1–4）"""

    impact_description: str
    """対応する影響の説明"""

    direction: Literal["positive", "negative", "mixed"]
    """影響の方向性"""

    final_score: float
    """最終スコア（0.0–1.0）: vector*0.35 + llm*0.40 + segment*0.25"""

    vector_similarity: float
    """ベクトルコサイン類似度（0.0–1.0）"""

    llm_relevance_score: float
    """LLMによる関連度スコア（0.0–1.0）"""

    segment_exposure_ratio: float
    """該当セグメントの売上構成比（0.0–1.0）"""

    affected_segments: list[str] = field(default_factory=list)
    """影響を受けるセグメント名リスト"""

    rationale: str = ""
    """LLMが生成した根拠テキスト"""

    intensity: Literal["high", "medium", "low"] = "medium"
    """影響強度（親ImpactNodeから継承）"""

    # ------------------------------------------------------------------
    # 定量予測フィールド (予測モデル化のため追加)
    # ------------------------------------------------------------------

    expected_return_pct: float | None = None
    """期待株価リターン点推定値。親ImpactNodeのレンジ中央値 × segment_exposure_ratio"""

    time_horizon: TimeHorizon | None = None
    """検証時間軸 (親ImpactNodeから継承)"""

    prediction_window_days: int | None = None
    """検証に使う株価観察ウィンドウ (日数)。time_horizon から機械的に導出"""

    probability: float | None = None
    """親ImpactNodeから継承した発生確率"""


# ---------------------------------------------------------------------------
# 予測結果の実績検証 (outcome validation)
# ---------------------------------------------------------------------------

@dataclass
class RealizedMetrics:
    """予測の実績照合結果。予測→N日後の実績を突合して算出される。"""

    validated_at: str
    """検証実施日時 (ISO 8601)"""

    brier_score: float | None
    """方向性予測の Brier score。probability vs directional_hit。低いほど良い。"""

    mae_return: float | None
    """期待リターン中央値と実績リターンの絶対誤差平均 (MAE)"""

    coverage_rate: float | None
    """実績リターンが予測レンジ [low, high] に収まった割合 (0.0–1.0)"""

    n_matches: int
    """検証に使用したマッチ件数"""

    n_with_return: int
    """実績リターンが取得できたマッチ件数 (分母)"""

    per_match: list[dict[str, Any]] = field(default_factory=list)
    """個別マッチの検証結果。realized_return_pct / in_range / directional_hit を含む。"""


# ---------------------------------------------------------------------------
# バックテスト評価指標
# ---------------------------------------------------------------------------

@dataclass
class LevelAccuracy:
    """影響レベル別の精度"""

    precision: float
    recall: float
    f1: float


@dataclass
class BacktestMetrics:
    """バックテスト評価指標"""

    event: str
    """評価対象イベント"""

    event_date: str
    """イベント発生日（ISO 8601）"""

    # --- 推論チェーン精度 ---
    chain_precision: float
    """推論したセクターのうち実際に影響を受けた割合"""

    chain_recall: float
    """実際に影響を受けたセクターのうち推論で捉えた割合"""

    chain_f1: float
    """F1スコア"""

    # --- 企業マッチング精度（株価リターンとの相関） ---
    positive_hit_rate: float
    """ポジティブ予測企業の実際の超過リターン率"""

    negative_hit_rate: float
    """ネガティブ予測企業の実際の下落率"""

    top10_return: float
    """スコア上位10社の平均リターン（イベント後 ground_truth_window 日）"""

    ground_truth_window: int
    """株価検証ウィンドウ（日数）"""

    # --- 影響レベル別精度 ---
    level_accuracy: dict[int, LevelAccuracy] = field(default_factory=dict)
    """レベル別精度 例: {1: LevelAccuracy(...), 2: ..., 3: ...}"""
