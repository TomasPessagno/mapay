import { useEffect, useState, useRef } from 'react';
import {
  IonItem, IonLabel, IonSelect, IonSelectOption,
  IonToggle, IonIcon, IonChip, IonList,
  IonModal, IonSearchbar, IonContent, IonHeader,
  IonToolbar, IonButtons, IonButton
} from '@ionic/react';
import { closeCircle, addOutline } from 'ionicons/icons';
import { HAZARD_TOKENS } from '../map/legend';
import type { HazardType, Preferences, Neighborhood } from '../lib/types';
import { api } from '../lib/api';

interface Props {
  preferences: Preferences;
  onChange: (prefs: Preferences) => void;
  showNavApp?: boolean;
}

const SECTION_HEADER_STYLE: React.CSSProperties = {
  marginLeft: '16px',
  marginTop: '24px',
  marginBottom: '8px',
  fontSize: '14px',
  textTransform: 'uppercase',
  color: 'var(--ion-color-medium)'
};

const getSourceHint = (source: string) => {
  if (source === 'city_of_miami') return 'City of Miami neighbourhood';
  if (source === 'municipality') return 'Municipality';
  if (source === 'census_place') return 'Census place';
  return source;
};

export default function PreferenceControls({ preferences, onChange, showNavApp = true }: Props) {
  const [initialNeighborhoods, setInitialNeighborhoods] = useState<Neighborhood[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Neighborhood[]>([]);
  const [showSearchModal, setShowSearchModal] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  const modalRef = useRef<HTMLIonModalElement>(null);

  useEffect(() => {
    // Initial fetch to resolve names of already selected IDs
    api.neighborhoods().then(setInitialNeighborhoods).catch(console.error);
  }, []);

  const handleChange = (field: keyof Preferences, value: unknown) => {
    onChange({ ...preferences, [field]: value });
  };

  const handleCategoryChange = (hazard: HazardType, value: string) => {
    onChange({
      ...preferences,
      categories: { ...(preferences.categories || {}), [hazard]: value as 'avoid' | 'prefer_avoid' | 'ignore' }
    });
  };

  const handleRemoveNeighborhood = (id: string) => {
    onChange({
      ...preferences,
      avoid_neighborhoods: (preferences.avoid_neighborhoods || []).filter(n => n !== id)
    });
  };

  const handleAddNeighborhood = (n: Neighborhood) => {
    const current = preferences.avoid_neighborhoods || [];
    if (!current.includes(n.id)) {
      handleChange('avoid_neighborhoods', [...current, n.id]);
    }
    modalRef.current?.dismiss();
    setSearchQuery('');
    setSearchResults([]);
  };

  const onSearchChange = (q: string | null | undefined) => {
    const safeQ = q || '';
    setSearchQuery(safeQ);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    
    if (!safeQ.trim()) {
      setSearchResults([]);
      return;
    }

    debounceRef.current = setTimeout(() => {
      api.neighborhoods(safeQ).then(setSearchResults).catch(console.error);
    }, 300);
  };

  const hazardKeys: HazardType[] = [
    'flood', 'construction', 'congestion', 'closure', 'incident', 'weather', 'no_sidewalk', 'pothole', 'event'
  ];

  const avoidNeighborhoods = preferences.avoid_neighborhoods || [];

  return (
    <>
      <h2 style={SECTION_HEADER_STYLE}>Hazards</h2>
      <IonList inset>
        {hazardKeys.map(hazard => {
          const token = HAZARD_TOKENS[hazard];
          return (
            <IonItem key={hazard}>
              <IonIcon icon={token.icon} slot="start" style={{ color: `var(--ion-color-${hazard}, ${token.colorLight})` }} />
              <IonLabel>{token.name}</IonLabel>
              <IonSelect 
                value={preferences.categories?.[hazard] || 'ignore'} 
                onIonChange={e => handleCategoryChange(hazard, e.detail.value)}
                interface="popover"
              >
                <IonSelectOption value="avoid">Avoid</IonSelectOption>
                <IonSelectOption value="prefer_avoid">Prefer to avoid</IonSelectOption>
                <IonSelectOption value="ignore">Don't care</IonSelectOption>
              </IonSelect>
            </IonItem>
          );
        })}
      </IonList>

      <h2 style={SECTION_HEADER_STYLE}>Neighbourhoods to avoid</h2>
      <IonList inset>
        {avoidNeighborhoods.length > 0 && (
          <IonItem>
            <div style={{ padding: '12px 0', display: 'flex', flexWrap: 'wrap', gap: '6px', width: '100%' }}>
              {avoidNeighborhoods.map(id => {
                const n = initialNeighborhoods.find(x => x.id === id);
                return (
                  <IonChip key={id} style={{ margin: 0 }}>
                    <IonLabel>{n ? n.name : id}</IonLabel>
                    <IonIcon icon={closeCircle} onClick={() => handleRemoveNeighborhood(id)} />
                  </IonChip>
                );
              })}
            </div>
          </IonItem>
        )}
        <IonItem button detail={false} onClick={() => setShowSearchModal(true)}>
          <IonIcon icon={addOutline} slot="start" color="primary" />
          <IonLabel color="primary">Add a neighbourhood</IonLabel>
        </IonItem>
      </IonList>

      <IonModal
        ref={modalRef}
        isOpen={showSearchModal}
        onDidDismiss={() => setShowSearchModal(false)}
        initialBreakpoint={0.5}
        breakpoints={[0, 0.5, 0.75, 1]}
      >
        <IonHeader className="ion-no-border">
          <IonToolbar>
            <IonSearchbar 
              placeholder="Search neighbourhoods..."
              value={searchQuery}
              onIonInput={e => onSearchChange(e.detail.value!)}
              debounce={0} // We handle debounce manually to avoid delay in typing feel
            />
            <IonButtons slot="end">
              <IonButton onClick={() => modalRef.current?.dismiss()}>Cancel</IonButton>
            </IonButtons>
          </IonToolbar>
        </IonHeader>
        <IonContent>
          <IonList>
            {searchResults.map(n => (
              <IonItem key={n.id} button onClick={() => handleAddNeighborhood(n)}>
                <IonLabel>
                  {n.name}
                  {n.source && <p style={{ fontSize: '12px', color: 'var(--ion-color-medium)' }}>{getSourceHint(n.source)}</p>}
                </IonLabel>
              </IonItem>
            ))}
            {searchQuery && searchResults.length === 0 && (
              <IonItem>
                <IonLabel color="medium">No results found</IonLabel>
              </IonItem>
            )}
            {!searchQuery && (
              <IonItem>
                <IonLabel color="medium">Type to search...</IonLabel>
              </IonItem>
            )}
          </IonList>
        </IonContent>
      </IonModal>

      <h2 style={SECTION_HEADER_STYLE}>Route</h2>
      <IonList inset>
        <IonItem>
          <IonToggle 
            checked={preferences.avoid_tolls || false} 
            onIonChange={e => handleChange('avoid_tolls', e.detail.checked)}
          >
            Avoid tolls
          </IonToggle>
        </IonItem>
        
        <IonItem>
          <IonToggle 
            checked={preferences.avoid_highways || false} 
            onIonChange={e => handleChange('avoid_highways', e.detail.checked)}
          >
            Avoid highways
          </IonToggle>
        </IonItem>
      </IonList>

      {showNavApp && (
        <>
          <h2 style={SECTION_HEADER_STYLE}>Navigate with</h2>
          <IonList inset>
            <IonItem>
              <IonLabel>Navigate with</IonLabel>
              <IonSelect 
                value={preferences.nav_app || 'google_maps'} 
                onIonChange={e => handleChange('nav_app', e.detail.value)}
              >
                <IonSelectOption value="google_maps">Google Maps</IonSelectOption>
                <IonSelectOption value="apple_maps">Apple Maps</IonSelectOption>
                <IonSelectOption value="waze">Waze</IonSelectOption>
              </IonSelect>
            </IonItem>
          </IonList>
          <div style={{ marginLeft: '16px', marginRight: '16px', marginTop: '-8px', fontSize: '13px', color: 'var(--ion-color-medium)' }}>
            Apple Maps and Waze get origin → destination only.
          </div>
        </>
      )}
    </>
  );
}
