from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.app.main import app

client = TestClient(app)


def test_api_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"


def test_api_symbols():
    res = client.get("/api/symbols")
    assert res.status_code == 200
    data = res.json()
    assert "symbols" in data
    assert "FPT" in data["symbols"]
    assert len(data["symbols"]) > 0


def test_api_backtest_run_endpoint():
    payload = {
        "symbol": "FPT",
        "start_date": "2021-01-01",
        "end_date": "2024-07-31",
        "initial_cash": 1_000_000_000.0,
        "base_nav_pct": 0.04,
        "lot_size": 100,
        "window": 20,
        "use_synthetic": True,
        "engine_type": "nautilus",
    }
    res = client.post("/api/backtest/run", json=payload)
    assert res.status_code == 200
    data = res.json()

    assert data["symbol"] == "FPT"
    assert data["engine"] == "NAUTILUS"
    assert "summary" in data
    assert "total_return_pct" in data["summary"]
    assert "candles" in data
    assert len(data["candles"]) > 0
    assert "markers" in data
    assert "equity_curve" in data
    assert "support" in data and len(data["support"]) > 0
    assert "resistance" in data and len(data["resistance"]) > 0
    assert "plus_di" in data and len(data["plus_di"]) > 0
    assert "minus_di" in data and len(data["minus_di"]) > 0
    assert "adx" in data and len(data["adx"]) > 0
    assert "position_shares" in data and len(data["position_shares"]) > 0
    assert "trades" in data


def test_api_backtest_expanding_endpoint():
    payload = {
        "symbol": "SSI",
        "initial_cash": 500_000_000.0,
        "expanding": True,
        "all_history": False,
        "use_synthetic": True,
        "engine_type": "direct",
    }
    res = client.post("/api/backtest/run", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "SSI"
    assert data["engine"] == "DIRECT"
    assert len(data["candles"]) > 0
