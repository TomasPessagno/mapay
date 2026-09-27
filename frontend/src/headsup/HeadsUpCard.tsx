import React, { useEffect, useState } from 'react';
import { IonCard, IonCardContent, IonButton, IonText, IonIcon, IonChip } from '@ionic/react';
import { Haptics, NotificationType } from '@capacitor/haptics';
import type { UpcomingLeg } from '../lib/types';
import { openLink } from '../lib/deepLinks';
import { waterOutline, warningOutline, constructOutline, stopCircleOutline, carOutline, alertCircleOutline } from 'ionicons/icons';

const getHazardIcon = (type: string) => {
  switch (type) {
    case 'flood': return waterOutline;
    case 'weather': return warningOutline;
    case 'construction': return constructOutline;
    case 'closure': return stopCircleOutline;
    case 'congestion': return carOutline;
    default: return alertCircleOutline;
  }
};

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

  useEffect(() => {
    const timer = setInterval(() => {
      setNow(new Date(Date.now() + timeOffsetMs));
    }, 1000);
    return () => clearInterval(timer);
  }, [timeOffsetMs]);

  useEffect(() => {
    if (leg.top_hazards && leg.top_hazards.length > 0) {
      Haptics.notification({ type: NotificationType.Warning }).catch(() => {});
    }
  }, [leg.routine_id, leg.leg, leg.top_hazards]);

  const targetTime = leg.best_departure_at ? new Date(leg.best_departure_at) : new Date(leg.departure_at);
  const diffMs = targetTime.getTime() - now.getTime();
  const diffMins = Math.round(diffMs / 60000);

  const countdownText = diffMins > 0 
    ? `Leave in ${diffMins} min` 
    : diffMins === 0 
    ? "Leave now" 
    : `Left ${Math.abs(diffMins)} min ago`;

  return (
    <IonCard style={{ borderRadius: '26px', margin: '0 0 16px 0', boxShadow: 'none', background: 'var(--secondary-system-background)' }}>
      <IonCardContent>
        {/* Countdown */}
        <h1 style={{ 
          fontFamily: "ui-rounded, 'SF Pro Rounded', system-ui, sans-serif",
          fontSize: '34px', 
          fontWeight: 'bold', 
          color: 'var(--ion-color-dark)',
          margin: '0 0 12px 0'
        }}>
          {countdownText}
        </h1>

        {/* Route (Title 2) and Trip time */}
        <IonText color="dark">
          <h2 style={{ fontSize: '22px', fontWeight: 'bold', margin: '0 0 4px 0' }}>
            {leg.from.name} → {leg.to.name}
          </h2>
        </IonText>
        <IonText color="medium">
          <p style={{ margin: '0 0 12px 0', fontSize: '17px' }}>
            {formatTime(leg.duration_s)} trip
            {leg.window && leg.best_departure_at
              ? ` · Best time to leave ${new Date(leg.best_departure_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
              : ''}
          </p>
        </IonText>

        {/* Hazards */}
        {leg.top_hazards && leg.top_hazards.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '16px' }}>
            {leg.top_hazards.map((h, i) => (
              <IonChip key={i} outline style={{ margin: 0 }}>
                <IonIcon icon={getHazardIcon(h.hazard_type)} />
                {h.title}
              </IonChip>
            ))}
          </div>
        )}

        {/* Buttons */}
        <div style={{ display: 'flex', gap: '12px' }}>
          <IonButton 
            expand="block" 
            shape="round" 
            style={{ flex: 1, margin: 0 }}
            onClick={() => {
              if (leg.deep_links.google_maps) {
                openLink(leg.deep_links.google_maps);
              }
            }}
          >
            Start
          </IonButton>
          <IonButton 
            expand="block" 
            shape="round" 
            style={{ 
              flex: 1, 
              margin: 0, 
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
