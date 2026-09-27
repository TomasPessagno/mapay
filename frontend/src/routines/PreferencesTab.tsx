import { useEffect, useState } from 'react';
import { IonItem, IonLabel, IonList, IonSegment, IonSegmentButton, IonSpinner } from '@ionic/react';
import { api } from '../lib/api';
import type { Preferences } from '../lib/types';
import PreferenceControls from '../components/PreferenceControls';
import { getDataSource, setDataSource, type DataSource } from '../lib/dataSource';

const SECTION_HEADER_STYLE: React.CSSProperties = {
  marginLeft: '16px',
  marginTop: '24px',
  marginBottom: '8px',
  fontSize: '14px',
  textTransform: 'uppercase',
  color: 'var(--ion-color-medium)'
};

function DataSourceSection() {
  const [source] = useState<DataSource>(() => getDataSource());

  const handleChange = (next: DataSource) => {
    if (next === source) return;
    setDataSource(next);
    // Reload so every screen refetches from the chosen source.
    window.location.reload();
  };

  return (
    <>
      <h2 style={SECTION_HEADER_STYLE}>Data</h2>
      <IonList inset>
        <IonItem>
          <IonLabel className="ion-text-wrap">
            <h2>Data source</h2>
            <p>Demo uses bundled sample data. Live uses the real Mapay backend.</p>
          </IonLabel>
        </IonItem>
        <IonItem lines="none">
          <IonSegment
            value={source}
            aria-label="Data source"
            onIonChange={(e) => handleChange(e.detail.value as DataSource)}
          >
            <IonSegmentButton value="demo">Demo</IonSegmentButton>
            <IonSegmentButton value="live">Live</IonSegmentButton>
          </IonSegment>
        </IonItem>
      </IonList>
    </>
  );
}

export default function PreferencesTab() {
  const [preferences, setPreferences] = useState<Preferences | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getPreferences().then(p => {
      setPreferences(p);
      setLoading(false);
    }).catch(err => {
      console.error(err);
      setLoading(false);
    });
  }, []);

  const handleSave = (p: Preferences) => {
    setPreferences(p);
    api.savePreferences(p).catch(console.error);
  };

  return (
    <>
      {loading ? (
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: '2rem' }}>
          <IonSpinner />
        </div>
      ) : preferences ? (
        <PreferenceControls
          preferences={preferences}
          onChange={handleSave}
        />
      ) : (
        <div className="ion-padding">Failed to load preferences</div>
      )}

      <DataSourceSection />
    </>
  );
}
