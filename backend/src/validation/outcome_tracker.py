"""
予測結果の実績検証 (outcome validation) パイプライン。

AnalysisResult に保存された予測を読み出し、prediction_window_days 経過後の
実績株価リターンを yfinance で取得して突合し、
Brier score / MAE / coverage rate を RealizedMetrics として永続化する。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import AnalysisResult
from src.models import RealizedMetrics, horizon_to_days
from src.validation.yfinance_fetch import fetch_return_pct


# 1件の予測で検証する上限マッチ数 (yfinance レート制限対策)
_MAX_MATCHES_PER_RESULT = 50


def validate_result(
    result: AnalysisResult,
    session: Session,
    now: datetime | None = None,
) -> RealizedMetrics:
    """
    1件の AnalysisResult について実績検証を実行する。

    各マッチに対し:
      - prediction_window_days 後の実績リターンを yfinance から取得
      - directional_hit (direction が正しかったか)
      - in_range (実績が [expected_return_pct_low, expected_return_pct_high] に入ったか)
    を算出し、集約指標 (Brier / MAE / coverage) を計算して DB に書き戻す。

    Args:
        result: 対象の AnalysisResult レコード
        session: SQLAlchemy セッション (commit は呼び出し側で行う)
        now: 検証時刻 (テスト用にオーバーライド可能)

    Returns:
        RealizedMetrics: 集約された検証結果
    """
    now = now or datetime.now(timezone.utc)
    chain_impacts: list[dict[str, Any]] = list(
        (result.chain_json or {}).get("impacts", [])
    )
    matches: list[dict[str, Any]] = list(result.matches_json or [])[:_MAX_MATCHES_PER_RESULT]

    # impact_description → 親 impact の数値レンジ/probability を引くための索引
    impact_lookup: dict[str, dict[str, Any]] = {}
    for imp in chain_impacts:
        desc = imp.get("description")
        if desc:
            impact_lookup[desc] = imp

    per_match: list[dict[str, Any]] = []
    brier_terms: list[float] = []
    abs_errors: list[float] = []
    in_range_flags: list[bool] = []

    event_time = result.created_at or now
    # SQLite では tz が剥がれることがあるので補う
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)

    for match in matches:
        direction = match.get("direction")
        horizon = match.get("time_horizon")
        window_days = match.get("prediction_window_days") or horizon_to_days(horizon)

        # 予測ウィンドウが未経過ならスキップ (検証時刻として扱うのみ)
        if event_time + timedelta(days=window_days) > now:
            continue

        company_code = match.get("company_code")
        if not company_code:
            continue

        realized = fetch_return_pct(company_code, event_time, window_days)

        # 親 impact からレンジと probability を取得 (match に無ければ)
        parent = impact_lookup.get(match.get("impact_description", ""), {})
        expected_low = parent.get("expected_return_pct_low")
        expected_high = parent.get("expected_return_pct_high")
        probability = parent.get("probability")
        # match 側にもフィールドがあれば優先
        probability = match.get("probability", probability)
        expected_point = match.get("expected_return_pct")
        if expected_point is None and expected_low is not None and expected_high is not None:
            expected_point = (float(expected_low) + float(expected_high)) / 2.0

        entry: dict[str, Any] = {
            "company_code": company_code,
            "company_name": match.get("company_name"),
            "direction": direction,
            "time_horizon": horizon,
            "window_days": window_days,
            "expected_return_pct": expected_point,
            "expected_return_pct_low": expected_low,
            "expected_return_pct_high": expected_high,
            "probability": probability,
            "realized_return_pct": realized,
        }

        if realized is None:
            entry["directional_hit"] = None
            entry["in_range"] = None
            per_match.append(entry)
            continue

        directional_hit = _directional_hit(direction, realized)
        entry["directional_hit"] = directional_hit

        if expected_low is not None and expected_high is not None:
            lo, hi = float(expected_low), float(expected_high)
            in_range = lo <= realized <= hi
            entry["in_range"] = in_range
            in_range_flags.append(in_range)
        else:
            entry["in_range"] = None

        if expected_point is not None:
            abs_errors.append(abs(realized - float(expected_point)))

        if probability is not None and directional_hit is not None:
            p = float(probability)
            hit = 1.0 if directional_hit else 0.0
            brier_terms.append((p - hit) ** 2)

        per_match.append(entry)

    n_with_return = sum(1 for e in per_match if e.get("realized_return_pct") is not None)

    metrics = RealizedMetrics(
        validated_at=now.isoformat(),
        brier_score=(sum(brier_terms) / len(brier_terms)) if brier_terms else None,
        mae_return=(sum(abs_errors) / len(abs_errors)) if abs_errors else None,
        coverage_rate=(
            sum(1 for f in in_range_flags if f) / len(in_range_flags)
            if in_range_flags
            else None
        ),
        n_matches=len(matches),
        n_with_return=n_with_return,
        per_match=per_match,
    )

    # DB 書き戻し
    result.realized_metrics_json = {
        "validated_at": metrics.validated_at,
        "brier_score": metrics.brier_score,
        "mae_return": metrics.mae_return,
        "coverage_rate": metrics.coverage_rate,
        "n_matches": metrics.n_matches,
        "n_with_return": metrics.n_with_return,
        "per_match": metrics.per_match,
    }
    result.validated_at = now
    result.validation_status = "validated"
    session.add(result)
    return metrics


def sweep_pending(
    session: Session,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[str]:
    """
    validation_status="pending" の AnalysisResult を走査し、
    最大の prediction_window_days を経過したものを順に validate_result にかける。

    Returns:
        検証した result_id のリスト
    """
    now = now or datetime.now(timezone.utc)

    stmt = select(AnalysisResult).where(AnalysisResult.validation_status == "pending")
    if limit is not None:
        stmt = stmt.limit(limit)
    pending = session.execute(stmt).scalars().all()

    validated_ids: list[str] = []
    for result in pending:
        created = result.created_at or now
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        max_window = _max_window_days(result)
        if max_window is None:
            # ウィンドウが決まらないマッチしかない場合はスキップ
            continue
        if created + timedelta(days=max_window) > now:
            # 最長ウィンドウもまだ経過していない
            continue

        validate_result(result, session, now=now)
        validated_ids.append(result.id)

    session.commit()
    return validated_ids


def _max_window_days(result: AnalysisResult) -> int | None:
    """result 内の全マッチ中、最長の prediction_window_days を返す。"""
    matches = list(result.matches_json or [])
    windows: list[int] = []
    for m in matches:
        w = m.get("prediction_window_days")
        if w is None:
            w = horizon_to_days(m.get("time_horizon"))
        if isinstance(w, int) and w > 0:
            windows.append(w)
    return max(windows) if windows else None


def _directional_hit(direction: str | None, realized: float) -> bool | None:
    """
    予測方向 (positive/negative/mixed) と実績リターンの符号を比較。
    mixed は評価から除外 (None を返す)。
    """
    if direction == "positive":
        return realized > 0
    if direction == "negative":
        return realized < 0
    return None
