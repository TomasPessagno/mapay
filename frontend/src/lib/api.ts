import { Device } from '@capacitor/device';
import type { RouteResponse, Routine, UpcomingRoutinesResponse, Neighborhood, Preferences, LayersResponse } from "./types";

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true';
// Paths start with "/", so drop any trailing slash ("http://localhost:8000/" would call "//route").
const BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/+$/, "");

let deviceIdCache: string | null = null;

async function getDeviceId(): Promise<string> {
  if (deviceIdCache) return deviceIdCache;
  try {
    const info = await Device.getId();
    deviceIdCache = info.identifier;
  } catch {
    // Fallback for web
    let stored = localStorage.getItem('mapay_device_id');
    if (!stored) {
      stored = crypto.randomUUID();
      localStorage.setItem('mapay_device_id', stored);
    }
    deviceIdCache = stored;
  }
  return deviceIdCache;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (USE_MOCKS) {
    // map /route -> /mocks/route.json
    let mockFile = path.split('?')[0];
    if (mockFile === '/') mockFile = '/index';
    
    // For specific endpoints, map them to mock files
    if (mockFile.startsWith('/route')) mockFile = '/route';
    else if (mockFile.startsWith('/layers')) mockFile = '/layers';
    else if (mockFile.startsWith('/alerts')) mockFile = '/alerts';
    else if (mockFile.startsWith('/routines/upcoming')) mockFile = '/routines-upcoming';
    else if (mockFile.startsWith('/routines')) mockFile = '/routines';
    else if (mockFile.startsWith('/places')) mockFile = '/places';
    else if (mockFile.startsWith('/neighborhoods')) mockFile = '/neighborhoods';
    else if (mockFile.startsWith('/me/preferences')) mockFile = '/preferences';
    else if (mockFile.startsWith('/customize')) mockFile = '/customize';

    const mockUrl = `/mocks${mockFile}.json`;
    const res = await fetch(mockUrl);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText} fetching mock ${mockUrl}`);
    return res.json() as Promise<T>;
  }

  const deviceId = await getDeviceId();
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 
      "Content-Type": "application/json",
      "X-Device-Id": deviceId,
      ...init?.headers 
    },
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  route: (body: unknown) => request<RouteResponse>("/route", { method: "POST", body: JSON.stringify(body) }),
  layers: (t: Date) => request<LayersResponse>(`/layers?t=${t.toISOString()}`),
  alerts: () => request<{ nws: unknown[]; news: unknown[] }>("/alerts"),
  report: (type: string, lat: number, lng: number) =>
    request("/report", { method: "POST", body: JSON.stringify({ type, lat, lng }) }),
  routines: () => request<Routine[]>(`/routines`),
  saveRoutine: (r: Routine) => request<Routine>("/routines", { method: "POST", body: JSON.stringify(r) }),
  upcomingRoutines: (days: number = 7) => request<UpcomingRoutinesResponse>(`/routines/upcoming?days=${days}`),
  places: () => request<unknown[]>("/places"),
  neighborhoods: () => request<Neighborhood[]>("/neighborhoods"),
  getPreferences: () => request<Preferences>("/me/preferences"),
  savePreferences: (p: Preferences) => request<Preferences>("/me/preferences", { method: "PUT", body: JSON.stringify(p) }),
  customize: (body: unknown) => request<unknown>("/customize", { method: "POST", body: JSON.stringify(body) }),
};
