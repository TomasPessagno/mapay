import { Navigate, Route } from 'react-router-dom';
import {
  IonApp,
  IonBadge,
  IonIcon,
  IonLabel,
  IonRouterOutlet,
  IonTabBar,
  IonTabButton,
  IonTabs,
} from '@ionic/react';
import { IonReactRouter } from '@ionic/react-router';
import { mapOutline, timeOutline, settingsOutline } from 'ionicons/icons';
import { App as CapacitorApp } from '@capacitor/app';
import { useEffect, useState } from 'react';
import { useHeadsUpSync } from './headsup/refresh';
import { useDeepLinks } from './headsup/deeplinks';

// Pages
import MapPage from './pages/MapPage';
import RoutinesPage from './pages/RoutinesPage';
import PreferencesPage from './pages/PreferencesPage';
import CustomizeSheet from './headsup/CustomizeSheet';
import ErrorBoundary from './components/ErrorBoundary';
import { getDataSource, isDemo, setDataSource, type DataSource } from './lib/dataSource';

const DesktopDataSourceSwitch: React.FC = () => {
  const [source, setSource] = useState<DataSource>(() => getDataSource());

  const selectSource = (next: DataSource) => {
    if (next === source) return;
    setDataSource(next);
    setSource(next);
    window.location.reload();
  };

  return (
    <div className="desktop-source-switch glass" role="group" aria-label="Map data source">
      <button type="button" aria-pressed={source === 'demo'} onClick={() => selectSource('demo')}>Demo</button>
      <button type="button" aria-pressed={source === 'live'} onClick={() => selectSource('live')}>Live</button>
    </div>
  );
};

const App: React.FC = () => {
  const [demo] = useState(() => isDemo());
  const [customizeOpen, setCustomizeOpen] = useState(false);
  const [customizeRoutine, setCustomizeRoutine] = useState<string | undefined>();
  const [customizeLeg, setCustomizeLeg] = useState<number | undefined>();
  useHeadsUpSync();
  useDeepLinks();

  useEffect(() => {
    // Listen for deep links like mapay://customize?routine=...&leg=...
    CapacitorApp.addListener('appUrlOpen', data => {
      const url = new URL(data.url);
      if (url.host === 'customize' || url.pathname.includes('customize')) {
        const routineId = url.searchParams.get('routine') || undefined;
        const leg = url.searchParams.get('leg') ? parseInt(url.searchParams.get('leg') as string, 10) : undefined;
        setCustomizeRoutine(routineId);
        setCustomizeLeg(leg);
        setCustomizeOpen(true);
      }
    });

    // Also listen for a custom event from HeadsUpCard
    const handleOpenCustomize = (e: Event) => {
      const customEvent = e as CustomEvent;
      setCustomizeRoutine(customEvent.detail?.routineId);
      setCustomizeLeg(customEvent.detail?.legIndex);
      setCustomizeOpen(true);
    };
    window.addEventListener('open-customize', handleOpenCustomize);
    return () => {
      window.removeEventListener('open-customize', handleOpenCustomize);
      CapacitorApp.removeAllListeners();
    };
  }, []);

  return (
    <IonApp>
      <IonReactRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '') || undefined}>
        <IonTabs className="app-tabs">
          <IonRouterOutlet className="app-router-outlet">
            <Route path="/map" element={<ErrorBoundary><MapPage /></ErrorBoundary>} />
            <Route path="/routines" element={<RoutinesPage />} />
            <Route path="/preferences" element={<PreferencesPage />} />
            <Route path="/" element={<Navigate to="/map" replace />} />
          </IonRouterOutlet>

          <IonTabBar slot="bottom" className="glass glass-tab-bar desktop-tab-bar">
            <IonTabButton tab="map" href="/map">
              <IonIcon aria-hidden="true" icon={mapOutline} />
              <IonLabel>Map</IonLabel>
            </IonTabButton>
            <IonTabButton tab="routines" href="/routines">
              <IonIcon aria-hidden="true" icon={timeOutline} />
              <IonLabel>Routines</IonLabel>
            </IonTabButton>
            <IonTabButton tab="preferences" href="/preferences">
              <IonIcon aria-hidden="true" icon={settingsOutline} />
              <IonLabel>Preferences</IonLabel>
            </IonTabButton>
          </IonTabBar>
        </IonTabs>
      </IonReactRouter>

      <DesktopDataSourceSwitch />

      {demo && (
        <IonBadge 
          className="mock-data-badge"
          color="warning" 
          style={{ position: 'fixed', top: 'var(--ion-safe-area-top, 40px)', right: '16px', zIndex: 99999, pointerEvents: 'none' }}
        >
          Mock data
        </IonBadge>
      )}

      <CustomizeSheet 
        isOpen={customizeOpen} 
        onClose={() => setCustomizeOpen(false)} 
        routineId={customizeRoutine}
        legIndex={customizeLeg}
      />
    </IonApp>
  );
};

export default App;
