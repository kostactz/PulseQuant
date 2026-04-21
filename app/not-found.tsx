import React from 'react';
import Link from 'next/link';

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen text-slate-200 bg-slate-950">
      <h2 className="text-2xl font-bold mb-4">404 - Not Found</h2>
      <p className="mb-4">Could not find requested resource</p>
      <Link href="/" className="text-emerald-400 hover:text-emerald-300">
        Return Home
      </Link>
    </div>
  );
}
