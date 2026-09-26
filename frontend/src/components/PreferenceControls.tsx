import { useEffect, useState } from 'react';
import {
  IonItem, IonLabel, IonSelect, IonSelectOption,
  IonToggle, IonIcon, IonChip
} from '@ionic/react';
import { closeCircle } from 'ionicons/icons';
import { HAZARD_TOKENS } from '../map/legend';
import type { HazardType, Preferences, Neighborhood } from '../lib/types';
import { api } from '../lib/api';

interface Props {
  preferences: Preferences;
  onChange: (prefs: Preferences) => void;
  showNavApp?: boolean;
}

export default function PreferenceControls({ preferences, onChange, showNavApp = true }: Props) {
  const [neighborhoods, setNeighborhoods] = useState<Neighborhood[]>([]);

  useEffect(() => {
    api.neighborhoods().then(setNeighborhoods).catch(console.error);
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

  const hazardKeys: HazardType[] = [
    'flood', 'construction', 'congestion', 'closure', 'incident', 'weather', 'no_sidewalk', 'pothole', 'event'
  ];

  const avoidNeighborhoods = preferences.avoid_neighborhoods || [];

  return (
    <>
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

      <IonItem>
        <IonLabel position="stacked">Avoid Neighbourhoods</IonLabel>
        <div style={{ padding: '8px 0', display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
          {avoidNeighborhoods.map(id => {
            const n = neighborhoods.find(x => x.id === id);
            return (
              <IonChip key={id}>
                <IonLabel>{n ? n.name : id}</IonLabel>
                <IonIcon icon={closeCircle} onClick={() => handleRemoveNeighborhood(id)} />
              </IonChip>
            );
          })}
        </div>
        <IonSelect 
          placeholder="Add neighbourhood..."
          onIonChange={e => {
            if (e.detail.value) {
              handleChange('avoid_neighborhoods', [...avoidNeighborhoods, e.detail.value]);
              // Delay resetting the select so it closes properly first
              setTimeout(() => {
                e.target.value = null;
              }, 100);
            }
          }}
        >
          {neighborhoods.filter(n => !avoidNeighborhoods.includes(n.id)).map(n => (
            <IonSelectOption key={n.id} value={n.id}>{n.name}</IonSelectOption>
          ))}
        </IonSelect>
      </IonItem>

      <IonItem>
        <IonToggle 
          checked={preferences.avoid_tolls || false} 
          onIonChange={e => handleChange('avoid_tolls', e.detail.checked)}
        >
          Avoid Tolls
        </IonToggle>
      </IonItem>
      
      <IonItem>
        <IonToggle 
          checked={preferences.avoid_highways || false} 
          onIonChange={e => handleChange('avoid_highways', e.detail.checked)}
        >
          Avoid Highways
        </IonToggle>
      </IonItem>

      {showNavApp && (
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
      )}
    </>
  );
}
