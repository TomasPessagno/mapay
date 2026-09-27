import React, { useEffect, useState } from 'react';
import { Capacitor } from '@capacitor/core';
import { IonContent, IonHeader, IonItem, IonList, IonNote, IonPage, IonTitle, IonToggle, IonToolbar } from '@ionic/react';
import { enableHeadsUpNotifications, notificationsAllowed } from '../headsup/notifications';
import PreferencesTab from '../routines/PreferencesTab';
import { getDeviceId } from '../lib/api';
import { MapayNative, isNativeIOS } from '../lib/native';
import { App as CapacitorApp } from '@capacitor/app';

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

// Heads-up notifications (#28): permission is asked from this toggle, a user gesture. Native only.
const NotificationsRow: React.FC = () => {
  const [allowed, setAllowed] = useState<boolean | null>(null);
  useEffect(() => {
    if (Capacitor.isNativePlatform()) notificationsAllowed().then(setAllowed);
  }, []);
  if (allowed === null) return null;
  return (
    <>
      <h2 style={{ marginLeft: 16, marginTop: 24, marginBottom: 8, fontSize: 14, textTransform: 'uppercase', color: 'var(--ion-color-medium)' }}>
        Heads-up
      </h2>
      <IonList inset>
        <IonItem>
          <IonToggle
            checked={allowed}
            disabled={allowed}
            onIonChange={e => { if (e.detail.checked) enableHeadsUpNotifications().then(setAllowed); }}
          >
            Notify me before each trip
          </IonToggle>
        </IonItem>
      </IonList>
      {allowed && <IonNote style={{ display: 'block', margin: '0 32px', fontSize: 13 }}>To turn them off, use Settings › Notifications › Mapay.</IonNote>}
      <LiveActivitiesOffNote />
    </>
  );
};

const PreferencesPage: React.FC = () => {
  return (
    <IonPage>
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
        <DeviceIdLine />
      </IonContent>
    </IonPage>
  );
};

export default PreferencesPage;
