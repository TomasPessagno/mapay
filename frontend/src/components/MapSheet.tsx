import React, { useRef, useEffect, useState } from 'react';
import { IonModal, IonContent, IonButton } from '@ionic/react';
import SearchField from './SearchField';
import RouteOptions from './RouteOptions';
import type { RouteResponse, UpcomingLeg } from '../lib/types';
import { api } from '../lib/api';
import HeadsUpCard from '../headsup/HeadsUpCard';

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
  const [upcomingLegs, setUpcomingLegs] = useState<UpcomingLeg[]>([]);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [timeOffsetMs, setTimeOffsetMs] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setNowMs(Date.now()), 60000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    api.upcomingRoutines().then(res => {
      if (res && res.items) {
        setUpcomingLegs(res.items);
      }
    }).catch(console.error);
  }, []);

  const nowTime = nowMs + timeOffsetMs;
  const activeLeg = upcomingLegs.find(leg => {
    const headsUp = new Date(leg.heads_up_at).getTime();
    const end = leg.window ? new Date(leg.window.end).getTime() : new Date(leg.departure_at).getTime();
    return nowTime >= headsUp && nowTime <= end;
  });

  // If a route is fetched OR active leg is shown, move to medium breakpoint
  useEffect(() => {
    if ((routeResponse || activeLeg) && modal.current) {
      modal.current.setCurrentBreakpoint(0.5);
    }
  }, [routeResponse, activeLeg]);

  return (
    <IonModal
      ref={modal}
      isOpen={isOpen}
      keepContentsMounted={true}
      backdropBreakpoint={0.5}
      initialBreakpoint={0.25}
      breakpoints={[0.25, 0.5, 0.9]}
      backdropDismiss={false}
      canDismiss={false}
      className="map-sheet"
    >
      <IonContent className="ion-padding">
        {import.meta.env.DEV && (
          <div style={{ position: 'absolute', top: 8, right: 8, zIndex: 999 }}>
            <IonButton 
              size="small" 
              fill="outline" 
              onClick={() => {
                // mock 'rt-fiu' leg 0 heads_up is 9:00, departure 9:30 on 2026-09-28
                const target = new Date("2026-09-28T09:05:00-04:00").getTime();
                setTimeOffsetMs(target - Date.now());
              }}
            >
              Debug Heads-Up
            </IonButton>
          </div>
        )}

        {activeLeg && !routeResponse ? (
          <HeadsUpCard leg={activeLeg} timeOffsetMs={timeOffsetMs} />
        ) : null}

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
