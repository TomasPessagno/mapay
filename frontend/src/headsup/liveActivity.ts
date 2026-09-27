import { api } from '../lib/api';
import { isDemo } from '../lib/dataSource';
import { isDemoRoutine } from '../lib/demoRoutines';
import { MapayNative, isNativeIOS } from '../lib/native';
import type { UpcomingLeg } from '../lib/types';
import { departureMs, planHeadsUp, soonestLiveActivity, type HeadsUpCandidate } from './schedule';

// The heads-up Live Activity (#37). ActivityKit only starts one while the app is in the foreground
// (no push with a free Apple ID), so it's (re)started whenever the app opens within 8 h of a leg —
// and right after a routine is saved (#126, refreshHeadsUps).

const LINGER_MS = 10 * 60 * 1000; // it stays up until departure + 10 min
// Demo data (its fixed times are days away): the countdown owner departs 30 min after the banner
// starts. The countdown is kept across foregrounds, but nothing is remembered as "started": the demo
// banner comes back on every launch and foreground (Start just resets the countdown for the next one).
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
/** The demo leg's departure (Demo data): the banner's countdown, which the demo notification follows. */
export const demoDeparture = (now = Date.now()) => mockDeparture(now);
/** A new 30-min demo countdown ("Fire heads-up now"). */
export function freshDemoDeparture(now = Date.now()) {
  resetMockDeparture();
  return mockDeparture(now);
}

// The leg "Fire heads-up now" picked in Demo mode, so the foreground sync keeps showing that one.
const DEMO_LEG_KEY = 'mapay_demo_leg';
export function setDemoLeg(leg: UpcomingLeg) {
  try { localStorage.setItem(DEMO_LEG_KEY, `${leg.routine_id}:${leg.leg}`); } catch { /* private mode */ }
}
/** The fired demo leg, if it's still upcoming. */
function demoLeg(items: UpcomingLeg[]) {
  let key: string | null = null;
  try { key = localStorage.getItem(DEMO_LEG_KEY); } catch { /* private mode */ }
  return items.find(leg => `${leg.routine_id}:${leg.leg}` === key);
}
function resetMockDeparture() {
  try { localStorage.removeItem(MOCK_KEY); } catch { /* private mode */ }
}

/** The leg the fresh demo countdown runs on: the one "Fire heads-up now" picked, else the mock leg. */
export function demoCountdownLeg(items: UpcomingLeg[]): UpcomingLeg | undefined {
  return demoLeg(items) ?? items.find(leg => !isDemoRoutine(leg.routine_id));
}

/**
 * Demo mode's banner candidates: the countdown owner departs at the fresh 30-min countdown, while a
 * routine the user created in Demo mode departs at its own time. The soonest one wins the banner,
 * so the built-in mock leg can't fight a user routine over the one Live Activity.
 */
export function demoWinner(items: UpcomingLeg[], countdownMs: number, now = Date.now()): HeadsUpCandidate | undefined {
  const owner = demoCountdownLeg(items);
  const candidates: HeadsUpCandidate[] = [];
  for (const leg of items) {
    if (owner && leg === owner) {
      candidates.push({ leg, departureMs: countdownMs });
      continue;
    }
    if (!isDemoRoutine(leg.routine_id)) continue;
    if (planHeadsUp(leg, now).liveActivity) candidates.push({ leg, departureMs: departureMs(leg) });
  }
  return soonestLiveActivity(candidates, now);
}

const isAvailable = isNativeIOS;

export function startLiveActivity(leg: UpcomingLeg, departure = departureMs(leg)) {
  if (!isAvailable()) return Promise.resolve();
  const top = leg.top_hazards[0];
  return MapayNative.startLiveActivity({
    routineId: leg.routine_id,
    leg: leg.leg,
    fromName: leg.from.name,
    toName: leg.to.name,
    departureMs: departure,
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

/** Starts (or updates) the Live Activity for the next leg departing within 8 h; ends it when there's none. */
export async function syncLiveActivity(items?: UpcomingLeg[]) {
  if (!isAvailable()) return;
  const legs = items ?? (await api.upcomingRoutines(1)).items;
  const now = Date.now();
  // Demo data (Preferences › Data): the mock's fixed times are days away, so the countdown owner
  // runs on the debug departure while user-created routines keep their own times (soonest wins).
  if (isDemo()) {
    const winner = demoWinner(legs, mockDeparture(now), now);
    return winner ? startLiveActivity(winner.leg, winner.departureMs) : endLiveActivity();
  }
  const candidates: HeadsUpCandidate[] = legs
    .filter(leg => !wasStarted(leg))
    .filter(leg => planHeadsUp(leg, now).liveActivity)
    .map(leg => ({ leg, departureMs: departureMs(leg) }));
  const winner = soonestLiveActivity(candidates, now);
  return winner ? startLiveActivity(winner.leg) : endLiveActivity();
}

/** Called on Start. Live: the next foreground sync won't bring this leg's banner back. Demo: the banner
 * comes back on the next launch or foreground, with a fresh countdown. */
export function markLegStarted(routineId?: string, leg?: number, localDate?: string) {
  if (isDemo()) resetMockDeparture();
  else markStarted(legKey(routineId, leg, localDate));
}
