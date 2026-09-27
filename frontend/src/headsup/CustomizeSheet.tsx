import React, { useState, useRef } from 'react';
import { 
  IonModal, IonContent, IonButton, IonTextarea, IonChip, IonIcon, 
  IonSpinner, IonText, IonCard, IonCardContent
} from '@ionic/react';
import { closeOutline, addOutline, warningOutline, timeOutline, navigateOutline } from 'ionicons/icons';
import { api } from '../lib/api';
import type { CustomizeResponse, RouteOption, RouteResponse } from '../lib/types';
import { openLink } from '../lib/deepLinks';

interface CustomizeSheetProps {
  isOpen: boolean;
  onClose: () => void;
  routineId?: string;
  legIndex?: number;
  initialPrompt?: string;
}

const CustomizeSheet: React.FC<CustomizeSheetProps> = ({ isOpen, onClose, routineId, legIndex, initialPrompt = '' }) => {
  const modal = useRef<HTMLIonModalElement>(null);
  const [prompt, setPrompt] = useState(initialPrompt);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CustomizeResponse | null>(null);

  const handleOpen = () => {
    setPrompt(initialPrompt);
    setResult(null);
    setError(null);
    setLoading(false);
  };

  const handleCustomize = async () => {
    if (!prompt.trim()) return;
    setLoading(true);
    setError(null);
    try {
      // Post to /customize API
      const res = await api.customize({ prompt, routineId, legIndex }) as CustomizeResponse;
      setResult(res);
      
      const syntheticRouteResponse: RouteResponse = {
        routes: [res.new_route],
        waypoints: [],
        hazards_on_route: res.new_route.hazards_on_route || [],
        deep_links: res.deep_links,
        briefing: res.explanation
      };
      window.dispatchEvent(new CustomEvent('update-map-route', { detail: { routeResponse: syntheticRouteResponse } }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to customize route");
    } finally {
      setLoading(false);
    }
  };

  const addChip = (text: string) => {
    setPrompt(prev => prev ? `${prev}, ${text}` : text);
  };

  const formatTime = (seconds?: number) => {
    if (!seconds) return '';
    const mins = Math.round(seconds / 60);
    if (mins < 60) return `${mins} min`;
    return `${Math.floor(mins / 60)} hr ${mins % 60} min`;
  };

  const renderRouteCard = (title: string, route: RouteOption) => (
    <IonCard style={{ margin: '0 0 12px 0', borderRadius: '16px', background: 'var(--ion-color-step-50, #f2f2f7)', boxShadow: 'none' }}>
      <IonCardContent>
        <IonText color="dark">
          <h3 style={{ fontSize: '17px', fontWeight: 'bold', margin: '0 0 4px 0' }}>{title}</h3>
        </IonText>
        <p style={{ margin: '0 0 4px 0', fontSize: '15px' }}>{route.summary}</p>
        <p style={{ margin: 0, fontSize: '15px', color: 'var(--ion-color-medium)' }}>
          {formatTime(route.duration_s)} · {Math.round((route.distance_m || 0) / 1609.34)} mi
        </p>
      </IonCardContent>
    </IonCard>
  );

  return (
    <IonModal
      ref={modal}
      isOpen={isOpen}
      onWillPresent={handleOpen}
      onDidDismiss={onClose}
      breakpoints={[0.9]}
      initialBreakpoint={0.9}
      backdropDismiss={true}
    >
      <IonContent className="ion-padding">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h2 style={{ fontSize: '22px', fontWeight: 'bold', margin: 0 }}>Customize Route</h2>
          <IonButton fill="clear" onClick={onClose} style={{ margin: 0, '--padding-end': 0 }}>
            <IonIcon icon={closeOutline} slot="icon-only" />
          </IonButton>
        </div>

        <IonTextarea
          placeholder="e.g. stop at a Starbucks and stay off the Palmetto"
          value={prompt}
          onIonInput={e => setPrompt(e.detail.value!)}
          rows={3}
          style={{ 
            background: 'var(--ion-color-step-50, #f2f2f7)', 
            borderRadius: '12px', 
            padding: '8px 12px',
            marginBottom: '12px',
            '--padding-top': '8px',
            '--padding-bottom': '8px',
            '--padding-start': '12px',
            '--padding-end': '12px'
          } as React.CSSProperties}
        />

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '24px' }}>
          <IonChip outline onClick={() => addChip('Add a stop')}>
            <IonIcon icon={addOutline} /> Add a stop
          </IonChip>
          <IonChip outline onClick={() => addChip('Avoid floods')}>
            <IonIcon icon={warningOutline} /> Avoid floods
          </IonChip>
          <IonChip outline onClick={() => addChip('Leave later')}>
            <IonIcon icon={timeOutline} /> Leave later
          </IonChip>
          <IonChip outline onClick={() => addChip('Avoid a neighbourhood')}>
            <IonIcon icon={navigateOutline} /> Avoid a neighbourhood
          </IonChip>
        </div>

        <IonButton 
          expand="block" 
          shape="round" 
          onClick={handleCustomize} 
          disabled={!prompt.trim() || loading}
          style={{ marginBottom: '24px' }}
        >
          {loading ? <IonSpinner name="crescent" /> : "Customize"}
        </IonButton>

        {error && (
          <IonText color="danger">
            <p>{error}</p>
          </IonText>
        )}

        {result && (
          <div>
            <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
              <div style={{ flex: 1 }}>
                {renderRouteCard("Old Route", result.old_route)}
              </div>
              <div style={{ flex: 1 }}>
                {renderRouteCard("New Route", result.new_route)}
              </div>
            </div>

            <IonText color="medium">
              <p style={{ fontSize: '16px', lineHeight: '1.4', marginBottom: '24px' }}>
                {result.explanation}
              </p>
            </IonText>

            <IonButton 
              expand="block" 
              shape="round"
              onClick={() => {
                if (result.deep_links.google_maps) {
                  openLink(result.deep_links.google_maps);
                }
              }}
            >
              Open in Google Maps
            </IonButton>
          </div>
        )}
      </IonContent>
    </IonModal>
  );
};

export default CustomizeSheet;
