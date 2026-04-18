"""
IR ニュースフェッチャー

企業の IR ページからプレスリリース・ニュース一覧を取得する。
IR ページの URL は backend/data/ir_sources.json に証券コード → URL の
マッピングとして管理する。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
from lxml import html

_SOURCES_PATH = Path(__file__).parent.parent.parent / "data" / "ir_sources.json"


def load_ir_sources() -> dict[str, str]:
    """ir_sources.json を読み込み {company_code: ir_page_url} を返す。"""
    if not _SOURCES_PATH.exists():
        return {}
    try:
        return json.loads(_SOURCES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_ir_url(company_code: str) -> str | None:
    """指定企業の IR ページ URL を返す。未登録なら None。"""
    sources = load_ir_sources()
    return sources.get(company_code.split(".")[0].strip())


def fetch_ir_news(
    company_code: str,
    ir_url: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """
    企業 IR ページからニュース一覧を取得する。

    Args:
        company_code: 証券コード
        ir_url: IR ページの URL (None なら ir_sources.json から取得)
        limit: 取得件数上限

    Returns:
        list[dict]: {title, url, date, context_type} のリスト
    """
    url = ir_url or get_ir_url(company_code)
    if not url:
        return []

    try:
        client = httpx.Client(
            timeout=20.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; ReasoningChain/1.0)",
            },
        )
        resp = client.get(url)
        resp.raise_for_status()
    except Exception:
        return []

    tree = html.fromstring(resp.content)

    results: list[dict] = []

    # 一般的な IR ページのニュース一覧を抽出 (各社フォーマットは異なるが共通パターンを探す)
    # パターン 1: <dl> or <ul> ベースのニュースリスト
    for link_el in tree.xpath("//a[contains(@href, 'pdf') or contains(@href, 'news') or contains(@href, 'ir')]"):
        title = link_el.text_content().strip()
        if not title or len(title) < 5:
            continue

        href = link_el.get("href", "")
        if not href:
            continue
        if not href.startswith("http"):
            href = _resolve_url(url, href)

        # 日付を前後の要素から探す
        date_str = _find_nearby_date(link_el)

        results.append({
            "title": title[:200],
            "url": href,
            "date": date_str or "",
            "context_type": _classify_ir_title(title),
        })

        if len(results) >= limit:
            break

    return results


def _resolve_url(base: str, relative: str) -> str:
    """相対URLを絶対URLに変換する。"""
    from urllib.parse import urljoin
    return urljoin(base, relative)


def _find_nearby_date(element) -> str | None:
    """リンク要素の近くにある日付文字列を探す。"""
    # 親要素のテキストから日付パターンを探す
    parent = element.getparent()
    if parent is None:
        return None

    text = parent.text_content()
    # YYYY/MM/DD or YYYY.MM.DD or YYYY-MM-DD
    match = re.search(r"(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})", text)
    if match:
        y, m, d = match.groups()
        return f"{y}-{int(m):02d}-{int(d):02d}"

    # 前の兄弟要素も探す
    prev = element.getprevious()
    if prev is not None:
        prev_text = prev.text_content()
        match = re.search(r"(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})", prev_text)
        if match:
            y, m, d = match.groups()
            return f"{y}-{int(m):02d}-{int(d):02d}"

    return None


def _classify_ir_title(title: str) -> str:
    """IR ニュースのタイトルからコンテキスト種別を推定する。"""
    keywords_earnings = ["決算", "業績", "配当", "四半期", "通期"]
    keywords_plan = ["中期経営", "中計", "経営計画", "成長戦略", "ビジョン"]

    for kw in keywords_earnings:
        if kw in title:
            return "earnings_summary"
    for kw in keywords_plan:
        if kw in title:
            return "midterm_plan"
    return "ir_news"
