import { useEffect, useState, useRef } from "react";
import { Map, useMap } from "@vis.gl/react-google-maps";
import { IonFab, IonFabButton, IonIcon } from "@ionic/react";
import { layersOutline } from "ionicons/icons";
import type { RouteResponse, RouteOption } from "../lib/types";
import { api } from "../lib/api";
import { upsertGeoJsonLayer, toggleLayer } from "./layers";
import LegendSheet from "../components/LegendSheet";

const MIAMI = { lat: 25.7617, lng: -80.1918 };

interface Props {
  departAt: Date;
  routeResponse: RouteResponse | null;
  selectedRouteIndex: number;
  mapId: string;
}

export default function MapView(props: Props) {
  const [layersToggled, setLayersToggled] = useState<Record<string, boolean>>({});
  const [showLegend, setShowLegend] = useState(false);

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
      />
      <MapLayers {...props} layersToggled={layersToggled} />
      
      <IonFab slot="fixed" vertical="top" horizontal="end" style={{ top: '60px', right: '16px' }}>
        <IonFabButton aria-label="Legend and Layers" className="glass" onClick={() => setShowLegend(true)} style={{ width: '44px', height: '44px', borderRadius: '50%' }}>
          <IonIcon icon={layersOutline} color="primary" />
        </IonFabButton>
      </IonFab>

      <LegendSheet
        isOpen={showLegend}
        onDidDismiss={() => setShowLegend(false)}
        toggled={layersToggled}
        onToggle={(id, visible) => setLayersToggled((prev) => ({ ...prev, [id]: visible }))}
      />
    </>
  );
}

function MapLayers({ departAt, routeResponse, selectedRouteIndex, layersToggled }: Props & { layersToggled: Record<string, boolean> }) {
  const map = useMap();
  const routeLayersRef = useRef<google.maps.Data[]>([]);

  useEffect(() => {
    if (!map) return;
    
    // Fetch layers and draw them
    api.layers(departAt).then((layersResponse) => {
      Object.entries(layersResponse).forEach(([id, data]) => {
        if (id !== 't' && id !== 'freshness' && id !== 'radar') {
          upsertGeoJsonLayer(map, id, data as unknown as GeoJSON.FeatureCollection);
        }
      });
    }).catch(err => console.error("Failed to load layers", err));
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
