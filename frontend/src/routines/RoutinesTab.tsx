import { useEffect, useState } from 'react';
import {
  IonList, IonItem, IonLabel, IonToggle, IonItemGroup, IonItemDivider,
  IonButton, IonIcon, IonModal, IonSpinner
} from '@ionic/react';
import { add } from 'ionicons/icons';
import { api } from '../lib/api';
import type { Routine, Place } from '../lib/types';
import RoutineEditor from './RoutineEditor';

export default function RoutinesTab() {
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [places, setPlaces] = useState<Place[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingRoutine, setEditingRoutine] = useState<Routine | null>(null);
  const [isEditorOpen, setIsEditorOpen] = useState(false);

  const loadData = async () => {
    try {
      setLoading(true);
      const [rData, pData] = await Promise.all([
        api.routines(),
        api.places() as Promise<Place[]>
      ]);
      setRoutines(rData);
      setPlaces(pData);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // eslint-disable-next-line
    loadData();
  }, []);


  const getPlaceName = (id: string) => {
    const p = places.find(p => p._id === id);
    return p ? p.name : id;
  };

  const toggleRoutine = async (routine: Routine, active: boolean) => {
    const updated = { ...routine, active };
    setRoutines(prev => prev.map(r => r._id === routine._id ? updated : r));
    try {
      await api.saveRoutine(updated);
    } catch (err) {
      console.error(err);
      // revert on fail
      setRoutines(prev => prev.map(r => r._id === routine._id ? routine : r));
    }
  };

  const openEditor = (routine?: Routine) => {
    if (routine) {
      setEditingRoutine(routine);
    } else {
      setEditingRoutine({
        _id: `new-${Date.now()}`,
        user_id: '',
        name: 'New Routine',
        active: true,
        repeat: { kind: 'custom', weekdays: ['mon', 'tue', 'wed', 'thu', 'fri'] },
        legs: [],
        tz: Intl.DateTimeFormat().resolvedOptions().timeZone || 'America/New_York',
        heads_up_minutes: 30
      });
    }
    setIsEditorOpen(true);
  };

  const handleSave = async (routine: Routine) => {
    setIsEditorOpen(false);
    const isNew = !routines.some(r => r._id === routine._id);
    if (isNew) {
      setRoutines(prev => [...prev, routine]);
    } else {
      setRoutines(prev => prev.map(r => r._id === routine._id ? routine : r));
    }
    
    try {
      await api.saveRoutine(routine);
    } catch (err) {
      console.error(err);
      loadData();
    }
  };

  const formatRepeat = (repeat: Routine['repeat']) => {
    if (repeat.kind === 'daily') return 'Every day';
    if (repeat.kind === 'weekly') return `Weekly on ${repeat.weekdays?.[0] || '?'}`;
    if (repeat.kind === 'custom') {
      if (repeat.weekdays?.length === 5 && !repeat.weekdays.includes('sat') && !repeat.weekdays.includes('sun')) {
        return 'Weekdays';
      }
      return (repeat.weekdays || []).map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(', ');
    }
    return 'Custom';
  };

  const formatWhen = (when: Routine['legs'][0]['when']) => {
    if (when.kind === 'at') {
      return `at ${when.time}`;
    }
    return `between ${when.start} and ${when.end}`;
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', marginTop: '2rem' }}>
        <IonSpinner />
      </div>
    );
  }

  return (
    <>
      <IonList inset>
        {routines.map(routine => (
          <IonItemGroup key={routine._id}>
            <IonItemDivider>
              <IonLabel>{routine.name}</IonLabel>
              <IonToggle
                slot="end"
                checked={routine.active}
                onIonChange={e => toggleRoutine(routine, e.detail.checked)}
              />
            </IonItemDivider>
            <IonItem button onClick={() => openEditor(routine)} detail>
              <IonLabel className="ion-text-wrap">
                {routine.legs.map((leg, i) => (
                  <div key={i} style={{ marginBottom: '4px' }}>
                    <strong>{getPlaceName(leg.from_place)} → {getPlaceName(leg.to_place)}</strong>
                    <span style={{ color: 'var(--ion-color-medium)', marginLeft: '8px' }}>
                      {formatWhen(leg.when)}
                    </span>
                  </div>
                ))}
                <p style={{ marginTop: '8px' }}>{formatRepeat(routine.repeat)}</p>
              </IonLabel>
            </IonItem>
          </IonItemGroup>
        ))}
      </IonList>

      <div className="ion-padding">
        <IonButton expand="block" onClick={() => openEditor()}>
          <IonIcon slot="start" icon={add} />
          Add Routine
        </IonButton>
      </div>

      <IonModal isOpen={isEditorOpen} onDidDismiss={() => setIsEditorOpen(false)}>
        {editingRoutine && (
          <RoutineEditor
            routine={editingRoutine}
            places={places}
            onSave={handleSave}
            onCancel={() => setIsEditorOpen(false)}
          />
        )}
      </IonModal>
    </>
  );
}
