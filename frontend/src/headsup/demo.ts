import { api } from '../lib/api';
import { isDemo } from '../lib/dataSource';
import { reloadWidgets } from '../lib/native';
import type { UpcomingLeg } from '../lib/types';
import { freshDemoDeparture, setDemoLeg, startLiveActivity } from './liveActivity';
import { markDemoNotified, scheduleDemoHeadsUp } from './notifications';

// "Fire heads-up now" (#36, AGENTS.md › Pre-route heads-up › Demo): the whole heads-up on cue.
// The leg's Live Activity starts right away, its notification arrives 10 s later (time to lock the
// phone), the widget reloads and the in-app card switches to heads-up mode.
//   Live data: POST /demo/heads-up makes the leg due in heads_up_minutes on the backend first.
//   Demo data: the mock's times are fixed, so the leg is shifted onto a fresh 30-min countdown.

export const DEMO_HEADS_UP = 'mapay:demo-heads-up';
export interface DemoHeadsUpDetail { leg: UpcomingLeg }

const NOTIFY_IN_MS = 10_000;

// The last fired leg, for a map sheet that mounts after the event (switching to the Map tab remounts it).
let lastFired: UpcomingLeg | null = null;
export const lastFiredHeadsUp = () => lastFired;

const at = (iso: string, offsetMs: number) => new Date(new Date(iso).getTime() + offsetMs).toISOString();

/** The leg moved in time so it departs at `departureMs` (heads-up, window and best time move with it). */
function shiftedTo(leg: UpcomingLeg, departureMs: number): UpcomingLeg {
  const offset = departureMs - new Date(leg.best_departure_at ?? leg.departure_at).getTime();
  return {
    ...leg,
    departure_at: at(leg.departure_at, offset),
    heads_up_at: at(leg.heads_up_at, offset),
    best_departure_at: leg.best_departure_at && at(leg.best_departure_at, offset),
    window: leg.window && { start: at(leg.window.start, offset), end: at(leg.window.end, offset) },
  };
}

const sameLeg = (pick?: { routineId: string; leg: number }) => (leg: UpcomingLeg) =>
  !pick || (leg.routine_id === pick.routineId && leg.leg === pick.leg);

/** Fires the heads-up for a leg (default: the next one). Resolves with the leg as it's now shown. */
export async function fireHeadsUpNow(pick?: { routineId: string; leg: number }): Promise<UpcomingLeg | undefined> {
  const { items } = await api.upcomingRoutines(7);
  let leg = items.find(sameLeg(pick));
  if (!leg) return undefined;

  if (isDemo()) {
    const departure = freshDemoDeparture();
    leg = shiftedTo(leg, departure);
    setDemoLeg(leg);
    markDemoNotified(departure); // the notification below is this countdown's
  } else {
    await api.demoHeadsUp(leg.routine_id, leg.leg);
    leg = (await api.upcomingRoutines(7)).items.find(sameLeg({ routineId: leg.routine_id, leg: leg.leg })) ?? leg;
  }

  lastFired = leg;
  window.dispatchEvent(new CustomEvent<DemoHeadsUpDetail>(DEMO_HEADS_UP, { detail: { leg } }));
  const warn = (what: string) => (err: unknown) => console.warn(`[mapay] demo ${what}`, err);
  await Promise.all([
    startLiveActivity(leg).catch(warn('Live Activity')), // also ends any other leg's
    scheduleDemoHeadsUp(NOTIFY_IN_MS, leg).catch(warn('notification')),
    reloadWidgets(),
  ]);
  return leg;
}
