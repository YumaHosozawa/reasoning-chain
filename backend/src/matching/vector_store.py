"""
ベクトルストア管理

Qdrant を使用して企業プロファイルの埋め込みベクトルを管理する。
初期構築・更新・検索の操作を提供する。
"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Sequence
from urllib.parse import urlparse

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    ScoredPoint,
    VectorParams,
)

from src.models import CompanyProfile

# コレクション名
COLLECTION_FULL = "company_profiles_full"
COLLECTION_SEGMENTS = "company_segments"

_EMBEDDING_DIM = 3072


class VectorStore:
    """Qdrant ベクトルストアのラッパー"""

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        resolved_url = _resolve_qdrant_url(url)
        resolved_api_key = _resolve_qdrant_api_key(
            resolved_url,
            explicit_api_key=api_key,
        )
        self._url = resolved_url
        self._client = QdrantClient(
            url=resolved_url,
            api_key=resolved_api_key,
            check_compatibility=False,
        )

    # ------------------------------------------------------------------
    # コレクション管理
    # ------------------------------------------------------------------

    def ensure_collections(self) -> None:
        """必要なコレクションが存在しなければ作成する"""
        try:
            existing = {c.name for c in self._client.get_collections().collections}
        except Exception as e:
            raise RuntimeError(_build_qdrant_connection_error(self._url, e)) from e

        if COLLECTION_FULL not in existing:
            self._client.create_collection(
                collection_name=COLLECTION_FULL,
                vectors_config=VectorParams(
                    size=_EMBEDDING_DIM, distance=Distance.COSINE
                ),
            )

        if COLLECTION_SEGMENTS not in existing:
            self._client.create_collection(
                collection_name=COLLECTION_SEGMENTS,
                vectors_config=VectorParams(
                    size=_EMBEDDING_DIM, distance=Distance.COSINE
                ),
            )

    # ------------------------------------------------------------------
    # データ格納
    # ------------------------------------------------------------------

    def upsert_company(self, profile: CompanyProfile) -> None:
        """
        企業プロファイルをベクトルストアに登録/更新する。

        profile.embedding が None の場合はスキップする。
        """
        if profile.embedding is None:
            raise ValueError(f"{profile.company_code}: embedding が設定されていません")

        point = PointStruct(
            id=_code_to_id(profile.company_code),
            vector=profile.embedding,
            payload={
                "company_code": profile.company_code,
                "company_name": profile.company_name,
                "industry_code": profile.industry_code,
                "keywords": profile.keywords,
                "last_updated": profile.last_updated,
            },
        )
        self._client.upsert(
            collection_name=COLLECTION_FULL,
            points=[point],
        )

        # セグメント単位でも登録
        for i, seg in enumerate(profile.segments):
            if not hasattr(seg, "_embedding") or seg._embedding is None:
                continue
            seg_point = PointStruct(
                id=_segment_id(profile.company_code, i),
                vector=seg._embedding,
                payload={
                    "company_code": profile.company_code,
                    "company_name": profile.company_name,
                    "industry_code": profile.industry_code,
                    "segment_name": seg.name,
                    "revenue_ratio": seg.revenue_ratio,
                    "keywords": seg.keywords,
                },
            )
            self._client.upsert(
                collection_name=COLLECTION_SEGMENTS,
                points=[seg_point],
            )

    def upsert_batch(self, profiles: Sequence[CompanyProfile]) -> None:
        """複数企業を一括登録する"""
        points = []
        for profile in profiles:
            if profile.embedding is None:
                continue
            points.append(
                PointStruct(
                    id=_code_to_id(profile.company_code),
                    vector=profile.embedding,
                    payload={
                        "company_code": profile.company_code,
                        "company_name": profile.company_name,
                        "industry_code": profile.industry_code,
                        "keywords": profile.keywords,
                        "last_updated": profile.last_updated,
                    },
                )
            )

        if points:
            # Qdrant は1バッチ100件が推奨
            for i in range(0, len(points), 100):
                self._client.upsert(
                    collection_name=COLLECTION_FULL,
                    points=points[i: i + 100],
                )

    # ------------------------------------------------------------------
    # 検索
    # ------------------------------------------------------------------

    def search(
        self,
        query_vector: list[float],
        top_k: int = 20,
        industry_code: str | None = None,
        score_threshold: float = 0.0,
    ) -> list[ScoredPoint]:
        """
        クエリベクトルに類似した企業を検索する。

        Args:
            query_vector: クエリ埋め込みベクトル
            top_k: 返す件数
            industry_code: 業種コードでフィルタリング（None で全業種）
            score_threshold: コサイン類似度の最低閾値

        Returns:
            list[ScoredPoint]: スコア付き検索結果
        """
        query_filter = None
        if industry_code:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="industry_code",
                        match=MatchValue(value=industry_code),
                    )
                ]
            )

        return self._client.search(
            collection_name=COLLECTION_FULL,
            query_vector=query_vector,
            limit=top_k,
            query_filter=query_filter,
            score_threshold=score_threshold if score_threshold > 0 else None,
        )

    def search_segments(
        self,
        query_vector: list[float],
        top_k: int = 20,
        score_threshold: float = 0.0,
    ) -> list[ScoredPoint]:
        """セグメント単位でコサイン類似度検索する"""
        return self._client.search(
            collection_name=COLLECTION_SEGMENTS,
            query_vector=query_vector,
            limit=top_k,
            score_threshold=score_threshold if score_threshold > 0 else None,
        )

    def get_company(self, company_code: str) -> dict | None:
        """証券コードで企業ペイロードを取得する"""
        results = self._client.retrieve(
            collection_name=COLLECTION_FULL,
            ids=[_code_to_id(company_code)],
            with_payload=True,
            with_vectors=False,
        )
        return results[0].payload if results else None

    def count(self) -> int:
        """登録企業数を返す"""
        return self._client.count(collection_name=COLLECTION_FULL).count


# ------------------------------------------------------------------
# ID変換ヘルパー
# ------------------------------------------------------------------

def _code_to_id(company_code: str) -> int:
    """
    証券コード（文字列）をQdrantのポイントID（整数）に変換する。
    例: "6337" → 6337
    末尾に .T などがある場合は除去する。
    """
    code = company_code.split(".")[0].strip()
    try:
        return int(code)
    except ValueError:
        # 数値でない場合はハッシュ値の絶対値を使用
        return abs(hash(company_code)) % (10 ** 9)


def _segment_id(company_code: str, segment_index: int) -> int:
    """セグメントポイントIDを生成する（企業ID * 100 + セグメントインデックス）"""
    return _code_to_id(company_code) * 100 + segment_index


def _resolve_qdrant_url(explicit_url: str | None) -> str:
    """Qdrant接続URLを決定する。"""
    if explicit_url:
        return explicit_url
    env_url = os.environ.get("QDRANT_URL")
    if env_url:
        return env_url
    endpoint = os.environ.get("QDRANT_ENDPOINT")
    if endpoint:
        return endpoint
    return "http://localhost:6333"


def _resolve_qdrant_api_key(url: str, explicit_api_key: str | None) -> str | None:
    """
    APIキーを決定する。
    ローカルHTTP接続ではキーを送らず、Qdrant clientの警告を回避する。
    """
    key = explicit_api_key if explicit_api_key is not None else os.environ.get("QDRANT_API_KEY")
    if not key:
        return None

    parsed = urlparse(url)
    is_local_http = (
        parsed.scheme == "http"
        and (parsed.hostname in {"localhost", "127.0.0.1"})
    )
    return None if is_local_http else key


def _build_qdrant_connection_error(url: str, exc: Exception) -> str:
    parsed = urlparse(url)
    is_local = parsed.hostname in {"localhost", "127.0.0.1"}
    message = [
        f"Qdrant接続に失敗しました: {url}",
        f"原因: {exc}",
    ]
    if is_local:
        message.extend(
            [
                "ローカル利用時は Docker Desktop を起動し、次を実行してください:",
                "  docker compose -f infra/docker-compose.yml up -d qdrant",
            ]
        )
    else:
        message.extend(
            [
                "クラウド利用時は QDRANT_URL (https://...) と QDRANT_API_KEY を確認してください。",
            ]
        )
    return "\n".join(message)
