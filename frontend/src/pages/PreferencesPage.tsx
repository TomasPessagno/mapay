import React, { useEffect, useState } from 'react';
import { Capacitor } from '@capacitor/core';
import { IonContent, IonHeader, IonPage, IonTitle, IonToolbar } from '@ionic/react';
import PreferencesTab from '../routines/PreferencesTab';
import { getDeviceId } from '../lib/api';

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
        <DeviceIdLine />
      </IonContent>
    </IonPage>
  );
};

export default PreferencesPage;
