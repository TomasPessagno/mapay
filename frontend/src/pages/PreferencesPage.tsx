import React, { useEffect, useState } from 'react';
import { Capacitor } from '@capacitor/core';
import { IonContent, IonHeader, IonIcon, IonItem, IonLabel, IonList, IonNote, IonPage, IonTitle, IonToast, IonToggle, IonToolbar } from '@ionic/react';
import { notificationsOutline, sparklesOutline } from 'ionicons/icons';
import { Haptics, NotificationType } from '@capacitor/haptics';
import { enableHeadsUpNotifications, notificationsAllowed } from '../headsup/notifications';
import { NOTIFY_IN_MS, fireHeadsUpNow } from '../headsup/demo';
import PreferencesTab from '../routines/PreferencesTab';
import { getDeviceId } from '../lib/api';
import { MapayNative, isNativeIOS } from '../lib/native';
import { App as CapacitorApp } from '@capacitor/app';
import { openOnboarding } from '../onboarding/events';

// Debug line for #19: the app's identifierForVendor, to compare with the widget's. Native only.
const DeviceIdLine: React.FC = () => {
  const [id, setId] = useState<string | null>(null);
  useEffect(() => {
    if (!Capacitor.isNativePlatform()) return;
    getDeviceId().then((deviceId) => {
      console.log('[mapay] identifierForVendor', deviceId);
      setId(deviceId);
    });
  }, []);
  if (!id) return null;
  return (
    <p style={{ fontSize: 11, opacity: 0.5, textAlign: 'center', padding: '24px 16px', userSelect: 'text' }}>
      Device {id}
    </p>
  );
};

// The first Live Activity after a fresh install asks "Allow Live Activities from Mapay?" on the Lock
// Screen; Don't Allow turns them off silently, so say so here (re-checked when the app comes back).
const LiveActivitiesOffNote: React.FC = () => {
  const [enabled, setEnabled] = useState(true);
  useEffect(() => {
    if (!isNativeIOS()) return;
    const check = () => MapayNative.areActivitiesEnabled().then(r => setEnabled(r.enabled)).catch(() => undefined);
    check();
    const listener = CapacitorApp.addListener('appStateChange', ({ isActive }) => { if (isActive) check(); });
    return () => { listener.then(h => h.remove()); };
  }, []);
  if (enabled) return null;
  return (
    <IonNote color="danger" style={{ display: 'block', margin: '8px 32px 0', fontSize: 13 }}>
      Live Activities are off for Mapay, so the heads-up banner can't show. Turn them on in Settings › Mapay › Live Activities.
    </IonNote>
  );
};

// #36: the visible demo entry point. Fires the whole heads-up on cue. The native calls no-op
// safely on web, where the row is still handy to check the flow.
const FireHeadsUpItem: React.FC = () => {
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const fire = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const leg = await fireHeadsUpNow();
      if (!leg) {
        setToast('No upcoming trip to fire');
        return;
      }
      Haptics.notification({ type: NotificationType.Success }).catch(() => {});
      setToast(`Heads-up fired for ${leg.from.name} → ${leg.to.name} · notification in ${NOTIFY_IN_MS / 1000} s — lock the phone`);
    } catch (err) {
      console.warn('[mapay] fire heads-up', err);
      setToast('Could not fire the heads-up');
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <IonItem button detail={false} disabled={busy} onClick={fire}>
        <IonIcon icon={notificationsOutline} slot="start" color="primary" />
        <IonLabel className="ion-text-wrap">
          <h2>Fire heads-up now</h2>
          <p>Notification + widget + in-app card, on cue for the demo.</p>
        </IonLabel>
      </IonItem>
      <IonToast isOpen={!!toast} message={toast ?? ''} duration={3000} onDidDismiss={() => setToast(null)} position="top" />
    </>
  );
};

// #139: the intro lives in frontend/src/onboarding; this row re-opens it any time.
const ShowIntroItem: React.FC = () => (
  <IonItem button detail={false} onClick={() => openOnboarding()}>
    <IonIcon icon={sparklesOutline} slot="start" color="primary" />
    <IonLabel>Show intro</IonLabel>
  </IonItem>
);

// Heads-up notifications (#28): permission is asked from this toggle, a user gesture. Native only.
const NotificationsRow: React.FC = () => {
  const native = Capacitor.isNativePlatform();
  const [allowed, setAllowed] = useState<boolean | null>(null);
  useEffect(() => {
    if (native) notificationsAllowed().then(setAllowed);
  }, [native]);
  return (
    <>
      <h2 style={{ marginLeft: 16, marginTop: 24, marginBottom: 8, fontSize: 14, textTransform: 'uppercase', color: 'var(--ion-color-medium)' }}>
        Heads-up
      </h2>
      <IonList inset>
        {native && allowed !== null && (
          <IonItem>
            <IonToggle
              checked={allowed}
              disabled={allowed}
              onIonChange={e => { if (e.detail.checked) enableHeadsUpNotifications().then(setAllowed); }}
            >
              Notify me before each trip
            </IonToggle>
          </IonItem>
        )}
        <FireHeadsUpItem />
      </IonList>
      {allowed && <IonNote style={{ display: 'block', margin: '0 32px', fontSize: 13 }}>To turn them off, use Settings › Notifications › Mapay.</IonNote>}
      <LiveActivitiesOffNote />
    </>
  );
};

const PreferencesPage: React.FC = () => {
  return (
    <IonPage className="preferences-page">
      <IonHeader translucent={true} className="ion-no-border">
        <IonToolbar className="glass">
          <IonTitle>Preferences</IonTitle>
        </IonToolbar>
      </IonHeader>
      <IonContent fullscreen={true} style={{ '--background': 'var(--ion-color-step-50, var(--system-grouped-background))' } as React.CSSProperties}>
        <IonHeader collapse="condense">
          <IonToolbar>
            <IonTitle size="large">Preferences</IonTitle>
          </IonToolbar>
        </IonHeader>
        
        <PreferencesTab />
        <NotificationsRow />

        <h2 style={{ marginLeft: 16, marginTop: 24, marginBottom: 8, fontSize: 14, textTransform: 'uppercase', color: 'var(--ion-color-medium)' }}>
          About
        </h2>
        <IonList inset>
          <ShowIntroItem />
        </IonList>

        <DeviceIdLine />
      </IonContent>
    </IonPage>
  );
};

export default PreferencesPage;
