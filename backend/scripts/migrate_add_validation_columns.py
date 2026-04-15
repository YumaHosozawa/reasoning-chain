"""
単発マイグレーション: analysis_results に検証用カラムを追加する。

追加カラム:
  - validation_status        TEXT     NOT NULL DEFAULT 'pending'
  - validated_at             DATETIME NULL
  - realized_metrics_json    JSON     NULL

実行:
    python -m backend.scripts.migrate_add_validation_columns

SQLiteの `ALTER TABLE ADD COLUMN` を3回実行するだけの単純スクリプト。
既に列が存在する場合はスキップする (冪等)。
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from backend.db.session import engine


_TABLE = "analysis_results"

# (column_name, SQL to append via ALTER TABLE)
_COLUMNS: list[tuple[str, str]] = [
    (
        "validation_status",
        "ALTER TABLE analysis_results ADD COLUMN validation_status VARCHAR(20) NOT NULL DEFAULT 'pending'",
    ),
    (
        "validated_at",
        "ALTER TABLE analysis_results ADD COLUMN validated_at DATETIME NULL",
    ),
    (
        "realized_metrics_json",
        "ALTER TABLE analysis_results ADD COLUMN realized_metrics_json JSON NULL",
    ),
]


def main() -> None:
    inspector = inspect(engine)
    if _TABLE not in inspector.get_table_names():
        print(f"[migrate] テーブル '{_TABLE}' が存在しません。init_db() を先に実行してください。")
        return

    existing = {col["name"] for col in inspector.get_columns(_TABLE)}
    print(f"[migrate] 既存カラム: {sorted(existing)}")

    with engine.begin() as conn:
        for name, sql in _COLUMNS:
            if name in existing:
                print(f"[migrate] skip: {name} は既に存在します")
                continue
            print(f"[migrate] add column: {name}")
            conn.execute(text(sql))

    # 追加後の状態を再確認
    inspector2 = inspect(engine)
    final = {col["name"] for col in inspector2.get_columns(_TABLE)}
    print(f"[migrate] 完了。現カラム: {sorted(final)}")


if __name__ == "__main__":
    main()
