export type HazardType = 'flood' | 'weather' | 'construction' | 'closure' | 'congestion' | 'no_sidewalk' | 'pothole' | 'incident' | 'event';

export type PreferenceCategoryMap = Record<HazardType, 'avoid' | 'prefer_avoid' | 'ignore'>;

export interface Preferences {
  categories: Partial<PreferenceCategoryMap>;
  avoid_neighborhoods: string[];
  avoid_tolls?: boolean;
  avoid_highways?: boolean;
  nav_app?: 'google_maps' | 'apple_maps' | 'waze';
}

export interface Place {
  _id: string;
  user_id?: string;
  name: string;
  google_place_id?: string;
  address?: string; // display only; not part of the stored place
  location: {
    type: 'Point';
    coordinates: [number, number]; // [lng, lat], as in public/mocks/places.json
  };
}

export interface RoutineRepeat {
  kind: 'daily' | 'weekly' | 'custom';
  weekday?: string;   // 'mon', 'tue', etc. for weekly
  weekdays?: string[]; // ['mon', 'wed'] for custom
}

export interface RoutineWhen {
  kind: 'at' | 'window';
  time?: string; // '09:30'
  start?: string; // '17:00'
  end?: string; // '19:00'
}

export interface RoutineLeg {
  from_place: string;
  to_place: string;
  when: RoutineWhen;
  anchor: 'depart' | 'arrive';
  days?: string[] | null;
}

export interface Routine {
  _id: string;
  user_id: string;
  name: string;
  active: boolean;
  repeat: RoutineRepeat;
  legs: RoutineLeg[];
  tz: string;
  heads_up_minutes: number;
  preferences?: Preferences;
}

export interface HazardOnRoute {
  hazard_id: string;
  hazard_type: HazardType;
  title: string;
  probability: number;
  status?: string; // e.g. "observed"
}

export interface RouteOption {
  summary: string;
  route_geojson: Record<string, unknown>; // GeoJSON FeatureCollection
  duration_s: number;
  static_duration_s: number;
  distance_m: number;
  score: number;
  recommended: boolean;
  hazards_on_route: HazardOnRoute[];
  neighborhoods_crossed?: string[]; // avoided neighbourhood ids this route still enters
}

export interface RouteResponse {
  routes: RouteOption[];
  waypoints?: [number, number][];
  hazards_on_route: HazardOnRoute[];
  deep_links: {
    google_maps?: string;
    apple_maps?: string;
    waze?: string;
    start?: string;
    customize?: string;
  };
  briefing: string;
}

export interface UpcomingLegPlace {
  place_id: string;
  name: string;
}

export interface UpcomingLeg {
  routine_id: string;
  routine_name: string;
  leg: number;
  from: UpcomingLegPlace;
  to: UpcomingLegPlace;
  local_date: string;
  departure_at: string;
  heads_up_at: string;
  window: { start: string; end: string } | null;
  best_departure_at: string | null;
  best_saving_s?: number | null; // seconds saved vs leaving at the window start ("Leave at 17:45: 14 min faster")
  duration_s: number;
  static_duration_s: number;
  summary: string;
  top_hazards: HazardOnRoute[];
  image_url: string | null;
  deep_links: Record<string, string>;
}

export interface UpcomingRoutinesResponse {
  generated_at: string;
  items: UpcomingLeg[];
}

export interface Neighborhood {
  id: string;
  name: string;
  source?: string;
}

export interface CustomizeResponse {
  prompt: string;
  constraints: Record<string, unknown>;
  old_route: RouteOption;
  new_route: RouteOption;
  explanation: string;
  deep_links: {
    google_maps?: string;
    apple_maps?: string;
    waze?: string;
  };
  waypoints?: [number, number][]; // [lat, lng] stops + detour points, in route order
  depart_at?: string | null; // when the prompt set a departure ("leave at 6:15")
  unmet?: string[]; // parts of the prompt that couldn't be applied, e.g. "no Starbucks near the route"
  constraints_source?: 'gemini' | 'keywords'; // keywords = Gemini unavailable, simple parser used
}

export interface RadarOverlay {
  type: string;
  url_template: string;
  attribution: string;
  min_zoom?: number;
  max_zoom?: number;
  tile_size?: number;
  opacity?: number;
}

// Last successful run of one ingestion job, exposed in `freshness` as `<job>_run`
// (e.g. `news_run`): separate from `<source>` (the last hazard change). Optional keys.
export interface IngestRun {
  job: string;
  last_run_at: string;
  items_seen?: number;
  items_new?: number;
  hazards_added?: number;
  hazards_updated?: number;
}

export interface LayersResponse {
  t?: string;
  freshness?: Record<string, string | IngestRun>;
  radar?: RadarOverlay;
  [layerName: string]: unknown; // GeoJSON FeatureCollections keyed by legend category
}

export type LatLng = [number, number];
