import { useEffect, useState } from "react";
import { APIProvider, Map, useMap } from "@vis.gl/react-google-maps";
import { IonFab, IonFabButton, IonIcon } from "@ionic/react";
import { layersOutline } from "ionicons/icons";
import type { RouteResponse } from "../lib/types";
import { api } from "../lib/api";
import { upsertGeoJsonLayer, toggleLayer } from "./layers";
import LegendSheet from "../components/LegendSheet";

const MIAMI = { lat: 25.7617, lng: -80.1918 };
const API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY ?? "";
const MAP_ID = import.meta.env.VITE_GOOGLE_MAPS_MAP_ID ?? "DEMO_MAP_ID";

interface Props {
  departAt: Date;
  route: RouteResponse | null;
}

export default function MapView(props: Props) {
  const [layersToggled, setLayersToggled] = useState<Record<string, boolean>>({});
  const [showLegend, setShowLegend] = useState(false);

  return (
    <>
      <APIProvider apiKey={API_KEY}>
        <Map
          style={{ position: "absolute", inset: 0 }}
          defaultCenter={MIAMI}
          defaultZoom={11}
          mapId={MAP_ID}
          gestureHandling="greedy"
          disableDefaultUI
          colorScheme="FOLLOW_SYSTEM"
        />
        <MapLayers {...props} layersToggled={layersToggled} />
      </APIProvider>
      
      <IonFab slot="fixed" vertical="top" horizontal="end" style={{ top: '60px', right: '16px' }}>
        <IonFabButton aria-label="Legend and Layers" className="glass" onClick={() => setShowLegend(true)} style={{ width: '44px', height: '44px' }}>
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

function MapLayers({ departAt, route, layersToggled }: Props & { layersToggled: Record<string, boolean> }) {
  const map = useMap();

  useEffect(() => {
    if (!map) return;
    
    // Fetch layers and draw them
    api.layers(departAt).then((layersResponse) => {
      Object.entries(layersResponse).forEach(([id, data]) => {
        if (id !== 't' && id !== 'freshness') {
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
    // TODO: draw baseline + hazard-aware routes
  }, [map, route]);

  return null;
}
