#!/usr/bin/env python3
"""
Launcher script for Quantitative Backtest Terminal & Analysis Web Application.
Khởi động FastAPI server phục vụ cả REST API và giao diện Web React (tương tự quant-project).
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


def ensure_frontend_build():
    static_dir = Path(__file__).parent / "src" / "app" / "static"
    frontend_dir = Path(__file__).parent / "src" / "app" / "frontend"

    if not (static_dir / "index.html").exists():
        print("Chưa tìm thấy bản build tĩnh của frontend. Đang tiến hành build React frontend...")
        try:
            subprocess.run(["bunx", "--bun", "vite", "build"], cwd=str(frontend_dir), check=True)
            print("Frontend đã được build thành công vào src/app/static")
        except Exception as e:
            print(f"Cảnh báo: Không thể tự động build frontend ({e}). Bạn có thể build thủ công trong src/app/frontend bằng 'bun run build'.")


def main():
    parser = argparse.ArgumentParser(description="Chạy Quantitative Backtest Terminal Web Application")
    parser.add_argument("--host", default="0.0.0.0", help="Địa chỉ host (mặc định: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Cổng port (mặc định: 8000)")
    parser.add_argument("--reload", action="store_true", help="Kích hoạt uvicorn hot reloading khi code thay đổi")
    parser.add_argument("--no-build", action="store_true", help="Bỏ qua bước kiểm tra/build frontend")
    args = parser.parse_args()

    if not args.no_build:
        ensure_frontend_build()

    print("\n" + "=" * 75)
    print(" 🚀 QUANTITATIVE BACKTEST TERMINAL (NAUTILUS TRADER & FASTAPI)")
    print(f" 🌐 Giao diện Web UI & API   : http://localhost:{args.port}")
    print(f" 📖 Tài liệu tương tác API   : http://localhost:{args.port}/docs")
    print(f" 📊 TradingView Lightweight Charts & Fibonacci Tranche Execution")
    print("=" * 75 + "\n")

    import uvicorn
    uvicorn.run("src.app.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
