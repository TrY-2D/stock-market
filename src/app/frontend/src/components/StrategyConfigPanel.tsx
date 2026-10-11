import React from 'react';
import type { BacktestRunRequest } from '../types';

interface StrategyConfigPanelProps {
  symbols: string[];
  config: BacktestRunRequest;
  onChange: (cfg: BacktestRunRequest) => void;
  onRun: () => void;
  loading: boolean;
}

export const StrategyConfigPanel: React.FC<StrategyConfigPanelProps> = ({
  symbols,
  config,
  onChange,
  onRun,
  loading,
}) => {
  const updateField = <K extends keyof BacktestRunRequest>(field: K, value: BacktestRunRequest[K]) => {
    onChange({ ...config, [field]: value });
  };

  return (
    <aside className="w-full bg-slate-900/90 backdrop-blur-md border border-slate-800 rounded-xl p-5 flex flex-col gap-5 shadow-xl shadow-black/20 text-slate-200">
      {/* Panel Header */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <div className="w-2.5 h-2.5 rounded-full bg-sky-400 animate-pulse" />
          <h3 className="font-semibold text-sm text-slate-100 tracking-tight">Cấu Hình Chiến Lược</h3>
        </div>
        <span className="text-[10px] font-medium tracking-wide uppercase px-2 py-0.5 rounded bg-slate-800 text-sky-400 border border-slate-700/60">
          Fibonacci 1,1,2,3,5,8
        </span>
      </div>

      {/* Symbol & Engine Selection */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Mã Cổ Phiếu</label>
          <div className="relative">
            <select
              value={config.symbol}
              onChange={(e) => updateField('symbol', e.target.value)}
              className="w-full bg-slate-950 border border-slate-700/80 rounded-lg px-3 py-2 text-xs font-semibold text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500 focus:border-sky-500 transition-all appearance-none cursor-pointer"
            >
              {symbols.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-400 text-[10px]">
              ▼
            </div>
          </div>
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Nền Tảng Backtest</label>
          <div className="relative">
            <select
              value={config.engine_type}
              onChange={(e) => updateField('engine_type', e.target.value as 'nautilus' | 'direct')}
              className="w-full bg-slate-950 border border-slate-700/80 rounded-lg px-3 py-2 text-xs font-semibold text-sky-400 focus:outline-none focus:ring-1 focus:ring-sky-500 focus:border-sky-500 transition-all appearance-none cursor-pointer"
            >
              <option value="nautilus">Nautilus Trader</option>
              <option value="direct">Direct Vector</option>
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-400 text-[10px]">
              ▼
            </div>
          </div>
        </div>
      </div>

      {/* Capital Allocation */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Vốn Ban Đầu (VNĐ)</label>
          <input
            type="number"
            value={config.initial_cash}
            step={100_000_000}
            onChange={(e) => updateField('initial_cash', parseFloat(e.target.value) || 1_000_000_000)}
            className="w-full bg-slate-950 border border-slate-700/80 rounded-lg px-3 py-2 text-xs font-mono text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500 transition-all"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-400 mb-1.5">Base Lô N% NAV (V0)</label>
          <input
            type="number"
            value={Math.round(config.base_nav_pct * 100)}
            step={1}
            min={1}
            max={20}
            onChange={(e) => updateField('base_nav_pct', (parseFloat(e.target.value) || 4) / 100)}
            className="w-full bg-slate-950 border border-slate-700/80 rounded-lg px-3 py-2 text-xs font-mono text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500 transition-all"
          />
        </div>
      </div>

      {/* Date Range & All History (Default: Checked) */}
      <div className="flex flex-col gap-2 p-3 bg-slate-950/60 rounded-lg border border-slate-800">
        <label className="flex items-center gap-2.5 text-xs text-slate-200 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={config.all_history}
            onChange={(e) => updateField('all_history', e.target.checked)}
            className="w-4 h-4 rounded border-slate-700 text-sky-500 focus:ring-0 focus:ring-offset-0 bg-slate-900 cursor-pointer"
          />
          <span className="font-medium text-sky-300">Toàn bộ lịch sử (Năm 2000 ➔ Nay)</span>
        </label>

        {!config.all_history && (
          <div className="grid grid-cols-2 gap-2 mt-2 pt-2 border-t border-slate-800/80 animate-fadeIn">
            <div>
              <span className="block text-[11px] text-slate-400 mb-1">Từ ngày</span>
              <input
                type="date"
                value={config.start_date}
                onChange={(e) => updateField('start_date', e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-sky-500"
              />
            </div>
            <div>
              <span className="block text-[11px] text-slate-400 mb-1">Đến ngày</span>
              <input
                type="date"
                value={config.end_date}
                onChange={(e) => updateField('end_date', e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-sky-500"
              />
            </div>
          </div>
        )}
      </div>

      {/* Parameters & Model Windows */}
      <div className="bg-slate-950/40 p-3.5 rounded-lg border border-slate-800/80 flex flex-col gap-3">
        <div className="flex items-center justify-between pb-1 border-b border-slate-800/60">
          <span className="text-xs font-semibold text-slate-300">📐 Tham Số & Chu Kỳ</span>
          <span className="text-[10px] text-slate-400">7 Luận Điểm A-G</span>
        </div>

        <div className="grid grid-cols-2 gap-2.5">
          <div>
            <label className="block text-[11px] text-slate-400 mb-1">Mô Hình LRC</label>
            <input
              type="text"
              value={config.linear_window ?? 'Expand Liên Tục'}
              disabled
              className="w-full bg-slate-900/60 border border-slate-800 rounded px-2.5 py-1.5 text-xs font-mono text-sky-400 cursor-not-allowed"
            />
          </div>

          <div>
            <label className="block text-[11px] text-slate-400 mb-1">Chu Kỳ SMA (Cap 1500)</label>
            <input
              type="number"
              value={config.sma_window}
              min={5}
              max={1500}
              onChange={(e) => updateField('sma_window', Math.min(parseInt(e.target.value) || 1500, 1500))}
              className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs font-mono text-slate-100 focus:outline-none focus:border-sky-500"
            />
          </div>

          <div>
            <label className="block text-[11px] text-slate-400 mb-1">Chuẩn Hóa Z-Score</label>
            <input
              type="number"
              value={config.z_score_window}
              min={10}
              max={1500}
              onChange={(e) => updateField('z_score_window', parseInt(e.target.value) || 120)}
              className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs font-mono text-slate-100 focus:outline-none focus:border-sky-500"
            />
          </div>

          <div>
            <label className="block text-[11px] text-slate-400 mb-1">Bộ Lọc SMA 20</label>
            <input
              type="number"
              value={config.sma20_period}
              min={2}
              max={100}
              onChange={(e) => updateField('sma20_period', parseInt(e.target.value) || 20)}
              className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs font-mono text-slate-100 focus:outline-none focus:border-sky-500"
            />
          </div>

          <div>
            <label className="block text-[11px] text-slate-400 mb-1">Vùng +/- N ATR</label>
            <input
              type="number"
              step={0.1}
              value={config.atr_multiplier}
              min={0.1}
              max={5.0}
              onChange={(e) => updateField('atr_multiplier', parseFloat(e.target.value) || 1.0)}
              className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs font-mono text-slate-100 focus:outline-none focus:border-sky-500"
            />
          </div>

          <div>
            <label className="block text-[11px] text-slate-400 mb-1">Luận Điểm Tối Thiểu</label>
            <select
              value={config.min_theses}
              onChange={(e) => updateField('min_theses', parseInt(e.target.value) || 4)}
              className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-sky-500 cursor-pointer"
            >
              <option value={1}>1 / 7 Luận điểm</option>
              <option value={2}>2 / 7 Luận điểm</option>
              <option value={3}>3 / 7 Luận điểm</option>
              <option value={4}>4 / 7 Luận điểm (Chuẩn)</option>
              <option value={5}>5 / 7 Luận điểm</option>
              <option value={6}>6 / 7 Luận điểm</option>
              <option value={7}>7 / 7 Luận điểm</option>
            </select>
          </div>
        </div>

        <label className="flex items-center gap-2 text-xs text-slate-400 hover:text-slate-300 cursor-pointer mt-1 select-none">
          <input
            type="checkbox"
            checked={config.use_synthetic}
            onChange={(e) => updateField('use_synthetic', e.target.checked)}
            className="w-3.5 h-3.5 rounded border-slate-700 text-sky-500 bg-slate-900 cursor-pointer"
          />
          <span>Dữ liệu giả lập chuẩn hóa (Synthetic)</span>
        </label>
      </div>

      {/* Run Backtest Button */}
      <button
        onClick={onRun}
        disabled={loading}
        className={`w-full py-3 px-4 rounded-lg font-semibold text-xs tracking-wide uppercase transition-all duration-200 shadow-lg ${
          loading
            ? 'bg-slate-800 text-slate-500 cursor-not-allowed shadow-none'
            : 'bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 text-white shadow-sky-500/25 active:scale-[0.98]'
        }`}
      >
        {loading ? '⏳ Đang Thực Thi Backtest...' : '▶ KHỞI CHẠY BACKTEST'}
      </button>
    </aside>
  );
};
