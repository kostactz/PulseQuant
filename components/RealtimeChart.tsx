import { useEffect, useRef, useImperativeHandle, forwardRef } from 'react';
import { createChart, ColorType, IChartApi, ISeriesApi, LineSeries, HistogramSeries, createSeriesMarkers } from 'lightweight-charts';

interface ChartProps {
  data: {
    spread_metrics?: {
      current_spread: number;
      z_score: number;
      beta: number;
      target_price: number;
      feature_price: number;
    } | null;
  } | null;
  trades?: any[];
  autoScale?: boolean;
  followLive?: boolean;
}

export interface RealtimeChartRef {
  fitContent: () => void;
}

export const RealtimeChart = forwardRef<RealtimeChartRef, ChartProps>(({ 
  data, 
  trades, 
  autoScale = true,
  followLive = true
}, ref) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  
  const zScoreSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const spreadSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const upperBandRef = useRef<ISeriesApi<"Line"> | null>(null);
  const lowerBandRef = useRef<ISeriesApi<"Line"> | null>(null);
  const zeroLineRef = useRef<ISeriesApi<"Line"> | null>(null);

  const markersPluginRef = useRef<any | null>(null);
  const userInteractingRef = useRef<boolean>(false);

  useImperativeHandle(ref, () => ({
    fitContent: () => {
      if (chartRef.current) {
        chartRef.current.timeScale().fitContent();
      }
    }
  }));

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#525252',
      },
      grid: {
        vertLines: { color: '#e5e5e5' },
        horzLines: { color: '#e5e5e5' },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: true,
      },
      rightPriceScale: {
        visible: true,
        borderColor: '#e5e5e5',
        autoScale: true,
      },
      leftPriceScale: {
        visible: true,
        borderColor: '#e5e5e5',
        autoScale: true,
      },
    });

    const zScoreSeries = chart.addSeries(LineSeries, {
      color: '#3b82f6', // Blue
      lineWidth: 2,
      priceScaleId: 'right',
      title: 'Z-Score',
    });

    const upperBand = chart.addSeries(LineSeries, {
      color: '#ef4444', // Red
      lineWidth: 1,
      lineStyle: 2, // Dashed
      priceScaleId: 'right',
      title: '+2 SD',
    });

    const lowerBand = chart.addSeries(LineSeries, {
      color: '#10b981', // Green
      lineWidth: 1,
      lineStyle: 2, // Dashed
      priceScaleId: 'right',
      title: '-2 SD',
    });

    const zeroLine = chart.addSeries(LineSeries, {
      color: '#9ca3af', // Gray
      lineWidth: 1,
      lineStyle: 1, // Dotted
      priceScaleId: 'right',
      title: 'Zero',
    });

    const spreadSeries = chart.addSeries(LineSeries, {
      color: '#8b5cf6', // Purple
      lineWidth: 2,
      priceScaleId: 'left',
      title: 'Spread',
    });

    const markersPlugin = createSeriesMarkers(zScoreSeries);

    chartRef.current = chart;
    zScoreSeriesRef.current = zScoreSeries;
    spreadSeriesRef.current = spreadSeries;
    upperBandRef.current = upperBand;
    lowerBandRef.current = lowerBand;
    zeroLineRef.current = zeroLine;
    markersPluginRef.current = markersPlugin;

    const handleResize = () => {
      chart.applyOptions({ width: chartContainerRef.current?.clientWidth });
    };
    window.addEventListener('resize', handleResize);

    let interactionTimeout: any = null;
    const logicalRangeChangeHandler = () => {
      userInteractingRef.current = true;
      if (interactionTimeout) clearTimeout(interactionTimeout);
      interactionTimeout = setTimeout(() => {
        userInteractingRef.current = false;
      }, 5000);
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(logicalRangeChangeHandler);

    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(logicalRangeChangeHandler);
      if (interactionTimeout) clearTimeout(interactionTimeout);
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, []);

  useEffect(() => {
    if (chartRef.current) {
      chartRef.current.priceScale('right').applyOptions({ autoScale });
      chartRef.current.priceScale('left').applyOptions({ autoScale });
    }
  }, [autoScale]);

  const lastProcessedTimeRef = useRef<number>(0);
  const windowBucketsRef = useRef<Map<number, any>>(new Map());
  const MAX_POINTS = 1000;

  useEffect(() => {
    if (!data?.spread_metrics) return;
    
    const timeSec = Math.floor(Date.now() / 1000);
    if (timeSec < lastProcessedTimeRef.current) return;
    
    lastProcessedTimeRef.current = timeSec;
    
    windowBucketsRef.current.set(timeSec, {
      time: timeSec,
      zScore: data.spread_metrics.z_score,
      spread: data.spread_metrics.current_spread
    });
    
    let keys = Array.from(windowBucketsRef.current.keys()).sort((a, b) => a - b);
    if (keys.length > MAX_POINTS) {
      const toDelete = keys.length - MAX_POINTS;
      for (let i = 0; i < toDelete; i++) {
        windowBucketsRef.current.delete(keys[i]);
      }
      keys = keys.slice(toDelete);
    }

    const zData = [];
    const spreadData = [];
    const uData = [];
    const lData = [];
    const zLineData = [];

    for (const k of keys) {
      const b = windowBucketsRef.current.get(k);
      zData.push({ time: b.time, value: b.zScore });
      spreadData.push({ time: b.time, value: b.spread });
      uData.push({ time: b.time, value: 2.0 });
      lData.push({ time: b.time, value: -2.0 });
      zLineData.push({ time: b.time, value: 0.0 });
    }

    zScoreSeriesRef.current?.setData(zData as any);
    spreadSeriesRef.current?.setData(spreadData as any);
    upperBandRef.current?.setData(uData as any);
    lowerBandRef.current?.setData(lData as any);
    zeroLineRef.current?.setData(zLineData as any);

    if (followLive && !userInteractingRef.current && chartRef.current) {
      chartRef.current.timeScale().scrollToRealTime();
    }
  }, [data, followLive]);

  // Marker logic
  useEffect(() => {
    if (!trades || !markersPluginRef.current) return;
    
    const keys = Array.from(windowBucketsRef.current.keys()).sort((a, b) => a - b);
    const minVisibleTime = keys.length > 0 ? keys[0] : 0;
    
    const tradeBuckets = new Map<number, { buyQty: number, sellQty: number }>();

    for (let i = 0; i < trades.length; i++) {
      const trade = trades[i];
      const rawTimeMs = trade.timestamp || Date.now();
      const bucketSec = Math.floor(rawTimeMs / 1000);
      
      if (bucketSec >= minVisibleTime) {
        let tb = tradeBuckets.get(bucketSec);
        if (!tb) {
          tb = { buyQty: 0, sellQty: 0 };
          tradeBuckets.set(bucketSec, tb);
        }
        if (trade.side === 'buy') tb.buyQty += trade.qty || 1;
        else tb.sellQty += trade.qty || 1;
      }
    }
    
    const markers: any[] = [];
    for (const [time, tb] of tradeBuckets.entries()) {
      if (tb.buyQty > 0) {
        markers.push({
          time: time as any,
          position: 'belowBar',
          color: '#059669',
          shape: 'arrowUp',
          text: `Buy ${tb.buyQty.toFixed(4)}`
        });
      }
      if (tb.sellQty > 0) {
        markers.push({
          time: time as any,
          position: 'aboveBar',
          color: '#dc2626',
          shape: 'arrowDown',
          text: `Sell ${tb.sellQty.toFixed(4)}`
        });
      }
    }
    
    markers.sort((a, b) => a.time - b.time);
    markersPluginRef.current?.setMarkers(markers);
  }, [trades]);

  return <div ref={chartContainerRef} className="w-full h-full" />;
});

RealtimeChart.displayName = 'RealtimeChart';
