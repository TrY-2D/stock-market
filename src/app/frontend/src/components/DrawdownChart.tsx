import React, { useEffect, useRef } from 'react';
import {
  createChart,
  AreaSeries,
  ColorType,
  type IChartApi,
  type ISeriesApi,
  type Time,
  type LogicalRange,
  type MouseEventParams,
} from 'lightweight-charts';
import { chartSync } from '../chartSync';
import type { LinePoint, BacktestSummaryMetrics } from '../types';

interface DrawdownChartProps {
  drawdownCurve: LinePoint[];
  summary?: BacktestSummaryMetrics | null;
}

export const DrawdownChart: React.FC<DrawdownChartProps> = ({
  drawdownCurve,
  summary,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const areaLineRef = useRef<ISeriesApi<'Area'> | null>(null);

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

    areaLineRef.current = chart.addSeries(AreaSeries, {
      topColor: 'rgba(244, 63, 94, 0.05)',
      bottomColor: 'rgba(244, 63, 94, 0.35)',
      lineColor: '#f43f5e',
      lineWidth: 2,
      title: 'Drawdown %',
    });

    // Register with ChartSyncManager
    const dataMap = new Map<number, number>();
    drawdownCurve.forEach((p) => dataMap.set(p.time, p.value));
    chartSync.register({
      id: 'drawdown',
      chart,
      primarySeries: areaLineRef.current,
      dataMap,
    });

    const onRangeChange = (range: LogicalRange | null) => {
      chartSync.syncLogicalRange('drawdown', range);
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange);

    const onCrosshairMove = (param: MouseEventParams<Time>) => {
      chartSync.syncCrosshair('drawdown', param);
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
      chartSync.unregister('drawdown');
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (areaLineRef.current && drawdownCurve) {
      areaLineRef.current.setData(
        drawdownCurve
          .filter((p) => Number.isFinite(p.value))
          .map((p) => ({ time: p.time as unknown as Time, value: p.value }))
      );
      if (drawdownCurve.length > 0) {
        chartRef.current?.timeScale().fitContent();
      }
    }
    const dataMap = new Map<number, number>();
    drawdownCurve.forEach((p) => dataMap.set(p.time, p.value));
    chartSync.updateDataMap('drawdown', dataMap);
  }, [drawdownCurve]);

  const lastItem = drawdownCurve.length > 0 ? drawdownCurve[drawdownCurve.length - 1] : undefined;
  const currentDD = lastItem ? lastItem.value : 0;

  return (
    <div style={{ position: 'relative', width: '100%', background: '#0f172a', borderRadius: '8px', border: '1px solid #1e293b', overflow: 'hidden' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 16px', background: '#1e293b', borderBottom: '1px solid #334155' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontWeight: 600, fontSize: '13px', color: '#f8fafc' }}>📉 Đường Cong Sụt Giảm (Drawdown Underwater)</span>
          <span style={{ fontSize: '12px', color: '#f43f5e', fontWeight: 600 }}>
            Hiện tại: {currentDD.toFixed(2)}% | Max Drawdown: {summary?.max_drawdown_pct.toFixed(2) || 0}%
          </span>
        </div>
        <div style={{ display: 'flex', gap: '14px', fontSize: '12px' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ width: '8px', height: '8px', background: '#f43f5e', borderRadius: '2px', display: 'inline-block' }} />
            <span style={{ color: '#94a3b8' }}>Mức sụt giảm từ đỉnh (%)</span>
          </span>
        </div>
      </div>
      <div ref={containerRef} style={{ width: '100%', height: '220px' }} />
    </div>
  );
};
