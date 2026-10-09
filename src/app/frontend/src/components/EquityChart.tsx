import React, { useEffect, useRef } from 'react';
import {
  createChart,
  LineSeries,
  LineStyle,
  ColorType,
  type IChartApi,
  type ISeriesApi,
  type Time,
  type LogicalRange,
  type MouseEventParams,
} from 'lightweight-charts';
import { chartSync } from '../chartSync';
import type { LinePoint, BacktestSummaryMetrics } from '../types';

interface EquityChartProps {
  equityCurve: LinePoint[];
  benchmarkCurve: LinePoint[];
  initialNav: number;
  summary?: BacktestSummaryMetrics | null;
}

export const EquityChart: React.FC<EquityChartProps> = ({
  equityCurve,
  benchmarkCurve,
  initialNav,
  summary,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const equityLineRef = useRef<ISeriesApi<'Line'> | null>(null);
  const benchLineRef = useRef<ISeriesApi<'Line'> | null>(null);

  // Initialize Chart ONCE
  useEffect(() => {
    if (!containerRef.current) return;

    const container = containerRef.current;
    const chart = createChart(container, {
      width: container.clientWidth,
      height: 240,
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

    equityLineRef.current = chart.addSeries(LineSeries, {
      color: '#38bdf8',
      lineWidth: 2,
      title: 'Strategy NAV',
    });

    benchLineRef.current = chart.addSeries(LineSeries, {
      color: '#64748b',
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      title: 'Benchmark Buy & Hold',
    });
    // Register with ChartSyncManager
    const dataMap = new Map<number, number>();
    equityCurve.forEach((p) => dataMap.set(p.time, p.value));
    chartSync.register({
      id: 'equity',
      chart,
      primarySeries: equityLineRef.current,
      dataMap,
    });

    const onRangeChange = (range: LogicalRange | null) => {
      chartSync.syncLogicalRange('equity', range);
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange);

    const onCrosshairMove = (param: MouseEventParams<Time>) => {
      chartSync.syncCrosshair('equity', param);
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
      chartSync.unregister('equity');
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, []);

  // Update Data
  useEffect(() => {
    if (equityLineRef.current && equityCurve) {
      equityLineRef.current.setData(
        equityCurve.map((p) => ({ time: p.time as unknown as Time, value: p.value }))
      );
      if (equityCurve.length > 0) {
        chartRef.current?.timeScale().fitContent();
      }
    }
    if (benchLineRef.current && benchmarkCurve) {
      benchLineRef.current.setData(
        benchmarkCurve.map((p) => ({ time: p.time as unknown as Time, value: p.value }))
      );
    }
    const dataMap = new Map<number, number>();
    equityCurve.forEach((p) => dataMap.set(p.time, p.value));
    chartSync.updateDataMap('equity', dataMap);
  }, [equityCurve, benchmarkCurve]);

  return (
    <div style={{ position: 'relative', width: '100%', background: '#0f172a', borderRadius: '8px', border: '1px solid #1e293b', overflow: 'hidden' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 16px', background: '#1e293b', borderBottom: '1px solid #334155' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontWeight: 600, fontSize: '13px', color: '#f8fafc' }}>📈 Equity Curve (NAV VNĐ)</span>
          {summary && (
            <span style={{ fontSize: '12px', color: summary.total_return_pct >= 0 ? '#10b981' : '#ef4444', fontWeight: 600 }}>
              Return: {summary.total_return_pct > 0 ? '+' : ''}{summary.total_return_pct}%
            </span>
          )}

        </div>
        <div style={{ display: 'flex', gap: '14px', fontSize: '12px' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ width: '8px', height: '8px', background: '#38bdf8', borderRadius: '2px', display: 'inline-block' }} />
            <span style={{ color: '#94a3b8' }}>Strategy NAV</span>
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ width: '8px', height: '8px', background: '#64748b', borderRadius: '2px', display: 'inline-block' }} />
            <span style={{ color: '#94a3b8' }}>Buy & Hold ({summary?.benchmark_return_pct || 0}%)</span>
          </span>
        </div>
      </div>
      <div ref={containerRef} style={{ width: '100%', height: '240px' }} />
    </div>
  );
};
