import { useState } from 'react';
import {
  IonModal,
  IonContent,
  IonButton,
  IonIcon,
  IonItem,
  IonLabel,
  IonList,
  IonNote,
} from '@ionic/react';
import { HAZARD_TOKENS } from '../map/legend';
import { api } from '../lib/api';

export interface HazardSource {
  kind: string;
  label: string;
  url: string | null;
  observed_at: string | null;
  pass_time?: string | null;
}

export interface HazardProperties {
  hazard_id: string;
  hazard_type: string;
  // Live features are looser than the mock: NWS weather alerts have no place, and some layers
  // omit title/sources. The sheet must render whatever the layer actually sent.
  title?: string | null;
  place?: string | null;
  probability?: number | null;
  status?: string | null;
  severity?: number | null;
  sources?: HazardSource[] | null;
  last_updated?: string | null;
  expires_at?: string | null;
  lat?: number;
  lng?: number;
}

interface HazardSheetProps {
  isOpen: boolean;
  hazard: HazardProperties | null;
  onDidDismiss: () => void;
}

const DIRECTIONS = new Set(['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']);

// "NW 24TH ST" → "NW 24th St"; already mixed-case names are left alone.
function titleCaseStreetName(value: string | null | undefined): string {
  if (!value || /[a-z]/.test(value)) return value ?? '';
  return value.toLowerCase().replace(/\S+/g, (word) => {
    if (/^\d+(st|nd|rd|th)$/.test(word)) return word;
    if (DIRECTIONS.has(word)) return word.toUpperCase();
    return word.charAt(0).toUpperCase() + word.slice(1);
  });
}

export default function HazardSheet({ isOpen, hazard, onDidDismiss }: HazardSheetProps) {
  const [reporting, setReporting] = useState(false);

  if (!hazard) {
    return (
      <IonModal isOpen={isOpen} onDidDismiss={onDidDismiss} initialBreakpoint={0.5} breakpoints={[0, 0.5]}>
        <IonContent className="ion-padding" />
      </IonModal>
    );
  }

  const token = HAZARD_TOKENS[hazard.hazard_type as keyof typeof HAZARD_TOKENS] || HAZARD_TOKENS.incident;
  const isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  const color = isDark ? token.colorDark : token.colorLight;

  // "Weather alert" is a fine title when the layer has none (NWS features are title-only).
  const title = titleCaseStreetName(hazard.title) || token.name;
  const place = titleCaseStreetName(hazard.place);
  // City GIS repeats the street as title and place; don't show the same line twice.
  const showPlace = place.length > 0 && place.trim().toLowerCase() !== title.trim().toLowerCase();
  const sources = hazard.sources ?? [];
  const probability = typeof hazard.probability === 'number' ? hazard.probability : 1;

  let confidence = 'High';
  if (probability < 0.73) confidence = 'Unconfirmed';
  else if (probability < 0.9) confidence = 'Medium';

  const isPredicted = hazard.status === 'predicted';
  const canReport = typeof hazard.lat === 'number' && typeof hazard.lng === 'number';

  const handleReport = async (cleared: boolean) => {
    if (!canReport) return;
    setReporting(true);
    try {
      await api.report({
        type: hazard.hazard_type,
        lat: hazard.lat as number,
        lng: hazard.lng as number,
        hazard_id: hazard.hazard_id,
        cleared
      });
      onDidDismiss();
    } catch (e) {
      console.error(e);
    } finally {
      setReporting(false);
    }
  };

  const formatTime = (isoString: string | null) => {
    if (!isoString) return '';
    try {
      const d = new Date(isoString);
      const now = new Date();
      const diffMs = d.getTime() - now.getTime();
      const diffMinutes = Math.round(diffMs / 60000);
      const absMinutes = Math.abs(diffMinutes);
      const hours = Math.floor(absMinutes / 60);
      const mins = absMinutes % 60;
      
      let str = '';
      if (hours > 0) {
        str += `${hours} hour${hours > 1 ? 's' : ''}`;
        if (mins > 0) str += ` ${mins} min${mins > 1 ? 's' : ''}`;
      } else {
        str += `${mins} min${mins > 1 ? 's' : ''}`;
      }
      
      return diffMinutes > 0 ? `in ${str}` : `${str} ago`;
    } catch {
      return '';
    }
  };

  return (
    <IonModal
      isOpen={isOpen}
      onDidDismiss={onDidDismiss}
      initialBreakpoint={0.5}
      breakpoints={[0, 0.5, 0.75, 1]}
      aria-label={`Hazard Details: ${title}`}
    >
      <IonContent className="ion-padding">
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: '16px' }}>
          <div
            style={{
              width: '40px',
              height: '40px',
              borderRadius: '50%',
              backgroundColor: `${color}33`,
              color: color,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginRight: '12px',
            }}
            aria-hidden="true"
          >
            {/* token.icon is an Ionicons data URL, not markup */}
            <IonIcon icon={token.icon} style={{ fontSize: '22px', color }} />
          </div>
          <div>
            <h2 style={{ margin: 0, fontSize: '22px', fontWeight: 'bold' }}>{title}</h2>
            {showPlace && (
              <p style={{ margin: 0, color: 'var(--ion-color-step-600)', fontSize: '17px' }}>{place}</p>
            )}
          </div>
        </div>

        <IonList inset>
          <IonItem>
            <IonLabel>
              <h2>Confidence</h2>
            </IonLabel>
            <IonNote slot="end">{isPredicted ? 'Predicted' : confidence}</IonNote>
          </IonItem>

          {hazard.expires_at && (
            <IonItem>
              <IonLabel>
                <h2>Expires</h2>
              </IonLabel>
              <IonNote slot="end">{formatTime(hazard.expires_at)}</IonNote>
            </IonItem>
          )}
        </IonList>

        {sources.length > 0 && (
          <>
            <h3 style={{ marginLeft: '16px', marginTop: '24px', fontSize: '15px', textTransform: 'uppercase', color: 'var(--ion-color-step-600)' }}>
              Sources
            </h3>
            <IonList inset>
              {sources.map((src, idx) => (
                <IonItem key={idx} href={src.url || undefined} target={src.url ? '_blank' : undefined}>
                  <IonLabel className="ion-text-wrap">
                    <h2>{src.label}</h2>
                    <p>
                      {src.pass_time
                        ? `Satellite pass ${formatTime(src.pass_time)}`
                        : src.observed_at
                        ? `Observed ${formatTime(src.observed_at)}`
                        : ''}
                    </p>
                  </IonLabel>
                </IonItem>
              ))}
            </IonList>
          </>
        )}

        <div style={{ display: 'flex', gap: '12px', padding: '16px 0' }}>
          <IonButton
            expand="block"
            fill="outline"
            style={{ flex: 1 }}
            disabled={reporting || !canReport}
            onClick={() => handleReport(true)}
            aria-label="Report Cleared"
          >
            Cleared
          </IonButton>
          <IonButton
            expand="block"
            style={{ flex: 1 }}
            disabled={reporting || !canReport}
            onClick={() => handleReport(false)}
            aria-label="Report Still there"
          >
            Still there
          </IonButton>
        </div>
      </IonContent>
    </IonModal>
  );
}
