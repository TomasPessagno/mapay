import React from 'react';
import { IonButton, IonIcon, IonText } from '@ionic/react';
import { closeOutline, navigateOutline, addOutline } from 'ionicons/icons';
import { openLink } from '../lib/deepLinks';

export interface PlaceData {
  location: { lat: number; lng: number };
  name: string;
  address?: string;
  type?: string;
  placeId?: string;
  distanceMiles?: number;
}

interface PlaceCardProps {
  place: PlaceData;
  onRoute: () => void;
  onAddToRoutine: () => void;
  onClose: () => void;
}

const PlaceCard: React.FC<PlaceCardProps> = ({ place, onRoute, onAddToRoutine, onClose }) => {
  const handleOpenGoogleMaps = () => {
    // using openLink
    const link = `https://www.google.com/maps/search/?api=1&query=${place.location.lat},${place.location.lng}${place.placeId ? `&query_place_id=${place.placeId}` : ''}`;
    openLink(link);
  };

  return (
    <div className="place-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
        <div>
          <IonText color="dark">
            <h2 className="dynamic-title2" style={{ fontWeight: 'bold', margin: '0 0 4px 0' }}>{place.name}</h2>
          </IonText>
          <IonText color="medium">
            <p className="dynamic-subheadline" style={{ margin: 0 }}>
              {place.type && <span style={{ textTransform: 'capitalize' }}>{place.type} · </span>}
              {place.distanceMiles !== undefined ? `${place.distanceMiles.toFixed(1)} mi` : ''}
            </p>
          </IonText>
        </div>
        <IonButton fill="clear" color="medium" onClick={onClose} aria-label={`Close ${place.name}`} style={{ margin: '-8px -8px 0 0', height: '44px' }}>
          <IonIcon aria-hidden="true" slot="icon-only" icon={closeOutline} />
        </IonButton>
      </div>
      
      {place.address && (
        <IonText color="medium">
          <p className="dynamic-subheadline" style={{ margin: '0 0 16px 0' }}>{place.address}</p>
        </IonText>
      )}

      <div style={{ display: 'flex', gap: '8px', marginTop: '16px' }}>
        <IonButton expand="block" shape="round" color="primary" onClick={onRoute} style={{ flex: 1, margin: 0 }}>
          <IonIcon slot="start" icon={navigateOutline} />
          Route
        </IonButton>
      </div>
      
      <div style={{ marginTop: '12px' }}>
        <IonButton expand="block" fill="clear" color="primary" onClick={handleOpenGoogleMaps}>
          Open in Google Maps
        </IonButton>
        <IonButton expand="block" fill="clear" color="primary" onClick={onAddToRoutine}>
          <IonIcon slot="start" icon={addOutline} />
          Add to routine
        </IonButton>
      </div>
    </div>
  );
};

export default PlaceCard;
