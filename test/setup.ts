import Module from 'module';

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

process.on('unhandledRejection', (reason: any) => {
  const message = String(reason);
  if (message.includes('ERR_REQUIRE_ESM') || message.includes('html-encoding-sniffer')) {
    return;
  }
  throw reason;
});

process.on('uncaughtException', (error: any) => {
  const message = String(error);
  if (message.includes('ERR_REQUIRE_ESM') || message.includes('html-encoding-sniffer')) {
    return;
  }
  throw error;
});
