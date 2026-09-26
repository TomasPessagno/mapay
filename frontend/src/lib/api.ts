import type { RouteRequest, RouteResponse, Routine } from "./types";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  route: (body: RouteRequest) => request<RouteResponse>("/route", { method: "POST", body: JSON.stringify(body) }),
  layers: (t: Date) => request<Record<string, GeoJSON.FeatureCollection>>(`/layers?t=${t.toISOString()}`),
  alerts: () => request<{ nws: unknown[]; news: unknown[] }>("/alerts"),
  report: (type: string, lat: number, lng: number) =>
    request("/report", { method: "POST", body: JSON.stringify({ type, lat, lng }) }),
  routines: (userId: string) => request<Routine[]>(`/routines?user_id=${userId}`),
  saveRoutine: (r: Routine) => request<Routine>("/routines", { method: "POST", body: JSON.stringify(r) }),
};
