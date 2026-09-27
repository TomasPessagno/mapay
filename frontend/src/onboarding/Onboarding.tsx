import React, { useCallback, useEffect, useState } from 'react';
import { Capacitor } from '@capacitor/core';
import { IonButton, IonIcon, IonSpinner } from '@ionic/react';
import {
  checkmarkCircle,
  closeCircle,
  locationOutline,
  notificationsOutline,
  phonePortraitOutline,
} from 'ionicons/icons';
import { getDataSource, setDataSource, type DataSource } from '../lib/dataSource';
import { ColourCodedIllustration, HeadsUpIllustration, PromptIllustration } from './Illustrations';
import {
  liveActivitiesState,
  requestLocationPermission,
  requestNotificationPermission,
  type PermissionState,
} from './permissions';
import { markOnboardingSeen } from './storage';
import './onboarding.css';

// First-run onboarding (#139): three intro screens, a permission primer and the data-mode pick.
// Mounted by App on a fresh install; re-opened from Preferences › About › "Show intro".

const INTRO_STEPS = 3;
const PERMISSION_STEP = 3;
const DATA_STEP = 4;
const STEP_COUNT = 5;

const INTROS = [
  {
    figure: <ColourCodedIllustration />,
    title: "Miami's streets, colour-coded",
    body: "Floods, construction, traffic and closures — all on one map, one colour each.",
  },
  {
    figure: <HeadsUpIllustration />,
    title: 'A heads-up before every trip',
    body: 'Before each routine, your Lock Screen shows the route, the leave time and what is in the way, with Start and Customize.',
  },
  {
    figure: <PromptIllustration />,
    title: 'Change the route in plain English',
    body: 'Say “stop at a Starbucks and stay off the Palmetto” and Mapay reroutes around it.',
  },
];

const STATUS_LABEL: Record<PermissionState, string> = {
  unknown: '',
  granted: 'Allowed',
  denied: 'Not allowed',
  unavailable: '',
};

const PermissionStatus: React.FC<{ state: PermissionState }> = ({ state }) => {
  if (state === 'granted') {
    return (
      <span className="ob-perm-status ob-perm-status-ok">
        <IonIcon icon={checkmarkCircle} aria-hidden="true" /> {STATUS_LABEL.granted}
      </span>
    );
  }
  if (state === 'denied') {
    return (
      <span className="ob-perm-status ob-perm-status-no">
        <IonIcon icon={closeCircle} aria-hidden="true" /> {STATUS_LABEL.denied}
      </span>
    );
  }
  return null;
};

const PermissionRow: React.FC<{
  icon: string;
  title: string;
  children: React.ReactNode;
  status?: PermissionState;
}> = ({ icon, title, children, status }) => (
  <div className="ob-perm-row">
    <span className="ob-perm-icon"><IonIcon icon={icon} aria-hidden="true" /></span>
    <div className="ob-perm-text">
      <h3 className="ob-perm-title">
        {title}
        {status ? <PermissionStatus state={status} /> : null}
      </h3>
      <p className="ob-perm-detail">{children}</p>
    </div>
  </div>
);

const Onboarding: React.FC<{ onDone: () => void }> = ({ onDone }) => {
  const native = Capacitor.isNativePlatform();
  const [initialMode] = useState<DataSource>(() => getDataSource());
  const [step, setStep] = useState(0);
  const [mode, setMode] = useState<DataSource>(initialMode);
  const [location, setLocation] = useState<PermissionState>('unknown');
  const [notifications, setNotifications] = useState<PermissionState>('unknown');
  const [activities, setActivities] = useState<'on' | 'off' | 'unavailable'>('unavailable');
  const [requesting, setRequesting] = useState(false);

  useEffect(() => {
    liveActivitiesState().then(setActivities).catch(() => undefined);
  }, []);

  // Reload when the data source changed so every screen refetches from the chosen source, the same
  // way Preferences › Data does it.
  const finish = useCallback(() => {
    setDataSource(mode);
    markOnboardingSeen();
    if (mode !== initialMode) {
      window.location.reload();
      return;
    }
    onDone();
  }, [mode, initialMode, onDone]);

  // The Continue tap is the user gesture iOS needs; requests run in order, one after the other.
  const requestPermissions = async () => {
    if (requesting) return;
    setRequesting(true);
    try {
      setLocation(await requestLocationPermission());
      setNotifications(await requestNotificationPermission());
    } finally {
      setRequesting(false);
      setStep(DATA_STEP);
    }
  };

  const intro = step < INTRO_STEPS ? INTROS[step] : null;

  return (
    <div className="ob" role="dialog" aria-modal="true" aria-label="Welcome to Mapay">
      <div className="ob-topbar">
        {intro && (
          <button type="button" className="ob-skip" onClick={() => setStep(PERMISSION_STEP)}>
            Skip
          </button>
        )}
      </div>

      <div className="ob-scroll">
        {intro && (
          <div className="ob-stage" key={step}>
            <div className="ob-figure">{intro.figure}</div>
            <h1 className="ob-title dynamic-large-title">{intro.title}</h1>
            <p className="ob-body dynamic-body">{intro.body}</p>
          </div>
        )}

        {step === PERMISSION_STEP && (
          <div className="ob-stage">
            <h1 className="ob-title dynamic-large-title">A couple of permissions</h1>
            <p className="ob-body dynamic-body">Mapay works best with these. iOS will ask next.</p>
            <div className="ob-perms">
              <PermissionRow icon={locationOutline} title="Location" status={native ? location : undefined}>
                to start routes where you are.
              </PermissionRow>
              <PermissionRow icon={notificationsOutline} title="Notifications" status={native ? notifications : undefined}>
                to remind you before you leave.
              </PermissionRow>
              <PermissionRow icon={phonePortraitOutline} title="Live Activities">
                when iOS asks “Allow Live Activities from Mapay?” on the Lock Screen, tap Allow.
              </PermissionRow>
            </div>
            {!native && (
              <p className="ob-hint">The permission prompts appear when Mapay runs on an iPhone.</p>
            )}
            {activities === 'off' && (
              <p className="ob-warning">
                Live Activities are off for Mapay. Turn them on in Settings › Mapay › Live Activities.
              </p>
            )}
          </div>
        )}

        {step === DATA_STEP && (
          <div className="ob-stage">
            <h1 className="ob-title dynamic-large-title">Pick a data mode</h1>
            <p className="ob-body dynamic-body">You can change this any time in Preferences › Data.</p>
            <div className="ob-modes" role="radiogroup" aria-label="Data mode">
              <button
                type="button"
                role="radio"
                aria-checked={mode === 'demo'}
                className={mode === 'demo' ? 'ob-mode ob-mode-selected' : 'ob-mode'}
                onClick={() => setMode('demo')}
              >
                <span className="ob-mode-head">
                  <span className="ob-mode-name">Demo</span>
                  <span className="ob-mode-tag">Recommended</span>
                </span>
                <span className="ob-mode-detail">Bundled sample data — the map, routes and hazards are ready to explore.</span>
              </button>
              <button
                type="button"
                role="radio"
                aria-checked={mode === 'live'}
                className={mode === 'live' ? 'ob-mode ob-mode-selected' : 'ob-mode'}
                onClick={() => setMode('live')}
              >
                <span className="ob-mode-head">
                  <span className="ob-mode-name">Live</span>
                </span>
                <span className="ob-mode-detail">The real Mapay backend, with live hazards and your routines.</span>
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="ob-footer">
        <div className="ob-dots" aria-hidden="true">
          {Array.from({ length: STEP_COUNT }, (_, i) => (
            <span key={i} className={i === step ? 'ob-dot ob-dot-active' : 'ob-dot'} />
          ))}
        </div>

        {intro && (
          <IonButton expand="block" shape="round" size="large" onClick={() => setStep(step + 1)}>
            Continue
          </IonButton>
        )}

        {step === PERMISSION_STEP && (
          <>
            <IonButton expand="block" shape="round" size="large" disabled={requesting} onClick={requestPermissions}>
              {requesting ? <><IonSpinner name="crescent" />&nbsp;Waiting for iOS…</> : 'Continue'}
            </IonButton>
            <IonButton expand="block" fill="clear" size="default" disabled={requesting} onClick={() => setStep(DATA_STEP)}>
              Not now
            </IonButton>
          </>
        )}

        {step === DATA_STEP && (
          <IonButton expand="block" shape="round" size="large" onClick={finish}>
            Get started
          </IonButton>
        )}
      </div>
    </div>
  );
};

export default Onboarding;
