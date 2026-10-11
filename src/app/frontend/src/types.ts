export interface CandleBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface LinePoint {
  time: number;
  value: number;
}

export interface ChartMarker {
  time: number;
  position: 'aboveBar' | 'belowBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square';
  text: string;
  size?: number;
}

export interface TradeItem {
  trade_id: number;
  date: string;
  action: 'BUY' | 'SELL';
  price: number;
  shares: number;
  amount: number;
  fee_tax: number;
  factor: number;
  theses_count: number;
  reason: string;
  nav: number;
  level?: number;
  pnl?: number;
  surplus_after?: number;
}

export interface BacktestSummaryMetrics {
  initial_nav: number;
  final_nav: number;
  total_return_pct: number;
  cagr_pct: number;
  benchmark_return_pct: number;
  alpha_pct: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  win_rate_pct: number;
  profit_factor: number;
  total_trades: number;
  buy_trades: number;
  sell_trades: number;
}

export interface BacktestRunResponse {
  symbol: string;
  engine: string;
  summary: BacktestSummaryMetrics;
  candles: CandleBar[];
  p_suggest: LinePoint[];
  support?: LinePoint[];
  resistance?: LinePoint[];
  buy_threshold: LinePoint[];
  sell_threshold: LinePoint[];
  sma20: LinePoint[];
  expected_return: LinePoint[];
  pqr_series: LinePoint[];
  pqt_series: LinePoint[];
  pr_series: LinePoint[];
  pt_series: LinePoint[];
  div_yield_series: LinePoint[];
  theses_count: LinePoint[];
  loser_ratio?: LinePoint[];
  equity_curve: LinePoint[];
  benchmark_curve: LinePoint[];
  drawdown_curve: LinePoint[];
  plus_di?: LinePoint[];
  minus_di?: LinePoint[];
  adx?: LinePoint[];
  position_shares?: LinePoint[];
  position_level?: LinePoint[];
  markers: ChartMarker[];
  trades: TradeItem[];
}

export interface BacktestRunRequest {
  symbol: string;
  start_date: string;
  end_date: string;
  initial_cash: number;
  base_nav_pct: number;
  lot_size: number;
  window: number;
  linear_window?: number | null;
  sma_window: number;
  beta_window: number;
  z_score_window: number;
  sma20_period: number;
  atr_period: number;
  atr_multiplier: number;
  min_theses: number;
  expanding: boolean;
  all_history: boolean;
  use_synthetic: boolean;
  engine_type: 'nautilus' | 'direct';
}
