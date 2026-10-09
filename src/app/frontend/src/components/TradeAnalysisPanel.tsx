import React, { useState } from 'react';
import type { TradeItem, BacktestSummaryMetrics } from '../types';

interface TradeAnalysisPanelProps {
  trades: TradeItem[];
  summary: BacktestSummaryMetrics | null;
}

export const TradeAnalysisPanel: React.FC<TradeAnalysisPanelProps> = ({ trades, summary }) => {
  const [filterAction, setFilterAction] = useState<'ALL' | 'BUY' | 'SELL'>('ALL');
  const [searchDate, setSearchDate] = useState<string>('');

  const filteredTrades = trades.filter((t) => {
    if (filterAction !== 'ALL' && t.action !== filterAction) return false;
    if (searchDate && !t.date.includes(searchDate)) return false;
    return true;
  });

  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', overflow: 'hidden' }}>
      {/* Header & Controls */}
      <div style={{ padding: '12px 16px', background: '#1e293b', borderBottom: '1px solid #334155', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#f8fafc' }}>
            📋 Nhật Ký Giao Dịch & Luận Điểm ({filteredTrades.length}/{trades.length} lệnh)
          </h3>
          <div style={{ display: 'flex', gap: '4px' }}>
            {(['ALL', 'BUY', 'SELL'] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => setFilterAction(mode)}
                style={{
                  padding: '4px 10px',
                  fontSize: '11px',
                  fontWeight: 600,
                  borderRadius: '4px',
                  border: '1px solid #475569',
                  background: filterAction === mode ? '#38bdf8' : '#0f172a',
                  color: filterAction === mode ? '#0f172a' : '#94a3b8',
                  cursor: 'pointer',
                }}
              >
                {mode === 'ALL' ? 'Tất cả' : mode === 'BUY' ? 'Lệnh MUA' : 'Lệnh BÁN'}
              </button>
            ))}
          </div>
        </div>

        <input
          type="text"
          placeholder="Lọc theo ngày (YYYY-MM-DD)..."
          value={searchDate}
          onChange={(e) => setSearchDate(e.target.value)}
          style={{ background: '#0f172a', border: '1px solid #475569', color: '#f8fafc', padding: '4px 10px', borderRadius: '4px', fontSize: '12px', width: '220px' }}
        />
      </div>

      {/* Table */}
      <div style={{ maxHeight: '380px', overflowY: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', textAlign: 'left' }}>
          <thead>
            <tr style={{ background: '#1e293b', color: '#94a3b8', borderBottom: '1px solid #334155', position: 'sticky', top: 0, zIndex: 1 }}>
              <th style={{ padding: '8px 12px' }}>#</th>
              <th style={{ padding: '8px 12px' }}>Ngày</th>
              <th style={{ padding: '8px 12px' }}>Lệnh</th>
              <th style={{ padding: '8px 12px', textAlign: 'right' }}>Giá (VNĐ)</th>
              <th style={{ padding: '8px 12px', textAlign: 'right' }}>Khối Lượng</th>
              <th style={{ padding: '8px 12px', textAlign: 'right' }}>Giá Trị (VNĐ)</th>
              <th style={{ padding: '8px 12px', textAlign: 'right' }}>Phí & Thuế</th>
              <th style={{ padding: '8px 12px', textAlign: 'center' }}>Factor</th>
              <th style={{ padding: '8px 12px', textAlign: 'center' }}>Luận Điểm</th>
              <th style={{ padding: '8px 12px' }}>Lý Do Khớp Lệnh</th>
              <th style={{ padding: '8px 12px', textAlign: 'right' }}>NAV Sau Lệnh</th>
            </tr>
          </thead>
          <tbody>
            {filteredTrades.length === 0 ? (
              <tr>
                <td colSpan={11} style={{ padding: '24px', textAlign: 'center', color: '#64748b' }}>
                  Chưa có giao dịch nào phù hợp tiêu chí lọc.
                </td>
              </tr>
            ) : (
              filteredTrades.map((t) => (
                <tr key={t.trade_id} style={{ borderBottom: '1px solid #1e293b', background: t.trade_id % 2 === 0 ? '#0f172a' : '#141e33' }}>
                  <td style={{ padding: '8px 12px', color: '#64748b' }}>#{t.trade_id}</td>
                  <td style={{ padding: '8px 12px', color: '#cbd5e1', fontWeight: 500 }}>{t.date}</td>
                  <td style={{ padding: '8px 12px' }}>
                    <span
                      style={{
                        padding: '2px 8px',
                        borderRadius: '4px',
                        fontWeight: 700,
                        fontSize: '11px',
                        background: t.action === 'BUY' ? 'rgba(8, 153, 129, 0.2)' : 'rgba(242, 54, 69, 0.2)',
                        color: t.action === 'BUY' ? '#10b981' : '#f43f5e',
                      }}
                    >
                      {t.action}
                    </span>
                  </td>
                  <td style={{ padding: '8px 12px', textAlign: 'right', fontWeight: 600, color: '#f8fafc' }}>
                    {t.price.toLocaleString('vi-VN')}
                  </td>
                  <td style={{ padding: '8px 12px', textAlign: 'right', color: '#cbd5e1' }}>
                    {t.shares.toLocaleString('vi-VN')}
                  </td>
                  <td style={{ padding: '8px 12px', textAlign: 'right', color: '#cbd5e1' }}>
                    {t.amount.toLocaleString('vi-VN')}
                  </td>
                  <td style={{ padding: '8px 12px', textAlign: 'right', color: '#94a3b8' }}>
                    {t.fee_tax.toLocaleString('vi-VN', { maximumFractionDigits: 0 })}
                  </td>
                  <td style={{ padding: '8px 12px', textAlign: 'center', fontWeight: 700, color: '#38bdf8' }}>
                    {t.factor}
                  </td>
                  <td style={{ padding: '8px 12px', textAlign: 'center' }}>
                    <span style={{ padding: '2px 6px', borderRadius: '4px', background: t.theses_count >= 3 ? '#065f46' : '#334155', color: '#f8fafc', fontWeight: 600 }}>
                      {t.theses_count}/5
                    </span>
                  </td>
                  <td style={{ padding: '8px 12px', color: '#94a3b8', fontSize: '11px' }}>
                    {t.reason}
                  </td>
                  <td style={{ padding: '8px 12px', textAlign: 'right', fontWeight: 600, color: '#38bdf8' }}>
                    {t.nav > 0 ? t.nav.toLocaleString('vi-VN', { maximumFractionDigits: 0 }) : '-'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
