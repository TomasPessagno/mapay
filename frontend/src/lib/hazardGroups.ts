import { alertCircleOutline } from 'ionicons/icons';
import { HAZARD_TOKENS } from '../map/legend';
import type { HazardOnRoute, HazardType } from './types';

export interface HazardGroup {
  hazard_type: HazardType;
  label: string;
  count: number;
  icon: string;
}

export const MAX_HAZARD_CHIPS = 6;

// One chip per category: "No sidewalk ×30" rather than 30 identical "No sidewalk" chips. The
// backend already orders hazards worst-first (routing/scoring.py), so first appearance is the
// severity order; later ones are merged into their category's group.
export function groupHazards(
  hazards: HazardOnRoute[] | null | undefined,
  max: number = MAX_HAZARD_CHIPS,
): { groups: HazardGroup[]; hidden: number } {
  const order: HazardType[] = [];
  const byType = new Map<HazardType, HazardGroup>();
  for (const hazard of hazards ?? []) {
    const token = HAZARD_TOKENS[hazard.hazard_type];
    let group = byType.get(hazard.hazard_type);
    if (!group) {
      group = {
        hazard_type: hazard.hazard_type,
        label: token?.chipName ?? token?.name ?? hazard.title ?? 'Hazard',
        count: 0,
        icon: token?.icon ?? alertCircleOutline,
      };
      byType.set(hazard.hazard_type, group);
      order.push(hazard.hazard_type);
    }
    group.count += 1;
  }
  const all = order.map((type) => byType.get(type)!);
  return {
    groups: all.slice(0, max),
    hidden: all.slice(max).reduce((sum, group) => sum + group.count, 0),
  };
}
