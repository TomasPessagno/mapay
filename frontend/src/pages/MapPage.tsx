import React, { useState } from 'react';
import { IonContent, IonHeader, IonPage, IonTitle, IonToolbar } from '@ionic/react';
import MapView from '../map/MapView';
import MapSheet from '../components/MapSheet';
import { api } from '../lib/api';
import type { RouteResponse } from '../lib/types';

const MapPage: React.FC = () => {
  const [departAt] = useState(new Date());
  const [routeResponse, setRouteResponse] = useState<RouteResponse | null>(null);
  const [selectedRouteIndex, setSelectedRouteIndex] = useState(0);

  const handleSearch = async (destination: string) => {
    // In a real app we'd geocode this, but here we just call the route API
    // which is mocked to return route.json
    try {
      const res = await api.route({ origin: "current", destination });
      setRouteResponse(res);
      setSelectedRouteIndex(0);
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <IonPage>
      <IonHeader translucent={true} className="ion-no-border" style={{ position: 'absolute', top: 0, width: '100%', zIndex: 10 }}>
        <IonToolbar className="glass">
          <IonTitle>Map</IonTitle>
        </IonToolbar>
      </IonHeader>
      <IonContent fullscreen={true} scrollY={false}>
        <MapView 
          departAt={departAt} 
          routeResponse={routeResponse} 
          selectedRouteIndex={selectedRouteIndex} 
        />
        <MapSheet
          routeResponse={routeResponse}
          onSearch={handleSearch}
          onRouteSelect={setSelectedRouteIndex}
          selectedRouteIndex={selectedRouteIndex}
        />
      </IonContent>
    </IonPage>
  );
};

export default MapPage;
