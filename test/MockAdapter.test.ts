import { describe, it, expect, vi } from 'vitest';
import { MockAdapter } from '../lib/market-data/adapters/MockAdapter';

describe('MockAdapter', () => {
  it('should initialize correctly', () => {
    const adapter = new MockAdapter();
    expect(adapter).toBeDefined();
  });
});