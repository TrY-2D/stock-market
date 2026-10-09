import React, { useState, useEffect } from 'react';
import { Chart } from './components/Chart';
import { EquityChart } from './components/EquityChart';
import { DrawdownChart } from './components/DrawdownChart';
import { ExpectedReturnChart } from './components/ExpectedReturnChart';
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
    linear_window: 30,
    sma_window: 30,
    beta_window: 30,
    z_score_window: 120,
    sma20_period: 20,
    atr_period: 14,
    atr_multiplier: 1.0,
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [syncEnabled, setSyncEnabled] = useState<boolean>(true);
  const [subChartTab, setSubChartTab] = useState<'equity' | 'drawdown' | 'expected_return' | 'all'>('equity');
  const [elapsed, setElapsed] = useState<number>(0);

  useEffect(() => {
    let timer: any;
    if (loading) {
      setElapsed(0);
      timer = setInterval(() => {
        setElapsed((prev) => prev + 1);
      }, 1000);
    }
    return () => clearInterval(timer);
  }, [loading]);
    engine_type: 'nautilus',
  });

  const [result, setResult] = useState<BacktestRunResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [syncEnabled, setSyncEnabled] = useState<boolean>(true);
  const [subChartTab, setSubChartTab] = useState<'equity' | 'drawdown' | 'expected_return' | 'all'>('equity');

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
    <div style={{ minHeight: '100vh', background: '#0b0f19', color: '#e2e8f0', display: 'flex', flexDirection: 'column' }}>
      {/* Top Header Bar */}
      <header style={{ background: '#0f172a', borderBottom: '1px solid #1e293b', padding: '12px 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <span style={{ fontSize: '20px' }}>⚡</span>
          <div>
            <h1 style={{ fontSize: '16px', fontWeight: 700, color: '#f8fafc', letterSpacing: '-0.02em' }}>
              QUANTITATIVE BACKTEST TERMINAL
            </h1>
            <p style={{ fontSize: '11px', color: '#64748b' }}>
              Nautilus Trader Engine &bull; Fibonacci Tranches &bull; Expected Return E &bull; 5 Theses Scoring
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
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
              background: syncEnabled ? 'rgba(56, 189, 248, 0.15)' : '#1e293b',
              border: `1px solid ${syncEnabled ? '#38bdf8' : '#334155'}`,
              color: syncEnabled ? '#38bdf8' : '#94a3b8',
              padding: '6px 12px',
              borderRadius: '6px',
              fontSize: '12px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <span>{syncEnabled ? '🔗' : '⛓️💥'}</span>
            <span>Share X & X-Cross: {syncEnabled ? 'BẬT' : 'TẮT'}</span>
          </button>

          {lastUpdated && (
            <span style={{ fontSize: '12px', color: '#38bdf8', background: 'rgba(56, 189, 248, 0.1)', padding: '4px 10px', borderRadius: '12px', border: '1px solid rgba(56, 189, 248, 0.2)' }}>
              ✓ Cập nhật: {lastUpdated} ({result?.symbol})
            </span>
          )}
        {/* Top KPI Summary Ribbon */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
          <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', padding: '14px 16px', opacity: loading ? 0.5 : 1, transition: 'opacity 0.2s' }}>
            <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Tổng Lợi Nhuận</span>
            <div style={{ fontSize: '20px', fontWeight: 700, color: summary ? (summary.total_return_pct >= 0 ? '#10b981' : '#ef4444') : '#64748b', marginTop: '4px' }}>
              {loading ? '⏳ Đang tính...' : summary ? `${summary.total_return_pct > 0 ? '+' : ''}${summary.total_return_pct.toFixed(2)}%` : '---'}
            </div>
            <span style={{ fontSize: '11px', color: '#64748b' }}>
              {loading ? 'Vui lòng chờ...' : summary ? `Alpha: ${summary.alpha_pct > 0 ? '+' : ''}${summary.alpha_pct.toFixed(2)}%` : 'Đang tính toán...'}
            </span>
          </div>

          <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', padding: '14px 16px', opacity: loading ? 0.5 : 1, transition: 'opacity 0.2s' }}>
            <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Giá Trị NAV Cuối</span>
            <div style={{ fontSize: '20px', fontWeight: 700, color: '#38bdf8', marginTop: '4px' }}>
              {loading ? '⏳ Đang tính...' : summary ? `${summary.final_nav.toLocaleString('vi-VN', { maximumFractionDigits: 0 })} VNĐ` : '---'}
            </div>
            <span style={{ fontSize: '11px', color: '#64748b' }}>
              {loading ? 'Vui lòng chờ...' : summary ? `CAGR: ${summary.cagr_pct.toFixed(2)}%/năm` : 'Đang tính toán...'}
            </span>
          </div>

          <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', padding: '14px 16px', opacity: loading ? 0.5 : 1, transition: 'opacity 0.2s' }}>
            <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Sụt Giảm Max (MDD)</span>
            <div style={{ fontSize: '20px', fontWeight: 700, color: '#f59e0b', marginTop: '4px' }}>
              {loading ? '⏳ Đang tính...' : summary ? `${summary.max_drawdown_pct.toFixed(2)}%` : '---'}
            </div>
            <span style={{ fontSize: '11px', color: '#64748b' }}>
              {loading ? 'Vui lòng chờ...' : summary ? `Calmar: ${summary.calmar_ratio.toFixed(2)}` : 'Đang tính toán...'}
            </span>
          </div>

          <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', padding: '14px 16px', opacity: loading ? 0.5 : 1, transition: 'opacity 0.2s' }}>
            <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Tỷ Lệ Thắng (Win Rate)</span>
            <div style={{ fontSize: '20px', fontWeight: 700, color: '#10b981', marginTop: '4px' }}>
              {loading ? '⏳ Đang tính...' : summary ? `${summary.win_rate_pct.toFixed(1)}%` : '---'}
            </div>
            <span style={{ fontSize: '11px', color: '#64748b' }}>
              {loading ? 'Vui lòng chờ...' : summary ? `Profit Factor: ${summary.profit_factor.toFixed(2)}` : 'Đang tính toán...'}
            </span>
          </div>

          <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', padding: '14px 16px', opacity: loading ? 0.5 : 1, transition: 'opacity 0.2s' }}>
            <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Sharpe / Sortino</span>
            <div style={{ fontSize: '20px', fontWeight: 700, color: '#f8fafc', marginTop: '4px' }}>
              {loading ? '⏳ Đang tính...' : summary ? `${summary.sharpe_ratio.toFixed(2)} / ${summary.sortino_ratio.toFixed(2)}` : '---'}
            </div>
            <span style={{ fontSize: '11px', color: '#64748b' }}>Rf = 5.0%/năm</span>
          </div>

          <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', padding: '14px 16px', opacity: loading ? 0.5 : 1, transition: 'opacity 0.2s' }}>
            <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Tổng Số Lệnh</span>
            <div style={{ fontSize: '20px', fontWeight: 700, color: '#c084fc', marginTop: '4px' }}>
              {loading ? '⏳ Đang tính...' : summary ? `${summary.total_trades}` : '---'}
            </div>
            <span style={{ fontSize: '11px', color: '#64748b' }}>
              {loading ? 'Vui lòng chờ...' : summary ? `Mua: ${summary.buy_trades} | Bán: ${summary.sell_trades}` : 'Đang tính toán...'}
            </span>
          </div>
        </div>
              fontWeight: 600,
              borderRadius: '6px',
              border: 'none',
              cursor: loading ? 'not-allowed' : 'pointer',
            }}
          >
            {loading ? '⏳ Đang Chạy...' : 'Chạy Lại'}
          </button>
        </div>
      </header>

      {/* Main Container */}
      <main style={{ padding: '16px 24px', display: 'flex', flexDirection: 'column', gap: '16px', flex: 1 }}>
        {/* Error Alert */}
        {errorMsg && (
          <div style={{ padding: '12px 16px', background: 'rgba(239, 68, 68, 0.15)', border: '1px solid #ef4444', borderRadius: '6px', color: '#fca5a5', fontSize: '13px' }}>
            ⚠️ {errorMsg}
          </div>
        )}

        {/* Top KPI Summary Ribbon */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
          <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', padding: '14px 16px' }}>
            <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Tổng Lợi Nhuận</span>
            <div style={{ fontSize: '20px', fontWeight: 700, color: summary ? (summary.total_return_pct >= 0 ? '#10b981' : '#ef4444') : '#64748b', marginTop: '4px' }}>
              {summary ? `${summary.total_return_pct > 0 ? '+' : ''}${summary.total_return_pct.toFixed(2)}%` : '---'}
            </div>
            <span style={{ fontSize: '11px', color: '#64748b' }}>
              {summary ? `Alpha: ${summary.alpha_pct > 0 ? '+' : ''}${summary.alpha_pct.toFixed(2)}%` : 'Đang tính toán...'}
            </span>
          </div>

          <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', padding: '14px 16px' }}>
            <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Giá Trị NAV Cuối</span>
            <div style={{ fontSize: '20px', fontWeight: 700, color: '#38bdf8', marginTop: '4px' }}>
              {summary ? `${summary.final_nav.toLocaleString('vi-VN', { maximumFractionDigits: 0 })} VNĐ` : '---'}
            </div>
            <span style={{ fontSize: '11px', color: '#64748b' }}>
              {summary ? `CAGR: ${summary.cagr_pct.toFixed(2)}%/năm` : 'Đang tính toán...'}
            </span>
          </div>

          <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', padding: '14px 16px' }}>
            <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Sụt Giảm Max (MDD)</span>
            <div style={{ fontSize: '20px', fontWeight: 700, color: '#f59e0b', marginTop: '4px' }}>
              {summary ? `${summary.max_drawdown_pct.toFixed(2)}%` : '---'}
            </div>
            <span style={{ fontSize: '11px', color: '#64748b' }}>
              {summary ? `Calmar: ${summary.calmar_ratio.toFixed(2)}` : 'Đang tính toán...'}
            </span>
          </div>

          <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', padding: '14px 16px' }}>
            <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Tỷ Lệ Thắng (Win Rate)</span>
            <div style={{ fontSize: '20px', fontWeight: 700, color: '#10b981', marginTop: '4px' }}>
              {summary ? `${summary.win_rate_pct.toFixed(1)}%` : '---'}
            </div>
            <span style={{ fontSize: '11px', color: '#64748b' }}>
              {summary ? `Profit Factor: ${summary.profit_factor.toFixed(2)}` : 'Đang tính toán...'}
            </span>
          </div>

          <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', padding: '14px 16px' }}>
            <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Sharpe / Sortino</span>
            <div style={{ fontSize: '20px', fontWeight: 700, color: '#f8fafc', marginTop: '4px' }}>
              {summary ? `${summary.sharpe_ratio.toFixed(2)} / ${summary.sortino_ratio.toFixed(2)}` : '---'}
            </div>
            <span style={{ fontSize: '11px', color: '#64748b' }}>Rf = 5.0%/năm</span>
          </div>

            {/* Main Interactive Candlestick Chart */}
            <div style={{ position: 'relative' }}>
              {loading && (
                <div style={{ position: 'absolute', inset: 0, background: 'rgba(11, 15, 25, 0.85)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', zIndex: 30, backdropFilter: 'blur(4px)', borderRadius: '8px' }}>
                  <div style={{ width: '48px', height: '48px', border: '3px solid #334155', borderTopColor: '#38bdf8', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
                  <span style={{ marginTop: '16px', fontSize: '15px', fontWeight: 700, color: '#f8fafc' }}>
                    Đang chạy mô phỏng {config.engine_type === 'nautilus' ? 'Nautilus Trader' : 'Direct Vector Engine'} ({config.symbol})...
                  </span>
                  <span style={{ fontSize: '12px', color: '#38bdf8', marginTop: '6px', fontWeight: 600 }}>
                    {config.all_history ? '📅 Toàn bộ dữ liệu lịch sử từ năm 2000 ➔ Nay (~5,000 phiên)' : `📅 Giai đoạn: ${config.start_date} ➔ ${config.end_date}`}
                  </span>
                  <span style={{ fontSize: '12px', color: '#94a3b8', marginTop: '4px' }}>
                    {config.expanding ? '📐 Chế độ: Expanding Window (Tích lũy toàn bộ dữ liệu)' : `📐 Cửa sổ trượt: ${config.window} phiên`}
                  </span>
                  <span style={{ fontSize: '12px', color: '#f59e0b', marginTop: '10px', fontWeight: 600, background: 'rgba(245, 158, 11, 0.1)', padding: '4px 14px', borderRadius: '12px', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
                    ⏱️ Đang thực thi: {elapsed}s...
                  </span>
                </div>
              )}
        {/* Workspace Layout */}
        <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: '16px' }}>
          {/* Left Sidebar */}
          <div>
            <StrategyConfigPanel
              symbols={symbols}
              config={config}
              onChange={setConfig}
              onRun={handleRunBacktest}
              loading={loading}
            />
          </div>

          {/* Right Area: Charts & Tables */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {/* Main Interactive Candlestick Chart */}
            <div style={{ position: 'relative' }}>
              {loading && (
                <div style={{ position: 'absolute', inset: 0, background: 'rgba(11, 15, 25, 0.75)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', zIndex: 20, backdropFilter: 'blur(3px)', borderRadius: '8px' }}>
                  <div style={{ width: '40px', height: '40px', border: '3px solid #334155', borderTopColor: '#38bdf8', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
                  <span style={{ marginTop: '12px', fontSize: '13px', fontWeight: 600, color: '#f8fafc' }}>
                    Đang chạy mô phỏng Nautilus Trader ({config.symbol})...
                  </span>
                  <span style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px' }}>
                    Tính toán E, cụm Q, Beta, Vùng giá +/-1 ATR & Luận điểm
                  </span>
                </div>
              )}
              <Chart
                bars={result?.candles || []}
                markers={result?.markers || []}
                pSuggestSeries={result?.p_suggest || []}
                buyThresholdSeries={result?.buy_threshold || []}
                sellThresholdSeries={result?.sell_threshold || []}
                sma20Series={result?.sma20 || []}
                symbol={result?.symbol || config.symbol}
                engine={result?.engine || config.engine_type.toUpperCase()}
              />
            </div>

            {/* Sub-Chart Selector Bar */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#0f172a', padding: '10px 16px', borderRadius: '8px', border: '1px solid #1e293b', flexWrap: 'wrap', gap: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <span style={{ fontSize: '12px', fontWeight: 700, color: '#cbd5e1', marginRight: '4px' }}>
                  📊 Biểu Đồ Phân Tích:
                </span>
                <button
                  onClick={() => setSubChartTab('equity')}
                  style={{
                    padding: '5px 12px',
                    fontSize: '12px',
                    fontWeight: 600,
                    borderRadius: '6px',
                    border: '1px solid ' + (subChartTab === 'equity' ? '#38bdf8' : '#334155'),
                    background: subChartTab === 'equity' ? 'rgba(56, 189, 248, 0.15)' : '#1e293b',
                    color: subChartTab === 'equity' ? '#38bdf8' : '#94a3b8',
                    cursor: 'pointer',
                  }}
                >
                  📈 Đường Cong NAV
                </button>
                <button
                  onClick={() => setSubChartTab('drawdown')}
                  style={{
                    padding: '5px 12px',
                    fontSize: '12px',
                    fontWeight: 600,
                    borderRadius: '6px',
                    border: '1px solid ' + (subChartTab === 'drawdown' ? '#f43f5e' : '#334155'),
                    background: subChartTab === 'drawdown' ? 'rgba(244, 63, 94, 0.15)' : '#1e293b',
                    color: subChartTab === 'drawdown' ? '#f43f5e' : '#94a3b8',
                    cursor: 'pointer',
                  }}
                >
                  📉 Sụt Giảm (Drawdown %)
                </button>
                <button
                  onClick={() => setSubChartTab('expected_return')}
                  style={{
                    padding: '5px 12px',
                    fontSize: '12px',
                    fontWeight: 600,
                    borderRadius: '6px',
                    border: '1px solid ' + (subChartTab === 'expected_return' ? '#a855f7' : '#334155'),
                    background: subChartTab === 'expected_return' ? 'rgba(168, 85, 247, 0.15)' : '#1e293b',
                    color: subChartTab === 'expected_return' ? '#a855f7' : '#94a3b8',
                    cursor: 'pointer',
                  }}
                >
                  🎯 Lợi Nhuận Dự Phóng (E) & Luận Điểm
                </button>
              </div>

              <button
                onClick={() => setSubChartTab(subChartTab === 'all' ? 'equity' : 'all')}
                style={{
                  padding: '5px 12px',
                  fontSize: '11px',
                  fontWeight: 600,
                  borderRadius: '6px',
                  border: '1px solid #475569',
                  background: subChartTab === 'all' ? '#2563eb' : '#1e293b',
                  color: '#f8fafc',
                  cursor: 'pointer',
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

              {(subChartTab === 'expected_return' || subChartTab === 'all') && (
                <ExpectedReturnChart
                  expectedReturnSeries={result?.expected_return || []}
                  pqrSeries={result?.pqr_series || []}
                  pqtSeries={result?.pqt_series || []}
                  prSeries={result?.pr_series || []}
                  ptSeries={result?.pt_series || []}
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
