import { HAZARD_TOKENS, type LegendToken } from './legend';
import type { HazardType, RouteOption } from '../lib/types';

// Hazard layer renderers: flood, closures, potholes, reports, walk overlay.
// Each layer is its own google.maps.Data instance so it can be toggled/replaced independently.
const layers = new Map<string, google.maps.Data>();
const layerMarkers = new Map<string, google.maps.marker.AdvancedMarkerElement[]>();
// Real data has ~27k hazards across Miami-Dade (mostly construction permits). One DOM marker per
// hazard would stall a phone, so icons are drawn only for layers with few hazards in the fetched
// area, and the dense layers are skipped entirely when zoomed out.
const MAX_MARKERS_PER_LAYER = 150;
const DENSE_LAYERS = new Set(['construction', 'no_sidewalk', 'pothole']);
const DENSE_MIN_ZOOM = 12;
// City of Miami Public Works permits ("city:permit:…") cover every street around downtown and
// load slowly; like no_sidewalk they only appear once the map is at street level. HERE and other
// construction keep the normal dense-layer behaviour.
const CITY_PERMIT_PREFIX = 'city:permit:';
const CITY_PERMIT_MIN_ZOOM = 15;
// Hazards below p 0.5 are hidden by default: planned City of Miami roadway projects (p 0.2) cover
// every street but never affect routing. The legend sheet's switch brings them back, faded.
const UNCONFIRMED_THRESHOLD = 0.5;
const layerVisibility = new Map<string, boolean>();
const layerDataCache = new Map<string, GeoJSON.FeatureCollection>();

// Congestion is Google's own live traffic (TrafficLayer), drawn by Google inside the map like on
// Google Maps. The HERE flow hazards behind the old congestion lines still count in routing; they
// just aren't drawn on top of the map any more.
const TRAFFIC_ID = 'congestion';
let trafficLayer: google.maps.TrafficLayer | null = null;

function setTrafficVisible(map: google.maps.Map, visible: boolean): void {
  if (!trafficLayer) trafficLayer = new google.maps.TrafficLayer();
  trafficLayer.setMap(visible ? map : null);
}

// Line widths follow the zoom like Google's roads (in screen pixels), so a hazard line reads as
// part of the street instead of a fixed-width stroke painted over it. ~4 px at zoom 14, doubling
// every two zoom levels, clamped to what still looks like a road.
function roadWidth(zoom: number): number {
  return Math.min(16, Math.max(1.5, 4 * Math.pow(2, (zoom - 14) / 2)));
}

// Severity 1–5 widens a line a little (0.85×–1.25×), without turning it into a smear.
function severityScale(severity: number): number {
  return 0.75 + Math.min(Math.max(severity, 1), 5) * 0.1;
}

// A darker shade of a line's colour for its edge: how Google outlines coloured road features.
function darken(hex: string, amount = 0.35): string {
  const value = parseInt(hex.slice(1), 16);
  const channel = (shift: number) => Math.round(((value >> shift) & 0xff) * (1 - amount));
  return `#${[16, 8, 0].map((shift) => channel(shift).toString(16).padStart(2, '0')).join('')}`;
}

function isLine(feature: google.maps.Data.Feature): boolean {
  const type = feature.getGeometry()?.getType();
  return type === 'LineString' || type === 'MultiLineString';
}

// Flood lines get a slightly wider, darker line underneath (an edge), drawn by a second Data layer.
const EDGED_LAYERS = new Set(['flood']);
const edgeLayers = new Map<string, google.maps.Data>();

function formatObservedAge(value: string | undefined): string | null {
  if (!value) return null;
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return null;
  const elapsedMinutes = Math.max(0, Math.round((Date.now() - timestamp) / 60000));
  if (elapsedMinutes < 60) return `${elapsedMinutes} ${elapsedMinutes === 1 ? 'minute' : 'minutes'} ago`;
  const elapsedHours = Math.round(elapsedMinutes / 60);
  if (elapsedHours < 24) return `${elapsedHours} ${elapsedHours === 1 ? 'hour' : 'hours'} ago`;
  const elapsedDays = Math.round(elapsedHours / 24);
  return `${elapsedDays} ${elapsedDays === 1 ? 'day' : 'days'} ago`;
}

let showUnconfirmed = false;

export function getShowUnconfirmed(): boolean {
  return showUnconfirmed;
}

export function setShowUnconfirmed(value: boolean): void {
  if (showUnconfirmed === value) return;
  showUnconfirmed = value;
  refreshAllLayers();
}

let mapInstance: google.maps.Map | null = null;
let advancedMarkerLib: google.maps.MarkerLibrary | null = null;
let geometryLib: google.maps.GeometryLibrary | null = null;
let zoomListener: google.maps.MapsEventListener | null = null;
let hazardClickHandler: ((hazard: Record<string, unknown>) => void) | null = null;

export function setOnHazardClick(handler: ((hazard: Record<string, unknown>) => void) | null) {
  hazardClickHandler = handler;
}

let focusPolyline: google.maps.Polyline | null = null;

export async function setFocusRoute(route: RouteOption | null) {
  if (route && route.route_geojson) {
    if (!geometryLib) {
      geometryLib = await google.maps.importLibrary("geometry") as google.maps.GeometryLibrary;
    }
    const featureCollection = route.route_geojson as unknown as GeoJSON.FeatureCollection;
    const geometry = featureCollection.features[0].geometry as GeoJSON.LineString;
    const path = geometry.coordinates.map((c: number[]) => new google.maps.LatLng(c[1], c[0]));
    focusPolyline = new google.maps.Polyline({ path });
  } else {
    focusPolyline = null;
  }
  refreshAllLayers();
}

function isFocused(centroid: google.maps.LatLngLiteral | null): boolean {
  if (!focusPolyline || !geometryLib || !centroid) return true;
  const pt = new google.maps.LatLng(centroid.lat, centroid.lng);
  return geometryLib.poly.isLocationOnEdge(pt, focusPolyline, 0.00135);
}

let isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;

if (window.matchMedia) {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
    isDark = e.matches;
    refreshAllLayers();
  });
}

function refreshAllLayers() {
  if (!mapInstance) return;
  
  layers.forEach((layer) => {
    if (layer.getStyle()) {
      layer.setStyle(layer.getStyle() as google.maps.Data.StylingFunction);
    }
  });

  // Re-run upsert for markers to pick up new colors
  layerDataCache.forEach((data, id) => {
    upsertGeoJsonLayer(mapInstance!, id, data).catch(console.error);
  });
}

function setupMapListeners(map: google.maps.Map) {
  if (mapInstance === map) return;
  mapInstance = map;
  
  if (zoomListener) {
    zoomListener.remove();
  }

  let permitsVisible = (map.getZoom() ?? 0) >= CITY_PERMIT_MIN_ZOOM;
  
  zoomListener = map.addListener('zoom_changed', () => {
    const zoom = map.getZoom() ?? 0;

    // Re-evaluate styles so line widths follow the zoom.
    layers.forEach((layer) => {
      const style = layer.getStyle();
      if (typeof style === 'function') layer.setStyle(style);
    });
    edgeLayers.forEach((layer) => {
      const style = layer.getStyle();
      if (typeof style === 'function') layer.setStyle(style);
    });
    
    // Check no_sidewalk layer visibility based on zoom
    const nsLayer = layers.get('no_sidewalk');
    const isVisible = layerVisibility.get('no_sidewalk') !== false && zoom >= 15;
    if (nsLayer) {
      nsLayer.setMap(isVisible ? map : null);
    }
    
    const nsMarkers = layerMarkers.get('no_sidewalk');
    if (nsMarkers) {
      nsMarkers.forEach(m => { m.map = isVisible ? map : null; });
    }

    // Permits are filtered out of the Data layer below street level, so crossing the threshold
    // means redrawing construction from the last fetched data.
    const nowVisible = zoom >= CITY_PERMIT_MIN_ZOOM;
    if (nowVisible !== permitsVisible) {
      permitsVisible = nowVisible;
      const data = layerDataCache.get('construction');
      if (data) void upsertGeoJsonLayer(map, 'construction', data).catch(console.error);
    }
  });
}

function getCentroid(feature: google.maps.Data.Feature): google.maps.LatLngLiteral | null {
  const geom = feature.getGeometry();
  if (!geom) return null;
  
  if (geom.getType() === 'Point') {
    const pt = geom as google.maps.Data.Point;
    return { lat: pt.get().lat(), lng: pt.get().lng() };
  }
  
  const bounds = new google.maps.LatLngBounds();
  geom.forEachLatLng((latLng) => {
    bounds.extend(latLng);
  });
  
  if (bounds.isEmpty()) return null;
  const center = bounds.getCenter();
  return { lat: center.lat(), lng: center.lng() };
}

function isCityPermitFeature(feature: google.maps.Data.Feature): boolean {
  return String(feature.getProperty('hazard_id') ?? '').startsWith(CITY_PERMIT_PREFIX);
}

function isCityPermitGeoJson(feature: GeoJSON.Feature): boolean {
  const properties = feature.properties as Record<string, unknown> | null | undefined;
  return String(properties?.hazard_id ?? '').startsWith(CITY_PERMIT_PREFIX);
}

function createMarkerContent(token: LegendToken, isDark: boolean, opacity: number): HTMLElement {
  const baseColor = isDark ? token.colorDark : token.colorLight;
  const haloColor = isDark ? '#000000' : '#FFFFFF';
  
  const div = document.createElement('div');
  div.style.width = '24px';
  div.style.height = '24px';
  div.style.display = 'flex';
  div.style.alignItems = 'center';
  div.style.justifyContent = 'center';
  div.style.color = baseColor;
  div.style.opacity = Math.max(opacity, 0.25).toString();
  div.setAttribute('aria-hidden', 'true');
  
  // 1.5px halo using drop-shadow
  div.style.filter = `drop-shadow(0px 1.5px 0px ${haloColor}) drop-shadow(0px -1.5px 0px ${haloColor}) drop-shadow(1.5px 0px 0px ${haloColor}) drop-shadow(-1.5px 0px 0px ${haloColor})`;

  let svgStr = token.icon as string;
  if (svgStr.startsWith('data:image/svg+xml;utf8,')) {
    svgStr = svgStr.substring('data:image/svg+xml;utf8,'.length);
  }
  
  // Convert ionic paths to use currentColor
  svgStr = svgStr.replace(/class='ionicon-fill-none ionicon-stroke-width'/g, 'fill="none" stroke="currentColor" stroke-width="32"');
  svgStr = svgStr.replace(/class='ionicon'/g, 'fill="currentColor"');
  
  div.innerHTML = svgStr;
  const svg = div.querySelector('svg');
  if (svg) {
    svg.style.width = '100%';
    svg.style.height = '100%';
    svg.style.overflow = 'visible';
  }
  
  return div;
}

export async function upsertGeoJsonLayer(
  map: google.maps.Map,
  id: string,
  data: GeoJSON.FeatureCollection,
): Promise<void> {
  setupMapListeners(map);
  layerDataCache.set(id, data);

  if (id === TRAFFIC_ID) {
    setTrafficVisible(map, layerVisibility.get(id) !== false);
    return;
  }
  
  if (!advancedMarkerLib) {
    advancedMarkerLib = await google.maps.importLibrary("marker") as google.maps.MarkerLibrary;
  }
  
  let layer = layers.get(id);
  if (!layer) {
    layer = new google.maps.Data();
    layers.set(id, layer);
    
    layer.addListener('click', (e: google.maps.Data.MouseEvent) => {
      if (!hazardClickHandler) return;
      const feature = e.feature;
      const hazard: Record<string, unknown> = {};
      feature.forEachProperty((value, key) => {
        hazard[key] = value;
      });
      const centroid = getCentroid(feature);
      if (centroid) {
        hazard.lat = centroid.lat;
        hazard.lng = centroid.lng;
      }
      hazardClickHandler(hazard);
    });
  } else {
    // Clear existing features
    layer.forEach((feature) => layer!.remove(feature));
  }
  
  let markers = layerMarkers.get(id);
  if (markers) {
    markers.forEach(m => { m.map = null; });
  }
  markers = [];
  layerMarkers.set(id, markers);
  
  const zoom = map.getZoom() ?? 0;
  const permitZoomedOut = id === 'construction' && zoom < CITY_PERMIT_MIN_ZOOM;
  const features = permitZoomedOut
    ? (data.features ?? []).filter((feature) => !isCityPermitGeoJson(feature))
    : data.features ?? [];
  if (!(DENSE_LAYERS.has(id) && zoom < DENSE_MIN_ZOOM)) {
    layer.addGeoJson({ ...data, features });
  }
  const showMarkers = features.length <= MAX_MARKERS_PER_LAYER;

  let isVisible = layerVisibility.get(id) !== false;
  if (id === 'no_sidewalk' && zoom < 15) {
    isVisible = false;
  }

  // Create markers
  layer.forEach((feature) => {
    const hazardType = feature.getProperty('hazard_type') as HazardType;
    const probability = feature.getProperty('probability') as number ?? 1.0;
    const status = feature.getProperty('status') as string;
    
    // Skip markers for congestion and no_sidewalk lines, and for crowded layers (shapes only)
    if (!showMarkers || hazardType === 'congestion' || hazardType === 'no_sidewalk') return;
    if (permitZoomedOut && isCityPermitFeature(feature)) return;
    if (probability < UNCONFIRMED_THRESHOLD && !showUnconfirmed) return;
    
    const centroid = getCentroid(feature);
    if (!centroid) return;
    
    let opacity = probability;
    if (status === 'predicted') {
      opacity *= 0.5;
    }
    if (probability < UNCONFIRMED_THRESHOLD) {
      opacity *= 0.5;
    }
    if (!isFocused(centroid)) {
      opacity *= 0.3;
    }
    
    const token = HAZARD_TOKENS[hazardType] || HAZARD_TOKENS.incident;
    const markerTitle = feature.getProperty('title') as string || token.name;
    const place = feature.getProperty('place') as string;
    const confidence = status === 'predicted'
      ? 'predicted'
      : probability >= 0.9
        ? 'high confidence'
        : probability >= 0.73
          ? 'medium confidence'
          : 'unconfirmed';
    const observedAt = feature.getProperty('observed_at') as string
      || feature.getProperty('last_updated') as string
      || undefined;
    const observedAge = status === 'predicted' ? null : formatObservedAge(observedAt);
    const marker = new advancedMarkerLib!.AdvancedMarkerElement({
      map: isVisible ? map : null,
      position: centroid,
      content: createMarkerContent(token, isDark, opacity),
      title: `${token.name} on ${place || markerTitle}, ${confidence}${observedAge ? `, observed ${observedAge}` : ''}`,
      gmpClickable: true,
    });
    
    marker.addListener('gmp-click', () => {
      if (!hazardClickHandler) return;
      const hazard: Record<string, unknown> = {};
      feature.forEachProperty((value, key) => {
        hazard[key] = value;
      });
      hazard.lat = centroid.lat;
      hazard.lng = centroid.lng;
      hazardClickHandler(hazard);
    });

    markers!.push(marker);
  });

  layer.setStyle((feature) => {
    const visible = layerVisibility.get(id) ?? true;
    if (!visible) return { visible: false };
    if (id === 'no_sidewalk' && (map.getZoom() ?? 0) < 15) return { visible: false };
    if (id === 'construction' && (map.getZoom() ?? 0) < CITY_PERMIT_MIN_ZOOM && isCityPermitFeature(feature)) {
      return { visible: false };
    }

    const hazardType = feature.getProperty('hazard_type') as HazardType;
    const probability = feature.getProperty('probability') as number ?? 1.0;
    const severity = feature.getProperty('severity') as number ?? 3;
    const status = feature.getProperty('status') as string;

    if (probability < UNCONFIRMED_THRESHOLD && !showUnconfirmed) return { visible: false };

    const token = HAZARD_TOKENS[hazardType] || HAZARD_TOKENS.incident;
    const baseColor = isDark ? token.colorDark : token.colorLight;

    let fillOpacity = Math.max(probability * 0.4, 0.25);
    // Lines are near-solid like Google's road colours; only unconfirmed and predicted ones fade.
    let strokeOpacity = probability >= 0.73 ? 0.9 : 0.75;

    if (status === 'predicted') {
      fillOpacity = Math.max(fillOpacity * 0.5, 0.25);
      strokeOpacity = 0.6;
    }

    if (probability < UNCONFIRMED_THRESHOLD) {
      fillOpacity *= 0.5;
      strokeOpacity *= 0.6;
    }
    
    if (!isFocused(getCentroid(feature))) {
      fillOpacity *= 0.3;
      strokeOpacity *= 0.3;
    }

    const zoom = map.getZoom() ?? 14;
    const line = isLine(feature);
    // Area outlines stay thin; lines take the width of a road at this zoom.
    const strokeWeight = line ? roadWidth(zoom) * severityScale(severity) : 1.5;

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
        options.strokeWeight = line ? strokeWeight : 2;
        options.zIndex = 2;
        break;
      case 'weather':
        options.strokeWeight = 0;
        options.fillOpacity = Math.max(0.25, fillOpacity);
        break;
      case 'construction':
        // Thin, translucent lines: active roadwork shouldn't paint whole streets solid orange.
        options.strokeWeight = line ? roadWidth(zoom) * 0.6 : 1.5;
        options.strokeOpacity = Math.min(strokeOpacity, 0.8);
        break;
      case 'closure':
        options.strokeOpacity = 0;
        // Keep the dashed line using icons along the path
        options.icons = [{
          icon: {
            path: 'M 0,-1 0,1',
            strokeOpacity: strokeOpacity,
            scale: roadWidth(zoom) * 0.6,
            strokeWeight: roadWidth(zoom) * 0.6,
            strokeColor: baseColor
          },
          offset: '0',
          repeat: '20px'
        }];
        break;
      case 'congestion': {
        const level = (feature.getProperty('level') as string || '').toLowerCase();
        const ratio = feature.getProperty('ratio') as number;
        
        let congColor = '#FFCC00'; // Default yellow
        if (level === 'severe' || level === 'dark red') congColor = '#A50E0E';
        else if (level === 'heavy' || level === 'red') congColor = '#FF3B30';
        else if (ratio !== undefined) {
          if (ratio > 0.7) congColor = '#A50E0E';
          else if (ratio > 0.4) congColor = '#FF3B30';
        }
        
        options.strokeColor = congColor;
        options.strokeWeight = severity * 2 + 1; // 1pt wider per spec
        options.strokeOpacity = strokeOpacity;
        break;
      }
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
        // Hide standard Data layer rendering for these since AdvancedMarkerElement handles it
        options.visible = false;
        break;
    }

    return options;
  });

  if (EDGED_LAYERS.has(id)) {
    upsertEdgeLayer(map, id, layer, isVisible);
  }

  if (isVisible) {
    layer.setMap(map);
  } else {
    layer.setMap(null);
  }
}

// The edge under a layer's lines: same features, a bit wider and darker, below the line itself.
function upsertEdgeLayer(map: google.maps.Map, id: string, source: google.maps.Data, visible: boolean): void {
  let edge = edgeLayers.get(id);
  if (!edge) {
    edge = new google.maps.Data();
    edgeLayers.set(id, edge);
  } else {
    edge.forEach((feature) => edge!.remove(feature));
  }
  // Copies, not the same feature objects: a feature belongs to one Data layer.
  source.forEach((feature) => {
    if (!isLine(feature)) return;
    const properties: Record<string, unknown> = {};
    feature.forEachProperty((value, key) => { properties[key] = value; });
    edge!.add(new google.maps.Data.Feature({ geometry: feature.getGeometry(), properties }));
  });
  edge.setStyle((feature) => {
    const main = source.getStyle();
    const style = typeof main === 'function' ? main(feature) : main;
    if (!style || style.visible === false || !style.strokeWeight) return { visible: false };
    return {
      clickable: false,
      strokeColor: darken(style.strokeColor ?? '#000000'),
      strokeOpacity: Math.min(1, (style.strokeOpacity ?? 1) * 0.9),
      strokeWeight: (style.strokeWeight ?? 0) + 2,
      zIndex: 1,
    };
  });
  edge.setMap(visible ? map : null);
}

export function toggleLayer(id: string, map: google.maps.Map, visible: boolean): void {
  layerVisibility.set(id, visible);

  if (id === TRAFFIC_ID) {
    setTrafficVisible(map, visible);
    return;
  }
  
  const zoom = map.getZoom() ?? 0;
  let isVisible = visible;
  if (id === 'no_sidewalk' && zoom < 15) {
    isVisible = false;
  }
  
  const layer = layers.get(id);
  if (layer) {
    layer.setMap(isVisible ? map : null);
    if (isVisible) {
      layer.setStyle(layer.getStyle() as google.maps.Data.StylingFunction);
    }
  }
  edgeLayers.get(id)?.setMap(isVisible ? map : null);
  
  const markers = layerMarkers.get(id);
  if (markers) {
    markers.forEach(m => { m.map = isVisible ? map : null; });
  }
}

export function removeLayer(id: string): void {
  if (id === TRAFFIC_ID) trafficLayer?.setMap(null);
  layers.get(id)?.setMap(null);
  layers.delete(id);
  edgeLayers.get(id)?.setMap(null);
  edgeLayers.delete(id);
  
  const markers = layerMarkers.get(id);
  if (markers) {
    markers.forEach(m => { m.map = null; });
  }
  layerMarkers.delete(id);
  layerDataCache.delete(id);
}
