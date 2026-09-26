import { useEffect } from "react";
import { APIProvider, Map, useMap } from "@vis.gl/react-google-maps";
import type { RouteResponse } from "../lib/types";

const MIAMI = { lat: 25.7617, lng: -80.1918 };
const API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY ?? "";
const MAP_ID = import.meta.env.VITE_GOOGLE_MAPS_MAP_ID ?? "DEMO_MAP_ID";

interface Props {
  departAt: Date;
  route: RouteResponse | null;
}

export default function MapView(props: Props) {
  return (
    <APIProvider apiKey={API_KEY}>
      <Map
        style={{ position: "absolute", inset: 0 }}
        defaultCenter={MIAMI}
        defaultZoom={11}
        mapId={MAP_ID}
        gestureHandling="greedy"
        disableDefaultUI
      />
      <MapLayers {...props} />
    </APIProvider>
  );
}

function MapLayers({ departAt, route }: Props) {
  const map = useMap();

  useEffect(() => {
    if (!map) return;
    // TODO: fetch api.layers(departAt) and update hazard layers (see ./layers.ts)
  }, [map, departAt]);

  useEffect(() => {
    if (!map) return;
    // TODO: draw baseline + hazard-aware routes
  }, [map, route]);

  return null;
}
