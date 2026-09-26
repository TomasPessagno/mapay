import React, { useState, useEffect, useRef } from 'react';
import { IonSearchbar, IonList, IonItem, IonLabel, IonIcon } from '@ionic/react';
import { useMapsLibrary } from '@vis.gl/react-google-maps';
import { locationOutline } from 'ionicons/icons';

interface SearchFieldProps {
  onSearch: (destination: {lat: number, lng: number}, name: string) => void;
  onFocus?: () => void;
  placeholder?: string;
  value?: string;
  onValueChange?: (value: string) => void;
}

const MIAMI_DADE_BOUNDS = {
  north: 25.979,
  south: 25.214,
  east: -80.089,
  west: -80.875
};

const SearchField: React.FC<SearchFieldProps> = ({ onSearch, onFocus, placeholder = "Where to?", value, onValueChange }) => {
  const [internalQuery, setInternalQuery] = useState('');
  const query = value !== undefined ? value : internalQuery;
  const setQuery = (v: string) => {
    setInternalQuery(v);
    if (onValueChange) onValueChange(v);
  };

  const [suggestions, setSuggestions] = useState<google.maps.places.AutocompletePrediction[]>([]);
  const placesLibrary = useMapsLibrary('places');
  const autocompleteService = useRef<google.maps.places.AutocompleteService | null>(null);
  const placesService = useRef<google.maps.places.PlacesService | null>(null);

  useEffect(() => {
    if (!placesLibrary) return;
    autocompleteService.current = new placesLibrary.AutocompleteService();
    // Dummy element for PlacesService
    const div = document.createElement('div');
    placesService.current = new placesLibrary.PlacesService(div);
  }, [placesLibrary]);

  useEffect(() => {
    if (!autocompleteService.current || !query.trim()) {
      setSuggestions([]);
      return;
    }
    autocompleteService.current.getPlacePredictions({
      input: query,
      locationBias: MIAMI_DADE_BOUNDS,
      componentRestrictions: { country: 'us' }
    }, (results, status) => {
      if (status === google.maps.places.PlacesServiceStatus.OK && results) {
        setSuggestions(results);
      } else {
        setSuggestions([]);
      }
    });
  }, [query]);

  const handleSelect = (placeId: string, description: string) => {
    if (!placesService.current) return;
    placesService.current.getDetails({
      placeId,
      fields: ['geometry', 'name']
    }, (place, status) => {
      if (status === google.maps.places.PlacesServiceStatus.OK && place?.geometry?.location) {
        setQuery(place.name || description);
        setSuggestions([]);
        onSearch({ lat: place.geometry.location.lat(), lng: place.geometry.location.lng() }, place.name || description);
      }
    });
  };

  return (
    <>
      <IonSearchbar
        value={query}
        onIonInput={(e) => setQuery(e.detail.value!)}
        onIonFocus={onFocus}
        placeholder={placeholder}
        mode="ios"
        className="ion-no-padding"
      />
      {suggestions.length > 0 && (
        <IonList style={{ marginTop: '8px', background: 'transparent' }}>
          {suggestions.map((s) => (
            <IonItem key={s.place_id} button onClick={() => handleSelect(s.place_id, s.description)} lines="full">
              <IonIcon icon={locationOutline} slot="start" color="medium" />
              <IonLabel>
                <h2>{s.structured_formatting.main_text}</h2>
                <p>{s.structured_formatting.secondary_text}</p>
              </IonLabel>
            </IonItem>
          ))}
        </IonList>
      )}
    </>
  );
};

export default SearchField;
