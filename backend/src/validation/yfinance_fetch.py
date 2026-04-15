"""
株価リターン取得ヘルパー (yfinance ラッパ)

東証銘柄 (code.T) 向けに、指定日からN営業日後までのリターンを取得する。
backtest.evaluator と outcome_tracker の両方から利用される共有モジュール。
"""

from __future__ import annotations

from datetime import datetime, timedelta


def fetch_return_pct(
    company_code: str,
    start_date: datetime,
    window_days: int,
) -> float | None:
    """
    指定企業の株価リターン (window_days 後 / start_date) を取得する。

    Args:
        company_code: 証券コード (例: "7203")
        start_date: 起点となる日時 (tz付き想定だが無くても可)
        window_days: 取得するリターンのウィンドウ日数

    Returns:
        float: リターン (例: 0.05 = +5%)。データなし / 取得失敗時は None。
    """
    try:
        import yfinance as yf
    except ImportError:
        return None

    ticker = f"{company_code}.T"
    # 終値を確実に拾うため末尾に余裕を持たせる (週末・祝日対策)
    end_date = start_date + timedelta(days=window_days + 10)

    try:
        hist = yf.download(
            ticker,
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=False,
        )
    except Exception:
        return None

    if hist is None or hist.empty or len(hist) < 2:
        return None

    try:
        start_price = float(hist["Close"].iloc[0])
        # window_days 目の営業日終値 (データが足りなければ最後の日)
        idx = min(window_days, len(hist) - 1)
        end_price = float(hist["Close"].iloc[idx])
    except Exception:
        return None

    if start_price <= 0:
        return None

    return (end_price - start_price) / start_price
