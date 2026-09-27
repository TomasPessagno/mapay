/// <reference types="node" />
import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { UpcomingLeg } from '../lib/types.ts';
import {
  DEPARTURE_LINGER_MS,
  FIRE_NOW_DELAY_MS,
  LIVE_ACTIVITY_WINDOW_MS,
  formatClock,
  headsUpToast,
  planHeadsUp,
  soonestLiveActivity,
} from './schedule.ts';

const MIN = 60_000;
// Mon 2026-09-28 12:00 UTC.
const NOW = Date.UTC(2026, 8, 28, 12, 0, 0);

function leg(overrides: Partial<UpcomingLeg> = {}): UpcomingLeg {
  return {
    routine_id: 'rt-fiu',
    routine_name: 'FIU campuses',
    leg: 0,
    from: { place_id: 'pl-mmc', name: 'MMC' },
    to: { place_id: 'pl-bbc', name: 'BBC' },
    local_date: '2026-09-28',
    departure_at: new Date(NOW + 60 * MIN).toISOString(),
    heads_up_at: new Date(NOW + 30 * MIN).toISOString(),
    window: null,
    best_departure_at: null,
    best_saving_s: null,
    duration_s: 1800,
    static_duration_s: 1500,
    summary: 'via I-95',
    top_hazards: [],
    image_url: null,
    deep_links: {},
    ...overrides,
  };
}

test('inside the heads-up window: fire the notification now and start the banner', () => {
  const plan = planHeadsUp(leg({ heads_up_at: new Date(NOW - 15 * MIN).toISOString(), departure_at: new Date(NOW + 15 * MIN).toISOString() }), NOW);
  assert.equal(plan.action, 'notify-now');
  assert.equal(plan.notifyAt, NOW + FIRE_NOW_DELAY_MS);
  assert.equal(plan.liveActivity, true);
  assert.equal(plan.expired, false);
});

test('within 8 h: schedule at heads_up_at and start the banner now', () => {
  const plan = planHeadsUp(leg({ departure_at: new Date(NOW + 8 * 60 * MIN - MIN).toISOString(), heads_up_at: new Date(NOW + 30 * MIN).toISOString() }), NOW);
  assert.equal(plan.action, 'notify');
  assert.equal(plan.notifyAt, NOW + 30 * MIN);
  assert.equal(plan.liveActivity, true);
});

test('beyond 8 h: schedule the notification, the banner waits for the app', () => {
  const plan = planHeadsUp(leg({ departure_at: new Date(NOW + 24 * 60 * MIN).toISOString(), heads_up_at: new Date(NOW + 23.5 * 60 * MIN).toISOString() }), NOW);
  assert.equal(plan.action, 'notify');
  assert.equal(plan.notifyAt, NOW + 23.5 * 60 * MIN);
  assert.equal(plan.liveActivity, false);
  assert.ok(24 * 60 * MIN > LIVE_ACTIVITY_WINDOW_MS);
});

test('already departed: no notification, the banner lingers until departure + 10 min', () => {
  const plan = planHeadsUp(leg({ departure_at: new Date(NOW - 5 * MIN).toISOString(), heads_up_at: new Date(NOW - 35 * MIN).toISOString() }), NOW);
  assert.equal(plan.action, 'none');
  assert.equal(plan.liveActivity, true);
});

test('expired: departure + linger passed, nothing to do', () => {
  const plan = planHeadsUp(leg({ departure_at: new Date(NOW - DEPARTURE_LINGER_MS - MIN).toISOString(), heads_up_at: new Date(NOW - 45 * MIN).toISOString() }), NOW);
  assert.equal(plan.action, 'none');
  assert.equal(plan.liveActivity, false);
  assert.equal(plan.expired, true);
});

test('the soonest leg wins the one Live Activity', () => {
  const userLeg = leg({ routine_id: 'new-1', departure_at: new Date(NOW + 15 * MIN).toISOString(), heads_up_at: new Date(NOW - 15 * MIN).toISOString() });
  const mockCountdown = { leg: leg({ routine_id: 'rt-fiu' }), departureMs: NOW + 30 * MIN };
  const winner = soonestLiveActivity([mockCountdown, { leg: userLeg, departureMs: NOW + 15 * MIN }], NOW);
  assert.equal(winner?.leg, userLeg);
  // A tomorrow leg is not a candidate; the mock countdown keeps the banner.
  const tomorrow = { leg: leg({ routine_id: 'new-2', departure_at: new Date(NOW + 24 * 60 * MIN).toISOString() }), departureMs: NOW + 24 * 60 * MIN };
  assert.equal(soonestLiveActivity([mockCountdown, tomorrow], NOW)?.leg, mockCountdown.leg);
});

test('demo countdown: a mock leg days away follows its fresh 30-min departure', () => {
  const mock = leg({ departure_at: new Date(NOW + 48 * 60 * MIN).toISOString(), heads_up_at: new Date(NOW + 47.5 * 60 * MIN).toISOString() });
  const demoDeparture = NOW + 30 * MIN;
  // The banner decision uses the countdown override...
  assert.equal(planHeadsUp(mock, NOW, demoDeparture).liveActivity, true);
  // ...while a user routine created in Demo mode plans from its own times like live data.
  const userLeg = leg({ routine_id: 'new-1', departure_at: new Date(NOW + 15 * MIN).toISOString(), heads_up_at: new Date(NOW + 5 * MIN).toISOString() });
  const plan = planHeadsUp(userLeg, NOW);
  assert.equal(plan.action, 'notify');
  assert.equal(plan.notifyAt, NOW + 5 * MIN);
  assert.equal(plan.liveActivity, true);
});

test('save toast: scheduled today vs tomorrow vs firing now', () => {
  const laterToday = leg({ departure_at: new Date(NOW + 5 * MIN).toISOString(), heads_up_at: new Date(NOW + 4 * MIN).toISOString() });
  assert.equal(headsUpToast(laterToday, planHeadsUp(laterToday, NOW), NOW), `Heads-up scheduled for ${formatClock(NOW + 4 * MIN, NOW)}`);

  const tomorrow = leg({ departure_at: new Date(NOW + 24 * 60 * MIN).toISOString(), heads_up_at: new Date(NOW + 23.5 * 60 * MIN).toISOString() });
  const tomorrowToast = headsUpToast(tomorrow, planHeadsUp(tomorrow, NOW), NOW);
  assert.ok(tomorrowToast?.startsWith('Heads-up scheduled for '));
  assert.match(tomorrowToast ?? '', /PM|AM/);

  const due = leg({ departure_at: new Date(NOW + 15 * MIN).toISOString(), heads_up_at: new Date(NOW - 15 * MIN).toISOString() });
  assert.ok(headsUpToast(due, planHeadsUp(due, NOW), NOW)?.startsWith('Heads-up now · leave at '));
});
