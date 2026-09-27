import { useEffect } from 'react';
import { App as CapacitorApp } from '@capacitor/app';
import { Capacitor } from '@capacitor/core';
import { LocalNotifications } from '@capacitor/local-notifications';
import { api } from '../lib/api';
import { reloadWidgets } from '../lib/native';
import type { UpcomingLeg } from '../lib/types';
import { openCustomize, startLeg } from './deeplinks';
import { syncLiveActivity } from './liveActivity';
import { ROUTINES_CHANGED, markHeadsUpFiredKey, scheduleHeadsUps } from './notifications';
import { departureMs, planHeadsUp, type HeadsUpPlan } from './schedule';

// One heads-up refresh (#126): reschedule notifications, re-sync the Live Activity and reload the
// widgets from a single fetch. Used on launch, on resume and after a routine is saved/edited/toggled.

const DAYS = 7;

export interface NextHeadsUp {
  leg: UpcomingLeg;
  plan: HeadsUpPlan;
}

export interface HeadsUpRefreshResult {
  /** The soonest covered leg (of the saved routine, when one is given): the save toast reads this. */
  next: NextHeadsUp | null;
}

// A save dispatches ROUTINES_CHANGED (api.saveRoutine) while the save hook also refreshes; share the
// fetch so both see the same upcoming legs.
let inFlight: Promise<UpcomingLeg[]> | null = null;
function upcomingOnce(): Promise<UpcomingLeg[]> {
  if (!inFlight) {
    inFlight = api.upcomingRoutines(DAYS)
      .then(res => res.items)
      .finally(() => { inFlight = null; });
  }
  return inFlight;
}

function soonestPlan(items: UpcomingLeg[]): NextHeadsUp | null {
  const now = Date.now();
  return items
    .map(leg => ({ leg, plan: planHeadsUp(leg, now) }))
    .filter(({ plan }) => plan.action !== 'none' || plan.liveActivity)
    .sort((a, b) => departureMs(a.leg) - departureMs(b.leg))[0] ?? null;
}

export async function refreshHeadsUps(options: { routineId?: string } = {}): Promise<HeadsUpRefreshResult> {
  // Everything below is native (notifications, Live Activities, widgets): no-op safely on web.
  if (!Capacitor.isNativePlatform()) return { next: null };
  const items = await upcomingOnce().catch(err => {
    console.warn('[mapay] heads-up refresh', err);
    return [] as UpcomingLeg[];
  });
  await Promise.all([
    scheduleHeadsUps(items).catch(err => console.warn('[mapay] notifications', err)),
    syncLiveActivity(items).catch(err => console.warn('[mapay] Live Activity', err)),
    reloadWidgets(),
  ]);
  const relevant = options.routineId ? items.filter(leg => leg.routine_id === options.routineId) : items;
  return { next: soonestPlan(relevant) };
}

/** Keeps the heads-up in sync on launch, on resume and after routine edits. */
export function useHeadsUpSync() {
  useEffect(() => {
    if (!Capacitor.isNativePlatform()) return;
    const sync = () => { refreshHeadsUps().catch(err => console.warn('[mapay] heads-up sync', err)); };
    sync();
    window.addEventListener(ROUTINES_CHANGED, sync);
    const listeners = [
      CapacitorApp.addListener('appStateChange', ({ isActive }) => { if (isActive) sync(); }),
      LocalNotifications.addListener('localNotificationActionPerformed', ({ actionId, notification }) => {
        const { routineId, leg, key, demo } = (notification.extra ?? {}) as
          { routineId?: string; leg?: number; key?: string; demo?: boolean };
        // Tapping the notification (or Start / Customize) used up this occurrence's heads-up.
        if (key && !demo) markHeadsUpFiredKey(key);
        if (actionId === 'start') startLeg(routineId, leg).catch(err => console.warn('[mapay] start', err));
        else if (actionId === 'customize') openCustomize(routineId, leg);
        // A plain tap just opens the app, whose foreground sync starts the Live Activity.
      }),
    ];
    return () => {
      window.removeEventListener(ROUTINES_CHANGED, sync);
      listeners.forEach(l => l.then(h => h.remove()));
    };
  }, []);
}
