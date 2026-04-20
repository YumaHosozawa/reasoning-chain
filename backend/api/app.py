"""
FastAPI アプリケーションファクトリ
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.db.session import init_db
from backend.api.routes.analyze import router as analyze_router
from backend.api.routes.results import router as results_router
from backend.api.routes.export import router as export_router
from backend.api.routes.validation import router as validation_router
from backend.api.routes.backtest import router as backtest_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="推論チェーン API",
        description="マクロイベント→企業影響の多段推論システム",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:3001"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(analyze_router)
    app.include_router(results_router)
    app.include_router(export_router)
    app.include_router(validation_router)
    app.include_router(backtest_router)

    return app


app = create_app()
