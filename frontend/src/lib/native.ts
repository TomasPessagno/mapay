import { registerPlugin, Capacitor } from '@capacitor/core';

// JS bridge to the app-local MapayNative plugin (ios/App/App/MapayNativePlugin.swift).

export interface LiveActivityOptions {
  routineId: string;
  leg: number;
  fromName: string;
  toName: string;
  departureMs: number;
  durationMin: number;
  summary: string;
  hazardCount: number;
  topHazardType?: string;
  topHazardTitle?: string;
}

interface MapayNativePlugin {
  startLiveActivity(options: LiveActivityOptions): Promise<{ id: string; updated: boolean }>;
  endLiveActivity(options?: { routineId?: string; leg?: number }): Promise<void>;
  areActivitiesEnabled(): Promise<{ enabled: boolean }>;
  reloadWidgets(): Promise<void>;
}

export const MapayNative = registerPlugin<MapayNativePlugin>('MapayNative');

// Registered from MapayViewController, so it isn't in Capacitor's plugin headers; iOS is enough.
export const isNativeIOS = () => Capacitor.getPlatform() === 'ios';

/** Asks WidgetKit to refetch the home-screen widget's timeline (after routine edits). */
export function reloadWidgets() {
  if (!isNativeIOS()) return Promise.resolve();
  return MapayNative.reloadWidgets().catch(err => console.warn('[mapay] reloadWidgets', err));
}
