// First-run onboarding (#139): "seen" lives in localStorage. Every access is wrapped, so private
// mode (where localStorage throws) never blocks the app.

export const ONBOARDING_SEEN_KEY = 'mapay_onboarding_seen';

export function hasSeenOnboarding(): boolean {
  try {
    return localStorage.getItem(ONBOARDING_SEEN_KEY) === '1';
  } catch {
    return false;
  }
}

export function markOnboardingSeen(): void {
  try {
    localStorage.setItem(ONBOARDING_SEEN_KEY, '1');
  } catch {
    // Private mode: the intro shows again next launch, and the app still works.
  }
}
