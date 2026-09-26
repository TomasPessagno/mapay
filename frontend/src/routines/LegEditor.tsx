import {
  IonList, IonItem, IonLabel, IonSegment, IonSegmentButton, IonDatetimeButton, IonModal, IonDatetime
} from '@ionic/react';
import type { RoutineLeg, Place } from '../lib/types';
import PlacePicker from './PlacePicker';

interface LegEditorProps {
  leg: RoutineLeg;
  places: Place[];
  onChange: (leg: RoutineLeg) => void;
}

export default function LegEditor({ leg, places, onChange }: LegEditorProps) {
  const handleWhenKindChange = (kind: 'at' | 'window') => {
    if (kind === 'at') {
      onChange({ ...leg, when: { kind: 'at', time: '09:00' } });
    } else {
      onChange({ ...leg, when: { kind: 'window', start: '17:00', end: '19:00' } });
    }
  };

  const updateTime = (field: 'time' | 'start' | 'end', value: string) => {
    // value from IonDatetime is ISO string, we just want HH:mm
    const date = new Date(value);
    const timeString = `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`;
    onChange({ ...leg, when: { ...leg.when, [field]: timeString } });
  };

  // Helper to convert HH:mm to ISO for IonDatetime
  const getIso = (timeStr?: string) => {
    const today = new Date();
    if (!timeStr) return today.toISOString();
    const [hh, mm] = timeStr.split(':');
    today.setHours(parseInt(hh, 10), parseInt(mm, 10), 0, 0);
    return today.toISOString();
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
          <IonDatetimeButton datetime={`datetime-at-${leg.from_place}-${leg.to_place}`} />
          <IonModal keepContentsMounted={true}>
            <IonDatetime 
              id={`datetime-at-${leg.from_place}-${leg.to_place}`}
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
            <IonDatetimeButton datetime={`datetime-start-${leg.from_place}-${leg.to_place}`} />
            <IonModal keepContentsMounted={true}>
              <IonDatetime 
                id={`datetime-start-${leg.from_place}-${leg.to_place}`}
                presentation="time" 
                value={getIso(leg.when.start)}
                onIonChange={e => updateTime('start', e.detail.value as string)}
              />
            </IonModal>
          </IonItem>
          <IonItem>
            <IonLabel>End Time</IonLabel>
            <IonDatetimeButton datetime={`datetime-end-${leg.from_place}-${leg.to_place}`} />
            <IonModal keepContentsMounted={true}>
              <IonDatetime 
                id={`datetime-end-${leg.from_place}-${leg.to_place}`}
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
