import { useEffect, useState, useRef } from "react";
import { Map, useMap, AdvancedMarker } from "@vis.gl/react-google-maps";
import { IonFab, IonFabButton, IonIcon } from "@ionic/react";
import { layersOutline, locateOutline } from "ionicons/icons";
import type { RouteResponse, RouteOption } from "../lib/types";
import { api } from "../lib/api";
import { upsertGeoJsonLayer, toggleLayer, setOnHazardClick } from "./layers";
import LegendSheet from "../components/LegendSheet";
import HazardSheet, { type HazardProperties } from "../components/HazardSheet";
import ReportFab from "../components/ReportFab";
import type { PlaceData } from "../components/PlaceCard";

const MIAMI = { lat: 25.7617, lng: -80.1918 };

interface Props {
  departAt: Date;
  routeResponse: RouteResponse | null;
  selectedRouteIndex: number;
  mapId: string;
  userLocation: {lat: number, lng: number} | null;
  onLocateMe: () => void;
}

export default function MapView(props: Props) {
  const [layersToggled, setLayersToggled] = useState<Record<string, boolean>>({});
  const [showLegend, setShowLegend] = useState(false);
  const [selectedHazard, setSelectedHazard] = useState<HazardProperties | null>(null);

  useEffect(() => {
    setOnHazardClick((hazard) => {
      setSelectedHazard(hazard as unknown as HazardProperties);
    });
    return () => setOnHazardClick(null);
  }, []);

  return (
    <>
      <Map
        style={{ position: "absolute", inset: 0 }}
        defaultCenter={MIAMI}
        defaultZoom={11}
        mapId={props.mapId}
        gestureHandling="greedy"
        disableDefaultUI
        colorScheme="FOLLOW_SYSTEM"
      >
        {props.userLocation && (
          <AdvancedMarker position={props.userLocation} zIndex={100}>
            <div style={{
              width: '18px', height: '18px',
              backgroundColor: '#007AFF',
              borderRadius: '50%',
              border: '3px solid white',
              boxShadow: '0 0 6px rgba(0,0,0,0.3)'
            }} />
          </AdvancedMarker>
        )}
        <MapController />
      </Map>
      <MapLayers {...props} layersToggled={layersToggled} />
      
      {/* Floating buttons sit under the toolbar, 52 px apart: Layers, Locate Me, then Report (ReportFab). */}
      <IonFab slot="fixed" vertical="top" horizontal="end" style={{ top: 'calc(var(--ion-safe-area-top, 0px) + 60px)', right: '16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <IonFabButton aria-label="Legend and Layers" className="glass" onClick={() => setShowLegend(true)} style={{ width: '44px', height: '44px', borderRadius: '50%' }}>
          <IonIcon icon={layersOutline} color="primary" />
        </IonFabButton>
        <IonFabButton aria-label="Locate Me" className="glass" onClick={props.onLocateMe} style={{ width: '44px', height: '44px', borderRadius: '50%' }}>
          <IonIcon icon={locateOutline} color="primary" />
        </IonFabButton>
      </IonFab>

      <LegendSheet
        isOpen={showLegend}
        onDidDismiss={() => setShowLegend(false)}
        toggled={layersToggled}
        onToggle={(id, visible) => setLayersToggled((prev) => ({ ...prev, [id]: visible }))}
      />

      <HazardSheet
        isOpen={!!selectedHazard}
        hazard={selectedHazard}
        onDidDismiss={() => setSelectedHazard(null)}
      />
      <ReportFab />
    </>
  );
}

function MapController() {
  const map = useMap();
  const [selectedPlace, setSelectedPlace] = useState<PlaceData | null>(null);

  useEffect(() => {
    const handleRecenter = (e: Event) => {
      if (!map) return;
      const customEvent = e as CustomEvent;
      if (customEvent.detail?.location) {
        map.panTo(customEvent.detail.location);
        if (customEvent.detail.zoom) {
          map.setZoom(customEvent.detail.zoom);
        }
      }
      if (customEvent.detail?.place !== undefined) {
         setSelectedPlace(customEvent.detail.place);
      }
    };
    window.addEventListener('recenter-map', handleRecenter);
    return () => window.removeEventListener('recenter-map', handleRecenter);
  }, [map]);

  return (
    <>
      {selectedPlace && (
        <AdvancedMarker position={selectedPlace.location} zIndex={50} />
      )}
    </>
  );
}

function MapLayers({ departAt, routeResponse, selectedRouteIndex, layersToggled }: Props & { layersToggled: Record<string, boolean> }) {
  const map = useMap();
  const routeLayersRef = useRef<google.maps.Data[]>([]);

  // Fetch only the visible area (padded) whenever the map settles, and skip the request while the
  // view stays inside the last area fetched. Rounded so nearby views share the backend's 60 s cache.
  useEffect(() => {
    if (!map) return;
    let fetched: [number, number, number, number] | null = null;
    let fetchedZoom = 0;
    let request = 0;

    const load = () => {
      const bounds = map.getBounds();
      if (!bounds) return;
      const ne = bounds.getNorthEast();
      const sw = bounds.getSouthWest();
      const view: [number, number, number, number] = [sw.lng(), sw.lat(), ne.lng(), ne.lat()];
      const zoom = map.getZoom() ?? 0;
      const inside = fetched && view[0] >= fetched[0] && view[1] >= fetched[1] && view[2] <= fetched[2] && view[3] <= fetched[3];
      // Zooming in 2+ levels refetches a smaller area, so crowded layers can get their icons back.
      if (inside && zoom - fetchedZoom < 2) return;

      const padX = (view[2] - view[0]) * 0.25;
      const padY = (view[3] - view[1]) * 0.25;
      const round = (v: number, up: boolean) => (up ? Math.ceil(v * 100) : Math.floor(v * 100)) / 100;
      const bbox: [number, number, number, number] = [
        round(view[0] - padX, false), round(view[1] - padY, false),
        round(view[2] + padX, true), round(view[3] + padY, true),
      ];
      const id = ++request;
      api.layers(departAt, bbox).then((layersResponse) => {
        if (id !== request) return; // a newer view won
        fetched = bbox;
        fetchedZoom = zoom;
        Object.entries(layersResponse).forEach(([layerId, data]) => {
          if (layerId !== 't' && layerId !== 'freshness' && layerId !== 'radar') {
            upsertGeoJsonLayer(map, layerId, data as unknown as GeoJSON.FeatureCollection);
          }
        });
      }).catch(err => console.error("Failed to load layers", err));
    };

    const listener = map.addListener('idle', load);
    load();
    return () => listener.remove();
  }, [map, departAt]);

  useEffect(() => {
    if (!map) return;
    // apply toggles
    Object.entries(layersToggled).forEach(([id, visible]) => {
      toggleLayer(id, map, visible);
    });
  }, [map, layersToggled]);

  useEffect(() => {
    if (!map) return;
    
    // Clear old routes
    routeLayersRef.current.forEach(l => l.setMap(null));
    routeLayersRef.current = [];

    if (!routeResponse) {
      import("./layers").then(m => m.setFocusRoute(null));
      return;
    }
    
    const routes: RouteOption[] = routeResponse.routes || (routeResponse as unknown as { alternatives?: RouteOption[] }).alternatives || [];
    if (!routes.length) {
      import("./layers").then(m => m.setFocusRoute(null));
      return;
    }
    
    import("./layers").then(m => m.setFocusRoute(routes[selectedRouteIndex]));

    routes.forEach((r: RouteOption, idx: number) => {
      const isSelected = idx === selectedRouteIndex;
      const isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
      const blueColor = isDark ? '#0A84FF' : '#007AFF';

      const data = new google.maps.Data();
      data.addGeoJson(r.route_geojson);
      
      data.setStyle({
        strokeColor: isSelected ? '#FFFFFF' : blueColor,
        strokeWeight: isSelected ? 8 : 6,
        strokeOpacity: isSelected ? 1 : 0.45,
        zIndex: isSelected ? 10 : 5
      });
      
      // If it's selected, we add an inner line for casing
      if (isSelected) {
        const inner = new google.maps.Data();
        inner.addGeoJson(r.route_geojson);
        inner.setStyle({
          strokeColor: blueColor,
          strokeWeight: 4,
          strokeOpacity: 1,
          zIndex: 11
        });
        inner.setMap(map);
        routeLayersRef.current.push(inner);
      }
      
      data.setMap(map);
      routeLayersRef.current.push(data);
    });

    if (routes[selectedRouteIndex]) {
       const selectedRoute = routes[selectedRouteIndex];
       const bounds = new google.maps.LatLngBounds();
       try {
           const coords = ((selectedRoute.route_geojson as unknown as GeoJSON.FeatureCollection).features[0].geometry as GeoJSON.LineString).coordinates as [number, number][];
           coords.forEach((c: [number, number]) => bounds.extend({ lat: c[1], lng: c[0] }));
           map.fitBounds(bounds, { top: 100, bottom: 400, left: 40, right: 40 });
       } catch (e) {
           console.error("Failed to fit bounds", e);
       }
    }
  }, [map, routeResponse, selectedRouteIndex]);

  return null;
}
