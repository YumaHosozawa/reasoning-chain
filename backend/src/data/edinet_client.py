"""
EDINETクライアント

EDINET API v2 を使用して有価証券報告書・四半期報告書・臨時報告書等を取得し、
企業の定性情報テキストを抽出する。

EDINET API ドキュメント:
  https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx

主な書類種別コード:
  120 - 有価証券報告書 (annual securities report)
  130 - 訂正有価証券報告書
  140 - 四半期報告書 (quarterly report)
  150 - 訂正四半期報告書
  160 - 半期報告書 (semi-annual report)
  030 - 臨時報告書 (extraordinary report)
  350 - 大量保有報告書
"""

from __future__ import annotations

import io
import os
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

# EDINET API v2 のベースURL
_BASE_URL = "https://disclosure2.edinet-fsa.go.jp/api/v2"

# 書類種別コード定数
DOC_TYPE_ANNUAL_REPORT = "120"
DOC_TYPE_QUARTERLY_REPORT = "140"
DOC_TYPE_SEMIANNUAL_REPORT = "160"
DOC_TYPE_EXTRAORDINARY_REPORT = "030"

# 定性情報の抽出に使用する書類種別
QUALITATIVE_DOC_TYPES = [
    DOC_TYPE_ANNUAL_REPORT,
    DOC_TYPE_QUARTERLY_REPORT,
    DOC_TYPE_SEMIANNUAL_REPORT,
    DOC_TYPE_EXTRAORDINARY_REPORT,
]

# キャッシュディレクトリ
_CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "company_profiles"

# 抽出可能なセクションタグとフォールバックキーワードの定義
_SECTION_CONFIG: dict[str, list[str]] = {
    "BusinessDescription": ["事業の内容", "事業内容"],
    "SegmentInformation": ["セグメント情報", "セグメント別", "事業の種類別"],
    "ManagementPolicy": [
        "経営方針",
        "経営上の目標の達成状況を判断するための客観的な指標等",
        "会社の経営の基本方針",
        "中長期的な会社の経営戦略",
    ],
    "ManagementAnalysis": [
        "経営者による財政状態、経営成績及びキャッシュ・フローの状況の分析",
        "経営成績等の状況の概要",
        "業績等の概要",
        "MD&A",
    ],
    "BusinessRisks": [
        "事業等のリスク",
        "リスク情報",
    ],
    "ResearchAndDevelopment": [
        "研究開発活動",
        "研究開発",
    ],
    "CapitalExpenditure": [
        "設備投資等の概要",
        "設備の新設",
    ],
}


class EdinetClient:
    """EDINET API クライアント"""

    def __init__(self, use_cache: bool = True, api_key: str | None = None) -> None:
        self._use_cache = use_cache
        self._api_key = api_key or os.environ.get("EDINET_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "EDINET API キーが設定されていません。"
                "環境変数 EDINET_API_KEY を設定するか、"
                "コンストラクタの api_key 引数で渡してください。"
                "\n取得先: https://disclosure2.edinet-fsa.go.jp/weee0010.aspx"
            )
        self._http = httpx.Client(timeout=60.0)

    # ------------------------------------------------------------------
    # 書類一覧取得
    # ------------------------------------------------------------------

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def list_documents(
        self,
        target_date: date,
        doc_type: str = DOC_TYPE_ANNUAL_REPORT,
    ) -> list[dict]:
        """
        指定日に提出された書類一覧を取得する。

        Args:
            target_date: 対象日
            doc_type: 書類種別コード。空文字で全種別。

        Returns:
            list[dict]: 各書類のメタデータリスト
                - docID: 書類管理番号
                - edinetCode: EDINETコード
                - filerName: 提出者名
                - secCode: 証券コード (5桁、末尾0)
                - docTypeCode: 書類種別コード
                - periodEnd: 事業年度終了日
                - docDescription: 書類名称
        """
        params: dict = {
            "date": target_date.isoformat(),
            "type": 2,  # 2=メタデータ＋書類一覧
            "Subscription-Key": self._api_key,
        }

        resp = self._http.get(f"{_BASE_URL}/documents.json", params=params)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if doc_type:
            results = [r for r in results if r.get("docTypeCode") == doc_type]
        return results

    def list_qualitative_documents(
        self,
        target_date: date,
        doc_types: list[str] | None = None,
    ) -> list[dict]:
        """
        指定日の定性情報取得対象書類を返す（複数書類種別に対応）。

        Args:
            target_date: 対象日
            doc_types: 取得する書類種別コードのリスト。None で全定性情報対象種別。
        """
        types = doc_types or QUALITATIVE_DOC_TYPES
        params: dict = {
            "date": target_date.isoformat(),
            "type": 2,
            "Subscription-Key": self._api_key,
        }
        resp = self._http.get(f"{_BASE_URL}/documents.json", params=params)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        return [r for r in results if r.get("docTypeCode") in types]

    def list_documents_for_company(
        self,
        sec_code: str,
        start_date: date,
        end_date: date,
        doc_types: list[str] | None = None,
    ) -> list[dict]:
        """
        特定企業の書類一覧を期間指定で取得する。

        Args:
            sec_code: 証券コード（4桁 or 5桁）
            start_date: 検索開始日
            end_date: 検索終了日
            doc_types: 書類種別コードのリスト。None で全定性情報対象種別。

        Returns:
            list[dict]: 該当する書類のメタデータリスト
        """
        types = doc_types or QUALITATIVE_DOC_TYPES
        # EDINET の secCode は5桁 (末尾0) なので正規化
        code_5 = sec_code.split(".")[0].strip()
        if len(code_5) == 4:
            code_5 = code_5 + "0"

        docs: list[dict] = []
        current = start_date
        while current <= end_date:
            try:
                day_docs = self.list_qualitative_documents(current, types)
                for d in day_docs:
                    if d.get("secCode") == code_5:
                        docs.append(d)
            except httpx.HTTPError:
                pass
            current += timedelta(days=1)
        return docs

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

        params: dict = {"type": 5, "Subscription-Key": self._api_key}  # 5=XBRL形式

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

    def extract_section(self, doc_id: str, section_tag: str) -> str:
        """
        書類ZIPから任意のセクションテキストを抽出する。

        Args:
            doc_id: 書類管理番号
            section_tag: セクションタグ名 (_SECTION_CONFIG のキー)

        Returns:
            str: セクションテキスト（抽出失敗時は空文字）
        """
        zip_bytes = self.download_document(doc_id)
        return _extract_section_from_zip(zip_bytes, section_tag=section_tag)

    def extract_qualitative_sections(self, doc_id: str) -> dict[str, str]:
        """
        書類から定性情報セクションをまとめて抽出する。

        経営方針・MD&A・事業リスク・研究開発・設備投資を一括抽出し、
        {セクション名: テキスト} の辞書を返す。空テキストのセクションは含めない。

        Returns:
            dict[str, str]: セクション名 → テキスト
        """
        zip_bytes = self.download_document(doc_id)
        qualitative_tags = [
            "ManagementPolicy",
            "ManagementAnalysis",
            "BusinessRisks",
            "ResearchAndDevelopment",
            "CapitalExpenditure",
        ]
        result: dict[str, str] = {}
        for tag in qualitative_tags:
            text = _extract_section_from_zip(zip_bytes, section_tag=tag)
            if text:
                result[tag] = text
        return result

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
        keywords = _SECTION_CONFIG.get(section_tag, [])
        for kw in keywords:
            idx = html.find(kw)
            if idx >= 0:
                return html[idx: idx + 3000]

    except Exception:
        pass
    return ""
