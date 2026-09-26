import React from 'react';
import { IonContent, IonHeader, IonPage, IonTitle, IonToolbar } from '@ionic/react';

const RoutinesPage: React.FC = () => {
  return (
    <IonPage>
      <IonHeader translucent={true} className="ion-no-border">
        <IonToolbar className="glass">
          <IonTitle>Routines</IonTitle>
        </IonToolbar>
      </IonHeader>
      <IonContent fullscreen={true}>
        <IonHeader collapse="condense">
          <IonToolbar>
            <IonTitle size="large">Routines</IonTitle>
          </IonToolbar>
        </IonHeader>
        
        {/* Placeholder for Routines */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '101%' }}>
          <p>Routines List</p>
        </div>
      </IonContent>
    </IonPage>
  );
};

export default RoutinesPage;
