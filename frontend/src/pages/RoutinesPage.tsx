import React, { useRef, useState } from 'react';
import { IonActionSheet, IonContent, IonHeader, IonPage, IonTitle, IonToast, IonToolbar, useIonRouter } from '@ionic/react';
import RoutinesTab from '../routines/RoutinesTab';
import { api } from '../lib/api';
import type { UpcomingLeg } from '../lib/types';
import { fireHeadsUpNow } from '../headsup/demo';

const LONG_PRESS_MS = 600;

// Hidden demo menu (#36): long-press the Routines title → pick a leg → "Fire heads-up now".
function useDemoMenu() {
  const router = useIonRouter();
  const [legs, setLegs] = useState<UpcomingLeg[] | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const open = () => {
    api.upcomingRoutines(7)
      .then(({ items }) => {
        // One entry per leg (upcoming lists every occurrence).
        const seen = new Set<string>();
        setLegs(items.filter(leg => !seen.has(`${leg.routine_id}:${leg.leg}`) && seen.add(`${leg.routine_id}:${leg.leg}`)));
      })
      .catch(err => setToast(`Couldn't load the routines: ${err instanceof Error ? err.message : err}`));
  };

  const fire = (leg: UpcomingLeg) => {
    fireHeadsUpNow({ routineId: leg.routine_id, leg: leg.leg })
      .then(() => {
        setToast('Heads-up fired. Lock the phone: the notification arrives in 10 s.');
        router.push('/map', 'root');
      })
      .catch(err => setToast(`Couldn't fire the heads-up: ${err instanceof Error ? err.message : err}`));
  };

  const pressProps = {
    onPointerDown: () => { timer.current = window.setTimeout(open, LONG_PRESS_MS); },
    onPointerUp: () => window.clearTimeout(timer.current),
    onPointerLeave: () => window.clearTimeout(timer.current),
    onPointerCancel: () => window.clearTimeout(timer.current),
    style: { userSelect: 'none', WebkitUserSelect: 'none', WebkitTouchCallout: 'none' } as React.CSSProperties,
  };

  const menu = (
    <>
      <IonActionSheet
        isOpen={legs !== null}
        header="Fire heads-up now"
        subHeader="Starts the Live Activity, sends the notification in 10 s and switches the widget and the map card."
        buttons={[
          ...(legs ?? []).map(leg => ({
            text: `${leg.from.name} → ${leg.to.name} · ${leg.routine_name}`,
            handler: () => fire(leg),
          })),
          { text: 'Cancel', role: 'cancel' },
        ]}
        onDidDismiss={() => setLegs(null)}
      />
      <IonToast isOpen={toast !== null} message={toast ?? ''} duration={4000} position="top" onDidDismiss={() => setToast(null)} />
    </>
  );

  return { pressProps, menu };
}

const RoutinesPage: React.FC = () => {
  const { pressProps, menu } = useDemoMenu();
  return (
    <IonPage className="routines-page">
      <IonHeader translucent={true} className="ion-no-border">
        <IonToolbar className="glass">
          <IonTitle {...pressProps}>Routines</IonTitle>
        </IonToolbar>
      </IonHeader>
      <IonContent fullscreen={true} className="ion-padding-bottom">
        <IonHeader collapse="condense">
          <IonToolbar>
            <IonTitle size="large" {...pressProps}>Routines</IonTitle>
          </IonToolbar>
        </IonHeader>

        <RoutinesTab />
      </IonContent>
      {menu}
    </IonPage>
  );
};

export default RoutinesPage;
