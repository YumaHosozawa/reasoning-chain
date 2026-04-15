"""
推論チェーンシステム エントリーポイント

使用例:
    python main.py "米国、対中半導体輸出規制を強化"
    python main.py "日銀が政策金利を0.5%に引き上げ" --format json
    python main.py "原油価格が$100突破" --slack-webhook https://hooks.slack.com/...
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

from src.chain.generator import ReasoningChainGenerator
from src.matching.matcher import CompanyMatcher
from src.output.formatter import AlertFormatter


def main() -> None:
    parser = argparse.ArgumentParser(
        description="マクロイベント→企業影響の多段推論チェーン"
    )
    parser.add_argument("event", help="マクロ経済イベントの説明テキスト")
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="出力形式（デフォルト: markdown）",
    )
    parser.add_argument(
        "--max-levels",
        type=int,
        default=4,
        help="推論チェーンの最大レベル（デフォルト: 4）",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="アラートに表示する企業数（デフォルト: 10）",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.6,
        help="マッチングスコア閾値（デフォルト: 0.6）",
    )
    parser.add_argument(
        "--slack-webhook",
        default=None,
        help="Slack Incoming Webhook URL（指定時はSlackに送信）",
    )
    parser.add_argument(
        "--chain-only",
        action="store_true",
        help="推論チェーン生成のみ実行（企業マッチングをスキップ）",
    )
    args = parser.parse_args()

    # 推論チェーン生成
    print(f"推論チェーン生成中... イベント: {args.event[:60]}", file=sys.stderr)
    generator = ReasoningChainGenerator(max_levels=args.max_levels)
    chain = generator.generate(args.event)
    print(
        f"  → {len(chain.impacts)} 件の影響ノードを生成（最大レベル: {chain.max_level}）",
        file=sys.stderr,
    )

    matches = []
    if not args.chain_only:
        # 企業マッチング
        print("企業マッチング実行中...", file=sys.stderr)
        matcher = CompanyMatcher(score_threshold=args.threshold)
        matches = matcher.match(chain)
        print(f"  → {len(matches)} 社がマッチ（閾値: {args.threshold}）", file=sys.stderr)

    # 出力
    formatter = AlertFormatter(chain, matches, top_n=args.top_n)

    if args.format == "json":
        print(formatter.to_json())
    else:
        print(formatter.to_markdown())

    if args.slack_webhook:
        success = formatter.post_to_slack(args.slack_webhook)
        status = "成功" if success else "失敗"
        print(f"Slack送信: {status}", file=sys.stderr)


if __name__ == "__main__":
    main()
