import type { Place, Routine, RoutineLeg, UpcomingLeg } from './types';

// Demo mode (VITE_USE_MOCKS / Preferences › Data): the mock API can't store what the user creates,
// so routines and places saved in Demo mode live in localStorage and are merged into the mock
// responses. Upcoming occurrences are computed client-side from the routine's own times — the same
// rule as backend/app/scheduling/occurrences.py — so a Demo-mode routine still schedules its
// heads-up (#126) even though /routines/upcoming is a fixed mock file.

const ROUTINES_KEY = 'mapay_demo_routines';
const PLACES_KEY = 'mapay_demo_places';

const WEEKDAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
const DEFAULT_TZ = 'America/New_York';

function read<T>(key: string): T[] {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) as T[] : [];
  } catch {
    return []; // private mode / corrupted value
  }
}

function write<T>(key: string, items: T[]): void {
  try { localStorage.setItem(key, JSON.stringify(items)); } catch { /* private mode */ }
}

/** Routines saved in Demo mode; an entry shadows the mock routine with the same _id. */
export function demoRoutines(): Routine[] {
  return read<Routine>(ROUTINES_KEY);
}

export function isDemoRoutine(routineId: string): boolean {
  return demoRoutines().some(r => r._id === routineId);
}

export function saveDemoRoutine(routine: Routine): Routine {
  // The Map route's editor starts a routine with an empty _id; the store still needs a stable one.
  const saved = routine._id ? routine : { ...routine, _id: `new-${Date.now()}` };
  write(ROUTINES_KEY, [...demoRoutines().filter(r => r._id !== saved._id), saved]);
  return saved;
}

export function demoPlaces(): Place[] {
  return read<Place>(PLACES_KEY);
}

export function saveDemoPlace(place: Place): Place {
  write(PLACES_KEY, [...demoPlaces().filter(p => p._id !== place._id), place]);
  return place;
}

/** Mock routines with the locally saved (created or edited) ones shadowing same-id entries. */
export function mergeDemoRoutines(mock: Routine[]): Routine[] {
  const local = demoRoutines();
  const overridden = new Set(local.map(r => r._id));
  return [...mock.filter(r => !overridden.has(r._id)), ...local];
}

export function mergeDemoPlaces(mock: Place[]): Place[] {
  const local = demoPlaces();
  const overridden = new Set(local.map(p => p._id));
  return [...mock.filter(p => !overridden.has(p._id)), ...local];
}

/** Weekdays a leg runs on: its own `days`, else the routine's repeat rule (models.py › leg_days). */
export function legDays(routine: Routine, leg: RoutineLeg): string[] {
  if (leg.days && leg.days.length) return leg.days;
  if (routine.repeat.kind === 'weekly') return [routine.repeat.weekday ?? 'mon'];
  if (routine.repeat.kind === 'custom') return routine.repeat.weekdays ?? [];
  return WEEKDAYS;
}

interface ZonedParts { year: number; month: number; day: number; hour: number; minute: number; second: number }

function partsInTz(date: Date, tz: string): ZonedParts {
  const parts: Record<string, number> = {};
  for (const part of new Intl.DateTimeFormat('en-US', {
    timeZone: tz, hour12: false,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).formatToParts(date)) {
    if (part.type !== 'literal') parts[part.type] = Number(part.value);
  }
  return {
    year: parts.year, month: parts.month, day: parts.day,
    hour: parts.hour % 24, minute: parts.minute, second: parts.second,
  };
}

function tzOffsetMs(tz: string, at: Date): number {
  const p = partsInTz(at, tz);
  return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) - at.getTime();
}

/** `2026-09-28` in the routine's timezone. */
function dayInTz(now: Date, tz: string): string {
  const p = partsInTz(now, tz);
  return `${p.year}-${String(p.month).padStart(2, '0')}-${String(p.day).padStart(2, '0')}`;
}

function addDays(day: string, offset: number): string {
  const [y, m, d] = day.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + offset)).toISOString().slice(0, 10);
}

function weekdayOf(day: string): string {
  const [y, m, d] = day.split('-').map(Number);
  return WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
}

/** A wall-clock time on a local day in `tz` (two offset passes settle DST edges). */
function zonedTime(day: string, clock: string, tz: string): Date {
  const [y, m, d] = day.split('-').map(Number);
  const [hh, mm] = clock.split(':').map(Number);
  const guess = Date.UTC(y, m - 1, d, hh, mm);
  let at = new Date(guess);
  for (let i = 0; i < 2; i++) at = new Date(guess - tzOffsetMs(tz, at));
  return at;
}

function metersBetween(a: Place, b: Place): number {
  const [lng1, lat1] = a.location.coordinates;
  const [lng2, lat2] = b.location.coordinates;
  const rad = Math.PI / 180;
  const dLat = (lat2 - lat1) * rad;
  const dLng = (lng2 - lng1) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLng / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(h));
}

/** No routing for locally created demo routines: ~30 km/h across the straight line, 8-90 min. */
function durationEstimate(from?: Place, to?: Place): number {
  if (!from || !to) return 25 * 60;
  const minutes = Math.round((metersBetween(from, to) / 1000) * 2) + 5;
  return Math.min(Math.max(minutes, 8), 90) * 60;
}

function deepLinks(routine: Routine, leg: number, from?: Place, to?: Place): Record<string, string> {
  const links: Record<string, string> = {
    start: `mapay://start?routine=${encodeURIComponent(routine._id)}&leg=${leg}`,
    customize: `mapay://customize?routine=${encodeURIComponent(routine._id)}&leg=${leg}`,
  };
  if (from && to) {
    const origin = `${from.location.coordinates[1]},${from.location.coordinates[0]}`;
    const destination = `${to.location.coordinates[1]},${to.location.coordinates[0]}`;
    links.google_maps = `https://www.google.com/maps/dir/?${new URLSearchParams({ api: '1', origin, destination, travelmode: 'driving' })}`;
  }
  return links;
}

/** The next `days` occurrences of one routine's legs, soonest-first (heads-up = departure − setting). */
export function demoOccurrences(routine: Routine, places: Place[], now = new Date(), days = 7): UpcomingLeg[] {
  if (!routine.active) return [];
  const tz = routine.tz || DEFAULT_TZ;
  const headsUpMinutes = routine.heads_up_minutes || 30;
  const byId = new Map(places.map(p => [p._id, p]));
  const startDay = dayInTz(now, tz);
  const found: UpcomingLeg[] = [];

  routine.legs.forEach((leg, index) => {
    const days0 = legDays(routine, leg);
    const clock = leg.when.kind === 'at' ? leg.when.time : leg.when.start;
    if (!clock || !leg.from_place || !leg.to_place || days0.length === 0) return;
    for (let offset = 0; offset <= days; offset++) {
      const day = addDays(startDay, offset);
      if (!days0.includes(weekdayOf(day))) continue;
      const departure = zonedTime(day, clock, tz);
      if (departure.getTime() <= now.getTime()) continue;
      const from = byId.get(leg.from_place);
      const to = byId.get(leg.to_place);
      const duration = durationEstimate(from, to);
      found.push({
        routine_id: routine._id,
        routine_name: routine.name,
        leg: index,
        from: { place_id: leg.from_place, name: from?.name ?? leg.from_place },
        to: { place_id: leg.to_place, name: to?.name ?? leg.to_place },
        local_date: day,
        departure_at: departure.toISOString(),
        heads_up_at: new Date(departure.getTime() - headsUpMinutes * 60_000).toISOString(),
        window: leg.when.kind === 'window' && leg.when.end
          ? { start: departure.toISOString(), end: zonedTime(day, leg.when.end, tz).toISOString() }
          : null,
        best_departure_at: null,
        best_saving_s: null,
        duration_s: duration,
        static_duration_s: duration,
        summary: 'Estimated route',
        top_hazards: [],
        image_url: null,
        deep_links: deepLinks(routine, index, from, to),
      });
    }
  });

  return found;
}

/** Mock upcoming items, with locally created demo routines replacing their mock counterparts. */
export function mergeDemoUpcoming(mock: UpcomingLeg[], places: Place[], now = new Date(), days = 7): UpcomingLeg[] {
  const local = demoRoutines();
  const overridden = new Set(local.map(r => r._id));
  const generated = local.flatMap(r => demoOccurrences(r, places, now, days));
  return [...mock.filter(l => !overridden.has(l.routine_id)), ...generated]
    .sort((a, b) => new Date(a.departure_at).getTime() - new Date(b.departure_at).getTime());
}
