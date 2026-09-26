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
import { HAZARD_TOKENS } from '../map/legend';
import type { HazardType } from '../lib/types';
import { closeOutline } from 'ionicons/icons';

interface Props {
  isOpen: boolean;
  onDidDismiss: () => void;
  toggled: Record<string, boolean>;
  onToggle: (id: string, visible: boolean) => void;
}

const LegendSheet: React.FC<Props> = ({ isOpen, onDidDismiss, toggled, onToggle }) => {
  const isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;

  const hazards = Object.keys(HAZARD_TOKENS) as HazardType[];

  return (
    <IonModal
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
            <IonButton onClick={onDidDismiss}>
              <IonIcon icon={closeOutline} />
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
                />
                <IonLabel>
                  <h2>{token.name}</h2>
                  <p>{token.drawnAs}</p>
                </IonLabel>
                <IonToggle 
                  slot="end" 
                  checked={isVisible} 
                  onIonChange={(e) => onToggle(hazard, e.detail.checked)}
                />
              </IonItem>
            );
          })}
        </IonList>
      </IonContent>
    </IonModal>
  );
};

export default LegendSheet;
