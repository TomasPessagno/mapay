import React from 'react';
import {
  IonModal,
  IonHeader,
  IonToolbar,
  IonTitle,
  IonContent,
  IonList,
  IonItem,
  IonLabel,
  IonToggle,
  IonIcon,
  IonButtons,
  IonButton
} from '@ionic/react';
import { HAZARD_TOKENS, TRAFFIC_COLORS } from '../map/legend';
import { GOOGLE_TRAFFIC_ID, getShowUnconfirmed, setShowUnconfirmed } from '../map/layers';
import type { HazardType } from '../lib/types';
import { closeOutline } from 'ionicons/icons';

interface Props {
  isOpen: boolean;
  onDidDismiss: () => void;
  toggled: Record<string, boolean>;
  onToggle: (id: string, visible: boolean) => void;
}

const LegendSheet: React.FC<Props> = ({ isOpen, onDidDismiss, toggled, onToggle }) => {
  const [isDark, setIsDark] = React.useState(
    window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
  );
  const [unconfirmed, setUnconfirmed] = React.useState(() => getShowUnconfirmed());

  React.useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e: MediaQueryListEvent) => setIsDark(e.matches);
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);

  const hazards = Object.keys(HAZARD_TOKENS) as HazardType[];

  return (
    <IonModal
      className="desktop-sidebar-sheet legend-sheet"
      isOpen={isOpen}
      onDidDismiss={onDidDismiss}
      initialBreakpoint={0.5}
      breakpoints={[0, 0.5, 0.85]}
      backdropBreakpoint={0.5}
    >
      <IonHeader className="ion-no-border">
        <IonToolbar className="glass">
          <IonTitle>Legend & Layers</IonTitle>
          <IonButtons slot="end">
            <IonButton onClick={onDidDismiss} aria-label="Close legend and layers">
              <IonIcon aria-hidden="true" icon={closeOutline} />
            </IonButton>
          </IonButtons>
        </IonToolbar>
      </IonHeader>
      <IonContent>
        <IonList inset>
          {hazards.map((hazard) => {
            const token = HAZARD_TOKENS[hazard];
            const color = isDark ? token.colorDark : token.colorLight;
            const isVisible = toggled[hazard] !== false; // default true
            return (
              <IonItem key={hazard}>
                <IonIcon 
                  slot="start" 
                  icon={token.icon} 
                  style={{ color }}
                  aria-hidden="true"
                />
                <IonLabel>
                  <h2>{token.name}</h2>
                  {hazard === 'congestion' && (
                    <div style={{ marginTop: '6px', height: '4px', background: `linear-gradient(to right, ${TRAFFIC_COLORS.moderate}, ${TRAFFIC_COLORS.heavy}, ${TRAFFIC_COLORS.severe})`, borderRadius: '2px', width: '100%' }} />
                  )}
                </IonLabel>
                <IonToggle 
                  slot="end" 
                  checked={isVisible}
                  aria-label={`Show ${token.name}`}
                  onIonChange={(e) => onToggle(hazard, e.detail.checked)}
                />
              </IonItem>
            );
          })}
        </IonList>

        <IonList inset>
          <IonItem>
            <IonLabel className="ion-text-wrap">
              <h2>Show unconfirmed</h2>
              <p>Hazards below 50% confidence, shown faintly</p>
            </IonLabel>
            <IonToggle
              slot="end"
              checked={unconfirmed}
              aria-label="Show unconfirmed hazards"
              onIonChange={(e) => {
                setUnconfirmed(e.detail.checked);
                setShowUnconfirmed(e.detail.checked);
              }}
            />
          </IonItem>
          <IonItem>
            <IonLabel className="ion-text-wrap">
              <h2>Google live traffic</h2>
              <p>Google's own traffic layer, drawn into the map; includes green for free-flowing roads</p>
            </IonLabel>
            <IonToggle
              slot="end"
              checked={toggled[GOOGLE_TRAFFIC_ID] === true}
              aria-label="Show Google live traffic"
              onIonChange={(e) => onToggle(GOOGLE_TRAFFIC_ID, e.detail.checked)}
            />
          </IonItem>
        </IonList>
      </IonContent>
    </IonModal>
  );
};

export default LegendSheet;
