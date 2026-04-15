"""
Markdownエクスポーター

分析結果（推論チェーン＋企業マッチング）を
Markdown形式のテキストに変換する。
"""

from __future__ import annotations

from datetime import datetime, timezone

_LEVEL_LABEL = {1: "一次", 2: "二次", 3: "三次", 4: "四次"}
_DIRECTION_LABEL = {"positive": "＋ ポジティブ", "negative": "－ ネガティブ", "mixed": "± 混在"}
_DIRECTION_SIGN = {"positive": "＋", "negative": "－", "mixed": "±"}
_INTENSITY_LABEL = {"high": "高", "medium": "中", "low": "低"}


def chain_to_markdown(chain_json: dict, matches_json: list[dict]) -> str:
    """
    推論チェーンと企業マッチング結果をMarkdown文字列に変換する。

    Args:
        chain_json: APIが返す chain_json
        matches_json: APIが返す matches_json

    Returns:
        str: Markdown形式のテキスト
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []

    # ヘッダー
    lines += [
        f"# 推論チェーン分析レポート",
        "",
        f"**生成日時**: {now}  ",
        f"**イベント**: {chain_json.get('event_summary', '')}  ",
        f"**イベント種別**: {chain_json.get('event_type', '')}  ",
        f"**推論信頼度**: {int(chain_json.get('confidence', 0) * 100)}%  ",
        "",
        "---",
        "",
    ]

    # 元のイベントテキスト
    source = chain_json.get("source_event", "")
    if source:
        lines += [
            "## 入力イベント",
            "",
            f"> {source}",
            "",
        ]

    # 推論チェーン
    lines += ["## 影響チェーン", ""]

    impacts: list[dict] = chain_json.get("impacts", [])
    max_level = max((n.get("level", 1) for n in impacts), default=0)

    for level in range(1, max_level + 1):
        nodes = [n for n in impacts if n.get("level") == level]
        if not nodes:
            continue
        label = _LEVEL_LABEL.get(level, f"{level}次")
        lines.append(f"### {label}影響")
        lines.append("")

        for node in nodes:
            sign = _DIRECTION_SIGN.get(node.get("direction", ""), "")
            intensity = _INTENSITY_LABEL.get(node.get("intensity", ""), "")
            direction = _DIRECTION_LABEL.get(node.get("direction", ""), "")
            lines += [
                f"#### {sign} {node.get('sector', '')}",
                "",
                f"| 項目 | 内容 |",
                f"|------|------|",
                f"| 影響方向 | {direction} |",
                f"| 影響強度 | {intensity} |",
                "",
                f"{node.get('description', '')}",
                "",
                f"**根拠**: {node.get('rationale', '')}",
                "",
            ]
            companies = node.get("example_companies", [])
            if companies:
                lines.append(f"**関連企業例**: {' / '.join(companies)}")
                lines.append("")
            keywords = node.get("keywords", [])
            if keywords:
                lines.append(f"**キーワード**: {' · '.join(keywords)}")
                lines.append("")

    # 企業マッチング
    if matches_json:
        lines += ["---", "", "## マッチング企業", ""]

        pos = [m for m in matches_json if m.get("direction") == "positive"]
        neg = [m for m in matches_json if m.get("direction") == "negative"]
        mix = [m for m in matches_json if m.get("direction") == "mixed"]

        for group, label in [(pos, "ポジティブ影響"), (neg, "ネガティブ影響"), (mix, "混在")]:
            if not group:
                continue
            lines += [f"### {label}", ""]
            lines += [
                "| 企業名 | 証券コード | 影響レベル | スコア | 影響強度 | 根拠 |",
                "|--------|-----------|-----------|-------|---------|------|",
            ]
            for m in group:
                intensity = _INTENSITY_LABEL.get(m.get("intensity", ""), "")
                rationale = m.get("rationale", "").replace("|", "｜")[:60]
                lines.append(
                    f"| {m.get('company_name', '')} "
                    f"| {m.get('company_code', '')} "
                    f"| {m.get('impact_level', '')}次 "
                    f"| {m.get('final_score', 0):.2f} "
                    f"| {intensity} "
                    f"| {rationale} |"
                )
            lines.append("")

        # スコア詳細
        lines += [
            "### スコア内訳",
            "",
            "| 企業名 | 総合スコア | ベクトル類似度 | LLM関連度 | セグメント構成比 |",
            "|--------|-----------|--------------|----------|----------------|",
        ]
        for m in sorted(matches_json, key=lambda x: x.get("final_score", 0), reverse=True):
            lines.append(
                f"| {m.get('company_name', '')} "
                f"| {m.get('final_score', 0):.2f} "
                f"| {m.get('vector_similarity', 0):.2f} "
                f"| {m.get('llm_relevance_score', 0):.2f} "
                f"| {m.get('segment_exposure_ratio', 0):.2f} |"
            )
        lines.append("")
    else:
        lines += ["---", "", "## マッチング企業", "", "_企業プロファイルDBが未構築のためマッチングデータなし_", ""]

    lines += [
        "---",
        "",
        "_このレポートは推論チェーン分析システムにより自動生成されました。_",
        "",
    ]

    return "\n".join(lines)
