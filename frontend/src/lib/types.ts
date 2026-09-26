export type LatLng = [number, number];

export interface RouteRequest {
  origin: LatLng;
  destination: LatLng;
  depart_at?: string;
  avoid_tolls?: boolean;
  mode?: "drive" | "walk";
}

export interface RouteResponse {
  route_geojson: GeoJSON.FeatureCollection;
  baseline_geojson?: GeoJSON.FeatureCollection | null;
  hazards_avoided: Record<string, unknown>[];
  briefing?: string | null;
  deep_links: Record<string, string>;
}

export interface Routine {
  _id?: string;
  user_id: string;
  origin: LatLng;
  destination: LatLng;
  days: string[];
  time_window: [string, string];
  preferences: Record<string, unknown>;
}
