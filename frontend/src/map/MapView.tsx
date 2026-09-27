import { useEffect, useState, useRef } from "react";
import { Map, useMap, AdvancedMarker } from "@vis.gl/react-google-maps";
import { IonFab, IonFabButton, IonIcon, IonSpinner } from "@ionic/react";
import { layersOutline, locateOutline } from "ionicons/icons";
import type { RouteResponse, RouteOption, LayersResponse } from "../lib/types";
import { api } from "../lib/api";
import { isDemo } from "../lib/dataSource";
import { getCachedLayers, putCachedLayers } from "../lib/layersCache";
import { upsertGeoJsonLayer, toggleLayer, setOnHazardClick } from "./layers";
import LegendSheet from "../components/LegendSheet";
import HazardSheet, { type HazardProperties } from "../components/HazardSheet";
import ReportFab from "../components/ReportFab";
import type { PlaceData } from "../components/PlaceCard";

const MIAMI = { lat: 25.7617, lng: -80.1918 };
const MEDIUM_SHEET_BREAKPOINT = 0.5;

function mapSheetOcclusion(map: google.maps.Map): { top: number; bottom: number } {
  const mapRect = map.getDiv().getBoundingClientRect();
  const modal = document.querySelector('ion-modal.map-sheet') as HTMLIonModalElement | null;
  const panel = modal?.shadowRoot?.querySelector<HTMLElement>('[part~="content"]');
  const panelTop = panel?.getBoundingClientRect().top;

  if (panelTop !== undefined && panelTop > mapRect.top) {
    return {
      top: Math.max(0, panelTop - mapRect.top),
      bottom: Math.max(0, mapRect.bottom - panelTop),
    };
  }

  const clearance = modal ? Number.parseFloat(getComputedStyle(modal).bottom) || 0 : 0;
  const sheetTop = mapRect.bottom - clearance - mapRect.height * MEDIUM_SHEET_BREAKPOINT;
  return {
    top: Math.max(0, sheetTop - mapRect.top),
    bottom: Math.max(0, mapRect.bottom - sheetTop),
  };
}

type LayersStatus = "idle" | "loading" | "error";

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
  const [layersStatus, setLayersStatus] = useState<LayersStatus>("idle");
  const [retryToken, setRetryToken] = useState(0);

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
          <AdvancedMarker position={props.userLocation} zIndex={100} title="Your current location">
            <div style={{
              width: '18px', height: '18px',
              backgroundColor: '#007AFF',
              borderRadius: '50%',
              border: '3px solid white',
              boxShadow: '0 0 6px rgba(0,0,0,0.3)'
            }} aria-hidden="true" />
          </AdvancedMarker>
        )}
        <MapController userLocation={props.userLocation} />
      </Map>
      <MapLayers
        {...props}
        layersToggled={layersToggled}
        onLayersStatus={setLayersStatus}
        retryToken={retryToken}
      />

      <HazardsStatusPill
        status={layersStatus}
        onRetry={() => {
          setLayersStatus("loading");
          setRetryToken((token) => token + 1);
        }}
      />

      {/* Floating buttons sit under the toolbar, 52 px apart: Layers, Locate Me, then Report (ReportFab). */}
      <IonFab slot="fixed" vertical="top" horizontal="end" style={{ top: 'calc(var(--ion-safe-area-top, 0px) + 60px)', right: '16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <IonFabButton aria-label="Show map legend and hazard layers" className="glass map-control-label" onClick={() => setShowLegend(true)} style={{ width: '44px', height: '44px', borderRadius: '50%' }}>
          <IonIcon aria-hidden="true" icon={layersOutline} color="primary" />
        </IonFabButton>
        <IonFabButton aria-label="Center map on my location" className="glass map-control-label" onClick={props.onLocateMe} style={{ width: '44px', height: '44px', borderRadius: '50%' }}>
          <IonIcon aria-hidden="true" icon={locateOutline} color="primary" />
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

// Quiet status for the first Live load: only shown while the map has no hazards to draw yet.
function HazardsStatusPill({ status, onRetry }: { status: LayersStatus; onRetry: () => void }) {
  if (status === "idle") return null;
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: "absolute",
        top: "calc(var(--ion-safe-area-top, 0px) + 60px)",
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 20,
        pointerEvents: status === "error" ? "auto" : "none",
      }}
    >
      <div
        className="glass"
        style={{
          display: "flex",
          alignItems: "center",
          gap: "6px",
          padding: "6px 14px",
          borderRadius: "22px",
          boxShadow: "0 2px 10px rgba(0, 0, 0, 0.18)",
          color: "var(--label)",
          fontSize: "13px",
          lineHeight: "18px",
          fontWeight: 500,
          whiteSpace: "nowrap",
        }}
      >
        {status === "loading" ? (
          <>
            <IonSpinner name="dots" style={{ width: "14px", height: "14px", color: "var(--label)" }} />
            <span>Loading hazards…</span>
          </>
        ) : (
          <button type="button" aria-label="Retry loading map hazards" onClick={onRetry} style={{ all: "unset", cursor: "pointer", minHeight: 44 }}>
            Couldn't load hazards · Retry
          </button>
        )}
      </div>
    </div>
  );
}

function MapController({ userLocation }: { userLocation?: { lat: number; lng: number } | null }) {
  const map = useMap();
  const [selectedPlace, setSelectedPlace] = useState<PlaceData | null>(null);
  const centredOnUser = useRef(false);
  const recenterTimer = useRef<number | null>(null);

  // Centre on the user's first known position as soon as both the map and the position exist,
  // whichever comes last (a recenter event fired before the map loaded used to be lost).
  useEffect(() => {
    if (!map || !userLocation || centredOnUser.current) return;
    centredOnUser.current = true;
    map.panTo(userLocation);
    map.setZoom(14);
  }, [map, userLocation]);

  useEffect(() => {
    const handleRecenter = (e: Event) => {
      if (!map) return;
      const customEvent = e as CustomEvent;
      if (customEvent.detail?.location) {
        const { location, zoom, place } = customEvent.detail;
        if (recenterTimer.current !== null) window.clearTimeout(recenterTimer.current);
        if (zoom) map.setZoom(zoom);

        if (place) {
          // Let the place card rise to its medium detent, then shift the point into the
          // unobscured map area instead of leaving it behind the card.
          recenterTimer.current = window.setTimeout(() => {
            map.setCenter(location);
            const mapRect = map.getDiv().getBoundingClientRect();
            const { top: visibleBottom } = mapSheetOcclusion(map);
            const targetY = Math.max(72, visibleBottom / 3);
            map.panBy(0, Math.max(0, mapRect.height / 2 - targetY));
          }, 850);
        } else {
          map.panTo(location);
        }
      }
      if (customEvent.detail?.place !== undefined) {
         setSelectedPlace(customEvent.detail.place);
      }
    };
    window.addEventListener('recenter-map', handleRecenter);
    return () => {
      window.removeEventListener('recenter-map', handleRecenter);
      if (recenterTimer.current !== null) window.clearTimeout(recenterTimer.current);
    };
  }, [map]);

  return (
    <>
      {selectedPlace && (
        <AdvancedMarker position={selectedPlace.location} zIndex={50} title={selectedPlace.name} />
      )}
    </>
  );
}

function MapLayers({
  departAt,
  routeResponse,
  selectedRouteIndex,
  mapId,
  layersToggled,
  onLayersStatus,
  retryToken,
}: Props & {
  layersToggled: Record<string, boolean>;
  onLayersStatus: (status: LayersStatus) => void;
  retryToken: number;
}) {
  const map = useMap();
  const routeLayersRef = useRef<google.maps.Data[]>([]);
  const cacheReadRef = useRef(false);
  const drawnOnceRef = useRef(false);

  // Fetch only the visible area (padded) whenever the map settles, and skip the request while the
  // view stays inside the last area fetched. Rounded so nearby views share the backend's 60 s cache.
  // In Live mode the last cached response paints first (stale-while-revalidate): only the first
  // view of a mount reads the cache, so changing the time scrubber never shows another time's data.
  useEffect(() => {
    if (!map) return;
    let fetched: [number, number, number, number] | null = null;
    let fetchedZoom = 0;
    let request = 0;
    let fresh = 0;
    const live = !isDemo();

    const drawLayers = (layersResponse: LayersResponse) => {
      Object.entries(layersResponse).forEach(([layerId, data]) => {
        if (layerId !== 't' && layerId !== 'freshness' && layerId !== 'radar') {
          upsertGeoJsonLayer(map, layerId, data as unknown as GeoJSON.FeatureCollection);
        }
      });
    };

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

      if (live && !cacheReadRef.current) {
        cacheReadRef.current = true;
        getCachedLayers(bbox).then((cached) => {
          if (!cached || id !== request || fresh === id) return;
          drawnOnceRef.current = true;
          drawLayers(cached.data);
          onLayersStatus("idle");
        }).catch(() => {});
      }

      if (live && !drawnOnceRef.current) onLayersStatus("loading");
      api.layers(departAt, bbox).then((layersResponse) => {
        if (id !== request) return; // a newer view won
        fetched = bbox;
        fetchedZoom = zoom;
        fresh = id;
        drawnOnceRef.current = true;
        drawLayers(layersResponse);
        onLayersStatus("idle");
        if (live) void putCachedLayers(bbox, layersResponse);
      }).catch(err => {
        console.error("Failed to load layers", err);
        if (id !== request || drawnOnceRef.current) return;
        if (live) onLayersStatus("error");
      });
    };

    const listener = map.addListener('idle', load);
    load();
    return () => listener.remove();
  }, [map, departAt, retryToken, onLayersStatus]);

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

    let fitTimer: number | undefined;
    if (routes[selectedRouteIndex]) {
       const selectedRoute = routes[selectedRouteIndex];
       const bounds = new google.maps.LatLngBounds();
       try {
           const coords = ((selectedRoute.route_geojson as unknown as GeoJSON.FeatureCollection).features[0].geometry as GeoJSON.LineString).coordinates as [number, number][];
           coords.forEach((c: [number, number]) => bounds.extend({ lat: c[1], lng: c[0] }));
           fitTimer = window.setTimeout(() => {
             const { bottom } = mapSheetOcclusion(map);
             map.fitBounds(bounds, { top: 100, bottom: Math.ceil(bottom + 16), left: 40, right: 40 });
           }, 850);
       } catch (e) {
           console.error("Failed to fit bounds", e);
       }
     }
    return () => {
      if (fitTimer !== undefined) window.clearTimeout(fitTimer);
    };
  }, [map, mapId, routeResponse, selectedRouteIndex]);

  return null;
}
