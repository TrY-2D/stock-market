import React, { useEffect, useRef, useState } from 'react';
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  ColorType,
  CrosshairMode,
  LineStyle,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
  type LogicalRange,
  type MouseEventParams,
} from 'lightweight-charts';
import { chartSync } from '../chartSync';
import type { CandleBar, ChartMarker, LinePoint } from '../types';

interface ChartProps {
  bars: CandleBar[];
  markers: ChartMarker[];
  pSuggestSeries: LinePoint[];
  supportSeries?: LinePoint[];
  resistanceSeries?: LinePoint[];
  buyThresholdSeries: LinePoint[];
  sellThresholdSeries: LinePoint[];
  sma20Series: LinePoint[];
  symbol: string;
  engine: string;
}

export const Chart: React.FC<ChartProps> = ({
  bars,
  markers,
  pSuggestSeries,
  supportSeries = [],
  resistanceSeries = [],
  buyThresholdSeries,
  sellThresholdSeries,
  sma20Series,
  symbol,
  engine,
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const pSuggestSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const supportSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const buyThreshSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const resistanceSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const sellThreshSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const sma20SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const markersPrimitiveRef = useRef<{ setMarkers: (m: SeriesMarker<Time>[]) => void } | null>(null);

  // Toggle layer visibility
  const [showPSuggest, setShowPSuggest] = useState<boolean>(true);
  const [showSupportZone, setShowSupportZone] = useState<boolean>(true);
  const [showResistanceZone, setShowResistanceZone] = useState<boolean>(true);
  const [showSMA20, setShowSMA20] = useState<boolean>(true);
  const [showMarkers, setShowMarkers] = useState<boolean>(true);

  // 1. Initialize Chart ONCE on mount
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const container = chartContainerRef.current;
    const chart = createChart(container, {
      width: container.clientWidth,
      height: 480,
      layout: {
        background: { type: ColorType.Solid, color: '#0f172a' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: 'rgba(30, 41, 59, 0.4)' },
        horzLines: { color: 'rgba(30, 41, 59, 0.4)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: '#334155',
        autoScale: true,
      },
      timeScale: {
        borderColor: '#334155',
        timeVisible: true,
        secondsVisible: false,
      },
    });
    chartRef.current = chart;

    // Series instances
    candleSeriesRef.current = chart.addSeries(CandlestickSeries, {
      upColor: '#089981',
      downColor: '#f23645',
      borderVisible: false,
      wickUpColor: '#089981',
      wickDownColor: '#f23645',
    });

    // P_suggest (Blue dashed)
    pSuggestSeriesRef.current = chart.addSeries(LineSeries, {
      color: 'rgba(56, 189, 248, 0.75)',
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      title: 'P_suggest',
      priceLineVisible: false,
      lastValueVisible: false,
    });

    // Support S (Green solid)
    supportSeriesRef.current = chart.addSeries(LineSeries, {
      color: '#10b981',
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      title: 'Hỗ Trợ (S)',
      priceLineVisible: false,
      lastValueVisible: false,
    });
    // Support zone upper S_top (Green dotted)
    buyThreshSeriesRef.current = chart.addSeries(LineSeries, {
      color: 'rgba(52, 211, 153, 0.75)',
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      title: 'Biên Trên Hỗ Trợ',
      priceLineVisible: false,
      lastValueVisible: false,
    });

    // Resistance R (Red solid)
    resistanceSeriesRef.current = chart.addSeries(LineSeries, {
      color: '#f43f5e',
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      title: 'Kháng Cự (R)',
      priceLineVisible: false,
      lastValueVisible: false,
    });

    // Resistance zone lower R_bottom (Red dotted)
    sellThreshSeriesRef.current = chart.addSeries(LineSeries, {
      color: 'rgba(251, 113, 133, 0.75)',
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      title: 'Biên Dưới Kháng Cự',
      priceLineVisible: false,
      lastValueVisible: false,
    });
    // SMA 20 (Amber line)
    sma20SeriesRef.current = chart.addSeries(LineSeries, {
      color: 'rgba(251, 191, 36, 0.75)',
      lineWidth: 2,
      title: 'SMA 20',
      priceLineVisible: false,
      lastValueVisible: false,
    });

    // Register with ChartSyncManager
    const dataMap = new Map<number, number>();
    bars.forEach((b) => dataMap.set(b.time, b.close));
    chartSync.register({
      id: 'main-ohlc',
      chart,
      primarySeries: candleSeriesRef.current,
      dataMap,
    });

    const onRangeChange = (range: LogicalRange | null) => {
      chartSync.syncLogicalRange('main-ohlc', range);
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange);

    const onCrosshairMove = (param: MouseEventParams<Time>) => {
      chartSync.syncCrosshair('main-ohlc', param);
    };
    chart.subscribeCrosshairMove(onCrosshairMove);

    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRangeChange);
      chart.unsubscribeCrosshairMove(onCrosshairMove);
      chartSync.unregister('main-ohlc');
      markersPrimitiveRef.current = null;
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, []);

  // Update layer visibility dynamically
  useEffect(() => {
    pSuggestSeriesRef.current?.applyOptions({ visible: showPSuggest });
  }, [showPSuggest]);

  useEffect(() => {
    supportSeriesRef.current?.applyOptions({ visible: showSupportZone });
    buyThreshSeriesRef.current?.applyOptions({ visible: showSupportZone });
  }, [showSupportZone]);

  useEffect(() => {
    resistanceSeriesRef.current?.applyOptions({ visible: showResistanceZone });
    sellThreshSeriesRef.current?.applyOptions({ visible: showResistanceZone });
  }, [showResistanceZone]);

  useEffect(() => {
    sma20SeriesRef.current?.applyOptions({ visible: showSMA20 });
  }, [showSMA20]);

  // 2. Update Bars and Indicator Series only when actual data changes
  useEffect(() => {
    if (!candleSeriesRef.current) return;

    if (bars && bars.length > 0) {
      candleSeriesRef.current.setData(
        bars.map((b) => ({
          time: b.time as unknown as Time,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        }))
      );
    }

    const dataMap = new Map<number, number>();
    bars.forEach((b) => dataMap.set(b.time, b.close));
    chartSync.updateDataMap('main-ohlc', dataMap);

    if (pSuggestSeriesRef.current) {
      pSuggestSeriesRef.current.setData(
        (pSuggestSeries || []).filter((p) => Number.isFinite(p.value)).map((p) => ({ time: p.time as unknown as Time, value: p.value }))
      );
    }

    if (supportSeriesRef.current) {
      supportSeriesRef.current.setData(
        (supportSeries || []).filter((p) => Number.isFinite(p.value)).map((p) => ({ time: p.time as unknown as Time, value: p.value }))
      );
    }

    if (buyThreshSeriesRef.current) {
      buyThreshSeriesRef.current.setData(
        (buyThresholdSeries || []).filter((p) => Number.isFinite(p.value)).map((p) => ({ time: p.time as unknown as Time, value: p.value }))
      );
    }

    if (resistanceSeriesRef.current) {
      resistanceSeriesRef.current.setData(
        (resistanceSeries || []).filter((p) => Number.isFinite(p.value)).map((p) => ({ time: p.time as unknown as Time, value: p.value }))
      );
    }

    if (sellThreshSeriesRef.current) {
      sellThreshSeriesRef.current.setData(
        (sellThresholdSeries || []).filter((p) => Number.isFinite(p.value)).map((p) => ({ time: p.time as unknown as Time, value: p.value }))
      );
    }

    if (sma20SeriesRef.current) {
      sma20SeriesRef.current.setData(
        (sma20Series || []).filter((p) => Number.isFinite(p.value)).map((p) => ({ time: p.time as unknown as Time, value: p.value }))
      );
    }
  }, [bars, pSuggestSeries, supportSeries, buyThresholdSeries, resistanceSeries, sellThresholdSeries, sma20Series]);

  // 3. Update Markers smoothly
  useEffect(() => {
    if (!candleSeriesRef.current || !bars || bars.length === 0) return;

    const sortedMarkers: SeriesMarker<Time>[] = (markers || [])
      .filter((m) => Number.isFinite(m.time))
      .map((m) => ({
        time: m.time as unknown as Time,
        position: m.position,
        color: m.color,
        shape: m.shape,
        text: m.text,
        size: m.size || 1,
      }))
      .sort((a, b) => Number(a.time) - Number(b.time));

    try {
      const markersToSet = showMarkers ? sortedMarkers : [];
      if (!markersPrimitiveRef.current) {
        markersPrimitiveRef.current = createSeriesMarkers(candleSeriesRef.current, markersToSet);
      } else {
        markersPrimitiveRef.current.setMarkers(markersToSet);
      }
    } catch (err) {
      console.warn('Failed to update markers:', err);
    }
  }, [markers, bars, showMarkers]);

  // Metrics for header toolbar
  const lastBar = bars && bars.length > 0 ? bars[bars.length - 1] : null;
  const lastPrice = lastBar ? lastBar.close : 0;
  const lastPSuggest = pSuggestSeries && pSuggestSeries.length > 0 ? pSuggestSeries[pSuggestSeries.length - 1].value : 0;
  const lastSup = supportSeries && supportSeries.length > 0 ? supportSeries[supportSeries.length - 1].value : (buyThresholdSeries.length > 0 ? buyThresholdSeries[buyThresholdSeries.length - 1].value : 0);
  const lastBuyTh = buyThresholdSeries && buyThresholdSeries.length > 0 ? buyThresholdSeries[buyThresholdSeries.length - 1].value : 0;
  const lastRes = resistanceSeries && resistanceSeries.length > 0 ? resistanceSeries[resistanceSeries.length - 1].value : (sellThresholdSeries.length > 0 ? sellThresholdSeries[sellThresholdSeries.length - 1].value : 0);
  const lastSellTh = sellThresholdSeries && sellThresholdSeries.length > 0 ? sellThresholdSeries[sellThresholdSeries.length - 1].value : 0;

  return (
    <div style={{ position: 'relative', width: '100%', background: '#0f172a', borderRadius: '8px', border: '1px solid #1e293b', overflow: 'hidden' }}>
      {/* Top Chart Toolbar & Interactive Indicator Toggles */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 16px', background: '#1e293b', borderBottom: '1px solid #334155', flexWrap: 'wrap', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          <span style={{ fontWeight: 700, fontSize: '15px', color: '#f8fafc' }}>{symbol}</span>
          <span style={{ fontSize: '11px', background: '#2563eb', color: '#fff', padding: '2px 8px', borderRadius: '4px', fontWeight: 600 }}>1D</span>
          <span style={{ fontSize: '11px', background: '#059669', color: '#fff', padding: '2px 8px', borderRadius: '4px', fontWeight: 600 }}>{engine}</span>
          {lastPrice > 0 && (
            <span style={{ fontSize: '13px', fontWeight: 700, color: '#f8fafc' }}>
              Giá: {lastPrice.toLocaleString('vi-VN')}
            </span>
          )}
          {lastPSuggest > 0 && (
            <span style={{ fontSize: '12px', color: '#38bdf8', fontWeight: 600 }}>
              P_s: {lastPSuggest.toLocaleString('vi-VN', { maximumFractionDigits: 0 })}
            </span>
          )}
          {lastSup > 0 && (
            <span style={{ fontSize: '12px', color: '#10b981', fontWeight: 600 }} title="Vùng hỗ trợ [S, S_top]">
              Hỗ Trợ: [{lastSup.toLocaleString('vi-VN', { maximumFractionDigits: 0 })}, {lastBuyTh.toLocaleString('vi-VN', { maximumFractionDigits: 0 })}]
            </span>
          )}
          {lastRes > 0 && (
            <span style={{ fontSize: '12px', color: '#f43f5e', fontWeight: 600 }} title="Vùng kháng cự [R_bottom, R]">
              Kháng Cự: [{lastSellTh.toLocaleString('vi-VN', { maximumFractionDigits: 0 })}, {lastRes.toLocaleString('vi-VN', { maximumFractionDigits: 0 })}]
            </span>
          )}
        </div>

        {/* Interactive Indicator Layer Toggles */}
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
          <button
            onClick={() => setShowSupportZone(!showSupportZone)}
            title="Bật/Tắt Vùng Hỗ Trợ [S, S+ATR] (Target point gần giá và nhỏ hơn giá)"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              background: showSupportZone ? 'rgba(16, 185, 129, 0.15)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showSupportZone ? '#10b981' : '#334155'}`,
              padding: '3px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showSupportZone ? '#10b981' : '#64748b',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showSupportZone ? '#10b981' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            Vùng Hỗ Trợ [S, S_top]
          </button>

          <button
            onClick={() => setShowResistanceZone(!showResistanceZone)}
            title="Bật/Tắt Vùng Kháng Cự [R-ATR, R] (Target point gần giá và lớn hơn giá)"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              background: showResistanceZone ? 'rgba(244, 63, 94, 0.15)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showResistanceZone ? '#f43f5e' : '#334155'}`,
              padding: '3px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showResistanceZone ? '#f43f5e' : '#64748b',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showResistanceZone ? '#f43f5e' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            Vùng Kháng Cự [R_bot, R]
          </button>

          <button
            onClick={() => setShowPSuggest(!showPSuggest)}
            title="Bật/Tắt đường giá cơ sở P_suggest (0.5 LRC + 0.5 SMA)"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              background: showPSuggest ? 'rgba(56, 189, 248, 0.12)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showPSuggest ? 'rgba(56, 189, 248, 0.35)' : '#334155'}`,
              padding: '3px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showPSuggest ? '#38bdf8' : '#64748b',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showPSuggest ? '#38bdf8' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            P_suggest
          </button>

          <button
            onClick={() => setShowSMA20(!showSMA20)}
            title="Bật/Tắt đường xu hướng SMA 20"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              background: showSMA20 ? 'rgba(251, 191, 36, 0.12)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showSMA20 ? 'rgba(251, 191, 36, 0.35)' : '#334155'}`,
              padding: '3px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showSMA20 ? '#fbbf24' : '#64748b',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showSMA20 ? '#fbbf24' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            SMA 20
          </button>

          <button
            onClick={() => setShowMarkers(!showMarkers)}
            title="Bật/Tắt mũi tên điểm khớp lệnh"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              background: showMarkers ? 'rgba(192, 132, 252, 0.12)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showMarkers ? 'rgba(192, 132, 252, 0.35)' : '#334155'}`,
              padding: '3px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showMarkers ? '#c084fc' : '#64748b',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showMarkers ? '#c084fc' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            Lệnh Khớp
          </button>
        </div>
      </div>
      <div ref={chartContainerRef} style={{ width: '100%', height: '480px' }} />
    </div>
  );
};
