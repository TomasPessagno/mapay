import { Device } from '@capacitor/device';
import type { RouteResponse, Routine, UpcomingRoutinesResponse, Neighborhood, Preferences, LayersResponse, Place } from "./types";

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true';
// Paths start with "/", so drop any trailing slash ("http://localhost:8000/" would call "//route").
const BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/+$/, "");

let deviceIdCache: string | null = null;

export async function getDeviceId(): Promise<string> {
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
    if (init?.method === 'POST' && path.startsWith('/places')) {
      return { _id: crypto.randomUUID(), ...JSON.parse(init.body as string) } as T;
    }
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
  report: (data: { type: string; lat: number; lng: number; hazard_id?: string; cleared?: boolean }) =>
    request("/report", { method: "POST", body: JSON.stringify(data) }),
  routines: () => request<Routine[]>(`/routines`),
  saveRoutine: (r: Routine) => request<Routine>("/routines", { method: "POST", body: JSON.stringify(r) }),
  upcomingRoutines: (days: number = 7) => request<UpcomingRoutinesResponse>(`/routines/upcoming?days=${days}`),
  places: () => request<Place[]>("/places"),
  // Stored shape follows public/mocks/places.json (GeoJSON Point). The mock is a GET list, so with
  // mocks on this returns the new place locally instead of POSTing.
  savePlace: async (p: { name: string; lat: number; lng: number; google_place_id?: string; address?: string }) => {
    const body = {
      name: p.name,
      google_place_id: p.google_place_id,
      location: { type: 'Point' as const, coordinates: [p.lng, p.lat] as [number, number] },
    };
    if (USE_MOCKS) return { _id: `pl-${Date.now()}`, user_id: 'device-demo', address: p.address, ...body } as Place;
    return request<Place>("/places", { method: "POST", body: JSON.stringify(body) });
  },
  neighborhoods: async (q?: string) => {
    let res = await request<Neighborhood[]>(`/neighborhoods${q ? `?q=${encodeURIComponent(q)}` : ''}`);
    if (USE_MOCKS && q) {
      res = res.filter(n => n.name.toLowerCase().includes(q.toLowerCase()));
    }
    return res;
  },
  getPreferences: () => request<Preferences>("/me/preferences"),
  savePreferences: (p: Preferences) => request<Preferences>("/me/preferences", { method: "PUT", body: JSON.stringify(p) }),
  customize: (body: unknown) => request<unknown>("/customize", { method: "POST", body: JSON.stringify(body) }),
};
