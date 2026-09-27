import { IonIcon } from '@ionic/react';
import { mapOutline, sparklesOutline } from 'ionicons/icons';

// Onboarding illustrations (#139): no photography, no mascots — small pieces of the real UI drawn
// with the legend palette from map/legend.ts.

const FLOOD = '#32ADE6';
const CONSTRUCTION = '#FF9500';
const CONGESTION = '#FF3B30';

/** Screen 1: floods, construction, traffic and closures on one colour-coded map. */
export function ColourCodedIllustration() {
  return (
    <div className="ob-figure-inner">
      <svg className="ob-map-svg" viewBox="0 0 300 190" role="img" aria-label="A map with a blue route and colour-coded hazard markers">
        <rect className="ob-map-bg" x="1" y="1" width="298" height="188" rx="26" />
        <path className="ob-map-road ob-map-road-minor" d="M 18 40 C 70 58 118 42 166 58 S 258 84 292 62" />
        <path className="ob-map-road ob-map-road-minor" d="M 40 8 C 58 60 44 112 70 182" />
        <path className="ob-map-road" d="M -6 148 C 66 128 104 132 150 100 S 232 58 306 74" />
        <path className="ob-map-road" d="M 128 -6 C 142 54 176 92 182 196" />
        <path className="ob-map-route-casing" d="M 20 152 C 84 126 112 132 152 98 S 224 58 280 70" />
        <path className="ob-map-route" d="M 20 152 C 84 126 112 132 152 98 S 224 58 280 70" />

        <g transform="translate(92 132)">
          <circle r="13" fill={FLOOD} stroke="var(--system-background)" strokeWidth="3" />
          <path d="M -6 1 q 3 -5 6 0 t 6 0 t 6 0" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" />
        </g>
        <g transform="translate(196 112)">
          <circle r="13" fill={CONGESTION} stroke="var(--system-background)" strokeWidth="3" />
          <rect x="-6" y="-6" width="12" height="12" rx="3.5" fill="#fff" />
          <rect x="-5.5" y="-1" width="11" height="1.6" rx="0.8" fill={CONGESTION} />
        </g>
        <g transform="translate(244 74)">
          <circle r="13" fill={CONSTRUCTION} stroke="var(--system-background)" strokeWidth="3" />
          <path d="M 0 -6 L 6.5 6 L -6.5 6 Z" fill="#fff" />
          <path d="M -4.5 6 L 4.5 6" stroke={CONSTRUCTION} strokeWidth="2" strokeLinecap="round" />
        </g>
        <g transform="translate(132 58)">
          <circle r="13" className="ob-map-closure" stroke="var(--system-background)" strokeWidth="3" />
          <rect x="-6" y="-2" width="12" height="4" rx="2" fill="var(--system-background)" />
        </g>
      </svg>
      <div className="ob-legend">
        <span className="ob-legend-item"><i style={{ background: FLOOD }} />Flood</span>
        <span className="ob-legend-item"><i style={{ background: CONSTRUCTION }} />Roadwork</span>
        <span className="ob-legend-item"><i style={{ background: CONGESTION }} />Traffic</span>
        <span className="ob-legend-item"><i className="ob-legend-closure" />Closure</span>
      </div>
    </div>
  );
}

/** Screen 2: the Lock Screen heads-up, with Start / Customize. */
export function HeadsUpIllustration() {
  return (
    <div className="ob-figure-inner">
      <div className="ob-banner">
        <div className="ob-banner-top">
          <span className="ob-banner-icon"><IonIcon icon={mapOutline} aria-hidden="true" /></span>
          <span className="ob-banner-app">MAPAY</span>
          <span className="ob-banner-when">now</span>
        </div>
        <p className="ob-banner-title">MMC → BBC · leave in 30 min</p>
        <div className="ob-banner-hazards">
          <span className="ob-chip"><i style={{ background: FLOOD }} />Flooded street</span>
          <span className="ob-chip"><i style={{ background: CONSTRUCTION }} />Roadwork</span>
        </div>
        <div className="ob-banner-actions">
          <span className="ob-banner-start">Start</span>
          <span className="ob-banner-customize">Customize</span>
        </div>
      </div>
    </div>
  );
}

/** Screen 3: a route changed in plain English. */
export function PromptIllustration() {
  return (
    <div className="ob-figure-inner">
      <div className="ob-prompt">
        <div className="ob-prompt-field">
          <IonIcon icon={sparklesOutline} className="ob-prompt-sparkle" aria-hidden="true" />
          <span>“stop at a Starbucks and stay off the Palmetto”</span>
        </div>
        <div className="ob-prompt-result">
          <span className="ob-prompt-dot" />
          <span className="ob-prompt-new">New route · 24 min</span>
          <span className="ob-prompt-via">via Starbucks</span>
        </div>
      </div>
    </div>
  );
}
