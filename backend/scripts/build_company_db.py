"""
企業プロファイルDB構築スクリプト

EDINETから有価証券報告書を取得し、企業の事業内容・セグメント情報を
埋め込みベクトル化してQdrantに格納する。

使い方:
  # 直近1年分の有報を取得して全社登録（約4,000社 / 数時間かかる）
  python -m scripts.build_company_db

  # 件数を絞って動作確認（100社）
  python -m scripts.build_company_db --limit 100

  # 期間を指定
  python -m scripts.build_company_db --start 2024-04-01 --end 2025-03-31

  # 中断後の再開（登録済みコードをスキップ）
  python -m scripts.build_company_db --resume
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from tqdm import tqdm

from src.data.edinet_client import EdinetClient
from src.data.segment_parser import SegmentParser
from src.matching.embedder import Embedder
from src.matching.vector_store import VectorStore
from src.models import CompanyProfile

# 進捗ファイル（中断再開用）
_PROGRESS_FILE = Path(__file__).parent.parent / "data" / "build_progress.json"


def collect_doc_ids(
    client: EdinetClient,
    start_date: date,
    end_date: date,
    limit: int | None = None,
) -> list[dict]:
    """
    期間内の有価証券報告書メタデータを収集する。

    Returns:
        list[dict]: [{docID, edinetCode, filerName, periodEnd}, ...]
    """
    print(f"書類一覧を収集中: {start_date} 〜 {end_date}")
    docs: list[dict] = []
    current = start_date
    total_days = (end_date - start_date).days + 1

    with tqdm(total=total_days, desc="日付スキャン") as pbar:
        while current <= end_date:
            try:
                daily = client.list_documents(current)
                docs.extend(daily)
            except Exception:
                pass
            current += timedelta(days=1)
            pbar.update(1)
            time.sleep(0.3)  # EDINET APIへの負荷軽減

    # 同一EDINETコードの重複を除去（最新提出のみ残す）
    seen: dict[str, dict] = {}
    for doc in docs:
        code = doc.get("edinetCode", "")
        if code and code not in seen:
            seen[code] = doc

    result = list(seen.values())
    print(f"  ユニーク企業数: {len(result)} 社")

    if limit:
        result = result[:limit]
        print(f"  --limit により {limit} 社に絞り込み")

    return result


def load_progress() -> set[str]:
    """処理済みEDINETコードのセットを返す"""
    if _PROGRESS_FILE.exists():
        data = json.loads(_PROGRESS_FILE.read_text())
        return set(data.get("done", []))
    return set()


def save_progress(done: set[str]) -> None:
    _PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PROGRESS_FILE.write_text(json.dumps({"done": list(done)}, ensure_ascii=False))


def process_company(
    doc: dict,
    edinet_client: EdinetClient,
    segment_parser: SegmentParser,
    embedder: Embedder,
) -> CompanyProfile | None:
    """
    1社分の有報を処理してCompanyProfileを返す。
    失敗した場合は None を返す。
    """
    doc_id = doc.get("docID", "")
    edinet_code = doc.get("edinetCode", "")
    company_name = doc.get("filerName", "")

    # 証券コード（secCode）が付いていない場合はスキップ（非上場など）
    sec_code = doc.get("secCode", "")
    if not sec_code:
        return None

    # 末尾の "0" を除いた4桁コードに正規化（EDINETは5桁、例: "72030" → "7203"）
    company_code = sec_code.rstrip("0") if len(sec_code) == 5 else sec_code

    try:
        # 事業の内容を取得
        biz_desc = edinet_client.extract_business_description(doc_id)
        if not biz_desc:
            return None

        # セグメント情報を取得・解析
        seg_text = edinet_client.extract_segment_text(doc_id)
        segments = segment_parser.parse(seg_text, biz_desc)

        # 埋め込みベクトル生成
        seg_descs = [s.description for s in segments if s.description]
        seg_keywords = [kw for s in segments for kw in s.keywords]
        all_keywords = list(dict.fromkeys(seg_keywords))[:20]

        embedding = embedder.embed_company_profile(
            business_description=biz_desc,
            segment_descriptions=seg_descs,
            keywords=all_keywords,
        )

        from datetime import datetime, timezone
        return CompanyProfile(
            company_code=company_code,
            company_name=company_name,
            business_description=biz_desc[:3000],
            segments=segments,
            keywords=all_keywords,
            embedding=embedding,
            last_updated=datetime.now(timezone.utc).isoformat(),
            edinet_code=edinet_code,
        )

    except Exception as e:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="企業プロファイルDB構築")
    parser.add_argument(
        "--start",
        default=(date.today() - timedelta(days=365)).isoformat(),
        help="取得開始日 YYYY-MM-DD（デフォルト: 1年前）",
    )
    parser.add_argument(
        "--end",
        default=date.today().isoformat(),
        help="取得終了日 YYYY-MM-DD（デフォルト: 今日）",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="処理する企業数の上限（動作確認用）",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="前回の中断位置から再開する",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Qdrantへの一括登録バッチサイズ（デフォルト: 10）",
    )
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)

    # 依存コンポーネントの初期化
    edinet_client = EdinetClient(use_cache=True)
    segment_parser = SegmentParser()
    embedder = Embedder()
    vector_store = VectorStore()
    try:
        vector_store.ensure_collections()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(1)

    # 書類一覧の収集
    docs = collect_doc_ids(edinet_client, start_date, end_date, limit=args.limit)

    # 中断再開
    done_codes: set[str] = set()
    if args.resume:
        done_codes = load_progress()
        docs = [d for d in docs if d.get("edinetCode", "") not in done_codes]
        print(f"再開: 残り {len(docs)} 社（スキップ済み: {len(done_codes)} 社）")

    # メイン処理
    batch: list[CompanyProfile] = []
    success = 0
    skip = 0

    print(f"\n処理開始: {len(docs)} 社")
    for doc in tqdm(docs, desc="企業プロファイル構築"):
        profile = process_company(doc, edinet_client, segment_parser, embedder)

        if profile is None:
            skip += 1
        else:
            batch.append(profile)
            success += 1

        # バッチ登録
        if len(batch) >= args.batch_size:
            vector_store.upsert_batch(batch)
            for p in batch:
                done_codes.add(p.edinet_code)
            save_progress(done_codes)
            batch.clear()

        # API負荷軽減
        time.sleep(0.1)

    # 残りを登録
    if batch:
        vector_store.upsert_batch(batch)
        for p in batch:
            done_codes.add(p.edinet_code)
        save_progress(done_codes)

    print(f"\n完了: 登録 {success} 社 / スキップ {skip} 社")
    print(f"Qdrant 総登録数: {vector_store.count()} 社")

    edinet_client.close()


if __name__ == "__main__":
    main()
