import React, { useState, useEffect } from 'react';
import { Chart } from './components/Chart';
import { EquityChart } from './components/EquityChart';
import { DrawdownChart } from './components/DrawdownChart';
import { DMIChart } from './components/DMIChart';
import { PositionChart } from './components/PositionChart';
import { ExpectedReturnChart } from './components/ExpectedReturnChart';
import { LoserRatioChart } from './components/LoserRatioChart';
import { StrategyConfigPanel } from './components/StrategyConfigPanel';
import { TradeAnalysisPanel } from './components/TradeAnalysisPanel';
import { chartSync } from './chartSync';
import type {
  BacktestRunRequest,
  BacktestRunResponse,
} from './types';

export const App: React.FC = () => {
  const [symbols, setSymbols] = useState<string[]>([
    'FPT', 'SSI', 'HPG', 'VNM', 'VIC', 'MWG', 'VCB', 'TCB', 'MBB', 'VHM'
  ]);

  const [config, setConfig] = useState<BacktestRunRequest>({
    symbol: 'FPT',
    start_date: '2021-01-01',
    end_date: '2024-07-31',
    initial_cash: 1_000_000_000.0,
    base_nav_pct: 0.04,
    lot_size: 100,
    window: 30,
    linear_window: null,
    sma_window: 1500,
    beta_window: 30,
    z_score_window: 120,
    sma20_period: 20,
    atr_period: 14,
    atr_multiplier: 1.0,
    min_theses: 4,
    expanding: false,
    all_history: true, // Default to all history
    use_synthetic: false,
    engine_type: 'nautilus',
  });

  const [result, setResult] = useState<BacktestRunResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [syncEnabled, setSyncEnabled] = useState<boolean>(true);
  const [subChartTab, setSubChartTab] = useState<'equity' | 'drawdown' | 'loser_ratio' | 'dmi' | 'position' | 'expected_return' | 'all'>('equity');
  const [elapsed, setElapsed] = useState<number>(0);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined;
    if (loading) {
      setElapsed(0);
      timer = setInterval(() => {
        setElapsed((prev) => prev + 1);
      }, 1000);
    }
    return () => clearInterval(timer);
  }, [loading]);

  // Fetch symbol list
  useEffect(() => {
    fetch('/api/symbols')
      .then((res) => res.json())
      .then((data) => {
        if (data && data.symbols) {
          setSymbols(data.symbols);
        }
      })
      .catch((err) => console.warn('Could not load symbols:', err));
  }, []);

  // Run backtest function
  const handleRunBacktest = async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const res = await fetch('/api/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(errJson.detail || 'Lỗi thực thi backtest');
      }

      const data: BacktestRunResponse = await res.json();
      setResult(data);
      setLastUpdated(new Date().toLocaleTimeString('vi-VN'));
    } catch (err: unknown) {
      console.error('Backtest error:', err);
      const msg = err instanceof Error ? err.message : 'Không thể kết nối đến máy chủ backtest';
      setErrorMsg(msg);
    } finally {
      setLoading(false);
    }
  };

  // Run initial backtest on mount
  useEffect(() => {
    handleRunBacktest();
  }, []);

  const summary = result?.summary;

  return (
    <div style={{ minHeight: '100vh', background: '#070b14', color: '#f8fafc', display: 'flex', flexDirection: 'column' }}>
      {/* Top Header Bar - Modern Glassmorphism */}
      <header style={{
        background: 'rgba(12, 18, 34, 0.85)',
        backdropFilter: 'blur(16px)',
        borderBottom: '1px solid rgba(30, 41, 59, 0.8)',
        padding: '12px 28px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        position: 'sticky',
        top: 0,
        zIndex: 40,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{
            width: '36px',
            height: '36px',
            borderRadius: '10px',
            background: 'linear-gradient(135deg, #0284c7 0%, #2563eb 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 0 16px rgba(14, 165, 233, 0.3)',
          }}>
            <span style={{ fontSize: '18px' }}>⚡</span>
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <h1 style={{ fontSize: '15px', fontWeight: 800, color: '#f8fafc', letterSpacing: '-0.02em', textTransform: 'uppercase' }}>
                Quantitative Backtest Terminal
              </h1>
              <span style={{
                fontSize: '10px',
                fontWeight: 700,
                color: '#38bdf8',
                background: 'rgba(56, 189, 248, 0.12)',
                border: '1px solid rgba(56, 189, 248, 0.25)',
                padding: '1px 7px',
                borderRadius: '6px',
                textTransform: 'uppercase',
              }}>
                {config.engine_type === 'nautilus' ? 'Nautilus Core' : 'Direct Vector'}
              </span>
              {config.all_history && (
                <span style={{
                  fontSize: '10px',
                  fontWeight: 600,
                  color: '#10b981',
                  background: 'rgba(16, 185, 129, 0.12)',
                  border: '1px solid rgba(16, 185, 129, 0.25)',
                  padding: '1px 7px',
                  borderRadius: '6px',
                }}>
                  All History (2000 ➔ Nay)
                </span>
              )}
            </div>
            <p style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>
              Fibonacci Multi-Level Allocation &bull; 7 Quantitative Theses &bull; DMI Adaptive Trend &bull; Expected Return E
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            onClick={() => {
              const next = !syncEnabled;
              setSyncEnabled(next);
              chartSync.setEnabled(next);
            }}
            title="Đồng bộ trục X và con trỏ chuột (Crosshair) trên tất cả các biểu đồ"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              background: syncEnabled ? 'rgba(56, 189, 248, 0.12)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${syncEnabled ? '#38bdf8' : '#334155'}`,
              color: syncEnabled ? '#38bdf8' : '#94a3b8',
              padding: '6px 12px',
              borderRadius: '8px',
              fontSize: '11px',
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
          >
            <span>{syncEnabled ? '🔗' : '⛓️'}</span>
            <span>Crosshair Sync: {syncEnabled ? 'BẬT' : 'TẮT'}</span>
          </button>

          {lastUpdated && (
            <div style={{
              fontSize: '11px',
              color: '#94a3b8',
              background: 'rgba(15, 23, 42, 0.8)',
              padding: '5px 12px',
              borderRadius: '8px',
              border: '1px solid #1e293b',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}>
              <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10b981' }} />
              <span>{result?.symbol}: {lastUpdated}</span>
            </div>
          )}

          <button
            onClick={() => handleRunBacktest()}
            disabled={loading}
            style={{
              padding: '6px 16px',
              background: loading ? '#1e293b' : 'linear-gradient(135deg, #0284c7 0%, #2563eb 100%)',
              color: loading ? '#64748b' : '#ffffff',
              fontSize: '12px',
              fontWeight: 700,
              borderRadius: '8px',
              border: 'none',
              cursor: loading ? 'not-allowed' : 'pointer',
              boxShadow: loading ? 'none' : '0 2px 10px rgba(2, 132, 199, 0.3)',
              transition: 'all 0.2s',
            }}
          >
            {loading ? '⏳ Đang Chạy...' : 'Chạy Lại'}
          </button>
        </div>
      </header>

      {/* Main Container */}
      <main style={{ padding: '16px 28px', display: 'flex', flexDirection: 'column', gap: '16px', flex: 1 }}>
        {/* Error Alert */}
        {errorMsg && (
          <div style={{
            padding: '12px 16px',
            background: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid rgba(239, 68, 68, 0.4)',
            borderRadius: '8px',
            color: '#fca5a5',
            fontSize: '12px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}>
            <span>⚠️</span>
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Top KPI Metrics Cards Ribbon */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
          {/* Card 1: Total Return */}
          <div className="kpi-card" style={{
            background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.8) 0%, rgba(11, 15, 25, 0.9) 100%)',
            border: '1px solid #1e293b',
            borderRadius: '10px',
            padding: '12px 16px',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600 }}>
                Tổng Lợi Nhuận
              </span>
              <span style={{ fontSize: '10px', padding: '1px 6px', borderRadius: '4px', background: summary && summary.total_return_pct >= 0 ? 'rgba(16, 185, 129, 0.15)' : 'rgba(244, 63, 94, 0.15)', color: summary && summary.total_return_pct >= 0 ? '#10b981' : '#f43f5e', fontWeight: 600 }}>
                {summary ? (summary.total_return_pct >= 0 ? 'LÃI' : 'LỖ') : '--'}
              </span>
            </div>
            <div style={{ fontSize: '22px', fontWeight: 800, color: summary ? (summary.total_return_pct >= 0 ? '#10b981' : '#f43f5e') : '#64748b', marginTop: '4px', fontFamily: 'JetBrains Mono, monospace' }}>
              {summary ? `${summary.total_return_pct > 0 ? '+' : ''}${summary.total_return_pct.toFixed(2)}%` : '---'}
            </div>
            <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px', display: 'flex', justifyContent: 'space-between' }}>
              <span>Alpha: {summary ? `${summary.alpha_pct > 0 ? '+' : ''}${summary.alpha_pct.toFixed(2)}%` : '--'}</span>
              <span>Bench: {summary ? `${summary.benchmark_return_pct.toFixed(1)}%` : '--'}</span>
            </div>
          </div>

          {/* Card 2: Final NAV */}
          <div className="kpi-card" style={{
            background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.8) 0%, rgba(11, 15, 25, 0.9) 100%)',
            border: '1px solid #1e293b',
            borderRadius: '10px',
            padding: '12px 16px',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600 }}>
                NAV Cuối Cùng
              </span>
              <span style={{ fontSize: '10px', color: '#38bdf8', background: 'rgba(56, 189, 248, 0.12)', padding: '1px 6px', borderRadius: '4px', fontWeight: 600 }}>
                CAGR
              </span>
            </div>
            <div style={{ fontSize: '20px', fontWeight: 800, color: '#38bdf8', marginTop: '4px', fontFamily: 'JetBrains Mono, monospace' }}>
              {summary ? `${summary.final_nav.toLocaleString('vi-VN', { maximumFractionDigits: 0 })}` : '---'}
            </div>
            <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>
              {summary ? `CAGR: ${summary.cagr_pct.toFixed(2)}%/năm` : 'Đang tính toán...'}
            </div>
          </div>

          {/* Card 3: Max Drawdown */}
          <div className="kpi-card" style={{
            background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.8) 0%, rgba(11, 15, 25, 0.9) 100%)',
            border: '1px solid #1e293b',
            borderRadius: '10px',
            padding: '12px 16px',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600 }}>
                Sụt Giảm (MDD)
              </span>
              <span style={{ fontSize: '10px', color: '#f59e0b', background: 'rgba(245, 158, 11, 0.12)', padding: '1px 6px', borderRadius: '4px', fontWeight: 600 }}>
                Rủi ro
              </span>
            </div>
            <div style={{ fontSize: '22px', fontWeight: 800, color: '#f59e0b', marginTop: '4px', fontFamily: 'JetBrains Mono, monospace' }}>
              {summary ? `-${summary.max_drawdown_pct.toFixed(2)}%` : '---'}
            </div>
            <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>
              {summary ? `Calmar Ratio: ${summary.calmar_ratio.toFixed(2)}` : 'Đang tính toán...'}
            </div>
          </div>

          {/* Card 4: Win Rate & Profit Factor */}
          <div className="kpi-card" style={{
            background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.8) 0%, rgba(11, 15, 25, 0.9) 100%)',
            border: '1px solid #1e293b',
            borderRadius: '10px',
            padding: '12px 16px',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600 }}>
                Tỷ Lệ Thắng
              </span>
              <span style={{ fontSize: '10px', color: '#10b981', background: 'rgba(16, 185, 129, 0.12)', padding: '1px 6px', borderRadius: '4px', fontWeight: 600 }}>
                PF: {summary ? summary.profit_factor.toFixed(2) : '--'}
              </span>
            </div>
            <div style={{ fontSize: '22px', fontWeight: 800, color: '#10b981', marginTop: '4px', fontFamily: 'JetBrains Mono, monospace' }}>
              {summary ? `${summary.win_rate_pct.toFixed(1)}%` : '---'}
            </div>
            <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>
              {summary ? `Profit Factor: ${summary.profit_factor.toFixed(2)}` : 'Đang tính toán...'}
            </div>
          </div>

          {/* Card 5: Sharpe & Sortino */}
          <div className="kpi-card" style={{
            background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.8) 0%, rgba(11, 15, 25, 0.9) 100%)',
            border: '1px solid #1e293b',
            borderRadius: '10px',
            padding: '12px 16px',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600 }}>
                Sharpe / Sortino
              </span>
              <span style={{ fontSize: '10px', color: '#a855f7', background: 'rgba(168, 85, 247, 0.12)', padding: '1px 6px', borderRadius: '4px', fontWeight: 600 }}>
                Rf 5%
              </span>
            </div>
            <div style={{ fontSize: '20px', fontWeight: 800, color: '#f8fafc', marginTop: '4px', fontFamily: 'JetBrains Mono, monospace' }}>
              {summary ? `${summary.sharpe_ratio.toFixed(2)} / ${summary.sortino_ratio.toFixed(2)}` : '---'}
            </div>
            <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>
              Hiệu suất điều chỉnh rủi ro
            </div>
          </div>

          {/* Card 6: Total Trades */}
          <div className="kpi-card" style={{
            background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.8) 0%, rgba(11, 15, 25, 0.9) 100%)',
            border: '1px solid #1e293b',
            borderRadius: '10px',
            padding: '12px 16px',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600 }}>
                Số Lệnh Khớp
              </span>
              <span style={{ fontSize: '10px', color: '#c084fc', background: 'rgba(192, 132, 252, 0.12)', padding: '1px 6px', borderRadius: '4px', fontWeight: 600 }}>
                Tranches
              </span>
            </div>
            <div style={{ fontSize: '22px', fontWeight: 800, color: '#c084fc', marginTop: '4px', fontFamily: 'JetBrains Mono, monospace' }}>
              {summary ? `${summary.total_trades}` : '---'}
            </div>
            <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>
              {summary ? `Mua: ${summary.buy_trades} | Bán: ${summary.sell_trades}` : 'Đang tính toán...'}
            </div>
          </div>
        </div>

        {/* Workspace Layout */}
        <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: '16px' }}>
          {/* Left Sidebar: Strategy Configuration */}
          <div>
            <StrategyConfigPanel
              symbols={symbols}
              config={config}
              onChange={setConfig}
              onRun={handleRunBacktest}
              loading={loading}
            />
          </div>

          {/* Right Main Area: Charts & Log */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', minWidth: 0 }}>
            {/* Interactive Candlestick Chart */}
            <div style={{ position: 'relative' }}>
              {loading && (
                <div style={{
                  position: 'absolute',
                  inset: 0,
                  background: 'rgba(7, 11, 20, 0.88)',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  zIndex: 30,
                  backdropFilter: 'blur(8px)',
                  borderRadius: '12px',
                  border: '1px solid rgba(56, 189, 248, 0.2)',
                }}>
                  <div style={{
                    width: '44px',
                    height: '44px',
                    border: '3px solid rgba(56, 189, 248, 0.2)',
                    borderTopColor: '#38bdf8',
                    borderRadius: '50%',
                    animation: 'spin 0.8s linear infinite',
                  }} />
                  <span style={{ marginTop: '16px', fontSize: '14px', fontWeight: 700, color: '#f8fafc', letterSpacing: '-0.01em' }}>
                    Đang mô phỏng {config.engine_type === 'nautilus' ? 'Nautilus Trader' : 'Direct Vector Engine'} ({config.symbol})...
                  </span>
                  <span style={{ fontSize: '12px', color: '#38bdf8', marginTop: '6px', fontWeight: 600 }}>
                    {config.all_history ? '📅 Toàn bộ dữ liệu lịch sử từ năm 2000 ➔ Nay' : `📅 Giai đoạn: ${config.start_date} ➔ ${config.end_date}`}
                  </span>
                  <span style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px' }}>
                    {config.expanding ? '📐 Chế độ: Expanding Window (Tích lũy toàn bộ dữ liệu)' : `📐 Cửa sổ trượt: ${config.window} phiên`}
                  </span>
                  <span style={{
                    fontSize: '11px',
                    color: '#f59e0b',
                    marginTop: '10px',
                    fontWeight: 600,
                    background: 'rgba(245, 158, 11, 0.1)',
                    padding: '3px 12px',
                    borderRadius: '12px',
                    border: '1px solid rgba(245, 158, 11, 0.25)',
                  }}>
                    ⏱️ Thời gian thực thi: {elapsed}s...
                  </span>
                </div>
              )}
              <Chart
                bars={result?.candles || []}
                markers={result?.markers || []}
                pSuggestSeries={result?.p_suggest || []}
                supportSeries={result?.support || []}
                resistanceSeries={result?.resistance || []}
                buyThresholdSeries={result?.buy_threshold || []}
                sellThresholdSeries={result?.sell_threshold || []}
                symbol={result?.symbol || config.symbol}
                engine={result?.engine || config.engine_type.toUpperCase()}
              />
            </div>

            {/* Sub-Chart Navigation Selector Bar */}
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              background: 'rgba(12, 18, 34, 0.9)',
              padding: '8px 14px',
              borderRadius: '10px',
              border: '1px solid #1e293b',
              flexWrap: 'wrap',
              gap: '8px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                <span style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', marginRight: '6px' }}>
                  Phân Tích:
                </span>
                
                {/* Tab: Equity */}
                <button
                  onClick={() => setSubChartTab('equity')}
                  style={{
                    padding: '5px 12px',
                    fontSize: '11px',
                    fontWeight: 600,
                    borderRadius: '6px',
                    border: '1px solid ' + (subChartTab === 'equity' ? '#38bdf8' : '#1e293b'),
                    background: subChartTab === 'equity' ? 'rgba(56, 189, 248, 0.15)' : 'rgba(15, 23, 42, 0.6)',
                    color: subChartTab === 'equity' ? '#38bdf8' : '#94a3b8',
                    cursor: 'pointer',
                    transition: 'all 0.15s',
                  }}
                >
                  📈 Đường Cong NAV
                </button>

                {/* Tab: Drawdown */}
                <button
                  onClick={() => setSubChartTab('drawdown')}
                  style={{
                    padding: '5px 12px',
                    fontSize: '11px',
                    fontWeight: 600,
                    borderRadius: '6px',
                    border: '1px solid ' + (subChartTab === 'drawdown' ? '#f43f5e' : '#1e293b'),
                    background: subChartTab === 'drawdown' ? 'rgba(244, 63, 94, 0.15)' : 'rgba(15, 23, 42, 0.6)',
                    color: subChartTab === 'drawdown' ? '#f43f5e' : '#94a3b8',
                    cursor: 'pointer',
                    transition: 'all 0.15s',
                  }}
                >
                  📉 Sụt Giảm (Drawdown %)
                </button>

                {/* Tab: Loser Ratio (Requested by user) */}
                <button
                  onClick={() => setSubChartTab('loser_ratio')}
                  style={{
                    padding: '5px 12px',
                    fontSize: '11px',
                    fontWeight: 600,
                    borderRadius: '6px',
                    border: '1px solid ' + (subChartTab === 'loser_ratio' ? '#f59e0b' : '#1e293b'),
                    background: subChartTab === 'loser_ratio' ? 'rgba(245, 158, 11, 0.15)' : 'rgba(15, 23, 42, 0.6)',
                    color: subChartTab === 'loser_ratio' ? '#f59e0b' : '#94a3b8',
                    cursor: 'pointer',
                    transition: 'all 0.15s',
                  }}
                >
                  🎯 Tỷ Lệ Loser 3 Năm (C)
                </button>

                {/* Tab: DMI & ADX */}
                <button
                  onClick={() => setSubChartTab('dmi')}
                  style={{
                    padding: '5px 12px',
                    fontSize: '11px',
                    fontWeight: 600,
                    borderRadius: '6px',
                    border: '1px solid ' + (subChartTab === 'dmi' ? '#06b6d4' : '#1e293b'),
                    background: subChartTab === 'dmi' ? 'rgba(6, 182, 212, 0.15)' : 'rgba(15, 23, 42, 0.6)',
                    color: subChartTab === 'dmi' ? '#06b6d4' : '#94a3b8',
                    cursor: 'pointer',
                    transition: 'all 0.15s',
                  }}
                >
                  ⚡ DMI & ADX
                </button>

                {/* Tab: Position */}
                <button
                  onClick={() => setSubChartTab('position')}
                  style={{
                    padding: '5px 12px',
                    fontSize: '11px',
                    fontWeight: 600,
                    borderRadius: '6px',
                    border: '1px solid ' + (subChartTab === 'position' ? '#10b981' : '#1e293b'),
                    background: subChartTab === 'position' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(15, 23, 42, 0.6)',
                    color: subChartTab === 'position' ? '#10b981' : '#94a3b8',
                    cursor: 'pointer',
                    transition: 'all 0.15s',
                  }}
                >
                  📊 Vị Thế Fibonacci
                </button>

                {/* Tab: Expected Return E */}
                <button
                  onClick={() => setSubChartTab('expected_return')}
                  style={{
                    padding: '5px 12px',
                    fontSize: '11px',
                    fontWeight: 600,
                    borderRadius: '6px',
                    border: '1px solid ' + (subChartTab === 'expected_return' ? '#a855f7' : '#1e293b'),
                    background: subChartTab === 'expected_return' ? 'rgba(168, 85, 247, 0.15)' : 'rgba(15, 23, 42, 0.6)',
                    color: subChartTab === 'expected_return' ? '#a855f7' : '#94a3b8',
                    cursor: 'pointer',
                    transition: 'all 0.15s',
                  }}
                >
                  🎯 Lợi Nhuận Kỳ Vọng (E)
                </button>
              </div>

              {/* View All (Stack) Toggle Button */}
              <button
                onClick={() => setSubChartTab(subChartTab === 'all' ? 'equity' : 'all')}
                style={{
                  padding: '5px 12px',
                  fontSize: '11px',
                  fontWeight: 600,
                  borderRadius: '6px',
                  border: '1px solid ' + (subChartTab === 'all' ? '#38bdf8' : '#334155'),
                  background: subChartTab === 'all' ? '#0284c7' : 'rgba(15, 23, 42, 0.6)',
                  color: '#f8fafc',
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                {subChartTab === 'all' ? 'Thu Gọn Tab' : '📂 Xem Tất Cả (Xếp Chồng)'}
              </button>
            </div>

            {/* Sub-Charts Container */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {(subChartTab === 'equity' || subChartTab === 'all') && (
                <EquityChart
                  equityCurve={result?.equity_curve || []}
                  benchmarkCurve={result?.benchmark_curve || []}
                  initialNav={config.initial_cash}
                  summary={result?.summary}
                />
              )}

              {(subChartTab === 'drawdown' || subChartTab === 'all') && (
                <DrawdownChart
                  drawdownCurve={result?.drawdown_curve || []}
                  summary={result?.summary}
                />
              )}

              {(subChartTab === 'loser_ratio' || subChartTab === 'all') && (
                <LoserRatioChart
                  loserRatioSeries={result?.loser_ratio || []}
                />
              )}

              {(subChartTab === 'dmi' || subChartTab === 'all') && (
                <DMIChart
                  plusDiSeries={result?.plus_di || []}
                  minusDiSeries={result?.minus_di || []}
                  adxSeries={result?.adx || []}
                />
              )}

              {(subChartTab === 'position' || subChartTab === 'all') && (
                <PositionChart
                  positionShares={result?.position_shares || []}
                  positionLevel={result?.position_level || []}
                  v0={Math.floor((config.base_nav_pct * config.initial_cash) / ((result?.candles?.[0]?.close || 50000) * config.lot_size)) * config.lot_size}
                  lotSize={config.lot_size}
                />
              )}

              {(subChartTab === 'expected_return' || subChartTab === 'all') && (
                <ExpectedReturnChart
                  expectedReturnSeries={result?.expected_return || []}
                  ptSeries={result?.pt_series || []}
                  prSeries={result?.pr_series || []}
                  divYieldSeries={result?.div_yield_series || []}
                  thesesCountSeries={result?.theses_count || []}
                />
              )}
            </div>

            {/* Trade Log & Analysis Table */}
            <TradeAnalysisPanel
              trades={result?.trades || []}
              summary={result?.summary || null}
            />
          </div>
        </div>
      </main>
    </div>
  );
};
