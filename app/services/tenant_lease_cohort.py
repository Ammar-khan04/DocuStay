"""Group tenant assignments (and overlapping invites) that share a unit and overlapping lease windows."""

from __future__ import annotations

from collections import Counter
from datetime import date

from app.models.invitation import Invitation
from app.models.tenant_assignment import TenantAssignment


def _end_inclusive(d: date | None) -> date:
    """Treat open-ended lease as far-future for overlap tests."""
    return d if d is not None else date(9999, 12, 31)


def date_ranges_overlap(
    a_start: date,
    a_end: date | None,
    b_start: date,
    b_end: date | None,
) -> bool:
    return a_start <= _end_inclusive(b_end) and b_start <= _end_inclusive(a_end)


def assignments_date_overlap(a: TenantAssignment, b: TenantAssignment) -> bool:
    if a.unit_id != b.unit_id:
        return False
    return date_ranges_overlap(a.start_date, a.end_date, b.start_date, b.end_date)


def cluster_assignments_for_unit(unit_id: int, assignments: list[TenantAssignment]) -> list[list[TenantAssignment]]:
    """Connected components: same unit, edges when lease intervals overlap."""
    rows = [ta for ta in assignments if ta.unit_id == unit_id]
    if not rows:
        return []
    n = len(rows)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        pi, pj = find(i), find(j)
        if pi != pj:
            parent[pi] = pj

    for i in range(n):
        for j in range(i + 1, n):
            if assignments_date_overlap(rows[i], rows[j]):
                union(i, j)
    buckets: dict[int, list[TenantAssignment]] = {}
    for i in range(n):
        r = find(i)
        buckets.setdefault(r, []).append(rows[i])
    return list(buckets.values())


def cohort_key_for_cluster(unit_id: int, cluster: list[TenantAssignment]) -> str:
    ids = sorted(ta.id for ta in cluster)
    return f"u{unit_id}-ta-" + "-".join(str(x) for x in ids)


def map_assignment_id_to_cohort_key(assignments: list[TenantAssignment]) -> dict[int, str]:
    out: dict[int, str] = {}
    by_unit: dict[int, list[TenantAssignment]] = {}
    for ta in assignments:
        by_unit.setdefault(ta.unit_id, []).append(ta)
    for uid, rows in by_unit.items():
        for cluster in cluster_assignments_for_unit(uid, rows):
            ck = cohort_key_for_cluster(uid, cluster)
            for ta in cluster:
                out[ta.id] = ck
    return out


def invitation_overlaps_assignment_cluster(inv: Invitation, cluster: list[TenantAssignment]) -> bool:
    if not inv.unit_id or not cluster or inv.unit_id != cluster[0].unit_id:
        return False
    if inv.stay_start_date is None:
        return False
    for ta in cluster:
        if date_ranges_overlap(inv.stay_start_date, inv.stay_end_date, ta.start_date, ta.end_date):
            return True
    return False


def cohort_key_for_pending_invitation(inv: Invitation, assignments: list[TenantAssignment]) -> str | None:
    if not inv.unit_id:
        return None
    uid = inv.unit_id
    unit_assignments = [ta for ta in assignments if ta.unit_id == uid]
    for cluster in cluster_assignments_for_unit(uid, unit_assignments):
        if invitation_overlaps_assignment_cluster(inv, cluster):
            return cohort_key_for_cluster(uid, cluster)
    return f"u{uid}-inv-{inv.id}"


def count_cohort_members(rows: list[dict], *, key: str = "lease_cohort_id") -> None:
    """Mutates rows: set cohort_member_count from shared lease_cohort_id."""
    cids = [r.get(key) for r in rows if r.get(key)]
    counts = Counter(cids)
    for r in rows:
        cid = r.get(key)
        r["cohort_member_count"] = counts[cid] if cid else 1
