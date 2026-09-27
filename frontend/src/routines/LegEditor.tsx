import {
  IonList, IonItem, IonLabel, IonSegment, IonSegmentButton, IonDatetimeButton, IonModal, IonDatetime
} from '@ionic/react';
import type { RoutineLeg, Place } from '../lib/types';
import PlacePicker from './PlacePicker';

interface LegEditorProps {
  leg: RoutineLeg;
  index: number;
  places: Place[];
  onChange: (leg: RoutineLeg) => void;
}

export default function LegEditor({ leg, index, places, onChange }: LegEditorProps) {
  const handleWhenKindChange = (kind: 'at' | 'window') => {
    if (kind === 'at') {
      onChange({ ...leg, when: { kind: 'at', time: '09:00' } });
    } else {
      onChange({ ...leg, when: { kind: 'window', start: '17:00', end: '19:00' } });
    }
  };

  const updateTime = (field: 'time' | 'start' | 'end', value: string) => {
    // IonDatetime returns a full ISO string. Extract the local HH:mm part.
    let timeString = '00:00';
    if (/^\d{2}:\d{2}/.test(value)) {
      timeString = value.substring(0, 5);
    } else {
      const match = value.match(/T(\d{2}:\d{2})/);
      if (match) {
        timeString = match[1];
      }
    }
    onChange({ ...leg, when: { ...leg.when, [field]: timeString } });
  };

  // Helper to convert HH:mm to a local ISO string (no 'Z') for IonDatetime.
  // No time set (a new leg starts empty) → null value; the picker keeps its own default.
  const getIso = (timeStr?: string) => {
    if (!timeStr) return null;
    return `2024-01-01T${timeStr}:00`;
  };

  return (
    <IonList inset>
      <IonItem>
        <IonLabel position="fixed">From</IonLabel>
        <PlacePicker 
          label="Origin" 
          value={leg.from_place} 
          places={places} 
          onChange={val => onChange({ ...leg, from_place: val })} 
        />
      </IonItem>
      <IonItem>
        <IonLabel position="fixed">To</IonLabel>
        <PlacePicker 
          label="Destination" 
          value={leg.to_place} 
          places={places} 
          onChange={val => onChange({ ...leg, to_place: val })} 
        />
      </IonItem>
      
      <IonItem>
        <IonSegment 
          value={leg.when.kind} 
          onIonChange={e => handleWhenKindChange(e.detail.value as 'at' | 'window')}
        >
          <IonSegmentButton value="at">
            <IonLabel>At</IonLabel>
          </IonSegmentButton>
          <IonSegmentButton value="window">
            <IonLabel>Between</IonLabel>
          </IonSegmentButton>
        </IonSegment>
      </IonItem>

      {leg.when.kind === 'at' && (
        <IonItem>
          <IonLabel>Time</IonLabel>
          <div style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
            {/* IonDatetimeButton falls back to "now" when the datetime has no value, so a new
                leg hides it under a "Set time" placeholder until the user picks one. */}
            <IonDatetimeButton
              datetime={`datetime-at-${index}`}
              style={leg.when.time ? undefined : { opacity: 0 }}
            />
            {!leg.when.time && (
              <span
                style={{
                  position: 'absolute',
                  inset: 0,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: 'var(--ion-color-medium)',
                  fontSize: '15px',
                  pointerEvents: 'none',
                }}
              >
                Set time
              </span>
            )}
          </div>
          <IonModal keepContentsMounted={true}>
            <IonDatetime 
              id={`datetime-at-${index}`}
              presentation="time" 
              value={getIso(leg.when.time)}
              onIonChange={e => updateTime('time', e.detail.value as string)}
            />
          </IonModal>
        </IonItem>
      )}

      {leg.when.kind === 'window' && (
        <>
          <IonItem>
            <IonLabel>Start Time</IonLabel>
            <IonDatetimeButton datetime={`datetime-start-${index}`} />
            <IonModal keepContentsMounted={true}>
              <IonDatetime 
                id={`datetime-start-${index}`}
                presentation="time" 
                value={getIso(leg.when.start)}
                onIonChange={e => updateTime('start', e.detail.value as string)}
              />
            </IonModal>
          </IonItem>
          <IonItem>
            <IonLabel>End Time</IonLabel>
            <IonDatetimeButton datetime={`datetime-end-${index}`} />
            <IonModal keepContentsMounted={true}>
              <IonDatetime 
                id={`datetime-end-${index}`}
                presentation="time" 
                value={getIso(leg.when.end)}
                onIonChange={e => updateTime('end', e.detail.value as string)}
              />
            </IonModal>
          </IonItem>
        </>
      )}
    </IonList>
  );
}
