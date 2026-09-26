import React, { useRef, useEffect } from 'react';
import { IonModal, IonContent } from '@ionic/react';
import SearchField from './SearchField';
import RouteOptions from './RouteOptions';
import type { RouteResponse } from '../lib/types';

interface MapSheetProps {
  isOpen: boolean;
  routeResponse: RouteResponse | null;
  onSearch: (destination: {lat: number, lng: number}, name: string) => void;
  onRouteSelect: (index: number) => void;
  selectedRouteIndex: number;
  onClearRoute: () => void;
}

const MapSheet: React.FC<MapSheetProps> = ({ isOpen, routeResponse, onSearch, onRouteSelect, selectedRouteIndex, onClearRoute }) => {
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
      isOpen={isOpen}
      backdropBreakpoint={0.5}
      initialBreakpoint={0.25}
      breakpoints={[0.25, 0.5, 0.9]}
      backdropDismiss={false}
      canDismiss={false}
      className="map-sheet"
    >
      <IonContent className="ion-padding">
        {!routeResponse ? (
          <SearchField 
            onSearch={onSearch} 
            onFocus={() => modal.current?.setCurrentBreakpoint(0.9)}
          />
        ) : (
          <RouteOptions 
            response={routeResponse} 
            selectedIndex={selectedRouteIndex} 
            onSelect={onRouteSelect} 
            onClose={onClearRoute}
          />
        )}
      </IonContent>
    </IonModal>
  );
};

export default MapSheet;
