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
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: '8px', padding: '16px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #334155', paddingBottom: '12px' }}>
        <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '8px' }}>
          ⚙️ Cấu Hình Chiến Lược
        </h3>
        <span style={{ fontSize: '11px', background: '#334155', color: '#94a3b8', padding: '2px 6px', borderRadius: '4px' }}>
          Fibonacci 1,1,2,3,5
        </span>
      </div>

      {/* Symbol & Engine */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        <div>
          <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>Mã Cổ Phiếu</label>
          <select
            value={config.symbol}
            onChange={(e) => updateField('symbol', e.target.value)}
            style={{ width: '100%', background: '#1e293b', color: '#f8fafc', border: '1px solid #334155', borderRadius: '4px', padding: '6px 8px', fontSize: '13px' }}
          >
            {symbols.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>Nền Tảng Backtest</label>
          <select
            value={config.engine_type}
            onChange={(e) => updateField('engine_type', e.target.value as 'nautilus' | 'direct')}
            style={{ width: '100%', background: '#1e293b', color: '#38bdf8', fontWeight: 600, border: '1px solid #334155', borderRadius: '4px', padding: '6px 8px', fontSize: '13px' }}
          >
            <option value="nautilus">Nautilus Trader (Official)</option>
            <option value="direct">Direct Vector Engine</option>
          </select>
        </div>
      </div>

      {/* Initial Cash & Base NAV % */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        <div>
          <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>Vốn Ban Đầu (VNĐ)</label>
          <input
            type="number"
            value={config.initial_cash}
            step={100_000_000}
            onChange={(e) => updateField('initial_cash', parseFloat(e.target.value) || 1_000_000_000)}
            style={{ width: '100%', background: '#1e293b', color: '#f8fafc', border: '1px solid #334155', borderRadius: '4px', padding: '6px 8px', fontSize: '13px' }}
          />
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>Base Lô N% NAV (F1)</label>
          <input
            type="number"
            value={config.base_nav_pct * 100}
            step={1}
            min={1}
            max={20}
            onChange={(e) => updateField('base_nav_pct', (parseFloat(e.target.value) || 4) / 100)}
            style={{ width: '100%', background: '#1e293b', color: '#f8fafc', border: '1px solid #334155', borderRadius: '4px', padding: '6px 8px', fontSize: '13px' }}
          />
        </div>
      </div>

      {/* Date Range & All History Option */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>Ngày Bắt Đầu</label>
            <input
              type="date"
              value={config.all_history ? '2000-01-01' : config.start_date}
              disabled={config.all_history}
              onChange={(e) => updateField('start_date', e.target.value)}
              style={{ width: '100%', background: config.all_history ? '#0f172a' : '#1e293b', color: config.all_history ? '#64748b' : '#f8fafc', border: '1px solid #334155', borderRadius: '4px', padding: '6px 8px', fontSize: '13px', opacity: config.all_history ? 0.7 : 1 }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>Ngày Kết Thúc</label>
            <input
              type="date"
              value={config.all_history ? new Date().toISOString().split('T')[0] : config.end_date}
              disabled={config.all_history}
              onChange={(e) => updateField('end_date', e.target.value)}
              style={{ width: '100%', background: config.all_history ? '#0f172a' : '#1e293b', color: config.all_history ? '#64748b' : '#f8fafc', border: '1px solid #334155', borderRadius: '4px', padding: '6px 8px', fontSize: '13px', opacity: config.all_history ? 0.7 : 1 }}
            />
          </div>
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px', color: config.all_history ? '#38bdf8' : '#cbd5e1', cursor: 'pointer', padding: '4px 6px', background: config.all_history ? 'rgba(56, 189, 248, 0.1)' : 'transparent', borderRadius: '4px', border: `1px solid ${config.all_history ? 'rgba(56, 189, 248, 0.3)' : 'transparent'}` }}>
          <input
            type="checkbox"
            checked={config.all_history}
            onChange={(e) => updateField('all_history', e.target.checked)}
          />
          <span style={{ fontWeight: config.all_history ? 600 : 400 }}>Toàn bộ lịch sử (Năm 2000 ➔ Nay)</span>
        </label>
      </div>

      {/* Strategy Indicator Windows */}
      <div style={{ background: '#1e293b', padding: '12px', borderRadius: '6px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #334155', paddingBottom: '6px' }}>
          <span style={{ fontSize: '12px', fontWeight: 700, color: '#f8fafc' }}>
            📏 Chu Kỳ Các Mô Hình Định Lượng
          </span>
          {config.expanding && (
            <span style={{ fontSize: '10px', background: '#2563eb', color: '#fff', padding: '1px 5px', borderRadius: '3px', fontWeight: 600 }}>
              EXPANDING
            </span>
          )}
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px', color: config.expanding ? '#38bdf8' : '#cbd5e1', cursor: 'pointer', padding: '4px 6px', background: config.expanding ? 'rgba(56, 189, 248, 0.1)' : 'rgba(15, 23, 42, 0.5)', borderRadius: '4px', border: `1px solid ${config.expanding ? 'rgba(56, 189, 248, 0.3)' : '#334155'}` }}>
          <input
            type="checkbox"
            checked={config.expanding}
            onChange={(e) => updateField('expanding', e.target.checked)}
          />
          <span style={{ fontWeight: config.expanding ? 600 : 400 }}>
            Expanding Window (Không giới hạn window)
          </span>
        </label>

        {config.expanding && (
          <div style={{ fontSize: '10px', color: '#38bdf8', background: 'rgba(56, 189, 248, 0.08)', padding: '4px 8px', borderRadius: '4px', lineHeight: '1.4' }}>
            ℹ️ Các mô hình Tuyến tính, SMA, Beta và Z-Score sẽ tích lũy mở rộng toàn bộ lịch sử từ phiên đầu tiên.
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '11px', color: '#94a3b8', marginBottom: '2px' }}>Độ Dài Tuyến Tính (LRC)</label>
            <input
              type="number"
              value={config.linear_window}
              min={5}
              max={300}
              onChange={(e) => updateField('linear_window', parseInt(e.target.value) || 30)}
              style={{ width: '100%', background: '#0f172a', color: '#f8fafc', border: '1px solid #334155', borderRadius: '4px', padding: '4px 6px', fontSize: '12px' }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '11px', color: '#94a3b8', marginBottom: '2px' }}>Độ Dài Đường SMA</label>
            <input
              type="number"
              value={config.sma_window}
              min={5}
              max={300}
              onChange={(e) => updateField('sma_window', parseInt(e.target.value) || 30)}
              style={{ width: '100%', background: '#0f172a', color: '#f8fafc', border: '1px solid #334155', borderRadius: '4px', padding: '4px 6px', fontSize: '12px' }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '11px', color: '#94a3b8', marginBottom: '2px' }}>Cửa Sổ Hồi Quy Beta</label>
            <input
              type="number"
              value={config.beta_window}
              min={5}
              max={300}
              onChange={(e) => updateField('beta_window', parseInt(e.target.value) || 30)}
              style={{ width: '100%', background: '#0f172a', color: '#f8fafc', border: '1px solid #334155', borderRadius: '4px', padding: '4px 6px', fontSize: '12px' }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '11px', color: '#94a3b8', marginBottom: '2px' }}>Chuẩn Hóa Z-Score</label>
            <input
              type="number"
              value={config.z_score_window}
              min={10}
              max={500}
              onChange={(e) => updateField('z_score_window', parseInt(e.target.value) || 120)}
              style={{ width: '100%', background: '#0f172a', color: '#f8fafc', border: '1px solid #334155', borderRadius: '4px', padding: '4px 6px', fontSize: '12px' }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '11px', color: '#94a3b8', marginBottom: '2px' }}>Bộ Lọc Xu Hướng SMA</label>
            <input
              type="number"
              value={config.sma20_period}
              min={2}
              max={100}
              onChange={(e) => updateField('sma20_period', parseInt(e.target.value) || 20)}
              style={{ width: '100%', background: '#0f172a', color: '#f8fafc', border: '1px solid #334155', borderRadius: '4px', padding: '4px 6px', fontSize: '12px' }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '11px', color: '#94a3b8', marginBottom: '2px' }}>Vùng +/- N ATR</label>
            <input
              type="number"
              step={0.1}
              value={config.atr_multiplier}
              min={0.1}
              max={5.0}
              onChange={(e) => updateField('atr_multiplier', parseFloat(e.target.value) || 1.0)}
              style={{ width: '100%', background: '#0f172a', color: '#f8fafc', border: '1px solid #334155', borderRadius: '4px', padding: '4px 6px', fontSize: '12px' }}
            />
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px' }}>
          <label style={{ fontSize: '11px', color: '#94a3b8' }}>Luận Điểm Tối Thiểu Mua</label>
          <select
            value={config.min_theses}
            onChange={(e) => updateField('min_theses', parseInt(e.target.value) || 3)}
            style={{ background: '#0f172a', color: '#f8fafc', border: '1px solid #334155', borderRadius: '4px', padding: '3px 8px', fontSize: '12px' }}
          >
            <option value={1}>1 / 5 luận điểm</option>
            <option value={2}>2 / 5 luận điểm</option>
            <option value={3}>3 / 5 luận điểm (Chuẩn)</option>
            <option value={4}>4 / 5 luận điểm</option>
            <option value={5}>5 / 5 luận điểm</option>
          </select>
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px', color: '#cbd5e1', cursor: 'pointer', marginTop: '4px' }}>
          <input
            type="checkbox"
            checked={config.use_synthetic}
            onChange={(e) => updateField('use_synthetic', e.target.checked)}
          />
          <span>Dữ liệu giả lập 3 năm (Synthetic)</span>
        </label>
      </div>

      {/* Button Run */}
      <button
        onClick={onRun}
        disabled={loading}
        style={{
          width: '100%',
          padding: '12px',
          background: loading ? '#475569' : 'linear-gradient(135deg, #2563eb, #1d4ed8)',
          color: '#ffffff',
          fontWeight: 700,
          fontSize: '14px',
          border: 'none',
          borderRadius: '6px',
          cursor: loading ? 'not-allowed' : 'pointer',
          boxShadow: '0 4px 12px rgba(37, 99, 235, 0.3)',
          transition: 'all 0.2s ease',
        }}
      >
        {loading ? '⏳ Đang Chạy Backtest...' : '🚀 Chạy Backtest Định Lượng'}
      </button>
    </div>
  );
};
