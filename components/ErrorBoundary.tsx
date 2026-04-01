'use client';

import React from 'react';
import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

type ErrorBoundaryProps = {
  children: ReactNode;
  fallback?: (error: Error, resetError: () => void) => ReactNode;
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
};

type ErrorBoundaryState =
  | { hasError: false; error: null }
  | { hasError: true; error: Error };

function normalizeThrownError(error: unknown): Error {
  if (error instanceof Error) {
    return error;
  }

  if (typeof error === 'string') {
    return new Error(error);
  }

  if (typeof error === 'object' && error !== null) {
    const maybeMessage = (error as { message?: unknown }).message;
    if (typeof maybeMessage === 'string') {
      const normalizedMessage = maybeMessage.trim();
      if (normalizedMessage.length > 0) {
        return new Error(normalizedMessage);
      }
    }

    try {
      return new Error(JSON.stringify(error));
    } catch {
      return new Error('Non-Error object was thrown');
    }
  }

  return new Error(String(error));
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = {
    hasError: false,
    error: null,
  };

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return {
      hasError: true,
      error: normalizeThrownError(error),
    };
  }

  componentDidCatch(error: unknown, errorInfo: ErrorInfo) {
    const normalizedError = normalizeThrownError(error);
    console.error('ErrorBoundary caught:', normalizedError, errorInfo);
    this.props.onError?.(normalizedError, errorInfo);
  }

  private readonly resetError = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      const error = this.state.error;

      if (this.props.fallback) {
        return this.props.fallback(error, this.resetError);
      }

      return (
        <div className="min-h-[240px] bg-white border border-red-200 rounded-xl p-6 flex flex-col justify-center">
          <div className="flex items-center gap-2 text-red-600 mb-2">
            <AlertTriangle className="w-5 h-5" />
            <h2 className="text-lg font-semibold">Something went wrong</h2>
          </div>
          <p className="text-sm text-gray-600 mb-4">
            This section crashed unexpectedly. You can retry without reloading the page.
          </p>
          <div className="flex gap-3">
            <button
              onClick={this.resetError}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              Try Again
            </button>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 rounded-lg bg-gray-200 text-gray-700 hover:bg-gray-300 transition-colors"
            >
              Reload Page
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
