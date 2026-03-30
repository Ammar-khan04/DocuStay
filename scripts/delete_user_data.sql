-- Delete all app data for users matching the given emails (any role).
-- Covers: owner, tenant, manager, guest; properties they own; stays they appear on;
-- invitations they own/sent; signatures, ledgers, alerts, assignments, etc.
--
-- Edit the emails array below, then run:
--   psql $DATABASE_URL -f scripts/delete_user_data.sql
--
-- Or use the Python helper (same logic, parameterized):
--   python scripts/delete_user_data.py email1@example.com email2@example.com
--
-- Order respects FKs: children of stays/residents first, then stays/invitations, properties, profiles, users.
--
-- PostgreSQL: no trailing comma after the last element in ARRAY[ 'a', 'b' ] — a comma before ] causes:
--   ERROR: syntax error at or near "]"
-- Delete stays before invitations: stays.invitation_id references invitations.id (FK).

DO $$
DECLARE
  emails text[] := ARRAY[
    'walexes826@medevsa.com'
  ];
  emails_lower text[];
  user_ids int[];
  owner_profile_ids int[];
  property_ids int[];
  unit_ids int[];
  stay_ids int[];
  invitation_ids int[];
BEGIN
  SELECT COALESCE(array_agg(lower(btrim(e))) FILTER (WHERE btrim(e) <> ''), ARRAY[]::text[])
  INTO emails_lower
  FROM unnest(emails) AS u(e);

  SELECT array_agg(id) INTO user_ids FROM users WHERE lower(btrim(email)) = ANY(emails_lower);
  IF user_ids IS NULL THEN user_ids := ARRAY[]::int[]; END IF;

  SELECT array_agg(id) INTO owner_profile_ids FROM owner_profiles WHERE user_id = ANY(user_ids);
  IF owner_profile_ids IS NULL THEN owner_profile_ids := ARRAY[]::int[]; END IF;

  SELECT array_agg(id) INTO property_ids FROM properties WHERE owner_profile_id = ANY(owner_profile_ids);
  IF property_ids IS NULL THEN property_ids := ARRAY[]::int[]; END IF;

  SELECT array_agg(id) INTO unit_ids FROM units WHERE property_id = ANY(property_ids);
  IF unit_ids IS NULL THEN unit_ids := ARRAY[]::int[]; END IF;

  -- Stays: by user/property, or any stay tied to an invitation we will remove (required before DELETE invitations)
  SELECT COALESCE(array_agg(DISTINCT sid) FILTER (WHERE sid IS NOT NULL), ARRAY[]::int[]) INTO stay_ids
  FROM (
    SELECT s.id AS sid FROM stays s
    WHERE s.guest_id = ANY(user_ids)
       OR s.owner_id = ANY(user_ids)
       OR s.invited_by_user_id = ANY(user_ids)
       OR s.property_id = ANY(property_ids)
    UNION
    SELECT s.id FROM stays s
    INNER JOIN invitations i ON i.id = s.invitation_id
    WHERE i.owner_id = ANY(user_ids)
       OR i.invited_by_user_id = ANY(user_ids)
       OR i.property_id = ANY(property_ids)
  ) stay_scope;

  -- Invitation ids for ledger/alerts: invitations in delete set + invitation_id on stays we delete
  SELECT COALESCE(array_agg(DISTINCT inv_id) FILTER (WHERE inv_id IS NOT NULL), ARRAY[]::int[]) INTO invitation_ids
  FROM (
    SELECT id AS inv_id FROM invitations
    WHERE owner_id = ANY(user_ids)
       OR invited_by_user_id = ANY(user_ids)
       OR property_id = ANY(property_ids)
    UNION
    SELECT invitation_id AS inv_id FROM stays
    WHERE id = ANY(stay_ids) AND invitation_id IS NOT NULL
  ) inv_union;

  -- Dashboard alerts (notification_attempts CASCADE from dashboard_alerts)
  DELETE FROM dashboard_alerts
  WHERE user_id = ANY(user_ids)
     OR property_id = ANY(property_ids)
     OR stay_id = ANY(stay_ids)
     OR invitation_id = ANY(invitation_ids);

  DELETE FROM event_ledger
  WHERE actor_user_id = ANY(user_ids)
     OR property_id = ANY(property_ids)
     OR unit_id = ANY(unit_ids)
     OR stay_id = ANY(stay_ids)
     OR invitation_id = ANY(invitation_ids);

  DELETE FROM audit_logs
  WHERE actor_user_id = ANY(user_ids)
     OR property_id = ANY(property_ids)
     OR stay_id = ANY(stay_ids)
     OR invitation_id = ANY(invitation_ids);

  DELETE FROM presence_away_periods
  WHERE stay_id = ANY(stay_ids)
     OR resident_presence_id IN (
        SELECT id FROM resident_presences WHERE user_id = ANY(user_ids) OR unit_id = ANY(unit_ids)
      );

  DELETE FROM stay_presences WHERE stay_id = ANY(stay_ids);

  DELETE FROM resident_presences WHERE user_id = ANY(user_ids) OR unit_id = ANY(unit_ids);

  DELETE FROM resident_modes WHERE user_id = ANY(user_ids) OR unit_id = ANY(unit_ids);

  DELETE FROM tenant_assignments
  WHERE user_id = ANY(user_ids)
     OR unit_id = ANY(unit_ids)
     OR invited_by_user_id = ANY(user_ids);

  DELETE FROM property_manager_assignments
  WHERE user_id = ANY(user_ids)
     OR property_id = ANY(property_ids)
     OR assigned_by_user_id = ANY(user_ids);

  DELETE FROM manager_invitations
  WHERE invited_by_user_id = ANY(user_ids)
     OR property_id = ANY(property_ids)
     OR lower(btrim(email)) = ANY(emails_lower);

  DELETE FROM guest_pending_invites WHERE user_id = ANY(user_ids) OR invitation_id = ANY(invitation_ids);

  -- Signatures: this user signed / guest_email match / invites we are about to delete (owner or property scope)
  DELETE FROM agreement_signatures
  WHERE used_by_user_id = ANY(user_ids)
     OR lower(btrim(guest_email)) = ANY(emails_lower)
     OR invitation_code IN (
          SELECT invitation_code FROM invitations
          WHERE owner_id = ANY(user_ids)
             OR invited_by_user_id = ANY(user_ids)
             OR property_id = ANY(property_ids)
        );

  -- Stays must be removed before invitations (stays.invitation_id FK)
  DELETE FROM stays WHERE id = ANY(stay_ids);

  DELETE FROM invitations
  WHERE owner_id = ANY(user_ids)
     OR invited_by_user_id = ANY(user_ids)
     OR property_id = ANY(property_ids);

  DELETE FROM bulk_upload_jobs WHERE user_id = ANY(user_ids);

  DELETE FROM property_authority_letters WHERE property_id = ANY(property_ids);

  DELETE FROM property_utility_providers WHERE property_id = ANY(property_ids);

  DELETE FROM units WHERE property_id = ANY(property_ids);

  DELETE FROM properties WHERE owner_profile_id = ANY(owner_profile_ids);

  DELETE FROM owner_poa_signatures WHERE used_by_user_id = ANY(user_ids);

  DELETE FROM owner_profiles WHERE user_id = ANY(user_ids);

  DELETE FROM guest_profiles WHERE user_id = ANY(user_ids);

  DELETE FROM pending_registrations WHERE lower(btrim(email)) = ANY(emails_lower);

  DELETE FROM users WHERE lower(btrim(email)) = ANY(emails_lower);

  RAISE NOTICE 'Deleted all data for % user(s) (matched by email).', COALESCE(array_length(user_ids, 1), 0);
END $$;
