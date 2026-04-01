// @vitest-environment jsdom
import React, { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { ErrorBoundary } from '../components/ErrorBoundary';

function ThrowingComponent() {
  throw new Error('Boom');
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
});
