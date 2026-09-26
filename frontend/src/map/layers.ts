import { HAZARD_TOKENS } from './legend';
import type { HazardType } from '../lib/types';

// Hazard layer renderers: flood, closures, potholes, reports, walk overlay.
// Each layer is its own google.maps.Data instance so it can be toggled/replaced independently.
const layers = new Map<string, google.maps.Data>();
const layerVisibility = new Map<string, boolean>();

export function upsertGeoJsonLayer(
  map: google.maps.Map,
  id: string,
  data: GeoJSON.FeatureCollection,
): void {
  const isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  
  let layer = layers.get(id);
  if (!layer) {
    layer = new google.maps.Data();
    layers.set(id, layer);
  } else {
    // Clear existing features
    layer.forEach((feature) => layer!.remove(feature));
  }
  
  layer.addGeoJson(data);

  layer.setStyle((feature) => {
    // Check global visibility
    const visible = layerVisibility.get(id) ?? true;
    if (!visible) return { visible: false };

    const hazardType = feature.getProperty('hazard_type') as HazardType;
    const probability = feature.getProperty('probability') as number ?? 1.0;
    const severity = feature.getProperty('severity') as number ?? 3;
    const status = feature.getProperty('status') as string;

    const token = HAZARD_TOKENS[hazardType] || HAZARD_TOKENS.incident;
    const baseColor = isDark ? token.colorDark : token.colorLight;

    // probability -> opacity
    // if predicted, maybe lighter opacity or different stroke.
    let fillOpacity = probability * 0.4;
    let strokeOpacity = probability;

    if (status === 'predicted') {
      fillOpacity *= 0.5;
      strokeOpacity *= 0.5;
    }

    // severity -> width/size
    const strokeWeight = severity * 1.5;

    const options: google.maps.Data.StyleOptions = {
      fillColor: baseColor,
      fillOpacity,
      strokeColor: baseColor,
      strokeWeight,
      strokeOpacity,
      visible: true
    };

    switch (hazardType) {
      case 'flood':
        options.strokeWeight = severity * 2;
        break;
      case 'weather':
        options.strokeWeight = 0;
        options.fillOpacity = 0.25;
        break;
      case 'closure':
        options.strokeOpacity = 0;
        options.icons = [{
          icon: {
            path: 'M 0,-1 0,1',
            strokeOpacity: strokeOpacity,
            scale: severity * 1.5,
            strokeWeight: severity * 1.5,
            strokeColor: baseColor
          },
          offset: '0',
          repeat: '20px'
        }];
        break;
      case 'no_sidewalk':
        options.strokeOpacity = 0;
        options.icons = [{
          icon: {
            path: google.maps.SymbolPath.CIRCLE,
            fillOpacity: strokeOpacity,
            scale: severity,
            fillColor: baseColor
          },
          offset: '0',
          repeat: '10px'
        }];
        break;
      case 'pothole':
      case 'incident':
      case 'event':
        options.icon = {
          path: google.maps.SymbolPath.CIRCLE,
          scale: severity * 2 + 4,
          fillColor: baseColor,
          fillOpacity: strokeOpacity,
          strokeColor: isDark ? '#000000' : '#FFFFFF',
          strokeWeight: 1.5,
          strokeOpacity: 1
        };
        break;
    }

    return options;
  });

  if (layerVisibility.get(id) !== false) {
    layer.setMap(map);
  }
}

export function toggleLayer(id: string, map: google.maps.Map, visible: boolean): void {
  layerVisibility.set(id, visible);
  const layer = layers.get(id);
  if (layer) {
    if (visible) {
      layer.setMap(map);
      // Re-trigger style update
      layer.setStyle(layer.getStyle() as google.maps.Data.StylingFunction);
    } else {
      layer.setMap(null);
    }
  }
}

export function removeLayer(id: string): void {
  layers.get(id)?.setMap(null);
  layers.delete(id);
}
