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

  it('processes UPDATE_STRATEGY, TRADE, SET_AUTO_TRADE, SET_TRADE_SIZE messages', async () => {
    (globalThis as any).self = globalThis;
    const postMessageMock = vi.fn();
    (globalThis as any).postMessage = postMessageMock;

    const executeTradeMock = vi.fn();
    executeTradeMock.destroy = vi.fn();
    const setAutoTradeMock = vi.fn();
    setAutoTradeMock.destroy = vi.fn();
    const updateStrategyMock = vi.fn();
    updateStrategyMock.destroy = vi.fn();
    const setTradeSizeMock = vi.fn();
    setTradeSizeMock.destroy = vi.fn();

    const workerModule = await import('../workers/pythonEngine.worker');
    workerModule._testSetPandasLoaded(true);
    workerModule._testSetPyodide({
      globals: {
        get: (name: string) => {
          if (name === 'execute_trade') return executeTradeMock;
          if (name === 'set_auto_trade') return setAutoTradeMock;
          if (name === 'update_strategy') return updateStrategyMock;
          if (name === 'set_trade_size') return setTradeSizeMock;
          throw new Error('Unmocked function: ' + name);
        }
      }
    });

    await workerModule._testSendMessage({ type: 'UPDATE_STRATEGY', style: 'moderate', speed: 'fast' });
    await workerModule._testSendMessage({ type: 'TRADE', side: 'buy', bps: 50 });
    await workerModule._testSendMessage({ type: 'SET_AUTO_TRADE', enabled: true });
    await workerModule._testSendMessage({ type: 'SET_TRADE_SIZE', bps: 200 });

    expect(updateStrategyMock).toHaveBeenCalledWith('moderate', 'fast');
    expect(executeTradeMock).toHaveBeenCalledWith('buy', 50);
    expect(setAutoTradeMock).toHaveBeenCalledWith(true);
    expect(setTradeSizeMock).toHaveBeenCalledWith(200);

    expect(postMessageMock).toHaveBeenCalledWith({ type: 'STRATEGY_UPDATED', style: 'moderate', speed: 'fast' });
    expect(postMessageMock).toHaveBeenCalledWith({ type: 'TRADE_EXECUTED' });
    expect(postMessageMock).toHaveBeenCalledWith({ type: 'AUTO_TRADE_UPDATED', enabled: true });
    expect(postMessageMock).toHaveBeenCalledWith({ type: 'TRADE_SIZE_UPDATED', bps: 200 });
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
});
