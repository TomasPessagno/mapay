import React, { useState, useEffect, useRef } from 'react';
import { IonSearchbar, IonList, IonItem, IonLabel, IonIcon } from '@ionic/react';
import { useMapsLibrary } from '@vis.gl/react-google-maps';
import { locationOutline } from 'ionicons/icons';

interface SearchFieldProps {
  onSearch: (destination: {lat: number, lng: number}, name: string, address?: string, type?: string, placeId?: string) => void;
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
  const [error, setError] = useState(false);
  const placesLibrary = useMapsLibrary('places');
  const sessionTokenRef = useRef<google.maps.places.AutocompleteSessionToken | null>(null);

  useEffect(() => {
    if (!placesLibrary) return;
    if (!sessionTokenRef.current) {
      sessionTokenRef.current = new placesLibrary.AutocompleteSessionToken();
    }
  }, [placesLibrary]);

  // Debounced so typing doesn't send one billed Places request per keystroke.
  useEffect(() => {
    if (!placesLibrary || !query.trim()) {
      setSuggestions([]);
      setError(false);
      return;
    }
    let isActive = true;
    const timer = setTimeout(async () => {
      try {
        const result = await placesLibrary.AutocompleteSuggestion.fetchAutocompleteSuggestions({
          input: query,
          locationRestriction: MIAMI_DADE_BOUNDS,
          region: 'us',
          sessionToken: sessionTokenRef.current || undefined
        });
        if (isActive) {
          setSuggestions(result.suggestions ?? []);
          setError(false);
        }
      } catch (err) {
        console.warn('Places autocomplete failed', err);
        if (isActive) {
          setSuggestions([]);
          setError(true);
        }
      }
    }, 250);
    return () => { isActive = false; clearTimeout(timer); };
  }, [query, placesLibrary]);

  const visibleSuggestions = query.trim() ? suggestions : [];

  const handleSelect = async (suggestion: google.maps.places.AutocompleteSuggestion) => {
    if (!placesLibrary || !suggestion.placePrediction) return;
    try {
      const place = suggestion.placePrediction.toPlace();
      await place.fetchFields({fields: ['displayName', 'formattedAddress', 'location', 'id', 'types', 'primaryTypeDisplayName']});
      if (place.location) {
        const name = place.displayName || place.formattedAddress || query;
        setQuery(name);
        setSuggestions([]);
        // Start a new session for the next search
        sessionTokenRef.current = new placesLibrary.AutocompleteSessionToken();
        const typeStr = place.primaryTypeDisplayName || (place.types && place.types.length > 0 ? place.types[0].replace(/_/g, ' ') : undefined);
        onSearch({ lat: place.location.lat(), lng: place.location.lng() }, name, place.formattedAddress || undefined, typeStr, place.id);
      }
    } catch (e) {
      console.error(e);
      // Ensure we still pass something if Place fails entirely, or just throw
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
      {error && query.trim() ? (
        <div style={{ padding: '16px', textAlign: 'center', color: 'var(--ion-color-medium)' }}>
          <p>Search isn't available right now</p>
        </div>
      ) : (
        visibleSuggestions.length > 0 && (
          <IonList style={{ marginTop: '8px', background: 'transparent' }}>
            {visibleSuggestions.map((s, idx) => {
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
        )
      )}
    </>
  );
};

export default SearchField;
