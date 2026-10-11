import React, { useEffect, useRef, useState } from 'react';
import {
  createChart,
  LineSeries,
  ColorType,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type Time,
  type LogicalRange,
  type MouseEventParams,
} from 'lightweight-charts';
import { chartSync } from '../chartSync';
import type { LinePoint } from '../types';

interface DMIChartProps {
  plusDiSeries?: LinePoint[];
  minusDiSeries?: LinePoint[];
  adxSeries?: LinePoint[];
}

export const DMIChart: React.FC<DMIChartProps> = ({
  plusDiSeries = [],
  minusDiSeries = [],
  adxSeries = [],
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const plusDiLineRef = useRef<ISeriesApi<'Line'> | null>(null);
  const minusDiLineRef = useRef<ISeriesApi<'Line'> | null>(null);
  const adxLineRef = useRef<ISeriesApi<'Line'> | null>(null);

  const [showPlusDi, setShowPlusDi] = useState<boolean>(true);
  const [showMinusDi, setShowMinusDi] = useState<boolean>(true);
  const [showAdx, setShowAdx] = useState<boolean>(true);

  useEffect(() => {
    if (!containerRef.current) return;

    const container = containerRef.current;
    const chart = createChart(container, {
      width: container.clientWidth,
      height: 220,
      layout: {
        background: { type: ColorType.Solid, color: '#0f172a' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: 'rgba(30, 41, 59, 0.4)' },
        horzLines: { color: 'rgba(30, 41, 59, 0.4)' },
      },
      rightPriceScale: {
        borderColor: '#334155',
        autoScale: true,
      },
      timeScale: {
        borderColor: '#334155',
        timeVisible: true,
      },
    });
    chartRef.current = chart;

    // +DI series (Green)
    plusDiLineRef.current = chart.addSeries(LineSeries, {
      color: '#10b981',
      lineWidth: 2,
      title: '+DI',
      priceLineVisible: false,
      lastValueVisible: false,
    });

    // -DI series (Red)
    minusDiLineRef.current = chart.addSeries(LineSeries, {
      color: '#f43f5e',
      lineWidth: 2,
      title: '-DI',
      priceLineVisible: false,
      lastValueVisible: false,
    });

    // ADX series (Amber)
    adxLineRef.current = chart.addSeries(LineSeries, {
      color: '#f59e0b',
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      title: 'ADX',
      priceLineVisible: false,
      lastValueVisible: false,
    });

    // 25 Level line (Trend threshold)
    const adx25Line = chart.addSeries(LineSeries, {
      color: 'rgba(148, 163, 184, 0.35)',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      title: '25',
      priceLineVisible: false,
      lastValueVisible: false,
    });

    // Register with ChartSyncManager using adx as primary
    const dataMap = new Map<number, number>();
    adxSeries.forEach((p) => dataMap.set(p.time, p.value));
    chartSync.register({
      id: 'dmi',
      chart,
      primarySeries: adxLineRef.current,
      dataMap,
    });

    const onRangeChange = (range: LogicalRange | null) => {
      chartSync.syncLogicalRange('dmi', range);
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange);

    const onCrosshairMove = (param: MouseEventParams<Time>) => {
      chartSync.syncCrosshair('dmi', param);
    };
    chart.subscribeCrosshairMove(onCrosshairMove);

    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
        });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRangeChange);
      chart.unsubscribeCrosshairMove(onCrosshairMove);
      chartSync.unregister('dmi');
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    plusDiLineRef.current?.applyOptions({ visible: showPlusDi });
  }, [showPlusDi]);

  useEffect(() => {
    minusDiLineRef.current?.applyOptions({ visible: showMinusDi });
  }, [showMinusDi]);

  useEffect(() => {
    adxLineRef.current?.applyOptions({ visible: showAdx });
  }, [showAdx]);

  useEffect(() => {
    if (plusDiLineRef.current && plusDiSeries.length > 0) {
      plusDiLineRef.current.setData(
        plusDiSeries
          .filter((p) => Number.isFinite(p.value))
          .map((p) => ({ time: p.time as unknown as Time, value: p.value }))
      );
    }
    if (minusDiLineRef.current && minusDiSeries.length > 0) {
      minusDiLineRef.current.setData(
        minusDiSeries
          .filter((p) => Number.isFinite(p.value))
          .map((p) => ({ time: p.time as unknown as Time, value: p.value }))
      );
    }
    if (adxLineRef.current && adxSeries.length > 0) {
      adxLineRef.current.setData(
        adxSeries
          .filter((p) => Number.isFinite(p.value))
          .map((p) => ({ time: p.time as unknown as Time, value: p.value }))
      );
    }

    const dataMap = new Map<number, number>();
    adxSeries.forEach((p) => dataMap.set(p.time, p.value));
    chartSync.updateDataMap('dmi', dataMap);
  }, [plusDiSeries, minusDiSeries, adxSeries]);

  const lastPlus = plusDiSeries && plusDiSeries.length > 0 ? plusDiSeries[plusDiSeries.length - 1].value : 0;
  const lastMinus = minusDiSeries && minusDiSeries.length > 0 ? minusDiSeries[minusDiSeries.length - 1].value : 0;
  const lastAdx = adxSeries && adxSeries.length > 0 ? adxSeries[adxSeries.length - 1].value : 0;
  const isBull = lastPlus > lastMinus;

  return (
    <div style={{ background: '#0f172a', borderRadius: '8px', border: '1px solid #1e293b', overflow: 'hidden' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 16px', background: '#1e293b', borderBottom: '1px solid #334155', flexWrap: 'wrap', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontWeight: 700, fontSize: '13px', color: '#f8fafc' }}>⚡ Chỉ Báo DMI & ADX (14)</span>
          <span style={{ fontSize: '12px', color: '#10b981', fontWeight: 600 }}>+DI: {lastPlus.toFixed(1)}</span>
          <span style={{ fontSize: '12px', color: '#f43f5e', fontWeight: 600 }}>-DI: {lastMinus.toFixed(1)}</span>
          <span style={{ fontSize: '12px', color: '#f59e0b', fontWeight: 600 }}>ADX: {lastAdx.toFixed(1)}</span>
          <span style={{ fontSize: '11px', background: isBull ? 'rgba(16, 185, 129, 0.15)' : 'rgba(244, 63, 94, 0.15)', color: isBull ? '#10b981' : '#f43f5e', padding: '2px 8px', borderRadius: '4px', fontWeight: 600 }}>
            {isBull ? 'Bullish (+DI > -DI)' : 'Bearish (-DI > +DI)'} {lastAdx >= 25 ? '• Xu Hướng Mạnh' : '• Đi Ngang (Chop)'}
          </span>
        </div>

        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          <button
            onClick={() => setShowPlusDi(!showPlusDi)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              background: showPlusDi ? 'rgba(16, 185, 129, 0.15)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showPlusDi ? '#10b981' : '#334155'}`,
              padding: '2px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showPlusDi ? '#10b981' : '#64748b',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showPlusDi ? '#10b981' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            +DI
          </button>

          <button
            onClick={() => setShowMinusDi(!showMinusDi)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              background: showMinusDi ? 'rgba(244, 63, 94, 0.15)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showMinusDi ? '#f43f5e' : '#334155'}`,
              padding: '2px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showMinusDi ? '#f43f5e' : '#64748b',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showMinusDi ? '#f43f5e' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            -DI
          </button>

          <button
            onClick={() => setShowAdx(!showAdx)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              background: showAdx ? 'rgba(245, 158, 11, 0.15)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showAdx ? '#f59e0b' : '#334155'}`,
              padding: '2px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showAdx ? '#f59e0b' : '#64748b',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showAdx ? '#f59e0b' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            ADX
          </button>
        </div>
      </div>
      <div ref={containerRef} style={{ width: '100%', height: '220px' }} />
    </div>
  );
};
