import React, { useState } from 'react';
import { IonContent, IonHeader, IonPage, IonTitle, IonToolbar } from '@ionic/react';
import MapView from '../map/MapView';

const MapPage: React.FC = () => {
  const [departAt] = useState(new Date());

  return (
    <IonPage>
      <IonHeader translucent={true} className="ion-no-border" style={{ position: 'absolute', top: 0, width: '100%', zIndex: 10 }}>
        <IonToolbar className="glass">
          <IonTitle>Map</IonTitle>
        </IonToolbar>
      </IonHeader>
      <IonContent fullscreen={true} scrollY={false}>
        <MapView departAt={departAt} route={null} />
      </IonContent>
    </IonPage>
  );
};

export default MapPage;
