import Module from 'module';
import { vi, beforeEach } from 'vitest';

const originalRequire = Module.prototype.require;

// Monkeypatch html-encoding-sniffer and nested @exodus bytes path to avoid ERR_REQUIRE_ESM issues under Node + vitest.
Module.prototype.require = function (id: string, ...args: any[]) {
  if (id === 'html-encoding-sniffer') {
    return function htmlEncodingSniffer(uint8Array: Uint8Array) {
      return 'UTF-8';
    };
  }
  if (id === '@exodus/bytes/encoding-lite.js' || id === '@exodus/bytes/encoding-lite') {
    return {
      getBOMEncoding: () => null,
      labelToName: (label: string | null) => {
        if (label === null || label === undefined) return null;
        return String(label);
      },
    };
  }
  return (originalRequire as any).apply(this, [id, ...args]);
};

function isExpectedEsmImportError(error: any): boolean {
  if (!error || typeof error !== 'object') return false;
  const code = (error as any).code;
  if (code !== 'ERR_REQUIRE_ESM') return false;
  const message = String(error);
  return (
    message.includes('html-encoding-sniffer') ||
    message.includes('@exodus/bytes/encoding-lite.js') ||
    message.includes('@exodus/bytes/encoding-lite')
  );
}

let hasLoggedSuppressedEsmError = false;

process.on('unhandledRejection', (reason: any) => {
  if (isExpectedEsmImportError(reason)) {
    if (!hasLoggedSuppressedEsmError) {
      hasLoggedSuppressedEsmError = true;
      console.warn('[test/setup] Suppressing known ERR_REQUIRE_ESM html-encoding-sniffer/@exodus/bytes import error for unhandledRejection.');
    }
    return;
  }
  throw reason;
});

process.on('uncaughtException', (error: any) => {
  if (isExpectedEsmImportError(error)) {
    if (!hasLoggedSuppressedEsmError) {
      hasLoggedSuppressedEsmError = true;
      console.warn('[test/setup] Suppressing known ERR_REQUIRE_ESM html-encoding-sniffer/@exodus/bytes import error for uncaughtException.');
    }
    return;
  }
  throw error;
});

const matchMediaMock = function(query: string) {
  return {
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(), // deprecated
    removeListener: vi.fn(), // deprecated
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  };
};

if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn(matchMediaMock),
  });
}
if (typeof global !== 'undefined') {
  Object.defineProperty(global, 'matchMedia', {
    writable: true,
    value: vi.fn(matchMediaMock),
  });
}
if (typeof globalThis !== 'undefined') {
  Object.defineProperty(globalThis, 'matchMedia', {
    writable: true,
    value: vi.fn(matchMediaMock),
  });
}

beforeEach(() => {
  if (typeof window !== 'undefined') {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn(matchMediaMock),
    });
  }
});

if (typeof HTMLCanvasElement !== 'undefined') {
  HTMLCanvasElement.prototype.getContext = () => {
    return {
      fillRect: () => {},
      clearRect: () => {},
      getImageData: (x: number, y: number, w: number, h: number) => {
        return {
          data: new Array(w * h * 4),
        };
      },
      putImageData: () => {},
      createImageData: () => { return []; },
      setTransform: () => {},
      drawImage: () => {},
      save: () => {},
      fillText: () => {},
      restore: () => {},
      beginPath: () => {},
      moveTo: () => {},
      lineTo: () => {},
      closePath: () => {},
      stroke: () => {},
      translate: () => {},
      scale: () => {},
      rotate: () => {},
      arc: () => {},
      fill: () => {},
      measureText: () => {
        return { width: 0 };
      },
      transform: () => {},
      rect: () => {},
      clip: () => {},
    } as any;
  };

  Object.defineProperty(HTMLCanvasElement.prototype, 'clientWidth', {
    configurable: true,
    get() { return 100; },
  });
  Object.defineProperty(HTMLCanvasElement.prototype, 'clientHeight', {
    configurable: true,
    get() { return 100; },
  });
  Object.defineProperty(HTMLCanvasElement.prototype, 'width', {
    configurable: true,
    get() { return 100; },
    set() {},
  });
  Object.defineProperty(HTMLCanvasElement.prototype, 'height', {
    configurable: true,
    get() { return 100; },
    set() {},
  });
}
