# キャリブレーション機能 詳細設計書

## 1. 概要

### 1.1 目的

推論チェーンシステムが出力する予測（影響方向・期待リターン・発生確率）を、実績株価リターンと自動照合し、予測精度を定量的に評価・可視化する。これにより「予測 → 検証 → 改善」のフィードバックループを閉じ、クオンツ/シストラ運用に耐える信頼性基盤を構築する。

### 1.2 スコープ

| 対象 | 内容 |
|------|------|
| 定量スキーマ拡張 | ImpactNode / CompanyMatchResult に期待リターンレンジ・時間軸・発生確率を付与 |
| 実績検証パイプライン | yfinance による実績リターン取得 → Brier / MAE / Coverage の自動算出 |
| キャリブレーションAPI | 一括検証・個別検証・集計サマリの3エンドポイント |
| ダッシュボードUI | Reliability diagram, KPI カード, Horizon別MAE テーブル |

### 1.3 スコープ外

- Self-consistency（複数サンプル合意度） — 計算コスト大、検証データ蓄積後に判断
- シナリオ分岐UI — UX大改修、キャリブレーションとは独立
- 学習ベースのスコア重み最適化 — 検証データ蓄積が前提
- cron/スケジューラ統合 — 現時点では手動 or API呼び出しで実行

---

## 2. アーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (Next.js)                     │
│                                                             │
│  /calibration ─────────────────────────────────────────┐    │
│  │ KPI Cards │ ReliabilityDiagram │ Horizon MAE Table  │    │
│  └─────────────────────────────────────────────────────┘    │
│       │                                                     │
│       │ fetchCalibrationSummary() / runValidationSweep()    │
└───────┼─────────────────────────────────────────────────────┘
        │ HTTP
┌───────▼─────────────────────────────────────────────────────┐
│                   Backend (FastAPI)                          │
│                                                             │
│  /api/validation/summary  ← GET  集計サマリ                  │
│  /api/validation/run      ← POST 一括検証                    │
│  /api/validation/{id}/run ← POST 個別強制検証                │
│       │                                                     │
│       ▼                                                     │
│  ┌─────────────────────────────────────────────┐            │
│  │        outcome_tracker.py                    │            │
│  │  sweep_pending() ──► validate_result()       │            │
│  │       │                     │                │            │
│  │       │              yfinance_fetch.py        │            │
│  │       │              fetch_return_pct()       │            │
│  └───────┼─────────────────────┼────────────────┘            │
│          ▼                     ▼                             │
│  ┌──────────────┐    ┌──────────────────┐                   │
│  │   SQLite DB   │    │  yfinance API    │                   │
│  │ analysis_     │    │  ({code}.T)      │                   │
│  │ results       │    └──────────────────┘                   │
│  └──────────────┘                                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. データモデル

### 3.1 ImpactNode 追加フィールド

推論チェーン生成時に LLM が出力する各影響ノードの定量フィールド。

| フィールド | 型 | 説明 | 例 |
|-----------|---|------|---|
| `expected_return_pct_low` | `float \| None` | 代表企業の期待株価リターン下限 | `-0.15` (-15%) |
| `expected_return_pct_high` | `float \| None` | 同上限 | `-0.05` (-5%) |
| `time_horizon` | `TimeHorizon \| None` | 影響顕在化の時間軸 | `"1-3m"` |
| `probability` | `float \| None` | 実現確率 (0.0-1.0) | `0.75` |

```python
TimeHorizon = Literal["immediate", "1-4w", "1-3m", "3-12m"]
```

### 3.2 CompanyMatchResult 追加フィールド

マッチング処理時に親 ImpactNode から伝播・導出される。

| フィールド | 型 | 導出方法 |
|-----------|---|---------|
| `expected_return_pct` | `float \| None` | `(low + high) / 2 * segment_exposure_ratio` |
| `time_horizon` | `TimeHorizon \| None` | 親 ImpactNode から継承 |
| `prediction_window_days` | `int \| None` | `horizon_to_days(time_horizon)` |
| `probability` | `float \| None` | 親 ImpactNode から継承 |

### 3.3 時間軸 → 検証ウィンドウ マッピング

```python
HORIZON_WINDOW_DAYS = {
    "immediate": 5,    # 1週間（営業日ベース）
    "1-4w":      28,   # 4週間
    "1-3m":      90,   # 3ヶ月
    "3-12m":     270,  # 9ヶ月（レンジ中央値）
}
```

未知の `time_horizon` 値は `"1-3m"` (90日) にフォールバックする。

### 3.4 RealizedMetrics（検証結果）

1件の AnalysisResult に対する検証結果の集約。

| フィールド | 型 | 説明 |
|-----------|---|------|
| `validated_at` | `str` | 検証実施日時 (ISO 8601) |
| `brier_score` | `float \| None` | `mean((probability - directional_hit)^2)` — 低いほど良い |
| `mae_return` | `float \| None` | `mean(abs(expected_return_pct - realized_return_pct))` |
| `coverage_rate` | `float \| None` | `realized が [low, high] に入った割合` |
| `n_matches` | `int` | 検証対象マッチ件数 |
| `n_with_return` | `int` | 実績リターン取得成功件数 |
| `per_match` | `list[dict]` | 個別マッチの詳細検証結果 |

#### per_match 各要素の構造

```json
{
  "company_code": "7203",
  "company_name": "トヨタ自動車",
  "direction": "negative",
  "time_horizon": "1-3m",
  "window_days": 90,
  "expected_return_pct": -0.08,
  "expected_return_pct_low": -0.12,
  "expected_return_pct_high": -0.04,
  "probability": 0.70,
  "realized_return_pct": -0.065,
  "directional_hit": true,
  "in_range": true
}
```

### 3.5 DB スキーマ（analysis_results テーブル拡張）

既存テーブルへの3列追加。

| カラム | 型 | デフォルト | 説明 |
|-------|---|----------|------|
| `validation_status` | `VARCHAR(20)` | `"pending"` | `pending` / `validated` / `expired` |
| `validated_at` | `DATETIME` | `NULL` | 検証実施日時 |
| `realized_metrics_json` | `JSON` | `NULL` | `RealizedMetrics` の JSON ダンプ |

状態遷移:

```
pending ──(sweep_pending/validate_result)──► validated
pending ──(手動/TTL超過)──► expired (将来用、現時点では未使用)
```

---

## 4. 検証パイプライン

### 4.1 処理フロー

```
sweep_pending()
  │
  ├─ SELECT * FROM analysis_results WHERE validation_status = 'pending'
  │
  ├─ 各 result について:
  │   ├─ created_at + max(prediction_window_days) > now → スキップ
  │   └─ validate_result(result)
  │       │
  │       ├─ 各マッチについて:
  │       │   ├─ prediction_window_days 未経過 → スキップ
  │       │   ├─ fetch_return_pct(code, start, window) → realized_return_pct
  │       │   ├─ directional_hit = direction一致判定
  │       │   ├─ in_range = realized ∈ [low, high]
  │       │   └─ Brier term = (probability - hit)^2
  │       │
  │       ├─ 集約: brier_score, mae_return, coverage_rate
  │       └─ DB書き戻し: realized_metrics_json, validation_status="validated"
  │
  └─ session.commit()
```

### 4.2 yfinance データ取得

```python
def fetch_return_pct(company_code: str, start_date: datetime, window_days: int) -> float | None
```

- ティッカー形式: `{company_code}.T`（東証）
- 取得期間: `start_date` ～ `start_date + window_days + 10日`（週末・祝日のバッファ）
- リターン計算: `(end_price - start_price) / start_price`
- `window_days` 目の営業日終値を使用。データ不足時は最終営業日の終値で代替
- 取得失敗/データなしは `None` を返す（エラーでパイプラインを止めない）

### 4.3 検証指標の定義

#### Brier Score

方向性予測の確率較正を測る指標。完全なキャリブレーションで 0.0。

```
Brier = mean((p_i - hit_i)^2)

p_i   = 予測確率 (probability フィールド)
hit_i = directional_hit ? 1.0 : 0.0
```

- `direction = "mixed"` のマッチは directional_hit が定義できないため除外
- `probability` が None のマッチは除外

#### MAE (Mean Absolute Error)

期待リターンの点推定精度。

```
MAE = mean(|expected_return_pct_i - realized_return_pct_i|)
```

- `expected_return_pct` = `(low + high) / 2 * segment_exposure_ratio`
- 両方が非 None のマッチのみ対象

#### Coverage Rate

予測レンジの包含率。信頼区間の健全性を評価する。

```
Coverage = count(realized ∈ [low, high]) / count(low, high が共に非 None)
```

- 理想値は予測信頼度水準に依存（90%レンジなら 0.9 前後が健全）

### 4.4 制約・制限

| 項目 | 値 | 理由 |
|------|---|------|
| 1件あたり最大マッチ検証数 | 50 | yfinance レート制限対策 |
| sweep_pending の limit | API パラメータで制御可能 (1-500) | バッチサイズ制御 |
| prediction_window 未経過 | スキップ | 公正な検証のため |

---

## 5. API エンドポイント

### 5.1 `POST /api/validation/run`

pending 状態の予測を一括検証する。

**クエリパラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|---|------|------|
| `limit` | `int` | No | 処理上限件数 (1-500) |

**レスポンス (200):**

```json
{
  "validated_ids": ["uuid-1", "uuid-2"],
  "count": 2,
  "swept_at": "2026-04-16T12:00:00+00:00"
}
```

**実行条件:** `validation_status = "pending"` かつ `created_at + max(prediction_window_days) <= now`

### 5.2 `POST /api/validation/{result_id}/run`

指定 result_id を即時検証する。prediction_window 未経過でも強制実行。

**レスポンス (200):**

```json
{
  "id": "uuid-1",
  "brier_score": 0.18,
  "mae_return": 0.045,
  "coverage_rate": 0.72,
  "n_matches": 15,
  "n_with_return": 12
}
```

**エラー (404):** `{"detail": "result not found"}`

### 5.3 `GET /api/validation/summary`

キャリブレーションダッシュボード用の集計データを返す。

**クエリパラメータ:**

| パラメータ | 型 | デフォルト | 説明 |
|-----------|---|----------|------|
| `last_n` | `int` | `100` | 集計対象の直近検証済み件数 (1-1000) |
| `horizon` | `str` | `None` | 特定の time_horizon でフィルタ |

**レスポンス (200):**

```json
{
  "validated_count": 42,
  "pending_count": 18,
  "overall_coverage_rate": 0.68,
  "overall_mae_return": 0.052,
  "rolling_brier": 0.21,
  "reliability_bins": [
    {
      "bin_lower": 0.0,
      "bin_upper": 0.1,
      "mean_predicted": null,
      "realized_frequency": null,
      "count": 0
    },
    {
      "bin_lower": 0.5,
      "bin_upper": 0.6,
      "mean_predicted": 0.55,
      "realized_frequency": 0.48,
      "count": 12
    }
  ],
  "mae_by_horizon": [
    { "time_horizon": "immediate", "mae_return": 0.032, "count": 8 },
    { "time_horizon": "1-3m", "mae_return": 0.061, "count": 22 }
  ]
}
```

#### Reliability Bins の算出ロジック

1. 検証済み result の `per_match` を全件展開
2. `probability` と `directional_hit` が共に非 None のマッチを対象
3. `probability` を 10 bin (`[0.0, 0.1), [0.1, 0.2), ..., [0.9, 1.0]`) に分割
4. 各 bin 内の `mean(probability)` = `mean_predicted`, `mean(directional_hit)` = `realized_frequency`
5. 完全カリブレーション: `mean_predicted ≈ realized_frequency`（y=x 線上）

---

## 6. フロントエンド

### 6.1 キャリブレーションダッシュボード (`/calibration`)

#### 画面構成

```
┌──────────────────────────────────────────────────────┐
│  ← 分析に戻る                    [ホライズン▼] [検証を実行]  │
│  キャリブレーションダッシュボード                              │
│  実績リターンとの突合による予測精度の可視化                      │
├──────────────────────────────────────────────────────┤
│                                                      │
│  ┌──────┐ ┌──────┐ ┌──────────┐ ┌──────────┐       │
│  │検証済み│ │Brier │ │Coverage  │ │MAE       │       │
│  │  42   │ │0.210 │ │  68.0%   │ │  5.2%    │       │
│  │pend 18│ │0-1低◎│ │レンジ包含│ │期待vs実績│       │
│  └──────┘ └──────┘ └──────────┘ └──────────┘       │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │ Reliability diagram                          │   │
│  │                                              │   │
│  │  [SVG: x=予測確率, y=実現頻度]                │   │
│  │  [y=x 基準線 + データ点 + 折れ線]             │   │
│  │                                              │   │
│  │  bin  件数  平均予測  実現率                    │   │
│  │  0.5   12    0.55    0.48                    │   │
│  │  0.6    8    0.63    0.71                    │   │
│  │  0.7   15    0.74    0.68                    │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │ 時間軸別 MAE                                  │   │
│  │  Horizon    件数    MAE                       │   │
│  │  即時          8    3.2%                      │   │
│  │  1-3ヶ月     22    6.1%                      │   │
│  └──────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────┘
```

#### コンポーネント構成

| コンポーネント | ファイル | 説明 |
|-------------|---------|------|
| `CalibrationPage` | `app/calibration/page.tsx` | ページ本体。状態管理・API呼び出し |
| `ReliabilityDiagram` | `components/ReliabilityDiagram.tsx` | 純SVG実装の散布図 |
| `KpiCard` | `app/calibration/page.tsx` 内 | KPI表示カード（ローカルコンポーネント） |

#### 操作

- **ホライズンフィルタ**: `全ホライズン / 即時 / 1-4週 / 1-3ヶ月 / 3-12ヶ月` — API の `horizon` パラメータに連動
- **検証を実行**: `POST /api/validation/run` → 完了後にサマリを再取得
- **← 分析に戻る**: トップページに遷移

### 6.2 ReliabilityDiagram (SVG)

外部チャートライブラリに依存しない純 SVG 実装。

**描画仕様:**

| 要素 | 説明 |
|------|------|
| x軸 | 予測確率 (0.0 - 1.0) |
| y軸 | 実現頻度 (0.0 - 1.0) |
| y=x 基準線 | 破線。完全カリブレーション基準 |
| データ点 | 円。cx = mean_predicted, cy = realized_frequency |
| 円の半径 | `3 + 7 * (count / maxCount)` — bin内件数に比例 |
| 折れ線 | データ点を結ぶ実現曲線 |
| グリッド | 0.1 刻み |

**判読:**
- 点が y=x 線上 → well-calibrated
- 点が y=x より下 → 過信 (overconfident)
- 点が y=x より上 → 過小評価 (underconfident)

### 6.3 既存UIへの反映

#### ChainViewer (影響ノード詳細)

各ノードに以下のバッジを追加表示:

```
期待リターン +3.0% 〜 +12.0%  |  1-3ヶ月  |  p = 0.75
```

- `expected_return_pct_low/high` が非 null の場合のみ表示
- `time_horizon` が非 null の場合のみ表示
- `probability` が非 null の場合のみ表示

#### MatchTable (企業マッチング一覧)

2列を追加:

| 追加列 | データソース | フォーマット |
|-------|------------|-----------|
| 期待リターン | `expected_return_pct` | `+3.5%` / `-8.2%` / `—` |
| Horizon | `time_horizon` | `即時` / `1-4w` / `1-3m` / `3-12m` |

---

## 7. 後方互換性

### 7.1 LLM 出力のフォールバック

新フィールドが欠落した旧フォーマットの LLM 出力に対して:

```python
expected_return_pct_low  → None
expected_return_pct_high → None
time_horizon             → None (horizon_to_days で 90日扱い)
probability              → None
```

`generator.py` の `_to_float_or_none()` と `_validate_horizon()` ヘルパーがパース時にフォールバックを適用する。

### 7.2 フロントエンド

全定量フィールドは TypeScript 型定義で `optional (?)` かつ `| null` として宣言されている。旧データでは `—` 表示にフォールバックする。

### 7.3 DB マイグレーション

`ALTER TABLE` による既存行への影響:

| カラム | 既存行の値 |
|-------|----------|
| `validation_status` | `"pending"` |
| `validated_at` | `NULL` |
| `realized_metrics_json` | `NULL` |

マイグレーションスクリプト (`scripts/migrate_add_validation_columns.py`) は冪等性あり — `inspect(engine).get_columns()` で既存カラムを事前チェックし、存在する場合はスキップする。

---

## 8. ファイル構成

### 変更ファイル

| ファイル | 変更内容 |
|---------|---------|
| `backend/src/models.py` | ImpactNode / CompanyMatchResult / RealizedMetrics 拡張 |
| `backend/src/chain/prompt_templates.py` | 定量フィールド必須化 + few-shot追加 |
| `backend/src/chain/generator.py` | パースフォールバック追加 |
| `backend/src/matching/matcher.py` | 定量フィールド伝播 |
| `backend/db/models.py` | validation 用カラム3列追加 |
| `backend/api/app.py` | validation ルータ登録 |
| `backend/api/schemas.py` | レスポンススキーマ拡張 |
| `backend/api/routes/analyze.py` | 新フィールドのレスポンス反映 |
| `backend/src/backtest/evaluator.py` | yfinance呼び出しを共有helperに置換 |
| `frontend/src/lib/api.ts` | 型定義 + API関数追加 |
| `frontend/src/components/ChainViewer.tsx` | 定量バッジ表示 |
| `frontend/src/components/MatchTable.tsx` | 列追加 |
| `frontend/src/components/HistorySidebar.tsx` | キャリブレーションリンク追加 |

### 新規ファイル

| ファイル | 説明 |
|---------|------|
| `backend/src/validation/__init__.py` | パッケージ初期化 |
| `backend/src/validation/outcome_tracker.py` | 検証パイプライン本体 |
| `backend/src/validation/yfinance_fetch.py` | 株価リターン取得の共有ヘルパー |
| `backend/api/routes/validation.py` | 検証APIエンドポイント |
| `backend/scripts/migrate_add_validation_columns.py` | DBマイグレーションスクリプト |
| `frontend/src/app/calibration/page.tsx` | キャリブレーションダッシュボード |
| `frontend/src/components/ReliabilityDiagram.tsx` | Reliability diagram (SVG) |

---

## 9. 検証手順

### 9.1 マイグレーション確認

```bash
cd /path/to/reasoning-chain
python -m backend.scripts.migrate_add_validation_columns
```

SQLite に `validation_status`, `validated_at`, `realized_metrics_json` の3列が追加されていることを確認。既存行は `validation_status = "pending"`。

### 9.2 新スキーマでの分析

```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"event": "日銀が政策金利を0.5%に引き上げ"}'
```

レスポンス JSON で以下を確認:
- 全 impact に `expected_return_pct_low/high`, `time_horizon`, `probability` が存在
- 全 match に `expected_return_pct`, `time_horizon`, `prediction_window_days` が存在

### 9.3 後方互換

旧フォーマットの既存 result を `GET /api/results/{id}` で取得し、フロントが `—` 表示にフォールバックすることを確認。

### 9.4 検証パイプライン

1. テスト用に `created_at` を60日前にずらした行を1件挿入
2. `POST /api/validation/run` → `realized_metrics_json` が埋まり `validation_status = "validated"` に
3. 再度実行 → 既に validated の行はスキップ（冪等性確認）
4. 1社について yfinance リターンを手計算でクロスチェック

### 9.5 ダッシュボード

5件以上 validated させてから `/calibration` にアクセス:
- Reliability diagram が描画される
- KPI カード (Brier / Coverage / MAE) が表示される
- ホライズンフィルタが機能する
- 検証実行ボタンが動作する

### 9.6 リグレッション

- 4プリセットの backtest (`evaluate_all_preset_events`) が以前と同等の数値で通る
- Markdown / PDF エクスポートが新フィールド込みで正常動作
- メインページの履歴切替・分析実行が正常動作
