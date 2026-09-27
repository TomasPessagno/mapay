// Preferences › About › "Show intro" re-opens the flow by firing a window event, so the row doesn't
// need a prop drilled from App.

export const OPEN_ONBOARDING_EVENT = 'mapay:open-onboarding';

export function openOnboarding(): void {
  window.dispatchEvent(new Event(OPEN_ONBOARDING_EVENT));
}
