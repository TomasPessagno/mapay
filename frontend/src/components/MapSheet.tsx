import React, { useRef, useEffect } from 'react';
import { IonModal, IonContent } from '@ionic/react';
import SearchField from './SearchField';
import RouteOptions from './RouteOptions';
import type { RouteResponse } from '../lib/types';

interface MapSheetProps {
  routeResponse: RouteResponse | null;
  onSearch: (destination: string) => void;
  onRouteSelect: (index: number) => void;
  selectedRouteIndex: number;
}

const MapSheet: React.FC<MapSheetProps> = ({ routeResponse, onSearch, onRouteSelect, selectedRouteIndex }) => {
  const modal = useRef<HTMLIonModalElement>(null);

  // If a route is fetched, move to medium breakpoint to show options
  useEffect(() => {
    if (routeResponse && modal.current) {
      modal.current.setCurrentBreakpoint(0.5);
    }
  }, [routeResponse]);

  return (
    <IonModal
      ref={modal}
      isOpen={true}
      backdropBreakpoint={0.5}
      initialBreakpoint={0.15}
      breakpoints={[0.15, 0.5, 0.9]}
      backdropDismiss={false}
      canDismiss={false}
      className="map-sheet"
    >
      <IonContent className="ion-padding">
        {!routeResponse ? (
          <SearchField onSearch={onSearch} />
        ) : (
          <RouteOptions 
            response={routeResponse} 
            selectedIndex={selectedRouteIndex} 
            onSelect={onRouteSelect} 
          />
        )}
      </IonContent>
    </IonModal>
  );
};

export default MapSheet;
