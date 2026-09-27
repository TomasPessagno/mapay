import { useEffect, useState } from 'react';
import { IonChip, IonIcon } from '@ionic/react';
import type { HazardOnRoute } from '../lib/types';
import { groupHazards, MAX_HAZARD_CHIPS } from '../lib/hazardGroups';
import { HAZARD_TOKENS } from '../map/legend';

interface Props {
  hazards?: HazardOnRoute[] | null;
  max?: number;
}

export default function HazardChips({ hazards, max = MAX_HAZARD_CHIPS }: Props) {
  const [isDark, setIsDark] = useState(() => window.matchMedia('(prefers-color-scheme: dark)').matches);
  const { groups, hidden } = groupHazards(hazards, max);

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = (event: MediaQueryListEvent) => setIsDark(event.matches);
    media.addEventListener('change', handleChange);
    return () => media.removeEventListener('change', handleChange);
  }, []);

  if (!groups.length) return null;

  return (
    <div className="hazard-chips">
      {groups.map((group) => (
        <IonChip
          key={group.hazard_type}
          className="hazard-chip dynamic-footnote"
          aria-label={`${group.label}, ${group.count} on this route`}
        >
          <IonIcon
            aria-hidden="true"
            icon={group.icon}
            style={{ color: isDark ? HAZARD_TOKENS[group.hazard_type].colorDark : HAZARD_TOKENS[group.hazard_type].colorLight }}
          />
          <span className="hazard-chip-label">
            {group.count > 1 ? `${group.label} ×${group.count}` : group.label}
          </span>
        </IonChip>
      ))}
      {hidden > 0 && (
        <span className="hazard-chip-more dynamic-footnote">+{hidden} more</span>
      )}
    </div>
  );
}
