import { Capacitor } from '@capacitor/core';

export type DataSource = 'demo' | 'live';

export const DATA_SOURCE_STORAGE_KEY = 'mapay_data_source';

// The iPhone can't reach the Mac's localhost, so native builds fall back to the deployed API.
export const NATIVE_FALLBACK_BASE_URL = 'https://mapay-api-lgfe7q5oja-ue.a.run.app';

const BUILD_DEFAULT: DataSource = import.meta.env.VITE_USE_MOCKS === 'true' ? 'demo' : 'live';
const LOCALHOST_RE = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i;

export function getDataSource(): DataSource {
  try {
    const stored = localStorage.getItem(DATA_SOURCE_STORAGE_KEY);
    if (stored === 'demo' || stored === 'live') return stored;
  } catch {
    // localStorage can be unavailable (private mode); fall back to the build default.
  }
  return BUILD_DEFAULT;
}

export function setDataSource(source: DataSource): void {
  try {
    localStorage.setItem(DATA_SOURCE_STORAGE_KEY, source);
  } catch {
    // ignore: the build default still applies
  }
}

export function isDemo(): boolean {
  return getDataSource() === 'demo';
}

// Read at request time so a switch only needs a reload.
export function apiBaseUrl(): string {
  const configured = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '');
  if (Capacitor.isNativePlatform() && LOCALHOST_RE.test(configured)) {
    return NATIVE_FALLBACK_BASE_URL;
  }
  return configured;
}
