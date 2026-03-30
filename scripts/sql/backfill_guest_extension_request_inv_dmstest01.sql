-- Backfill guest_extension_requests for bootstrap DMS test stay INV-DMSTEST01 / test guest.
-- Use when the guest already triggered extension (email + alerts) before the table existed.
--
-- Tenant dashboard lists rows where tenant_user_id = logged-in tenant. This script uses the
-- bootstrap tenant (bahofon622@smkanba.com) as host. If your stay is still property-lane
-- (invited_by = owner), uncomment the UPDATE block so extension features match tenant-lane.
--
-- Run against your DocuStay PostgreSQL DB, then refresh the tenant dashboard.

BEGIN;

-- Optional: make stay + invitation tenant-lane (required for guest "request extension" in app)
-- Uncomment if invited_by should be the tenant host:
-- UPDATE invitations inv
-- SET invited_by_user_id = (SELECT id FROM users WHERE email = 'bahofon622@smkanba.com')
-- WHERE inv.invitation_code = 'INV-DMSTEST01';
-- UPDATE stays s
-- SET invited_by_user_id = (SELECT id FROM users WHERE email = 'bahofon622@smkanba.com')
-- FROM invitations inv
-- WHERE s.invitation_id = inv.id AND inv.invitation_code = 'INV-DMSTEST01';

INSERT INTO guest_extension_requests (
  stay_id,
  property_id,
  guest_user_id,
  tenant_user_id,
  message,
  status,
  created_at,
  responded_at,
  tenant_note
)
SELECT
  s.id,
  s.property_id,
  s.guest_id,
  ten.id,
  'Longer stay requested (backfilled after notification without DB row).',
  'pending',
  NOW(),
  NULL,
  NULL
FROM stays s
JOIN invitations inv ON inv.id = s.invitation_id
JOIN users gu ON gu.id = s.guest_id
JOIN users ten ON ten.email = 'bahofon622@smkanba.com'
WHERE inv.invitation_code = 'INV-DMSTEST01'
  AND gu.email = 'ditiko6553@muncloud.com'
  AND NOT EXISTS (
    SELECT 1
    FROM guest_extension_requests ger
    WHERE ger.stay_id = s.id
      AND ger.status = 'pending'
  );

COMMIT;
