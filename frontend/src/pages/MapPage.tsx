import React, { useState } from 'react';
import { IonContent, IonHeader, IonPage, IonTitle, IonToolbar, useIonViewDidEnter, useIonViewWillLeave } from '@ionic/react';
import { APIProvider } from "@vis.gl/react-google-maps";
import { Geolocation } from '@capacitor/geolocation';
import MapView from '../map/MapView';
import MapSheet from '../components/MapSheet';
import { api } from '../lib/api';
import type { RouteResponse } from '../lib/types';

const API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY ?? "";
const MAP_ID = import.meta.env.VITE_GOOGLE_MAPS_MAP_ID ?? "DEMO_MAP_ID";

const MapPage: React.FC = () => {
  const [departAt] = useState(new Date());
  const [routeResponse, setRouteResponse] = useState<RouteResponse | null>(null);
  const [selectedRouteIndex, setSelectedRouteIndex] = useState(0);
  const [showSheet, setShowSheet] = useState(false);

  useIonViewDidEnter(() => setShowSheet(true));
  useIonViewWillLeave(() => setShowSheet(false));

  const handleSearch = async (destination: {lat: number, lng: number}) => {
    try {
      let origin = { lat: 25.7617, lng: -80.1918 }; // fallback center
      try {
        const pos = await Geolocation.getCurrentPosition();
        origin = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      } catch (e) {
        console.warn("Geolocation failed, using fallback", e);
      }

      let preferences;
      try {
        preferences = await api.getPreferences();
      } catch {
        // ignore
      }

      const res = await api.route({ 
        origin, 
        destination,
        depart_at: new Date().toISOString(),
        ...(preferences ? { preferences } : {})
      });
      setRouteResponse(res);
      setSelectedRouteIndex(0);
    } catch (e) {
      console.error(e);
    }
  };

  const handleClearRoute = () => {
    setRouteResponse(null);
    setSelectedRouteIndex(0);
  };

  return (
    <IonPage>
      <IonHeader translucent={true} className="ion-no-border" style={{ position: 'absolute', top: 0, width: '100%', zIndex: 10 }}>
        <IonToolbar className="glass">
          <IonTitle>Map</IonTitle>
        </IonToolbar>
      </IonHeader>
      <IonContent fullscreen={true} scrollY={false}>
        <APIProvider apiKey={API_KEY}>
          <MapView 
            departAt={departAt} 
            routeResponse={routeResponse} 
            selectedRouteIndex={selectedRouteIndex} 
            mapId={MAP_ID}
          />
          <MapSheet
            isOpen={showSheet}
            routeResponse={routeResponse}
            onSearch={handleSearch}
            onRouteSelect={setSelectedRouteIndex}
            selectedRouteIndex={selectedRouteIndex}
            onClearRoute={handleClearRoute}
          />
        </APIProvider>
      </IonContent>
    </IonPage>
  );
};

export default MapPage;
