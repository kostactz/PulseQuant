import type {Metadata} from 'next';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import './globals.css'; // Global styles

export const metadata: Metadata = {
  title: 'PulseQuant | BTC-USDT',
  description: '',
};

export default function RootLayout({children}: {children: React.ReactNode}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <ErrorBoundary>{children}</ErrorBoundary>
      </body>
    </html>
  );
}
