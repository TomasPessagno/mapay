import { useEffect } from 'react';
import { App as CapacitorApp } from '@capacitor/app';
import { api } from '../lib/api';
import { openLink } from '../lib/deepLinks';
import { endLiveActivity, markLegStarted } from './liveActivity';
import { scheduleDemoHeadsUp } from './notifications';

// mapay:// deep links (custom URL scheme; universal links need Associated Domains, which free signing lacks).
//   mapay://start?routine=…&leg=…      Start from the notification, widget or Live Activity
//   mapay://customize?routine=…&leg=…  the Customize sheet (App.tsx listens for it)
//   mapay://demo/heads-up              fires the next leg's heads-up notification in 5 s

/** Start: end the heads-up and hand off to the leg's Google Maps link. */
export async function startLeg(routineId?: string, leg?: number) {
  const { items } = await api.upcomingRoutines(7);
  const match = items.find(i => i.routine_id === routineId && i.leg === leg);
  markLegStarted(routineId, leg, match?.local_date);
  await endLiveActivity(routineId, leg);
  const nav = match?.deep_links.google_maps ?? match?.deep_links.apple_maps;
  if (nav) await openLink(nav);
}

/** Opens the Customize sheet (App.tsx listens for this event, like mapay://customize). */
export function openCustomize(routineId?: string, leg?: number) {
  window.dispatchEvent(new CustomEvent('open-customize', { detail: { routineId, legIndex: leg } }));
}

export function parseLeg(params: URLSearchParams) {
  return {
    routineId: params.get('routine') ?? undefined,
    leg: params.has('leg') ? Number(params.get('leg')) : undefined,
  };
}

export function useDeepLinks() {
  useEffect(() => {
    const listener = CapacitorApp.addListener('appUrlOpen', ({ url }) => {
      const parsed = new URL(url);
      const { routineId, leg } = parseLeg(parsed.searchParams);
      if (parsed.host === 'start') startLeg(routineId, leg).catch(err => console.warn('[mapay] start', err));
      if (parsed.host === 'demo' && parsed.pathname === '/heads-up') scheduleDemoHeadsUp().catch(err => console.warn('[mapay] demo', err));
    });
    return () => { listener.then(h => h.remove()); };
  }, []);
}
