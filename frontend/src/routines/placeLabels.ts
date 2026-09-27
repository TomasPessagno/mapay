import type { Place } from '../lib/types';

const ADDRESS_MARKERS = /\b(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|court|ct|lane|ln|highway|hwy|parkway|pkwy|way)\b/i;
const STATE_OR_POSTAL = /\b(?:FL|Florida)\b|\b\d{5}(?:-\d{4})?\b/i;

function looksLikeFormattedAddress(value: string): boolean {
  return value.length > 48 || (ADDRESS_MARKERS.test(value) && /\d/.test(value)) || STATE_OR_POSTAL.test(value);
}

function findLocality(value?: string): string | undefined {
  if (!value) return undefined;
  const parts = value.split(',').map((part) => part.trim()).filter(Boolean);
  const locality = parts.reverse().find((part) => {
    if (/^(?:US|USA|United States|Florida|FL)$/i.test(part) || STATE_OR_POSTAL.test(part)) return false;
    if (/^\d+\s/.test(part) || (ADDRESS_MARKERS.test(part) && /\d/.test(part))) return false;
    return true;
  });
  return locality?.replace(/\s+County$/i, '').trim() || undefined;
}

export function shortPlaceLabel(name?: string, address?: string): string {
  const candidate = name?.trim();
  if (candidate && !looksLikeFormattedAddress(candidate)) {
    const locality = findLocality(address);
    if (locality && /^(?:home|work|house|apartment)$/i.test(candidate)) return `${candidate} (${locality})`;
    return candidate;
  }
  return findLocality(address) || findLocality(candidate) || 'Saved place';
}

export function savedPlaceLabel(place?: Place): string {
  return shortPlaceLabel(place?.name, place?.address);
}
