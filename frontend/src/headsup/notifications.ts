import { useEffect } from 'react';
import { App as CapacitorApp } from '@capacitor/app';
import { Capacitor } from '@capacitor/core';
import { LocalNotifications, type LocalNotificationSchema } from '@capacitor/local-notifications';
import { Directory, Filesystem } from '@capacitor/filesystem';
import { api } from '../lib/api';
import type { UpcomingLeg } from '../lib/types';
import { openCustomize, startLeg } from './deeplinks';

// Heads-up notifications (#28, AGENTS.md › Pre-route heads-up › Local notifications). A free Apple ID
// can't receive server push, so the phone schedules one local notification per upcoming leg at
// `heads_up_at` and reschedules on launch, on resume and after routine edits.

const CATEGORY = 'HEADS_UP';
const DAYS = 7; // iOS keeps up to 64 pending notifications; a weekday routine with two legs needs 10
export const ROUTINES_CHANGED = 'mapay:routines-changed';

const isNative = () => Capacitor.isNativePlatform();

/** `routine:leg:date`, the stable key that makes rescheduling replace a leg's notification. */
const legKey = (leg: UpcomingLeg) => `${leg.routine_id}:${leg.leg}:${leg.local_date}`;

/** Local notification ids are 32-bit ints, so hash the key (FNV-1a, positive). */
function notificationId(key: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 1) || 1;
}

export async function notificationsAllowed() {
  if (!isNative()) return false;
  return (await LocalNotifications.checkPermissions()).display === 'granted';
}

/** Asks for permission; call it from a user gesture (a button). Schedules right away when granted. */
export async function enableHeadsUpNotifications() {
  if (!isNative()) return false;
  const { display } = await LocalNotifications.requestPermissions();
  if (display !== 'granted') return false;
  await scheduleHeadsUps();
  return true;
}

let actionTypesRegistered = false;
async function registerActionTypes() {
  if (actionTypesRegistered) return;
  await LocalNotifications.registerActionTypes({
    types: [{
      id: CATEGORY,
      actions: [
        { id: 'start', title: 'Start', foreground: true },
        { id: 'customize', title: 'Customize', foreground: true },
      ],
    }],
  });
  actionTypesRegistered = true;
}

/** The route image (signed Static Maps URL) downloaded to the cache, as a file:// URL. */
async function routeImage(leg: UpcomingLeg): Promise<string | undefined> {
  if (!leg.image_url) return undefined;
  try {
    const path = `heads-up/${notificationId(legKey(leg))}.png`;
    await Filesystem.downloadFile({ url: leg.image_url, path, directory: Directory.Cache, recursive: true });
    return (await Filesystem.getUri({ path, directory: Directory.Cache })).uri;
  } catch (err) {
    console.warn('[mapay] route image', err);
    return undefined;
  }
}

async function toNotification(leg: UpcomingLeg, at: Date): Promise<LocalNotificationSchema> {
  const minutes = Math.round((new Date(leg.departure_at).getTime() - new Date(leg.heads_up_at).getTime()) / 60000);
  const hazards = leg.top_hazards.slice(0, 2).map(h => h.title);
  const image = await routeImage(leg);
  return {
    id: notificationId(legKey(leg)),
    title: `${leg.from.name} → ${leg.to.name} · leave in ${minutes} min`,
    body: hazards.length ? hazards.join(' · ') : `No hazards on the route · ${Math.round(leg.duration_s / 60)} min trip`,
    schedule: { at, allowWhileIdle: true },
    actionTypeId: CATEGORY,
    threadIdentifier: 'heads-up',
    extra: { routineId: leg.routine_id, leg: leg.leg, key: legKey(leg) },
    attachments: image ? [{ id: 'route', url: image }] : undefined,
  };
}

/** Replaces the pending heads-ups with one per upcoming leg (by id); drops ones that no longer exist. */
export async function scheduleHeadsUps() {
  if (!(await notificationsAllowed())) return;
  await registerActionTypes();
  const now = Date.now();
  const { items } = await api.upcomingRoutines(DAYS);
  const upcoming = items.filter(leg => new Date(leg.heads_up_at).getTime() > now);
  const wanted = new Set(upcoming.map(leg => notificationId(legKey(leg))));

  const { notifications: pending } = await LocalNotifications.getPending();
  const stale = pending.filter(n => n.extra?.key && !wanted.has(n.id));
  if (stale.length) await LocalNotifications.cancel({ notifications: stale.map(n => ({ id: n.id })) });

  const scheduled = await Promise.all(upcoming.map(leg => toNotification(leg, new Date(leg.heads_up_at))));
  if (scheduled.length) await LocalNotifications.schedule({ notifications: scheduled });
}

/** Demo / testing (mapay://demo/heads-up): the next leg's heads-up, delivered 5 s from now. */
export async function scheduleDemoHeadsUp(delayMs = 5000) {
  if (!(await notificationsAllowed()) && !(await enableHeadsUpNotifications())) return;
  await registerActionTypes();
  const { items } = await api.upcomingRoutines(DAYS);
  if (!items.length) return;
  const notification = await toNotification(items[0], new Date(Date.now() + delayMs));
  await LocalNotifications.schedule({ notifications: [{ ...notification, id: notification.id ^ 1 }] });
}

/** Reschedules on launch, on resume and after routine edits; routes the Start / Customize actions. */
export function useHeadsUpNotifications() {
  useEffect(() => {
    if (!isNative()) return;
    const reschedule = () => scheduleHeadsUps().catch(err => console.warn('[mapay] notifications', err));
    reschedule();
    window.addEventListener(ROUTINES_CHANGED, reschedule);
    const listeners = [
      CapacitorApp.addListener('appStateChange', ({ isActive }) => { if (isActive) reschedule(); }),
      LocalNotifications.addListener('localNotificationActionPerformed', ({ actionId, notification }) => {
        const { routineId, leg } = (notification.extra ?? {}) as { routineId?: string; leg?: number };
        if (actionId === 'start') startLeg(routineId, leg).catch(err => console.warn('[mapay] start', err));
        else if (actionId === 'customize') openCustomize(routineId, leg);
        // A plain tap just opens the app, whose foreground sync starts the Live Activity.
      }),
    ];
    return () => {
      window.removeEventListener(ROUTINES_CHANGED, reschedule);
      listeners.forEach(l => l.then(h => h.remove()));
    };
  }, []);
}
