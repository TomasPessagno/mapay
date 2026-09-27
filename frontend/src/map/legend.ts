import type { HazardType } from '../lib/types';
import {
  waterOutline,
  rainyOutline,
  constructOutline,
  removeCircleOutline,
  carOutline,
  walkOutline,
  discOutline,
  warningOutline,
  calendarOutline
} from 'ionicons/icons';

export interface LegendToken {
  name: string;
  // Short label for chips, where the full name would wrap ("Weather alert ×2", not
  // "Heavy rain / weather alert ×2").
  chipName: string;
  colorLight: string;
  colorDark: string;
  icon: string;
  drawnAs: string;
}

export const HAZARD_TOKENS: Record<HazardType, LegendToken> = {
  flood: { name: 'Flooded street', chipName: 'Flood', colorLight: '#32ADE6', colorDark: '#64D2FF', icon: waterOutline, drawnAs: 'Wide translucent band on streets + areas with outline, water-waves icon' },
  weather: { name: 'Heavy rain / weather alert', chipName: 'Weather alert', colorLight: '#5856D6', colorDark: '#5E5CE6', icon: rainyOutline, drawnAs: 'Translucent area (25 %), no outline, cloud-rain icon' },
  construction: { name: 'Construction', chipName: 'Roadwork', colorLight: '#FF9500', colorDark: '#FF9F0A', icon: constructOutline, drawnAs: 'Cone icon + area outline' },
  closure: { name: 'Road closure', chipName: 'Closure', colorLight: '#1C1C1E', colorDark: '#F2F2F7', icon: removeCircleOutline, drawnAs: 'Dashed line + no-entry icon' },
  congestion: { name: 'Congestion', chipName: 'Traffic', colorLight: '#FF3B30', colorDark: '#FF3B30', icon: carOutline, drawnAs: 'Line along the road' },
  no_sidewalk: { name: 'No sidewalk', chipName: 'No sidewalk', colorLight: '#AF52DE', colorDark: '#BF5AF2', icon: walkOutline, drawnAs: 'Dotted line, zoom ≥ 15 only' },
  pothole: { name: 'Pothole', chipName: 'Pothole', colorLight: '#A2845E', colorDark: '#AC8E68', icon: discOutline, drawnAs: 'Small dot' },
  incident: { name: 'Incident / police / news', chipName: 'Incident', colorLight: '#FF2D55', colorDark: '#FF375F', icon: warningOutline, drawnAs: 'Pin with !' },
  event: { name: 'Event / holiday', chipName: 'Event', colorLight: '#34C759', colorDark: '#30D158', icon: calendarOutline, drawnAs: 'Pin with calendar icon' },
};
