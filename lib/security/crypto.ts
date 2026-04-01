/**
 * Web Crypto API wrapper for AES-GCM encryption/decryption
 * Used to securely store Binance API keys in the browser's localStorage.
 */

// Helper to convert string to Uint8Array
function strToArrayBuffer(str: string): Uint8Array {
  return new TextEncoder().encode(str);
}

// Helper to convert Uint8Array to string
function arrayBufferToStr(buffer: ArrayBuffer): string {
  return new TextDecoder().decode(buffer);
}

// Helper to convert Uint8Array to base64
function arrayBufferToBase64(buffer: ArrayBuffer | Uint8Array): string {
  let binary = '';
  const bytes = new Uint8Array(buffer instanceof Uint8Array ? buffer.buffer : buffer);
  const len = bytes.byteLength;
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

// Helper to convert base64 to Uint8Array
function base64ToArrayBuffer(base64: string): Uint8Array {
  const binary_string = atob(base64);
  const len = binary_string.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    bytes[i] = binary_string.charCodeAt(i);
  }
  return bytes;
}

/**
 * Derives a strong AES-GCM key from a user-provided password (KEK).
 */
export async function deriveKey(password: string, saltHex?: string): Promise<{ key: CryptoKey; salt: string }> {
  const enc = new TextEncoder();
  const passwordBuffer = enc.encode(password);
  
  // Use existing salt or generate a new one
  let salt: Uint8Array;
  if (saltHex) {
    salt = base64ToArrayBuffer(saltHex);
  } else {
    salt = window.crypto.getRandomValues(new Uint8Array(16));
  }

  const importedKey = await window.crypto.subtle.importKey(
    'raw',
    passwordBuffer as any,
    { name: 'PBKDF2' },
    false,
    ['deriveKey']
  );

  const key = await window.crypto.subtle.deriveKey(
    {
      name: 'PBKDF2',
      salt: salt as any,
      iterations: 100000,
      hash: 'SHA-256'
    },
    importedKey,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt']
  );

  return { key, salt: arrayBufferToBase64(salt) };
}

/**
 * Encrypts a plaintext string using AES-GCM.
 */
export async function encryptData(plaintext: string, key: CryptoKey): Promise<{ ciphertext: string; iv: string }> {
  const iv = window.crypto.getRandomValues(new Uint8Array(12));
  const encodedText = strToArrayBuffer(plaintext);

  const encryptedBuffer = await window.crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: iv as any },
    key,
    encodedText as any
  );

  return {
    ciphertext: arrayBufferToBase64(encryptedBuffer),
    iv: arrayBufferToBase64(iv)
  };
}

/**
 * Decrypts a ciphertext string using AES-GCM.
 */
export async function decryptData(ciphertextBase64: string, ivBase64: string, key: CryptoKey): Promise<string> {
  const iv = base64ToArrayBuffer(ivBase64);
  const ciphertextBuffer = base64ToArrayBuffer(ciphertextBase64);

  const decryptedBuffer = await window.crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: iv as any },
    key,
    ciphertextBuffer as any
  );

  return arrayBufferToStr(decryptedBuffer as ArrayBuffer);
}
