import React from 'react';
import { IonCard, IonCardContent, IonButton, IonText, IonChip, IonIcon } from '@ionic/react';
import type { RouteResponse, RouteOption } from '../lib/types';
import { openLink } from '../lib/deepLinks';
import HazardChips from './HazardChips';
import { Haptics, NotificationType } from '@capacitor/haptics';
import { closeOutline } from 'ionicons/icons';
import TimeScrubber from './TimeScrubber';
import { formatClockTime } from '../lib/departureTime';

interface RouteOptionsProps {
  response: RouteResponse;
  selectedIndex: number;
  onSelect: (index: number) => void;
  onClose: () => void;
  departureTime: Date;
  selectedDeparture: Date | null;
  onDepartureChange: (departure: Date | null) => void;
  onAddToRoutine: () => void;
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

const RouteOptions: React.FC<RouteOptionsProps> = ({
  response,
  selectedIndex,
  onSelect,
  onClose,
  departureTime,
  selectedDeparture,
  onDepartureChange,
  onAddToRoutine,
}) => {
  // Handle case where API might return `alternatives` instead of `routes` in mock
  const routes: RouteOption[] = response.routes || (response as unknown as { alternatives?: RouteOption[] }).alternatives || [];

  if (!routes.length) return null;

  const selectedRoute = routes[selectedIndex] ?? routes[0];
  const arrivalTime = new Date(departureTime.getTime() + selectedRoute.duration_s * 1000);
  const departureSummary = `${selectedDeparture ? `Leave at ${formatClockTime(selectedDeparture)}` : 'Leave now'} · arrive ${formatClockTime(arrivalTime)}`;

  return (
    <div className="route-options">
      <div className="route-options-header">
        <div>
          <IonText color="dark"><h2 className="dynamic-title2" style={{ fontWeight: 'bold', margin: 0 }}>Route Options</h2></IonText>
        </div>
        <IonButton fill="clear" color="medium" onClick={onClose} aria-label="Close route options" style={{ margin: 0, height: '44px' }}>
          <IonIcon aria-hidden="true" slot="icon-only" icon={closeOutline} />
        </IonButton>
      </div>
      <div className="route-time-control">
        <TimeScrubber
          compact
          compactLabel={departureSummary}
          value={selectedDeparture}
          onChange={onDepartureChange}
        />
      </div>
      <div className="route-options-list">
        <div className="route-options-secondary-actions">
          <IonButton
            expand="block"
            fill="clear"
            color="medium"
            onClick={() => {
              const link = response.deep_links?.apple_maps;
              if (link) void openLink(link).then(() => Haptics.notification({ type: NotificationType.Success }).catch(() => {}));
            }}
            disabled={!response.deep_links?.apple_maps}
          >
            Apple Maps
          </IonButton>
          <IonButton expand="block" fill="clear" color="primary" onClick={onAddToRoutine}>
            Add to routine
          </IonButton>
        </div>
        {routes.map((route, i) => (
          <IonCard
            key={i}
            button={true}
            aria-label={`${route.recommended ? 'Recommended route. ' : ''}${formatTime(route.duration_s)}, ${formatDistance(route.distance_m)}${route.hazards_on_route?.length ? `, ${route.hazards_on_route.length} hazards` : ', no reported hazards'}`}
            aria-pressed={selectedIndex === i}
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
                    <h2 className="dynamic-title2" style={{ fontWeight: 'bold', margin: '0 0 4px 0' }}>{formatTime(route.duration_s)}</h2>
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

      </div>
      <div className="route-options-footer glass">
        <div className="route-options-actions">
          <IonButton
            expand="block"
            shape="round"
            onClick={() => {
              const link = response.deep_links?.google_maps;
              if (link) void openLink(link).then(() => Haptics.notification({ type: NotificationType.Success }).catch(() => {}));
            }}
            disabled={!response.deep_links?.google_maps}
          >
            Start
          </IonButton>
          <IonButton
            expand="block"
            shape="round"
            fill="clear"
            onClick={() => window.dispatchEvent(new CustomEvent('open-customize'))}
          >
            Customize
          </IonButton>
        </div>
      </div>
    </div>
  );
};

export default RouteOptions;
