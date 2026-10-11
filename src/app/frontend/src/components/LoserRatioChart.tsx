import React, { useEffect, useRef, useState } from 'react';
import {
  createChart,
  AreaSeries,
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

interface LoserRatioChartProps {
  loserRatioSeries?: LinePoint[];
}

export const LoserRatioChart: React.FC<LoserRatioChartProps> = ({
  loserRatioSeries = [],
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const areaLineRef = useRef<ISeriesApi<'Area'> | null>(null);

  const [showLoserRatio, setShowLoserRatio] = useState<boolean>(true);

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

    // Loser Ratio Area Series (Rose/Orange)
    areaLineRef.current = chart.addSeries(AreaSeries, {
      topColor: 'rgba(244, 63, 94, 0.25)',
      bottomColor: 'rgba(244, 63, 94, 0.02)',
      lineColor: '#f43f5e',
      lineWidth: 2,
      priceScaleId: 'right',
      title: 'Loser Ratio %',
    });

    // 50% Median benchmark line
    const ref50Line = chart.addSeries(LineSeries, {
      color: 'rgba(148, 163, 184, 0.40)',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      title: '50% (Thế Cân Bằng)',
      priceLineVisible: false,
      lastValueVisible: false,
    });

    // Register with ChartSyncManager
    const dataMap = new Map<number, number>();
    loserRatioSeries.forEach((p) => dataMap.set(p.time, p.value));
    chartSync.register({
      id: 'loser_ratio',
      chart,
      primarySeries: areaLineRef.current,
      dataMap,
    });

    const onRangeChange = (range: LogicalRange | null) => {
      chartSync.syncLogicalRange('loser_ratio', range);
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange);

    const onCrosshairMove = (param: MouseEventParams<Time>) => {
      chartSync.syncCrosshair('loser_ratio', param);
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
      chartSync.unregister('loser_ratio');
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    areaLineRef.current?.applyOptions({ visible: showLoserRatio });
  }, [showLoserRatio]);

  useEffect(() => {
    if (areaLineRef.current && loserRatioSeries.length > 0) {
      areaLineRef.current.setData(
        loserRatioSeries
          .filter((p) => Number.isFinite(p.value))
          .map((p) => ({ time: p.time as unknown as Time, value: p.value }))
      );
    }

    const dataMap = new Map<number, number>();
    loserRatioSeries.forEach((p) => dataMap.set(p.time, p.value));
    chartSync.updateDataMap('loser_ratio', dataMap);
  }, [loserRatioSeries]);

  const lastVal = loserRatioSeries && loserRatioSeries.length > 0 ? loserRatioSeries[loserRatioSeries.length - 1].value : 50;

  return (
    <div style={{ background: '#0f172a', borderRadius: '8px', border: '1px solid #1e293b', overflow: 'hidden' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 16px', background: '#1e293b', borderBottom: '1px solid #334155', flexWrap: 'wrap', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontWeight: 700, fontSize: '13px', color: '#f8fafc' }}>📉 Tỷ Lệ Loser 3 Năm (Luận Điểm C)</span>
          <span style={{ fontSize: '12px', color: lastVal >= 50 ? '#10b981' : '#f43f5e', fontWeight: 600 }}>
            Hiện tại: {lastVal.toFixed(1)}%
          </span>
          <span style={{ fontSize: '11px', background: lastVal >= 50 ? 'rgba(16, 185, 129, 0.15)' : 'rgba(244, 63, 94, 0.15)', color: lastVal >= 50 ? '#10b981' : '#f43f5e', padding: '2px 8px', borderRadius: '4px', fontWeight: 600 }}>
            {lastVal >= 50 ? 'Đạt Luận Điểm C (Đa số người mua đang lỗ -> Vùng Gom)' : 'Dưới 50% (Đa số đang lãi)'}
          </span>
        </div>

        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          <button
            onClick={() => setShowLoserRatio(!showLoserRatio)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              background: showLoserRatio ? 'rgba(244, 63, 94, 0.15)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showLoserRatio ? '#f43f5e' : '#334155'}`,
              padding: '2px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showLoserRatio ? '#f43f5e' : '#64748b',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showLoserRatio ? '#f43f5e' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            Loser Ratio %
          </button>
        </div>
      </div>
      <div ref={containerRef} style={{ width: '100%', height: '220px' }} />
    </div>
  );
};
