"""
EDINETクライアント

EDINET API v2 を使用して有価証券報告書を取得し、
「事業の内容」テキストおよびセグメント情報を抽出する。

EDINET API ドキュメント:
  https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx
"""

from __future__ import annotations

import io
import os
import zipfile
from datetime import date, timedelta
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

# EDINET API v2 のベースURL
_BASE_URL = "https://disclosure2.edinet-fsa.go.jp/api/v2"

# 有価証券報告書の書類種別コード
_DOC_TYPE_ANNUAL_REPORT = "120"

# キャッシュディレクトリ
_CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "company_profiles"


class EdinetClient:
    """EDINET API クライアント"""

    def __init__(self, use_cache: bool = True) -> None:
        self._use_cache = use_cache
        self._http = httpx.Client(timeout=60.0)

    # ------------------------------------------------------------------
    # 書類一覧取得
    # ------------------------------------------------------------------

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def list_documents(
        self,
        target_date: date,
        doc_type: str = _DOC_TYPE_ANNUAL_REPORT,
    ) -> list[dict]:
        """
        指定日に提出された書類一覧を取得する。

        Returns:
            list[dict]: 各書類のメタデータリスト
                - docID: 書類管理番号
                - edinetCode: EDINETコード
                - filerName: 提出者名
                - docTypeCode: 書類種別コード
                - periodEnd: 事業年度終了日
        """
        params: dict = {
            "date": target_date.isoformat(),
            "type": 2,  # 2=メタデータ＋書類一覧
        }

        resp = self._http.get(f"{_BASE_URL}/documents.json", params=params)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if doc_type:
            results = [r for r in results if r.get("docTypeCode") == doc_type]
        return results

    def list_annual_reports_range(
        self,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        """
        期間内に提出された有価証券報告書の一覧をまとめて取得する。

        Note:
            EDINET APIは1日単位でしか取得できないため、
            指定範囲を1日ずつループして収集する。
        """
        docs: list[dict] = []
        current = start_date
        while current <= end_date:
            try:
                docs.extend(self.list_documents(current))
            except httpx.HTTPError:
                pass  # 該当日にデータがない場合はスキップ
            current += timedelta(days=1)
        return docs

    # ------------------------------------------------------------------
    # 書類取得・テキスト抽出
    # ------------------------------------------------------------------

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def download_document(self, doc_id: str) -> bytes:
        """
        書類管理番号から書類ZIPを取得してバイト列を返す。
        """
        cache_path = _CACHE_DIR / f"{doc_id}.zip"
        if self._use_cache and cache_path.exists():
            return cache_path.read_bytes()

        params: dict = {"type": 5}  # 5=XBRL形式

        resp = self._http.get(
            f"{_BASE_URL}/documents/{doc_id}", params=params
        )
        resp.raise_for_status()

        if self._use_cache:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(resp.content)

        return resp.content

    def extract_business_description(self, doc_id: str) -> str:
        """
        有報ZIPから「事業の内容」テキストを抽出する。

        Returns:
            str: 事業の内容テキスト（抽出失敗時は空文字）
        """
        zip_bytes = self.download_document(doc_id)
        return _extract_section_from_zip(zip_bytes, section_tag="BusinessDescription")

    def extract_segment_text(self, doc_id: str) -> str:
        """
        有報ZIPからセグメント情報テキストを抽出する。

        Returns:
            str: セグメント情報テキスト（抽出失敗時は空文字）
        """
        zip_bytes = self.download_document(doc_id)
        return _extract_section_from_zip(zip_bytes, section_tag="SegmentInformation")

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "EdinetClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()


# ------------------------------------------------------------------
# 内部ヘルパー
# ------------------------------------------------------------------

def _extract_section_from_zip(zip_bytes: bytes, section_tag: str) -> str:
    """
    ZIPファイル内のXBRL/HTMLファイルから指定セクションのテキストを抽出する。

    EDINET有報のZIPは複数のXBRL/TXTファイルを含む。
    ここでは主報告書HTMLファイルからlxmlでテキストを取り出す。
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            # 主報告書HTML（jpcrp030000-asr-001_E*.htm のパターン）を探す
            target_files = [
                name for name in zf.namelist()
                if name.endswith(".htm") and "asr" in name
            ]
            if not target_files:
                # フォールバック: 全HTMファイルを試す
                target_files = [n for n in zf.namelist() if n.endswith(".htm")]

            for fname in target_files:
                with zf.open(fname) as f:
                    content = f.read().decode("utf-8", errors="replace")
                    text = _parse_section_from_html(content, section_tag)
                    if text:
                        return text
    except (zipfile.BadZipFile, Exception):
        pass
    return ""


def _parse_section_from_html(html: str, section_tag: str) -> str:
    """
    HTMLテキストから指定セクションのテキストを取り出す。

    lxmlを使ったXPath検索でセクションタグを探す。
    EDINET XBRLの名前空間は複数あるため、ローカル名で検索する。
    """
    try:
        from lxml import etree

        parser = etree.HTMLParser()
        tree = etree.fromstring(html.encode("utf-8"), parser)

        # XBRL要素名でのXPath（名前空間を無視）
        elements = tree.xpath(
            f"//*[local-name()='{section_tag}']"
        )
        if elements:
            texts = []
            for el in elements:
                texts.append(
                    " ".join(el.itertext()).strip()
                )
            return "\n".join(texts)

        # フォールバック: セクション見出しのテキスト検索
        _SECTION_KEYWORDS = {
            "BusinessDescription": ["事業の内容", "事業内容"],
            "SegmentInformation": ["セグメント情報", "セグメント別", "事業の種類別"],
        }
        keywords = _SECTION_KEYWORDS.get(section_tag, [])
        for kw in keywords:
            idx = html.find(kw)
            if idx >= 0:
                return html[idx: idx + 3000]

    except Exception:
        pass
    return ""
