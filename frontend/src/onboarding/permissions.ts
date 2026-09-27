import { Capacitor } from '@capacitor/core';
import { Geolocation } from '@capacitor/geolocation';
import { LocalNotifications } from '@capacitor/local-notifications';
import { enableHeadsUpNotifications } from '../headsup/notifications';
import { MapayNative, isNativeIOS } from '../lib/native';

// Permission primer helpers (#139). The web build skips every native call (issue #139, step 2), the
// same way the Preferences rows only act on native.

export type PermissionState = 'unknown' | 'granted' | 'denied' | 'unavailable';

export async function requestLocationPermission(): Promise<PermissionState> {
  if (!Capacitor.isNativePlatform()) return 'unavailable';
  try {
    const status = await Geolocation.requestPermissions();
    return status.location === 'granted' ? 'granted' : 'denied';
  } catch {
    return 'unavailable';
  }
}

export async function requestNotificationPermission(): Promise<PermissionState> {
  if (!Capacitor.isNativePlatform()) return 'unavailable';
  try {
    await enableHeadsUpNotifications();
  } catch {
    // Granting succeeded but scheduling can fail offline; the permission is what the primer reports.
  }
  try {
    const { display } = await LocalNotifications.checkPermissions();
    return display === 'granted' ? 'granted' : 'denied';
  } catch {
    return 'unavailable';
  }
}

/** iOS holds the Live Activities switch; we can only read it, never prompt for it. */
export async function liveActivitiesState(): Promise<'on' | 'off' | 'unavailable'> {
  if (!isNativeIOS()) return 'unavailable';
  try {
    return (await MapayNative.areActivitiesEnabled()).enabled ? 'on' : 'off';
  } catch {
    return 'unavailable';
  }
}
