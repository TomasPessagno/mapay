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

  const [suggestions, setSuggestions] = useState<google.maps.places.AutocompleteSuggestion[]>([]);
  const placesLibrary = useMapsLibrary('places');
  const sessionTokenRef = useRef<google.maps.places.AutocompleteSessionToken | null>(null);

  useEffect(() => {
    if (!placesLibrary) return;
    if (!sessionTokenRef.current) {
      sessionTokenRef.current = new placesLibrary.AutocompleteSessionToken();
    }
  }, [placesLibrary]);

  useEffect(() => {
    if (!placesLibrary || !query.trim()) {
      setSuggestions([]);
      return;
    }
    let isActive = true;
    const fetchSuggestions = async () => {
      try {
        const result = await placesLibrary.AutocompleteSuggestion.fetchAutocompleteSuggestions({
          input: query,
          locationRestriction: MIAMI_DADE_BOUNDS,
          region: 'us',
          sessionToken: sessionTokenRef.current || undefined
        });
        if (isActive && result.suggestions) {
          setSuggestions(result.suggestions);
        }
      } catch (e) {
        if (isActive) setSuggestions([]);
      }
    };
    fetchSuggestions();
    return () => { isActive = false; };
  }, [query, placesLibrary]);

  const handleSelect = async (suggestion: google.maps.places.AutocompleteSuggestion) => {
    if (!placesLibrary || !suggestion.placePrediction) return;
    try {
      const place = suggestion.placePrediction.toPlace();
      await place.fetchFields({fields: ['displayName', 'formattedAddress', 'location', 'id']});
      if (place.location) {
        const name = place.displayName || place.formattedAddress || query;
        setQuery(name);
        setSuggestions([]);
        // Start a new session for the next search
        sessionTokenRef.current = new placesLibrary.AutocompleteSessionToken();
        onSearch({ lat: place.location.lat(), lng: place.location.lng() }, name);
      }
    } catch (e) {
      console.error(e);
    }
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
          {suggestions.map((s, idx) => {
            if (!s.placePrediction) return null;
            const mainText = s.placePrediction.mainText?.toString() || s.placePrediction.text?.toString() || 'Unknown';
            const secondaryText = s.placePrediction.secondaryText?.toString() || '';
            return (
              <IonItem key={s.placePrediction.placeId || idx} button onClick={() => handleSelect(s)} lines="full">
                <IonIcon icon={locationOutline} slot="start" color="medium" />
                <IonLabel>
                  <h2>{mainText}</h2>
                  {secondaryText && <p>{secondaryText}</p>}
                </IonLabel>
              </IonItem>
            );
          })}
        </IonList>
      )}
    </>
  );
};

export default SearchField;
