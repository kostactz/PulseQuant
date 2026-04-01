declare function importScripts(...urls: string[]): void;
declare const loadPyodide: any;

let pyodide: any;
let pandasLoaded = false;
let initInProgress = false;
let latestMetrics: any = null;

// Performance Tracking
let lastQueueWarnTime = 0;
const STATS_WINDOW_MS = 2000;
let statsBuffer: { ts: number, netLat: number, sysLat: number }[] = [];

const originalFetch = self.fetch.bind(self as any);

// Only cache same-origin engine assets (do NOT cache CDN pyodide files)
self.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  try {
    const request = new Request(input, init);
    const reqUrl = new URL(request.url, (self as any).location?.href);

    if (request.method === 'GET' && reqUrl.origin === (self as any).location.origin && reqUrl.pathname.startsWith('/python/')) {
      const cache = await caches.open('pyodide-cache-v1');
      const cached = await cache.match(request);
      if (cached) {
        console.log(`[Pyodide Cache] Hit: ${request.url}`);
        return cached;
      }
      console.log(`[Pyodide Cache] Miss: ${request.url}`);
      const net = await originalFetch(request);
      if (net && net.ok) {
        await cache.put(request, net.clone());
      }
      return net;
    }
  } catch (err) {
    console.warn('[Pyodide Cache] cache logic failed, falling back to network', err);
  }
  return originalFetch(input as any, init as any);
};

function sleep(ms: number) {
  return new Promise((res) => setTimeout(res, ms));
}

async function initPyodide() {
  if (pandasLoaded || initInProgress) return;
  initInProgress = true;
  const maxAttempts = 3;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      // Load pyodide bootstrap (may throw if network is flaky)
      importScripts('https://cdn.jsdelivr.net/pyodide/v0.25.0/full/pyodide.js');

      pyodide = await loadPyodide({ indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.25.0/full/' });
      await pyodide.loadPackage(['pandas', 'numpy', 'scipy']);

      const response = await fetch('/python/engine.py?t=' + Date.now());
      if (!response.ok) throw new Error('Failed to fetch engine.py: ' + response.status);
      const pythonCode = await response.text();

      await pyodide.runPythonAsync(pythonCode);

      pandasLoaded = true;
      postMessage({ type: 'READY' });
      initInProgress = false;
      return;
    } catch (err) {
      console.error(`[Pyodide] init attempt ${attempt + 1} failed:`, err);
      if (attempt + 1 >= maxAttempts) {
        postMessage({ type: 'ERROR', error: String(err) });
        initInProgress = false;
        pandasLoaded = false;
        return;
      }
      // exponential backoff
      await sleep(Math.min(5000, 500 * Math.pow(2, attempt)));
    }
  }
  initInProgress = false;
}

self.onmessage = async (e: MessageEvent) => {
  try {
    if (e.data.type === 'INIT') {
      await initPyodide();
      return;
    }

    if (!pandasLoaded) {
      postMessage({ type: 'NOT_READY' });
      return;
    }

    if (e.data.type === 'PROCESS') {
      const now = Date.now();
      const enqueuedAt = e.data.enqueuedAt || now;
      const queueTime = now - enqueuedAt;

      if (queueTime > 50 && now - lastQueueWarnTime > 5000) {
        postMessage({ type: 'LOGS', data: [{ level: 'WARN', message: `Worker queue delay: ${queueTime}ms`, data: null }] });
        lastQueueWarnTime = now;
      }

      let processEvents: any = null;
      let pyPayload: any = null;
      let results: any = null;
      try {
        processEvents = pyodide.globals.get('process_events');
        pyPayload = pyodide.toPy(e.data.payload);
        results = processEvents(pyPayload);
        
        let jsResults: any = results;
        if (results && typeof results.toJs === 'function') jsResults = results.toJs({ dict_converter: Object.fromEntries });

        const finishTime = Date.now();
        const sysLat = finishTime - enqueuedAt;
        let netLat = 0;
        if (e.data.payload && e.data.payload.length > 0) {
          const firstPayload = e.data.payload[0];
          const tickTs = firstPayload.data?.timestamp || firstPayload.timestamp;
          if (tickTs) {
            netLat = enqueuedAt - tickTs;
            if (netLat < 0) netLat = 0;
          }
        }

        statsBuffer.push({ ts: finishTime, netLat, sysLat });
        const cutoff = finishTime - STATS_WINDOW_MS;
        statsBuffer = statsBuffer.filter(s => s.ts >= cutoff);
        
        const count = statsBuffer.length;
        const mps = count / (STATS_WINDOW_MS / 1000);
        const avgNetLat = count > 0 ? statsBuffer.reduce((acc, s) => acc + s.netLat, 0) / count : 0;
        const avgSysLat = count > 0 ? statsBuffer.reduce((acc, s) => acc + s.sysLat, 0) / count : 0;

        // Since processEvents now only returns logs and intents, we don't attach stats here.
        // We'll attach system_stats to the latestMetrics when we fetch them in GET_UI_DELTA.
        const currentStats = {
          mps: mps.toFixed(1),
          netLat: avgNetLat.toFixed(1),
          sysLat: avgSysLat.toFixed(1)
        };
        
        // Temporarily store the latest stats to be retrieved by GET_UI_DELTA
        (self as any).latestStats = currentStats;

        if (jsResults.logs && jsResults.logs.length > 0) {
          postMessage({ type: 'LOGS', data: jsResults.logs });
        }

        if (jsResults.intents && jsResults.intents.length > 0) {
          postMessage({ type: 'INTENTS', data: jsResults.intents });
        }
      } catch (err) {
        console.error('[Worker] Process error:', err);
        postMessage({ type: 'ERROR', error: String(err) });
        if (String(err).includes('Pyodide already fatally failed')) {
          pandasLoaded = false;
          // attempt background re-init
          initPyodide();
        }
      } finally {
        if (results && typeof results.destroy === 'function') results.destroy();
        if (pyPayload && typeof pyPayload.destroy === 'function') pyPayload.destroy();
        if (processEvents && typeof processEvents.destroy === 'function') processEvents.destroy();
      }
        } else if (e.data.type === 'GET_UI_DELTA') {
      let results: any = null;
      let metricsResults: any = null;
      try {
        results = pyodide.runPython(`get_ui_delta()`);
        let jsResults: any = results;
        if (results && typeof results.toJs === 'function') jsResults = results.toJs({ dict_converter: Object.fromEntries });
        
        postMessage({ type: 'UI_DELTA', data: jsResults });
        
        // Also fetch the heavy metrics state less frequently (e.g. at the UI delta interval)
        metricsResults = pyodide.runPython(`get_metrics()`);
        let jsMetrics: any = metricsResults;
        if (metricsResults && typeof metricsResults.toJs === 'function') jsMetrics = metricsResults.toJs({ dict_converter: Object.fromEntries });
        
        if ((self as any).latestStats) {
          jsMetrics.system_stats = (self as any).latestStats;
        }

        latestMetrics = jsMetrics;
        postMessage({ type: 'RESULTS', data: latestMetrics });
      } catch (err) {
        console.error('[Worker] Get UI delta / metrics error:', err);
        postMessage({ type: 'ERROR', error: String(err) });
      } finally {
        if (results && typeof results.destroy === 'function') results.destroy();
        if (metricsResults && typeof metricsResults.destroy === 'function') metricsResults.destroy();
      }
} else if (e.data.type === 'CLEAR') {
      try {
        pyodide.runPython('clear_data()');
        latestMetrics = null;
        postMessage({ type: 'CLEARED' });
      } catch (err) {
        console.error('[Worker] Clear error:', err);
        postMessage({ type: 'ERROR', error: String(err) });
        if (String(err).includes('Pyodide already fatally failed')) {
          pandasLoaded = false;
          initPyodide();
        }
      }
    } else if (e.data.type === 'TRADE') {
      try {
        pyodide.runPython(`execute_trade('${e.data.side}', ${e.data.bps})`);
        postMessage({ type: 'TRADE_EXECUTED' });
      } catch (err) {
        console.error('[Worker] Trade error:', err);
        postMessage({ type: 'ERROR', error: String(err) });
        if (String(err).includes('Pyodide already fatally failed')) {
          pandasLoaded = false;
          initPyodide();
        }
      }
    } else if (e.data.type === 'SET_AUTO_TRADE') {
      try {
        pyodide.runPython(`set_auto_trade(${e.data.enabled ? 'True' : 'False'})`);
      } catch (err) {
        console.error('[Worker] Auto trade error:', err);
        postMessage({ type: 'ERROR', error: String(err) });
      }
    } else if (e.data.type === 'UPDATE_STRATEGY') {
      try {
        pyodide.runPython(`update_strategy('${e.data.style}', '${e.data.speed}')`);
      } catch (err) {
        console.error('[Worker] Update strategy error:', err);
        postMessage({ type: 'ERROR', error: String(err) });
      }
    } else if (e.data.type === 'SET_TRADE_SIZE') {
      try {
        pyodide.runPython(`set_trade_size(${e.data.bps})`);
      } catch (err) {
        console.error('[Worker] Set trade size error:', err);
        postMessage({ type: 'ERROR', error: String(err) });
      }
    }
  } catch (outerErr) {
    console.error('[Worker] Unexpected message handler error:', outerErr);
    postMessage({ type: 'ERROR', error: String(outerErr) });
  }
};
