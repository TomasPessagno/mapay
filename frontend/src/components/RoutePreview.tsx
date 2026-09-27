import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { IonButton, IonIcon, IonModal } from '@ionic/react';
import { Haptics } from '@capacitor/haptics';
import { closeOutline, navigateOutline, pauseOutline, playOutline } from 'ionicons/icons';
import { Map, useMap, AdvancedMarker } from '@vis.gl/react-google-maps';
import type { HazardOnRoute, RouteOption, RouteStep } from '../lib/types';
import { HAZARD_TOKENS } from '../map/legend';
import { openLink } from '../lib/deepLinks';
import { formatClockTime } from '../lib/departureTime';
import './RoutePreview.css';

const PREVIEW_DURATION_MS = 36_000;
const EARTH_RADIUS_M = 6_371_000;
const ROUTE_FIT_DURATION_MS = 1_000;
const LIGHT_MAP_ID = import.meta.env.VITE_GOOGLE_MAPS_MAP_ID ?? 'DEMO_MAP_ID';
const DARK_MAP_ID = import.meta.env.VITE_GOOGLE_MAPS_DARK_MAP_ID ?? LIGHT_MAP_ID;

type Point = { lat: number; lng: number };

interface Props {
  isOpen: boolean;
  route: RouteOption;
  departureTime: Date;
  selectedDeparture: Date | null;
  googleMapsUrl?: string;
  onClose: () => void;
}

function decodePolyline(encoded: string): Point[] {
  const points: Point[] = [];
  let index = 0;
  let lat = 0;
  let lng = 0;
  while (index < encoded.length) {
    const deltas: number[] = [];
    for (let axis = 0; axis < 2; axis += 1) {
      let value = 0;
      let shift = 0;
      let byte: number;
      do {
        byte = encoded.charCodeAt(index) - 63;
        index += 1;
        value |= (byte & 0x1f) << shift;
        shift += 5;
      } while (byte >= 0x20 && index < encoded.length);
      deltas.push(value & 1 ? ~(value >> 1) : value >> 1);
    }
    lat += deltas[0];
    lng += deltas[1];
    points.push({ lat: lat / 1e5, lng: lng / 1e5 });
  }
  return points;
}

function routeCoordinates(route: RouteOption): Point[] {
  const steps = route.steps ?? [];
  const stepPoints = steps.flatMap((step) => step.polyline ? decodePolyline(step.polyline) : []);
  if (stepPoints.length > 1) return dedupePoints(stepPoints);

  const collection = route.route_geojson as {
    features?: Array<{ geometry?: { coordinates?: number[][] } }>;
  };
  const coordinates = collection.features?.flatMap((feature) => feature.geometry?.coordinates ?? []) ?? [];
  return coordinates.map(([lng, lat]) => ({ lat, lng }));
}

function dedupePoints(points: Point[]): Point[] {
  return points.filter((point, index) => index === 0 ||
    Math.abs(point.lat - points[index - 1].lat) > 1e-7 || Math.abs(point.lng - points[index - 1].lng) > 1e-7);
}

function distanceBetween(a: Point, b: Point): number {
  const radians = (value: number) => value * Math.PI / 180;
  const dLat = radians(b.lat - a.lat);
  const dLng = radians(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(radians(a.lat)) * Math.cos(radians(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

function interpolate(points: Point[], fraction: number): { point: Point; heading: number } {
  if (points.length < 2) return { point: points[0] ?? { lat: 25.7617, lng: -80.1918 }, heading: 0 };
  const lengths = points.slice(1).map((point, index) => distanceBetween(points[index], point));
  const total = lengths.reduce((sum, length) => sum + length, 0);
  let remaining = total * Math.min(1, Math.max(0, fraction));
  for (let index = 0; index < lengths.length; index += 1) {
    const segmentLength = lengths[index];
    const start = points[index];
    const end = points[index + 1];
    if (remaining <= segmentLength || index === lengths.length - 1) {
      const ratio = segmentLength ? Math.min(1, remaining / segmentLength) : 0;
      const radians = (value: number) => value * Math.PI / 180;
      const heading = (Math.atan2(
        Math.sin(radians(end.lng - start.lng)) * Math.cos(radians(end.lat)),
        Math.cos(radians(start.lat)) * Math.sin(radians(end.lat)) -
        Math.sin(radians(start.lat)) * Math.cos(radians(end.lat)) * Math.cos(radians(end.lng - start.lng)),
      ) * 180 / Math.PI + 360) % 360;
      return {
        point: { lat: start.lat + (end.lat - start.lat) * ratio, lng: start.lng + (end.lng - start.lng) * ratio },
        heading,
      };
    }
    remaining -= segmentLength;
  }
  return { point: points[points.length - 1], heading: 0 };
}

function formatDuration(seconds: number): string {
  const minutes = Math.max(0, Math.ceil(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} hr ${minutes % 60} min`;
}

function formatDistance(meters: number): string {
  return `${(Math.max(0, meters) / 1609.344).toFixed(1)} mi`;
}

function maneuverGlyph(maneuver = ''): string {
  const value = maneuver.toUpperCase();
  if (value.includes('UTURN')) return value.includes('RIGHT') ? '↷' : '↶';
  if (value.includes('ROUNDABOUT')) return value.includes('RIGHT') ? '⟳' : '⟲';
  if (value.includes('SLIGHT_LEFT')) return '↖';
  if (value.includes('SLIGHT_RIGHT')) return '↗';
  if (value.includes('FORK') || value.includes('RAMP')) return value.includes('LEFT') ? '↖' : '↗';
  if (value.includes('MERGE')) return value.includes('LEFT') ? '↖' : '↗';
  if (value.includes('SHARP_LEFT') || value.includes('LEFT')) return '↰';
  if (value.includes('SHARP_RIGHT') || value.includes('RIGHT')) return '↱';
  return '↑';
}

function maneuverLabel(maneuver = ''): string {
  const value = maneuver.toUpperCase();
  if (value.includes('ROUNDABOUT')) return 'roundabout';
  if (value.includes('UTURN')) return 'U-turn';
  if (value.includes('MERGE')) return 'merge';
  if (value.includes('RAMP')) return 'ramp';
  if (value.includes('SLIGHT')) return 'slight turn';
  if (value.includes('LEFT')) return 'turn left';
  if (value.includes('RIGHT')) return 'turn right';
  return 'continue straight';
}

function stepForProgress(steps: RouteStep[], distanceM: number): { step: RouteStep; next?: RouteStep; remainingM: number } | null {
  if (!steps.length) return null;
  let cumulative = 0;
  for (let index = 0; index < steps.length; index += 1) {
    const step = steps[index];
    if (distanceM <= cumulative || index === steps.length - 1) {
      return { step, next: steps[index + 1], remainingM: Math.max(0, cumulative - distanceM) };
    }
    cumulative += Math.max(0, step.distance_m);
  }
  return { step: steps[steps.length - 1], remainingM: 0 };
}

function roadStepForProgress(steps: RouteStep[], distanceM: number): RouteStep | undefined {
  let cumulative = 0;
  for (const step of steps) {
    const end = cumulative + Math.max(0, step.distance_m);
    if (distanceM < end) return step;
    cumulative = end;
  }
  return steps.at(-1);
}

function locationForHazard(hazard: HazardOnRoute, steps: RouteStep[]): string | undefined {
  if (hazard.location_label) return hazard.location_label;
  if (hazard.route_progress_m === undefined) return undefined;
  const instruction = stepForProgress(steps, hazard.route_progress_m)?.step.instruction;
  const match = instruction?.match(/\b(?:onto|on|toward|towards|to)\s+(.+)$/i);
  return match?.[1]?.replace(/[,.].*$/, '').trim();
}

function cameraPadding(map: google.maps.Map): { top: number; bottom: number; left: number; right: number } {
  const mapDiv = map.getDiv();
  const rect = mapDiv.getBoundingClientRect();
  const height = mapDiv.clientHeight || rect.height;
  const maneuverBottom = document.querySelector('.route-preview-maneuver')?.getBoundingClientRect().bottom;
  const controlsTop = document.querySelector('.route-preview-controls')?.getBoundingClientRect().top;
  const top = maneuverBottom === undefined ? height * 0.28 : maneuverBottom - rect.top + 16;
  const bottom = controlsTop === undefined ? height * 0.76 : rect.bottom - controlsTop + 16;
  return { top, bottom, left: 24, right: 24 };
}

function centeredForOverlays(
  map: google.maps.Map,
  point: Point,
  zoom: number,
  verticalPosition: number,
  heading: number,
): Point {
  const mapDiv = map.getDiv();
  const mapRect = mapDiv.getBoundingClientRect();
  const height = mapDiv.clientHeight || mapRect.height;
  if (!height) return point;

  const padding = cameraPadding(map);
  const top = padding.top;
  const bottom = height - padding.bottom;
  const targetY = top + Math.max(height * 0.25, bottom - top) * verticalPosition;
  const offsetY = targetY - height / 2;
  const scale = 256 * 2 ** zoom;
  const headingRadians = heading * Math.PI / 180;
  const verticalOffset = offsetY / scale;
  const worldX = (point.lng + 180) / 360 + Math.sin(headingRadians) * verticalOffset;
  const worldY = (1 - Math.asinh(Math.tan(point.lat * Math.PI / 180)) / Math.PI) / 2 +
    Math.cos(headingRadians) * verticalOffset;
  const latitude = Math.atan(Math.sinh(Math.PI * (1 - 2 * worldY))) * 180 / Math.PI;
  return { lat: latitude, lng: worldX * 360 - 180 };
}

function routeOverview(path: Point[], map: google.maps.Map): { center: Point; zoom: number } {
  const lats = path.map((point) => point.lat);
  const lngs = path.map((point) => point.lng);
  const north = Math.max(...lats);
  const south = Math.min(...lats);
  const east = Math.max(...lngs);
  const west = Math.min(...lngs);
  const mercatorY = (latitude: number) => {
    const radians = Math.max(-85, Math.min(85, latitude)) * Math.PI / 180;
    return (1 - Math.asinh(Math.tan(radians)) / Math.PI) / 2;
  };
  const xFraction = Math.max(1e-6, (east - west) / 360);
  const yFraction = Math.max(1e-6, mercatorY(south) - mercatorY(north));
  const mapDiv = map.getDiv();
  const rect = mapDiv.getBoundingClientRect();
  const width = mapDiv.clientWidth || rect.width;
  const height = mapDiv.clientHeight || rect.height;
  const padding = cameraPadding(map);
  const fitWidth = Math.max(80, width - padding.left - padding.right);
  const fitHeight = Math.max(80, height - padding.top - padding.bottom);
  const zoom = Math.max(3, Math.min(16,
    Math.log2(fitWidth / (256 * xFraction)),
    Math.log2(fitHeight / (256 * yFraction)),
  ));
  const center = { lat: (north + south) / 2, lng: (east + west) / 2 };
  return { center: centeredForOverlays(map, center, zoom, 0.5, 0), zoom };
}

function PreviewMap({ point, path, heading, zoom, mapId, isPresented }: {
  point: Point;
  path: Point[];
  heading: number;
  zoom: number;
  mapId: string;
  isPresented: boolean;
}) {
  const map = useMap();
  const lines = useRef<google.maps.Polyline[]>([]);
  const followed = useRef(false);
  const zoomRef = useRef<number | null>(null);
  const headingRef = useRef(heading);
  const fitTimer = useRef<number | null>(null);

  useEffect(() => {
    if (!map || !path.length || !isPresented) return;
    const casing = new google.maps.Polyline({
      map, path, geodesic: true, clickable: false, strokeColor: '#ffffff', strokeOpacity: 0.94, strokeWeight: 11,
      zIndex: 4,
    });
    const route = new google.maps.Polyline({
      map, path, geodesic: true, clickable: false, strokeColor: '#007AFF', strokeOpacity: 1, strokeWeight: 6,
      zIndex: 5,
    });
    lines.current = [casing, route];
    followed.current = false;
    zoomRef.current = null;
    const overview = routeOverview(path, map);
    map.moveCamera({ center: overview.center, zoom: overview.zoom, heading: 0, tilt: 0 });
    fitTimer.current = window.setTimeout(() => {
      zoomRef.current = overview.zoom;
      followed.current = true;
    }, ROUTE_FIT_DURATION_MS);
    return () => {
      if (fitTimer.current !== null) window.clearTimeout(fitTimer.current);
      lines.current.forEach((line) => line.setMap(null));
      lines.current = [];
      followed.current = false;
    };
  }, [isPresented, map, mapId, path]);

  useEffect(() => {
    if (!map || !followed.current) return;
    const currentZoom = zoomRef.current ?? map.getZoom() ?? zoom;
    const zoomDelta = zoom - currentZoom;
    const nextZoom = currentZoom + Math.sign(zoomDelta) * Math.min(Math.abs(zoomDelta), 0.25);
    zoomRef.current = nextZoom;
    const isVector = map.getRenderingType?.() === google.maps.RenderingType.VECTOR;
    let nextHeading = 0;
    if (isVector) {
      const turn = ((heading - headingRef.current + 540) % 360) - 180;
      nextHeading = (headingRef.current + turn * 0.16 + 360) % 360;
      headingRef.current = nextHeading;
    }
    const cameraCenter = centeredForOverlays(map, point, nextZoom, 0.86, isVector ? nextHeading : 0);
    map.moveCamera({
      center: cameraCenter,
      zoom: nextZoom,
      heading: nextHeading,
      tilt: isVector ? 45 : 0,
    });
  }, [map, mapId, point, heading, zoom]);

  return (
    <AdvancedMarker
      position={point}
      title="Preview car position"
      zIndex={20}
      onClick={() => { followed.current = true; map?.panTo(point); }}
    >
      <div className="route-preview-car" style={{ transform: `rotate(${heading}deg)` }} aria-hidden="true">
        <IonIcon icon={navigateOutline} />
      </div>
    </AdvancedMarker>
  );
}

export default function RoutePreview({ isOpen, route, departureTime, selectedDeparture, googleMapsUrl, onClose }: Props) {
  const [progress, setProgress] = useState(0);
  const progressRef = useRef(0);
  const [isPresented, setIsPresented] = useState(false);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState<1 | 2>(1);
  const [dark, setDark] = useState(() => window.matchMedia('(prefers-color-scheme: dark)').matches);
  const [callout, setCallout] = useState<HazardOnRoute | null>(null);
  const shownHazards = useRef(new Set<string>());
  const calloutTimer = useRef<number | null>(null);

  const steps = route.steps ?? [];
  const path = useMemo(() => routeCoordinates(route), [route]);
  const position = useMemo(() => interpolate(path, progress), [path, progress]);
  const progressM = Math.max(0, route.distance_m) * progress;
  const activeStep = stepForProgress(steps, progressM);
  const roadStep = roadStepForProgress(steps, progressM);
  const zoom = roadStep && /\b(?:I-\d+|SR-?\d+|highway|freeway|expressway|turnpike)\b/i.test(roadStep.instruction) ? 15 : 16;
  const remainingSeconds = Math.ceil(route.duration_s * (1 - progress));
  const remainingMeters = Math.ceil(route.distance_m * (1 - progress));
  const estimatedArrival = new Date(departureTime.getTime() + route.duration_s * 1000);
  const nearbyHazard = (route.hazards_on_route ?? []).find((hazard) => {
    if (hazard.route_progress_m === undefined) return false;
    const distance = hazard.route_progress_m - progressM;
    return distance >= 0 && distance <= 300;
  }) ?? null;

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const change = (event: MediaQueryListEvent) => setDark(event.matches);
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);

  useEffect(() => () => {
    if (calloutTimer.current !== null) window.clearTimeout(calloutTimer.current);
  }, []);

  useEffect(() => {
    if (!isOpen || !playing) return;
    let last = 0;
    let frame = 0;
    const advance = (now: number) => {
      if (!last) last = now;
      const elapsed = now - last;
      last = now;
      const next = Math.min(1, progressRef.current + elapsed * speed / PREVIEW_DURATION_MS);
      progressRef.current = next;
      setProgress(next);
      if (next >= 1) setPlaying(false);
      else frame = window.requestAnimationFrame(advance);
    };
    frame = window.requestAnimationFrame(advance);
    return () => window.cancelAnimationFrame(frame);
  }, [isOpen, playing, speed]);

  useEffect(() => {
    if (!nearbyHazard || shownHazards.current.has(nearbyHazard.hazard_id)) return;
    shownHazards.current.add(nearbyHazard.hazard_id);
    setCallout(nearbyHazard);
    if (calloutTimer.current !== null) window.clearTimeout(calloutTimer.current);
    calloutTimer.current = window.setTimeout(() => setCallout(null), 5_000);
    void Haptics.selectionChanged().catch(() => {});
  }, [nearbyHazard]);

  const hazardToken = callout ? HAZARD_TOKENS[callout.hazard_type] : null;
  const hazardDistance = callout?.route_progress_m === undefined ? 0 : Math.max(0, callout.route_progress_m - progressM);
  const hazardLocation = callout ? locationForHazard(callout, steps) : undefined;

  return (
    <IonModal
      isOpen={isOpen}
      onWillPresent={() => {
        setIsPresented(false);
        progressRef.current = 0;
        setProgress(0);
        setSpeed(1);
        setPlaying(!window.matchMedia('(prefers-reduced-motion: reduce)').matches);
        setCallout(null);
        shownHazards.current.clear();
      }}
      onDidPresent={() => setIsPresented(true)}
      onDidDismiss={onClose}
      backdropDismiss={false}
      className="route-preview-modal"
    >
      <div className="route-preview" aria-label="Route preview">
        <Map
          className="route-preview-map"
          style={{ position: 'absolute', inset: 0 }}
          defaultCenter={path[0] ?? { lat: 25.7617, lng: -80.1918 }}
          defaultZoom={13}
          mapId={dark ? DARK_MAP_ID : LIGHT_MAP_ID}
          colorScheme="FOLLOW_SYSTEM"
          disableDefaultUI
          gestureHandling="greedy"
          keyboardShortcuts={false}
        >
          {(route.hazards_on_route ?? []).map((hazard) => {
            if (hazard.route_progress_m === undefined || route.distance_m <= 0) return null;
            const hazardPosition = interpolate(path, hazard.route_progress_m / route.distance_m).point;
            const token = HAZARD_TOKENS[hazard.hazard_type];
            return (
              <AdvancedMarker
                key={hazard.hazard_id}
                position={hazardPosition}
                title={`${hazard.title}${hazard.location_label ? ` on ${hazard.location_label}` : ''}`}
                zIndex={10}
              >
                <div
                  className="route-preview-hazard-marker"
                  style={{ '--hazard-color': dark ? token.colorDark : token.colorLight } as CSSProperties}
                  aria-hidden="true"
                >
                  <IonIcon icon={token.icon} />
                </div>
              </AdvancedMarker>
            );
          })}
          <PreviewMap point={position.point} path={path} heading={position.heading} zoom={zoom} mapId={dark ? DARK_MAP_ID : LIGHT_MAP_ID} isPresented={isPresented} />
        </Map>

        <header className="route-preview-header glass">
          <IonButton fill="clear" aria-label="Close route preview" onClick={onClose}>
            <IonIcon icon={closeOutline} slot="icon-only" aria-hidden="true" />
          </IonButton>
          <div className="route-preview-heading">
            <strong>Route preview</strong>
            <span>Preview only · Google Maps handles navigation</span>
          </div>
          <span className="route-preview-badge">PREVIEW</span>
        </header>

        <section className="route-preview-maneuver glass" aria-live="polite" aria-label="Upcoming maneuver">
          <div className="maneuver-icon" aria-label={maneuverLabel(activeStep?.step.maneuver)}>{maneuverGlyph(activeStep?.step.maneuver)}</div>
          <div className="maneuver-copy">
            <div className="maneuver-distance">{activeStep ? activeStep.remainingM <= 40 ? 'Now' : formatDistance(activeStep.remainingM) : 'Follow the route'}</div>
            <h2>{activeStep?.step.instruction ?? 'Follow the blue route'}</h2>
            {activeStep && <p>Then · {activeStep.next?.instruction ?? 'Arrive at destination'}</p>}
          </div>
        </section>

        {callout && hazardToken && (
          <div
            key={callout.hazard_id}
            className="route-preview-hazard glass"
            role="status"
            style={{ '--hazard-color': dark ? hazardToken.colorDark : hazardToken.colorLight } as CSSProperties}
          >
            <IonIcon icon={hazardToken.icon} aria-hidden="true" />
            <div>
              <strong>{callout.title}{hazardLocation ? ` on ${hazardLocation}` : ''}</strong>
              <span>{hazardDistance > 0 ? `in ${formatDistance(hazardDistance)}` : 'at this point'} · route hazard</span>
            </div>
          </div>
        )}

        <section className="route-preview-controls glass" aria-label="Preview controls">
          {selectedDeparture && <div className="route-preview-leave">Leave at {formatClockTime(selectedDeparture)}</div>}
          <div className="route-preview-summary">
            <div>
              <strong>{formatClockTime(estimatedArrival)}</strong>
              <span>ETA · {formatDuration(remainingSeconds)} left</span>
            </div>
            <div className="route-preview-summary-distance">
              <strong>{formatDistance(remainingMeters)}</strong>
              <span>remaining</span>
            </div>
          </div>

          <input
            className="route-preview-scrubber"
            aria-label="Scrub through route preview"
            type="range"
            min="0"
            max="1000"
            step="1"
            value={Math.round(progress * 1000)}
            style={{ '--route-progress': `${progress * 100}%` } as CSSProperties}
            onChange={(event) => {
              setPlaying(false);
              const next = Number(event.target.value) / 1000;
              progressRef.current = next;
              setProgress(next);
            }}
          />

          <div className="route-preview-playback">
            <IonButton
              fill="clear"
              aria-label={playing ? 'Pause route preview' : 'Play route preview'}
              onClick={() => {
                if (progress >= 1) {
                  progressRef.current = 0;
                  setProgress(0);
                  setPlaying(true);
                } else {
                  setPlaying((current) => !current);
                }
              }}
            >
              <IonIcon icon={playing ? pauseOutline : playOutline} slot="icon-only" aria-hidden="true" />
            </IonButton>
            <IonButton fill="outline" shape="round" className="route-preview-speed" onClick={() => setSpeed((current) => current === 1 ? 2 : 1)}>
              {speed}×
            </IonButton>
            <IonButton
              expand="block"
              shape="round"
              className="route-preview-start"
              disabled={!googleMapsUrl}
              onClick={() => {
                if (googleMapsUrl) void openLink(googleMapsUrl);
              }}
            >
              Start in Google Maps
            </IonButton>
          </div>
        </section>
      </div>
    </IonModal>
  );
}
