import React, { useState } from 'react';
import type { TradeItem, BacktestSummaryMetrics } from '../types';

interface TradeAnalysisPanelProps {
  trades: TradeItem[];
  summary: BacktestSummaryMetrics | null;
}

export const TradeAnalysisPanel: React.FC<TradeAnalysisPanelProps> = ({ trades }) => {
  const [filterAction, setFilterAction] = useState<'ALL' | 'BUY' | 'SELL'>('ALL');
  const [searchDate, setSearchDate] = useState<string>('');

  const filteredTrades = trades.filter((t) => {
    if (filterAction !== 'ALL' && t.action !== filterAction) return false;
    if (searchDate && !t.date.includes(searchDate)) return false;
    return true;
  });

  return (
    <div className="w-full bg-slate-900/90 backdrop-blur-md border border-slate-800 rounded-xl overflow-hidden shadow-xl shadow-black/20 text-slate-200">
      {/* Header & Controls Toolbar */}
      <div className="p-4 bg-slate-900 border-b border-slate-800/80 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="text-base">📋</span>
            <h3 className="font-semibold text-sm text-slate-100 tracking-tight">
              Nhật Ký Lệnh & Khớp V_order
            </h3>
            <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 font-mono">
              {filteredTrades.length} / {trades.length}
            </span>
          </div>

          <div className="flex rounded-lg p-0.5 bg-slate-950 border border-slate-800 text-xs">
            {(['ALL', 'BUY', 'SELL'] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => setFilterAction(mode)}
                className={`px-3 py-1 rounded-md font-medium transition-all ${
                  filterAction === mode
                    ? mode === 'BUY'
                      ? 'bg-emerald-500/20 text-emerald-400 font-semibold shadow-sm'
                      : mode === 'SELL'
                      ? 'bg-rose-500/20 text-rose-400 font-semibold shadow-sm'
                      : 'bg-sky-500/20 text-sky-400 font-semibold shadow-sm'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {mode === 'ALL' ? 'Tất cả' : mode === 'BUY' ? 'Lệnh Mua' : 'Lệnh Bán'}
              </button>
            ))}
          </div>
        </div>

        <div className="relative">
          <input
            type="text"
            placeholder="Tìm theo ngày (YYYY-MM-DD)..."
            value={searchDate}
            onChange={(e) => setSearchDate(e.target.value)}
            className="bg-slate-950 border border-slate-700/80 rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-sky-500 transition-all w-60"
          />
          <span className="absolute left-2.5 top-1.5 text-slate-500 text-xs pointer-events-none">🔍</span>
        </div>
      </div>

      {/* Table Container */}
      <div className="max-h-96 overflow-y-auto scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-slate-900">
        <table className="w-full border-collapse text-xs text-left">
          <thead>
            <tr className="bg-slate-950/80 text-slate-400 border-b border-slate-800 sticky top-0 z-10 backdrop-blur font-medium">
              <th className="py-2.5 px-3">#</th>
              <th className="py-2.5 px-3">Ngày</th>
              <th className="py-2.5 px-3">Lệnh</th>
              <th className="py-2.5 px-3 text-right">Giá Khớp</th>
              <th className="py-2.5 px-3 text-right">Khối Lượng</th>
              <th className="py-2.5 px-3 text-right">Giá Trị (VNĐ)</th>
              <th className="py-2.5 px-3 text-center">Cấp Li</th>
              <th className="py-2.5 px-3 text-center">Luận Điểm</th>
              <th className="py-2.5 px-3 text-right">PnL Lệnh</th>
              <th className="py-2.5 px-3">Diễn Giải Chi Tiết</th>
              <th className="py-2.5 px-3 text-right">NAV Sau Lệnh</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono">
            {filteredTrades.length === 0 ? (
              <tr>
                <td colSpan={11} className="py-10 text-center text-slate-500 font-sans">
                  Không tìm thấy giao dịch nào phù hợp với bộ lọc.
                </td>
              </tr>
            ) : (
              filteredTrades.map((t) => {
                const isBuy = t.action === 'BUY';
                const hasPnl = !isBuy && typeof t.pnl === 'number' && Math.abs(t.pnl) > 0.01;
                const pnlPositive = (t.pnl || 0) > 0;
                return (
                  <tr
                    key={t.trade_id}
                    className="hover:bg-slate-800/40 transition-colors group"
                  >
                    <td className="py-2 px-3 text-slate-500">#{t.trade_id}</td>
                    <td className="py-2 px-3 text-slate-300 font-medium font-sans whitespace-nowrap">{t.date}</td>
                    <td className="py-2 px-3">
                      <span
                        className={`inline-block px-2 py-0.5 rounded text-[10px] font-bold tracking-wide uppercase ${
                          isBuy
                            ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                            : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                        }`}
                      >
                        {t.action}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-right font-semibold text-slate-100">
                      {t.price.toLocaleString('vi-VN')}
                    </td>
                    <td className="py-2 px-3 text-right text-slate-200">
                      {t.shares.toLocaleString('vi-VN')}
                    </td>
                    <td className="py-2 px-3 text-right text-slate-300">
                      {t.amount.toLocaleString('vi-VN')}
                    </td>
                    <td className="py-2 px-3 text-center">
                      <span className="px-1.5 py-0.5 rounded text-[11px] font-bold bg-sky-500/15 text-sky-400 border border-sky-500/20">
                        L{t.level ?? t.factor}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-center">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[11px] font-semibold ${
                          t.theses_count >= 4
                            ? 'bg-emerald-500/20 text-emerald-300'
                            : t.theses_count > 0
                            ? 'bg-slate-800 text-slate-300'
                            : 'bg-rose-500/20 text-rose-300'
                        }`}
                      >
                        {t.theses_count}/7
                      </span>
                    </td>
                    <td className="py-2 px-3 text-right">
                      {hasPnl ? (
                        <span className={`font-semibold ${pnlPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {pnlPositive ? '+' : ''}{(t.pnl || 0).toLocaleString('vi-VN', { maximumFractionDigits: 0 })}
                        </span>
                      ) : (
                        <span className="text-slate-600">-</span>
                      )}
                    </td>
                    <td className="py-2 px-3 text-slate-400 font-sans text-[11px] max-w-xs truncate" title={t.reason}>
                      {t.reason}
                    </td>
                    <td className="py-2 px-3 text-right font-semibold text-sky-400">
                      {t.nav > 0 ? t.nav.toLocaleString('vi-VN', { maximumFractionDigits: 0 }) : '-'}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
