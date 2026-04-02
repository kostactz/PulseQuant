import path from 'path';
import { fileURLToPath } from 'url';
import { defineConfig } from 'vitest/config'

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname)
    }
  },
  test: {
    environment: 'node',
    globals: true,
    setupFiles: './test/setup.ts',
    pool: {
      // run tests in the same process to avoid remote worker unhandled errors for ESM-compat circuit.
      isolate: false,
      // vitest defaults to threads; this forces in-process mode.
      threads: false,
      forks: false
    },
    exclude: ['**/node_modules/**', '**/dist/**', '**/e2e/**'],
  },
})