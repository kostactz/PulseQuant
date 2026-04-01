import { deriveKey, encryptData, decryptData } from './crypto';

const STORAGE_KEY = 'PulseQuant_encrypted_credentials';

export interface Credentials {
  apiKey: string;
  apiSecret: string;
}

interface EncryptedPayload {
  salt: string;
  iv: string;
  ciphertext: string;
}

/**
 * Checks if encrypted credentials exist in localStorage.
 */
export function hasSavedCredentials(): boolean {
  if (typeof window === 'undefined') return false;
  return !!localStorage.getItem(STORAGE_KEY);
}

/**
 * Encrypts and saves credentials to localStorage using the provided KEK (password).
 */
export async function saveCredentials(kek: string, creds: Credentials): Promise<void> {
  const { key, salt } = await deriveKey(kek);
  const payloadStr = JSON.stringify(creds);
  const { ciphertext, iv } = await encryptData(payloadStr, key);

  const payload: EncryptedPayload = { salt, iv, ciphertext };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

/**
 * Loads and decrypts credentials from localStorage using the provided KEK (password).
 */
export async function loadCredentials(kek: string): Promise<Credentials | null> {
  if (typeof window === 'undefined') return null;

  const stored = localStorage.getItem(STORAGE_KEY);
  if (!stored) return null;

  try {
    const payload: EncryptedPayload = JSON.parse(stored);
    const { key } = await deriveKey(kek, payload.salt);
    const decryptedStr = await decryptData(payload.ciphertext, payload.iv, key);
    return JSON.parse(decryptedStr) as Credentials;
  } catch (err) {
    console.error('Failed to decrypt credentials. Incorrect KEK or corrupted data.');
    return null;
  }
}

/**
 * Removes the saved credentials from localStorage.
 */
export function clearCredentials(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(STORAGE_KEY);
}

// In-memory runtime storage for decrypted keys so they aren't kept in localStorage
let runtimeCredentials: Credentials | null = null;

export function setRuntimeCredentials(creds: Credentials) {
  runtimeCredentials = creds;
}

export function getRuntimeCredentials(): Credentials | null {
  // If we're in Node.js (headless mode), attempt to parse from argv
  if (typeof window === 'undefined' && !runtimeCredentials) {
    const apiKeyArg = process.argv.find(arg => arg.startsWith('--api-key='));
    const apiSecretArg = process.argv.find(arg => arg.startsWith('--api-secret='));

    if (apiKeyArg && apiSecretArg) {
      runtimeCredentials = {
        apiKey: apiKeyArg.split('=')[1],
        apiSecret: apiSecretArg.split('=')[1]
      };
    }
  }

  return runtimeCredentials;
}

export function clearRuntimeCredentials(): void {
  runtimeCredentials = null;
}
