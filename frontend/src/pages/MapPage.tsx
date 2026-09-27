import React, { useState, useEffect } from 'react';
import { IonContent, IonHeader, IonPage, IonTitle, IonToolbar, IonModal } from '@ionic/react';
import { useLocation } from 'react-router-dom';
import { APIProvider } from "@vis.gl/react-google-maps";
import { Geolocation } from '@capacitor/geolocation';
import { App as CapacitorApp } from '@capacitor/app';
import MapView from '../map/MapView';
import MapSheet from '../components/MapSheet';
import { api } from '../lib/api';
import type { RouteResponse, Place, Routine } from '../lib/types';
import type { PlaceData } from '../components/PlaceCard';
import RoutineEditor from '../routines/RoutineEditor';

const API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY ?? "";

/**
 * Asks for location if needed and returns the current position, or null if it's denied.
 * checkPermissions/requestPermissions can throw on iOS (e.g. while location services start up);
 * getCurrentPosition then still triggers the system prompt, so a throw never skips the request.
 */
async function locateUser(): Promise<{ lat: number; lng: number } | null> {
  let state: string = 'prompt';
  try {
    state = (await Geolocation.checkPermissions()).location;
  } catch (e) {
    console.warn("Location permission check failed", e);
  }
  if (state === 'denied') return null;
  if (state !== 'granted') {
    try {
      state = (await Geolocation.requestPermissions()).location;
    } catch (e) {
      console.warn("Location permission request failed", e);
    }
    if (state === 'denied') return null;
  }
  const pos = await Geolocation.getCurrentPosition({ enableHighAccuracy: false, timeout: 15000, maximumAge: 60000 });
  return { lat: pos.coords.latitude, lng: pos.coords.longitude };
}
const MAP_ID = import.meta.env.VITE_GOOGLE_MAPS_MAP_ID ?? "DEMO_MAP_ID";

function getDistanceMiles(lat1: number, lon1: number, lat2: number, lon2: number) {
  const R = 3958.8; // Radius of the earth in miles
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

const MapPage: React.FC = () => {
  const [departAt] = useState(new Date());
  const [routeResponse, setRouteResponse] = useState<RouteResponse | null>(null);
  const [selectedRouteIndex, setSelectedRouteIndex] = useState(0);
  const [selectedPlace, setSelectedPlace] = useState<PlaceData | null>(null);
  const [userLocation, setUserLocation] = useState<{lat: number, lng: number} | null>(null);
  
  // RoutineEditor state
  const [isRoutineEditorOpen, setIsRoutineEditorOpen] = useState(false);
  const [newRoutine, setNewRoutine] = useState<Routine | null>(null);
  const [savedPlaces, setSavedPlaces] = useState<Place[]>([]);

  const showSheet = useLocation().pathname.startsWith('/map');

  useEffect(() => {
    let watchId: string | null = null;
    let isActive = true;

    let settingUp = false; // the permission prompt itself fires inactive → active; don't start twice
    const setupLocation = async () => {
      if (settingUp || watchId) return;
      settingUp = true;
      try {
        const initial = await locateUser();
        if (!initial || !isActive) return;
        // MapView centres on the first known position once the map is ready (no event to miss).
        setUserLocation(initial);

        watchId = await Geolocation.watchPosition({}, (position, err) => {
          if (err) {
            console.warn("Location watch error", err);
            return;
          }
          if (position && isActive) {
            setUserLocation({ lat: position.coords.latitude, lng: position.coords.longitude });
          }
        });
      } catch (e) {
         console.warn("Geolocation failed", e);
      } finally {
        settingUp = false;
      }
    };
    setupLocation();
    const resume = CapacitorApp.addListener('appStateChange', ({ isActive: active }) => {
      if (active) setupLocation();
    });

    return () => {
      isActive = false;
      resume.then(h => h.remove());
      if (watchId) {
        Geolocation.clearWatch({ id: watchId });
      }
    };
  }, []);

  const handleSearch = (destination: {lat: number, lng: number}, name: string, address?: string, type?: string, placeId?: string) => {
    let distanceMiles: number | undefined = undefined;
    if (userLocation) {
      distanceMiles = getDistanceMiles(userLocation.lat, userLocation.lng, destination.lat, destination.lng);
    }
    const placeData: PlaceData = { location: destination, name, address, type, placeId, distanceMiles };
    setSelectedPlace(placeData);
    
    // Dispatch event to map view
    const event = new CustomEvent('recenter-map', { detail: { location: destination, zoom: 15, place: placeData } });
    window.dispatchEvent(event);
  };

  const handleRequestRoute = async () => {
    if (!selectedPlace) return;
    try {
      let origin = { lat: 25.7617, lng: -80.1918 }; // fallback center
      if (userLocation) {
        origin = userLocation;
      }

      let preferences;
      try {
        preferences = await api.getPreferences();
      } catch {
        // ignore
      }

      const res = await api.route({ 
        origin, 
        destination: selectedPlace.location,
        depart_at: new Date().toISOString(),
        ...(preferences ? { preferences } : {})
      });
      setRouteResponse(res);
      setSelectedRouteIndex(0);
    } catch (e) {
      console.error(e);
    }
  };

  const handleAddToRoutine = async () => {
    if (!selectedPlace) return;
    try {
      const places = await api.places();
      const savedPlace = await api.savePlace({
        name: selectedPlace.name,
        lat: selectedPlace.location.lat,
        lng: selectedPlace.location.lng,
        google_place_id: selectedPlace.placeId,
        address: selectedPlace.address,
      });
      // The editor's place picker resolves ids from this list, so include the new place.
      setSavedPlaces([...places.filter((p) => p._id !== savedPlace._id), savedPlace]);

      // Prepare new routine
      setNewRoutine({
        _id: '',
        user_id: '',
        name: `To ${selectedPlace.name}`,
        active: true,
        legs: [{
          from_place: '',
          to_place: savedPlace._id,
          when: { kind: 'at', time: '09:00' },
          anchor: 'depart',
          days: null
        }],
        tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
        repeat: { kind: 'daily', weekday: undefined, weekdays: undefined },
        heads_up_minutes: 30
      });
      setIsRoutineEditorOpen(true);
    } catch (e) {
      console.error("Failed to setup routine", e);
    }
  };

  React.useEffect(() => {
    const handleUpdateRoute = (e: Event) => {
      const customEvent = e as CustomEvent;
      if (customEvent.detail?.routeResponse) {
        setRouteResponse(customEvent.detail.routeResponse);
        setSelectedRouteIndex(0);
      }
    };
    window.addEventListener('update-map-route', handleUpdateRoute);
    return () => window.removeEventListener('update-map-route', handleUpdateRoute);
  }, []);

  const handleClearRoute = () => {
    setRouteResponse(null);
    setSelectedRouteIndex(0);
  };

  const handleClearPlace = () => {
    setSelectedPlace(null);
    const event = new CustomEvent('recenter-map', { detail: { place: null } });
    window.dispatchEvent(event);
  };

  const handleLocateMe = () => {
    if (userLocation) {
       const event = new CustomEvent('recenter-map', { detail: { location: userLocation, zoom: 14 } });
       window.dispatchEvent(event);
    } else {
       // A tap is a user gesture, so this is also where a skipped or failed prompt gets asked again.
       locateUser().then(loc => {
         if (!loc) return;
         setUserLocation(loc);
         const event = new CustomEvent('recenter-map', { detail: { location: loc, zoom: 14 } });
         window.dispatchEvent(event);
       }).catch(e => console.warn("Locate me failed", e));
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
        <APIProvider apiKey={API_KEY}>
          <MapView 
            departAt={departAt} 
            routeResponse={routeResponse} 
            selectedRouteIndex={selectedRouteIndex} 
            mapId={MAP_ID}
            userLocation={userLocation}
            onLocateMe={handleLocateMe}
          />
          {showSheet && (
            <MapSheet
              isOpen
              routeResponse={routeResponse}
              selectedPlace={selectedPlace}
              onSearch={handleSearch}
              onRouteSelect={setSelectedRouteIndex}
              selectedRouteIndex={selectedRouteIndex}
              onClearRoute={handleClearRoute}
              onClearPlace={handleClearPlace}
              onRequestRoute={handleRequestRoute}
              onAddToRoutine={handleAddToRoutine}
            />
          )}
        </APIProvider>

        <IonModal isOpen={isRoutineEditorOpen} onDidDismiss={() => setIsRoutineEditorOpen(false)}>
          {newRoutine && (
            <RoutineEditor 
              routine={newRoutine}
              places={savedPlaces}
              onSave={async (r) => {
                await api.saveRoutine(r);
                setIsRoutineEditorOpen(false);
              }}
              onCancel={() => setIsRoutineEditorOpen(false)}
            />
          )}
        </IonModal>
      </IonContent>
    </IonPage>
  );
};

export default MapPage;
