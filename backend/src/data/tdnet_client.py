"""
TDNet (適時開示ネットワーク) クライアント

決算短信・適時開示情報を取得し、LLM で要約する。
TDNet は東証が運営する適時開示情報配信システムで、
上場企業の重要な経営情報（決算・中計・業績修正等）が即時公開される。

TDNet 開示一覧:
  https://www.release.tdnet.info/inbs/
"""

from __future__ import annotations

import os
import re
from datetime import date, timedelta

import httpx
from lxml import html
from tenacity import retry, stop_after_attempt, wait_exponential

_TDNET_BASE = "https://www.release.tdnet.info/inbs"

_CONTEXT_TYPE_MAP: dict[str, str] = {
    "決算短信": "earnings_summary",
    "業績予想の修正": "earnings_summary",
    "配当予想の修正": "earnings_summary",
    "中期経営計画": "midterm_plan",
    "経営計画": "midterm_plan",
}

_MAX_SUMMARY_CHARS = 500


class TdnetClient:
    """TDNet 適時開示フェッチャー"""

    def __init__(self) -> None:
        self._http = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; ReasoningChain/1.0)",
            },
        )

    def fetch_recent_disclosures(
        self,
        company_code: str,
        days_back: int = 90,
    ) -> list[dict]:
        """
        指定企業の直近 N 日間の適時開示を取得する。

        Returns:
            list[dict]: 各要素は {title, url, date, context_type}
        """
        results: list[dict] = []
        today = date.today()

        for day_offset in range(0, days_back, 1):
            target = today - timedelta(days=day_offset)
            try:
                page_results = self._fetch_day(target, company_code)
                results.extend(page_results)
            except Exception:
                continue

            if len(results) >= 20:
                break

        return results

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=5))
    def _fetch_day(self, target: date, company_code: str) -> list[dict]:
        """1日分の開示一覧から指定企業のものを抽出する。"""
        date_str = target.strftime("%Y%m%d")
        url = f"{_TDNET_BASE}/I_list_{date_str}.html"

        resp = self._http.get(url)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()

        tree = html.fromstring(resp.content)
        rows = tree.xpath('//table[@class="main-table" or @id="main-list-table"]//tr')

        results: list[dict] = []
        code_4 = company_code.split(".")[0].strip()[:4]

        for row in rows:
            cells = row.xpath(".//td")
            if len(cells) < 4:
                continue

            row_text = row.text_content()
            if code_4 not in row_text:
                continue

            link = row.xpath('.//td[@class="kjTitle" or @class="title"]//a/@href')
            title_el = row.xpath('.//td[@class="kjTitle" or @class="title"]//a')
            if not link or not title_el:
                link = row.xpath(".//a/@href")
                title_el = row.xpath(".//a")
            if not link or not title_el:
                continue

            title = title_el[0].text_content().strip()
            doc_url = link[0] if link[0].startswith("http") else f"{_TDNET_BASE}/{link[0]}"

            context_type = _classify_disclosure(title)

            results.append({
                "title": title,
                "url": doc_url,
                "date": target.isoformat(),
                "context_type": context_type,
            })

        return results

    def download_text(self, url: str) -> str:
        """開示文書の本文テキストを取得する。HTML の場合はテキスト抽出。"""
        try:
            resp = self._http.get(url)
            resp.raise_for_status()
        except Exception:
            return ""

        content_type = resp.headers.get("content-type", "")

        if "html" in content_type or "xml" in content_type:
            tree = html.fromstring(resp.content)
            text = tree.text_content()
            text = re.sub(r"\s+", " ", text).strip()
            return text[:8000]

        if "pdf" in content_type:
            try:
                import pdfplumber

                import io
                with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                    pages_text = []
                    for page in pdf.pages[:5]:
                        t = page.extract_text()
                        if t:
                            pages_text.append(t)
                    return "\n".join(pages_text)[:8000]
            except ImportError:
                return ""
            except Exception:
                return ""

        return resp.text[:8000]

    def summarize(self, text: str, title: str = "") -> str:
        """Haiku を使って開示テキストを 500 chars 以内に要約する。"""
        if not text or len(text) < 50:
            return text

        try:
            import anthropic
        except ImportError:
            return text[:_MAX_SUMMARY_CHARS]

        client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
        )
        prompt = (
            f"以下の適時開示文書を、投資判断に重要なポイントに絞って"
            f"日本語で{_MAX_SUMMARY_CHARS}文字以内に要約してください。"
            f"数値（売上・利益・成長率等）は必ず含めてください。\n\n"
        )
        if title:
            prompt += f"タイトル: {title}\n\n"
        prompt += f"本文:\n{text[:4000]}"

        try:
            response = client.messages.create(
                model=os.environ.get("SUMMARIZE_MODEL", "claude-haiku-4-5-20251001"),
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()[:_MAX_SUMMARY_CHARS]
        except Exception:
            return text[:_MAX_SUMMARY_CHARS]


def _classify_disclosure(title: str) -> str:
    """開示タイトルからコンテキスト種別を推定する。"""
    for keyword, ctx_type in _CONTEXT_TYPE_MAP.items():
        if keyword in title:
            return ctx_type
    return "ir_news"
