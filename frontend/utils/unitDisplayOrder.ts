/** Stable ordering and explicit occupancy grouping for property unit cards (owner + manager UIs). */

export type UnitSortable = {
  id: number;
  unit_label: string;
  is_primary_residence?: boolean;
};

/** Primary residence first, then label (case-insensitive), then id — matches backend `unit_display_order`. */
export function compareUnitsForDisplay(a: UnitSortable, b: UnitSortable): number {
  const pa = a.is_primary_residence ? 1 : 0;
  const pb = b.is_primary_residence ? 1 : 0;
  if (pa !== pb) return pb - pa;
  const la = (a.unit_label || '').toLowerCase();
  const lb = (b.unit_label || '').toLowerCase();
  if (la < lb) return -1;
  if (la > lb) return 1;
  return a.id - b.id;
}

export type OccupancyGroupKey = 'occupied' | 'unconfirmed' | 'vacant' | 'unknown';

const GROUP_ORDER: OccupancyGroupKey[] = ['occupied', 'unconfirmed', 'vacant', 'unknown'];

const GROUP_HEADINGS: Record<OccupancyGroupKey, string> = {
  occupied: 'Occupied units',
  unconfirmed: 'Unconfirmed status',
  vacant: 'Vacant units',
  unknown: 'Other status',
};

function normalizeOccupancyGroupKey(status: string): OccupancyGroupKey {
  const t = (status || '').toLowerCase().trim();
  if (t === 'occupied') return 'occupied';
  if (t === 'unconfirmed') return 'unconfirmed';
  if (t === 'vacant') return 'vacant';
  if (t === 'unknown') return 'unknown';
  return 'unknown';
}

export type UnitRowWithStatus<T extends UnitSortable> = { u: T; status: string };

/** Groups rows by effective occupancy; each group is labeled. Units within a group use `compareUnitsForDisplay`. */
export function partitionUnitsByOccupancyStatus<T extends UnitSortable>(
  rows: UnitRowWithStatus<T>[],
): { key: OccupancyGroupKey; heading: string; items: UnitRowWithStatus<T>[] }[] {
  const buckets = new Map<OccupancyGroupKey, UnitRowWithStatus<T>[]>();
  for (const k of GROUP_ORDER) buckets.set(k, []);
  for (const row of rows) {
    const key = normalizeOccupancyGroupKey(row.status);
    buckets.get(key)!.push(row);
  }
  const out: { key: OccupancyGroupKey; heading: string; items: UnitRowWithStatus<T>[] }[] = [];
  for (const key of GROUP_ORDER) {
    const items = buckets.get(key)!;
    if (items.length === 0) continue;
    items.sort((a, b) => compareUnitsForDisplay(a.u, b.u));
    out.push({ key, heading: GROUP_HEADINGS[key], items: [...items] });
  }
  return out;
}
