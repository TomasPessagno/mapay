import { Capacitor } from '@capacitor/core';
import { LocalNotifications, type LocalNotificationSchema } from '@capacitor/local-notifications';
import { Directory, Filesystem } from '@capacitor/filesystem';
import { api } from '../lib/api';
import { isDemo } from '../lib/dataSource';
import { isDemoRoutine } from '../lib/demoRoutines';
import type { UpcomingLeg } from '../lib/types';
import { demoDeparture, demoWinner } from './liveActivity';
import { planHeadsUp } from './schedule';

// Heads-up notifications (#28, AGENTS.md › Pre-route heads-up › Local notifications). A free Apple ID
// can't receive server push, so the phone schedules one local notification per upcoming leg:
// at `heads_up_at`, or a few seconds out when the heads-up window already started (#126).

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

// Demo data: the mock's fixed times are days away, so the demo notification follows the demo banner
// instead. Every fresh countdown (first launch, or the launch after Start) delivers it 5 s later.
const DEMO_NOTIFIED_KEY = 'mapay_demo_notified_departure';

async function scheduleDemoHeadsUpForBanner(items: UpcomingLeg[]) {
  const { display } = await LocalNotifications.checkPermissions();
  // Ask on launch in Demo mode so the demo doesn't depend on finding the Preferences toggle.
  if (display !== 'granted' && !(display.startsWith('prompt') && (await enableHeadsUpNotifications()))) return;
  const departure = demoDeparture();
  // If a user-created routine is sooner, it owns the banner and its own notification covers it.
  const winner = demoWinner(items, departure);
  if (!winner || isDemoRoutine(winner.leg.routine_id)) return;
  let notified: string | null = null;
  try { notified = localStorage.getItem(DEMO_NOTIFIED_KEY); } catch { /* private mode */ }
  if (notified === String(departure)) return;
  await scheduleDemoHeadsUp(undefined, winner.leg);
  markDemoNotified(departure);
}

/** This demo countdown already has its notification (so the next resume doesn't send another). */
export function markDemoNotified(departureMs: number) {
  try { localStorage.setItem(DEMO_NOTIFIED_KEY, String(departureMs)); } catch { /* private mode */ }
}

// "Fire heads-up now" delivers its own notification; don't let the next refresh duplicate it with a
// notify-now for the same occurrence. Keyed by `routine:leg:date`.
const FIRED_KEY = 'mapay_heads_up_fired';
function firedHeadsUps(): Record<string, number> {
  try { return JSON.parse(localStorage.getItem(FIRED_KEY) ?? '{}'); } catch { return {}; }
}
function wasHeadsUpFired(leg: UpcomingLeg): boolean {
  return Boolean(firedHeadsUps()[legKey(leg)]);
}
export function markHeadsUpFired(leg: UpcomingLeg) {
  markHeadsUpFiredKey(legKey(leg));
}
export function markHeadsUpFiredKey(key: string) {
  const fired = firedHeadsUps();
  fired[key] = Date.now();
  const keys = Object.keys(fired).slice(-50);
  try { localStorage.setItem(FIRED_KEY, JSON.stringify(Object.fromEntries(keys.map(k => [k, fired[k]])))); } catch { /* private mode */ }
}

/** Notifications already in the Notification Center, so an in-window refresh doesn't send them twice. */
async function deliveredNotificationIds(): Promise<Set<number>> {
  try {
    const { notifications } = await LocalNotifications.getDeliveredNotifications();
    return new Set(notifications.map(n => n.id));
  } catch {
    return new Set(); // not available: the fired marker still covers the app's own schedules
  }
}

/** Replaces the pending heads-ups with one per upcoming leg (by id); drops ones that no longer exist.
 * Already inside the heads-up window, the notification is delivered a few seconds out. */
export async function scheduleHeadsUps(items?: UpcomingLeg[]) {
  if (!isNative()) return;
  const legs = items ?? (await api.upcomingRoutines(DAYS)).items;
  if (isDemo()) await scheduleDemoHeadsUpForBanner(legs);
  if (!(await notificationsAllowed())) return;
  await registerActionTypes();
  const now = Date.now();
  const delivered = await deliveredNotificationIds();
  const wanted = new Set<number>();
  const scheduled: LocalNotificationSchema[] = [];
  const notified: UpcomingLeg[] = [];
  for (const leg of legs) {
    // Demo data: mock legs keep the demo notification above; only user-created routines are scheduled.
    if (isDemo() && !isDemoRoutine(leg.routine_id)) continue;
    const plan = planHeadsUp(leg, now);
    if (plan.action === 'none' || plan.notifyAt === null) continue;
    const id = notificationId(legKey(leg));
    wanted.add(id);
    // In-window and already sent (on a previous launch or from "Fire heads-up now"): don't repeat it.
    if (plan.action === 'notify-now' && (wasHeadsUpFired(leg) || delivered.has(id))) continue;
    scheduled.push(await toNotification(leg, new Date(plan.notifyAt)));
    if (plan.action === 'notify-now') notified.push(leg);
  }

  const { notifications: pending } = await LocalNotifications.getPending();
  // Only the regular heads-ups: a pending demo one (5 s out) must survive the reschedule on resume.
  const stale = pending.filter(n => n.extra?.key && !n.extra?.demo && !wanted.has(n.id));
  if (stale.length) await LocalNotifications.cancel({ notifications: stale.map(n => ({ id: n.id })) });

  if (scheduled.length) {
    await LocalNotifications.schedule({ notifications: scheduled });
    notified.forEach(markHeadsUpFired); // delivered a few seconds out: don't fire it again on refresh
  }
}

/** Demo ("Fire heads-up now", mapay://demo/heads-up): a leg's heads-up (default: the next), delivered `delayMs` from now. */
export async function scheduleDemoHeadsUp(delayMs = 5000, leg?: UpcomingLeg) {
  if (!(await notificationsAllowed()) && !(await enableHeadsUpNotifications())) return;
  await registerActionTypes();
  const target = leg ?? (await api.upcomingRoutines(DAYS)).items[0];
  if (!target) return;
  const notification = await toNotification(target, new Date(Date.now() + delayMs));
  await LocalNotifications.schedule({
    notifications: [{ ...notification, id: notification.id ^ 1, extra: { ...notification.extra, demo: true } }],
  });
}
