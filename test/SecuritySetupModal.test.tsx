// @vitest-environment jsdom
import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { SecuritySetupModal } from '../components/SecuritySetupModal';

describe('SecuritySetupModal', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('shows setup UI when no credentials are saved and allows skip to paper', async () => {
    const onSuccess = vi.fn();
    const onSkip = vi.fn();

    render(<SecuritySetupModal onSuccess={onSuccess} onSkip={onSkip} />);

    expect(await screen.findByText('Setup Trading Credentials')).toBeTruthy();
    expect(screen.getByText('Skip for now (return to Paper mode)')).toBeTruthy();

    await userEvent.click(screen.getByText('Skip for now (return to Paper mode)'));
    expect(onSkip).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it('shows unlock UI when credentials exist in localStorage', async () => {
    const fakePayload = JSON.stringify({ salt: 's', iv: 'i', ciphertext: 'c' });
    localStorage.setItem('PulseQuant_encrypted_credentials', fakePayload);

    render(<SecuritySetupModal onSuccess={vi.fn()} />);

    expect(await screen.findByText('Unlock Trading Engine')).toBeTruthy();
  });
});
