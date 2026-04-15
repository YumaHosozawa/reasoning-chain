"""
データベースセッション管理
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from backend.db.models import Base

_DB_PATH = Path(__file__).parent.parent / "data" / "results.db"
_DB_URL = os.environ.get("DATABASE_URL", f"sqlite:///{_DB_PATH}")

engine = create_engine(
    _DB_URL,
    connect_args={"check_same_thread": False} if _DB_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """テーブルを作成する（起動時に呼び出す）"""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI依存性注入用: DBセッションをyieldする"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
