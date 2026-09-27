import { useState } from 'react';
import {
  IonModal, IonHeader, IonToolbar, IonTitle, IonButtons, IonButton,
  IonContent, IonList, IonItem, IonLabel, IonIcon, IonListHeader
} from '@ionic/react';
import { locationOutline } from 'ionicons/icons';
import { APIProvider } from "@vis.gl/react-google-maps";
import type { Place } from '../lib/types';
import { api } from '../lib/api';
import SearchField from '../components/SearchField';

const API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY ?? "";

interface PlacePickerProps {
  label: string;
  value: string; // place ID
  places: Place[];
  onChange: (placeId: string) => void;
  onPlacesUpdated?: () => void;
}

export default function PlacePicker({ label, value, places: savedPlaces, onChange, onPlacesUpdated }: PlacePickerProps) {
  // Places searched and saved from this picker, until the parent's list includes them.
  const [added, setAdded] = useState<Place[]>([]);
  const places = [...savedPlaces, ...added.filter((a) => !savedPlaces.some((p) => p._id === a._id))];
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');

  const selectedPlace = places.find(p => p._id === value);
  const displayName = selectedPlace ? selectedPlace.name : (value ? 'Unknown Place' : `Select ${label}`);

  const handleSelectSaved = (placeId: string) => {
    onChange(placeId);
    setIsOpen(false);
  };

  const handleSearchSelect = async (destination: {lat: number, lng: number}, name: string) => {
    try {
      const newPlace = await api.savePlace({ name, lat: destination.lat, lng: destination.lng });
      setAdded((prev) => [...prev, newPlace]);
      if (onPlacesUpdated) onPlacesUpdated();
      onChange(newPlace._id);
      setIsOpen(false);
    } catch (e) {
      console.error('Failed to save place', e);
    }
  };

  const filteredPlaces = places.filter(p => p.name.toLowerCase().includes(search.toLowerCase()));

  return (
    <>
      <IonItem button onClick={() => setIsOpen(true)} detail={false}>
        <IonLabel color={value ? 'default' : 'medium'}>{displayName}</IonLabel>
      </IonItem>

      <IonModal isOpen={isOpen} onDidDismiss={() => setIsOpen(false)}>
        <IonHeader translucent>
          <IonToolbar className="glass">
            <IonButtons slot="start">
              <IonButton onClick={() => setIsOpen(false)}>Cancel</IonButton>
            </IonButtons>
            <IonTitle>Search Place</IonTitle>
          </IonToolbar>
        </IonHeader>
        <IonContent>
          <APIProvider apiKey={API_KEY}>
            <div style={{ padding: '16px' }}>
              <SearchField 
                value={search} 
                onValueChange={setSearch} 
                onSearch={handleSearchSelect} 
                placeholder="Search or enter address"
              />
            </div>
            {filteredPlaces.length > 0 && (
              <IonList>
                <IonListHeader>Saved Places</IonListHeader>
                {filteredPlaces.map(place => (
                  <IonItem button key={place._id} onClick={() => handleSelectSaved(place._id)}>
                    <IonIcon icon={locationOutline} slot="start" />
                    <IonLabel>
                      <h2>{place.name}</h2>
                      {place.address && <p>{place.address}</p>}
                    </IonLabel>
                  </IonItem>
                ))}
              </IonList>
            )}
          </APIProvider>
        </IonContent>
      </IonModal>
    </>
  );
}
