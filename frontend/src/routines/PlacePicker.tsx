import { useState } from 'react';
import {
  IonModal, IonHeader, IonToolbar, IonTitle, IonButtons, IonButton,
  IonContent, IonSearchbar, IonList, IonItem, IonLabel, IonIcon
} from '@ionic/react';
import { locationOutline } from 'ionicons/icons';
import type { Place } from '../lib/types';

interface PlacePickerProps {
  label: string;
  value: string; // place ID
  places: Place[];
  onChange: (placeId: string) => void;
}

export default function PlacePicker({ label, value, places, onChange }: PlacePickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [search, setSearch] = useState('');

  const selectedPlace = places.find(p => p._id === value);
  const displayName = selectedPlace ? selectedPlace.name : (value ? 'Unknown Place' : `Select ${label}`);

  const handleSelect = (placeId: string) => {
    onChange(placeId);
    setIsOpen(false);
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
          <IonToolbar className="glass">
            <IonSearchbar 
              value={search} 
              onIonInput={e => setSearch(e.detail.value!)} 
              placeholder="Search or enter address" 
            />
          </IonToolbar>
        </IonHeader>
        <IonContent>
          <IonList>
            {filteredPlaces.map(place => (
              <IonItem button key={place._id} onClick={() => handleSelect(place._id)}>
                <IonIcon icon={locationOutline} slot="start" />
                <IonLabel>
                  <h2>{place.name}</h2>
                  {place.address && <p>{place.address}</p>}
                </IonLabel>
              </IonItem>
            ))}
            {/* Mocking autocomplete results if typing something new */}
            {search && filteredPlaces.length === 0 && (
              <IonItem button onClick={() => handleSelect(`mock-${search}`)}>
                <IonIcon icon={locationOutline} slot="start" />
                <IonLabel>
                  <h2>{search}</h2>
                  <p>Mock place autocomplete result</p>
                </IonLabel>
              </IonItem>
            )}
          </IonList>
        </IonContent>
      </IonModal>
    </>
  );
}
