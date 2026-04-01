import { useEffect, useRef, useImperativeHandle, forwardRef } from 'react';
import { createChart, ColorType, IChartApi, ISeriesApi, HistogramSeries, LineSeries, CandlestickSeries, createSeriesMarkers, ISeriesMarkersPluginApi } from 'lightweight-charts';

interface ChartProps {
  data: {
    timestamps: number[];
    mid_prices: number[];
    ofi: number[];
    ofi_ema: number[];
    macro_sma: number[];
    vwap: number[];
    bb_mid?: number[];
    bb_upper?: number[];
    bb_lower?: number[];
    obi_norm?: number[];
    obi?: number[];
  } | null;
  trades?: any[];
  timeframeMs?: number | null;
  chartType?: 'line' | 'candlestick';
  autoScale?: boolean;
  followLive?: boolean;
  visibleSeries?: {
    ofi: boolean;
    ema: boolean;
    obi: boolean;
    vwap: boolean;
    macroSma: boolean;
    bb: boolean;
  };
}

export interface RealtimeChartRef {
  fitContent: () => void;
}

export const RealtimeChart = forwardRef<RealtimeChartRef, ChartProps>(({ 
  data, 
  trades, 
  timeframeMs = null, 
  chartType = 'line',
  autoScale = true,
  followLive = true,
  visibleSeries = { ofi: true, ema: true, obi: true, vwap: true, macroSma: true, bb: true }
}, ref) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  
  const ofiSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const emaSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const obiSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const priceSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const macroSmaSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  
  const bbMidSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bbUpperSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bbLowerSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  const markersPluginRef = useRef<ISeriesMarkersPluginApi<any> | null>(null);
  const candleMarkersPluginRef = useRef<ISeriesMarkersPluginApi<any> | null>(null);
  const userInteractingRef = useRef<boolean>(false);

  useImperativeHandle(ref, () => ({
    fitContent: () => {
      if (chartRef.current) {
        chartRef.current.timeScale().fitContent();
        // Lightweight charts typically auto-scales price if autoScale is on
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

    const priceSeries = chart.addSeries(LineSeries, {
      color: '#171717',
      lineWidth: 2,
      priceScaleId: 'right',
      title: 'Micro-Price',
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#059669',
      downColor: '#dc2626',
      borderVisible: false,
      wickUpColor: '#059669',
      wickDownColor: '#dc2626',
      priceScaleId: 'right',
      title: 'Micro-Price (OHLC)',
      visible: false,
    });

    const macroSmaSeries = chart.addSeries(LineSeries, {
      color: 'rgba(147, 51, 234, 0.7)',
      lineWidth: 2,
      priceScaleId: 'right',
      title: 'Macro SMA',
    });

    const vwapSeries = chart.addSeries(LineSeries, {
      color: '#db2777',
      lineWidth: 2,
      lineStyle: 2, // Dashed
      priceScaleId: 'right',
      title: 'VWAP',
    });

    // Bollinger Bands
    const bbUpperSeries = chart.addSeries(LineSeries, {
      color: 'rgba(59, 130, 246, 0.8)', // Stronger blue
      lineWidth: 1,
      lineStyle: 1, // Dotted instead of dashed
      priceScaleId: 'right',
      title: 'BB Upper',
    });
    
    const bbMidSeries = chart.addSeries(LineSeries, {
      color: 'rgba(59, 130, 246, 0.6)', 
      lineWidth: 1,
      lineStyle: 2,
      priceScaleId: 'right',
      title: 'BB Mid',
    });
    
    const bbLowerSeries = chart.addSeries(LineSeries, {
      color: 'rgba(59, 130, 246, 0.8)', // Stronger blue
      lineWidth: 1,
      lineStyle: 1, // Dotted instead of dashed
      priceScaleId: 'right',
      title: 'BB Lower',
    });

    // OFI and EMA on Left Scale
    const ofiSeries = chart.addSeries(HistogramSeries, {
      priceScaleId: 'left',
      title: 'OFI',
    });

    const emaSeries = chart.addSeries(LineSeries, {
      color: '#d97706',
      lineWidth: 2,
      priceScaleId: 'left',
      title: 'OFI EMA',
    });

    const obiSeries = chart.addSeries(LineSeries, {
      color: '#ec4899',
      lineWidth: 2,
      priceScaleId: 'left',
      title: 'OBI Z-Score',
    });

    // Create markers plugin on the price series that is primarily used.
    // If using candlesticks, we might need to attach to candlestick, but both share the same time scale.
    const markersPlugin = createSeriesMarkers(priceSeries);
    const candleMarkersPlugin = createSeriesMarkers(candleSeries);

    chartRef.current = chart;
    priceSeriesRef.current = priceSeries;
    candleSeriesRef.current = candleSeries;
    macroSmaSeriesRef.current = macroSmaSeries;
    vwapSeriesRef.current = vwapSeries;
    
    bbMidSeriesRef.current = bbMidSeries;
    bbUpperSeriesRef.current = bbUpperSeries;
    bbLowerSeriesRef.current = bbLowerSeries;
    
    ofiSeriesRef.current = ofiSeries;
    emaSeriesRef.current = emaSeries;
    obiSeriesRef.current = obiSeries;
    markersPluginRef.current = markersPlugin;
    candleMarkersPluginRef.current = candleMarkersPlugin;

    const handleResize = () => {
      chart.applyOptions({ width: chartContainerRef.current?.clientWidth });
    };
    window.addEventListener('resize', handleResize);

    // Track user interaction for followLive
    let interactionTimeout: any = null;
    const logicalRangeChangeHandler = () => {
      userInteractingRef.current = true;
      if (interactionTimeout) clearTimeout(interactionTimeout);
      interactionTimeout = setTimeout(() => {
        userInteractingRef.current = false;
      }, 5000); // Reset after 5 seconds of no panning
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(logicalRangeChangeHandler);

    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(logicalRangeChangeHandler);
      if (interactionTimeout) clearTimeout(interactionTimeout);
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, []);

  // Update visibility of series based on toggles
  useEffect(() => {
    priceSeriesRef.current?.applyOptions({ visible: chartType === 'line' });
    candleSeriesRef.current?.applyOptions({ visible: chartType === 'candlestick' });
    ofiSeriesRef.current?.applyOptions({ visible: visibleSeries.ofi });
    emaSeriesRef.current?.applyOptions({ visible: visibleSeries.ema });
    obiSeriesRef.current?.applyOptions({ visible: visibleSeries.obi });
    vwapSeriesRef.current?.applyOptions({ visible: visibleSeries.vwap });
    macroSmaSeriesRef.current?.applyOptions({ visible: visibleSeries.macroSma });
    bbMidSeriesRef.current?.applyOptions({ visible: visibleSeries.bb });
    bbUpperSeriesRef.current?.applyOptions({ visible: visibleSeries.bb });
    bbLowerSeriesRef.current?.applyOptions({ visible: visibleSeries.bb });
  }, [chartType, visibleSeries]);

  useEffect(() => {
    if (chartRef.current) {
      chartRef.current.priceScale('right').applyOptions({ autoScale });
      chartRef.current.priceScale('left').applyOptions({ autoScale });
    }
  }, [autoScale]);


  const lastProcessedTimeRef = useRef<number>(0);
  
  // Accumulators for the sliding window
  const windowBucketsRef = useRef<Map<number, any>>(new Map());

  const MAX_POINTS = 1000;

  useEffect(() => {
    if (!ofiSeriesRef.current || !data?.timestamps) return;
    
    let added = false;

    // Determine interval for bucketing
    const isLive = !timeframeMs;

    for (let i = 0; i < data.timestamps.length; i++) {
      const rawTimeMs = data.timestamps[i];
      const timeSec = (rawTimeMs / 1000) as any;
      
      // Reset if time went backwards a lot
      if (timeSec < lastProcessedTimeRef.current - 5000) {
        lastProcessedTimeRef.current = 0;
        windowBucketsRef.current.clear();
      }
      
      if (timeSec > lastProcessedTimeRef.current) {
        lastProcessedTimeRef.current = timeSec;
        added = true;

        const bucketMs = isLive ? rawTimeMs : Math.floor(rawTimeMs / timeframeMs!) * timeframeMs!;
        const bucketSec = bucketMs / 1000;
        
        let bucket = windowBucketsRef.current.get(bucketSec);
        if (!bucket) {
          bucket = {
            time: bucketSec,
            open: data.mid_prices[i],
            high: data.mid_prices[i],
            low: data.mid_prices[i],
            close: data.mid_prices[i],
            ofi: data.ofi[i],
            ofi_ema: data.ofi_ema[i],
            obi: data.obi_norm?.[i] ?? data.obi?.[i] ?? 0,
            macro: data.macro_sma[i],
            vwap: data.vwap[i],
            bbMid: data.bb_mid?.[i] ?? 0,
            bbUpper: data.bb_upper?.[i] ?? 0,
            bbLower: data.bb_lower?.[i] ?? 0,
            count: 1
          };
          windowBucketsRef.current.set(bucketSec, bucket);
        } else {
          bucket.high = Math.max(bucket.high, data.mid_prices[i]);
          bucket.low = Math.min(bucket.low, data.mid_prices[i]);
          bucket.close = data.mid_prices[i];
          // For indicators, we just take the latest in the bucket
          bucket.ofi = data.ofi[i];
          bucket.ofi_ema = data.ofi_ema[i];
          bucket.obi = data.obi_norm?.[i] ?? data.obi?.[i] ?? 0;
          bucket.macro = data.macro_sma[i];
          bucket.vwap = data.vwap[i];
          bucket.bbMid = data.bb_mid?.[i] ?? 0;
          bucket.bbUpper = data.bb_upper?.[i] ?? 0;
          bucket.bbLower = data.bb_lower?.[i] ?? 0;
          bucket.count++;
        }
      }
    }
    
    if (added) {
      // Truncate to MAX_POINTS
      let keys = Array.from(windowBucketsRef.current.keys()).sort((a, b) => a - b);
      if (keys.length > MAX_POINTS) {
        const toDelete = keys.length - MAX_POINTS;
        for (let i = 0; i < toDelete; i++) {
          windowBucketsRef.current.delete(keys[i]);
        }
        keys = keys.slice(toDelete);
      }

      const ofiData = [];
      const emaData = [];
      const obiData = [];
      const priceData = [];
      const candleData = [];
      const macroData = [];
      const vwapData = [];
      const bbMidData = [];
      const bbUpperData = [];
      const bbLowerData = [];

      for (const k of keys) {
        const b = windowBucketsRef.current.get(k);
        ofiData.push({ time: b.time, value: b.ofi, color: b.ofi >= 0 ? '#059669' : '#dc2626' });
        emaData.push({ time: b.time, value: b.ofi_ema });
        obiData.push({ time: b.time, value: b.obi });
        priceData.push({ time: b.time, value: b.close });
        candleData.push({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close });
        macroData.push({ time: b.time, value: b.macro });
        vwapData.push({ time: b.time, value: b.vwap });
        bbMidData.push({ time: b.time, value: b.bbMid });
        bbUpperData.push({ time: b.time, value: b.bbUpper });
        bbLowerData.push({ time: b.time, value: b.bbLower });
      }

      ofiSeriesRef.current?.setData(ofiData);
      emaSeriesRef.current?.setData(emaData);
      obiSeriesRef.current?.setData(obiData);
      priceSeriesRef.current?.setData(priceData);
      candleSeriesRef.current?.setData(candleData);
      macroSmaSeriesRef.current?.setData(macroData);
      vwapSeriesRef.current?.setData(vwapData);
      
      if (bbMidData.length > 0 && bbMidData[0].value !== 0) {
        bbMidSeriesRef.current?.setData(bbMidData);
        bbUpperSeriesRef.current?.setData(bbUpperData);
        bbLowerSeriesRef.current?.setData(bbLowerData);
      }

      if (followLive && !userInteractingRef.current && chartRef.current) {
        chartRef.current.timeScale().scrollToRealTime();
      }
    }
  }, [data, timeframeMs, followLive]);

  // Marker updating logic
  useEffect(() => {
    if (!trades || !markersPluginRef.current) return;
    
    const keys = Array.from(windowBucketsRef.current.keys()).sort((a, b) => a - b);
    const minVisibleTime = keys.length > 0 ? keys[0] : 0;
    
    // To support timeframe buckets for trades:
    // We'll bucket trades exactly like price, summing quantities, instead of de-duping by exact ms.
    const isLive = !timeframeMs;
    const tradeBuckets = new Map<number, { buyQty: number, sellQty: number }>();

    for (let i = 0; i < trades.length; i++) {
      const trade = trades[i];
      const rawTimeMs = trade.timestamp;
      const bucketMs = isLive ? rawTimeMs : Math.floor(rawTimeMs / timeframeMs!) * timeframeMs!;
      const bucketSec = bucketMs / 1000;
      
      if (bucketSec >= minVisibleTime) {
        let tb = tradeBuckets.get(bucketSec);
        if (!tb) {
          tb = { buyQty: 0, sellQty: 0 };
          tradeBuckets.set(bucketSec, tb);
        }
        if (trade.side === 'buy') tb.buyQty += trade.qty;
        else tb.sellQty += trade.qty;
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
    
    // Markers need to be attached to the visible series to show up accurately
    // The markers plugin API in our code requires recreating if series changes, 
    // but lightweight-charts typically puts markers on a specific series.
    // For now we set them on the existing markersPlugin which is tied to priceSeries.
    // If candlestick is active, they will still render on the timescale but might align to line series prices.
        if (chartType === 'line') {
      markersPluginRef.current?.setMarkers(markers);
      candleMarkersPluginRef.current?.setMarkers([]);
    } else {
      candleMarkersPluginRef.current?.setMarkers(markers);
      markersPluginRef.current?.setMarkers([]);
    }
  }, [trades, data, timeframeMs, chartType]);

  return <div ref={chartContainerRef} className="w-full h-full" />;
});

RealtimeChart.displayName = 'RealtimeChart';
