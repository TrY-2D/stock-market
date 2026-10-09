import React, { useEffect, useRef, useState } from 'react';
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
import type { LinePoint } from '../types';

interface ExpectedReturnChartProps {
  expectedReturnSeries: LinePoint[];
  pqrSeries?: LinePoint[];
  pqtSeries?: LinePoint[];
  prSeries?: LinePoint[];
  ptSeries?: LinePoint[];
  divYieldSeries?: LinePoint[];
  thesesCountSeries?: LinePoint[];
}

export const ExpectedReturnChart: React.FC<ExpectedReturnChartProps> = ({
  expectedReturnSeries,
  pqrSeries = [],
  pqtSeries = [],
  prSeries = [],
  ptSeries = [],
  divYieldSeries = [],
  thesesCountSeries = [],
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  // Line Series References
  const expLineRef = useRef<ISeriesApi<'Line'> | null>(null);
  const pqrLineRef = useRef<ISeriesApi<'Line'> | null>(null);
  const pqtLineRef = useRef<ISeriesApi<'Line'> | null>(null);
  const prLineRef = useRef<ISeriesApi<'Line'> | null>(null);
  const ptLineRef = useRef<ISeriesApi<'Line'> | null>(null);
  const divLineRef = useRef<ISeriesApi<'Line'> | null>(null);
  const thesesLineRef = useRef<ISeriesApi<'Line'> | null>(null);

  // Layer Toggles
  const [showTotalE, setShowTotalE] = useState<boolean>(true);
  const [showPqr, setShowPqr] = useState<boolean>(true);
  const [showPqt, setShowPqt] = useState<boolean>(true);
  const [showPr, setShowPr] = useState<boolean>(true);
  const [showPt, setShowPt] = useState<boolean>(true);
  const [showDiv, setShowDiv] = useState<boolean>(true);
  const [showTheses, setShowTheses] = useState<boolean>(true);

  // 1. Initialize Chart
  useEffect(() => {
    if (!containerRef.current) return;

    const container = containerRef.current;
    const chart = createChart(container, {
      width: container.clientWidth,
      height: 280,
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

    // Total Expected Return E (Thick purple)
    expLineRef.current = chart.addSeries(LineSeries, {
      color: '#c084fc',
      lineWidth: 2,
      priceScaleId: 'right',
      priceLineVisible: false,
      title: '',
    });

    // 1. Pqr: Lợi nhuận dự phóng vĩ mô SMA (42%)
    pqrLineRef.current = chart.addSeries(LineSeries, {
      color: 'rgba(56, 189, 248, 0.75)',
      lineWidth: 1,
      priceScaleId: 'right',
      priceLineVisible: false,
      title: '',
    });

    // 2. Pqt: Lợi nhuận dự phóng vĩ mô LRC (18%)
    pqtLineRef.current = chart.addSeries(LineSeries, {
      color: 'rgba(52, 211, 153, 0.75)',
      lineWidth: 1,
      priceScaleId: 'right',
      priceLineVisible: false,
      title: '',
    });

    // 3. Pr: Lợi nhuận dự phóng cổ phiếu SMA (28%)
    prLineRef.current = chart.addSeries(LineSeries, {
      color: 'rgba(251, 191, 36, 0.75)',
      lineWidth: 1,
      priceScaleId: 'right',
      priceLineVisible: false,
      title: '',
    });

    // 4. Pt: Lợi nhuận dự phóng cổ phiếu LRC (12%)
    ptLineRef.current = chart.addSeries(LineSeries, {
      color: 'rgba(251, 146, 60, 0.75)',
      lineWidth: 1,
      priceScaleId: 'right',
      priceLineVisible: false,
      title: '',
    });

    // 5. D: Lợi suất cổ tức (Dividend Yield)
    divLineRef.current = chart.addSeries(LineSeries, {
      color: 'rgba(45, 212, 191, 0.75)',
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      priceScaleId: 'right',
      priceLineVisible: false,
      title: '',
    });

    // Theses count on left scale
    thesesLineRef.current = chart.addSeries(LineSeries, {
      color: 'rgba(148, 163, 184, 0.60)',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      priceScaleId: 'left',
      priceLineVisible: false,
      title: '',
    });

    // Register with ChartSyncManager
    const dataMap = new Map<number, number>();
    expectedReturnSeries.forEach((p) => dataMap.set(p.time, p.value));
    chartSync.register({
      id: 'expected_return',
      chart,
      primarySeries: expLineRef.current,
      dataMap,
    });

    const onRangeChange = (range: LogicalRange | null) => {
      chartSync.syncLogicalRange('expected_return', range);
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange);

    const onCrosshairMove = (param: MouseEventParams<Time>) => {
      chartSync.syncCrosshair('expected_return', param);
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
      chartSync.unregister('expected_return');
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, []);

  // Update visibility dynamically
  useEffect(() => {
    expLineRef.current?.applyOptions({ visible: showTotalE });
  }, [showTotalE]);
  useEffect(() => {
    pqrLineRef.current?.applyOptions({ visible: showPqr });
  }, [showPqr]);
  useEffect(() => {
    pqtLineRef.current?.applyOptions({ visible: showPqt });
  }, [showPqt]);
  useEffect(() => {
    prLineRef.current?.applyOptions({ visible: showPr });
  }, [showPr]);
  useEffect(() => {
    ptLineRef.current?.applyOptions({ visible: showPt });
  }, [showPt]);
  useEffect(() => {
    divLineRef.current?.applyOptions({ visible: showDiv });
  }, [showDiv]);
  useEffect(() => {
    thesesLineRef.current?.applyOptions({ visible: showTheses });
  }, [showTheses]);

  // Update Series Data
  useEffect(() => {
    const filterValid = (arr: LinePoint[]) =>
      (arr || [])
        .filter((p) => Number.isFinite(p.value) && Math.abs(p.value) < 1000)
        .map((p) => ({ time: p.time as unknown as Time, value: p.value }));

    if (expLineRef.current && expectedReturnSeries) {
      expLineRef.current.setData(filterValid(expectedReturnSeries));
      if (expectedReturnSeries.length > 0) {
        chartRef.current?.timeScale().fitContent();
      }
    }

    if (pqrLineRef.current && pqrSeries) {
      pqrLineRef.current.setData(filterValid(pqrSeries));
    }
    if (pqtLineRef.current && pqtSeries) {
      pqtLineRef.current.setData(filterValid(pqtSeries));
    }
    if (prLineRef.current && prSeries) {
      prLineRef.current.setData(filterValid(prSeries));
    }
    if (ptLineRef.current && ptSeries) {
      ptLineRef.current.setData(filterValid(ptSeries));
    }
    if (divLineRef.current && divYieldSeries) {
      divLineRef.current.setData(filterValid(divYieldSeries));
    }
    if (thesesLineRef.current && thesesCountSeries) {
      thesesLineRef.current.setData(
        (thesesCountSeries || [])
          .filter((p) => Number.isFinite(p.value))
          .map((p) => ({ time: p.time as unknown as Time, value: p.value }))
      );
    }

    const dataMap = new Map<number, number>();
    expectedReturnSeries.forEach((p) => dataMap.set(p.time, p.value));
    chartSync.updateDataMap('expected_return', dataMap);
  }, [expectedReturnSeries, pqrSeries, pqtSeries, prSeries, ptSeries, divYieldSeries, thesesCountSeries]);

  const validE = (expectedReturnSeries || []).filter((p) => Number.isFinite(p.value) && Math.abs(p.value) < 1000);
  const lastE = validE.length > 0 ? validE[validE.length - 1] : undefined;
  const currentE = lastE ? lastE.value : 0;
  const lastTh = thesesCountSeries && thesesCountSeries.length > 0 ? thesesCountSeries[thesesCountSeries.length - 1] : undefined;
  const currentTheses = lastTh ? lastTh.value : 0;

  return (
    <div style={{ position: 'relative', width: '100%', background: '#0f172a', borderRadius: '8px', border: '1px solid #1e293b', overflow: 'hidden' }}>
      {/* Header Info & Formula Bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 16px', background: '#1e293b', borderBottom: '1px solid #334155', flexWrap: 'wrap', gap: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          <span style={{ fontWeight: 700, fontSize: '13px', color: '#f8fafc' }}>🎯 Mô Hình Dự Phóng Lợi Nhuận (E)</span>
          <span style={{ fontSize: '12px', color: currentE >= 0 ? '#10b981' : '#f43f5e', fontWeight: 700 }}>
            E = {currentE > 0 ? '+' : ''}{currentE.toFixed(2)}%/năm
          </span>
          <span style={{ fontSize: '11px', background: currentTheses >= 3 ? 'rgba(16, 185, 129, 0.15)' : 'rgba(100, 116, 139, 0.2)', color: currentTheses >= 3 ? '#10b981' : '#94a3b8', padding: '2px 8px', borderRadius: '4px', fontWeight: 600 }}>
            {currentTheses}/5 Luận điểm {currentTheses >= 3 ? '(Đủ điều kiện)' : ''}
          </span>
          <span style={{ fontSize: '11px', color: '#64748b' }}>
            E = 0.42·Pqr + 0.18·Pqt + 0.28·Pr + 0.12·Pt + D
          </span>
        </div>

        {/* 5 Component Layer Toggles */}
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
          <button
            onClick={() => setShowTotalE(!showTotalE)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              background: showTotalE ? 'rgba(192, 132, 252, 0.15)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showTotalE ? '#c084fc' : '#334155'}`,
              padding: '2px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showTotalE ? '#c084fc' : '#64748b',
              fontSize: '11px',
              fontWeight: 600,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showTotalE ? '#c084fc' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            E Tổng
          </button>

          <button
            onClick={() => setShowPqr(!showPqr)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              background: showPqr ? 'rgba(56, 189, 248, 0.15)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showPqr ? '#38bdf8' : '#334155'}`,
              padding: '2px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showPqr ? '#38bdf8' : '#64748b',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showPqr ? '#38bdf8' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            Pqr (42%)
          </button>

          <button
            onClick={() => setShowPqt(!showPqt)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              background: showPqt ? 'rgba(52, 211, 153, 0.15)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showPqt ? '#34d399' : '#334155'}`,
              padding: '2px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showPqt ? '#34d399' : '#64748b',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showPqt ? '#34d399' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            Pqt (18%)
          </button>

          <button
            onClick={() => setShowPr(!showPr)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              background: showPr ? 'rgba(251, 191, 36, 0.15)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showPr ? '#fbbf24' : '#334155'}`,
              padding: '2px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showPr ? '#fbbf24' : '#64748b',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showPr ? '#fbbf24' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            Pr (28%)
          </button>

          <button
            onClick={() => setShowPt(!showPt)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              background: showPt ? 'rgba(251, 146, 60, 0.15)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showPt ? '#fb923c' : '#334155'}`,
              padding: '2px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showPt ? '#fb923c' : '#64748b',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showPt ? '#fb923c' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            Pt (12%)
          </button>

          <button
            onClick={() => setShowDiv(!showDiv)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              background: showDiv ? 'rgba(45, 212, 191, 0.15)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showDiv ? '#2dd4bf' : '#334155'}`,
              padding: '2px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showDiv ? '#2dd4bf' : '#64748b',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showDiv ? '#2dd4bf' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            Cổ tức D
          </button>

          <button
            onClick={() => setShowTheses(!showTheses)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              background: showTheses ? 'rgba(148, 163, 184, 0.15)' : 'rgba(30, 41, 59, 0.6)',
              border: `1px solid ${showTheses ? '#94a3b8' : '#334155'}`,
              padding: '2px 8px',
              borderRadius: '4px',
              cursor: 'pointer',
              color: showTheses ? '#cbd5e1' : '#64748b',
              fontSize: '11px',
              fontWeight: 500,
            }}
          >
            <span style={{ width: '8px', height: '8px', background: showTheses ? '#94a3b8' : '#475569', borderRadius: '2px', display: 'inline-block' }} />
            Luận điểm (/5)
          </button>
        </div>
      </div>

      <div ref={containerRef} style={{ width: '100%', height: '280px' }} />
    </div>
  );
};
