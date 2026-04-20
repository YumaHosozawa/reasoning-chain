"""
企業コンテキスト一括更新スクリプト

3つのデータソースから企業の最新定性情報を取得し、
LLM で要約して SQLite に保存する。

データソース:
  1. EDINET — 有報・四半期報告書から経営方針/MD&A/事業リスク等を抽出
  2. TDNet  — 適時開示（決算短信・業績修正等）
  3. IR ニュース — 企業 IR ページからのプレスリリース

使い方:
  # 全社の直近90日分を取得（上限100社）
  python -m scripts.update_company_context --limit 100

  # 特定企業のみ
  python -m scripts.update_company_context --company-code 7203

  # EDINET のみ（TDNet/IR をスキップ）
  python -m scripts.update_company_context --source edinet --limit 50

  # 取得期間を変更
  python -m scripts.update_company_context --days-back 180 --limit 50
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from tqdm import tqdm

from backend.db.session import SessionLocal, init_db
from backend.db.crud import upsert_company_context
from src.data.edinet_client import EdinetClient, QUALITATIVE_DOC_TYPES
from src.data.tdnet_client import TdnetClient
from src.data.ir_fetcher import fetch_ir_news, get_ir_url


# EDINET セクションタグ → company_context の context_type マッピング
_EDINET_SECTION_CONTEXT_TYPE: dict[str, str] = {
    "ManagementPolicy": "midterm_plan",
    "ManagementAnalysis": "earnings_summary",
    "BusinessRisks": "ir_news",
    "ResearchAndDevelopment": "ir_news",
    "CapitalExpenditure": "ir_news",
}

# EDINET セクションタグ → 日本語ラベル
_EDINET_SECTION_LABEL: dict[str, str] = {
    "ManagementPolicy": "経営方針",
    "ManagementAnalysis": "経営者による分析 (MD&A)",
    "BusinessRisks": "事業等のリスク",
    "ResearchAndDevelopment": "研究開発活動",
    "CapitalExpenditure": "設備投資等の概要",
}

_MAX_SUMMARY_CHARS = 500


def main() -> None:
    parser = argparse.ArgumentParser(description="企業コンテキスト一括更新")
    parser.add_argument("--company-code", type=str, default=None, help="特定企業のみ更新")
    parser.add_argument("--limit", type=int, default=None, help="処理する企業数の上限")
    parser.add_argument("--days-back", type=int, default=90, help="遡る日数 (default: 90)")
    parser.add_argument(
        "--source",
        type=str,
        default="all",
        choices=["all", "edinet", "tdnet", "ir"],
        help="データソースを限定 (default: all)",
    )
    args = parser.parse_args()

    use_edinet = args.source in ("all", "edinet")
    use_tdnet = args.source in ("all", "tdnet")
    use_ir = args.source in ("all", "ir")

    init_db()
    db = SessionLocal()

    if args.company_code:
        codes = [args.company_code]
    else:
        codes = _get_company_codes_from_qdrant(args.limit)

    if not codes:
        print("対象企業がありません。build_company_db を先に実行してください。")
        return

    sources_str = []
    if use_edinet:
        sources_str.append("EDINET")
    if use_tdnet:
        sources_str.append("TDNet")
    if use_ir:
        sources_str.append("IR")
    print(f"対象企業数: {len(codes)}, 遡る日数: {args.days_back}, ソース: {'/'.join(sources_str)}")

    edinet = EdinetClient() if use_edinet else None
    tdnet = TdnetClient() if use_tdnet else None

    total_saved = 0
    today = date.today()
    start_date = today - timedelta(days=args.days_back)

    for code in tqdm(codes, desc="企業コンテキスト更新"):
        saved = 0

        # --- EDINET ---
        if edinet:
            saved += _fetch_edinet_context(edinet, db, code, start_date, today)

        # --- TDNet ---
        if tdnet:
            saved += _fetch_tdnet_context(tdnet, db, code, args.days_back)

        # --- IR ニュース ---
        if use_ir:
            saved += _fetch_ir_context(db, code)

        total_saved += saved
        time.sleep(0.3)

    if edinet:
        edinet.close()
    db.close()
    print(f"\n完了: {total_saved} 件のコンテキストを保存しました。")


def _fetch_edinet_context(
    edinet: EdinetClient,
    db,
    company_code: str,
    start_date: date,
    end_date: date,
) -> int:
    """EDINET から定性情報を取得して保存する。"""
    saved = 0
    try:
        docs = edinet.list_documents_for_company(
            sec_code=company_code,
            start_date=start_date,
            end_date=end_date,
        )
        if not docs:
            return 0

        # 直近3件に絞る（API コール数制限）
        for doc in docs[:3]:
            doc_id = doc.get("docID")
            doc_desc = doc.get("docDescription", "")
            period_end = doc.get("periodEnd", "")
            if not doc_id:
                continue

            try:
                sections = edinet.extract_qualitative_sections(doc_id)
            except Exception as e:
                tqdm.write(f"  [{company_code}] EDINET 抽出エラー ({doc_id}): {e}")
                continue

            for tag, text in sections.items():
                if not text or len(text) < 50:
                    continue

                label = _EDINET_SECTION_LABEL.get(tag, tag)
                ctx_type = _EDINET_SECTION_CONTEXT_TYPE.get(tag, "ir_news")
                title = f"{doc_desc} - {label}" if doc_desc else label

                # LLM で要約
                summary = _summarize_edinet_section(text, label)

                upsert_company_context(
                    db,
                    company_code=company_code,
                    context_type=ctx_type,
                    title=title,
                    summary=summary,
                    source_url=f"https://disclosure2.edinet-fsa.go.jp/api/v2/documents/{doc_id}",
                    published_date=period_end or end_date.isoformat(),
                )
                saved += 1

    except Exception as e:
        tqdm.write(f"  [{company_code}] EDINET エラー: {e}")
    return saved


def _fetch_tdnet_context(tdnet: TdnetClient, db, company_code: str, days_back: int) -> int:
    """TDNet から適時開示情報を取得して保存する。"""
    saved = 0
    try:
        disclosures = tdnet.fetch_recent_disclosures(company_code, days_back=days_back)
        for disc in disclosures[:5]:
            text = tdnet.download_text(disc["url"])
            if not text:
                continue
            summary = tdnet.summarize(text, title=disc["title"])
            if not summary:
                continue

            upsert_company_context(
                db,
                company_code=company_code,
                context_type=disc["context_type"],
                title=disc["title"],
                summary=summary,
                source_url=disc["url"],
                published_date=disc["date"],
            )
            saved += 1
    except Exception as e:
        tqdm.write(f"  [{company_code}] TDNet エラー: {e}")
    return saved


def _fetch_ir_context(db, company_code: str) -> int:
    """IR ニュースを取得して保存する。"""
    saved = 0
    ir_url = get_ir_url(company_code)
    if not ir_url:
        return 0
    try:
        news = fetch_ir_news(company_code, ir_url=ir_url, limit=3)
        for item in news:
            if not item.get("title"):
                continue
            upsert_company_context(
                db,
                company_code=company_code,
                context_type=item.get("context_type", "ir_news"),
                title=item["title"],
                summary=item["title"],
                source_url=item.get("url", ""),
                published_date=item.get("date", ""),
            )
            saved += 1
    except Exception as e:
        tqdm.write(f"  [{company_code}] IR エラー: {e}")
    return saved


def _summarize_edinet_section(text: str, section_label: str) -> str:
    """EDINET セクションテキストを Haiku で要約する。"""
    if len(text) < 100:
        return text[:_MAX_SUMMARY_CHARS]

    try:
        import anthropic
    except ImportError:
        return text[:_MAX_SUMMARY_CHARS]

    client = anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )

    prompt = (
        f"以下は上場企業の有価証券報告書の「{section_label}」セクションです。\n"
        f"投資判断に重要なポイントに絞って日本語で{_MAX_SUMMARY_CHARS}文字以内に要約してください。\n"
        f"特に以下の点を含めてください:\n"
        f"- 経営戦略の転換点や新規事業\n"
        f"- 具体的な数値目標（売上・利益・シェア等）\n"
        f"- リスク要因と対応策\n\n"
        f"本文:\n{text[:5000]}"
    )

    try:
        response = client.messages.create(
            model=os.environ.get("SUMMARIZE_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()[:_MAX_SUMMARY_CHARS]
    except Exception:
        return text[:_MAX_SUMMARY_CHARS]


def _get_company_codes_from_qdrant(limit: int | None) -> list[str]:
    """Qdrant に登録済みの企業コードを取得する。"""
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(
            url=os.environ.get("QDRANT_URL", "http://localhost:6333"),
            api_key=os.environ.get("QDRANT_API_KEY") or None,
        )

        codes: list[str] = []
        offset = None
        batch_size = 100

        while True:
            result = client.scroll(
                collection_name="company_profiles_full",
                limit=batch_size,
                offset=offset,
                with_payload=["company_code"],
                with_vectors=False,
            )
            points, next_offset = result
            for p in points:
                code = p.payload.get("company_code")
                if code:
                    codes.append(code)
            if next_offset is None or (limit and len(codes) >= limit):
                break
            offset = next_offset

        if limit:
            codes = codes[:limit]
        return codes
    except Exception as e:
        print(f"Qdrant 接続エラー: {e}")
        return []


if __name__ == "__main__":
    main()
