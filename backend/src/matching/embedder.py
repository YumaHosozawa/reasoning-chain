"""
埋め込みモデルラッパー

OpenAI text-embedding-3-large を使用して
企業プロファイルテキストと影響ノードテキストをベクトル化する。
"""

from __future__ import annotations

import os
import time
from typing import Sequence

import openai
from tenacity import retry, stop_after_attempt, wait_exponential

_DEFAULT_MODEL = "text-embedding-3-large"
_EMBEDDING_DIM = 3072
_BATCH_SIZE = 100  # OpenAI API のバッチ上限


class Embedder:
    """OpenAI 埋め込みモデルのラッパー"""

    def __init__(self, model: str | None = None) -> None:
        self._client = openai.OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY")
        )
        self.model = model or os.environ.get("EMBEDDING_MODEL", _DEFAULT_MODEL)
        self.dim = _EMBEDDING_DIM

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def embed(self, text: str) -> list[float]:
        """
        単一テキストをベクトル化する。

        Args:
            text: 埋め込み対象テキスト

        Returns:
            list[float]: 埋め込みベクトル（dim=3072）
        """
        text = _normalize_text(text)
        response = self._client.embeddings.create(
            input=text,
            model=self.model,
        )
        return response.data[0].embedding

    def embed_batch(
        self,
        texts: Sequence[str],
        show_progress: bool = False,
    ) -> list[list[float]]:
        """
        複数テキストを一括でベクトル化する（バッチ処理）。

        Args:
            texts: 埋め込み対象テキストのリスト
            show_progress: tqdm でプログレスバーを表示するか

        Returns:
            list[list[float]]: 各テキストの埋め込みベクトルリスト
        """
        texts = [_normalize_text(t) for t in texts]
        results: list[list[float]] = []

        batches = [
            texts[i: i + _BATCH_SIZE]
            for i in range(0, len(texts), _BATCH_SIZE)
        ]

        iterator = batches
        if show_progress:
            try:
                from tqdm import tqdm
                iterator = tqdm(batches, desc="Embedding")
            except ImportError:
                pass

        for batch in iterator:
            embeddings = self._embed_batch_single(batch)
            results.extend(embeddings)
            # レート制限への配慮（1秒あたり上限を超えないよう）
            if len(batches) > 1:
                time.sleep(0.2)

        return results

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def _embed_batch_single(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(
            input=texts,
            model=self.model,
        )
        # APIはinput順にソートして返す
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]

    def embed_impact(self, impact_description: str, keywords: list[str]) -> list[float]:
        """
        影響ノードのテキストとキーワードを連結して埋め込みベクトルを生成する。

        Args:
            impact_description: 影響の説明テキスト
            keywords: マッチング用キーワードリスト

        Returns:
            list[float]: 埋め込みベクトル
        """
        combined = f"{impact_description}\n関連キーワード: {' '.join(keywords)}"
        return self.embed(combined)

    def embed_company_profile(
        self,
        business_description: str,
        segment_descriptions: list[str] | None = None,
        keywords: list[str] | None = None,
    ) -> list[float]:
        """
        企業プロファイルテキストを埋め込みベクトルに変換する。

        事業説明 + セグメント説明 + キーワードを連結して埋め込む。
        """
        parts = [business_description[:2000]]
        if segment_descriptions:
            parts.append("セグメント: " + " / ".join(segment_descriptions[:5]))
        if keywords:
            parts.append("キーワード: " + " ".join(keywords[:20]))
        combined = "\n".join(parts)
        return self.embed(combined)


def _normalize_text(text: str) -> str:
    """
    埋め込み前のテキスト正規化。
    空白・改行の正規化と長さ制限（OpenAI上限: 8191トークン ≒ 32,000文字）。
    """
    text = " ".join(text.split())  # 連続空白・改行を単一スペースに
    return text[:30000]
