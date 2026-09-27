import { IonChip, IonIcon } from '@ionic/react';
import type { HazardOnRoute } from '../lib/types';
import { groupHazards, MAX_HAZARD_CHIPS } from '../lib/hazardGroups';

interface Props {
  hazards?: HazardOnRoute[] | null;
  max?: number;
}

export default function HazardChips({ hazards, max = MAX_HAZARD_CHIPS }: Props) {
  const { groups, hidden } = groupHazards(hazards, max);
  if (!groups.length) return null;

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '8px' }}>
      {groups.map((group) => (
        <IonChip
          key={group.hazard_type}
          outline
          style={{ margin: 0 }}
          aria-label={`${group.label}, ${group.count} on this route`}
        >
          <IonIcon icon={group.icon} />
          {group.count > 1 ? `${group.label} ×${group.count}` : group.label}
        </IonChip>
      ))}
      {hidden > 0 && (
        <span style={{ fontSize: '13px', color: 'var(--ion-color-medium)' }}>+{hidden} more</span>
      )}
    </div>
  );
}
