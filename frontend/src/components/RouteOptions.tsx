import React from 'react';
import { IonCard, IonCardContent, IonButton, IonText, IonChip, IonIcon } from '@ionic/react';
import type { RouteResponse, RouteOption } from '../lib/types';
import { openLink } from '../lib/deepLinks';
import HazardChips from './HazardChips';
import { closeOutline } from 'ionicons/icons';

interface RouteOptionsProps {
  response: RouteResponse;
  selectedIndex: number;
  onSelect: (index: number) => void;
  onClose: () => void;
}

const formatTime = (seconds: number) => {
  const mins = Math.round(seconds / 60);
  if (mins < 60) return `${mins} min`;
  const hrs = Math.floor(mins / 60);
  const remainingMins = mins % 60;
  return `${hrs} hr ${remainingMins} min`;
};

const formatDistance = (meters: number) => {
  const miles = meters * 0.000621371;
  return `${miles.toFixed(1)} mi`;
};

const RouteOptions: React.FC<RouteOptionsProps> = ({ response, selectedIndex, onSelect, onClose }) => {
  // Handle case where API might return `alternatives` instead of `routes` in mock
  const routes: RouteOption[] = response.routes || (response as unknown as { alternatives?: RouteOption[] }).alternatives || [];

  if (!routes.length) return null;

  return (
    <div className="route-options">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <IonText color="dark"><h2 style={{ fontSize: '22px', fontWeight: 'bold', margin: 0 }}>Route Options</h2></IonText>
        <IonButton fill="clear" color="medium" onClick={onClose} style={{ margin: 0, height: '32px' }}>
          <IonIcon slot="icon-only" icon={closeOutline} />
        </IonButton>
      </div>
      {routes.map((route, i) => (
        <IonCard 
          key={i} 
          onClick={() => onSelect(i)}
          style={{ 
            border: selectedIndex === i ? '2px solid var(--ion-color-primary)' : '2px solid transparent',
            margin: '0 0 16px 0',
            borderRadius: '22px',
            boxShadow: 'none',
            background: 'var(--secondary-system-background)'
          }}
        >
          <IonCardContent>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <IonText color="dark">
                  <h2 style={{ fontSize: '22px', fontWeight: 'bold', margin: '0 0 4px 0' }}>{formatTime(route.duration_s)}</h2>
                </IonText>
                <IonText color="medium">
                  <p style={{ margin: 0 }}>{formatDistance(route.distance_m)} · {route.summary}</p>
                </IonText>
              </div>
              {route.recommended && (
                <IonChip color="success" style={{ margin: 0 }}>
                  Recommended
                </IonChip>
              )}
            </div>

            {route.hazards_on_route && route.hazards_on_route.length > 0 && (
              <div style={{ marginTop: '12px' }}>
                <HazardChips hazards={route.hazards_on_route} />
              </div>
            )}
          </IonCardContent>
        </IonCard>
      ))}

      {response.briefing && (
        <div style={{ padding: '0 8px 16px' }}>
          <IonText color="medium">
            <p>{response.briefing}</p>
          </IonText>
        </div>
      )}

      <div style={{ marginTop: '16px' }}>
        <IonButton 
          expand="block" 
          shape="round" 
          onClick={() => response.deep_links?.google_maps && openLink(response.deep_links.google_maps)}
          disabled={!response.deep_links?.google_maps}
        >
          Open in Google Maps
        </IonButton>
        <IonButton 
          expand="block" 
          fill="clear" 
          color="medium"
          onClick={() => response.deep_links?.apple_maps && openLink(response.deep_links.apple_maps)}
          disabled={!response.deep_links?.apple_maps}
        >
          Apple Maps
        </IonButton>
      </div>
    </div>
  );
};

export default RouteOptions;
