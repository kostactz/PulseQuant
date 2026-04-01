// @vitest-environment jsdom
import React, { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { ErrorBoundary } from '../components/ErrorBoundary';

function ThrowingComponent() {
  throw new Error('Boom');
}

function ThrowingStringComponent() {
  throw 'string failure';
}

function ThrowingObjectComponent() {
  throw { reason: 'object failure' };
}

function RecoveryHarness() {
  const [shouldThrow, setShouldThrow] = useState(true);

  return (
    <ErrorBoundary
      fallback={(error, resetError) => (
        <div>
          <p>Caught: {error.message}</p>
          <button
            onClick={() => {
              setShouldThrow(false);
              resetError();
            }}
          >
            Recover
          </button>
        </div>
      )}
    >
      {shouldThrow ? <ThrowingComponent /> : <div>Recovered</div>}
    </ErrorBoundary>
  );
}

function OnErrorHarness({ onError }: { onError: (error: Error) => void }) {
  return (
    <ErrorBoundary onError={onError}>
      <ThrowingComponent />
    </ErrorBoundary>
  );
}

describe('ErrorBoundary', () => {
  let consoleSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    consoleSpy.mockRestore();
  });

  it('shows fallback UI when a child throws during render', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent />
      </ErrorBoundary>
    );

    expect(screen.getByText('Something went wrong')).toBeTruthy();
  });

  it('allows recovery after reset when the child no longer throws', async () => {
    const user = userEvent.setup();
    render(<RecoveryHarness />);

    expect(screen.getByText('Caught: Boom')).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Recover' }));

    expect(screen.getByText('Recovered')).toBeTruthy();
  });

  it('invokes onError callback from componentDidCatch', () => {
    const onError = vi.fn();

    render(<OnErrorHarness onError={onError} />);

    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError.mock.calls[0]?.[0]).toBeInstanceOf(Error);
    expect(onError.mock.calls[0]?.[0]?.message).toBe('Boom');
  });

  it('default fallback try again resets and allows recovery', async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <ErrorBoundary>
        <ThrowingComponent />
      </ErrorBoundary>
    );

    expect(screen.getByText('Something went wrong')).toBeTruthy();

    rerender(
      <ErrorBoundary>
        <div>Recovered with default fallback</div>
      </ErrorBoundary>
    );

    await user.click(screen.getByRole('button', { name: 'Try Again' }));
    expect(screen.getByText('Recovered with default fallback')).toBeTruthy();
  });

  it('normalizes non-Error string exceptions and shows fallback UI', () => {
    render(
      <ErrorBoundary fallback={(error) => <div>Normalized: {error.message}</div>}>
        <ThrowingStringComponent />
      </ErrorBoundary>
    );

    expect(screen.getByText('Normalized: string failure')).toBeTruthy();
  });

  it('normalizes non-Error object exceptions and shows fallback UI', () => {
    render(
      <ErrorBoundary fallback={(error) => <div>Normalized: {error.message}</div>}>
        <ThrowingObjectComponent />
      </ErrorBoundary>
    );

    expect(screen.getByText('Normalized: {"reason":"object failure"}')).toBeTruthy();
  });
});
