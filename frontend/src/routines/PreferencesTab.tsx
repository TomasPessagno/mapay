import { useEffect, useState } from 'react';
import { IonList, IonSpinner } from '@ionic/react';
import { api } from '../lib/api';
import type { Preferences } from '../lib/types';
import PreferenceControls from '../components/PreferenceControls';

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

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', marginTop: '2rem' }}>
        <IonSpinner />
      </div>
    );
  }

  if (!preferences) {
    return <div className="ion-padding">Failed to load preferences</div>;
  }

  return (
    <IonList inset>
      <PreferenceControls 
        preferences={preferences} 
        onChange={handleSave} 
      />
    </IonList>
  );
}
