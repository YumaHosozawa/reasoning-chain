"""
推論チェーン生成・スコアリング用プロンプトテンプレート
"""

CHAIN_GENERATION_SYSTEM = """\
あなたは金融・経済の専門家です。
マクロ経済イベントを分析し、企業業績への影響を多段階で推論します。
必ず指定されたJSON形式のみを出力してください。説明文や前置きは不要です。
"""

CHAIN_GENERATION_USER = """\
以下のマクロ経済イベントが発生した場合の影響を、段階的に推論してください。

イベント: {event_description}

以下の形式でJSONを出力してください（コードブロックなし、JSONのみ）:

{{
  "event_summary": "イベントの簡潔な要約（1文）",
  "event_type": "geopolitical|monetary|commodity|regulatory|natural_disaster|other のいずれか",
  "confidence": 0.0から1.0の数値,
  "impacts": [
    {{
      "level": 1,
      "sector": "影響を受けるセクター/業界名",
      "description": "影響の詳細説明（2〜3文）",
      "direction": "positive|negative|mixed のいずれか",
      "intensity": "high|medium|low のいずれか",
      "rationale": "なぜこの影響が生じるかの因果関係説明（1〜2文）",
      "example_companies": ["企業名1", "企業名2"],
      "keywords": ["キーワード1", "キーワード2", "キーワード3"],
      "expected_return_pct_low": -0.12,
      "expected_return_pct_high": -0.03,
      "time_horizon": "immediate|1-4w|1-3m|3-12m のいずれか",
      "probability": 0.0から1.0の数値
    }}
  ]
}}

推論ルール:
- level 1（一次影響）: イベントの直接的影響。必ず含める。
- level 2（二次影響）: 一次影響から派生する間接影響。必ず含める。
- level 3（三次影響）: 二次影響からさらに派生する影響。可能な場合に含める。
- level 4（四次影響）: 明確な因果関係がある場合のみ含める。
- 各レベルで複数の影響を列挙してよい（ポジティブ・ネガティブ両方）。
- example_companies は実在する日本企業名を優先する。
- keywords はベクトル検索のヒント語（事業内容・技術・製品名等）を含める。

定量フィールドのルール（予測モデルとしての信頼性に必須）:
- expected_return_pct_low / high: 代表的な対象銘柄に対する**株価リターン（%小数）**の想定レンジ。
  例: -15%〜-5% なら low=-0.15, high=-0.05。ポジティブなら low=0.03, high=0.12 のように正値。
  必ず low <= high。明確に見積もれない場合でも過去の類似イベントを参照して幅を示す（不確実性はレンジ幅で表現）。
- time_horizon: 影響が株価に顕在化する時間帯。
  * immediate: イベント当日〜1週間以内（ヘッドライン反応）
  * 1-4w:    1〜4週間（需給調整・決算ガイダンス修正）
  * 1-3m:    1〜3ヶ月（業績への織り込み）
  * 3-12m:   3ヶ月〜1年（構造変化・長期トレンド）
- probability: このインパクトが実現する確率。
  解釈: 「0.7 = 類似した過去事例 10 回中 7 回で観測された反応」。
  確実視できる一次影響は 0.8 以上、推測度が高い三次・四次は 0.3〜0.6 程度が典型。

定量フィールドの例（日銀利上げの場合）:
  銀行セクター（一次・ポジティブ）: expected_return_pct_low=0.03, high=0.12, time_horizon="1-3m", probability=0.75
    → 過去3回の類似利上げで +5〜+10% を記録した実績を参照。
  REITセクター（一次・ネガティブ）: expected_return_pct_low=-0.10, high=-0.03, time_horizon="immediate", probability=0.70
    → 金利感応度が高く即時反応が典型。
  地銀の貸出金利上昇（二次・ポジティブ）: expected_return_pct_low=0.02, high=0.08, time_horizon="3-12m", probability=0.55
    → 利ざや改善は業績反映までラグがあり、確信度は中程度。
"""

RELEVANCE_SCORING_SYSTEM = """\
あなたは企業調査の専門家です。
マクロ経済の影響と企業プロファイルを照合し、関連度を定量評価します。
必ず指定されたJSON形式のみを出力してください。
"""

RELEVANCE_SCORING_USER = """\
以下のマクロ経済影響と企業プロファイルの関連度を評価してください。

【マクロ影響】
{impact_description}
方向性: {direction}
強度: {intensity}
キーワード: {keywords}

【企業プロファイル】
企業名: {company_name}（証券コード: {company_code}）
事業内容: {business_description}
主要セグメント: {segments_summary}

【最近の動向】
{company_context}

評価基準:
- 1.0: 直接的かつ重大な影響が予想される（売上・利益への明確なインパクト）
- 0.7–0.9: 間接的だが明確な影響が予想される（特定セグメントへの波及）
- 0.5–0.6: 一部セグメントに軽微な影響
- 0.3–0.4: 影響は考えられるが不明確
- 0.0–0.2: ほぼ無関係
- 最近の経営方針転換・事業再編・新規事業がマクロ影響と合致する場合はスコアを上方修正すること

以下の形式でJSONを出力してください（コードブロックなし、JSONのみ）:

{{
  "score": 0.0から1.0の数値,
  "reason": "スコアの根拠（1〜2文）",
  "affected_segments": ["影響を受けるセグメント名のリスト"]
}}
"""

EVENT_IMPORTANCE_SYSTEM = """\
あなたは金融市場の専門家です。
マクロ経済イベントの市場へのインパクトを評価します。
必ず指定されたJSON形式のみを出力してください。
"""

EVENT_IMPORTANCE_USER = """\
以下のイベントの市場インパクトを評価してください。

イベント: {event_description}

以下の形式でJSONを出力してください（コードブロックなし、JSONのみ）:

{{
  "importance": "high|medium|low",
  "scope": "global|regional|domestic",
  "sectors_affected": ["影響セクター1", "影響セクター2"],
  "rationale": "評価根拠（1〜2文）"
}}

判定基準:
- high: 複数セクターに重大な影響。株価への即座のインパクトが予想される。
- medium: 特定セクターへの影響。中期的な業績への影響が予想される。
- low: 影響は限定的または軽微。
"""
