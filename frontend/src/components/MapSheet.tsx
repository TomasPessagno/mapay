import React, { useRef, useEffect, useState } from 'react';
import { IonModal, IonContent, IonButton } from '@ionic/react';
import SearchField from './SearchField';
import RouteOptions from './RouteOptions';
import PlaceCard from './PlaceCard';
import type { PlaceData } from './PlaceCard';
import type { RouteResponse, UpcomingLeg } from '../lib/types';
import { api } from '../lib/api';
import HeadsUpCard from '../headsup/HeadsUpCard';
import { DEMO_HEADS_UP, lastFiredHeadsUp, type DemoHeadsUpDetail } from '../headsup/demo';

interface MapSheetProps {
  isOpen: boolean;
  routeResponse: RouteResponse | null;
  selectedPlace: PlaceData | null;
  onSearch: (destination: {lat: number, lng: number}, name: string, address?: string, type?: string, placeId?: string) => void;
  onRouteSelect: (index: number) => void;
  selectedRouteIndex: number;
  onClearRoute: () => void;
  onClearPlace: () => void;
  onRequestRoute: () => void;
  onAddToRoutine: () => void;
}

const MapSheet: React.FC<MapSheetProps> = ({ 
  isOpen, routeResponse, selectedPlace, onSearch, 
  onRouteSelect, selectedRouteIndex, onClearRoute, onClearPlace, onRequestRoute, onAddToRoutine 
}) => {
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

  // "Fire heads-up now" (#36): show that leg's card right away, until its departure.
  const [demoLeg, setDemoLeg] = useState<UpcomingLeg | null>(lastFiredHeadsUp);
  useEffect(() => {
    const onDemo = (e: Event) => {
      setDemoLeg((e as CustomEvent<DemoHeadsUpDetail>).detail.leg);
      setNowMs(Date.now());
    };
    window.addEventListener(DEMO_HEADS_UP, onDemo);
    return () => window.removeEventListener(DEMO_HEADS_UP, onDemo);
  }, []);

  const nowTime = nowMs + timeOffsetMs;
  const demoActive = demoLeg && nowTime <= new Date(demoLeg.best_departure_at ?? demoLeg.departure_at).getTime();
  const activeLeg = demoActive ? demoLeg : upcomingLegs.find(leg => {
    const headsUp = new Date(leg.heads_up_at).getTime();
    const end = leg.window ? new Date(leg.window.end).getTime() : new Date(leg.departure_at).getTime();
    return nowTime >= headsUp && nowTime <= end;
  });

  // If a route is fetched OR active leg is shown OR place is selected, move to medium breakpoint
  useEffect(() => {
    if ((routeResponse || activeLeg || selectedPlace) && modal.current) {
      modal.current.setCurrentBreakpoint(0.5);
    }
  }, [routeResponse, activeLeg, selectedPlace]);

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
                const target = new Date("2026-09-28T09:05:00-04:00").getTime();
                setTimeOffsetMs(target - Date.now());
              }}
            >
              Debug Heads-Up
            </IonButton>
          </div>
        )}

        {activeLeg && !routeResponse && !selectedPlace ? (
          <HeadsUpCard leg={activeLeg} timeOffsetMs={timeOffsetMs} />
        ) : null}

        {selectedPlace && !routeResponse ? (
          <PlaceCard 
            place={selectedPlace} 
            onClose={onClearPlace} 
            onRoute={onRequestRoute} 
            onAddToRoutine={onAddToRoutine} 
          />
        ) : !routeResponse ? (
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
