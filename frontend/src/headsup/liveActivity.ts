import { useEffect } from 'react';
import { App as CapacitorApp } from '@capacitor/app';
import { api } from '../lib/api';
import { isDemo } from '../lib/dataSource';
import { openLink } from '../lib/deepLinks';
import { MapayNative, isNativeIOS } from '../lib/native';
import type { UpcomingLeg } from '../lib/types';

// The heads-up Live Activity (#37). ActivityKit only starts one while the app is in the foreground
// (no push with a free Apple ID), so it's (re)started whenever the app opens within 8 h of a leg.

const WINDOW_MS = 8 * 60 * 60 * 1000; // ActivityKit keeps one up for at most 8 h
const LINGER_MS = 10 * 60 * 1000; // it stays up until departure + 10 min
// Demo data (its fixed times are days away): the first leg departs 30 min after the banner starts.
// The countdown is kept across foregrounds, but nothing is remembered as "started": the demo banner
// comes back on every launch and foreground (Start just resets the countdown for the next one).
const MOCK_DEPARTS_IN_MS = 30 * 60 * 1000;
const MOCK_KEY = 'mapay_mock_departure';
function mockDeparture(now: number): number {
  try {
    const saved = Number(localStorage.getItem(MOCK_KEY));
    if (saved && saved + LINGER_MS > now) return saved;
  } catch { /* private mode */ }
  const fresh = now + MOCK_DEPARTS_IN_MS;
  try { localStorage.setItem(MOCK_KEY, String(fresh)); } catch { /* private mode */ }
  return fresh;
}
function resetMockDeparture() {
  try { localStorage.removeItem(MOCK_KEY); } catch { /* private mode */ }
}

const isAvailable = isNativeIOS;

const departureOf = (leg: UpcomingLeg) => new Date(leg.best_departure_at ?? leg.departure_at).getTime();

// Legs the user already pressed Start on, so the next foreground sync doesn't bring the banner back.
const STARTED_KEY = 'mapay_started_legs';
const legKey = (routineId?: string, leg?: number, localDate?: string) => `${routineId}:${leg}:${localDate ?? ''}`;
function startedLegs(): string[] {
  try { return JSON.parse(localStorage.getItem(STARTED_KEY) ?? '[]'); } catch { return []; }
}
function markStarted(key: string) {
  try { localStorage.setItem(STARTED_KEY, JSON.stringify([...startedLegs(), key].slice(-20))); } catch { /* private mode */ }
}
const wasStarted = (leg: UpcomingLeg) => startedLegs().includes(legKey(leg.routine_id, leg.leg, leg.local_date));

export function startLiveActivity(leg: UpcomingLeg, departureMs = departureOf(leg)) {
  if (!isAvailable()) return Promise.resolve();
  const top = leg.top_hazards[0];
  return MapayNative.startLiveActivity({
    routineId: leg.routine_id,
    leg: leg.leg,
    fromName: leg.from.name,
    toName: leg.to.name,
    departureMs,
    durationMin: Math.round(leg.duration_s / 60),
    summary: leg.summary,
    hazardCount: leg.top_hazards.length,
    topHazardType: top?.hazard_type,
    topHazardTitle: top?.title,
  }).then(() => undefined);
}

export function endLiveActivity(routineId?: string, leg?: number) {
  if (!isAvailable()) return Promise.resolve();
  return MapayNative.endLiveActivity({ routineId, leg });
}

/** Starts (or updates) the Live Activity for the next leg departing within 8 h; ends it when there's none. */
export async function syncLiveActivity() {
  if (!isAvailable()) return;
  const { items } = await api.upcomingRoutines(1);
  const now = Date.now();
  // Demo data (Preferences › Data): the mock's fixed times are days away, so use the debug departure.
  if (isDemo()) {
    return items.length ? startLiveActivity(items[0], mockDeparture(now)) : endLiveActivity();
  }
  const next = items
    .filter(leg => !wasStarted(leg))
    .filter(leg => departureOf(leg) + LINGER_MS > now && departureOf(leg) - now < WINDOW_MS)
    .sort((a, b) => departureOf(a) - departureOf(b))[0];
  return next ? startLiveActivity(next) : endLiveActivity();
}

/** mapay://start?routine=…&leg=… (the Live Activity's Start): end the heads-up and hand off to navigation. */
async function handleStart(url: URL) {
  const routineId = url.searchParams.get('routine') ?? undefined;
  const leg = url.searchParams.has('leg') ? Number(url.searchParams.get('leg')) : undefined;
  const { items } = await api.upcomingRoutines(1);
  const match = items.find(i => i.routine_id === routineId && i.leg === leg);
  if (isDemo()) resetMockDeparture();
  else markStarted(legKey(routineId, leg, match?.local_date));
  await endLiveActivity(routineId, leg);
  const nav = match?.deep_links.google_maps ?? match?.deep_links.apple_maps;
  if (nav) await openLink(nav);
}

/** Demo / testing (mapay://demo/heads-up, #36's button): a fresh demo banner with a 30-min countdown. */
export async function restartDemoLiveActivity() {
  if (!isAvailable()) return;
  resetMockDeparture();
  await endLiveActivity();
  const { items } = await api.upcomingRoutines(1);
  if (items.length) await startLiveActivity(items[0], mockDeparture(Date.now()));
}

/** Keeps the Live Activity in sync on launch and every time the app comes to the foreground. */
export function useLiveActivitySync() {
  useEffect(() => {
    if (!isAvailable()) return;
    const sync = () => syncLiveActivity().catch(err => console.warn('[mapay] Live Activity', err));
    sync();
    const listeners = [
      CapacitorApp.addListener('appStateChange', ({ isActive }) => { if (isActive) sync(); }),
      CapacitorApp.addListener('appUrlOpen', ({ url }) => {
        const parsed = new URL(url);
        if (parsed.host === 'start') handleStart(parsed).catch(err => console.warn('[mapay] start', err));
      }),
    ];
    return () => { listeners.forEach(l => l.then(h => h.remove())); };
  }, []);
}
