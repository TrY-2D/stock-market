from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.app.backtest_service import BacktestAppService
from src.app.schemas import (
    BacktestRunRequest,
    BacktestRunResponse,
    SymbolListResponse,
)

logger = logging.getLogger("quant_terminal")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Quantitative Backtest Terminal (Nautilus Trader & FastAPI)",
    description="Terminal giao dịch định lượng đa tài sản tích hợp mô hình E, cụm Q, Beta, LRC, SMA, DMI, Nến đảo chiều và Quản lý vốn Fibonacci",
    version="1.0.0",
)

# Enable CORS for local development and Vite proxy
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "platform": "Nautilus Trader & FastAPI Quantitative Terminal"}


@app.get("/api/symbols", response_model=SymbolListResponse)
def get_symbols() -> SymbolListResponse:
    """Danh sách các mã cổ phiếu hỗ trợ kiểm thử."""
    symbols = BacktestAppService.get_symbols()
    return SymbolListResponse(symbols=symbols)


@app.post("/api/backtest/run", response_model=BacktestRunResponse)
def run_backtest_endpoint(req: BacktestRunRequest) -> BacktestRunResponse:
    """Chạy mô phỏng Backtest định lượng và trả về nến TradingView, đường chỉ báo, markers và số liệu."""
    try:
        response = BacktestAppService.execute_backtest(req)
        return response
    except Exception as exc:
        logger.error(f"Lỗi thực thi backtest: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Backtest thất bại: {exc}")


# Phục vụ React frontend tĩnh nếu đã build
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = STATIC_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(
                index_file,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
        return JSONResponse({"message": "Quantitative Terminal API is running. Build frontend into src/app/static"})
