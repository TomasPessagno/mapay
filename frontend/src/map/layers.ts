// Hazard layer renderers: flood, closures, potholes, reports, walk overlay.
// Each layer is its own google.maps.Data instance so it can be toggled/replaced independently.
const layers = new Map<string, google.maps.Data>();

export function upsertGeoJsonLayer(
  map: google.maps.Map,
  id: string,
  data: GeoJSON.FeatureCollection,
): void {
  // TODO: per-hazard styling via layer.setStyle(...)
  layers.get(id)?.setMap(null);
  const layer = new google.maps.Data({ map });
  layer.addGeoJson(data);
  layers.set(id, layer);
}

export function removeLayer(id: string): void {
  layers.get(id)?.setMap(null);
  layers.delete(id);
}
