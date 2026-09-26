import { useState } from 'react';
import {
  IonHeader, IonToolbar, IonTitle, IonButtons, IonButton, IonContent,
  IonList, IonItem, IonLabel, IonInput, IonSelect, IonSelectOption,
  IonIcon, IonItemGroup, IonItemDivider, IonNote
} from '@ionic/react';
import { add, trash } from 'ionicons/icons';
import type { Routine, RoutineLeg, Place } from '../lib/types';
import LegEditor from './LegEditor';

interface RoutineEditorProps {
  routine: Routine;
  places: Place[];
  onSave: (routine: Routine) => void;
  onCancel: () => void;
}

export default function RoutineEditor({ routine, places, onSave, onCancel }: RoutineEditorProps) {
  const [edited, setEdited] = useState<Routine>(routine);

  const handleChange = (field: keyof Routine, value: unknown) => {
    setEdited(prev => ({ ...prev, [field]: value }));
  };

  const handleLegChange = (index: number, newLeg: RoutineLeg) => {
    const newLegs = [...edited.legs];
    newLegs[index] = newLeg;
    setEdited(prev => ({ ...prev, legs: newLegs }));
  };

  const removeLeg = (index: number) => {
    setEdited(prev => ({
      ...prev,
      legs: prev.legs.filter((_, i) => i !== index)
    }));
  };

  const addLeg = () => {
    setEdited(prev => ({
      ...prev,
      legs: [...prev.legs, {
        from_place: '',
        to_place: '',
        when: { kind: 'at', time: '09:00' },
        anchor: 'depart',
        days: null
      }]
    }));
  };

  const addReturnLeg = (leg: RoutineLeg) => {
    setEdited(prev => ({
      ...prev,
      legs: [...prev.legs, {
        from_place: leg.to_place,
        to_place: leg.from_place,
        when: { kind: 'window', start: '17:00', end: '19:00' },
        anchor: 'depart',
        days: null
      }]
    }));
  };

  const weekdays = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];

  const toggleDay = (day: string) => {
    const currentDays = edited.repeat.weekdays || [];
    const newDays = currentDays.includes(day)
      ? currentDays.filter(d => d !== day)
      : [...currentDays, day];
    
    setEdited(prev => ({
      ...prev,
      repeat: { ...prev.repeat, weekdays: newDays }
    }));
  };

  return (
    <>
      <IonHeader translucent>
        <IonToolbar className="glass">
          <IonButtons slot="start">
            <IonButton onClick={onCancel}>Cancel</IonButton>
          </IonButtons>
          <IonTitle>Edit Routine</IonTitle>
          <IonButtons slot="end">
            <IonButton strong onClick={() => onSave(edited)}>Save</IonButton>
          </IonButtons>
        </IonToolbar>
      </IonHeader>
      
      <IonContent className="ion-padding">
        <IonList inset>
          <IonItem>
            <IonLabel position="stacked">Routine Name</IonLabel>
            <IonInput 
              value={edited.name} 
              onIonChange={e => handleChange('name', e.detail.value!)} 
            />
          </IonItem>
        </IonList>

        <h2 style={{ marginLeft: '16px' }}>Legs</h2>
        
        {edited.legs.map((leg, i) => (
          <IonItemGroup key={i} style={{ marginBottom: '16px' }}>
            <LegEditor 
              leg={leg} 
              places={places}
              onChange={newLeg => handleLegChange(i, newLeg)} 
            />
            <div className="ion-padding-horizontal ion-padding-bottom" style={{ display: 'flex', gap: '8px' }}>
              <IonButton fill="outline" size="small" onClick={() => addReturnLeg(leg)}>
                Add the way back
              </IonButton>
              <IonButton fill="clear" color="danger" size="small" onClick={() => removeLeg(i)}>
                <IonIcon icon={trash} slot="icon-only" />
              </IonButton>
            </div>
          </IonItemGroup>
        ))}

        <div className="ion-padding-horizontal">
          <IonButton fill="outline" expand="block" onClick={addLeg}>
            <IonIcon icon={add} slot="start" />
            Add Leg
          </IonButton>
        </div>

        <h2 style={{ marginLeft: '16px', marginTop: '24px' }}>Settings</h2>
        <IonList inset>
          <IonItem>
            <IonLabel>Repeat</IonLabel>
            <IonSelect 
              value={edited.repeat.kind} 
              onIonChange={e => setEdited(prev => ({ 
                ...prev, 
                repeat: { ...prev.repeat, kind: e.detail.value } 
              }))}
            >
              <IonSelectOption value="daily">Every day</IonSelectOption>
              <IonSelectOption value="weekly">Every week</IonSelectOption>
              <IonSelectOption value="custom">Custom</IonSelectOption>
            </IonSelect>
          </IonItem>
          
          {edited.repeat.kind === 'weekly' && (
            <IonItem>
              <IonLabel>Day of week</IonLabel>
              <IonSelect 
                value={edited.repeat.weekdays?.[0] || 'mon'} 
                onIonChange={e => setEdited(prev => ({
                  ...prev,
                  repeat: { ...prev.repeat, weekdays: [e.detail.value] }
                }))}
              >
                {weekdays.map(d => (
                  <IonSelectOption key={d} value={d}>{d.toUpperCase()}</IonSelectOption>
                ))}
              </IonSelect>
            </IonItem>
          )}

          {edited.repeat.kind === 'custom' && (
            <IonItem>
              <div style={{ display: 'flex', gap: '8px', padding: '8px 0', overflowX: 'auto', width: '100%' }}>
                {['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'].map(day => (
                  <IonButton 
                    key={day}
                    size="small"
                    fill={edited.repeat.weekdays?.includes(day) ? 'solid' : 'outline'}
                    onClick={() => toggleDay(day)}
                  >
                    {day.charAt(0).toUpperCase()}
                  </IonButton>
                ))}
              </div>
            </IonItem>
          )}

          <IonItem>
            <IonLabel>Heads-up (minutes before)</IonLabel>
            <IonSelect 
              value={edited.heads_up_minutes} 
              onIonChange={e => handleChange('heads_up_minutes', parseInt(e.detail.value, 10))}
            >
              <IonSelectOption value={15}>15 min</IonSelectOption>
              <IonSelectOption value={30}>30 min</IonSelectOption>
              <IonSelectOption value={45}>45 min</IonSelectOption>
              <IonSelectOption value={60}>60 min</IonSelectOption>
            </IonSelect>
          </IonItem>

          <IonItemDivider>
            <IonLabel>Preferences Override</IonLabel>
          </IonItemDivider>
          <IonItem>
            <IonNote>Preference controls from B6 goes here.</IonNote>
          </IonItem>
        </IonList>
      </IonContent>
    </>
  );
}
