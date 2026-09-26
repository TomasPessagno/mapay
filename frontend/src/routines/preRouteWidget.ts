import type { Routine } from "../lib/types";

// Demo only: client-side timer + browser Notification API (no FCM/APNs).
export function schedulePreRouteNotification(_routine: Routine, _demoNow: () => Date): () => void {
  // TODO: request permission, setInterval against demo clock, fire Notification near time_window[0]
  return () => {};
}
