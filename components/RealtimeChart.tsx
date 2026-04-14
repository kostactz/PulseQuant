import React, { useEffect, useRef, useImperativeHandle, forwardRef } from 'react';
import { createChart, ColorType, IChartApi, ISeriesApi, LineSeries, CandlestickSeries, createSeriesMarkers } from 'lightweight-charts';

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
  targetAsset?: string;
  featureAsset?: string;
}

export interface RealtimeChartRef {
  fitContent: () => void;
}

export const RealtimeChart = forwardRef<RealtimeChartRef, ChartProps>(({ 
  data, 
  trades, 
  autoScale = true,
  followLive = true,
  targetAsset = 'Target',
  featureAsset = 'Feature'
}, ref) => {
  const metricContainerRef = useRef<HTMLDivElement>(null);
  const priceContainerRef = useRef<HTMLDivElement>(null);
  
  const metricChartRef = useRef<IChartApi | null>(null);
  const priceChartRef = useRef<IChartApi | null>(null);
  
  const zScoreSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const spreadSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const upperBandRef = useRef<ISeriesApi<"Line"> | null>(null);
  const lowerBandRef = useRef<ISeriesApi<"Line"> | null>(null);
  const zeroLineRef = useRef<ISeriesApi<"Line"> | null>(null);

  const targetCandlesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const featureCandlesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  const markersPluginRef = useRef<any | null>(null);
  const userInteractingRef = useRef<boolean>(false);

  useImperativeHandle(ref, () => ({
    fitContent: () => {
      if (metricChartRef.current) metricChartRef.current.timeScale().fitContent();
      if (priceChartRef.current) priceChartRef.current.timeScale().fitContent();
    }
  }));

  useEffect(() => {
    if (!metricContainerRef.current || !priceContainerRef.current) return;

    // --- PRICE CHART ---
    const priceChart = createChart(priceContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#525252' },
      grid: { vertLines: { color: '#e5e5e5' }, horzLines: { color: '#e5e5e5' } },
      timeScale: { timeVisible: true, secondsVisible: true },
      rightPriceScale: { visible: true, borderColor: '#e5e5e5', autoScale: true },
      leftPriceScale: { visible: true, borderColor: '#e5e5e5', autoScale: true },
    });

    const targetCandles = priceChart.addSeries(CandlestickSeries, {
      upColor: '#3b82f6', downColor: '#1d4ed8',
      borderVisible: false, wickUpColor: '#3b82f6', wickDownColor: '#1d4ed8',
      priceScaleId: 'right',
      title: targetAsset,
    });
    
    const featureCandles = priceChart.addSeries(CandlestickSeries, {
      upColor: '#f97316', downColor: '#c2410c',
      borderVisible: false, wickUpColor: '#f97316', wickDownColor: '#c2410c',
      priceScaleId: 'left',
      title: featureAsset,
    });

    // --- METRIC CHART ---
    const metricChart = createChart(metricContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#525252' },
      grid: { vertLines: { color: '#e5e5e5' }, horzLines: { color: '#e5e5e5' } },
      timeScale: { timeVisible: true, secondsVisible: true },
      rightPriceScale: { visible: true, borderColor: '#e5e5e5', autoScale: true },
      leftPriceScale: { visible: true, borderColor: '#e5e5e5', autoScale: true },
    });

    const zScoreSeries = metricChart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 2, priceScaleId: 'right', title: 'Z-Score' });
    const upperBand = metricChart.addSeries(LineSeries, { color: '#ef4444', lineWidth: 1, lineStyle: 2, priceScaleId: 'right', title: '+2 SD' });
    const lowerBand = metricChart.addSeries(LineSeries, { color: '#10b981', lineWidth: 1, lineStyle: 2, priceScaleId: 'right', title: '-2 SD' });
    const zeroLine = metricChart.addSeries(LineSeries, { color: '#9ca3af', lineWidth: 1, lineStyle: 1, priceScaleId: 'right', title: 'Zero' });
    const spreadSeries = metricChart.addSeries(LineSeries, { color: '#8b5cf6', lineWidth: 2, priceScaleId: 'left', title: 'Spread' });

    const markersPlugin = createSeriesMarkers(zScoreSeries);

    priceChartRef.current = priceChart;
    metricChartRef.current = metricChart;
    
    targetCandlesRef.current = targetCandles;
    featureCandlesRef.current = featureCandles;
    zScoreSeriesRef.current = zScoreSeries;
    spreadSeriesRef.current = spreadSeries;
    upperBandRef.current = upperBand;
    lowerBandRef.current = lowerBand;
    zeroLineRef.current = zeroLine;
    markersPluginRef.current = markersPlugin;

    // SYNC LOGIC (NFR3.1)
    const timeRangeHandler1 = (range: any) => {
        if (!range || range.from === null || range.to === null) return;
        try {
            metricChart.timeScale().setVisibleLogicalRange(range);
        } catch (e) {
            // lightweight-charts may throw if the target chart has no data yet
        }
    };
    const timeRangeHandler2 = (range: any) => {
        if (!range || range.from === null || range.to === null) return;
        try {
            priceChart.timeScale().setVisibleLogicalRange(range);
        } catch (e) {
            // lightweight-charts may throw if the target chart has no data yet
        }
    };
    
    priceChart.timeScale().subscribeVisibleLogicalRangeChange(timeRangeHandler1);
    metricChart.timeScale().subscribeVisibleLogicalRangeChange(timeRangeHandler2);

    const handleResize = () => {
      priceChart.applyOptions({ width: priceContainerRef.current?.clientWidth });
      metricChart.applyOptions({ width: metricContainerRef.current?.clientWidth });
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
    metricChart.timeScale().subscribeVisibleLogicalRangeChange(logicalRangeChangeHandler);
    priceChart.timeScale().subscribeVisibleLogicalRangeChange(logicalRangeChangeHandler);

    return () => {
      priceChart.timeScale().unsubscribeVisibleLogicalRangeChange(timeRangeHandler1);
      metricChart.timeScale().unsubscribeVisibleLogicalRangeChange(timeRangeHandler2);
      metricChart.timeScale().unsubscribeVisibleLogicalRangeChange(logicalRangeChangeHandler);
      priceChart.timeScale().unsubscribeVisibleLogicalRangeChange(logicalRangeChangeHandler);
      if (interactionTimeout) clearTimeout(interactionTimeout);
      window.removeEventListener('resize', handleResize);
      priceChart.remove();
      metricChart.remove();
    };
  }, [targetAsset, featureAsset]);

  useEffect(() => {
    if (metricChartRef.current) {
      metricChartRef.current.priceScale('right').applyOptions({ autoScale });
      metricChartRef.current.priceScale('left').applyOptions({ autoScale });
    }
    if (priceChartRef.current) {
      priceChartRef.current.priceScale('right').applyOptions({ autoScale });
      priceChartRef.current.priceScale('left').applyOptions({ autoScale });
    }
  }, [autoScale]);

  const lastProcessedTimeRef = useRef<number>(0);
  const windowBucketsRef = useRef<Map<number, any>>(new Map());
  const ohlcBucketsRef = useRef<Map<number, any>>(new Map());
  const MAX_POINTS = 1000;

  useEffect(() => {
    if (!data?.spread_metrics) return;
    
    const timeSec = Math.floor(Date.now() / 1000);
    const m = data.spread_metrics;
    
    // Handle OHLC intra-second aggregation
    let ohlc = ohlcBucketsRef.current.get(timeSec);
    if (!ohlc) {
      ohlc = {
        time: timeSec,
        tOpen: m.target_price, tHigh: m.target_price, tLow: m.target_price, tClose: m.target_price,
        fOpen: m.feature_price, fHigh: m.feature_price, fLow: m.feature_price, fClose: m.feature_price,
      };
      ohlcBucketsRef.current.set(timeSec, ohlc);
    } else {
      ohlc.tHigh = Math.max(ohlc.tHigh, m.target_price);
      ohlc.tLow = Math.min(ohlc.tLow, m.target_price);
      ohlc.tClose = m.target_price;
      
      ohlc.fHigh = Math.max(ohlc.fHigh, m.feature_price);
      ohlc.fLow = Math.min(ohlc.fLow, m.feature_price);
      ohlc.fClose = m.feature_price;
    }
    
    // Update chart data using .update() to preserve zoom/pan state
    const b = { time: timeSec as any, zScore: m.z_score, spread: m.current_spread };
    
    targetCandlesRef.current?.update({ time: ohlc.time as any, open: ohlc.tOpen, high: ohlc.tHigh, low: ohlc.tLow, close: ohlc.tClose });
    featureCandlesRef.current?.update({ time: ohlc.time as any, open: ohlc.fOpen, high: ohlc.fHigh, low: ohlc.fLow, close: ohlc.fClose });
    zScoreSeriesRef.current?.update({ time: b.time, value: b.zScore });
    spreadSeriesRef.current?.update({ time: b.time, value: b.spread });
    upperBandRef.current?.update({ time: b.time, value: 2.0 });
    lowerBandRef.current?.update({ time: b.time, value: -2.0 });
    zeroLineRef.current?.update({ time: b.time, value: 0.0 });
    
    windowBucketsRef.current.set(timeSec, b);

    if (timeSec > lastProcessedTimeRef.current) {
       lastProcessedTimeRef.current = timeSec;
       
       const keys = Array.from(windowBucketsRef.current.keys()).sort((a, b) => a - b);
       if (keys.length > MAX_POINTS) {
         const toDelete = keys.length - MAX_POINTS;
         for (let i = 0; i < toDelete; i++) {
           windowBucketsRef.current.delete(keys[i]);
           ohlcBucketsRef.current.delete(keys[i]);
         }
       }
    }

    // Lightweight charts naturally auto-scrolls to the newest data if the right edge is visible.
    // We only force scroll to real time if explicitly requested and user is not interacting.
    if (followLive && !userInteractingRef.current) {
      if (metricChartRef.current && priceChartRef.current) {
        // Only scroll if we really need to force it, otherwise let native auto-scroll handle it
        // metricChartRef.current.timeScale().scrollToRealTime();
      }
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

  return (
    <div className="flex flex-col w-full h-full gap-2">
      <div className="flex-1 min-h-0" ref={priceContainerRef} />
      <div className="flex-1 min-h-0" ref={metricContainerRef} />
    </div>
  );
});

RealtimeChart.displayName = 'RealtimeChart';
