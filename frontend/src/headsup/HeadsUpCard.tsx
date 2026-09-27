import React, { useEffect, useRef, useState } from 'react';
import { IonCard, IonCardContent, IonButton, IonText } from '@ionic/react';
import { Haptics, NotificationType } from '@capacitor/haptics';
import type { UpcomingLeg } from '../lib/types';
import { openLink } from '../lib/deepLinks';
import HazardChips from '../components/HazardChips';
import { shortPlaceLabel } from '../routines/placeLabels';

const formatTime = (seconds: number) => {
  const mins = Math.round(seconds / 60);
  if (mins < 60) return `${mins} min`;
  const hrs = Math.floor(mins / 60);
  const remainingMins = mins % 60;
  return `${hrs} hr ${remainingMins} min`;
};

interface HeadsUpCardProps {
  leg: UpcomingLeg;
  timeOffsetMs?: number;
  onCustomize?: () => void;
}

const HeadsUpCard: React.FC<HeadsUpCardProps> = ({ leg, timeOffsetMs = 0, onCustomize }) => {
  const [now, setNow] = useState(() => new Date(Date.now() + timeOffsetMs));
  const warnedOccurrenceRef = useRef<string | null>(null);

  useEffect(() => {
    const timer = setInterval(() => {
      setNow(new Date(Date.now() + timeOffsetMs));
    }, 1000);
    return () => clearInterval(timer);
  }, [timeOffsetMs]);

  useEffect(() => {
    const occurrence = `${leg.routine_id}:${leg.leg}:${leg.departure_at}`;
    if (leg.top_hazards?.length && warnedOccurrenceRef.current !== occurrence) {
      warnedOccurrenceRef.current = occurrence;
      Haptics.notification({ type: NotificationType.Warning }).catch(() => {});
    }
  }, [leg.routine_id, leg.leg, leg.departure_at, leg.top_hazards]);

  const targetTime = leg.best_departure_at ? new Date(leg.best_departure_at) : new Date(leg.departure_at);
  const diffMs = targetTime.getTime() - now.getTime();
  const diffMins = Math.round(diffMs / 60000);

  const countdownText = diffMins > 0 
    ? `Leave in ${diffMins} min` 
    : diffMins === 0 
    ? "Leave now" 
    : `Left ${Math.abs(diffMins)} min ago`;

  return (
    <IonCard className="heads-up-card" style={{ margin: '0 0 16px 0', boxShadow: 'none' }}>
      <IonCardContent>
        {/* Countdown */}
        <h1
          className="heads-up-countdown dynamic-large-title"
          style={{ fontSize: '34px', fontWeight: 700, lineHeight: '41px' }}
        >
          {countdownText}
        </h1>

        {/* Route (Title 2) and Trip time */}
        <IonText color="dark">
          <h2 className="heads-up-route-title dynamic-title2">
            {shortPlaceLabel(leg.from.name)} → {shortPlaceLabel(leg.to.name)}
          </h2>
        </IonText>
        <IonText color="medium">
          <p className="dynamic-body" style={{ margin: '0 0 12px 0' }}>
            {formatTime(leg.duration_s)} trip
            {leg.window && leg.best_departure_at
              ? ` · Best time to leave ${new Date(leg.best_departure_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
              : ''}
          </p>
        </IonText>

        {/* Hazards */}
        {leg.top_hazards && leg.top_hazards.length > 0 && (
          <div style={{ marginBottom: '16px' }}>
            <HazardChips hazards={leg.top_hazards} />
          </div>
        )}

        {/* Buttons */}
        <div className="heads-up-actions">
          <IonButton 
            expand="block" 
            shape="round" 
            className="heads-up-action dynamic-headline"
            aria-label={`Start route from ${leg.from.name} to ${leg.to.name}`}
            onClick={() => {
              if (leg.deep_links.google_maps) {
                void openLink(leg.deep_links.google_maps).then(() =>
                  Haptics.notification({ type: NotificationType.Success }).catch(() => {})
                );
              }
            }}
          >
            Start
          </IonButton>
          <IonButton 
            expand="block" 
            shape="round" 
            className="heads-up-action dynamic-headline"
            aria-label={`Customize route from ${leg.from.name} to ${leg.to.name}`}
            style={{ 
              // Tinted, not filled: system blue at low opacity (docs/design.md, heads-up card).
              '--background': 'rgba(var(--ion-color-primary-rgb, 0, 122, 255), 0.12)',
              '--color': 'var(--ion-color-primary)',
              '--box-shadow': 'none'
            }}
            onClick={() => {
              if (onCustomize) onCustomize();
              else {
                window.dispatchEvent(new CustomEvent('open-customize', { 
                  detail: { routineId: leg.routine_id, legIndex: leg.leg } 
                }));
              }
            }}
          >
            Customize
          </IonButton>
        </div>
      </IonCardContent>
    </IonCard>
  );
};

export default HeadsUpCard;
