# 手法 #12: 推論チェーン（マクロイベント→企業影響の多段推論）

> Tier S / 新規性 ★★★★☆ / 萌芽的研究あり、マルチホップ統合が差別化

## 概要

マクロイベント（原油高騰、金利上昇等）から「一次→二次→三次影響」を推論し、恩恵を受ける企業を4,000社から自動特定するシステム。

人間のアナリストは「原油高騰→石油企業が上がる」（一次影響）は考えるが、「原油高騰→独自精製技術を持つ中小企業が化ける」（二次影響）や「→その部品サプライヤー」（三次影響）までは網羅できない。LLMなら4,000社に対して同時に多段推論を実行可能。

---

## ディレクトリ構成

```
reasoning-chain/
├── README.md                    # 本ファイル
├── DESIGN.md                    # システム設計書
├── src/
│   ├── chain/
│   │   ├── generator.py         # 推論チェーン生成
│   │   └── prompt_templates.py  # プロンプトテンプレート
│   ├── matching/
│   │   ├── embedder.py          # 企業プロファイルの埋め込み
│   │   ├── vector_store.py      # ベクトルストア管理
│   │   └── matcher.py           # 企業マッチング
│   ├── data/
│   │   ├── edinet_client.py     # EDINET有報取得
│   │   └── segment_parser.py    # セグメントデータ解析
│   ├── backtest/
│   │   └── evaluator.py         # バックテスト評価
│   └── output/
│       └── formatter.py         # アラート出力フォーマット
├── tests/
│   ├── test_chain_generator.py
│   ├── test_matcher.py
│   └── test_backtest.py
├── notebooks/
│   ├── 01_chain_generation_demo.ipynb
│   ├── 02_matching_demo.ipynb
│   └── 03_backtest_analysis.ipynb
├── data/
│   ├── company_profiles/        # 企業プロファイルキャッシュ
│   └── events/                  # マクロイベントサンプル
└── requirements.txt
```

---

## クイックスタート

### 環境構築

```bash
pip install -r requirements.txt
```

### 基本的な使い方

```python
from src.chain.generator import ReasoningChainGenerator
from src.matching.matcher import CompanyMatcher

# 推論チェーン生成
generator = ReasoningChainGenerator()
chain = generator.generate("米国、対中半導体輸出規制を強化")

# 企業マッチング
matcher = CompanyMatcher()
results = matcher.match(chain)

# アラート出力
results.print_alert()
```

---

## 出力イメージ

```
【推論チェーンアラート】

イベント: 「米国、対中半導体輸出規制を強化」(2026/04/08)

影響チェーン:
  一次: 中国向け半導体装置メーカーに打撃（東京エレクトロン等）
  二次: 中国が国産半導体を加速 → 中国向け素材企業に恩恵
  三次: 日本の半導体検査装置企業は代替需要で恩恵の可能性

マッチング企業（4,000社中）:
  ポジティブ影響:
    テセック（6337）: 半導体検査装置。構成比100%。影響度: 高
    TOWA（6315）: モールディング装置。海外売上比率高い。影響度: 中
  ネガティブ影響:
    XXXX社: 中国向け装置売上40%。影響度: 高
```

---

## 必要なドメイン知識

### 必須

- マクロ経済の基礎（GDP、金利、為替、原油価格等と企業業績の関係）
- 産業連関の基礎（セクター間の依存関係）
- セグメント情報の読み方

### あると望ましい

- 地政学リスクの基礎（中東情勢、米中関係等）
- サプライチェーンの考え方
- 金融商品（先物、オプション）の基礎

---

## 関連論文

| 論文 | 概要 |
|------|------|
| Hassan et al. (2019) "Firm-Level Political Risk" QJE | テキスト→企業影響パイプラインの先行研究 |
| Lopez-Lira & Tang (2023) "Can ChatGPT Forecast Stock Price Movements?" | LLMプロンプト設計と金融推論の実証 |
| LLM Multi-Causal Event Causality Mining (2025) Springer | 多因果イベント因果関係マイニング |
| Decomposing Macroeconomic Sentiment with LLMs (BIS, 2025) | BISによるLLMマクロ分析 |
| Stock Market Spillovers via Global Production Network (NBER) | グローバル生産ネットワーク経由の株式市場スピルオーバー |

---

## 主なリスク

- LLMの推論チェーンが「もっともらしいが間違い」のリスク（二次・三次になるほど精度低下）
- 4,000社の事業内容ベクトルのメンテナンスコスト
- マクロイベントの「重要度」を自動判定する基準が必要
