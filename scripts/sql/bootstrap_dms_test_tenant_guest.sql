-- Bootstrap: test tenant + test guest + accepted stay for Status Confirmation (DMS) testing
-- PostgreSQL-oriented. Adjust enum casts if your DB uses different type names.
--
-- Logins after insert:
--   Tenant: bahofon622@smkanba.com / bahofon622
--   Guest:  ditiko6553@muncloud.com / ditiko6553
-- Scratch owner (created below): dms-scratch-owner@test.local / dms_scratch_owner
--
-- Stay is PROPERTY-LANE (invited_by = owner) so Status Confirmation emails fire.
-- Tenant exists + tenant_assignment so you can also switch the invitation to tenant-lane for negative tests.
--
-- Regenerate password hashes with:
--   python -c "import bcrypt; print(bcrypt.hashpw(b'bahofon622', bcrypt.gensalt()).decode())"
--   python -c "import bcrypt; print(bcrypt.hashpw(b'ditiko6553', bcrypt.gensalt()).decode())"
--   python -c "import bcrypt; print(bcrypt.hashpw(b'dms_scratch_owner', bcrypt.gensalt()).decode())"

BEGIN;

-- ---------------------------------------------------------------------------
-- 0) Cleanup previous test rows (order by FK dependencies)
-- ---------------------------------------------------------------------------
DELETE FROM stays WHERE invitation_id IN (
  SELECT id FROM invitations WHERE invitation_code = 'INV-DMSTEST01'
);
DELETE FROM invitations WHERE invitation_code = 'INV-DMSTEST01';
DELETE FROM tenant_assignments WHERE user_id IN (
  SELECT id FROM users WHERE email IN (
    'bahofon622@smkanba.com',
    'ditiko6553@muncloud.com',
    'dms-scratch-owner@test.local'
  )
);
DELETE FROM guest_profiles WHERE user_id IN (
  SELECT id FROM users WHERE email = 'ditiko6553@muncloud.com'
);
DELETE FROM units WHERE property_id IN (
  SELECT id FROM properties WHERE street = '900 DMS Test Lane' AND city = 'Testville'
);
DELETE FROM properties WHERE street = '900 DMS Test Lane' AND city = 'Testville';
DELETE FROM owner_profiles WHERE user_id IN (
  SELECT id FROM users WHERE email = 'dms-scratch-owner@test.local'
);
DELETE FROM users WHERE email IN (
  'bahofon622@smkanba.com',
  'ditiko6553@muncloud.com',
  'dms-scratch-owner@test.local'
);

-- ---------------------------------------------------------------------------
-- 1) Scratch owner (property owner for invitation.owner_id / stay.owner_id)
--    Password: dms_scratch_owner   (change below with bcrypt if your app uses different settings)
-- ---------------------------------------------------------------------------
INSERT INTO users (
  email,
  hashed_password,
  role,
  full_name,
  first_name,
  last_name,
  email_verified,
  email_verification_code,
  email_verification_expires_at,
  identity_verified_at,
  poa_waived_at,
  created_at,
  updated_at
) VALUES (
  'dms-scratch-owner@test.local',
  '$2b$12$LMbGo4o9KJpqpwaU4vt34.Curlt0tAcThPs4GmyirFEGsxMiVGoZm',
  'owner',
  'DMS Scratch Owner',
  'DMS',
  'Owner',
  TRUE,
  NULL,
  NULL,
  NOW(),
  NOW(),
  NOW(),
  NOW()
);

INSERT INTO owner_profiles (user_id, created_at, updated_at)
SELECT id, NOW(), NOW() FROM users WHERE email = 'dms-scratch-owner@test.local';

INSERT INTO properties (
  owner_profile_id,
  name,
  street,
  city,
  state,
  zip_code,
  region_code,
  owner_occupied,
  usat_token_state,
  shield_mode_enabled,
  occupancy_status,
  is_multi_unit,
  vacant_monitoring_enabled,
  created_at,
  updated_at
)
SELECT
  op.id,
  'DMS Test Property',
  '900 DMS Test Lane',
  'Testville',
  'TX',
  '78701',
  'TX',
  FALSE,
  'staged',
  0,
  'occupied',
  TRUE,
  0,
  NOW(),
  NOW()
FROM owner_profiles op
JOIN users u ON u.id = op.user_id
WHERE u.email = 'dms-scratch-owner@test.local';

INSERT INTO units (property_id, unit_label, occupancy_status, is_primary_residence, created_at, updated_at)
SELECT p.id, '1', 'occupied', 0, NOW(), NOW()
FROM properties p
WHERE p.street = '900 DMS Test Lane' AND p.city = 'Testville';

-- ---------------------------------------------------------------------------
-- 2) Tenant user (test tenant) — verified
-- ---------------------------------------------------------------------------
INSERT INTO users (
  email,
  hashed_password,
  role,
  full_name,
  first_name,
  last_name,
  email_verified,
  identity_verified_at,
  created_at,
  updated_at
) VALUES (
  'bahofon622@smkanba.com',
  '$2b$12$UsSX2.WBWiev5nmLD9oD9u5ANl11b.NP2XI6oTGco4zKyECd0KAci',
  'tenant',
  'test tenant',
  'test',
  'tenant',
  TRUE,
  NOW(),
  NOW(),
  NOW()
);

-- ---------------------------------------------------------------------------
-- 3) Guest user (test guest) — verified
-- ---------------------------------------------------------------------------
INSERT INTO users (
  email,
  hashed_password,
  role,
  full_name,
  first_name,
  last_name,
  email_verified,
  identity_verified_at,
  created_at,
  updated_at
) VALUES (
  'ditiko6553@muncloud.com',
  '$2b$12$mIepop1XJ5Is87B9/mVg8eiraESS6.pWGOUSqoxjtqaFoMHuqn/G6',
  'guest',
  'test guest',
  'test',
  'guest',
  TRUE,
  NOW(),
  NOW(),
  NOW()
);

INSERT INTO guest_profiles (user_id, full_legal_name, permanent_home_address, gps_checkin_acknowledgment, created_at, updated_at)
SELECT id, 'test guest', '123 Test St, Testville, TX 78701', TRUE, NOW(), NOW()
FROM users WHERE email = 'ditiko6553@muncloud.com';

-- ---------------------------------------------------------------------------
-- 4) Tenant assignment (tenant on the same unit as the guest stay)
-- ---------------------------------------------------------------------------
INSERT INTO tenant_assignments (unit_id, user_id, invited_by_user_id, start_date, end_date, created_at)
SELECT u.id, tu.id, ou.id, CURRENT_DATE - 60, CURRENT_DATE + 365, NOW()
FROM units u
JOIN properties p ON p.id = u.property_id
JOIN users tu ON tu.email = 'bahofon622@smkanba.com'
JOIN users ou ON ou.email = 'dms-scratch-owner@test.local'
WHERE p.street = '900 DMS Test Lane' AND p.city = 'Testville' AND u.unit_label = '1';

-- ---------------------------------------------------------------------------
-- 5) Invitation — PROPERTY-LANE (invited_by_user_id = owner) so DMS runs
--     Dates: end = CURRENT_DATE + 2 → first Status Confirmation email on next job run
-- ---------------------------------------------------------------------------
INSERT INTO invitations (
  invitation_code,
  owner_id,
  property_id,
  unit_id,
  invited_by_user_id,
  guest_name,
  guest_email,
  stay_start_date,
  stay_end_date,
  purpose_of_stay,
  relationship_to_owner,
  region_code,
  status,
  token_state,
  invitation_kind,
  dead_mans_switch_enabled,
  dead_mans_switch_alert_email,
  dead_mans_switch_alert_sms,
  dead_mans_switch_alert_dashboard,
  dead_mans_switch_alert_phone,
  created_at
)
SELECT
  'INV-DMSTEST01',
  ou.id,
  p.id,
  u.id,
  ou.id,
  'test guest',
  'ditiko6553@muncloud.com',
  CURRENT_DATE - 7,
  CURRENT_DATE + 2,
  'travel',
  'friend',
  'TX',
  'accepted',
  'BURNED',
  'guest',
  0,
  1,
  0,
  1,
  0,
  NOW()
FROM properties p
JOIN units u ON u.property_id = p.id
JOIN users ou ON ou.email = 'dms-scratch-owner@test.local'
WHERE p.street = '900 DMS Test Lane' AND p.city = 'Testville' AND u.unit_label = '1';

-- ---------------------------------------------------------------------------
-- 6) Stay — checked in; DMS off until job turns on at 48h-before (stay_end = today+2)
-- ---------------------------------------------------------------------------
INSERT INTO stays (
  guest_id,
  owner_id,
  property_id,
  unit_id,
  invitation_id,
  invited_by_user_id,
  stay_start_date,
  stay_end_date,
  intended_stay_duration_days,
  purpose_of_stay,
  relationship_to_owner,
  region_code,
  checked_in_at,
  checked_out_at,
  cancelled_at,
  dead_mans_switch_enabled,
  dead_mans_switch_alert_email,
  dead_mans_switch_alert_sms,
  dead_mans_switch_alert_dashboard,
  dead_mans_switch_alert_phone,
  dead_mans_switch_triggered_at,
  occupancy_confirmation_response,
  created_at,
  updated_at
)
SELECT
  gu.id,
  ou.id,
  p.id,
  u.id,
  inv.id,
  ou.id,
  CURRENT_DATE - 7,
  CURRENT_DATE + 2,
  9,
  'travel',
  'friend',
  'TX',
  NOW(),
  NULL,
  NULL,
  0,
  1,
  0,
  1,
  0,
  NULL,
  NULL,
  NOW(),
  NOW()
FROM invitations inv
JOIN users gu ON gu.email = 'ditiko6553@muncloud.com'
JOIN users ou ON ou.email = 'dms-scratch-owner@test.local'
JOIN properties p ON p.id = inv.property_id
JOIN units u ON u.id = inv.unit_id
WHERE inv.invitation_code = 'INV-DMSTEST01';

COMMIT;

-- ---------------------------------------------------------------------------
-- After run: execute Python job (from repo root, venv with app deps):
--   python -c "from app.database import SessionLocal; from app.services.stay_timer import run_dead_mans_switch_job; db=SessionLocal(); run_dead_mans_switch_job(db); db.close()"
--
-- Tenant-lane NEGATIVE test: point invitation + stay at tenant as inviter:
--   UPDATE invitations SET invited_by_user_id = (SELECT id FROM users WHERE email = 'bahofon622@smkanba.com') WHERE invitation_code = 'INV-DMSTEST01';
--   UPDATE stays SET invited_by_user_id = (SELECT id FROM users WHERE email = 'bahofon622@smkanba.com') WHERE invitation_id = (SELECT id FROM invitations WHERE invitation_code = 'INV-DMSTEST01');
-- Then re-run job — owner/PM should NOT get Status Confirmation for that stay.
-- ---------------------------------------------------------------------------
