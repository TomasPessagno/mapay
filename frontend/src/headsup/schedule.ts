import type { UpcomingLeg } from '../lib/types';

// The pure heads-up decision (#126): given a leg and "now", what should happen to its notification
// and its Live Activity? Kept free of Capacitor and localStorage so it's unit-testable and shared by
// the notification scheduler, the Live Activity sync and the save toast.

/** ActivityKit keeps one Live Activity up for at most 8 h. */
export const LIVE_ACTIVITY_WINDOW_MS = 8 * 60 * 60 * 1000;
/** The banner stays up until departure + 10 min (MapayNativePlugin.swift). */
export const DEPARTURE_LINGER_MS = 10 * 60 * 1000;
/** "Fire the notification now" lands a few seconds out, enough to reach the Lock Screen. */
export const FIRE_NOW_DELAY_MS = 5_000;

export type HeadsUpAction = 'notify-now' | 'notify' | 'none';

export interface HeadsUpPlan {
  action: HeadsUpAction;
  /** Epoch ms to schedule the notification at; null when there's nothing to send. */
  notifyAt: number | null;
  /** Whether the Live Activity should start right now (it starts on open within the window otherwise). */
  liveActivity: boolean;
  /** Departure + linger already passed: no notification, no banner. */
  expired: boolean;
}

/** The leg's departure: the best time inside a window when the backend suggested one. */
export function departureMs(leg: UpcomingLeg): number {
  return new Date(leg.best_departure_at ?? leg.departure_at).getTime();
}

export function headsUpMs(leg: UpcomingLeg): number {
  return new Date(leg.heads_up_at).getTime();
}

/**
 * - inside the heads-up window (heads_up_at ≤ now < departure_at): notify a few seconds out, banner now;
 * - later today / within 8 h: notify at heads_up_at, banner now (so it's on the Lock Screen when the
 *   app is closed right after saving);
 * - beyond 8 h: notify at heads_up_at, wait for the app to open inside the window;
 * - already departed: no notification; keep the banner until departure + linger.
 *
 * `departureOverrideMs` lets Demo mode run the built-in mock leg on its fresh 30-min countdown.
 */
export function planHeadsUp(leg: UpcomingLeg, now = Date.now(), departureOverrideMs?: number): HeadsUpPlan {
  const departure = departureOverrideMs ?? departureMs(leg);
  if (departure + DEPARTURE_LINGER_MS <= now) {
    return { action: 'none', notifyAt: null, liveActivity: false, expired: true };
  }
  if (departure <= now) {
    return { action: 'none', notifyAt: null, liveActivity: true, expired: false };
  }
  if (headsUpMs(leg) <= now) {
    return { action: 'notify-now', notifyAt: now + FIRE_NOW_DELAY_MS, liveActivity: true, expired: false };
  }
  return {
    action: 'notify',
    notifyAt: headsUpMs(leg),
    liveActivity: departure - now <= LIVE_ACTIVITY_WINDOW_MS,
    expired: false,
  };
}

export interface HeadsUpCandidate {
  leg: UpcomingLeg;
  departureMs: number;
}

/** The leg that owns the one Live Activity: the soonest departure still inside the window. */
export function soonestLiveActivity(candidates: HeadsUpCandidate[], now = Date.now()): HeadsUpCandidate | undefined {
  return candidates
    .filter(c => c.departureMs + DEPARTURE_LINGER_MS > now && c.departureMs - now <= LIVE_ACTIVITY_WINDOW_MS)
    .sort((a, b) => a.departureMs - b.departureMs)[0];
}

/** "3:30 PM" for today, "Mon 9:00 AM" otherwise. */
export function formatClock(ms: number, now = Date.now()): string {
  const date = new Date(ms);
  const sameDay = new Date(now).toDateString() === date.toDateString();
  return new Intl.DateTimeFormat(undefined, sameDay
    ? { hour: 'numeric', minute: '2-digit' }
    : { weekday: 'short', hour: 'numeric', minute: '2-digit' }).format(date);
}

/** The toast shown after saving a routine (#126). */
export function headsUpToast(leg: UpcomingLeg, plan: HeadsUpPlan, now = Date.now()): string | null {
  if (plan.action === 'notify-now') return `Heads-up now · leave at ${formatClock(departureMs(leg), now)}`;
  if (plan.action === 'notify' && plan.notifyAt !== null) return `Heads-up scheduled for ${formatClock(plan.notifyAt, now)}`;
  return null;
}
