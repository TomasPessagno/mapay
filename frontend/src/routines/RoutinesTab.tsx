import { useEffect, useState } from 'react';
import {
  IonList, IonItem, IonLabel, IonToggle,
  IonButton, IonIcon, IonModal, IonSpinner, IonToast
} from '@ionic/react';
import { add } from 'ionicons/icons';
import { api } from '../lib/api';
import type { Routine, Place } from '../lib/types';
import { refreshHeadsUps } from '../headsup/refresh';
import { headsUpToast } from '../headsup/schedule';
import RoutineEditor from './RoutineEditor';

export default function RoutinesTab() {
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [places, setPlaces] = useState<Place[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingRoutine, setEditingRoutine] = useState<Routine | null>(null);
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

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

  // After a save, re-run the whole heads-up sync and say when the next heads-up lands (#126).
  const refreshHeadsUp = async (routineId: string) => {
    const { next } = await refreshHeadsUps({ routineId });
    if (!next) return;
    const message = headsUpToast(next.leg, next.plan);
    if (message) setToast(message);
  };

  const toggleRoutine = async (routine: Routine, active: boolean) => {
    const updated = { ...routine, active };
    setRoutines(prev => prev.map(r => r._id === routine._id ? updated : r));
    try {
      const saved = await api.saveRoutine(updated);
      await refreshHeadsUp(saved._id);
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
      const saved = await api.saveRoutine(routine);
      await refreshHeadsUp(saved._id);
    } catch (err) {
      console.error(err);
      loadData();
    }
  };

  const formatRepeat = (repeat: Routine['repeat']) => {
    if (repeat.kind === 'daily') return 'Every day';
    if (repeat.kind === 'weekly') {
      const dayMap: Record<string, string> = {
        sun: 'Sunday', mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', sat: 'Saturday'
      };
      return `Every ${dayMap[repeat.weekday || 'mon']}`;
    }
    if (repeat.kind === 'custom') {
      if (repeat.weekdays?.length === 5 && !repeat.weekdays.includes('sat') && !repeat.weekdays.includes('sun')) {
        return 'Weekdays';
      }
      const shortMap: Record<string, string> = {
        sun: 'Sun', mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat'
      };
      return (repeat.weekdays || []).map(w => shortMap[w] || w).join(', ');
    }
    return 'Custom';
  };

  const formatTime = (timeStr?: string) => {
    if (!timeStr) return '';
    const [hh, mm] = timeStr.split(':');
    const d = new Date();
    d.setHours(parseInt(hh, 10), parseInt(mm, 10));
    const formatted = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: 'numeric' }).format(d);
    return formatted.replace(':00', ''); 
  };

  const formatWhen = (when: Routine['legs'][0]['when']) => {
    if (when.kind === 'at') {
      return formatTime(when.time);
    }
    const startStr = formatTime(when.start);
    const endStr = formatTime(when.end);
    
    // Attempt to condense '5 PM–7 PM' to '5–7 PM'
    const startMatch = startStr.match(/^(.*?)\s+([A-Za-z]+)$/);
    const endMatch = endStr.match(/^(.*?)\s+([A-Za-z]+)$/);
    if (startMatch && endMatch && startMatch[2] === endMatch[2]) {
      return `${startMatch[1]}–${endStr}`;
    }
    return `${startStr}–${endStr}`;
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', marginTop: '2rem' }}>
        <IonSpinner />
      </div>
    );
  }

  return (
    <div style={{ background: 'var(--ion-color-step-50, var(--system-grouped-background))', minHeight: '100%', paddingBottom: '16px' }}>
      <div style={{ height: '16px' }}></div>
      {routines.map(routine => (
        <IonList inset key={routine._id} style={{ marginBottom: '16px' }}>
          <IonItem lines="full">
            <IonLabel><strong>{routine.name}</strong></IonLabel>
            <IonToggle
              slot="end"
              checked={routine.active}
              onIonChange={e => toggleRoutine(routine, e.detail.checked)}
            />
          </IonItem>
          <IonItem button onClick={() => openEditor(routine)} detail lines="none">
            <IonLabel className="ion-text-wrap">
              {routine.legs.map((leg, i) => (
                <div key={i} style={{ marginBottom: '4px' }}>
                  <span style={{ color: 'var(--ion-text-color)' }}>{getPlaceName(leg.from_place)} → {getPlaceName(leg.to_place)}</span>
                  <span style={{ color: 'var(--ion-color-medium)' }}>
                    {' · '}{formatWhen(leg.when)}
                  </span>
                </div>
              ))}
              <p style={{ marginTop: '8px', color: 'var(--ion-color-medium)' }}>{formatRepeat(routine.repeat)}</p>
            </IonLabel>
          </IonItem>
        </IonList>
      ))}

      <div className="ion-padding-horizontal">
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

      <IonToast
        isOpen={toast !== null}
        message={toast ?? ''}
        duration={3000}
        position="top"
        onDidDismiss={() => setToast(null)}
      />
    </div>
  );
}
