import React, { useCallback, useRef, useEffect, useState } from 'react';
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
import type { Place } from '../lib/types';
import { shortPlaceLabel } from '../routines/placeLabels';

const COLLAPSED_BREAKPOINT = 0.1;

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
  departureTime: Date;
  selectedDeparture: Date | null;
  onDepartureChange: (departure: Date | null) => void;
}

const MapSheet: React.FC<MapSheetProps> = ({ 
  isOpen, routeResponse, selectedPlace, onSearch, 
  onRouteSelect, selectedRouteIndex, onClearRoute, onClearPlace, onRequestRoute, onAddToRoutine,
  departureTime, selectedDeparture, onDepartureChange,
}) => {
  const modal = useRef<HTMLIonModalElement>(null);
  const [upcomingLegs, setUpcomingLegs] = useState<UpcomingLeg[]>([]);
  const [savedPlaces, setSavedPlaces] = useState<Place[]>([]);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [sheetBreakpoint, setSheetBreakpoint] = useState(COLLAPSED_BREAKPOINT);

  const moveToBreakpoint = useCallback((breakpoint: number) => {
    setSheetBreakpoint(breakpoint);
    void modal.current?.setCurrentBreakpoint(breakpoint);
  }, []);

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
    api.places().then(setSavedPlaces).catch(console.error);
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

  const getLegPlaceName = (placeId: string, fallback: string) => {
    const savedPlace = savedPlaces.find((place) => place._id === placeId);
    return shortPlaceLabel(savedPlace?.name || fallback, savedPlace?.address);
  };
  const displayLeg = activeLeg ? {
    ...activeLeg,
    from: { ...activeLeg.from, name: getLegPlaceName(activeLeg.from.place_id, activeLeg.from.name) },
    to: { ...activeLeg.to, name: getLegPlaceName(activeLeg.to.place_id, activeLeg.to.name) },
  } : null;
  const isCollapsed = sheetBreakpoint <= COLLAPSED_BREAKPOINT + 0.01;

  useEffect(() => {
    const sheet = modal.current;
    if (!sheet) return;
    const handleBreakpointChange = () => {
      void Haptics.selectionChanged().catch(() => {});
      void sheet.getCurrentBreakpoint().then((breakpoint) => {
        if (breakpoint !== undefined) setSheetBreakpoint(breakpoint);
      }).catch(() => {});
    };
    sheet.addEventListener('ionBreakpointDidChange', handleBreakpointChange);
    return () => sheet.removeEventListener('ionBreakpointDidChange', handleBreakpointChange);
  }, []);

  // Give destination, route, and heads-up cards enough room without obscuring the map at idle.
  useEffect(() => {
    if (!modal.current) return;
    if (!routeResponse && !activeLeg && !selectedPlace) {
      const timeout = window.setTimeout(() => moveToBreakpoint(COLLAPSED_BREAKPOINT), 0);
      return () => window.clearTimeout(timeout);
    }
    const breakpoint = routeResponse || selectedPlace || activeLeg ? 0.9 : 0.5;
    const timeout = window.setTimeout(() => moveToBreakpoint(breakpoint), 0);
    return () => window.clearTimeout(timeout);
  }, [routeResponse, activeLeg, selectedPlace, moveToBreakpoint]);

  return (
    <IonModal
      ref={modal}
      isOpen={isOpen}
      keepContentsMounted={true}
      handle={!isCollapsed}
      backdropBreakpoint={0.5}
      initialBreakpoint={COLLAPSED_BREAKPOINT}
      breakpoints={[COLLAPSED_BREAKPOINT, 0.5, 0.9]}
      backdropDismiss={false}
      canDismiss={false}
      className={`map-sheet${isCollapsed ? ' map-sheet-compact' : ''}${routeResponse ? ' map-sheet-routes' : ''}`}
      onDidPresent={() => {
        void modal.current?.getCurrentBreakpoint().then((breakpoint) => {
          if (breakpoint !== undefined) setSheetBreakpoint(breakpoint);
        }).catch(() => {});
        if (activeLeg && !routeResponse && !selectedPlace) {
          moveToBreakpoint(0.9);
        }
      }}
    >
      <IonContent className={routeResponse ? 'route-sheet-content' : isCollapsed ? 'map-sheet-content-compact' : 'ion-padding'} scrollY={!routeResponse && !isCollapsed}>
        {showHeadsUp && displayLeg ? (
          <HeadsUpCard leg={displayLeg} />
        ) : null}

        {selectedPlace && !routeResponse ? (
          <PlaceCard 
            place={selectedPlace} 
            onClose={onClearPlace} 
            onRoute={onRequestRoute} 
            onAddToRoutine={onAddToRoutine} 
            departureTime={selectedDeparture}
            onDepartureChange={onDepartureChange}
          />
        ) : !routeResponse ? (
          <div className={isCollapsed ? 'map-search-pill glass' : undefined}>
            <SearchField
              onSearch={onSearch}
              onFocus={() => moveToBreakpoint(0.9)}
            />
          </div>
        ) : (
          <RouteOptions 
            response={routeResponse} 
            selectedIndex={selectedRouteIndex} 
            onSelect={onRouteSelect} 
            onClose={onClearRoute}
            departureTime={departureTime}
            selectedDeparture={selectedDeparture}
            onDepartureChange={onDepartureChange}
            onAddToRoutine={onAddToRoutine}
          />
        )}
      </IonContent>
    </IonModal>
  );
};

export default MapSheet;
