// @vitest-environment jsdom
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Dashboard from '../app/page';

vi.mock('@/hooks/usePythonWorker', () => ({
  usePythonWorker: () => ({
    isReady: true,
    metrics: {
      portfolio_value: 100000,
      capital: 100000,
      position: 0,
      last_micro_price: 40000,
      analytics: { profit_factor: 0, hit_ratio: 0, maker_fill_rate: 0 },
      current_dd_pct: 0,
      max_dd_pct: 0,
      max_dd_duration: 0,
      system_stats: { mps: 0, netLat: 0, sysLat: 0 }
    },
    uiDelta: null,
    getUIDelta: vi.fn(),
    processBatch: vi.fn(),
    clearData: vi.fn(),
    clearCache: vi.fn(),
    executeTrade: vi.fn(),
    setAutoTrade: vi.fn(),
    updateStrategy: vi.fn(),
    setTradeSize: vi.fn()
  })
}));

vi.mock('@/hooks/useMarketData', () => ({
  useMarketData: () => ({
    latestDepth: { bids: [], asks: [] },
    latestTick: null,
    getAndClearBuffer: vi.fn(),
    clearBuffer: vi.fn(),
    isPlaying: true,
    setIsPlaying: vi.fn(),
    isRecording: false,
    toggleRecording: vi.fn(),
    executeIntent: vi.fn()
  })
}));

describe('Dashboard smoke tests for onboarding + secure mode gating', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('opens in paper mode and shows welcome guide, no security modal initially', async () => {
    render(<Dashboard />);

    expect(await screen.findByText('Welcome to PulseQuant')).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: 'Got it!' }));

    await waitFor(() => {
      expect(screen.queryByText('Welcome to PulseQuant')).toBeNull();
    });

    expect(screen.queryByText('Setup Trading Credentials')).toBeNull();
  });

  it('switching to testnet with no credentials shows the security setup modal', async () => {
    render(<Dashboard />);

    await userEvent.click(screen.getByRole('button', { name: 'Got it!' }));
    await waitFor(() => expect(screen.queryByText('Welcome to PulseQuant')).toBeNull());

    await userEvent.click(screen.getByRole('button', { name: /Testnet/i }));

    expect(await screen.findByText('Setup Trading Credentials')).toBeTruthy();
  });

  it('skip path keeps user in paper mode and closes setup modal', async () => {
    render(<Dashboard />);

    await userEvent.click(screen.getByRole('button', { name: 'Got it!' }));
    await waitFor(() => expect(screen.queryByText('Welcome to PulseQuant')).toBeNull());

    await userEvent.click(screen.getByRole('button', { name: /Testnet/i }));
    await expect(screen.findByText('Setup Trading Credentials')).resolves.toBeTruthy();

    await userEvent.click(screen.getByText('Skip for now (return to Paper mode)'));

    await waitFor(() => {
      expect(screen.queryByText('Setup Trading Credentials')).toBeNull();
    });
    expect(screen.getByRole('button', { name: /Paper/i })).toBeTruthy();
  });
});
