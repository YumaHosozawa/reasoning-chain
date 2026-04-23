"""
マッチング戦略

ベクトル検索後の候補リランクを戦略パターンで切り替え可能にする。
小型株優先・多様性重視など、異なる発掘ロジックをプラグインとして実装。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict


class MatchingStrategy(ABC):
    """マッチング戦略の基底クラス"""

    name: str

    @abstractmethod
    def rerank(self, hits: list[dict]) -> list[dict]:
        """
        マージ済み候補をリランクして返す。

        Args:
            hits: _merge_hits() の出力。各 dict は
                  company_code, company_name, industry_code, vector_score を持つ。

        Returns:
            リランク後の候補リスト
        """
        ...

    @property
    def max_per_industry(self) -> int | None:
        """戦略固有の業種キャップ。None で matcher のデフォルトを使用。"""
        return None


class DefaultStrategy(MatchingStrategy):
    """高スコア優先 + 中位帯（マイナー上場企業）を一定割合インターリーブ。

    純粋な vector_score 降順だと事業記述がイベント語彙と一致しやすい
    大型・有名企業ばかりになるため、7:3 の比率で中位帯候補を混ぜる。
    """

    name = "default"
    _MIX_RATIO = 0.3
    _TOP_RATIO = 7
    _MID_RATIO = 3

    def rerank(self, hits: list[dict]) -> list[dict]:
        sorted_hits = sorted(hits, key=lambda x: x["vector_score"], reverse=True)
        n = len(sorted_hits)
        if n <= 5:
            return sorted_hits

        split = max(1, int(n * (1 - self._MIX_RATIO)))
        top_band = sorted_hits[:split]
        mid_band = sorted_hits[split:]

        result: list[dict] = []
        i = j = 0
        while i < len(top_band) or j < len(mid_band):
            for _ in range(self._TOP_RATIO):
                if i >= len(top_band):
                    break
                result.append(top_band[i])
                i += 1
            for _ in range(self._MID_RATIO):
                if j >= len(mid_band):
                    break
                result.append(mid_band[j])
                j += 1
        return result


class SmallCapFirstStrategy(MatchingStrategy):
    """
    小型株優先: ベクトルスコアの低い側から候補を取る。

    大企業は事業記述がメジャーなためベクトル類似度が高くなりやすい。
    あえてスコア下位（ただし最低閾値以上）から取ることで、
    ニッチ企業・小型株を優先的に LLM 評価に回す。
    """

    name = "small_cap_first"
    _MIN_VECTOR_SCORE = 0.15

    def rerank(self, hits: list[dict]) -> list[dict]:
        filtered = [h for h in hits if h["vector_score"] >= self._MIN_VECTOR_SCORE]
        return sorted(filtered, key=lambda x: x["vector_score"])


class DiversityStrategy(MatchingStrategy):
    """
    多様性重視: 業種キャップを厳しく (max 3) + ベクトルスコア中位帯を優先。

    ベクトルスコアの上位 20% と下位 20% を除外し、中位帯を優先する。
    これにより、明らかな関連企業でも大企業でもない「隠れた関連企業」を発掘。
    """

    name = "diversity"

    @property
    def max_per_industry(self) -> int | None:
        return 3

    def rerank(self, hits: list[dict]) -> list[dict]:
        if len(hits) <= 5:
            return hits

        sorted_hits = sorted(hits, key=lambda x: x["vector_score"], reverse=True)
        n = len(sorted_hits)
        top_cut = max(1, n // 5)
        bottom_cut = max(1, n // 5)

        # 中位帯を優先、ただし上位と下位も末尾に残す
        mid_band = sorted_hits[top_cut: n - bottom_cut]
        top_band = sorted_hits[:top_cut]
        bottom_band = sorted_hits[n - bottom_cut:]

        return mid_band + top_band + bottom_band


# ---------------------------------------------------------------------------
# レジストリ
# ---------------------------------------------------------------------------

STRATEGIES: dict[str, type[MatchingStrategy]] = {
    "default": DefaultStrategy,
    "small_cap_first": SmallCapFirstStrategy,
    "diversity": DiversityStrategy,
}


def get_strategy(name: str) -> MatchingStrategy:
    """戦略名からインスタンスを取得する。未知の名前は default にフォールバック。"""
    cls = STRATEGIES.get(name, DefaultStrategy)
    return cls()
