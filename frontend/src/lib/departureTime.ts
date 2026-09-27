/** ISO timestamp with the device's local UTC offset, e.g. 2026-09-27T17:30:00-04:00. */
export function toDeviceOffsetISOString(date: Date): string {
  const localTime = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
    .toISOString()
    .replace(/\.\d{3}Z$/, '');
  const offsetMinutes = -date.getTimezoneOffset();
  const sign = offsetMinutes >= 0 ? '+' : '-';
  const absoluteOffset = Math.abs(offsetMinutes);
  const hours = String(Math.floor(absoluteOffset / 60)).padStart(2, '0');
  const minutes = String(absoluteOffset % 60).padStart(2, '0');
  return `${localTime}${sign}${hours}:${minutes}`;
}

/** IonDatetime treats ISO components as wall time and ignores their timezone suffix. */
export function toLocalDatetimeValue(date: Date): string {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
    .toISOString()
    .replace(/\.\d{3}Z$/, '');
}

export function localClockTime(date: Date): string {
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

export function formatClockTime(date: Date): string {
  return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(date);
}
