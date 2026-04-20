# 推論チェーン分析システム — アプリケーション仕様書

**バージョン**: 0.2.0  
**最終更新**: 2026-04-20  
**ステータス**: 開発中 (ロジック完成・検証フェーズ)

---

## 目次

1. [システム概要](#1-システム概要)
2. [アーキテクチャ](#2-アーキテクチャ)
3. [技術スタック](#3-技術スタック)
4. [推論チェーン生成エンジン](#4-推論チェーン生成エンジン)
5. [企業マッチングエンジン](#5-企業マッチングエンジン)
6. [データソース](#6-データソース)
7. [予測検証パイプライン](#7-予測検証パイプライン)
8. [バックテストシステム](#8-バックテストシステム)
9. [データモデル](#9-データモデル)
10. [データベース設計](#10-データベース設計)
11. [API 仕様](#11-api-仕様)
12. [フロントエンド](#12-フロントエンド)
13. [出力フォーマット](#13-出力フォーマット)
14. [CLI ツール](#14-cli-ツール)
15. [環境変数・設定](#15-環境変数設定)
16. [インフラ構成](#16-インフラ構成)
17. [ディレクトリ構成](#17-ディレクトリ構成)

---

## 1. システム概要

### 1.1 目的

上場企業約 4,000 社の中から、マクロ経済イベントの影響を受ける企業を AI で自動検知し、投資機会のシグナルを生成する。特に **機関投資家が見落とすニッチ・小型企業** の発掘を本質的価値とする。

### 1.2 コア機能

| 機能 | 概要 |
|------|------|
| 推論チェーン生成 | マクロイベントから 1次〜4次の多段階因果影響を LLM で自動推論。`parent_sectors` による因果構造の明示 |
| 影響ツリー可視化 | セクター間の因果連鎖を SVG 樹木図で表示。ホバーで因果パスのハイライト、SVG/PNG エクスポート対応 |
| 企業マッチング | ベクトル検索 + LLM スコアリング + セグメント構成比の 3 軸で関連企業をスコアリング。影響ノードとの紐づき表示 |
| 根拠・透明性表示 | スコア内訳 (3軸)・リターン算出式・影響ノード紐づきをポップアップで提示 |
| 定量予測 | セクター別の株価リターンレンジ・時間軸・実現確率を予測 |
| 実績検証 | yfinance から実績株価を取得し、Brier score / MAE / Coverage rate で予測精度を評価 |
| バックテスト | 過去 11 件のプリセットイベントで推論チェーンの汎用性を検証 |

### 1.3 差別化要素

- **多段推論**: 1次影響だけでなく 2次・3次の派生影響を自動推論し、人間が見落とす因果連鎖を発見する
- **定性情報の統合**: EDINET 有報の MD&A / 経営方針 / 事業リスクや TDNet 適時開示など、数値に表れない企業の転換点を LLM スコアリングに反映
- **マッチング戦略切替**: 小型株優先・多様性重視などの戦略をプラグインとして切り替え可能
- **予測の自己検証**: 予測結果を実績株価と突合してキャリブレーションを可視化する閉ループ設計

---

## 2. アーキテクチャ

### 2.1 システム全体像

```
┌──────────────────────────────────────────────────────────────────┐
│                         Frontend (Next.js)                       │
│  /               /calibration           /backtest                │
│  分析フォーム     キャリブレーション      バックテスト検証          │
└───────────┬──────────────┬──────────────┬────────────────────────┘
            │              │              │
            ▼              ▼              ▼
┌──────────────────────────────────────────────────────────────────┐
│                        FastAPI Backend                            │
│  /api/analyze    /api/validation    /api/backtest    /api/results │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐   ┌─────────────────┐   ┌───────────────┐  │
│  │ ReasoningChain   │──▶│ CompanyMatcher   │──▶│ OutputFormat  │  │
│  │ Generator        │   │ (3-axis scoring) │   │ (MD/JSON/Slack│  │
│  │ (Claude Opus)    │   │ (Claude Haiku)   │   │  /PDF)        │  │
│  └─────────────────┘   └────────┬─────────┘   └───────────────┘  │
│                                 │                                 │
│          ┌──────────────────────┼──────────────────────┐          │
│          ▼                      ▼                      ▼          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐    │
│  │   Qdrant      │    │   SQLite      │    │   Redis          │    │
│  │ (Vector DB)   │    │ (Results DB)  │    │ (LLM Cache)      │    │
│  └──────────────┘    └──────────────┘    └──────────────────┘    │
│                                                                  │
│  ┌──────────────────────────────────────────────────────┐        │
│  │          Data Sources                                 │        │
│  │  EDINET API  ·  TDNet  ·  IR Pages  ·  yfinance      │        │
│  └──────────────────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 処理フロー

```
ユーザー入力（マクロイベント）
    │
    ▼
[1] 推論チェーン生成 (Claude Opus 4.6)
    │  → 構造化 JSON: event_summary, impacts[]
    │  → 各 impact に定量予測フィールド + parent_sectors (因果構造) 付与
    │
    ▼
[2] 影響ベクトル生成 (OpenAI text-embedding-3-large, 3072次元)
    │
    ▼
[3] 二段ベクトル検索 (Qdrant)
    │  → company_profiles_full (企業全体) + company_segments (セグメント単位)
    │  → company_code ベースで union、スコア max 採用
    │
    ▼
[4] マッチング戦略によるリランク
    │  → Default / SmallCapFirst / Diversity
    │
    ▼
[5] 業種多様性キャップ (max 8 社/業種)
    │
    ▼
[6] 企業コンテキスト取得 (SQLite: CompanyContextRecord)
    │  → 最近の決算短信・中計・IR ニュース (最大 5 件)
    │
    ▼
[7] LLM スコアリング (Claude Haiku 4.5, 並列実行)
    │  → score: 0.0–1.0, reason, affected_segments
    │  → Redis キャッシュ (TTL 24h)
    │
    ▼
[8] 最終スコア算出
    │  final_score = vector(0.35) + llm(0.40) + segment(0.25)
    │  → 閾値フィルタリング (default 0.6)
    │
    ▼
[9] 結果保存 (SQLite) + レスポンス返却
```

---

## 3. 技術スタック

### 3.1 バックエンド

| 区分 | 技術 | バージョン |
|------|------|-----------|
| 言語 | Python | 3.11+ |
| Web フレームワーク | FastAPI | >= 0.115.0 |
| ASGI サーバ | Uvicorn | >= 0.30.0 |
| ORM | SQLAlchemy | >= 2.0.0 |
| バリデーション | Pydantic | >= 2.8.0 |
| LLM (推論) | Anthropic Claude Opus 4.6 | anthropic >= 0.40.0 |
| LLM (スコアリング) | Anthropic Claude Haiku 4.5 | 同上 |
| LLM (要約) | Anthropic Claude Haiku 4.5 | 同上 |
| 埋め込み | OpenAI text-embedding-3-large | openai >= 1.50.0 |
| ベクトル DB | Qdrant | qdrant-client >= 1.12.0 |
| キャッシュ | Redis | redis >= 5.0.0 |
| HTTP | httpx | >= 0.27.0 |
| XML パース | lxml | >= 5.3.0 |
| 株価データ | yfinance | >= 0.2.40 |
| リトライ | tenacity | >= 8.3.0 |
| データ処理 | pandas / numpy | >= 2.2.0 / >= 1.26.0 |

### 3.2 フロントエンド

| 区分 | 技術 | バージョン |
|------|------|-----------|
| フレームワーク | Next.js (App Router) | 16.2.3 |
| UI ライブラリ | React | 19.2.4 |
| 言語 | TypeScript | 5.x |
| CSS | Tailwind CSS | 4.x |
| フォント | Geist Sans / Mono | Google Fonts |

### 3.3 インフラ

| 区分 | 技術 |
|------|------|
| ベクトル DB | Qdrant (Docker) |
| キャッシュ | Redis 7 Alpine (Docker) |
| RDB | SQLite (ファイル) |
| コンテナ管理 | Docker Compose |

---

## 4. 推論チェーン生成エンジン

**モジュール**: `backend/src/chain/generator.py`

### 4.1 概要

マクロ経済イベントのテキスト入力から、1次〜4次の多段階因果影響チェーンを構造化 JSON として生成する。

### 4.2 モデル構成

| パラメータ | デフォルト値 |
|-----------|-------------|
| model | claude-opus-4-6 (環境変数 `CHAIN_MODEL`) |
| max_tokens | 8192 |
| max_levels | 4 |

### 4.3 プロンプト設計

**ファイル**: `backend/src/chain/prompt_templates.py`

#### システムプロンプト (CHAIN_GENERATION_SYSTEM)

> あなたは金融・経済の専門家です。マクロ経済イベントを分析し、企業業績への影響を多段階で推論します。必ず指定されたJSON形式のみを出力してください。

#### ユーザープロンプト (CHAIN_GENERATION_USER)

推論ルール:
- **level 1 (一次影響)**: イベントの直接的影響。必須。
- **level 2 (二次影響)**: 一次影響から派生する間接影響。必須。
- **level 3 (三次影響)**: 二次影響からさらに派生。可能な場合に含める。
- **level 4 (四次影響)**: 明確な因果関係がある場合のみ。

因果構造フィールドのルール:
- `parent_sectors`: 因果関係の上流セクター名リスト。level 1 は空配列、level 2 以上は前レベルのセクター名を列挙。複数の親から派生する場合は複数列挙可。

定量フィールドのルール:
- `expected_return_pct_low/high`: 株価リターンの想定レンジ (例: -0.15〜-0.05)
- `time_horizon`: 影響顕在化の時間帯 (immediate / 1-4w / 1-3m / 3-12m)
- `probability`: 実現確率 (1次: 0.8+、3次/4次: 0.3〜0.6)

### 4.4 出力パース

- マークダウンコードブロックの自動除去
- JSON 末尾切れ時の自動補完 (`]}` の追加)
- 定量フィールドの型安全変換 (`_to_float_or_none`, `_validate_horizon`)

### 4.5 リトライ戦略

- 対象: RateLimitError (429), APIStatusError (5xx)
- 非対象: BadRequest (400), Authentication (401), Permission (403)
- 最大 3 回、指数バックオフ (min 2s, max 10s)

### 4.6 追加機能

| メソッド | 説明 |
|---------|------|
| `generate(event)` | 同期版チェーン生成 |
| `generate_async(event)` | 非同期版チェーン生成 |
| `generate_stream(event)` | SSE ストリーミング生成 (テキスト断片を逐次 yield) |
| `assess_importance(event)` | イベント重要度の事前評価 (importance / scope / sectors_affected) |

---

## 5. 企業マッチングエンジン

**モジュール**: `backend/src/matching/matcher.py`

### 5.1 スコアリング方式

3 軸の加重平均:

```
final_score = (vector_similarity × 0.35) + (llm_relevance_score × 0.40) + (segment_exposure_ratio × 0.25)
```

| 軸 | 重み | 算出方法 |
|----|------|---------|
| ベクトル類似度 | 0.35 | Qdrant コサイン距離 (3072 次元) |
| LLM 関連度 | 0.40 | Claude Haiku によるスコアリング (0.0–1.0) |
| セグメント構成比 | 0.25 | 影響セグメントの売上構成比合計 |

### 5.2 ベクトル検索

**モジュール**: `backend/src/matching/vector_store.py`

| コレクション | 内容 | 次元 | 距離関数 |
|-------------|------|------|---------|
| `company_profiles_full` | 企業全体の事業記述ベクトル | 3072 | Cosine |
| `company_segments` | セグメント単位のベクトル | 3072 | Cosine |

検索パラメータ:

| パラメータ | デフォルト | 環境変数 |
|-----------|-----------|---------|
| TOP_K_PER_IMPACT | 50 | `TOP_K_PER_IMPACT` |
| TOP_K_SEGMENTS | 30 | `TOP_K_SEGMENTS` |
| MAX_PER_INDUSTRY | 8 | `MAX_PER_INDUSTRY` |
| SCORE_THRESHOLD | 0.6 | `SCORE_THRESHOLD` |

### 5.3 LLM スコアリング

**プロンプト**: `RELEVANCE_SCORING_USER` (prompt_templates.py)

入力情報:
- マクロ影響の説明・方向性・強度・キーワード
- 企業名・証券コード・事業内容・主要セグメント
- 最近の動向 (CompanyContextRecord から最大 5 件)

評価基準:
| スコア | 解釈 |
|--------|------|
| 1.0 | 直接的かつ重大な影響 (売上・利益への明確なインパクト) |
| 0.7–0.9 | 間接的だが明確な影響 (特定セグメントへの波及) |
| 0.5–0.6 | 一部セグメントに軽微な影響 |
| 0.3–0.4 | 影響は考えられるが不明確 |
| 0.0–0.2 | ほぼ無関係 |

出力: `{score, reason, affected_segments}`

Redis キャッシュ: `llm_score:{impact_desc[:80]}:{company_code}` (TTL 24h)

### 5.4 定量予測値の伝播

```
expected_return_pct = midpoint(parent_impact.low, parent_impact.high) × segment_exposure_ratio
prediction_window_days = horizon_to_days(parent_impact.time_horizon)
```

`horizon_to_days` マッピング:
| time_horizon | 日数 |
|-------------|------|
| immediate | 5 |
| 1-4w | 28 |
| 1-3m | 90 |
| 3-12m | 270 |

### 5.5 マッチング戦略 (Strategy パターン)

**モジュール**: `backend/src/matching/strategy.py`

| 戦略名 | クラス | 動作 |
|--------|-------|------|
| `default` | DefaultStrategy | ベクトルスコア降順 (既存動作) |
| `small_cap_first` | SmallCapFirstStrategy | ベクトルスコア昇順 (最低閾値 0.15)。大企業を後回しにしてニッチ企業を優先 |
| `diversity` | DiversityStrategy | スコア中位帯優先 + 業種キャップ 3。上位 20% と下位 20% を除外 |

切り替え方法:
- API パラメータ: `strategy` (AnalyzeRequest)
- 環境変数: `MATCHING_STRATEGY`

### 5.6 埋め込みモデル

**モジュール**: `backend/src/matching/embedder.py`

| パラメータ | 値 |
|-----------|-----|
| モデル | text-embedding-3-large |
| 次元数 | 3072 |
| バッチサイズ | 100 |
| テキスト上限 | 30,000 文字 |

---

## 6. データソース

### 6.1 EDINET API

**モジュール**: `backend/src/data/edinet_client.py`  
**API**: EDINET API v2 (`https://disclosure2.edinet-fsa.go.jp/api/v2`)

| 書類種別コード | 名称 |
|-------------|------|
| 120 | 有価証券報告書 (年次) |
| 140 | 四半期報告書 |
| 160 | 半期報告書 |
| 030 | 臨時報告書 |

抽出可能なセクション:

| セクションタグ | 日本語名 | context_type マッピング |
|-------------|---------|----------------------|
| ManagementPolicy | 経営方針 | midterm_plan |
| ManagementAnalysis | 経営者による分析 (MD&A) | earnings_summary |
| BusinessRisks | 事業等のリスク | ir_news |
| ResearchAndDevelopment | 研究開発活動 | ir_news |
| CapitalExpenditure | 設備投資等の概要 | ir_news |
| BusinessDescription | 事業の内容 | (企業プロファイル構築用) |
| SegmentInformation | セグメント情報 | (セグメント構築用) |

主要メソッド:
- `list_documents(target_date, doc_type)` — 指定日の書類一覧
- `list_documents_for_company(sec_code, start_date, end_date)` — 企業・期間指定
- `extract_qualitative_sections(doc_id)` — 定性情報の一括抽出
- `download_document(doc_id)` — XBRL ZIP 取得 (ローカルキャッシュ対応)

### 6.2 TDNet

**モジュール**: `backend/src/data/tdnet_client.py`  
**対象**: 東証適時開示 (決算短信・業績修正等)

- `fetch_recent_disclosures(company_code, days_back)` — 直近 N 日の適時開示
- `download_text(url)` — 開示テキスト取得
- `summarize(text, title)` — Haiku による要約 (500 文字以内)

### 6.3 IR ニュース

**モジュール**: `backend/src/data/ir_fetcher.py`  
**設定**: `backend/data/ir_sources.json` (企業 → IR ページ URL マッピング)

- `get_ir_url(company_code)` — IR ページ URL 解決
- `fetch_ir_news(company_code, ir_url, limit)` — プレスリリース抽出

### 6.4 yfinance

**モジュール**: `backend/src/validation/yfinance_fetch.py`

- `fetch_return_pct(company_code, start_date, window_days)` — 実績株価リターン取得
- ティッカー形式: `{company_code}.T` (東証)
- 計算: `(close[window_end] - close[start]) / close[start]`

### 6.5 セグメントパーサ

**モジュール**: `backend/src/data/segment_parser.py`

EDINET のセグメント情報テキストから LLM (Haiku) を使って構造化データを抽出:
- セグメント名、売上構成比 (0.0–1.0)、事業内容
- 地域構成比 (JP / CN / US / ASIA / EU / OTHER)
- セグメント固有キーワード

---

## 7. 予測検証パイプライン

**モジュール**: `backend/src/validation/outcome_tracker.py`

### 7.1 検証フロー

1. AnalysisResult から chain_json (親 impact のレンジ/probability) と matches_json を取得
2. 各マッチについて:
   - `prediction_window_days` 経過を確認 (未経過ならスキップ)
   - yfinance で実績リターンを取得
   - `directional_hit`: 予測方向 (positive/negative) と実績リターンの符号の一致判定
   - `in_range`: 実績が [expected_return_pct_low, expected_return_pct_high] 内かを判定
3. 集約指標を計算
4. DB に RealizedMetrics を書き戻し、validation_status を "validated" に更新

### 7.2 評価指標

| 指標 | 計算式 | 解釈 |
|------|--------|------|
| Brier score | mean((probability - directional_hit)^2) | 低いほど良い (0–1)。確率予測の精度 |
| MAE (return) | mean(\|realized - expected_point\|) | 期待リターンと実績の平均絶対誤差 |
| Coverage rate | count(in_range=True) / count(in_range!=None) | 実績がレンジ内に入った割合 |
| Directional hit | 方向一致数 / 判定対象数 | positive→実績>0, negative→実績<0 の一致率 |

### 7.3 キャリブレーションダッシュボード

`GET /api/validation/summary` で提供:
- **Reliability diagram**: probability を 10 bin に分割し、各 bin の平均予測確率 vs 実現頻度をプロット
- **時間軸別 MAE**: immediate / 1-4w / 1-3m / 3-12m 別の誤差分析
- **影響レベル別精度**: 1次〜4次影響別の MAE / Brier / Coverage
- **クロス分析**: 時間軸 × 影響レベルの MAE ヒートマップ

---

## 8. バックテストシステム

**モジュール**: `backend/src/backtest/evaluator.py`

### 8.1 プリセットイベント (11 件)

| イベント | 発生日 | ポジティブセクター | ネガティブセクター |
|---------|--------|-------------------|-------------------|
| COVID-19 パンデミック宣言 | 2020-03-11 | EC/デジタル, 医療, 半導体, 食料品 | 航空・旅行, 外食, 百貨店, 石油 |
| ウクライナ侵攻 | 2022-02-24 | 石油・エネルギー, 防衛, 農業 | 航空, 化学, 輸送・物流 |
| 日銀マイナス金利解除 | 2024-03-19 | 銀行・金融, 保険 | 不動産, 自動車, 電機 |
| 米国対中半導体規制強化 | 2022-10-07 | 半導体検査装置 | 中国向け装置/素材 |
| トランプ関税第1弾 (対中25%) | 2018-07-06 | 国内回帰製造業, 防衛 | 自動車部品, 電子部品 |
| トランプ相互関税 (2025年) | 2025-04-02 | 国内消費, 内需型 | 輸出型製造業, 自動車, 半導体 |
| 米イラン緊張 (ソレイマニ) | 2020-01-03 | 石油・エネルギー, 防衛, 金 | 航空, 旅行, 保険 |
| 安倍元首相銃撃事件 | 2022-07-08 | 防衛, セキュリティ | — |
| 能登半島地震 | 2024-01-01 | 建設・復興, 住宅建材 | 観光, 北陸地域企業 |
| 東京五輪開催決定 | 2013-09-08 | 建設, 不動産, 観光 | — |
| 円安150円突破 | 2022-10-21 | 輸出型製造業, インバウンド | 内需型, 食品 |

### 8.2 評価指標

| 指標 | 説明 |
|------|------|
| chain_precision | 推論セクターのうち ground truth に含まれる割合 |
| chain_recall | ground truth セクターのうち推論で捉えた割合 |
| chain_f1 | 上記の調和平均 |
| positive_hit_rate | ポジティブ予測企業の実績リターン > 0 の割合 |
| negative_hit_rate | ネガティブ予測企業の実績リターン < 0 の割合 |
| top10_return | スコア上位 10 社の平均リターン (event 後 30 日) |
| level_accuracy | 影響レベル別 (1次〜4次) の precision / recall / f1 |

セクター照合方式: 部分文字列マッチ (大文字小文字無視)

---

## 9. データモデル

**ファイル**: `backend/src/models.py`

### 9.1 ImpactNode — 影響ノード

```python
@dataclass
class ImpactNode:
    level: int                              # 1–4
    sector: str                             # 影響セクター名
    description: str                        # 影響の詳細 (2–3文)
    direction: Literal["positive", "negative", "mixed"]
    intensity: Literal["high", "medium", "low"]
    rationale: str                          # 因果関係の説明
    example_companies: list[str]            # 日本企業名の例
    keywords: list[str]                     # ベクトル検索ヒント
    parent_sectors: list[str]               # 因果の上流セクター名 (level 2+ で設定)
    embedding: list[float] | None = None    # 3072次元ベクトル
    expected_return_pct_low: float | None    # 株価リターン下限
    expected_return_pct_high: float | None   # 株価リターン上限
    time_horizon: str | None                # immediate / 1-4w / 1-3m / 3-12m
    probability: float | None               # 実現確率 (0.0–1.0)
```

### 9.2 ReasoningChain — 推論チェーン

```python
@dataclass
class ReasoningChain:
    event_summary: str                      # イベント要約 (1文)
    event_type: str                         # geopolitical / monetary / commodity / regulatory / natural_disaster / other
    confidence: float                       # 推論信頼度 (0.0–1.0)
    impacts: list[ImpactNode]               # 全影響ノード
    generated_at: str                       # ISO 8601 生成日時
    source_event: str                       # 入力テキスト原文
```

### 9.3 CompanyProfile — 企業プロファイル

```python
@dataclass
class CompanyProfile:
    company_code: str                       # 証券コード (例: "6337")
    company_name: str                       # 企業名
    business_description: str               # 事業の内容テキスト
    segments: list[Segment]                 # セグメント一覧
    keywords: list[str]                     # 抽出キーワード
    embedding: list[float] | None           # 3072次元ベクトル
    last_updated: str                       # ISO 8601
    edinet_code: str                        # EDINET 提出者コード
    industry_code: str                      # 東証33業種コード
```

### 9.4 Segment — 事業セグメント

```python
@dataclass
class Segment:
    name: str                               # セグメント名
    revenue_ratio: float                    # 売上構成比 (0.0–1.0)
    description: str                        # セグメント説明
    geographic_exposure: dict[str, float]   # {JP, CN, US, ASIA, EU, OTHER}
    keywords: list[str]                     # セグメント固有キーワード
```

### 9.5 CompanyMatchResult — マッチング結果

```python
@dataclass
class CompanyMatchResult:
    company_code: str
    company_name: str
    impact_level: int                       # マッチ元影響レベル (1–4)
    impact_description: str                 # マッチ元影響テキスト
    impact_sector: str                      # マッチ元影響セクター名
    direction: str                          # positive / negative / mixed
    final_score: float                      # 3軸加重平均 (0.0–1.0)
    vector_similarity: float                # コサイン類似度
    llm_relevance_score: float              # LLM スコア
    segment_exposure_ratio: float           # セグメント構成比
    affected_segments: list[str]            # 影響セグメント名
    rationale: str                          # LLM による根拠
    intensity: str                          # 親 impact から継承
    expected_return_pct: float | None       # midpoint × segment_exposure
    time_horizon: str | None                # 親 impact から継承
    prediction_window_days: int | None      # horizon_to_days 変換値
    probability: float | None               # 親 impact から継承
    company_context: str | None             # 最近の動向テキスト
```

### 9.6 CompanyContext — 企業定性情報

```python
@dataclass
class CompanyContext:
    company_code: str
    context_type: Literal["earnings_summary", "midterm_plan", "ir_news"]
    title: str                              # 開示タイトル
    summary: str                            # LLM 要約 (≤500文字)
    source_url: str                         # 原文 URL
    published_date: str                     # 開示日
    fetched_at: str                         # 取得日時
```

### 9.7 RealizedMetrics — 実績検証結果

```python
@dataclass
class RealizedMetrics:
    validated_at: str                        # 検証日時 (ISO 8601)
    brier_score: float | None               # Brier スコア
    mae_return: float | None                # 平均絶対誤差
    coverage_rate: float | None             # レンジ内率
    n_matches: int                          # 予測総数
    n_with_return: int                      # 実績取得成功数
    per_match: list[dict]                   # 個別検証詳細
```

---

## 10. データベース設計

**ファイル**: `backend/db/models.py`  
**エンジン**: SQLite (デフォルト: `backend/data/results.db`)

### 10.1 analysis_results テーブル

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| id | String(36) | PK | UUID |
| event_text | Text | NOT NULL | ユーザー入力テキスト |
| event_summary | Text | NOT NULL | LLM 生成要約 |
| event_type | String(50) | NOT NULL | イベント種別 |
| confidence | Float | NOT NULL | 推論信頼度 |
| chain_json | JSON | NOT NULL | 推論チェーン全体 |
| matches_json | JSON | NOT NULL | マッチング結果リスト |
| total_impacts | Integer | NOT NULL | 影響ノード数 |
| total_matches | Integer | NOT NULL | マッチ企業数 |
| created_at | DateTime(tz) | NOT NULL | 作成日時 (UTC) |
| validation_status | String(20) | DEFAULT 'pending' | pending / validated / expired |
| validated_at | DateTime(tz) | NULLABLE | 検証実行日時 |
| realized_metrics_json | JSON | NULLABLE | 実績検証結果 |

### 10.2 company_context テーブル

| カラム | 型 | 制約 | 説明 |
|--------|-----|------|------|
| id | String(36) | PK | UUID |
| company_code | String(10) | INDEX | 証券コード |
| context_type | String(30) | NOT NULL | earnings_summary / midterm_plan / ir_news |
| title | Text | NOT NULL | 開示タイトル |
| summary | Text | NOT NULL | LLM 要約 |
| source_url | Text | | 原文 URL |
| published_date | String(30) | | 開示日 |
| fetched_at | DateTime(tz) | NOT NULL | 取得日時 |

インデックス: `(company_code)`, `(company_code, context_type)`

### 10.3 CRUD 操作

**ファイル**: `backend/db/crud.py`

| 関数 | 説明 |
|------|------|
| `create_result(session, data)` | 分析結果を作成 |
| `list_results(session, skip, limit)` | 一覧取得 (降順) |
| `get_result(session, id)` | 単一取得 |
| `upsert_company_context(session, ...)` | コンテキストの upsert (company_code + context_type + title で重複判定) |
| `get_company_contexts(session, company_code)` | 企業のコンテキスト取得 |
| `get_contexts_batch(session, company_codes)` | 複数企業のコンテキストをバッチ取得 |

---

## 11. API 仕様

**ファイル**: `backend/api/routes/*.py`  
**ベース URL**: `http://localhost:8000`

### 11.1 分析エンドポイント

#### POST /api/analyze

マクロイベントを分析し、推論チェーンと影響企業を返す。

**リクエスト**:
```json
{
  "event": "米国が対中半導体輸出規制を強化した",
  "max_levels": 4,
  "top_n": 30,
  "score_threshold": 0.6,
  "chain_only": false,
  "strategy": "default"
}
```

| フィールド | 型 | デフォルト | 制約 |
|-----------|-----|-----------|------|
| event | string | (必須) | 5–1000 文字 |
| max_levels | int | 4 | 1–4 |
| top_n | int | 30 | 1–100 |
| score_threshold | float | 0.6 | 0.0–1.0 |
| chain_only | bool | false | |
| strategy | string | "default" | default / small_cap_first / diversity |

**レスポンス**: `AnalyzeResponse`
```json
{
  "id": "uuid",
  "event_summary": "...",
  "event_type": "regulatory",
  "confidence": 0.85,
  "generated_at": "2026-04-20T10:00:00Z",
  "impacts": [ /* ImpactNodeResponse[] (parent_sectors 含む) */ ],
  "matches": [ /* CompanyMatchResponse[] (impact_sector / impact_description 含む) */ ],
  "total_impacts": 12,
  "total_matches": 45,
  "db_ready": true
}
```

#### GET /api/analyze/stream

SSE でチェーンをストリーミング生成。

| クエリ | 型 | 説明 |
|--------|-----|------|
| event | string | マクロイベント (5文字以上) |

ストリームイベント:
- `{"type": "chunk", "text": "..."}` — テキスト断片
- `{"type": "done"}` — 完了
- `{"type": "error", "message": "..."}` — エラー

### 11.2 結果エンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/api/results?skip=0&limit=50` | 結果一覧 (降順) |
| GET | `/api/results/{id}` | 結果詳細 (chain_json + matches_json 込み) |

### 11.3 エクスポートエンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/api/results/{id}/export/markdown` | Markdown ファイルダウンロード |
| GET | `/api/results/{id}/export/data` | JSON エクスポート (PDF 生成用) |

### 11.4 検証エンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| POST | `/api/validation/run?limit=N` | pending 一括検証 |
| POST | `/api/validation/{id}/run` | 指定 ID 強制検証 |
| GET | `/api/validation/summary?last_n=100&horizon=1-3m` | キャリブレーション集計 |

Summary レスポンスに含まれるフィールド:
- `validated_count`, `pending_count`
- `overall_coverage_rate`, `overall_mae_return`, `rolling_brier`
- `reliability_bins[]` — 10 bin (bin_lower, bin_upper, mean_predicted, realized_frequency, count)
- `mae_by_horizon[]` — 時間軸別 MAE
- `mae_by_level[]` — 影響レベル別 MAE / Brier / Coverage
- `horizon_level_cross[]` — 時間軸 × レベル クロス分析

### 11.5 バックテストエンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/api/backtest/events` | プリセットイベント一覧 (11件) |
| POST | `/api/backtest/run` | カスタムイベントでバックテスト実行 |
| POST | `/api/backtest/run-preset` | プリセット名指定で実行 |
| POST | `/api/backtest/run-all?ground_truth_window=30` | 全プリセット一括実行 |

---

## 12. フロントエンド

**フレームワーク**: Next.js 16 (App Router) + React 19 + TypeScript + Tailwind CSS 4

### 12.1 ページ構成

| ルート | ファイル | 機能 |
|--------|---------|------|
| `/` | `app/page.tsx` | メイン分析画面。イベント入力 → チェーン表示 → 企業マッチング表示 |
| `/calibration` | `app/calibration/page.tsx` | キャリブレーションダッシュボード。KPI / Reliability diagram / MAE 分析 |
| `/backtest` | `app/backtest/page.tsx` | バックテスト検証。プリセット一覧 → ワンクリック実行 → 精度比較 |
| `/results/[id]/print` | `app/results/[id]/print/page.tsx` | 印刷/PDF 用レイアウト |

### 12.2 コンポーネント

| コンポーネント | ファイル | 機能 |
|-------------|---------|------|
| EventForm | `components/EventForm.tsx` | イベント入力テキストエリア + chain_only / top_n / score_threshold / strategy の設定 |
| ChainViewer | `components/ChainViewer.tsx` | 折り畳み可能な多段影響チェーン表示。方向/強度別の色分け、期待リターン・時間軸の表示。ノードごとのマッチ企業数バッジ + 展開式紐づき企業リスト |
| ImpactTree | `components/ImpactTree.tsx` | SVG ベースの影響ツリー図。parent_sectors による因果構造を可視化。ホバー/クリックで因果パスをハイライト。SVG/PNG ダウンロード対応 |
| MatchTable | `components/MatchTable.tsx` | フィルタ (positive/negative/mixed) + ソート (スコア/影響レベル) 付き企業テーブル。紐づきノード表示 (ImpactLinkBadge)、スコア内訳ポップアップ (ScoreWithBreakdown)、リターン算出根拠ポップアップ (ReturnWithRationale)。展開式「最近の動向」 |
| HistorySidebar | `components/HistorySidebar.tsx` | 左サイドバーに最近 30 件の分析履歴。クリックで結果復元 |
| ExportButtons | `components/ExportButtons.tsx` | Markdown ダウンロード / PDF 印刷ボタン |
| ReliabilityDiagram | `components/ReliabilityDiagram.tsx` | SVG 散布図。y=x 参照線、bin サイズ比例の円表示 |

### 12.3 画面レイアウト (メインページ)

```
┌──────────────────┬─────────────────────────────────────┐
│ HistorySidebar   │  メインコンテンツ (max-w-4xl)        │
│ (w-64, 最新30件)  │                                     │
│                  │  [EventForm]                         │
│  分析履歴         │    └ テキストエリア + 設定セレクト    │
│  ├ イベント1 ←選択│                                     │
│  ├ イベント2      │  [影響チェーン] ← リスト/樹木図 切替 │
│  └ ...           │    ├ [ChainViewer] リスト表示         │
│                  │    │  └ 折り畳みカード + マッチ企業数 │
│  精度 ▸          │    └ [ImpactTree] 樹木図表示          │
│  (→/calibration) │       └ SVG/PNG ダウンロード          │
│                  │                                     │
│                  │  [MatchTable]                        │
│                  │    └ フィルタ + ソート + 企業テーブル │
│                  │    └ 紐づきノード + スコア根拠ポップ │
└──────────────────┴─────────────────────────────────────┘
```

### 12.4 影響ツリー図 (ImpactTree)

**共有モジュール**: `lib/tree-layout.ts` (React 非依存の純粋データ変換)

ツリーレイアウトの定数:

| 定数 | 値 | 説明 |
|------|-----|------|
| NODE_W | 180 | ノード幅 (px) |
| NODE_H | 72 | ノード高さ (px) |
| H_GAP | 60 | 水平間隔 (px) |
| V_GAP | 24 | 垂直間隔 (px) |
| ROOT_W | 200 | ルートノード幅 (px) |
| ROOT_H | 40 | ルートノード高さ (px) |

機能:
- `buildTreeLayout(impacts, matches, eventSummary)` — ノード配置 (x, y) とエッジを計算
- `renderTreeSvgString(layout, eventSummary)` — スタンドアロン SVG 文字列を生成 (PNG 出力・印刷用)
- ルートノード (イベント名) → 1次影響 → 2次影響 → ... の左→右レイアウト
- `parent_sectors` がある場合は明示的な因果リンクを描画、ない場合は前レベル全ノードにフォールバック接続
- 方向性による色分け (positive: 緑系、negative: 赤系、mixed: 黄系)
- 強度インジケータ (high: 赤丸、medium: 黄丸、low: 緑丸)
- マッチ企業数バッジ
- ホバー/クリックで因果パス (祖先 + 子孫) をハイライト、非対象ノードを半透明化
- 選択ノードの詳細パネル (説明・根拠・上流セクター名)

画像出力:
- **SVG ダウンロード**: `renderTreeSvgString()` → Blob → ダウンロード
- **PNG ダウンロード**: SVG → Canvas (2x Retina) → PNG → ダウンロード
- **PDF 印刷**: `/results/[id]/print` ページ内に `dangerouslySetInnerHTML` で SVG を埋め込み

### 12.5 証拠紐づき・根拠表示

ChainViewer と MatchTable の連携による分析の透明性向上機能:

#### ChainViewer 側
- 各影響ノードに対応するマッチ企業数を「N社マッチ」バッジで表示
- クリックで展開: 紐づき企業名・スコア・根拠を一覧表示 (LinkedCompanies)

#### MatchTable 側
- **紐づきノード** (ImpactLinkBadge): 各企業がどの影響ノードにマッチしたかをバッジで表示。クリックで影響ノードの詳細ポップアップ
- **スコア内訳** (ScoreWithBreakdown): final_score をクリックで 3 軸 (ベクトル×0.35 + LLM×0.40 + セグメント×0.25) の内訳テーブルをポップアップ表示
- **リターン算出根拠** (ReturnWithRationale): 期待リターン値をクリックで算出式 (セクターレンジ中央値 × セグメント構成比) をポップアップ表示
- **Popover コンポーネント**: useRef + useEffect による外側クリック検知で閉じる汎用ポップアップ

---

## 13. 出力フォーマット

**モジュール**: `backend/src/output/`

### 13.1 Markdown

`formatter.py` の `AlertFormatter.to_markdown()` および `exporter.py` の `chain_to_markdown()`:
- ヘッダー (イベント概要・信頼度)
- 影響チェーン (レベル別、方向/強度のラベル付き)
- マッチング企業テーブル (ポジティブ/ネガティブ/混在別)
- スコア内訳テーブル (総合/ベクトル/LLM/セグメント)

### 13.2 JSON

`AlertFormatter.to_json()`:
- 推論チェーン全体 + マッチング結果をフラット JSON として出力
- `ensure_ascii=False` (日本語対応)

### 13.3 Slack (Block Kit)

`AlertFormatter.to_slack_blocks()`:
- ヘッダー → イベント概要 → 影響チェーンサマリ (1次〜3次) → ポジティブ/ネガティブ上位 5 社
- `post_to_slack(webhook_url)` で Incoming Webhook 送信

### 13.4 PDF

フロントエンド `/results/[id]/print` ページからブラウザの印刷ダイアログで生成。

構成:
- ヘッダー (イベント概要・信頼度・生成日時)
- イベントサマリ (青背景バナー)
- 影響チェーン (レベル別カード形式)
- 影響ツリー図 (SVG 埋め込み、`break-inside: avoid` で改ページ制御)
- マッチング企業テーブル (方向別) + スコア内訳テーブル

---

## 14. CLI ツール

### 14.1 分析実行 (main.py)

```bash
python -m backend.main "米国が対中半導体輸出規制を強化した" \
  --format markdown \
  --max-levels 4 \
  --top-n 10 \
  --threshold 0.6 \
  --chain-only \
  --slack-webhook https://hooks.slack.com/...
```

### 14.2 企業 DB 構築 (scripts/build_company_db.py)

```bash
python -m scripts.build_company_db --limit 100 --resume
```

EDINET から有価証券報告書を取得 → 事業記述・セグメント抽出 → 埋め込みベクトル生成 → Qdrant 登録。

| オプション | 説明 |
|-----------|------|
| `--limit N` | 処理企業数の上限 |
| `--start DATE` | 検索開始日 |
| `--end DATE` | 検索終了日 |
| `--resume` | 処理済み企業をスキップ |

### 14.3 企業コンテキスト更新 (scripts/update_company_context.py)

```bash
python -m scripts.update_company_context --limit 100 --days-back 90 --source all
```

EDINET / TDNet / IR から最新の定性情報を取得し、LLM で要約して SQLite に保存。

| オプション | 説明 |
|-----------|------|
| `--company-code CODE` | 特定企業のみ更新 |
| `--limit N` | 処理企業数の上限 |
| `--days-back D` | 遡る日数 (default: 90) |
| `--source {all,edinet,tdnet,ir}` | データソース限定 |

### 14.4 DB マイグレーション (scripts/migrate_add_validation_columns.py)

```bash
python -m scripts.migrate_add_validation_columns
```

analysis_results テーブルに validation_status / validated_at / realized_metrics_json カラムを冪等に追加。

---

## 15. 環境変数・設定

**ファイル**: `backend/.env.example`

### 15.1 API キー

| 変数 | 必須 | 説明 |
|------|------|------|
| `ANTHROPIC_API_KEY` | Yes | Claude API キー |
| `OPENAI_API_KEY` | Yes | OpenAI Embedding API キー |

### 15.2 サービス接続

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `QDRANT_URL` | http://localhost:6333 | Qdrant エンドポイント |
| `QDRANT_API_KEY` | (空) | Qdrant 認証キー |
| `REDIS_URL` | redis://localhost:6379/0 | Redis キャッシュ |
| `DATABASE_URL` | sqlite:///backend/data/results.db | SQLAlchemy DB URI |

### 15.3 モデル選択

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `CHAIN_MODEL` | claude-opus-4-6 | 推論チェーン生成モデル |
| `SCORING_MODEL` | claude-haiku-4-5-20251001 | LLM スコアリングモデル |
| `SUMMARIZE_MODEL` | claude-haiku-4-5-20251001 | EDINET セクション要約モデル |
| `EMBEDDING_MODEL` | text-embedding-3-large | 埋め込みモデル |

### 15.4 マッチングパラメータ

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `TOP_K_PER_IMPACT` | 50 | 企業全体検索の取得件数 |
| `TOP_K_SEGMENTS` | 30 | セグメント検索の取得件数 |
| `MAX_PER_INDUSTRY` | 8 | 業種あたりの上限企業数 |
| `SCORE_THRESHOLD` | 0.6 | 最終スコアの閾値 |
| `MATCHING_STRATEGY` | default | デフォルトのマッチング戦略 |
| `MAX_LLM_CANDIDATES` | 80 | LLM スコアリング対象の上限 (feature/expand-candidates) |
| `VECTOR_SCORE_THRESHOLD` | 0.1 | ベクトル検索の最低スコア (feature/expand-candidates) |

### 15.5 フロントエンド

| 変数 | デフォルト | ファイル |
|------|-----------|---------|
| `NEXT_PUBLIC_API_URL` | http://localhost:8000 | `frontend/.env.local` |

---

## 16. インフラ構成

**ファイル**: `infra/docker-compose.yml`

```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
```

### 16.1 起動手順

```bash
# 1. インフラ起動
cd infra && docker compose up -d

# 2. バックエンド起動
cd backend && pip install -r requirements.txt
python server.py  # → http://localhost:8000

# 3. フロントエンド起動
cd frontend && npm install && npm run dev  # → http://localhost:3000

# 4. 企業 DB 構築 (初回のみ)
cd backend && python -m scripts.build_company_db --limit 100
```

---

## 17. ディレクトリ構成

```
reasoning-chain/
├── README.md
├── DESIGN.md                              # アーキテクチャ設計書
├── PROGRESS_REPORT.md                     # 進捗レポート
│
├── backend/
│   ├── main.py                            # CLI エントリポイント
│   ├── server.py                          # Uvicorn 起動スクリプト
│   ├── requirements.txt                   # Python 依存パッケージ
│   ├── .env.example                       # 環境変数テンプレート
│   │
│   ├── api/
│   │   ├── app.py                         # FastAPI アプリケーションファクトリ
│   │   ├── schemas.py                     # Pydantic リクエスト/レスポンスモデル
│   │   └── routes/
│   │       ├── analyze.py                 # POST /api/analyze, GET /api/analyze/stream
│   │       ├── results.py                 # GET /api/results, GET /api/results/{id}
│   │       ├── export.py                  # GET /api/results/{id}/export/*
│   │       ├── validation.py              # POST /api/validation/*, GET /api/validation/summary
│   │       └── backtest.py                # GET/POST /api/backtest/*
│   │
│   ├── db/
│   │   ├── models.py                      # SQLAlchemy ORM モデル
│   │   ├── session.py                     # DB 初期化・セッション管理
│   │   └── crud.py                        # CRUD 関数群
│   │
│   ├── src/
│   │   ├── models.py                      # データクラス定義
│   │   ├── chain/
│   │   │   ├── generator.py               # ReasoningChainGenerator
│   │   │   └── prompt_templates.py        # LLM プロンプトテンプレート
│   │   ├── matching/
│   │   │   ├── embedder.py                # OpenAI Embedding ラッパー
│   │   │   ├── vector_store.py            # Qdrant クライアントラッパー
│   │   │   ├── matcher.py                 # CompanyMatcher (3軸スコアリング)
│   │   │   └── strategy.py               # マッチング戦略 (Strategy パターン)
│   │   ├── data/
│   │   │   ├── edinet_client.py           # EDINET API v2 クライアント
│   │   │   ├── tdnet_client.py            # TDNet 適時開示フェッチャー
│   │   │   ├── ir_fetcher.py              # IR ニューススクレイパー
│   │   │   └── segment_parser.py          # LLM ベースセグメント抽出
│   │   ├── validation/
│   │   │   ├── outcome_tracker.py         # 予測検証パイプライン
│   │   │   └── yfinance_fetch.py          # 株価リターン取得
│   │   ├── backtest/
│   │   │   └── evaluator.py               # バックテスト評価 (11 プリセット)
│   │   └── output/
│   │       ├── formatter.py               # Markdown / JSON / Slack 出力
│   │       └── exporter.py                # Markdown レポートエクスポーター
│   │
│   ├── scripts/
│   │   ├── build_company_db.py            # 企業 DB 一括構築スクリプト
│   │   ├── update_company_context.py      # 企業コンテキスト更新スクリプト
│   │   └── migrate_add_validation_columns.py  # DB マイグレーション
│   │
│   └── data/
│       └── ir_sources.json                # IR ページ URL マッピング
│
├── frontend/
│   ├── package.json                       # Node.js 依存パッケージ
│   ├── next.config.ts                     # Next.js 設定
│   ├── tsconfig.json                      # TypeScript 設定
│   ├── .env.local                         # フロントエンド環境変数
│   └── src/
│       ├── app/
│       │   ├── layout.tsx                 # ルートレイアウト
│       │   ├── page.tsx                   # メイン分析ページ
│       │   ├── calibration/page.tsx       # キャリブレーションダッシュボード
│       │   ├── backtest/page.tsx          # バックテスト検証ページ
│       │   └── results/[id]/print/page.tsx # 印刷用ページ
│       ├── components/
│       │   ├── EventForm.tsx              # イベント入力フォーム
│       │   ├── ChainViewer.tsx            # 推論チェーンビューワー (マッチ企業数バッジ・紐づき企業展開)
│       │   ├── ImpactTree.tsx             # 影響ツリー図 (SVG/PNG エクスポート対応)
│       │   ├── MatchTable.tsx             # 企業マッチングテーブル (紐づきノード・スコア根拠ポップアップ)
│       │   ├── HistorySidebar.tsx         # 履歴サイドバー
│       │   ├── ExportButtons.tsx          # エクスポートボタン
│       │   └── ReliabilityDiagram.tsx     # Reliability diagram (SVG)
│       └── lib/
│           ├── api.ts                     # API クライアント (型定義 + fetch 関数)
│           └── tree-layout.ts             # ツリーレイアウト計算 (React非依存、印刷/PNG共用)
│
├── infra/
│   └── docker-compose.yml                 # Qdrant + Redis
│
└── docs/
    ├── calibration-design.md              # キャリブレーション詳細設計
    └── APPLICATION_SPEC.md                # 本ドキュメント
```
