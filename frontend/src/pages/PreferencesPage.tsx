import React from 'react';
import { IonContent, IonHeader, IonPage, IonTitle, IonToolbar } from '@ionic/react';

const PreferencesPage: React.FC = () => {
  return (
    <IonPage>
      <IonHeader translucent={true} className="ion-no-border">
        <IonToolbar className="glass">
          <IonTitle>Preferences</IonTitle>
        </IonToolbar>
      </IonHeader>
      <IonContent fullscreen={true}>
        <IonHeader collapse="condense">
          <IonToolbar>
            <IonTitle size="large">Preferences</IonTitle>
          </IonToolbar>
        </IonHeader>
        
        {/* Placeholder for Preferences */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '101%' }}>
          <p>Preferences Settings</p>
        </div>
      </IonContent>
    </IonPage>
  );
};

export default PreferencesPage;
