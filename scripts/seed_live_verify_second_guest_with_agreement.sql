-- PostgreSQL: second guest stay + agreement row with dummy PDF for live-slug "View PDF" / verify.
-- Adjust live_slug and guest_id (30) as needed. Requires a guest invitation tmpl row on the property.
--
-- Minimal PDF in signed_pdf_bytes so GET /public/verify/{code}/signed-agreement serves bytes without Dropbox.

BEGIN;

WITH prop AS (
  SELECT p.id AS property_id, p.region_code, op.user_id AS owner_id,
         (SELECT u2.id FROM units u2 WHERE u2.property_id = p.id ORDER BY u2.id LIMIT 1) AS unit_id
  FROM properties p
  JOIN owner_profiles op ON op.id = p.owner_profile_id
  WHERE p.live_slug = '4UPSA8Y1l3PJznSQ'
    AND p.deleted_at IS NULL
  LIMIT 1
),
tmpl AS (
  SELECT i.*
  FROM invitations i
  CROSS JOIN prop
  WHERE i.property_id = prop.property_id
    AND COALESCE(i.invitation_kind, 'guest') = 'guest'
  ORDER BY i.id DESC
  LIMIT 1
),
new_inv AS (
  INSERT INTO invitations (
    invitation_code, owner_id, property_id, unit_id, invited_by_user_id,
    guest_name, guest_email,
    stay_start_date, stay_end_date,
    purpose_of_stay, relationship_to_owner, region_code,
    status, token_state, invitation_kind,
    dead_mans_switch_enabled, dead_mans_switch_alert_email, dead_mans_switch_alert_sms,
    dead_mans_switch_alert_dashboard, dead_mans_switch_alert_phone
  )
  SELECT
    'INV-LIVEVERIFY-' || upper(substr(md5(random()::text), 1, 8)),
    tmpl.owner_id, tmpl.property_id, tmpl.unit_id, tmpl.invited_by_user_id,
    'Live verify guest 2', 'live-verify-2@example.invalid',
    CURRENT_DATE, CURRENT_DATE + 14,
    tmpl.purpose_of_stay, tmpl.relationship_to_owner, tmpl.region_code,
    'accepted', 'BURNED', 'guest',
    COALESCE(tmpl.dead_mans_switch_enabled, 0),
    COALESCE(tmpl.dead_mans_switch_alert_email, 1),
    COALESCE(tmpl.dead_mans_switch_alert_sms, 0),
    COALESCE(tmpl.dead_mans_switch_alert_dashboard, 1),
    COALESCE(tmpl.dead_mans_switch_alert_phone, 0)
  FROM tmpl
  RETURNING *
),
ins_stay AS (
  INSERT INTO stays (
    guest_id, owner_id, property_id, unit_id, invitation_id, invited_by_user_id,
    stay_start_date, stay_end_date, intended_stay_duration_days,
    purpose_of_stay, relationship_to_owner, region_code,
    checked_in_at,
    dead_mans_switch_enabled, dead_mans_switch_alert_email, dead_mans_switch_alert_sms,
    dead_mans_switch_alert_dashboard, dead_mans_switch_alert_phone
  )
  SELECT
    30::integer,
    new_inv.owner_id, new_inv.property_id, new_inv.unit_id, new_inv.id, new_inv.invited_by_user_id,
    new_inv.stay_start_date, new_inv.stay_end_date,
    GREATEST((new_inv.stay_end_date - new_inv.stay_start_date), 1),
    new_inv.purpose_of_stay, new_inv.relationship_to_owner, new_inv.region_code,
    NOW(),
    0, 1, 0, 1, 0
  FROM new_inv
  RETURNING id
),
ins_sig AS (
  INSERT INTO agreement_signatures (
    invitation_code,
    region_code,
    guest_email,
    guest_full_name,
    typed_signature,
    signature_method,
    acks_read,
    acks_temporary,
    acks_vacate,
    acks_electronic,
    document_id,
    document_title,
    document_hash,
    document_content,
    signed_at,
    used_by_user_id,
    used_at,
    signed_pdf_bytes
  )
  SELECT
    new_inv.invitation_code,
    new_inv.region_code::text,
    new_inv.guest_email,
    COALESCE(new_inv.guest_name, 'Guest'),
    'Test Signer',
    'typed',
    true,
    true,
    true,
    true,
    'doc-live-verify',
    'Guest agreement (live verify test)',
    'liveverify001',
    '<p>Dummy agreement body for live page PDF test.</p>',
    NOW(),
    30::integer,
    NOW(),
    convert_to(
      '%PDF-1.1' || chr(10) ||
      '1 0 obj<<>>endobj' || chr(10) ||
      'trailer<</Root 1 0 R>>' || chr(10) ||
      '%%EOF' || chr(10),
      'UTF8'
    )
  FROM new_inv
  RETURNING id
)
SELECT
  new_inv.invitation_code,
  ins_stay.id AS stay_id,
  ins_sig.id AS agreement_signature_id
FROM new_inv
CROSS JOIN ins_stay
CROSS JOIN ins_sig;

COMMIT;
