import { describe, it, expect, beforeAll, afterAll, beforeEach, afterEach, vi } from 'vitest';

let validateSide: any;
let validateStyle: any;
let validateSpeed: any;
let validateBps: any;

// Capture globalThis.fetch before the worker module patches it at import time,
// so it can be restored after all tests in this file complete.
let _originalFetch: typeof globalThis.fetch;
beforeAll(() => {
  _originalFetch = globalThis.fetch;
});
afterAll(() => {
  globalThis.fetch = _originalFetch;
});

describe('pythonEngine.worker validation helpers', () => {
  beforeAll(async () => {
    (globalThis as any).self = globalThis;
    const workerModule = await import('../workers/pythonEngine.worker');
    validateSide = workerModule.validateSide;
    validateStyle = workerModule.validateStyle;
    validateSpeed = workerModule.validateSpeed;
    validateBps = workerModule.validateBps;
  });

  afterAll(() => {
    delete (globalThis as any).self;
  });

  it('validates side', () => {
    expect(validateSide('buy')).toBe('buy');
    expect(validateSide('SELL')).toBe('sell');
  });

  it('rejects invalid side', () => {
    expect(() => validateSide('foo')).toThrow(/Invalid side/);
    expect(() => validateSide(123)).toThrow(/Invalid side/);
  });

  it('validates style', () => {
    expect(validateStyle('conservative')).toBe('conservative');
    expect(validateStyle('Moderate')).toBe('moderate');
  });

  it('rejects invalid style', () => {
    expect(() => validateStyle('extreme')).toThrow(/Invalid style/);
    expect(() => validateStyle(null)).toThrow(/Invalid style/);
    expect(() => validateStyle("'); import os; os.system('malicious_command'); #")).toThrow(/Invalid style/);
  });

  it('validates speed', () => {
    expect(validateSpeed('fast')).toBe('fast');
    expect(validateSpeed('NORMAL')).toBe('normal');
  });

  it('rejects invalid speed', () => {
    expect(() => validateSpeed('warp')).toThrow(/Invalid speed/);
    expect(() => validateSpeed({})).toThrow(/Invalid speed/);
  });

  it('validates bps values', () => {
    expect(validateBps(100)).toBe(100);
    expect(validateBps('2')).toBe(2);
    expect(validateBps(0)).toBe(0);
    expect(validateBps(10000)).toBe(10000);
  });

  it('rejects out-of-range bps', () => {
    expect(() => validateBps(-1)).toThrow(/Invalid bps/);
    expect(() => validateBps(10001)).toThrow(/Invalid bps/);
    expect(() => validateBps('foo')).toThrow(/Invalid bps/);
  });

  it('validates boolean values', async () => {
    const workerModule = await import('../workers/pythonEngine.worker');
    expect(workerModule.validateBoolean(true)).toBe(true);
    expect(workerModule.validateBoolean(false)).toBe(false);
    expect(() => workerModule.validateBoolean('true')).toThrow(/Invalid boolean/);
  });
});

describe('pythonEngine.worker message flow integration', () => {
  beforeEach(() => {
    (globalThis as any).self = globalThis;
  });

  afterEach(() => {
    delete (globalThis as any).postMessage;
    delete (globalThis as any).self;
  });

  it('processes TRADE and SET_AUTO_TRADE messages', async () => {
    (globalThis as any).self = globalThis;
    const postMessageMock = vi.fn();
    (globalThis as any).postMessage = postMessageMock;

    const executeTradeMock: any = vi.fn();
    executeTradeMock.destroy = vi.fn();
    const setAutoTradeMock: any = vi.fn();
    setAutoTradeMock.destroy = vi.fn();

    const workerModule = await import('../workers/pythonEngine.worker');
    workerModule._testSetPandasLoaded(true);
    workerModule._testSetPyodide({
      globals: {
        get: (name: string) => {
          if (name === 'execute_trade') return executeTradeMock;
          if (name === 'set_auto_trade') return setAutoTradeMock;
          throw new Error('Unmocked function: ' + name);
        }
      }
    });

    await workerModule._testSendMessage({ type: 'TRADE', side: 'buy', bps: 50 });
    await workerModule._testSendMessage({ type: 'SET_AUTO_TRADE', enabled: true });

    expect(executeTradeMock).toHaveBeenCalledWith('buy', 50);
    expect(setAutoTradeMock).toHaveBeenCalledWith(true);

    expect(postMessageMock).toHaveBeenCalledWith({ type: 'TRADE_EXECUTED' });
    expect(postMessageMock).toHaveBeenCalledWith({ type: 'AUTO_TRADE_UPDATED', enabled: true });
  });

  it('returns ERROR for invalid TRADE/SET_AUTO_TRADE payloads', async () => {
    (globalThis as any).self = globalThis;
    const postMessageMock = vi.fn();
    (globalThis as any).postMessage = postMessageMock;

    const workerModule = await import('../workers/pythonEngine.worker');
    workerModule._testSetPandasLoaded(true);
    workerModule._testSetPyodide({
      globals: {
        get: () => {
          throw new Error('should not be called for invalid payload');
        }
      }
    });

    await workerModule._testSendMessage({ type: 'TRADE', side: 'invalid', bps: 50 });
    await workerModule._testSendMessage({ type: 'SET_AUTO_TRADE', enabled: 'not-a-bool' });

    expect(postMessageMock).toHaveBeenCalledWith(expect.objectContaining({ type: 'ERROR' }));
  });

  it('calls set_strategy_params and destroys proxies', async () => {
    (globalThis as any).self = globalThis;
    const postMessageMock = vi.fn();
    (globalThis as any).postMessage = postMessageMock;

    const setParamsMock: any = vi.fn();
    setParamsMock.destroy = vi.fn();
    
    const pyPayloadMock = { destroy: vi.fn() };

    const workerModule = await import('../workers/pythonEngine.worker');
    workerModule._testSetPandasLoaded(true);
    workerModule._testSetPyodide({
      globals: {
        get: (name: string) => {
          if (name === 'set_strategy_params') return setParamsMock;
          throw new Error('Unmocked function: ' + name);
        }
      },
      toPy: () => pyPayloadMock
    });

    await workerModule._testSendMessage({ type: 'SET_STRATEGY_PARAMS', payload: { foo: 'bar' } });

    expect(setParamsMock).toHaveBeenCalled();
    expect(postMessageMock).toHaveBeenCalledWith({ type: 'STRATEGY_PARAMS_UPDATED' });
    expect(setParamsMock.destroy).toHaveBeenCalled();
    expect(pyPayloadMock.destroy).toHaveBeenCalled();
  });

  it('destroys proxies even if set_strategy_params throws', async () => {
    (globalThis as any).self = globalThis;
    const postMessageMock = vi.fn();
    (globalThis as any).postMessage = postMessageMock;

    const setParamsMock: any = vi.fn(() => { throw new Error('failure'); });
    setParamsMock.destroy = vi.fn();
    
    const pyPayloadMock = { destroy: vi.fn() };

    const workerModule = await import('../workers/pythonEngine.worker');
    workerModule._testSetPandasLoaded(true);
    workerModule._testSetPyodide({
      globals: {
        get: (name: string) => {
          if (name === 'set_strategy_params') return setParamsMock;
          throw new Error('Unmocked function: ' + name);
        }
      },
      toPy: () => pyPayloadMock
    });

    await workerModule._testSendMessage({ type: 'SET_STRATEGY_PARAMS', payload: { foo: 'bar' } });

    expect(postMessageMock).toHaveBeenCalledWith(expect.objectContaining({ type: 'ERROR' }));
    expect(setParamsMock.destroy).toHaveBeenCalled();
    expect(pyPayloadMock.destroy).toHaveBeenCalled();
  });

  it('calls run_adhoc_analysis and destroys proxies', async () => {
    (globalThis as any).self = globalThis;
    const postMessageMock = vi.fn();
    (globalThis as any).postMessage = postMessageMock;

    const adhocFnMock: any = vi.fn(() => ({
      toJs: () => ({ result: 42 }),
      destroy: vi.fn()
    }));
    adhocFnMock.destroy = vi.fn();
    
    const pyPayloadMock = { destroy: vi.fn() };

    const workerModule = await import('../workers/pythonEngine.worker');
    workerModule._testSetPandasLoaded(true);
    workerModule._testSetPyodide({
      globals: {
        get: (name: string) => {
          if (name === 'run_adhoc_analysis') return adhocFnMock;
          throw new Error('Unmocked function: ' + name);
        }
      },
      toPy: () => pyPayloadMock
    });

    await workerModule._testSendMessage({ type: 'RUN_ADHOC', payload: { data: [1, 2, 3] } });

    expect(adhocFnMock).toHaveBeenCalled();
    expect(postMessageMock).toHaveBeenCalledWith({ type: 'ADHOC_RESULT', data: { result: 42 } });
    expect(adhocFnMock.destroy).toHaveBeenCalled();
    expect(pyPayloadMock.destroy).toHaveBeenCalled();
    // The results object returned by adhocFnMock() should also be destroyed
    const results = adhocFnMock.mock.results[0].value;
    expect(results.destroy).toHaveBeenCalled();
  });

  it('destroys proxies even if run_adhoc_analysis throws', async () => {
    (globalThis as any).self = globalThis;
    const postMessageMock = vi.fn();
    (globalThis as any).postMessage = postMessageMock;

    const adhocFnMock: any = vi.fn(() => { throw new Error('adhoc failure'); });
    adhocFnMock.destroy = vi.fn();
    
    const pyPayloadMock = { destroy: vi.fn() };

    const workerModule = await import('../workers/pythonEngine.worker');
    workerModule._testSetPandasLoaded(true);
    workerModule._testSetPyodide({
      globals: {
        get: (name: string) => {
          if (name === 'run_adhoc_analysis') return adhocFnMock;
          throw new Error('Unmocked function: ' + name);
        }
      },
      toPy: () => pyPayloadMock
    });

    await workerModule._testSendMessage({ type: 'RUN_ADHOC', payload: { data: [1, 2, 3] } });

    expect(postMessageMock).toHaveBeenCalledWith(expect.objectContaining({ type: 'ERROR' }));
    expect(adhocFnMock.destroy).toHaveBeenCalled();
    expect(pyPayloadMock.destroy).toHaveBeenCalled();
  });
});
