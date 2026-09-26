import type { LatLng } from "./types";
import { AppLauncher } from '@capacitor/app-launcher';

const fmt = ([lat, lng]: LatLng) => `${lat},${lng}`;

// Only Google Maps preserves multi-waypoint shaping; Apple Maps/Waze get origin->destination only.
export function googleMapsLink(origin: LatLng, destination: LatLng, waypoints: LatLng[] = []): string {
  const params = new URLSearchParams({ api: "1", origin: fmt(origin), destination: fmt(destination) });
  if (waypoints.length) params.set("waypoints", waypoints.map(fmt).join("|"));
  return `https://www.google.com/maps/dir/?${params}`;
}

export function appleMapsLink(origin: LatLng, destination: LatLng): string {
  return `https://maps.apple.com/?saddr=${fmt(origin)}&daddr=${fmt(destination)}`;
}

export function wazeLink(destination: LatLng): string {
  return `https://waze.com/ul?ll=${fmt(destination)}&navigate=yes`;
}

export async function openLink(url: string) {
  try {
    const { value } = await AppLauncher.canOpenUrl({ url });
    if (value) {
      await AppLauncher.openUrl({ url });
    } else {
      window.open(url, '_blank');
    }
  } catch {
    window.open(url, '_blank');
  }
}
