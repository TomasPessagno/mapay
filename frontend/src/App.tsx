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

// Pages
import MapPage from './pages/MapPage';
import RoutinesPage from './pages/RoutinesPage';
import PreferencesPage from './pages/PreferencesPage';

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true';

const App: React.FC = () => (
  <IonApp>
    <IonReactRouter>
      <IonTabs>
        <IonRouterOutlet>
          <Route path="/map" element={<MapPage />} />
          <Route path="/routines" element={<RoutinesPage />} />
          <Route path="/preferences" element={<PreferencesPage />} />
          <Route path="/" element={<Navigate to="/map" replace />} />
        </IonRouterOutlet>

        <IonTabBar slot="bottom" className="glass">
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
    
    {USE_MOCKS && (
      <IonBadge 
        color="warning" 
        style={{ position: 'fixed', top: 'var(--ion-safe-area-top, 40px)', right: '16px', zIndex: 99999, pointerEvents: 'none' }}
      >
        Mock data
      </IonBadge>
    )}
  </IonApp>
);

export default App;
