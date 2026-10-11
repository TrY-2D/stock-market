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

interface PositionChartProps {
  positionShares?: LinePoint[];
  positionLevel?: LinePoint[];
  v0?: number;
  lotSize?: number;
}

export const PositionChart: React.FC<PositionChartProps> = ({
  positionShares = [],
  positionLevel = [],
  v0 = 100,
  lotSize = 100,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const sharesAreaRef = useRef<ISeriesApi<'Area'> | null>(null);
  const levelLineRef = useRef<ISeriesApi<'Line'> | null>(null);

  const [showShares, setShowShares] = useState<boolean>(true);
  const [showLevel, setShowLevel] = useState<boolean>(true);

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
      leftPriceScale: {
        visible: true,
        borderColor: '#334155',
        autoScale: true,
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

    // Shares Area Series (Right Scale)
    sharesAreaRef.current = chart.addSeries(AreaSeries, {
      topColor: 'rgba(56, 189, 248, 0.35)',
      bottomColor: 'rgba(56, 189, 248, 0.05)',
      lineColor: '#38bdf8',
      lineWidth: 2,
      priceScaleId: 'right',
      title: 'Khối Lượng CP',
    });

    // Level Line Series (Left Scale, values 0-6)
    levelLineRef.current = chart.addSeries(LineSeries, {
      color: '#c084fc',
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      priceScaleId: 'left',
      title: 'Cấp Lệnh (1-6)',
    });

    // Register with ChartSyncManager using shares as primary
    const dataMap = new Map<number, number>();
    positionShares.forEach((p) => dataMap.set(p.time, p.value));
    chartSync.register({
      id: 'position',
      chart,
      primarySeries: sharesAreaRef.current,
      dataMap,
    });

    const onRangeChange = (range: LogicalRange | null) => {
      chartSync.syncLogicalRange('position', range);
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange);

    const onCrosshairMove = (param: MouseEventParams<Time>) => {
      chartSync.syncCrosshair('position', param);
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
      chartSync.unregister('position');
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    sharesAreaRef.current?.applyOptions({ visible: showShares });
  }, [showShares]);

  useEffect(() => {
    levelLineRef.current?.applyOptions({ visible: showLevel });
  }, [showLevel]);

  useEffect(() => {
    if (sharesAreaRef.current && positionShares.length > 0) {
      sharesAreaRef.current.setData(
        positionShares
          .filter((p) => Number.isFinite(p.value))
          .map((p) => ({ time: p.time as unknown as Time, value: p.value }))
      );
    }
    if (levelLineRef.current && positionLevel.length > 0) {
      levelLineRef.current.setData(
        positionLevel
          .filter((p) => Number.isFinite(p.value))
          .map((p) => ({ time: p.time as unknown as Time, value: p.value }))
      );
    }

    const dataMap = new Map<number, number>();
    positionShares.forEach((p) => dataMap.set(p.time, p.value));
    chartSync.updateDataMap('position', dataMap);
  }, [positionShares, positionLevel]);

  const lastShares = positionShares && positionShares.length > 0 ? positionShares[positionShares.length - 1].value : 0;
  const lastLevel = positionLevel && positionLevel.length > 0 ? positionLevel[positionLevel.length - 1].value : 0;
  const maxCapacity = 21 * (v0 || 100);
  const capPct = maxCapacity > 0 ? (lastShares / maxCapacity) * 100.0 : 0.0;

  return (
    <div style={{ background: '#0f172a', borderRadius: '8px', border: '1px solid #1e293b', overflow: 'hidden' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 16px', background: '#1e293b', borderBottom: '1px solid #334155', flexWrap: 'wrap', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontWeight: 700, fontSize: '13px', color: '#f8fafc' }}>📊 Quy Mô Vị Thế & Cấp Fibonacci</span>
          <span style={{ fontSize: '12px', color: '#38bdf8', fontWeight: 600 }}>Nắm giữ: {lastShares.toLocaleString('vi-VN')} CP</span>
          <span style={{ fontSize: '12px', color: '#c084fc', fontWeight: 600 }}>Cấp hiện tại: {lastLevel > 0 ? `L${lastLevel}` : 'Không vị thế'}</span>
          <span style={{ fontSize: '11px', background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', padding: '2px 8px', borderRadius: '4px', fontWeight: 600 }}>
            Tỷ lệ lấp đầy: {capPct.toFixed(1)}% / Max {maxCapacity.toLocaleString('vi-VN')} CP (21·V0)
          </span>
        </div>

        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          <button
            onClick={() => setShowShares(!showShares)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              background: showShares ? 'rgba(56, 189, 248, 0.15)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showShares ? '#38bdf8' : '#334155'}`,
              padding: '2px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showShares ? '#38bdf8' : '#64748b',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showShares ? '#38bdf8' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            Khối Lượng CP
          </button>

          <button
            onClick={() => setShowLevel(!showLevel)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              background: showLevel ? 'rgba(192, 132, 252, 0.15)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showLevel ? '#c084fc' : '#334155'}`,
              padding: '2px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showLevel ? '#c084fc' : '#64748b',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showLevel ? '#c084fc' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            Cấp Lệnh (1-6)
          </button>
        </div>
      </div>
      <div ref={containerRef} style={{ width: '100%', height: '220px' }} />
    </div>
  );
};
