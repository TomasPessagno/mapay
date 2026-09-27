import { Device } from '@capacitor/device';
import { reloadWidgets } from './native';
import { mergeDemoPlaces, mergeDemoRoutines, mergeDemoUpcoming, saveDemoPlace, saveDemoRoutine } from './demoRoutines';
import type { RouteResponse, Routine, UpcomingRoutinesResponse, Neighborhood, Preferences, LayersResponse, Place } from "./types";
import { apiBaseUrl, isDemo } from "./dataSource";

type LatLngObj = { lat: number; lng: number };

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
  // Read at request time: the Demo/Live switch in Preferences takes effect after a reload.
  if (isDemo()) {
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

    const mockUrl = `${import.meta.env.BASE_URL}mocks${mockFile}.json`;
    if (init?.method === 'POST' && path.startsWith('/places')) {
      return { _id: crypto.randomUUID(), ...JSON.parse(init.body as string) } as T;
    }
    const res = await fetch(mockUrl);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText} fetching mock ${mockUrl}`);
    return res.json() as Promise<T>;
  }

  const deviceId = await getDeviceId();
  const res = await fetch(`${apiBaseUrl()}${path}`, {
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
  // POST /route takes origin/destination as [lat, lng] pairs (backend LatLng); the app passes {lat, lng}.
  route: ({ origin, destination, ...rest }: { origin: LatLngObj; destination: LatLngObj } & Record<string, unknown>) =>
    request<RouteResponse>("/route", {
      method: "POST",
      body: JSON.stringify({ ...rest, origin: [origin.lat, origin.lng], destination: [destination.lat, destination.lng] }),
    }),
  // bbox = [west, south, east, north]; without it /layers returns all of Miami-Dade (~800 KB gzipped).
  layers: (t: Date, bbox?: [number, number, number, number]) =>
    request<LayersResponse>(`/layers?t=${t.toISOString()}${bbox ? `&bbox=${bbox.join(",")}` : ""}`),
  alerts: () => request<{ nws: unknown[]; news: unknown[] }>("/alerts"),
  report: (data: { type: string; lat: number; lng: number; hazard_id?: string; cleared?: boolean }) =>
    request("/report", { method: "POST", body: JSON.stringify(data) }),
  routines: async () => {
    const list = await request<Routine[]>("/routines");
    return isDemo() ? mergeDemoRoutines(list) : list;
  },
  saveRoutine: async (r: Routine) => {
    // Demo mode keeps the routine locally (demoRoutines.ts) so its heads-up can be scheduled.
    const saved = isDemo() ? saveDemoRoutine(r) : await request<Routine>("/routines", { method: "POST", body: JSON.stringify(r) });
    reloadWidgets(); // the home-screen widget shows the next leg
    window.dispatchEvent(new Event('mapay:routines-changed')); // reschedules the heads-up notifications
    return saved;
  },
  upcomingRoutines: async (days: number = 7) => {
    const res = await request<UpcomingRoutinesResponse>(`/routines/upcoming?days=${days}`);
    if (!isDemo()) return res;
    // Locally created Demo-mode routines aren't in the mock; compute and merge their occurrences.
    const places = await request<Place[]>('/places').catch(() => [] as Place[]);
    return { ...res, items: mergeDemoUpcoming(res.items, places, new Date(), days) };
  },
  /** Live demo: makes that leg due in heads_up_minutes, so /routines/upcoming lists it in heads-up mode. */
  demoHeadsUp: (routineId: string, leg: number) =>
    request<{ departure_at: string; heads_up_at: string }>('/demo/heads-up', {
      method: 'POST',
      body: JSON.stringify({ routine_id: routineId, leg }),
    }),
  places: async () => {
    const list = await request<Place[]>("/places");
    return isDemo() ? mergeDemoPlaces(list) : list;
  },
  // Stored shape follows public/mocks/places.json (GeoJSON Point). The mock is a GET list, so with
  // mocks on the place is kept locally instead of POSTing.
  savePlace: async (p: { name: string; lat: number; lng: number; google_place_id?: string; address?: string }) => {
    const body = {
      name: p.name,
      google_place_id: p.google_place_id,
      location: { type: 'Point' as const, coordinates: [p.lng, p.lat] as [number, number] },
    };
    if (isDemo()) return saveDemoPlace({ _id: `pl-${Date.now()}`, user_id: 'device-demo', address: p.address, ...body } as Place);
    return request<Place>("/places", { method: "POST", body: JSON.stringify(body) });
  },
  neighborhoods: async (q?: string) => {
    let res = await request<Neighborhood[]>(`/neighborhoods${q ? `?q=${encodeURIComponent(q)}` : ''}`);
    if (isDemo() && q) {
      res = res.filter(n => n.name.toLowerCase().includes(q.toLowerCase()));
    }
    return res;
  },
  getPreferences: () => request<Preferences>("/me/preferences"),
  savePreferences: (p: Preferences) => request<Preferences>("/me/preferences", { method: "PUT", body: JSON.stringify(p) }),
  customize: (body: unknown) => request<unknown>("/customize", { method: "POST", body: JSON.stringify(body) }),
};
