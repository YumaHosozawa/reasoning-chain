"""
バックテスト評価システム

過去のマクロイベントで推論チェーンの精度と
企業マッチングの株価予測精度を評価する。
"""

from __future__ import annotations

import math
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pandas as pd

from src.models import BacktestMetrics, CompanyMatchResult, LevelAccuracy, ReasoningChain
from src.chain.generator import ReasoningChainGenerator
from src.matching.matcher import CompanyMatcher
from src.validation.yfinance_fetch import fetch_return_pct


# ------------------------------------------------------------------
# 過去検証イベント定義
# ------------------------------------------------------------------

BACKTEST_EVENTS: list[dict] = [
    {
        "name": "COVID-19ショック",
        "event_date": "2020-03-11",
        "description": "WHOがCOVID-19のパンデミックを宣言。各国で都市封鎖・渡航制限が実施された。",
        "ground_truth_sectors_positive": ["EC/デジタル", "医療・ヘルスケア", "半導体", "食料品"],
        "ground_truth_sectors_negative": ["航空・旅行", "外食", "百貨店・小売", "石油"],
    },
    {
        "name": "ウクライナ侵攻",
        "event_date": "2022-02-24",
        "description": "ロシアがウクライナへの軍事侵攻を開始。エネルギー・穀物価格が急騰した。",
        "ground_truth_sectors_positive": ["石油・エネルギー", "防衛", "農業・穀物", "代替エネルギー"],
        "ground_truth_sectors_negative": ["航空", "化学（原料高）", "輸送・物流（燃料高）"],
    },
    {
        "name": "日銀マイナス金利解除",
        "event_date": "2024-03-19",
        "description": "日銀がマイナス金利政策を解除し、政策金利を0〜0.1%に引き上げた。",
        "ground_truth_sectors_positive": ["銀行・金融", "保険", "不動産（一部）"],
        "ground_truth_sectors_negative": ["不動産（借入コスト増）", "自動車（輸出）", "電機（円高リスク）"],
    },
    {
        "name": "米国対中半導体規制強化",
        "event_date": "2022-10-07",
        "description": "米国が中国向け半導体・製造装置の輸出規制を大幅に強化した。",
        "ground_truth_sectors_positive": ["半導体検査装置（代替需要）", "日本国内向け半導体製造"],
        "ground_truth_sectors_negative": ["中国向け半導体装置メーカー", "中国向け素材メーカー"],
    },
    {
        "name": "トランプ関税第1弾（対中25%）",
        "event_date": "2018-07-06",
        "description": "トランプ政権が中国からの340億ドル相当の輸入品に25%の追加関税を発動した。",
        "ground_truth_sectors_positive": ["国内回帰製造業", "防衛"],
        "ground_truth_sectors_negative": ["自動車部品", "電子部品（中国依存）"],
    },
    {
        "name": "トランプ相互関税（2025年）",
        "event_date": "2025-04-02",
        "description": "トランプ大統領が相互関税を発表。日本を含む主要貿易相手国に対し、各国の対米関税率に応じた報復関税を課す方針を示した。",
        "ground_truth_sectors_positive": ["国内消費", "内需型"],
        "ground_truth_sectors_negative": ["輸出型製造業", "自動車", "半導体"],
    },
    {
        "name": "米イラン緊張（ソレイマニ司令官殺害）",
        "event_date": "2020-01-03",
        "description": "米軍がイラン革命防衛隊のソレイマニ司令官を殺害し、中東の地政学的緊張が急激に高まった。原油価格が急騰。",
        "ground_truth_sectors_positive": ["石油・エネルギー", "防衛", "金"],
        "ground_truth_sectors_negative": ["航空", "旅行", "保険"],
    },
    {
        "name": "安倍元首相銃撃事件",
        "event_date": "2022-07-08",
        "description": "安倍晋三元首相が奈良市で街頭演説中に銃撃され死亡した。政治的安定性への懸念が一時高まった。",
        "ground_truth_sectors_positive": ["防衛", "セキュリティ"],
        "ground_truth_sectors_negative": [],
    },
    {
        "name": "能登半島地震",
        "event_date": "2024-01-01",
        "description": "石川県能登地方を震源とするM7.6の地震が発生。広範囲で建物倒壊・インフラ被害が発生した。",
        "ground_truth_sectors_positive": ["建設・復興", "住宅建材"],
        "ground_truth_sectors_negative": ["観光", "北陸地域企業"],
    },
    {
        "name": "東京五輪開催決定",
        "event_date": "2013-09-08",
        "description": "2020年夏季オリンピック・パラリンピックの開催地が東京に決定した。",
        "ground_truth_sectors_positive": ["建設", "不動産", "観光"],
        "ground_truth_sectors_negative": [],
    },
    {
        "name": "円安150円突破",
        "event_date": "2022-10-21",
        "description": "ドル円相場が32年ぶりに1ドル=150円台を突破。日米金利差拡大を背景に歴史的な円安水準に到達した。",
        "ground_truth_sectors_positive": ["輸出型製造業", "インバウンド"],
        "ground_truth_sectors_negative": ["内需型（輸入コスト）", "食品"],
    },
]


class BacktestEvaluator:
    """過去イベントで推論チェーンシステムの精度を評価するクラス"""

    def __init__(
        self,
        generator: ReasoningChainGenerator | None = None,
        matcher: CompanyMatcher | None = None,
    ) -> None:
        self._generator = generator or ReasoningChainGenerator()
        self._matcher = matcher or CompanyMatcher()

    # ------------------------------------------------------------------
    # メイン評価
    # ------------------------------------------------------------------

    def evaluate(
        self,
        event: str,
        event_date: str,
        ground_truth_positive_sectors: list[str],
        ground_truth_negative_sectors: list[str],
        ground_truth_window: int = 30,
    ) -> BacktestMetrics:
        """
        指定イベントでバックテストを実行する。

        Args:
            event: イベント説明テキスト
            event_date: イベント発生日（ISO 8601）
            ground_truth_positive_sectors: 実際にポジティブ影響を受けたセクターリスト
            ground_truth_negative_sectors: 実際にネガティブ影響を受けたセクターリスト
            ground_truth_window: 株価検証ウィンドウ（日数）

        Returns:
            BacktestMetrics: 評価指標
        """
        # 推論チェーン生成
        chain = self._generator.generate(event)

        # 企業マッチング
        matches = self._matcher.match(chain)

        # 推論チェーン精度（セクター単位）
        chain_precision, chain_recall, chain_f1 = self._evaluate_chain_accuracy(
            chain,
            ground_truth_positive_sectors + ground_truth_negative_sectors,
        )

        # 影響レベル別精度
        level_accuracy = self._evaluate_level_accuracy(
            chain,
            ground_truth_positive_sectors + ground_truth_negative_sectors,
        )

        # 株価リターンの検証（yfinanceを使用）
        positive_hit_rate, negative_hit_rate, top10_return = (
            self._evaluate_stock_returns(
                matches, event_date, ground_truth_window
            )
        )

        return BacktestMetrics(
            event=event,
            event_date=event_date,
            chain_precision=round(chain_precision, 4),
            chain_recall=round(chain_recall, 4),
            chain_f1=round(chain_f1, 4),
            positive_hit_rate=round(positive_hit_rate, 4),
            negative_hit_rate=round(negative_hit_rate, 4),
            top10_return=round(top10_return, 4),
            ground_truth_window=ground_truth_window,
            level_accuracy=level_accuracy,
        )

    def evaluate_all_preset_events(
        self, ground_truth_window: int = 30
    ) -> list[BacktestMetrics]:
        """定義済みの全バックテストイベントを評価する"""
        results = []
        for event_def in BACKTEST_EVENTS:
            print(f"評価中: {event_def['name']}...")
            metrics = self.evaluate(
                event=event_def["description"],
                event_date=event_def["event_date"],
                ground_truth_positive_sectors=event_def["ground_truth_sectors_positive"],
                ground_truth_negative_sectors=event_def["ground_truth_sectors_negative"],
                ground_truth_window=ground_truth_window,
            )
            results.append(metrics)
        return results

    # ------------------------------------------------------------------
    # 内部評価ロジック
    # ------------------------------------------------------------------

    def _evaluate_chain_accuracy(
        self,
        chain: ReasoningChain,
        ground_truth_sectors: list[str],
    ) -> tuple[float, float, float]:
        """
        推論チェーンのセクター予測精度を計算する。

        推論したセクターと正解セクターを文字列部分マッチで照合する。
        """
        predicted_sectors = [node.sector for node in chain.impacts]
        gt_lower = [s.lower() for s in ground_truth_sectors]

        # Precision: 推論セクターのうち正解に含まれる割合
        hits_in_predicted = sum(
            1 for p in predicted_sectors
            if any(g in p.lower() or p.lower() in g for g in gt_lower)
        )
        precision = hits_in_predicted / len(predicted_sectors) if predicted_sectors else 0.0

        # Recall: 正解セクターのうち推論で捉えた割合
        pred_lower = [s.lower() for s in predicted_sectors]
        hits_in_gt = sum(
            1 for g in gt_lower
            if any(g in p or p in g for p in pred_lower)
        )
        recall = hits_in_gt / len(gt_lower) if gt_lower else 0.0

        f1 = _f1(precision, recall)
        return precision, recall, f1

    def _evaluate_level_accuracy(
        self,
        chain: ReasoningChain,
        ground_truth_sectors: list[str],
    ) -> dict[int, LevelAccuracy]:
        """影響レベルごとの精度を計算する"""
        result = {}
        gt_lower = [s.lower() for s in ground_truth_sectors]

        for level in range(1, chain.max_level + 1):
            nodes = chain.impacts_by_level(level)
            if not nodes:
                continue
            predicted = [n.sector for n in nodes]
            pred_lower = [s.lower() for s in predicted]

            hits_p = sum(
                1 for p in pred_lower
                if any(g in p or p in g for g in gt_lower)
            )
            precision = hits_p / len(pred_lower) if pred_lower else 0.0

            hits_r = sum(
                1 for g in gt_lower
                if any(g in p or p in g for p in pred_lower)
            )
            recall = hits_r / len(gt_lower) if gt_lower else 0.0

            result[level] = LevelAccuracy(
                precision=round(precision, 4),
                recall=round(recall, 4),
                f1=round(_f1(precision, recall), 4),
            )
        return result

    def _evaluate_stock_returns(
        self,
        matches: list[CompanyMatchResult],
        event_date: str,
        window: int,
    ) -> tuple[float, float, float]:
        """
        マッチング結果と実際の株価リターンを照合する。

        yfinance を使用してイベント後 window 日間の株価リターンを取得する。
        東証銘柄は "<code>.T" 形式でyfinanceに渡す。

        Returns:
            (positive_hit_rate, negative_hit_rate, top10_return)
        """
        start_dt = datetime.fromisoformat(event_date)

        positive_matches = [m for m in matches if m.direction == "positive"]
        negative_matches = [m for m in matches if m.direction == "negative"]

        pos_hit_count = 0
        neg_hit_count = 0
        top10_returns = []

        top_targets = (positive_matches + negative_matches)[:50]  # 上限50社
        top10_ids = {id(m) for m in top_targets[:10]}
        for match in top_targets:
            ret = fetch_return_pct(match.company_code, start_dt, window)
            if ret is None:
                continue

            if match.direction == "positive" and ret > 0:
                pos_hit_count += 1
            elif match.direction == "negative" and ret < 0:
                neg_hit_count += 1

            if id(match) in top10_ids:
                top10_returns.append(ret)

        pos_rate = pos_hit_count / len(positive_matches) if positive_matches else 0.0
        neg_rate = neg_hit_count / len(negative_matches) if negative_matches else 0.0
        top10_avg = sum(top10_returns) / len(top10_returns) if top10_returns else 0.0

        return pos_rate, neg_rate, top10_avg


# ------------------------------------------------------------------
# ヘルパー
# ------------------------------------------------------------------

def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def metrics_to_dataframe(metrics_list: list[BacktestMetrics]) -> "pd.DataFrame":
    """BacktestMetricsのリストをDataFrameに変換する"""
    rows = []
    for m in metrics_list:
        rows.append({
            "event": m.event[:50],
            "event_date": m.event_date,
            "chain_precision": m.chain_precision,
            "chain_recall": m.chain_recall,
            "chain_f1": m.chain_f1,
            "positive_hit_rate": m.positive_hit_rate,
            "negative_hit_rate": m.negative_hit_rate,
            "top10_return": m.top10_return,
        })
    return pd.DataFrame(rows)
