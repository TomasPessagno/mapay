import React, { useState, useRef } from 'react';
import { 
  IonModal, IonContent, IonButton, IonTextarea, IonChip, IonIcon, 
  IonSpinner, IonText, IonCard, IonCardContent
} from '@ionic/react';
import { closeOutline, addOutline, warningOutline, timeOutline, navigateOutline } from 'ionicons/icons';
import { api } from '../lib/api';
import { isDemo } from '../lib/dataSource';
import { getRouteContext, type LatLngContext } from '../lib/routeContext';
import HazardChips from '../components/HazardChips';
import type { CustomizeResponse, RouteOption, RouteResponse } from '../lib/types';
import { openLink } from '../lib/deepLinks';

interface CustomizeSheetProps {
  isOpen: boolean;
  onClose: () => void;
  routineId?: string;
  legIndex?: number;
  initialPrompt?: string;
}

const isNotFound = (err: unknown) => err instanceof Error && /^404\b/.test(err.message);

// A routine that only lives in the app (Demo user, widget deep link) can't be found by the API.
// Resolve its endpoints from the app's own routines + places so we can retry without it.
async function routineEndpoints(
  routineId: string,
  legIndex?: number,
): Promise<{ origin?: LatLngContext; destination?: LatLngContext }> {
  try {
    const [routines, places] = await Promise.all([api.routines(), api.places()]);
    const leg = routines.find((routine) => routine._id === routineId)?.legs?.[legIndex ?? 0];
    const from = places.find((place) => place._id === leg?.from_place);
    const to = places.find((place) => place._id === leg?.to_place);
    if (from && to) {
      return {
        origin: { lat: from.location.coordinates[1], lng: from.location.coordinates[0] },
        destination: { lat: to.location.coordinates[1], lng: to.location.coordinates[0] },
      };
    }
  } catch {
    // fall through: no endpoints to retry with
  }
  return {};
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

  // POST /customize takes either {prompt, routine_id, leg} or {prompt, origin, destination}
  // (backend/app/routers/customize.py, public/mocks/README.md). A route picked from search has no
  // routine, so it uses the endpoints of the route on the map.
  const buildBody = (): Record<string, unknown> | null => {
    const context = getRouteContext();
    const departAt = context.departAt ? { depart_at: context.departAt } : {};
    if (routineId) return { prompt, routine_id: routineId, leg: legIndex ?? 0, ...departAt };
    if (!context.origin || !context.destination) return null;
    return { prompt, origin: context.origin, destination: context.destination, ...departAt };
  };

  const handleCustomize = async () => {
    if (!prompt.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const body = buildBody();
      if (!body && !isDemo()) {
        setError('Pick a destination on the map first, then try Customize again.');
        return;
      }
      let res: CustomizeResponse;
      try {
        res = await api.customize(body ?? { prompt }) as CustomizeResponse;
      } catch (err) {
        if (!routineId || !isNotFound(err)) throw err;
        // The routine only exists in the app: retry once from the endpoints we do know.
        const context = getRouteContext();
        const fallback = await routineEndpoints(routineId, legIndex);
        const origin = context.origin ?? fallback.origin;
        const destination = context.destination ?? fallback.destination;
        if (!origin || !destination) throw err;
        const departAt = context.departAt ? { depart_at: context.departAt } : {};
        res = await api.customize({ prompt, origin, destination, ...departAt }) as CustomizeResponse;
      }
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
    <IonCard style={{ margin: '0 0 12px 0', borderRadius: '16px', background: 'var(--secondary-system-background)', boxShadow: 'none' }}>
      <IonCardContent>
        <IonText color="dark">
          <h3 className="dynamic-headline" style={{ fontWeight: 'bold', margin: '0 0 4px 0' }}>{title}</h3>
        </IonText>
        <p style={{ margin: '0 0 4px 0', fontSize: '15px' }}>{route.summary}</p>
        <p style={{ margin: 0, fontSize: '15px', color: 'var(--ion-color-medium)' }}>
          {formatTime(route.duration_s)} · {Math.round((route.distance_m || 0) / 1609.34)} mi
        </p>
        {route.hazards_on_route && route.hazards_on_route.length > 0 && (
          <div style={{ marginTop: '8px' }}>
            <HazardChips hazards={route.hazards_on_route} />
          </div>
        )}
      </IonCardContent>
    </IonCard>
  );

  return (
    <IonModal
      className="desktop-sidebar-sheet customize-route-sheet"
      ref={modal}
      isOpen={isOpen}
      onWillPresent={handleOpen}
      onDidDismiss={onClose}
      breakpoints={[0.9]}
      initialBreakpoint={0.9}
      backdropDismiss={true}
    >
      <IonContent className="ion-padding">
        <div className="customize-sheet-header glass" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 className="dynamic-title2" style={{ fontWeight: 'bold', margin: 0 }}>Customize Route</h2>
          <IonButton fill="clear" onClick={onClose} aria-label="Close customize route" style={{ margin: 0, '--padding-end': 0 }}>
            <IonIcon aria-hidden="true" icon={closeOutline} slot="icon-only" />
          </IonButton>
        </div>

        <IonTextarea
          aria-label="Describe how you want to change this route"
          placeholder="e.g. stop at a Starbucks and stay off the Palmetto"
          value={prompt}
          onIonInput={e => setPrompt(e.detail.value!)}
          rows={3}
          style={{ 
            '--background': 'var(--secondary-system-background)', 
            '--color': 'var(--label)',
            '--placeholder-color': 'var(--secondary-label)',
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
          <IonChip outline onClick={() => addChip('Add a stop')} aria-label="Add a stop to the route">
            <IonIcon aria-hidden="true" icon={addOutline} /> Add a stop
          </IonChip>
          <IonChip outline onClick={() => addChip('Avoid floods')} aria-label="Avoid floods">
            <IonIcon aria-hidden="true" icon={warningOutline} /> Avoid floods
          </IonChip>
          <IonChip outline onClick={() => addChip('Leave later')} aria-label="Leave later">
            <IonIcon aria-hidden="true" icon={timeOutline} /> Leave later
          </IonChip>
          <IonChip outline onClick={() => addChip('Avoid a neighbourhood')} aria-label="Avoid a neighbourhood">
            <IonIcon aria-hidden="true" icon={navigateOutline} /> Avoid a neighbourhood
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
