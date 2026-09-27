import type { RouteOption, RouteResponse } from './types';

export interface LatLngContext {
  lat: number;
  lng: number;
}

export interface RouteContext {
  origin?: LatLngContext;
  destination?: LatLngContext;
  departAt?: string;
}

// Last endpoints the map knows about. Customize opened from a heads-up card or a deep link has no
// coordinates of its own, but POST /customize needs routine_id + leg or origin + destination;
// this fills the gap and powers the retry when the routine isn't saved on the server.
let context: RouteContext = {};

export function setRouteContext(next: RouteContext): void {
  context = { ...context, ...next };
}

export function getRouteContext(): RouteContext {
  return context;
}

function routeOptions(response: RouteResponse | null): RouteOption[] {
  if (!response) return [];
  return response.routes
    ?? (response as unknown as { alternatives?: RouteOption[] }).alternatives
    ?? [];
}

// First and last point of the route on screen = its origin and destination.
export function endpointsFromRoute(response: RouteResponse | null): RouteContext {
  const geometry = (routeOptions(response)[0]?.route_geojson as unknown as
    | GeoJSON.FeatureCollection
    | undefined)?.features?.[0]?.geometry;
  if (!geometry || geometry.type !== 'LineString') return {};
  const coordinates = geometry.coordinates as [number, number][];
  if (coordinates.length < 2) return {};
  const [lngOrigin, latOrigin] = coordinates[0];
  const [lngDestination, latDestination] = coordinates[coordinates.length - 1];
  return {
    origin: { lat: latOrigin, lng: lngOrigin },
    destination: { lat: latDestination, lng: lngDestination },
  };
}
