'use client';

import React, { useState, useEffect } from 'react';
import { hasSavedCredentials, loadCredentials, saveCredentials, setRuntimeCredentials } from '../lib/security/credentials';

interface SecuritySetupModalProps {
  onSuccess: () => void;
}

export function SecuritySetupModal({ onSuccess }: SecuritySetupModalProps) {
  const [isSettingUp, setIsSettingUp] = useState(false);
  const [kek, setKek] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check if we already have saved credentials when component mounts
    const timeout = setTimeout(() => {
      if (!hasSavedCredentials()) {
        setIsSettingUp(true);
      }
      setLoading(false);
    }, 0);
    return () => clearTimeout(timeout);
  }, []);

  const handleSetup = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    
    if (!kek || !apiKey || !apiSecret) {
      setError('All fields are required');
      return;
    }

    try {
      const creds = { apiKey, apiSecret };
      await saveCredentials(kek, creds);
      setRuntimeCredentials(creds);
      onSuccess();
    } catch (err) {
      setError('Failed to encrypt and save credentials. ' + (err as Error).message);
    }
  };

  const handleUnlock = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    
    if (!kek) {
      setError('Password (KEK) is required');
      return;
    }

    try {
      const creds = await loadCredentials(kek);
      if (!creds) {
        setError('Incorrect password or corrupted data. If you lost your password, you will need to clear storage.');
        return;
      }
      
      setRuntimeCredentials(creds);
      onSuccess();
    } catch (err) {
      setError('Failed to decrypt credentials.');
    }
  };

  const handleReset = () => {
    if (confirm('This will delete your saved encrypted keys from this browser. You will need to re-enter them. Continue?')) {
      localStorage.removeItem('PulseQuant_encrypted_credentials');
      setIsSettingUp(true);
      setError('');
      setKek('');
    }
  };

  if (loading) {
    return (
      <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50">
        <div className="text-white">Loading Security Module...</div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 max-w-md w-full shadow-2xl text-white">
        <h2 className="text-xl font-bold mb-4">
          {isSettingUp ? 'Setup Trading Credentials' : 'Unlock Trading Engine'}
        </h2>
        
        {error && (
          <div className="bg-red-900/50 border border-red-500 text-red-200 px-3 py-2 rounded mb-4 text-sm">
            {error}
          </div>
        )}

        {isSettingUp ? (
          <form onSubmit={handleSetup} className="space-y-4">
            <p className="text-sm text-gray-400 mb-4">
              Your API keys will be encrypted locally in your browser using AES-GCM. 
              They are never sent to our servers.
            </p>
            
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Master Password (KEK)</label>
              <input 
                type="password"
                value={kek}
                onChange={(e) => setKek(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                placeholder="Create a strong password"
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Binance API Key</label>
              <input 
                type="text"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500 font-mono text-sm"
                placeholder="Enter API Key"
              />
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Binance Secret Key</label>
              <input 
                type="password"
                value={apiSecret}
                onChange={(e) => setApiSecret(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500 font-mono text-sm"
                placeholder="Enter Secret Key"
              />
            </div>
            
            <button 
              type="submit"
              className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 rounded transition-colors"
            >
              Encrypt & Save
            </button>
          </form>
        ) : (
          <form onSubmit={handleUnlock} className="space-y-4">
            <p className="text-sm text-gray-400 mb-4">
              Enter your master password to decrypt your Binance API keys and start the engine.
            </p>
            
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Master Password</label>
              <input 
                type="password"
                value={kek}
                onChange={(e) => setKek(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-white focus:outline-none focus:border-blue-500"
                placeholder="Enter your password"
                autoFocus
              />
            </div>
            
            <button 
              type="submit"
              className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 rounded transition-colors"
            >
              Unlock
            </button>

            <div className="mt-4 pt-4 border-t border-gray-800 text-center">
              <button 
                type="button" 
                onClick={handleReset}
                className="text-xs text-gray-500 hover:text-red-400 transition-colors"
              >
                Reset / Forgot Password?
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
