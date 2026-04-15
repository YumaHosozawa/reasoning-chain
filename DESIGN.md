# システム設計書: 推論チェーン（マクロイベント→企業影響の多段推論）

---

## 1. システム概要

### 1.1 目的

マクロ経済イベントを入力として受け取り、一次→二次→三次（→四次）の影響チェーンをLLMで推論し、日本上場企業約4,000社の中から影響を受ける企業を自動特定する。

### 1.2 システム全体図

```
                        ┌─────────────────────────────────────────────┐
                        │                入力レイヤー                   │
                        │   マクロイベント（テキスト or 構造化データ）    │
                        └──────────────────┬──────────────────────────┘
                                           │
                        ┌──────────────────▼──────────────────────────┐
                        │            推論チェーン生成エンジン             │
                        │                                              │
                        │  イベント解析 → 一次影響 → 二次影響 → 三次影響  │
                        │                    （LLM: Claude / GPT-4o）   │
                        └──────────────────┬──────────────────────────┘
                                           │ 影響チェーン（構造化JSON）
                        ┌──────────────────▼──────────────────────────┐
                        │               企業マッチングエンジン            │
                        │                                              │
                        │  影響ベクトル化 ──── コサイン類似度検索          │
                        │                          │                   │
                        │                  企業プロファイルDB             │
                        │              （EDINET有報 + セグメントDB）      │
                        └──────────────────┬──────────────────────────┘
                                           │ マッチング結果
                        ┌──────────────────▼──────────────────────────┐
                        │            スコアリング & フィルタリング         │
                        │                                              │
                        │  関連度スコア × 影響強度 × セグメント構成比       │
                        └──────────────────┬──────────────────────────┘
                                           │
                        ┌──────────────────▼──────────────────────────┐
                        │                 出力レイヤー                   │
                        │          推論チェーンアラート / レポート          │
                        └─────────────────────────────────────────────┘
```

---

## 2. コンポーネント設計

### 2.1 推論チェーン生成エンジン

#### 役割

マクロイベントのテキストを受け取り、多段の影響チェーンを構造化JSONとして生成する。

#### プロンプト設計

```python
CHAIN_GENERATION_PROMPT = """
あなたは金融・経済の専門家です。
以下のマクロ経済イベントが発生した場合の影響を、段階的に推論してください。

イベント: {event_description}

以下の形式でJSONを出力してください:

{
  "event_summary": "イベントの要約",
  "event_type": "geopolitical|monetary|commodity|regulatory|natural_disaster",
  "confidence": 0.0-1.0,
  "impacts": [
    {
      "level": 1,
      "sector": "影響を受けるセクター/業界",
      "description": "影響の詳細説明",
      "direction": "positive|negative|mixed",
      "intensity": "high|medium|low",
      "rationale": "なぜこの影響が生じるか（因果関係の説明）",
      "example_companies": ["企業名1", "企業名2"],
      "keywords": ["キーワード1", "キーワード2"]
    }
  ]
}

注意:
- 一次影響: イベントの直接的影響（必ず含める）
- 二次影響: 一次影響から派生する間接影響（必ず含める）
- 三次影響: 二次影響からさらに派生する影響（可能な場合）
- 四次影響: 三次影響からさらに派生する影響（明確な場合のみ）
- 各影響は独立したオブジェクトとして列挙する（1つのlevelに複数あってよい）
"""
```

#### 出力スキーマ

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class ImpactNode:
    level: int                          # 1=一次, 2=二次, 3=三次, 4=四次
    sector: str                         # 影響セクター
    description: str                    # 影響の説明
    direction: Literal["positive", "negative", "mixed"]
    intensity: Literal["high", "medium", "low"]
    rationale: str                      # 因果関係の説明
    example_companies: list[str]        # 例示企業名
    keywords: list[str]                 # マッチング用キーワード
    embedding: list[float] | None       # 埋め込みベクトル（生成後に付与）

@dataclass
class ReasoningChain:
    event_summary: str
    event_type: str
    confidence: float
    impacts: list[ImpactNode]
    generated_at: str                   # ISO 8601
    source_event: str                   # 元のイベントテキスト
```

---

### 2.2 企業プロファイルDB

#### データソース

| ソース | 内容 | 更新頻度 |
|--------|------|----------|
| EDINET有報「事業の内容」 | 企業の主要事業説明（非構造化テキスト） | 年1回（有報提出時） |
| EDINETセグメント情報 | セグメント別売上・利益・説明 | 年1回（有報提出時） |
| 決算短信 | 最新業績・事業概況 | 四半期毎 |

#### 企業プロファイルスキーマ

```python
@dataclass
class CompanyProfile:
    company_code: str           # 証券コード（例: "6337"）
    company_name: str           # 企業名
    business_description: str   # 有報「事業の内容」原文
    segments: list[Segment]     # セグメント情報
    keywords: list[str]         # 抽出済みキーワード
    embedding: list[float]      # 埋め込みベクトル
    last_updated: str           # 最終更新日時

@dataclass
class Segment:
    name: str                   # セグメント名
    revenue_ratio: float        # 売上構成比（0.0-1.0）
    description: str            # セグメント説明
    geographic_exposure: dict   # 地域別売上比率 {"JP": 0.6, "CN": 0.3, ...}
    keywords: list[str]         # セグメントキーワード
```

#### ベクトルストア構成

```
ベクトルDB（Qdrant推奨）
├── collection: company_profiles_full
│   └── ベクトル: 事業説明全文の埋め込み（dim=3072, text-embedding-3-large）
├── collection: company_segments
│   └── ベクトル: セグメント説明の埋め込み（セグメント単位）
└── collection: company_keywords
    └── ベクトル: キーワードの埋め込み（軽量・高速）
```

---

### 2.3 企業マッチングエンジン

#### マッチングフロー

```
影響ノード（ImpactNode）
    │
    ├─ Step 1: 影響説明 + キーワードを連結してテキスト生成
    │
    ├─ Step 2: テキストを埋め込みベクトルに変換
    │
    ├─ Step 3: ベクトルDBでコサイン類似度検索（top_k=50）
    │
    ├─ Step 4: LLMによるゼロショット関連度スコアリング（0.0-1.0）
    │
    ├─ Step 5: セグメントデータで影響の定量化
    │
    └─ Step 6: 最終スコア計算 → フィルタリング（閾値: 0.6以上）
```

#### スコアリング式

```
final_score = (
    vector_similarity * 0.35
  + llm_relevance_score * 0.40
  + segment_exposure_ratio * 0.25
)
```

| 要素 | 重み | 説明 |
|------|------|------|
| vector_similarity | 0.35 | コサイン類似度（0.0-1.0） |
| llm_relevance_score | 0.40 | LLMによる関連度判定（0.0-1.0） |
| segment_exposure_ratio | 0.25 | 該当セグメントの売上構成比（0.0-1.0） |

#### LLM関連度判定プロンプト

```python
RELEVANCE_SCORING_PROMPT = """
以下のマクロ経済影響と企業プロファイルの関連度を0.0〜1.0で評価してください。

【マクロ影響】
{impact_description}
方向性: {direction}
強度: {intensity}

【企業プロファイル】
企業名: {company_name}
事業内容: {business_description}
主要セグメント: {segments_summary}

評価基準:
- 1.0: 直接的かつ重大な影響が予想される
- 0.7: 間接的だが明確な影響が予想される
- 0.5: 一部セグメントに軽微な影響
- 0.3: 影響は考えられるが不明確
- 0.0: ほぼ無関係

JSON形式で出力:
{
  "score": 0.0-1.0,
  "reason": "スコアの根拠（1-2文）",
  "affected_segments": ["影響を受けるセグメント名"]
}
"""
```

---

### 2.4 バックテスト評価システム

#### 評価対象イベント

| イベント | 日付 | 検証ポイント |
|----------|------|-------------|
| COVID-19 ショック | 2020-03 | リモートワーク・医療・物流への影響チェーン精度 |
| ウクライナ侵攻 | 2022-02 | エネルギー・穀物・防衛関連の影響チェーン精度 |
| 日銀利上げ（マイナス金利解除） | 2024-03 | 金融・不動産・輸出企業への影響チェーン精度 |
| 米国対中半導体規制強化 | 2022-10 | 半導体サプライチェーンへの影響チェーン精度 |

#### 評価指標

```python
@dataclass
class BacktestMetrics:
    # 推論チェーン精度
    chain_precision: float      # 推論したセクターのうち実際に影響を受けた割合
    chain_recall: float         # 実際に影響を受けたセクターのうち推論で捉えた割合
    chain_f1: float

    # 企業マッチング精度（株価リターンとの相関）
    positive_hit_rate: float    # ポジティブ予測企業の実際の超過リターン率
    negative_hit_rate: float    # ネガティブ予測企業の実際の下落率
    top10_return: float         # スコア上位10社の平均リターン（イベント後30日）

    # 二次・三次影響の精度
    level_accuracy: dict        # {1: 0.85, 2: 0.70, 3: 0.55} など
```

---

## 3. データフロー

### 3.1 初期セットアップ（バッチ処理）

```
EDINET API
    │
    ▼
edinet_client.py ──── 有報XML取得 ────▶ 事業の内容テキスト
                                              │
                                    segment_parser.py
                                              │
                                    セグメント構造化データ
                                              │
                                       embedder.py
                                              │
                                    埋め込みベクトル生成
                           （text-embedding-3-large, dim=3072）
                                              │
                                      vector_store.py
                                              │
                                    Qdrant / FAISS に格納
                                    （約4,000社 × 複数コレクション）
```

### 3.2 リアルタイム処理（イベント発生時）

```
マクロイベント入力
    │
    ▼
generator.py
    │ Claude API呼び出し（Streaming対応）
    ▼
ReasoningChain（JSON）
    │
    ├── 各ImpactNodeを並列処理
    │
    ▼
matcher.py
    │ ベクトル検索（Qdrant）→ LLMスコアリング（並列）
    ▼
CompanyMatchResult（スコア付き企業リスト）
    │
    ▼
formatter.py
    │
    ▼
アラート出力（Markdown / JSON / Slack通知）
```

---

## 4. API設計

### 4.1 主要インターフェース

```python
class ReasoningChainGenerator:
    def generate(
        self,
        event_description: str,
        max_levels: int = 4,
        model: str = "claude-opus-4-6",
    ) -> ReasoningChain:
        """マクロイベントから推論チェーンを生成する"""
        ...

    def generate_stream(
        self,
        event_description: str,
        max_levels: int = 4,
    ):
        """ストリーミングで推論チェーンを生成する（逐次出力用）"""
        ...


class CompanyMatcher:
    def match(
        self,
        chain: ReasoningChain,
        top_k_per_impact: int = 20,
        score_threshold: float = 0.6,
    ) -> list[CompanyMatchResult]:
        """推論チェーンの各影響に対して企業をマッチングする"""
        ...

    def match_impact(
        self,
        impact: ImpactNode,
        top_k: int = 20,
    ) -> list[CompanyMatchResult]:
        """単一の影響ノードに対して企業をマッチングする"""
        ...


class BacktestEvaluator:
    def evaluate(
        self,
        event: str,
        event_date: str,           # ISO 8601
        ground_truth_window: int = 30,  # 株価検証ウィンドウ（日数）
    ) -> BacktestMetrics:
        """バックテストを実行して評価指標を返す"""
        ...
```

### 4.2 出力データ構造

```python
@dataclass
class CompanyMatchResult:
    company_code: str
    company_name: str
    impact_level: int               # 一次=1, 二次=2, ...
    impact_description: str
    direction: str                  # "positive" | "negative" | "mixed"
    final_score: float              # 0.0-1.0
    vector_similarity: float
    llm_relevance_score: float
    segment_exposure_ratio: float
    affected_segments: list[str]
    rationale: str                  # LLMが生成した根拠テキスト
```

---

## 5. 技術スタック

| カテゴリ | 採用技術 | 選定理由 |
|----------|----------|----------|
| LLM（推論チェーン生成） | Claude claude-opus-4-6 | 長文推論・構造化JSON出力の精度 |
| LLM（スコアリング） | Claude claude-haiku-4-5-20251001 | 高速・低コスト（4,000社処理のため） |
| 埋め込みモデル | text-embedding-3-large (OpenAI) | 日英対応・高次元（3072dim） |
| ベクトルDB | Qdrant | フィルタリング機能・スケーラビリティ |
| データ取得 | EDINET API | 日本上場企業の有報取得 |
| 言語 | Python 3.11+ | |
| 非同期処理 | asyncio + httpx | 4,000社の並列処理 |
| キャッシュ | Redis | LLMスコアリング結果のキャッシュ |

---

## 6. 実装ロードマップ

### Phase 1: 推論チェーン生成（2-3日）

- [ ] `prompt_templates.py` — プロンプト定義
- [ ] `generator.py` — Claude API呼び出し・JSON解析
- [ ] 単体テスト（5イベントでの動作確認）

### Phase 2: 企業プロファイルDB構築（5-7日）

- [ ] `edinet_client.py` — 有報XML取得・テキスト抽出
- [ ] `segment_parser.py` — セグメント情報の構造化
- [ ] `embedder.py` — 埋め込みベクトル生成（バッチ処理）
- [ ] `vector_store.py` — Qdrantへの格納・クエリ

### Phase 3: 企業マッチング（5-7日）

- [ ] `matcher.py` — ベクトル検索 + LLMスコアリング統合
- [ ] 並列処理の最適化（asyncio）
- [ ] スコアリングの閾値チューニング

### Phase 4: バックテスト（1-2週間）

- [ ] `evaluator.py` — 過去イベントでの精度評価
- [ ] 評価指標の実装
- [ ] 改善サイクル（プロンプト・重みの調整）

### Phase 5: 出力・統合（3-5日）

- [ ] `formatter.py` — アラートフォーマット
- [ ] Slack/メール通知オプション
- [ ] エンドツーエンドテスト

---

## 7. 既知のリスクと対策

| リスク | 影響度 | 対策 |
|--------|--------|------|
| 二次・三次影響の推論精度低下 | 高 | 各レベルに信頼度スコアを付与し、三次以降は参考情報として表示 |
| LLMの「もっともらしいハルシネーション」 | 高 | バックテストによる定量評価 + 人間レビューフラグ |
| 4,000社のベクトルDB更新コスト | 中 | 差分更新（変更された有報のみ再処理） |
| マクロイベントの重要度判定 | 中 | イベント分類モデル（high/medium/low impact）の構築 |
| LLMスコアリングのコスト（4,000社×影響数） | 中 | Haiku使用 + Redisキャッシュ + 閾値フィルタリングで削減 |
| EDINET APIのレート制限 | 低 | バッチ処理 + リトライロジック |
