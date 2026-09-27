import { useState } from 'react';
import { IonFab, IonFabButton, IonIcon, IonActionSheet, useIonToast } from '@ionic/react';
import { addOutline } from 'ionicons/icons';
import { Geolocation } from '@capacitor/geolocation';
import { api } from '../lib/api';

export default function ReportFab() {
  const [showActionSheet, setShowActionSheet] = useState(false);
  const [reporting, setReporting] = useState(false);
  const [presentToast] = useIonToast();

  const handleReport = async (type: string) => {
    setReporting(true);
    try {
      let lat = 25.7617, lng = -80.1918;
      try {
        const pos = await Geolocation.getCurrentPosition();
        lat = pos.coords.latitude;
        lng = pos.coords.longitude;
      } catch (e) {
        console.warn("Geolocation failed, using fallback", e);
      }
      
      await api.report({ type, lat, lng });
      presentToast({
        message: 'Report submitted. Thanks!',
        duration: 2000,
        position: 'top',
        color: 'success'
      });
    } catch (e) {
      console.error(e);
      presentToast({
        message: 'Failed to submit report.',
        duration: 2000,
        position: 'top',
        color: 'danger'
      });
    } finally {
      setReporting(false);
    }
  };

  return (
    <>
      <IonFab className="report-map-fab" slot="fixed" vertical="top" horizontal="end" style={{ top: 'calc(var(--ion-safe-area-top, 0px) + 164px)', right: '16px' }}>
        <IonFabButton 
          aria-label="Report a problem" 
          className="glass" 
          onClick={() => setShowActionSheet(true)} 
          disabled={reporting}
          style={{ width: '44px', height: '44px', borderRadius: '50%' }}
        >
          <IonIcon aria-hidden="true" icon={addOutline} color="primary" />
        </IonFabButton>
      </IonFab>

      <IonActionSheet
        isOpen={showActionSheet}
        onDidDismiss={() => setShowActionSheet(false)}
        header="Report a problem here"
        buttons={[
          { text: 'Flooded street', role: 'destructive', handler: () => handleReport('flood') },
          { text: 'Construction', handler: () => handleReport('construction') },
          { text: 'Road closure', handler: () => handleReport('closure') },
          { text: 'Pothole', handler: () => handleReport('pothole') },
          { text: 'No sidewalk', handler: () => handleReport('no_sidewalk') },
          { text: 'Cancel', role: 'cancel' }
        ]}
      />
    </>
  );
}
