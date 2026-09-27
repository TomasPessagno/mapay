import React, { useRef, useEffect, useState } from 'react';
import { IonModal, IonContent } from '@ionic/react';
import SearchField from './SearchField';
import RouteOptions from './RouteOptions';
import PlaceCard from './PlaceCard';
import type { PlaceData } from './PlaceCard';
import type { RouteResponse, UpcomingLeg } from '../lib/types';
import { api } from '../lib/api';
import HeadsUpCard from '../headsup/HeadsUpCard';
import { DEMO_HEADS_UP, lastFiredHeadsUp, type DemoHeadsUpDetail } from '../headsup/demo';
import { Haptics } from '@capacitor/haptics';

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

  const nowTime = nowMs;
  const demoActive = demoLeg && nowTime <= new Date(demoLeg.best_departure_at ?? demoLeg.departure_at).getTime();
  const activeLeg = demoActive ? demoLeg : upcomingLegs.find(leg => {
    const headsUp = new Date(leg.heads_up_at).getTime();
    const end = leg.window ? new Date(leg.window.end).getTime() : new Date(leg.departure_at).getTime();
    return nowTime >= headsUp && nowTime <= end;
  });
  const showHeadsUp = Boolean(activeLeg && !routeResponse && !selectedPlace);

  useEffect(() => {
    const sheet = modal.current;
    if (!sheet) return;
    const handleBreakpointChange = () => {
      void Haptics.selectionChanged().catch(() => {});
    };
    sheet.addEventListener('ionBreakpointDidChange', handleBreakpointChange);
    return () => sheet.removeEventListener('ionBreakpointDidChange', handleBreakpointChange);
  }, []);

  // Open one step further for heads-up so both actions remain visible at larger text sizes.
  useEffect(() => {
    if (!(routeResponse || activeLeg || selectedPlace) || !modal.current) return;
    const sheet = modal.current;
    const breakpoint = activeLeg && !routeResponse && !selectedPlace ? 0.9 : 0.5;
    const timeout = window.setTimeout(() => { void sheet.setCurrentBreakpoint(breakpoint); }, 750);
    return () => window.clearTimeout(timeout);
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
      onDidPresent={() => {
        if (activeLeg && !routeResponse && !selectedPlace) {
          void modal.current?.setCurrentBreakpoint(0.9);
        }
      }}
    >
      <IonContent className="ion-padding">
        {showHeadsUp && activeLeg ? (
          <HeadsUpCard leg={activeLeg} />
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
