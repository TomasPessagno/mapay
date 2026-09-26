import React from 'react';
import { IonContent, IonHeader, IonPage, IonTitle, IonToolbar } from '@ionic/react';
import PreferencesTab from '../routines/PreferencesTab';

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
      </IonContent>
    </IonPage>
  );
};

export default PreferencesPage;
