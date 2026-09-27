#!/usr/bin/env node
/**
 * B23 (#132) demo-data generator for `frontend/public/mocks/layers.json`.
 *
 * One-off: needs the network, not run by tests or the build. It pulls real street geometry from the
 * OpenStreetMap Overpass API (and real `sidewalk=no` ways for the no-sidewalk layer), turns a
 * hand-written hazard catalog into the `/layers` contract shape, and writes the mock file.
 *
 *   node frontend/scripts/gen-demo-layers.mjs
 *
 * Overpass responses are cached under `.scratch/overpass-cache/` (git-ignored), so re-runs only
 * hit the network for new streets. If a street can't be resolved the feature falls back to a
 * straight segment at its anchor and the run logs `MISS`.
 */

import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..', '..');
const OUT_FILE = resolve(HERE, '..', 'public', 'mocks', 'layers.json');
const CACHE_DIR = resolve(ROOT, '.scratch', 'overpass-cache');

const BASE = '2026-09-28';
const METRO = '25.35,-80.65,25.98,-80.05';
const OVERPASS_ENDPOINTS = [
  'https://overpass.kumi.systems/api/interpreter',
  'https://overpass-api.de/api/interpreter',
  'https://overpass.private.coffee/api/interpreter',
  'https://overpass.osm.ch/api/interpreter',
];
const USER_AGENT = 'mapay-demo-generator/1.0 (ShellHacks hackathon; contact: repo)';

// ---------------------------------------------------------------- Overpass

let endpointCursor = 0;

async function overpass(query) {
  const cacheKey = createHash('sha1').update(query).digest('hex').slice(0, 16);
  const cacheFile = resolve(CACHE_DIR, `${cacheKey}.json`);
  if (existsSync(cacheFile)) return JSON.parse(readFileSync(cacheFile, 'utf8'));

  let lastError;
  for (let attempt = 0; attempt < 12; attempt++) {
    const endpoint = OVERPASS_ENDPOINTS[endpointCursor++ % OVERPASS_ENDPOINTS.length];
    try {
      const body = new URLSearchParams({ data: query });
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'User-Agent': USER_AGENT, 'Content-Type': 'application/x-www-form-urlencoded' },
        body,
      });
      const text = await res.text();
      if (!res.ok || text.trimStart().startsWith('<')) throw new Error(`${res.status} busy`);
      const parsed = JSON.parse(text);
      // Some mirrors answer from an empty database: an empty result is never cached.
      if (!(parsed.elements ?? []).length) throw new Error('empty result');
      mkdirSync(CACHE_DIR, { recursive: true });
      writeFileSync(cacheFile, JSON.stringify(parsed));
      return parsed;
    } catch (err) {
      lastError = err;
      await new Promise((r) => setTimeout(r, 2500));
    }
  }
  throw lastError;
}

const escapeRe = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const nameCache = new Map();
const refCache = new Map();

async function namedWays(names) {
  const missing = names.filter((name) => !nameCache.has(name));
  for (let i = 0; i < missing.length; i += 5) {
    const chunk = missing.slice(i, i + 5);
    const alt = chunk.map(escapeRe).join('|');
    const query = `[out:json][timeout:180];way["highway"]["name"~"^(${alt})$"](${METRO});out geom;`;
    let result;
    try {
      result = await overpass(query);
    } catch (error) {
      console.warn(`Overpass failed for names ${chunk.join(', ')}: ${error.message}`);
      result = { elements: [] };
    }
    const grouped = new Map(chunk.map((name) => [name, []]));
    for (const element of result.elements ?? []) {
      const name = element.tags?.name;
      if (grouped.has(name)) grouped.get(name).push(element);
    }
    for (const name of chunk) nameCache.set(name, grouped.get(name));
  }
  return names.flatMap((name) => nameCache.get(name) ?? []);
}

async function refWays(refRegex) {
  if (!refCache.has(refRegex)) {
    const query = `[out:json][timeout:180];way["highway"]["ref"~"${refRegex}"](${METRO});out geom;`;
    try {
      const result = await overpass(query);
      refCache.set(refRegex, result.elements ?? []);
    } catch (error) {
      console.warn(`Overpass failed for ref ${refRegex}: ${error.message}`);
      refCache.set(refRegex, []);
    }
  }
  return refCache.get(refRegex);
}

const I95_REF = '(^|;)I 95($|;)';

async function waysFor(geometry) {
  const groups = [];
  if (geometry.street) groups.push(await namedWays([].concat(geometry.street)));
  if (geometry.ref) groups.push(await refWays(geometry.ref));
  return groups.flat().filter((element) => Array.isArray(element.geometry) && element.geometry.length >= 2);
}

// ---------------------------------------------------------------- Geometry

const M_PER_DEG = 111320;
const round5 = (value) => Math.round(value * 1e5) / 1e5;
const mPerLng = (lat) => M_PER_DEG * Math.cos((lat * Math.PI) / 180);

function lineMetres(line) {
  let total = 0;
  for (let i = 1; i < line.length; i++) {
    const dx = (line[i][0] - line[i - 1][0]) * mPerLng(line[i][1]);
    const dy = (line[i][1] - line[i - 1][1]) * M_PER_DEG;
    total += Math.hypot(dx, dy);
  }
  return total;
}

function pointToSegmentMetres(point, a, b) {
  const lat = ((a[1] + b[1]) / 2) * (Math.PI / 180);
  const kx = M_PER_DEG * Math.cos(lat);
  const ax = a[0] * kx;
  const ay = a[1] * M_PER_DEG;
  const bx = b[0] * kx;
  const by = b[1] * M_PER_DEG;
  const px = point[0] * kx;
  const py = point[1] * M_PER_DEG;
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy || 1;
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

function nearestWay(ways, anchor) {
  let best = null;
  let bestDistance = Infinity;
  for (const way of ways) {
    const line = way.geometry.map((point) => [point.lon, point.lat]);
    for (let i = 1; i < line.length; i++) {
      const distance = pointToSegmentMetres(anchor, line[i - 1], line[i]);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = way;
      }
    }
  }
  return best;
}

/** Line centred on the anchor's projection, clipped to `spanM` metres. */
function sliceLine(line, anchor, spanM) {
  const kx = mPerLng(anchor[1]);
  const x = (point) => point[0] * kx;
  const y = (point) => point[1] * M_PER_DEG;
  const px = x(anchor);
  const py = y(anchor);

  let total = 0;
  const segments = [];
  for (let i = 1; i < line.length; i++) {
    const ax = x(line[i - 1]);
    const ay = y(line[i - 1]);
    const bx = x(line[i]);
    const by = y(line[i]);
    const length = Math.hypot(bx - ax, by - ay);
    if (length === 0) continue;
    segments.push({ ax, ay, bx, by, length, start: total });
    total += length;
  }
  if (!segments.length) return [line[0], line[line.length - 1]];

  let bestDistance = Infinity;
  let bestArc = 0;
  for (const segment of segments) {
    const dx = segment.bx - segment.ax;
    const dy = segment.by - segment.ay;
    const t = Math.max(0, Math.min(1, ((px - segment.ax) * dx + (py - segment.ay) * dy) / (segment.length ** 2)));
    const distance = Math.hypot(px - (segment.ax + t * dx), py - (segment.ay + t * dy));
    if (distance < bestDistance) {
      bestDistance = distance;
      bestArc = segment.start + t * segment.length;
    }
  }

  const at = (arc) => {
    const clamped = Math.max(0, Math.min(total, arc));
    for (const segment of segments) {
      if (clamped <= segment.start + segment.length) {
        const t = (clamped - segment.start) / segment.length;
        return [segment.ax + t * (segment.bx - segment.ax), segment.ay + t * (segment.by - segment.ay)];
      }
    }
    const last = segments[segments.length - 1];
    return [last.bx, last.by];
  };

  const half = Math.min(spanM, total) / 2;
  const start = Math.max(0, bestArc - half);
  const end = Math.min(total, bestArc + half);
  const arcs = [0];
  for (const segment of segments) {
    const offset = segment.start - start;
    if (offset > 0 && offset < end - start) arcs.push(offset);
  }
  arcs.push(end - start);

  return [...new Set(arcs)].sort((a, b) => a - b)
    .map((offset) => at(start + offset))
    .map(([cx, cy]) => [round5(cx / kx), round5(cy / M_PER_DEG)]);
}

function resample(line, stepM) {
  if (line.length <= 2) return line;
  const points = [line[0]];
  let needed = stepM;
  for (let i = 1; i < line.length; i++) {
    let [ax, ay] = line[i - 1];
    const [bx, by] = line[i];
    let remaining = Math.hypot((bx - ax) * mPerLng(ay), (by - ay) * M_PER_DEG);
    while (remaining >= needed) {
      const t = needed / remaining;
      const nx = ax + (bx - ax) * t;
      const ny = ay + (by - ay) * t;
      points.push([round5(nx), round5(ny)]);
      ax = nx;
      ay = ny;
      remaining = Math.hypot((bx - ax) * mPerLng(ay), (by - ay) * M_PER_DEG);
      needed = stepM;
    }
    needed -= remaining;
  }
  const last = line[line.length - 1];
  const tail = points[points.length - 1];
  if (tail[0] !== last[0] || tail[1] !== last[1]) points.push(last);
  return points;
}

/** Thin polygon that follows the line, `halfWidthM` metres either side. */
function strip(line, halfWidthM) {
  if (line.length < 2) return null;
  const referenceLat = line[0][1];
  const kx = mPerLng(referenceLat);
  const xy = line.map(([lng, lat]) => [lng * kx, lat * M_PER_DEG]);
  const left = [];
  const right = [];
  for (let i = 0; i < xy.length; i++) {
    const previous = xy[Math.max(0, i - 1)];
    const next = xy[Math.min(xy.length - 1, i + 1)];
    let dx = next[0] - previous[0];
    let dy = next[1] - previous[1];
    const length = Math.hypot(dx, dy) || 1;
    dx /= length;
    dy /= length;
    left.push([xy[i][0] - dy * halfWidthM, xy[i][1] + dx * halfWidthM]);
    right.push([xy[i][0] + dy * halfWidthM, xy[i][1] - dx * halfWidthM]);
  }
  const ring = [...left, ...right.reverse(), left[0]];
  return ring.map(([cx, cy]) => [round5(cx / kx), round5(cy / M_PER_DEG)]);
}

function hashString(value) {
  let hash = 2166136261;
  for (const char of value) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

/** Deterministic straight segment at the anchor, used only when a street can't be resolved. */
function syntheticLine(id, anchor, spanM) {
  const bearing = ((hashString(id) % 360) * Math.PI) / 180;
  const dx = (Math.sin(bearing) * spanM) / 2;
  const dy = (Math.cos(bearing) * spanM) / 2;
  const kx = mPerLng(anchor[1]);
  const a = [round5(anchor[0] - dx / kx), round5(anchor[1] - dy / M_PER_DEG)];
  const b = [round5(anchor[0] + dx / kx), round5(anchor[1] + dy / M_PER_DEG)];
  return [a, b];
}

async function geometryFor(id, geometry) {
  const anchor = geometry.anchor;
  if (geometry.kind === 'fixed') return { type: 'Point', coordinates: [round5(anchor[0]), round5(anchor[1])] };
  if (geometry.kind === 'area') return { type: 'Polygon', coordinates: [geometry.coords] };

  const ways = await waysFor(geometry);
  const way = nearestWay(ways, anchor);
  if (!way) {
    console.warn(`MISS ${id}: no street for ${JSON.stringify(geometry.street ?? geometry.ref)} near ${anchor}`);
  }
  if (geometry.kind === 'point') {
    if (!way) return { type: 'Point', coordinates: [round5(anchor[0]), round5(anchor[1])] };
    const line = way.geometry.map((point) => [point.lon, point.lat]);
    const [point] = sliceLine(line, anchor, 1);
    return { type: 'Point', coordinates: point };
  }

  const full = way ? way.geometry.map((point) => [point.lon, point.lat]) : syntheticLine(id, anchor, geometry.span);
  const sliced = sliceLine(full, anchor, geometry.span);
  if (geometry.kind === 'band') {
    const polygon = strip(resample(sliced, 90), geometry.halfWidth ?? 28);
    if (polygon) return { type: 'Polygon', coordinates: [polygon] };
  }
  return { type: 'LineString', coordinates: resample(sliced, 60) };
}

// ---------------------------------------------------------------- Catalog helpers

const T = (hhmm, day = BASE) => `${day}T${hhmm}:00-04:00`;
const NOW = {
  tides: T('08:55'),
  nws: T('08:58'),
  here: T('08:57'),
  news: T('08:45'),
  city: T('06:00'),
  crowd: T('08:20'),
  osm: T('03:00'),
};
const PASS_S1 = '2026-09-27T07:14:00-04:00';
const PASS_S2 = '2026-09-24T12:02:00-04:00';
const NEWS_URLS = {
  NBC6: 'https://www.nbcmiami.com/',
  'Local 10': 'https://www.local10.com/',
  WLRN: 'https://www.wlrn.org/',
  CBS: 'https://www.cbsnews.com/miami/',
  Herald: 'https://www.miamiherald.com/',
};

const S = {
  tide: (label) => ({ kind: 'tides', label, url: null, observed_at: NOW.tides }),
  nws: (label) => ({ kind: 'nws', label, url: 'https://api.weather.gov/alerts/active?point=25.7617,-80.1918', observed_at: NOW.nws }),
  here: (label) => ({ kind: 'here', label, url: null, observed_at: NOW.here }),
  city: (label) => ({ kind: 'city_gis', label, url: null, observed_at: NOW.city }),
  county: (label) => ({ kind: 'county', label, url: null, observed_at: NOW.city }),
  osm: () => ({ kind: 'osm', label: 'OpenStreetMap: sidewalk=no', url: 'https://www.openstreetmap.org/', observed_at: NOW.osm }),
  crowd: (count, observedAt = NOW.crowd) => ({
    kind: 'crowd', label: `${count} report${count === 1 ? '' : 's'} from Mapay users`, url: null, observed_at: observedAt,
  }),
  '311': (label) => ({ kind: '311', label: `Miami-Dade 311: ${label}`, url: null, observed_at: null }),
  news: (outlet, label) => ({ kind: 'news', label: `${outlet}: ${label}`, url: NEWS_URLS[outlet] ?? null, observed_at: NOW.news }),
  gfm: () => ({ kind: 'gfm', label: 'Sentinel-1 flood map (Copernicus GFM)', url: null, observed_at: null, pass_time: PASS_S1 }),
  s2: (label) => ({ kind: 's2', label: `Sentinel-2: ${label}`, url: null, observed_at: null, pass_time: PASS_S2 }),
  ticketmaster: (label) => ({ kind: 'ticketmaster', label: `Ticketmaster: ${label}`, url: 'https://www.ticketmaster.com/', observed_at: NOW.city }),
};

const L = (street, anchor, span = 260) => ({ kind: 'line', street, anchor, span });
const LRef = (ref, anchor, span = 280) => ({ kind: 'line', ref, anchor, span });
const B = (street, anchor, span = 280, halfWidth = 28) => ({ kind: 'band', street, anchor, span, halfWidth });
const BRef = (ref, anchor, span = 300, halfWidth = 30) => ({ kind: 'band', ref, anchor, span, halfWidth });
const P = (street, anchor) => ({ kind: 'point', street, anchor });
const PRef = (ref, anchor) => ({ kind: 'point', ref, anchor });
const A = (coords) => ({ kind: 'area', coords });
const F = (lng, lat) => ({ kind: 'fixed', anchor: [lng, lat] });

const H = (id, type, title, place, severity, probability, status, geometry, sources, extra = {}) => ({
  id, type, title, place, severity, probability, status, geometry, sources, extra,
});

const CATALOG = [];
const add = (...entries) => CATALOG.push(...entries);

// ---------------------------------------------------------------- Flood (18)

add(
  H('flood:brickell-bay-dr', 'flood', 'Flooding expected', 'Brickell Bay Dr', 3, 0.81, 'predicted',
    B('Brickell Bay Drive', [-80.1892, 25.7605], 260, 30),
    [S.tide('King tide 1.9 ft over the minor-flood level + FEMA zone AE')],
    { last_updated: NOW.tides }),
  H('flood:ne-151st-st', 'flood', 'Flooded street', 'NE 151st St near BBC', 3, 0.88, 'observed',
    B('Northeast 151st Street', [-80.1405, 25.9085], 300, 26),
    [S.gfm(), S.crowd(2)],
    { last_updated: NOW.crowd }),
  H('flood:sunset-harbour', 'flood', 'Flooding expected', 'Sunset Harbour, Alton Rd', 3, 0.77, 'predicted',
    B('Alton Road', [-80.1438, 25.7925], 240, 28),
    [S.tide('King tide 1.7 ft over the minor-flood level at Sunset Harbour')],
    { last_updated: NOW.tides }),
  H('flood:shorecrest', 'flood', 'Flooding expected', 'NE 79th St, Shorecrest', 3, 0.72, 'predicted',
    B('Northeast 79th Street', [-80.1705, 25.8525], 260, 26),
    [S.tide('Tide 1.5 ft over the minor-flood level + onshore wind')],
    { last_updated: NOW.tides }),
  H('flood:coconut-grove', 'flood', 'Flooding expected', 'South Bayshore Dr, Coconut Grove', 2, 0.68, 'predicted',
    B('South Bayshore Drive', [-80.2405, 25.727], 260, 26),
    [S.tide('King tide + rain, FEMA zone AE along the Grove waterfront')],
    { last_updated: NOW.tides }),
  H('flood:south-miami', 'flood', 'Flooding expected', 'SW 57th Ave at Sunset Dr', 2, 0.64, 'predicted',
    B('Southwest 57th Avenue', [-80.2895, 25.7045], 240, 24),
    [S.tide('Tide 1.3 ft over the minor-flood level in South Miami')],
    { last_updated: NOW.tides }),
  H('flood:fiu-mmc', 'flood', 'Flooded street', 'SW 8th St at SW 107th Ave (FIU)', 3, 0.79, 'observed',
    B('Southwest 8th Street', [-80.3735, 25.7563], 220, 24),
    [S.crowd(3), S.news('Local 10', 'street flooding reported near the FIU entrance')],
    { last_updated: NOW.crowd }),
  H('flood:little-havana', 'flood', 'Flooded street', 'SW 8th St at SW 22nd Ave', 3, 0.74, 'observed',
    B('Southwest 8th Street', [-80.228, 25.7655], 260, 24),
    [S.crowd(4), S.tide('High tide still 0.8 ft over the minor-flood level')],
    { last_updated: NOW.crowd }),
  H('flood:miami-beach', 'flood', 'Flooding expected', 'Alton Rd at 10th St, Miami Beach', 3, 0.7, 'predicted',
    B('Alton Road', [-80.1415, 25.7805], 240, 26),
    [S.tide('King tide + full moon perigean cycle, FEMA zone AE')],
    { last_updated: NOW.tides }),
  H('flood:key-biscayne', 'flood', 'Flooding expected', 'Crandon Blvd, Key Biscayne', 2, 0.6, 'predicted',
    B('Crandon Boulevard', [-80.1575, 25.6935], 240, 24),
    [S.tide('Tide 1.2 ft over the minor-flood level at the Rickenbacker')],
    { last_updated: NOW.tides }),
  H('flood:edgewater', 'flood', 'Flooded street', 'Biscayne Blvd at NE 26th St', 2, 0.44, 'unconfirmed',
    B('Biscayne Boulevard', [-80.1865, 25.797], 240, 24),
    [S.crowd(1, T('08:05'))],
    { last_updated: T('08:05') }),
  H('flood:cutler-bay', 'flood', 'Flooding expected', 'Old Cutler Rd at SW 184th St', 2, 0.58, 'predicted',
    B('Old Cutler Road', [-80.318, 25.588], 240, 24),
    [S.tide('Rain on saturated ground, FEMA zone AE')],
    { last_updated: NOW.tides }),
  H('flood:homestead', 'flood', 'Flooded street', 'US-1 near SW 344th St', 2, 0.66, 'observed',
    B('South Dixie Highway', [-80.475, 25.474], 240, 24),
    [S.news('CBS', 'heavy rain flooded US-1 south of Homestead')],
    { last_updated: NOW.news }),
  H('flood:kendall', 'flood', 'Flooded street', 'SW 104th St at SW 117th Ave', 2, 0.62, 'observed',
    B('Southwest 104th Street', [-80.3545, 25.6765], 240, 24),
    [S.crowd(2, T('07:55'))],
    { last_updated: T('07:55') }),
  H('flood:westchester', 'flood', 'Flooding expected', 'Coral Way at SW 87th Ave', 2, 0.55, 'predicted',
    B('Southwest 24th Street', [-80.3355, 25.7475], 240, 24),
    [S.tide('Rain + tide, low-lying FEMA zone AE in Westchester')],
    { last_updated: NOW.tides }),
  H('flood:downtown', 'flood', 'Flooding expected', 'SE 2nd Ave at SE 1st St', 3, 0.63, 'predicted',
    B('Southeast 2nd Avenue', [-80.191, 25.7695], 220, 26),
    [S.tide('King tide 1.6 ft over the minor-flood level downtown')],
    { last_updated: NOW.tides }),
  H('flood:gables', 'flood', 'Flooding expected', 'Ponce de Leon Blvd at Alcazar Ave', 2, 0.52, 'predicted',
    B('Ponce de Leon Boulevard', [-80.259, 25.7425], 240, 24),
    [S.tide('Tide 1.1 ft over the minor-flood level, low-lying blocks')],
    { last_updated: NOW.tides }),
  H('flood:wynwood', 'flood', 'Flooded street', 'NW 2nd Ave at NW 24th St', 2, 0.38, 'unconfirmed',
    B('Northwest 2nd Avenue', [-80.199, 25.8005], 220, 22),
    [S.crowd(1, T('07:40'))],
    { last_updated: T('07:40') }),
);

// ---------------------------------------------------------------- Weather (3)

add(
  H('weather:nws-flood-advisory', 'weather', 'Flood advisory', 'North Miami-Dade', 2, 0.9, 'observed',
    A([[-80.3, 25.86], [-80.13, 25.86], [-80.12, 25.895], [-80.17, 25.97], [-80.29, 25.955], [-80.3, 25.86]]),
    [S.nws('NWS Miami: Coastal Flood Advisory until 1 PM')],
    { last_updated: NOW.nws, expires_at: T('13:00') }),
  H('weather:nws-flash-flood-watch', 'weather', 'Flash flood watch', 'Southwest Miami-Dade', 3, 0.55, 'observed',
    A([[-80.42, 25.6], [-80.3, 25.585], [-80.26, 25.65], [-80.28, 25.72], [-80.38, 25.73], [-80.42, 25.6]]),
    [S.nws('NWS Miami: Flash Flood Watch until 8 PM')],
    { last_updated: NOW.nws, expires_at: T('20:00') }),
  H('weather:nws-high-surf', 'weather', 'High surf advisory', 'Miami Beach and Key Biscayne', 1, 0.92, 'observed',
    A([[-80.14, 25.68], [-80.115, 25.68], [-80.115, 25.87], [-80.135, 25.87], [-80.14, 25.68]]),
    [S.nws('NWS Miami: High Surf Advisory until 7 PM')],
    { last_updated: NOW.nws, expires_at: T('19:00') }),
);

// ---------------------------------------------------------------- Construction (24)

add(
  // Active roadworks (HERE / City / County).
  H('construction:sr-826-nb-sw-8th', 'construction', 'Lane closures', 'SR-826 NB at SW 8th St', 3, 0.82, 'observed',
    B('Palmetto Expressway', [-80.333, 25.775], 300, 26),
    [S.here('HERE roadworks: two lanes closed on SR-826 NB at SW 8th St')],
    { last_updated: NOW.here }),
  H('construction:sr-826-sb-bird', 'construction', 'Lane closures', 'SR-826 SB at Bird Rd', 3, 0.78, 'observed',
    B('Palmetto Expressway', [-80.331, 25.7315], 280, 24),
    [S.here('HERE roadworks: shoulder and one lane closed on SR-826 SB')],
    { last_updated: NOW.here }),
  H('construction:ne-135th-st', 'construction', 'Construction', 'Biscayne Blvd & NE 135th St', 2, 0.8, 'observed',
    B('Northeast 135th Street', [-80.161, 25.9025], 260, 28),
    [S.city('Roadway project, status: active'), S.s2('new site on the NE 135th St rebuild, confirmed by Gemini')],
    { last_updated: NOW.city }),
  H('construction:ne-151st-bbc', 'construction', 'Roadwork', 'NE 151st St at the BBC entrance', 2, 0.75, 'observed',
    B('Northeast 151st Street', [-80.147, 25.908], 240, 26),
    [S.here('HERE roadworks: turn-lane work at the campus entrance')],
    { last_updated: NOW.here }),
  H('construction:i95-nb-79th', 'construction', 'Lane closures', 'I-95 NB near NW 79th St', 4, 0.83, 'observed',
    BRef(I95_REF, [-80.181, 25.85], 320, 30),
    [S.here('HERE roadworks: two lanes closed on I-95 NB overnight')],
    { last_updated: NOW.here }),
  H('construction:i95-sb-downtown', 'construction', 'Lane closures', 'I-95 SB near NW 8th St', 3, 0.72, 'observed',
    BRef(I95_REF, [-80.1905, 25.785], 300, 30),
    [S.here('HERE roadworks: barrier work on I-95 SB at the downtown curve')],
    { last_updated: NOW.here }),
  H('construction:us1-nb-kendall', 'construction', 'Lane closures', 'US-1 NB at Kendall Dr', 3, 0.8, 'observed',
    B('South Dixie Highway', [-80.302, 25.687], 300, 26),
    [S.county('Miami-Dade: bus-rapid-transit lane work on US-1')],
    { last_updated: NOW.city }),
  H('construction:us1-south-miami', 'construction', 'Construction', 'US-1 at SW 57th Ave', 3, 0.77, 'observed',
    B('South Dixie Highway', [-80.2885, 25.705], 260, 26),
    [S.county('Miami-Dade: repaving and signal work on US-1')],
    { last_updated: NOW.city }),
  H('construction:coral-way-westchester', 'construction', 'Roadwork', 'Coral Way at SW 87th Ave', 2, 0.74, 'observed',
    B('Southwest 24th Street', [-80.3355, 25.7475], 260, 24),
    [S.city('Roadway project: Coral Way drainage upgrades')],
    { last_updated: NOW.city }),
  H('construction:sw-8th-havana', 'construction', 'Lane closures', 'SW 8th St at SW 27th Ave', 3, 0.8, 'observed',
    B('Southwest 8th Street', [-80.239, 25.765], 280, 26),
    [S.city('Partial lane closure for curb and sidewalk work')],
    { last_updated: NOW.city }),
  H('construction:brickell-ave', 'construction', 'Roadwork', 'Brickell Ave at SE 13th St', 2, 0.76, 'observed',
    B('Brickell Avenue', [-80.1915, 25.757], 240, 24),
    [S.city('Lane shift for streetscape work on Brickell Ave')],
    { last_updated: NOW.city }),
  H('construction:biscayne-wynwood', 'construction', 'Lane closures', 'Biscayne Blvd at NE 29th St', 3, 0.79, 'observed',
    B('Biscayne Boulevard', [-80.190, 25.806], 280, 26),
    [S.here('HERE roadworks: crane placement on Biscayne Blvd')],
    { last_updated: NOW.here }),
  H('construction:nw-7th-st', 'construction', 'Roadwork', 'NW 7th St near NW 22nd Ave', 2, 0.71, 'observed',
    B('Northwest 7th Street', [-80.232, 25.777], 260, 24),
    [S.county('Miami-Dade: water-main replacement under NW 7th St')],
    { last_updated: NOW.city }),
  H('construction:okeechobee-hialeah', 'construction', 'Lane closures', 'Okeechobee Rd at W 12th Ave', 3, 0.81, 'observed',
    B('Okeechobee Road', [-80.289, 25.854], 300, 26),
    [S.here('HERE roadworks: intersection rebuild on Okeechobee Rd')],
    { last_updated: NOW.here }),
  H('construction:nw-36th-doral', 'construction', 'Roadwork', 'NW 36th St near NW 87th Ave', 3, 0.78, 'observed',
    B('Northwest 36th Street', [-80.3375, 25.8075], 280, 26),
    [S.county('Miami-Dade: widening work on NW 36th St')],
    { last_updated: NOW.city }),
  H('construction:nw-41st-doral', 'construction', 'Roadwork', 'NW 41st St near NW 107th Ave', 2, 0.73, 'observed',
    B('Northwest 41st Street', [-80.365, 25.812], 260, 24),
    [S.city('Doral: median and lighting work on NW 41st St')],
    { last_updated: NOW.city }),
  H('construction:collins-beach', 'construction', 'Roadwork', 'Collins Ave at 41st St', 2, 0.8, 'observed',
    B('Collins Avenue', [-80.126, 25.81], 240, 22),
    [S.city('Miami Beach: sidewalk and drainage work on Collins Ave')],
    { last_updated: NOW.city }),
  // Satellite-confirmed sites (Sentinel-2 change detection + Gemini vision).
  H('construction:s2-bbc-lot', 'construction', 'Satellite-confirmed construction', 'NE 151st St at Biscayne Blvd', 3, 0.88, 'observed',
    B('Northeast 151st Street', [-80.142, 25.9095], 240, 34),
    [S.s2('new cleared lot detected by change detection, confirmed by Gemini'), S.city('matching City permit nearby')],
    { last_updated: NOW.city }),
  H('construction:s2-sw-107th', 'construction', 'Satellite-confirmed construction', 'SW 107th Ave at SW 8th St', 3, 0.86, 'observed',
    B('Southwest 107th Avenue', [-80.3735, 25.7555], 200, 30),
    [S.s2('grading at the FIU edge detected by NDVI change, confirmed by Gemini'), S.city('matching County permit nearby')],
    { last_updated: NOW.city }),
  // Planned City of Miami roadway projects: below the unconfirmed threshold, street level only.
  H('city:permit:sw-107th-16th', 'construction', 'Planned roadwork', 'SW 107th Ave at SW 16th St', 1, 0.25, 'unconfirmed',
    B('Southwest 107th Avenue', [-80.373, 25.762], 220, 22),
    [S.city('Planned roadway project: resurfacing, status: planned')],
    { last_updated: NOW.city }),
  H('city:permit:sw-8th-112th', 'construction', 'Planned roadwork', 'SW 8th St at SW 112th Ave', 1, 0.32, 'unconfirmed',
    B('Southwest 8th Street', [-80.362, 25.756], 220, 22),
    [S.city('Planned roadway project: milling and resurfacing')],
    { last_updated: NOW.city }),
  H('city:permit:sw-27th-coral-way', 'construction', 'Planned roadwork', 'SW 27th Ave at Coral Way', 1, 0.28, 'unconfirmed',
    B('Southwest 27th Avenue', [-80.239, 25.75], 220, 22),
    [S.city('Planned roadway project: intersection upgrades')],
    { last_updated: NOW.city }),
  H('city:permit:brickell-se-13th', 'construction', 'Planned roadwork', 'Brickell Ave at SE 13th St', 1, 0.22, 'unconfirmed',
    B('Brickell Avenue', [-80.193, 25.762], 200, 20),
    [S.city('Planned roadway project: streetscape, status: planned')],
    { last_updated: NOW.city }),
  H('city:permit:nw-21st-2nd-ave', 'construction', 'Planned roadwork', 'NW 21st St at NW 2nd Ave', 1, 0.35, 'unconfirmed',
    B('Northwest 21st Street', [-80.199, 25.7955], 200, 20),
    [S.city('Planned roadway project: signal and curb work')],
    { last_updated: NOW.city }),
);

// ---------------------------------------------------------------- Closure (9)

add(
  H('closure:sw-8th-st-17th-ave', 'closure', 'Road closed', 'SW 8th St at SW 17th Ave', 4, 0.95, 'observed',
    L('Southwest 8th Street', [-80.219, 25.7655], 240),
    [S.here('HERE incident: road closed for event setup')],
    { last_updated: NOW.here, expires_at: T('18:00') }),
  H('closure:sr-826-nb-bird-rd', 'closure', 'Lanes closed on SR-826 NB at Bird Rd', 'SR-826 NB at Bird Rd', 3, 0.9, 'observed',
    L('Palmetto Expressway', [-80.3305, 25.7315], 260),
    [S.here('HERE incident: two lanes closed for emergency repairs')],
    { last_updated: NOW.here, expires_at: null }),
  H('closure:i95-sb-us1-ramp', 'closure', 'Ramp closed on I-95 SB to US-1', 'I-95 SB at the US-1 exit', 4, 0.88, 'observed',
    LRef(I95_REF, [-80.1905, 25.7725], 220),
    [S.here('HERE incident: exit ramp closed for barrier repair')],
    { last_updated: NOW.here, expires_at: T('15:00') }),
  H('closure:us1-sb-62nd', 'closure', 'Road closed on US-1 SB at SW 62nd Ave', 'US-1 SB at SW 62nd Ave', 4, 0.92, 'observed',
    L('South Dixie Highway', [-80.292, 25.702], 240),
    [S.city('Full closure for repaving, detour posted')],
    { last_updated: NOW.city, expires_at: T('17:00') }),
  H('closure:ne-151st-biscayne', 'closure', 'Road closed at Biscayne Blvd', 'NE 151st St at Biscayne Blvd', 4, 0.85, 'observed',
    L('Northeast 151st Street', [-80.153, 25.9085], 220),
    [S.news('Local 10', 'NE 151st St closed at Biscayne Blvd because of flooding')],
    { last_updated: NOW.news, expires_at: T('12:00') }),
  H('closure:alton-17th-overnight', 'closure', 'Overnight closure on Alton Rd at 17th St', 'Alton Rd at 17th St', 3, 0.9, 'observed',
    L('Alton Road', [-80.1435, 25.789], 220),
    [S.city('Overnight utility work, signed detour')],
    { last_updated: NOW.city, expires_at: T('06:00', '2026-09-29') }),
  H('closure:us1-344th', 'closure', 'Road closed on US-1 near SW 344th St', 'US-1 near SW 344th St, Homestead', 5, 0.87, 'observed',
    L('South Dixie Highway', [-80.475, 25.474], 240),
    [S.news('CBS', 'crash closes US-1 in both directions near SW 344th St')],
    { last_updated: NOW.news, expires_at: T('11:30') }),
  H('closure:grand-ave-festival', 'closure', 'Grand Ave closed for the street festival', 'Grand Ave at Main Hwy, Coconut Grove', 2, 0.9, 'observed',
    L('Grand Avenue', [-80.2405, 25.7275], 200),
    [S.city('Street festival setup: full closure until late')],
    { last_updated: NOW.city, expires_at: T('22:00') }),
  H('closure:nw-2nd-ave-crane', 'closure', 'NW 2nd Ave closed for crane work', 'NW 2nd Ave at NW 24th St', 3, 0.93, 'observed',
    L('Northwest 2nd Avenue', [-80.199, 25.8005], 200),
    [S.city('Full closure for tower-crane assembly')],
    { last_updated: NOW.city, expires_at: T('16:00') }),
);

// ---------------------------------------------------------------- Congestion (19)

const G = (id, title, place, level, ratio, severity, probability, geometry, flow) =>
  H(id, 'congestion', title, place, severity, probability, 'observed', geometry, [S.here(flow)],
    { last_updated: NOW.here, level, ratio });

add(
  G('congestion:sr-826-nb-flagler', 'Heavy traffic', 'SR-826 northbound near Flagler St', 'heavy', 0.65, 3, 0.9,
    L('Palmetto Expressway', [-80.332, 25.777], 300), 'HERE flow: 18 mph vs 55 mph free flow'),
  G('congestion:sr-826-sb-bird', 'Heavy traffic', 'SR-826 southbound at Bird Rd', 'heavy', 0.6, 3, 0.88,
    L('Palmetto Expressway', [-80.331, 25.732], 280), 'HERE flow: 24 mph vs 55 mph free flow'),
  G('congestion:palmetto-mmc', 'Heavy traffic', 'SR-826 near SW 8th St, by MMC', 'heavy', 0.62, 3, 0.86,
    L('Palmetto Expressway', [-80.3325, 25.755], 280), 'HERE flow: 21 mph vs 55 mph free flow'),
  G('congestion:i95-nb-125th', 'Slow traffic', 'I-95 northbound at NE 125th St', 'moderate', 0.4, 2, 0.82,
    LRef(I95_REF, [-80.177, 25.884], 300), 'HERE flow: 31 mph vs 60 mph free flow'),
  G('congestion:i95-sb-downtown', 'Severe traffic', 'I-95 southbound near the downtown curve', 'severe', 0.82, 4, 0.91,
    LRef(I95_REF, [-80.191, 25.779], 280), 'HERE flow: 11 mph vs 55 mph free flow'),
  G('congestion:i95-nb-ives', 'Severe traffic', 'I-95 northbound at Ives Dairy Rd', 'severe', 0.78, 4, 0.89,
    LRef(I95_REF, [-80.170, 25.925], 300), 'HERE flow: 13 mph vs 60 mph free flow'),
  G('congestion:us1-nb-south-miami', 'Heavy traffic', 'US-1 NB at SW 57th Ave', 'heavy', 0.58, 3, 0.87,
    L('South Dixie Highway', [-80.288, 25.706], 260), 'HERE flow: 16 mph vs 45 mph free flow'),
  G('congestion:us1-sb-kendall', 'Severe traffic', 'US-1 SB at Kendall Dr', 'severe', 0.75, 4, 0.9,
    L('South Dixie Highway', [-80.302, 25.688], 280), 'HERE flow: 12 mph vs 45 mph free flow'),
  G('congestion:us1-nb-dadeland', 'Slow traffic', 'US-1 NB near Dadeland', 'moderate', 0.38, 2, 0.8,
    L('South Dixie Highway', [-80.300, 25.66], 260), 'HERE flow: 28 mph vs 45 mph free flow'),
  G('congestion:sw-8th-27th', 'Heavy traffic', 'SW 8th St at SW 27th Ave', 'heavy', 0.6, 3, 0.85,
    L('Southwest 8th Street', [-80.239, 25.765], 280), 'HERE flow: 14 mph vs 35 mph free flow'),
  G('congestion:coral-way-gables', 'Slow traffic', 'Coral Way at SW 42nd Ave', 'moderate', 0.42, 2, 0.78,
    L('Southwest 24th Street', [-80.257, 25.748], 260), 'HERE flow: 22 mph vs 35 mph free flow'),
  G('congestion:brickell-ave-se7th', 'Severe traffic', 'Brickell Ave at SE 7th St', 'severe', 0.8, 4, 0.92,
    L('Brickell Avenue', [-80.192, 25.759], 240), 'HERE flow: 8 mph vs 30 mph free flow'),
  G('congestion:biscayne-downtown', 'Heavy traffic', 'Biscayne Blvd at NE 6th St', 'heavy', 0.63, 3, 0.88,
    L('Biscayne Boulevard', [-80.189, 25.786], 260), 'HERE flow: 15 mph vs 35 mph free flow'),
  G('congestion:alton-17th', 'Slow traffic', 'Alton Rd at 17th St', 'moderate', 0.35, 2, 0.76,
    L('Alton Road', [-80.142, 25.7895], 240), 'HERE flow: 19 mph vs 30 mph free flow'),
  G('congestion:okeechobee-hialeah', 'Heavy traffic', 'Okeechobee Rd at W 12th Ave', 'heavy', 0.6, 3, 0.84,
    L('Okeechobee Road', [-80.29, 25.8535], 280), 'HERE flow: 17 mph vs 45 mph free flow'),
  G('congestion:nw-36th-doral', 'Slow traffic', 'NW 36th St near NW 87th Ave', 'moderate', 0.4, 2, 0.8,
    L('Northwest 36th Street', [-80.338, 25.8075], 260), 'HERE flow: 20 mph vs 35 mph free flow'),
  G('congestion:ne-151st-bbc', 'Slow traffic', 'NE 151st St at Biscayne Blvd', 'moderate', 0.36, 2, 0.75,
    L('Northeast 151st Street', [-80.146, 25.908], 240), 'HERE flow: 16 mph vs 30 mph free flow'),
  G('congestion:sr-836-nw57', 'Severe traffic', 'SR-836 WB before NW 57th Ave', 'severe', 0.84, 4, 0.91,
    L('Dolphin Expressway', [-80.34, 25.783], 300), 'HERE flow: 10 mph vs 50 mph free flow'),
  G('congestion:kendall-dr-137', 'Slow traffic', 'Kendall Dr at SW 137th Ave', 'moderate', 0.34, 2, 0.77,
    L('Southwest 88th Street', [-80.3405, 25.6795], 260), 'HERE flow: 21 mph vs 35 mph free flow'),
);

// ---------------------------------------------------------------- Potholes (18)

add(
  H('pothole:311-corridor-sw-8th', 'pothole', 'Chronic potholes', 'SW 8th St near SW 107th Ave', 1, 0.62, 'predicted',
    P('Southwest 8th Street', [-80.373, 25.7565]), [S['311']('7 complaints/km (2023)')], { last_updated: NOW.city }),
  H('pothole:311-sw-107th-ave', 'pothole', 'Chronic potholes', 'SW 107th Ave near SW 12th St', 1, 0.4, 'predicted',
    P('Southwest 107th Avenue', [-80.3725, 25.765]), [S['311']('5 complaints/km (2023)')], { last_updated: NOW.city }),
  H('pothole:311-sw-24th-st', 'pothole', 'Chronic potholes', 'Coral Way at SW 87th Ave', 1, 0.55, 'predicted',
    P('Southwest 24th Street', [-80.335, 25.7475]), [S['311']('6 complaints/km (2023)')], { last_updated: NOW.city }),
  H('pothole:311-kendall-dr', 'pothole', 'Chronic potholes', 'Kendall Dr at SW 137th Ave', 1, 0.45, 'predicted',
    P('Southwest 88th Street', [-80.3405, 25.6795]), [S['311']('4 complaints/km (2023)')], { last_updated: NOW.city }),
  H('pothole:311-us1-south-miami', 'pothole', 'Chronic potholes', 'US-1 at SW 57th Ave', 1, 0.6, 'predicted',
    P('South Dixie Highway', [-80.288, 25.7045]), [S['311']('9 complaints/km (2023)')], { last_updated: NOW.city }),
  H('pothole:311-sw-8th-27th', 'pothole', 'Chronic potholes', 'SW 8th St at SW 27th Ave', 1, 0.58, 'predicted',
    P('Southwest 8th Street', [-80.239, 25.765]), [S['311']('8 complaints/km (2023)')], { last_updated: NOW.city }),
  H('pothole:311-flagler-27th', 'pothole', 'Chronic potholes', 'W Flagler St at SW 27th Ave', 1, 0.52, 'predicted',
    P('West Flagler Street', [-80.240, 25.7735]), [S['311']('6 complaints/km (2023)')], { last_updated: NOW.city }),
  H('pothole:311-brickell-ave', 'pothole', 'Chronic potholes', 'Brickell Ave at SE 10th St', 1, 0.55, 'predicted',
    P('Brickell Avenue', [-80.193, 25.765]), [S['311']('5 complaints/km (2023)')], { last_updated: NOW.city }),
  H('pothole:311-biscayne-79th', 'pothole', 'Chronic potholes', 'Biscayne Blvd at NE 79th St', 1, 0.57, 'predicted',
    P('Biscayne Boulevard', [-80.172, 25.854]), [S['311']('7 complaints/km (2023)')], { last_updated: NOW.city }),
  H('pothole:311-alton-rd', 'pothole', 'Chronic potholes', 'Alton Rd at 41st St', 1, 0.53, 'predicted',
    P('Alton Road', [-80.1415, 25.798]), [S['311']('6 complaints/km (2023)')], { last_updated: NOW.city }),
  H('pothole:311-okeechobee', 'pothole', 'Chronic potholes', 'Okeechobee Rd at W 12th Ave', 1, 0.6, 'predicted',
    P('Okeechobee Road', [-80.289, 25.854]), [S['311']('10 complaints/km (2023)')], { last_updated: NOW.city }),
  H('pothole:311-nw-36th', 'pothole', 'Chronic potholes', 'NW 36th St near NW 87th Ave', 1, 0.42, 'predicted',
    P('Northwest 36th Street', [-80.3375, 25.8075]), [S['311']('5 complaints/km (2023)')], { last_updated: NOW.city }),
  H('pothole:311-ne-151st', 'pothole', 'Chronic potholes', 'NE 151st St at Biscayne Blvd', 1, 0.59, 'predicted',
    P('Northeast 151st Street', [-80.15, 25.9085]), [S['311']('6 complaints/km (2023)')], { last_updated: NOW.city }),
  H('pothole:311-coral-way', 'pothole', 'Chronic potholes', 'Coral Way at SW 42nd Ave', 1, 0.54, 'predicted',
    P('Southwest 24th Street', [-80.257, 25.748]), [S['311']('7 complaints/km (2023)')], { last_updated: NOW.city }),
  H('pothole:report-nw-2nd-ave', 'pothole', 'Pothole reported', 'NW 2nd Ave at NW 24th St', 1, 0.78, 'observed',
    P('Northwest 2nd Avenue', [-80.199, 25.801]), [S.crowd(1, T('07:58'))], { last_updated: T('07:58') }),
  H('pothole:report-collins', 'pothole', 'Pothole reported', 'Collins Ave at 71st St', 1, 0.72, 'observed',
    P('Collins Avenue', [-80.129, 25.79]), [S.crowd(1, T('07:32'))], { last_updated: T('07:32') }),
  H('pothole:report-grand-ave', 'pothole', 'Pothole reported', 'Grand Ave at Commodore Plaza', 1, 0.7, 'observed',
    P('Grand Avenue', [-80.2425, 25.7275]), [S.crowd(1, T('08:02'))], { last_updated: T('08:02') }),
  H('pothole:report-sw-104th', 'pothole', 'Pothole reported', 'SW 104th St at SW 117th Ave', 1, 0.74, 'observed',
    P('Southwest 104th Street', [-80.355, 25.6765]), [S.crowd(1, T('07:20'))], { last_updated: T('07:20') }),
);

// ---------------------------------------------------------------- Incidents (10)

add(
  H('incident:news-i95-nb-125th', 'incident', 'Crash blocks two lanes on I-95 NB at NE 125th St',
    'I-95 northbound near NE 125th St', 3, 0.7, 'observed',
    PRef(I95_REF, [-80.177, 25.884]),
    [S.news('NBC6', 'crash blocks two lanes on I-95 NB at NE 125th St')],
    { last_updated: NOW.news, expires_at: T('11:30') }),
  H('incident:news-sr826-nb-bird', 'incident', 'Crash blocks two lanes on SR-826 NB at Bird Rd',
    'SR-826 northbound at Bird Rd', 3, 0.72, 'observed',
    P('Palmetto Expressway', [-80.3305, 25.7315]),
    [S.news('Local 10', 'two lanes blocked after a crash on SR-826 NB at Bird Rd')],
    { last_updated: NOW.news, expires_at: T('11:45') }),
  H('incident:news-us1-sb-kendall', 'incident', 'Crash on US-1 SB at Kendall Dr', 'US-1 southbound at Kendall Dr', 3, 0.68, 'observed',
    P('South Dixie Highway', [-80.302, 25.688]),
    [S.news('CBS', 'crash slows US-1 SB at Kendall Dr')],
    { last_updated: NOW.news, expires_at: T('11:15') }),
  H('incident:news-brickell-ave', 'incident', 'Police activity on Brickell Ave at SE 8th St',
    'Brickell Ave at SE 8th St', 2, 0.48, 'unconfirmed',
    P('Brickell Avenue', [-80.1925, 25.760]),
    [S.news('NBC6', 'police activity closes one lane on Brickell Ave')],
    { last_updated: T('08:10'), expires_at: T('11:10') }),
  H('incident:news-biscayne-blvd', 'incident', 'Disabled vehicle blocking a lane on Biscayne Blvd NB',
    'Biscayne Blvd at NE 36th St', 2, 0.55, 'observed',
    P('Biscayne Boulevard', [-80.186, 25.797]),
    [S.news('WLRN', 'disabled vehicle blocking a lane on Biscayne Blvd NB')],
    { last_updated: T('08:28'), expires_at: T('11:28') }),
  H('incident:news-alton-rd', 'incident', 'Crash on Alton Rd at 17th St leaves one lane open',
    'Alton Rd at 17th St', 3, 0.74, 'observed',
    P('Alton Road', [-80.1425, 25.7895]),
    [S.news('Local 10', 'crash on Alton Rd at 17th St leaves one lane open')],
    { last_updated: NOW.news, expires_at: T('11:40') }),
  H('incident:news-okeechobee', 'incident', 'Multi-car crash on Okeechobee Rd near W 12th Ave',
    'Okeechobee Rd near W 12th Ave', 3, 0.77, 'observed',
    P('Okeechobee Road', [-80.2895, 25.854]),
    [S.news('NBC6', 'multi-car crash delays Okeechobee Rd near W 12th Ave')],
    { last_updated: NOW.news, expires_at: T('12:00') }),
  H('incident:news-sw-8th-22nd', 'incident', 'Crash on SW 8th St at SW 22nd Ave', 'SW 8th St at SW 22nd Ave', 2, 0.65, 'observed',
    P('Southwest 8th Street', [-80.228, 25.7655]),
    [S.news('WLRN', 'crash blocks a lane on SW 8th St at SW 22nd Ave')],
    { last_updated: NOW.news, expires_at: T('11:20') }),
  H('incident:news-sr836-nw57', 'incident', 'Stalled truck blocking a lane on SR-836 WB before NW 57th Ave',
    'SR-836 WB before NW 57th Ave', 2, 0.58, 'observed',
    P('Dolphin Expressway', [-80.337, 25.783]),
    [S.news('CBS', 'stalled truck blocking a lane on SR-836 WB')],
    { last_updated: T('08:22'), expires_at: T('11:22') }),
  H('incident:news-us1-344th', 'incident', 'Crash closes a lane on US-1 near SW 344th St',
    'US-1 near SW 344th St, Homestead', 3, 0.7, 'observed',
    P('South Dixie Highway', [-80.474, 25.4745]),
    [S.news('Local 10', 'crash closes a lane on US-1 near SW 344th St')],
    { last_updated: NOW.news, expires_at: T('11:35') }),
);

// ---------------------------------------------------------------- Events (6)

add(
  H('event:kaseya-center-2026-09-28', 'event', 'Concert at Kaseya Center', 'Kaseya Center · doors 6:30 PM', 2, 0.95, 'observed',
    F(-80.1874, 25.7814),
    [S.ticketmaster('concert, doors 6:30 PM')],
    { last_updated: NOW.city, expires_at: T('23:30') }),
  H('event:arsht-center-2026-09-28', 'event', 'Performance at the Arsht Center', 'Adrienne Arsht Center · 8:00 PM', 1, 0.95, 'observed',
    F(-80.1878, 25.7868),
    [S.ticketmaster('performance, curtain 8:00 PM')],
    { last_updated: NOW.city, expires_at: T('22:30') }),
  H('event:loan-depot-park-2026-09-28', 'event', 'Baseball at loanDepot park', 'loanDepot park · 6:40 PM', 2, 0.95, 'observed',
    F(-80.2196, 25.7781),
    [S.ticketmaster('home game, first pitch 6:40 PM')],
    { last_updated: NOW.city, expires_at: T('23:00') }),
  H('event:miami-beach-convention-2026-09-29', 'event', 'Conference at the Miami Beach Convention Center',
    'Miami Beach Convention Center · 9:00 AM', 1, 0.95, 'observed',
    F(-80.1338, 25.7939),
    [S.ticketmaster('conference, doors 8:00 AM')],
    { last_updated: NOW.city, expires_at: T('17:00', '2026-09-29') }),
  H('event:calle-ocho-viernes-2026-10-02', 'event', 'Viernes Culturales on SW 8th St',
    'SW 8th St between 14th and 17th Ave · 6–10 PM', 2, 0.95, 'observed',
    F(-80.2195, 25.7655),
    [S.ticketmaster('street festival, Friday 6–10 PM')],
    { last_updated: NOW.city, expires_at: T('00:00', '2026-10-03') }),
  H('event:hard-rock-2026-10-03', 'event', 'College football at Hard Rock Stadium', 'Hard Rock Stadium · 3:30 PM', 3, 0.95, 'observed',
    F(-80.2389, 25.958),
    [S.ticketmaster('football, kickoff 3:30 PM')],
    { last_updated: NOW.city, expires_at: T('20:00', '2026-10-03') }),
);

// ---------------------------------------------------------------- No sidewalk (real OSM tags)

const SIDEWALK_TARGETS = [
  { anchor: [-80.374, 25.756], count: 8 },  // FIU MMC / SW 8th St
  { anchor: [-80.377, 25.765], count: 4 },  // Sweetwater
  { anchor: [-80.335, 25.748], count: 3 },  // Westchester
  { anchor: [-80.340, 25.680], count: 3 },  // Kendall
  { anchor: [-80.290, 25.705], count: 2 },  // South Miami
  { anchor: [-80.225, 25.767], count: 2 },  // Little Havana
  { anchor: [-80.290, 25.855], count: 2 },  // Hialeah
  { anchor: [-80.338, 25.808], count: 2 },  // Doral
  { anchor: [-80.170, 25.890], count: 2 },  // North Miami
  { anchor: [-80.130, 25.790], count: 2 },  // Miami Beach
];

async function noSidewalkFeatures() {
  const query = `[out:json][timeout:240];way["highway"]["sidewalk"~"^(no|none)$"](${METRO});out geom;`;
  const result = await overpass(query);
  const ways = (result.elements ?? [])
    .filter((way) => Array.isArray(way.geometry) && way.geometry.length >= 2)
    .map((way) => ({
      id: way.id,
      name: way.tags?.name ?? null,
      line: way.geometry.map((point) => [point.lon, point.lat]),
    }));

  const used = new Set();
  const features = [];
  for (const target of SIDEWALK_TARGETS) {
    const candidates = ways
      .filter((way) => !used.has(way.id))
      .map((way) => ({
        way,
        distance: Math.min(...way.line.slice(1).map((point, index) =>
          pointToSegmentMetres(target.anchor, way.line[index], point))),
        named: way.name ? 0 : 1,
      }))
      .sort((a, b) => a.named - b.named || a.distance - b.distance);
    for (const { way, distance } of candidates.slice(0, target.count)) {
      if (distance > 4000) break;
      used.add(way.id);
      const span = 140 + (hashString(String(way.id)) % 3) * 40;
      const sliced = sliceLine(way.line, target.anchor, span);
      const severity = hashString(`sev${way.id}`) % 4 === 0 ? 2 : 1;
      features.push(H(`no_sidewalk:osm-way-${way.id}`, 'no_sidewalk', 'No sidewalk',
        way.name ?? 'Unnamed street', severity, 0.95, 'observed',
        { kind: 'line', anchor: target.anchor, span, _sliced: sliced },
        [S.osm()],
        { last_updated: NOW.osm }));
    }
  }
  return features;
}

// ---------------------------------------------------------------- Build & write

const CATEGORIES = ['flood', 'weather', 'construction', 'closure', 'congestion', 'no_sidewalk', 'pothole', 'incident', 'event'];
const COLLECTIONS = new Map(CATEGORIES.map((category) => [category, []]));

function featureFor(entry, geometry) {
  const properties = {
    hazard_id: entry.id,
    hazard_type: entry.type,
    title: entry.title,
    place: entry.place,
    probability: entry.probability,
    status: entry.status,
    severity: entry.severity,
    sources: entry.sources,
    last_updated: entry.extra.last_updated ?? NOW.tides,
    expires_at: entry.extra.expires_at ?? null,
  };
  if (entry.type === 'congestion') {
    properties.level = entry.extra.level;
    properties.ratio = entry.extra.ratio;
  }
  return { type: 'Feature', geometry, properties };
}

async function main() {
  const sidewalk = await noSidewalkFeatures();
  const entries = [...CATALOG, ...sidewalk];

  const geometryCache = new Map();
  for (const entry of entries) {
    if (COLLECTIONS.get(entry.type)) continue;
    throw new Error(`Unknown category for ${entry.id}: ${entry.type}`);
  }

  // Warm the Overpass cache in batches before resolving one street at a time.
  const allNames = [...new Set(entries.flatMap((entry) => [].concat(entry.geometry.street ?? [])))];
  await namedWays(allNames);
  for (const ref of new Set(entries.map((entry) => entry.geometry.ref).filter(Boolean))) await refWays(ref);
  console.log(`resolved ${allNames.length} street names and ${refCache.size} refs`);

  for (const entry of entries) {
    if (entry.geometry._sliced) {
      geometryCache.set(entry.id, { type: 'LineString', coordinates: entry.geometry._sliced });
      continue;
    }
    geometryCache.set(entry.id, await geometryFor(entry.id, entry.geometry));
  }

  const seen = new Set();
  for (const entry of entries) {
    if (seen.has(entry.id)) throw new Error(`Duplicate hazard id: ${entry.id}`);
    seen.add(entry.id);
    COLLECTIONS.get(entry.type).push(featureFor(entry, geometryCache.get(entry.id)));
  }

  const layers = {
    t: T('09:00'),
    freshness: {
      tides: NOW.tides,
      nws: NOW.nws,
      here: NOW.here,
      news: NOW.news,
      gfm: PASS_S1,
      s2: PASS_S2,
      city_gis: NOW.city,
      osm: NOW.osm,
    },
    radar: {
      type: 'xyz',
      url_template: 'https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913/{z}/{x}/{y}.png',
      attribution: 'NOAA/NWS NEXRAD composite via Iowa Environmental Mesonet',
      min_zoom: 0,
      max_zoom: 12,
      tile_size: 256,
      opacity: 0.6,
    },
  };
  for (const category of CATEGORIES) {
    layers[category] = { type: 'FeatureCollection', features: COLLECTIONS.get(category) };
  }

  writeFileSync(OUT_FILE, `${JSON.stringify(layers, null, 2)}\n`);

  console.log('Wrote', OUT_FILE);
  for (const category of CATEGORIES) {
    console.log(String(COLLECTIONS.get(category).length).padStart(4), category);
  }
  const bytes = readFileSync(OUT_FILE).length;
  console.log(`size ${(bytes / 1024).toFixed(0)} KB`);

  // The demo route mocks must only reference hazards that exist on the map.
  const references = new Set();
  for (const file of ['route.json', 'customize.json', 'routines-upcoming.json']) {
    const raw = readFileSync(resolve(HERE, '..', 'public', 'mocks', file), 'utf8');
    for (const match of raw.matchAll(/"hazard_id":\s*"([^"]+)"/g)) references.add(match[1]);
  }
  const missing = [...references].filter((id) => !seen.has(id));
  console.log(`route mocks reference ${references.size} hazard ids; missing from layers.json: ${missing.length ? missing.join(', ') : 'none'}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
