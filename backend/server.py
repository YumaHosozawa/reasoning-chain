"""
バックエンドサーバー起動スクリプト
"""

import os
import sys

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "backend.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=["backend"],
    )
