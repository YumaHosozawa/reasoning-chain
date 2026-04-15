"""
エクスポートエンドポイント

GET /api/results/{id}/export/markdown  - Markdownファイルをダウンロード
GET /api/results/{id}/export/data      - PDF生成用の生データを返す
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.db import crud
from src.output.exporter import chain_to_markdown

router = APIRouter(prefix="/api/results", tags=["export"])


@router.get("/{result_id}/export/markdown")
def export_markdown(result_id: str, db: Session = Depends(get_db)):
    """
    分析結果をMarkdownファイルとしてダウンロードする。
    """
    record = crud.get_result(db, result_id)
    if record is None:
        raise HTTPException(status_code=404, detail="結果が見つかりません")

    md = chain_to_markdown(record.chain_json, record.matches_json)

    # ファイル名に使えるイベント名（先頭20文字）
    safe_name = record.event_summary[:20].replace(" ", "_").replace("/", "-")
    filename = f"reasoning_chain_{safe_name}.md"

    return Response(
        content=md.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename*=UTF-8\'\'{filename}',
        },
    )


@router.get("/{result_id}/export/data")
def export_data(result_id: str, db: Session = Depends(get_db)):
    """
    PDF生成用のデータをJSONで返す（フロントエンドでのPDF生成に使用）。
    """
    record = crud.get_result(db, result_id)
    if record is None:
        raise HTTPException(status_code=404, detail="結果が見つかりません")

    return {
        "id": record.id,
        "event_text": record.event_text,
        "event_summary": record.event_summary,
        "event_type": record.event_type,
        "confidence": record.confidence,
        "created_at": record.created_at.isoformat(),
        "chain_json": record.chain_json,
        "matches_json": record.matches_json,
        "total_impacts": record.total_impacts,
        "total_matches": record.total_matches,
    }
