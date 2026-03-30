-- ============================================================
-- DocuStay Supabase Migration v2 — FIXED for actual DB schema
-- Purpose: Complete and verify the Legal Logic Layer
-- Date: 2026-03-23 (updated)
--
-- Your actual tables are:
--   jurisdictions          (region_code PK-like unique, state_code, name, jurisdiction_group, section_3_clause, ...)
--   jurisdiction_statutes  (region_code, citation, plain_english, ...)
--   guest_templates        (new table — created here)
--
-- This migration does five things:
--   1. Adds section_3_clause column to jurisdictions (if missing)
--   2. UPSERTS all 50 states into the jurisdictions table
--      (including section_3_clause for guest acknowledgment docs)
--   3. UPSERTS statute citations into jurisdiction_statutes
--   4. Creates and populates the guest_templates table
--   5. Adds missing zip code mappings
--
-- HOW TO RUN:
--   Paste this entire file into the Supabase SQL Editor and click "Run".
-- ============================================================


-- ============================================================
-- PART 0: ADD section_3_clause COLUMN IF MISSING
-- ============================================================

ALTER TABLE jurisdictions ADD COLUMN IF NOT EXISTS section_3_clause TEXT;


-- ============================================================
-- PART 1: UPSERT ALL 50 STATES INTO jurisdictions TABLE
-- Uses region_code as the unique conflict key.
-- Now includes section_3_clause for each state.
-- ============================================================

-- Group A: 14-day common-law states
INSERT INTO jurisdictions (region_code, state_code, name, jurisdiction_group, legal_threshold_days, platform_renewal_cycle_days, reminder_days_before, max_stay_days, tenancy_threshold_days, warning_days, agreement_type, section_3_clause, stay_classification_label, risk_level, allow_extended_if_owner_occupied)
VALUES
  ('CA', 'CA', 'California', 'A', 14, 13, 3, 13, 14, 3, 'TRANSIENT_LODGER',
   '**3. Acknowledgment of Transient Occupancy (California):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under California Civil Code Sections 1940.1 and 1946.5, a guest who stays more than 14 consecutive days or more than 14 days in any 6-month period may acquire tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', true),

  ('CO', 'CO', 'Colorado', 'A', 14, 13, 3, 13, 14, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Colorado):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Colorado Revised Statutes Section 38-12-301 and applicable common law, a continuous stay of 14 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('CT', 'CT', 'Connecticut', 'A', 14, 13, 3, 13, 14, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Connecticut):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Connecticut General Statutes Section 47a-1 and applicable common law, a continuous stay of 14 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('FL', 'FL', 'Florida', 'A', 14, 13, 3, 13, 14, 3, 'HB621_DECLARATION',
   '**3. Acknowledgment of Status under Florida Law:** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Florida Statute Section 82.036 (HB 621) and applicable common law, a guest who stays more than 14 consecutive days or more than 14 days in any 6-month period may acquire tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('ME', 'ME', 'Maine', 'A', 14, 13, 3, 13, 14, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Maine):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Maine common law and applicable common law, a continuous stay of 14 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('MO', 'MO', 'Missouri', 'A', 14, 13, 3, 13, 14, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Missouri):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Missouri common law and applicable common law, a continuous stay of 14 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('NC', 'NC', 'North Carolina', 'A', 14, 13, 3, 13, 14, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (North Carolina):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under North Carolina common law and applicable common law, a continuous stay of 14 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false)

ON CONFLICT (region_code) DO UPDATE SET
  jurisdiction_group = EXCLUDED.jurisdiction_group,
  legal_threshold_days = EXCLUDED.legal_threshold_days,
  platform_renewal_cycle_days = EXCLUDED.platform_renewal_cycle_days,
  reminder_days_before = EXCLUDED.reminder_days_before,
  max_stay_days = EXCLUDED.max_stay_days,
  tenancy_threshold_days = EXCLUDED.tenancy_threshold_days,
  warning_days = EXCLUDED.warning_days,
  section_3_clause = EXCLUDED.section_3_clause;


-- Group B: 30-day states
INSERT INTO jurisdictions (region_code, state_code, name, jurisdiction_group, legal_threshold_days, platform_renewal_cycle_days, reminder_days_before, max_stay_days, tenancy_threshold_days, warning_days, agreement_type, section_3_clause, stay_classification_label, risk_level, allow_extended_if_owner_occupied)
VALUES
  ('AL', 'AL', 'Alabama', 'B', 30, 29, 5, 29, 30, 5, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Alabama):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under the Code of Alabama Section 35-9A-141 and applicable common law, a continuous stay of 30 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'high', false),

  ('IN', 'IN', 'Indiana', 'B', 30, 29, 5, 29, 30, 5, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Indiana):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Indiana Code IC 32-31-1-1 and applicable common law, a continuous stay of 30 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'high', false),

  ('KS', 'KS', 'Kansas', 'B', 30, 29, 5, 29, 30, 5, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Kansas):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under K.S.A. Section 58-2540 and applicable common law, a continuous stay of 30 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'high', false),

  ('KY', 'KY', 'Kentucky', 'B', 30, 29, 5, 29, 30, 5, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Kentucky):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under KRS Section 383.010 and applicable common law, a continuous stay of 30 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'high', false),

  ('NY', 'NY', 'New York', 'B', 30, 29, 5, 29, 30, 5, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Occupancy Limits (New York):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under New York Real Property Actions and Proceedings Law (RPAPL) Section 711, a continuous stay of 30 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'high', false),

  ('OH', 'OH', 'Ohio', 'B', 30, 29, 5, 29, 30, 5, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Ohio):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Ohio Revised Code Section 5321.01 and applicable common law, a continuous stay of 30 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'high', false),

  ('PA', 'PA', 'Pennsylvania', 'B', 30, 29, 5, 29, 30, 5, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Pennsylvania):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under 68 P.S. Section 250.1 and applicable common law, a continuous stay of 30 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'high', false)

ON CONFLICT (region_code) DO UPDATE SET
  jurisdiction_group = EXCLUDED.jurisdiction_group,
  legal_threshold_days = EXCLUDED.legal_threshold_days,
  platform_renewal_cycle_days = EXCLUDED.platform_renewal_cycle_days,
  reminder_days_before = EXCLUDED.reminder_days_before,
  max_stay_days = EXCLUDED.max_stay_days,
  tenancy_threshold_days = EXCLUDED.tenancy_threshold_days,
  warning_days = EXCLUDED.warning_days,
  section_3_clause = EXCLUDED.section_3_clause;


-- Group C: Lease-defined states (14-day platform default)
INSERT INTO jurisdictions (region_code, state_code, name, jurisdiction_group, legal_threshold_days, platform_renewal_cycle_days, reminder_days_before, max_stay_days, tenancy_threshold_days, warning_days, agreement_type, section_3_clause, stay_classification_label, risk_level, allow_extended_if_owner_occupied)
VALUES
  ('AK', 'AK', 'Alaska', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Alaska):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Alaska, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('AR', 'AR', 'Arkansas', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Arkansas):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Arkansas, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('DE', 'DE', 'Delaware', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Delaware):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Delaware, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('HI', 'HI', 'Hawaii', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Hawaii):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Hawaii, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('ID', 'ID', 'Idaho', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Idaho):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Idaho, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('IA', 'IA', 'Iowa', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Iowa):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Iowa, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('LA', 'LA', 'Louisiana', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Louisiana):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Louisiana, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('MA', 'MA', 'Massachusetts', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Massachusetts):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Massachusetts, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('MI', 'MI', 'Michigan', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Michigan):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Michigan, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('NE', 'NE', 'Nebraska', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Nebraska):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Nebraska, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('NV', 'NV', 'Nevada', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Nevada):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Nevada, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('NH', 'NH', 'New Hampshire', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (New Hampshire):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in New Hampshire, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('NJ', 'NJ', 'New Jersey', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (New Jersey):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in New Jersey, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('NM', 'NM', 'New Mexico', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (New Mexico):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in New Mexico, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('ND', 'ND', 'North Dakota', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (North Dakota):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in North Dakota, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('OK', 'OK', 'Oklahoma', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Oklahoma):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Oklahoma, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('OR', 'OR', 'Oregon', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Oregon):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest under a Temporary Occupancy Agreement as defined by Oregon Revised Statutes Section 90.275. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager, which would constitute a new Temporary Occupancy Agreement under ORS 90.275.',
   'guest', 'medium', false),

  ('RI', 'RI', 'Rhode Island', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Rhode Island):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Rhode Island, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('SC', 'SC', 'South Carolina', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (South Carolina):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in South Carolina, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('SD', 'SD', 'South Dakota', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (South Dakota):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in South Dakota, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('UT', 'UT', 'Utah', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Utah):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Utah, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('VT', 'VT', 'Vermont', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Vermont):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Vermont, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('VA', 'VA', 'Virginia', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Virginia):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Virginia, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('WA', 'WA', 'Washington', 'C', NULL, 14, 3, 14, NULL, 3, 'ANTI_SQUATTER_DECLARATION',
   '**3. Acknowledgment of Guest Status (Washington):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Washington Revised Code Section 9A.52.105, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('WV', 'WV', 'West Virginia', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (West Virginia):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in West Virginia, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('WI', 'WI', 'Wisconsin', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Wisconsin):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Wisconsin, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('WY', 'WY', 'Wyoming', 'C', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Wyoming):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Wyoming, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false)

ON CONFLICT (region_code) DO UPDATE SET
  jurisdiction_group = EXCLUDED.jurisdiction_group,
  legal_threshold_days = EXCLUDED.legal_threshold_days,
  platform_renewal_cycle_days = EXCLUDED.platform_renewal_cycle_days,
  reminder_days_before = EXCLUDED.reminder_days_before,
  max_stay_days = EXCLUDED.max_stay_days,
  tenancy_threshold_days = EXCLUDED.tenancy_threshold_days,
  warning_days = EXCLUDED.warning_days,
  section_3_clause = EXCLUDED.section_3_clause;


-- Group D: Behavior-based states
INSERT INTO jurisdictions (region_code, state_code, name, jurisdiction_group, legal_threshold_days, platform_renewal_cycle_days, reminder_days_before, max_stay_days, tenancy_threshold_days, warning_days, agreement_type, section_3_clause, stay_classification_label, risk_level, allow_extended_if_owner_occupied)
VALUES
  ('GA', 'GA', 'Georgia', 'D', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Georgia):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Georgia law (O.C.G.A. Section 44-7-1), tenancy is determined by behavior rather than a fixed number of days. Actions such as contributing to rent or utilities, receiving mail at the Property, or possessing a key without the owner present may trigger tenant rights. This acknowledgment serves as a clear record of your temporary, non-tenant status. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('IL', 'IL', 'Illinois', 'D', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Illinois):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Illinois law (765 ILCS 705/1), tenancy is determined by behavior rather than a fixed number of days. Actions such as contributing to rent or utilities, receiving mail at the Property, or possessing a key without the owner present may trigger tenant rights. This acknowledgment serves as a clear record of your temporary, non-tenant status. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('MD', 'MD', 'Maryland', 'D', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Maryland):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Maryland Real Property Section 8-101, tenancy is determined by behavior rather than a fixed number of days. Actions such as contributing to rent or utilities, receiving mail at the Property, or possessing a key without the owner present may trigger tenant rights. This acknowledgment serves as a clear record of your temporary, non-tenant status. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('MN', 'MN', 'Minnesota', 'D', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Minnesota):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Minnesota Statutes Section 504B.001, tenancy is determined by behavior rather than a fixed number of days. Actions such as contributing to rent or utilities, receiving mail at the Property, or possessing a key without the owner present may trigger tenant rights. This acknowledgment serves as a clear record of your temporary, non-tenant status. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('MS', 'MS', 'Mississippi', 'D', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Mississippi):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Mississippi Code Section 89-7-1, tenancy is determined by behavior rather than a fixed number of days. Actions such as contributing to rent or utilities, receiving mail at the Property, or possessing a key without the owner present may trigger tenant rights. This acknowledgment serves as a clear record of your temporary, non-tenant status. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('TN', 'TN', 'Tennessee', 'D', NULL, 14, 3, 14, NULL, 3, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Tennessee):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Tennessee Code Section 66-28-102, tenancy is determined by behavior rather than a fixed number of days. Actions such as contributing to rent or utilities, receiving mail at the Property, or possessing a key without the owner present may trigger tenant rights. This acknowledgment serves as a clear record of your temporary, non-tenant status. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('TX', 'TX', 'Texas', 'D', NULL, 14, 3, 14, NULL, 3, 'TRANSIENT_GUEST',
   '**3. Acknowledgment of Guest Status (Texas):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Texas Property Code Section 92.001 and Penal Code Section 30.05, tenancy is determined by behavior rather than a fixed number of days. Actions such as contributing to rent or utilities, receiving mail at the Property, or possessing a key without the owner present may trigger tenant rights. This acknowledgment serves as a clear record of your temporary, non-tenant status. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false)

ON CONFLICT (region_code) DO UPDATE SET
  jurisdiction_group = EXCLUDED.jurisdiction_group,
  legal_threshold_days = EXCLUDED.legal_threshold_days,
  platform_renewal_cycle_days = EXCLUDED.platform_renewal_cycle_days,
  reminder_days_before = EXCLUDED.reminder_days_before,
  max_stay_days = EXCLUDED.max_stay_days,
  tenancy_threshold_days = EXCLUDED.tenancy_threshold_days,
  warning_days = EXCLUDED.warning_days,
  section_3_clause = EXCLUDED.section_3_clause;


-- Group E: Unique statutory states
INSERT INTO jurisdictions (region_code, state_code, name, jurisdiction_group, legal_threshold_days, platform_renewal_cycle_days, reminder_days_before, max_stay_days, tenancy_threshold_days, warning_days, agreement_type, section_3_clause, stay_classification_label, risk_level, allow_extended_if_owner_occupied)
VALUES
  ('AZ', 'AZ', 'Arizona', 'E', 29, 28, 5, 28, 29, 5, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Arizona):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Arizona Revised Statutes Section 33-14 and the Arizona Department of Revenue short-term lodging regulations, a stay of 29 days or more may trigger transient lodging tax obligations and tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'medium', false),

  ('MT', 'MT', 'Montana', 'E', 7, 7, 2, 7, 7, 2, 'REVOCABLE_LICENSE',
   '**3. Acknowledgment of Guest Status (Montana):** By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Montana Code Section 70-24-103, a continuous stay of 7 days or more without a written agreement may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   'guest', 'high', false)

ON CONFLICT (region_code) DO UPDATE SET
  jurisdiction_group = EXCLUDED.jurisdiction_group,
  legal_threshold_days = EXCLUDED.legal_threshold_days,
  platform_renewal_cycle_days = EXCLUDED.platform_renewal_cycle_days,
  reminder_days_before = EXCLUDED.reminder_days_before,
  max_stay_days = EXCLUDED.max_stay_days,
  tenancy_threshold_days = EXCLUDED.tenancy_threshold_days,
  warning_days = EXCLUDED.warning_days,
  section_3_clause = EXCLUDED.section_3_clause;


-- ============================================================
-- PART 2: UPSERT STATUTE CITATIONS INTO jurisdiction_statutes
-- Adds citations for states that are currently missing.
-- Existing citations are preserved. Only inserts if
-- region_code+citation combo is new.
-- ============================================================

-- Group A statutes
INSERT INTO jurisdiction_statutes (region_code, citation, plain_english, use_in_authority_package, sort_order)
SELECT v.region_code, v.citation, v.plain_english, true, 0
FROM (VALUES
  ('CA', 'CA Civil Code § 1940.1, AB 1482',   'Transient occupancy; common-law tenancy may form around 14 days.'),
  ('CA', 'CA Civil Code § 1946.5',             'Single lodger; owner-occupied; removal as trespasser after notice.'),
  ('CO', 'C.R.S. § 38-12-101',                'Common-law tenancy principles; no fixed statutory threshold.'),
  ('CT', 'C.G.S. § 47a-1',                    'Tenancy implied from occupancy; common-law 14-day doctrine.'),
  ('FL', 'FL Statute § 82.036 (HB 621)',       'Sheriff may remove unauthorized person with signed affidavit; no lease.'),
  ('ME', 'Maine Common Law (14-Day)',          'Common-law tenancy may form after 14 days of continuous occupancy.'),
  ('MO', 'Missouri Common Law (14-Day)',       'Common-law tenancy may form after 14 days of continuous occupancy.'),
  ('NC', 'North Carolina Common Law (14-Day)', 'Common-law tenancy may form after 14 days of continuous occupancy.')
) AS v(region_code, citation, plain_english)
WHERE NOT EXISTS (
  SELECT 1 FROM jurisdiction_statutes js
  WHERE js.region_code = v.region_code AND js.citation = v.citation
);

-- Group B statutes
INSERT INTO jurisdiction_statutes (region_code, citation, plain_english, use_in_authority_package, sort_order)
SELECT v.region_code, v.citation, v.plain_english, true, 0
FROM (VALUES
  ('AL', 'Code of Alabama § 35-9A-141',  'Tenancy after 30 days of continuous occupancy.'),
  ('IN', 'IC 32-31-1-1',                 '30-day threshold for tenant protections.'),
  ('KS', 'K.S.A. § 58-2540',            '30-day continuous occupancy creates tenancy.'),
  ('KY', 'KRS § 383.010',               '30-day tenancy threshold.'),
  ('NY', 'RPAPL § 711',                  'Occupying a dwelling for 30+ consecutive days creates tenancy rights.'),
  ('OH', 'ORC § 5321.01',               'Tenant rights attach after 30 days.'),
  ('PA', '68 P.S. § 250.102',           'Occupant becomes tenant after 30 continuous days.')
) AS v(region_code, citation, plain_english)
WHERE NOT EXISTS (
  SELECT 1 FROM jurisdiction_statutes js
  WHERE js.region_code = v.region_code AND js.citation = v.citation
);

-- Group C statutes (lease-defined states)
INSERT INTO jurisdiction_statutes (region_code, citation, plain_english, use_in_authority_package, sort_order)
SELECT v.region_code, v.citation, v.plain_english, true, 0
FROM (VALUES
  ('AK', 'Alaska Lease-Defined Occupancy',          'Occupancy defined by agreement between parties; no fixed statutory day count.'),
  ('AR', 'Arkansas Lease-Defined Occupancy',         'Occupancy defined by agreement between parties.'),
  ('DE', 'Delaware Lease-Defined Occupancy',         'Occupancy defined by agreement between parties.'),
  ('HI', 'Hawaii Lease-Defined Occupancy',           'Occupancy defined by agreement between parties.'),
  ('ID', 'Idaho Lease-Defined Occupancy',            'Occupancy defined by agreement between parties.'),
  ('IA', 'Iowa Lease-Defined Occupancy',             'Occupancy defined by agreement between parties.'),
  ('LA', 'Louisiana Lease-Defined Occupancy',        'Occupancy defined by agreement between parties.'),
  ('MA', 'Massachusetts Lease-Defined Occupancy',    'Occupancy defined by agreement between parties.'),
  ('MI', 'Michigan Lease-Defined Occupancy',         'Occupancy defined by agreement between parties.'),
  ('NE', 'Nebraska Lease-Defined Occupancy',         'Occupancy defined by agreement between parties.'),
  ('NV', 'Nevada Lease-Defined Occupancy',           'Occupancy defined by agreement between parties.'),
  ('NH', 'New Hampshire Lease-Defined Occupancy',    'Occupancy defined by agreement between parties.'),
  ('NJ', 'New Jersey Lease-Defined Occupancy',       'Occupancy defined by agreement between parties.'),
  ('NM', 'New Mexico Lease-Defined Occupancy',       'Occupancy defined by agreement between parties.'),
  ('ND', 'North Dakota Lease-Defined Occupancy',     'Occupancy defined by agreement between parties.'),
  ('OK', 'Oklahoma Lease-Defined Occupancy',         'Occupancy defined by agreement between parties.'),
  ('OR', 'Oregon ORS 90.275',                        'Temporary Occupancy Agreement statute; occupancy defined by agreement.'),
  ('RI', 'Rhode Island Lease-Defined Occupancy',     'Occupancy defined by agreement between parties.'),
  ('SC', 'South Carolina Lease-Defined Occupancy',   'Occupancy defined by agreement between parties.'),
  ('SD', 'South Dakota Lease-Defined Occupancy',     'Occupancy defined by agreement between parties.'),
  ('UT', 'Utah Lease-Defined Occupancy',             'Occupancy defined by agreement between parties.'),
  ('VT', 'Vermont Lease-Defined Occupancy',          'Occupancy defined by agreement between parties.'),
  ('VA', 'Virginia Lease-Defined Occupancy',         'Occupancy defined by agreement between parties.'),
  ('WA', 'RCW 9A.52.105',                           'Tenancy is fact-specific; owner declaration can assist police removal.'),
  ('WV', 'West Virginia Lease-Defined Occupancy',   'Occupancy defined by agreement between parties.'),
  ('WI', 'Wisconsin Lease-Defined Occupancy',        'Occupancy defined by agreement between parties.'),
  ('WY', 'Wyoming Lease-Defined Occupancy',          'Occupancy defined by agreement between parties.')
) AS v(region_code, citation, plain_english)
WHERE NOT EXISTS (
  SELECT 1 FROM jurisdiction_statutes js
  WHERE js.region_code = v.region_code AND js.citation = v.citation
);

-- Group D statutes (behavior-based states)
INSERT INTO jurisdiction_statutes (region_code, citation, plain_english, use_in_authority_package, sort_order)
SELECT v.region_code, v.citation, v.plain_english, true, 0
FROM (VALUES
  ('GA', 'O.C.G.A. § 44-7-1',                                  'Tenancy determined by behavior and intent, not duration alone.'),
  ('IL', '765 ILCS 705/0.01',                                   'Behavior-based; intent and conduct determine tenancy.'),
  ('MD', 'MD Real Prop. § 8-101',                               'Behavior-based tenancy determination.'),
  ('MN', 'Minn. Stat. § 504B.001',                              'Tenancy from conduct and circumstances.'),
  ('MS', 'Miss. Code § 89-7-1',                                 'Behavior-based tenancy.'),
  ('TN', 'Tenn. Code § 66-28-102',                              'Tenancy determined by behavior.'),
  ('TX', 'Texas Property Code § 92.001, Penal Code § 30.05',    'Transient housing exempt from landlord-tenant; criminal trespass after notice.')
) AS v(region_code, citation, plain_english)
WHERE NOT EXISTS (
  SELECT 1 FROM jurisdiction_statutes js
  WHERE js.region_code = v.region_code AND js.citation = v.citation
);

-- Group E statutes (unique states)
INSERT INTO jurisdiction_statutes (region_code, citation, plain_english, use_in_authority_package, sort_order)
SELECT v.region_code, v.citation, v.plain_english, true, 0
FROM (VALUES
  ('AZ', 'A.R.S. § 33-1413',          'Guest occupancy for 29+ days may create tenant rights.'),
  ('MT', 'Montana Code § 70-24-103',   'Tenant at will after 7 days of occupancy.')
) AS v(region_code, citation, plain_english)
WHERE NOT EXISTS (
  SELECT 1 FROM jurisdiction_statutes js
  WHERE js.region_code = v.region_code AND js.citation = v.citation
);


-- ============================================================
-- PART 3: CREATE AND POPULATE guest_templates TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS guest_templates (
  id              SERIAL PRIMARY KEY,
  section_key     VARCHAR(50) UNIQUE NOT NULL,
  section_title   VARCHAR(200) NOT NULL,
  section_content TEXT NOT NULL,
  created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO guest_templates (section_key, section_title, section_content)
VALUES
  ('section_1', 'Parties and Property',
   'This Guest Acknowledgment and Temporary Occupancy Agreement ("Agreement") is entered into as of the date indicated below, between the Property Owner or Authorized Manager ("Host") and the individual identified below ("Guest"). The Property subject to this Agreement is identified by its registered address on the DocuStay platform. This Agreement is issued by DOCUSTAY LLC, a Washington State limited liability company.'),

  ('section_2', 'Nature of Stay and Authorization',
   'The Guest acknowledges that they have been granted a limited, revocable license to temporarily occupy the Property for the specific period defined in this Agreement ("Stay Period"). This Agreement does not create a landlord-tenant relationship, a lease, or any other tenancy interest. The Guest''s right to occupy the Property is strictly limited to the Stay Period and is subject to the terms herein.'),

  ('section_4', 'Guest Obligations',
   'During the Stay Period, the Guest agrees to: (a) comply with all applicable laws and regulations; (b) not disturb neighbors or other occupants; (c) not sublicense, sublet, or transfer any rights under this Agreement to any third party; (d) not make any alterations to the Property; and (e) vacate the Property promptly upon expiration of the Stay Period unless a new written authorization has been issued by the Host.'),

  ('section_5', 'Renewal and Expiration',
   'This Agreement expires automatically at the end of the Stay Period. Continued occupancy beyond the Stay Period without a new written authorization from the Host may constitute trespass and/or the establishment of unlawful tenancy. The Guest will receive reminder notifications prior to expiration via the DocuStay platform. Renewal requires a new acknowledgment from both parties through the platform.'),

  ('section_6', 'Disclaimer and Limitation of Liability',
   'DOCUSTAY LLC provides this platform as a documentation tool only. DOCUSTAY LLC is not a party to this Agreement and does not provide legal advice. The enforceability of this Agreement is subject to the laws of the jurisdiction where the Property is located. The Host and Guest are solely responsible for ensuring their arrangement complies with all applicable local, state, and federal laws. This Agreement is intended to document intent and provide evidentiary support; it does not guarantee any specific legal outcome.')

ON CONFLICT (section_key) DO UPDATE SET
  section_title = EXCLUDED.section_title,
  section_content = EXCLUDED.section_content,
  updated_at = NOW();


-- ============================================================
-- PART 4: ADD ZIP MAPPINGS FOR STATES THAT ARE MISSING
-- (Only adds if the zip is not already mapped)
-- ============================================================

INSERT INTO jurisdiction_zip_mappings (zip_code, region_code)
SELECT v.zip_code, v.region_code
FROM (VALUES
  -- Group C states (most were missing zip mappings)
  ('99501', 'AK'), ('72201', 'AR'), ('19901', 'DE'), ('96801', 'HI'),
  ('83701', 'ID'), ('50301', 'IA'), ('70112', 'LA'), ('02101', 'MA'),
  ('48201', 'MI'), ('68101', 'NE'), ('89101', 'NV'), ('03101', 'NH'),
  ('07101', 'NJ'), ('87101', 'NM'), ('58501', 'ND'), ('73101', 'OK'),
  ('97201', 'OR'), ('02901', 'RI'), ('29201', 'SC'), ('57501', 'SD'),
  ('84101', 'UT'), ('05601', 'VT'), ('23218', 'VA'), ('25301', 'WV'),
  ('53201', 'WI'), ('82001', 'WY')
) AS v(zip_code, region_code)
WHERE NOT EXISTS (
  SELECT 1 FROM jurisdiction_zip_mappings jzm
  WHERE jzm.zip_code = v.zip_code
);


-- ============================================================
-- VERIFICATION QUERIES (run automatically after migration)
-- ============================================================

-- Total state count (should be 50):
SELECT COUNT(*) AS total_states FROM jurisdictions;

-- Group distribution (should show A=7, B=7, C=27, D=7, E=2):
SELECT jurisdiction_group, COUNT(*) AS count
FROM jurisdictions
GROUP BY jurisdiction_group
ORDER BY jurisdiction_group;

-- States missing section_3_clause (should return 0 rows):
SELECT region_code, name FROM jurisdictions WHERE section_3_clause IS NULL;

-- Statute coverage (should show 0 rows = all states have at least 1 statute):
SELECT j.region_code, j.name, COUNT(js.id) AS statute_count
FROM jurisdictions j
LEFT JOIN jurisdiction_statutes js ON js.region_code = j.region_code
GROUP BY j.region_code, j.name
HAVING COUNT(js.id) = 0
ORDER BY j.region_code;

-- Template sections (should return 5 rows):
SELECT section_key, section_title FROM guest_templates ORDER BY id;

-- Full state audit with section_3_clause status:
SELECT region_code, name, jurisdiction_group, legal_threshold_days,
       platform_renewal_cycle_days,
       CASE WHEN section_3_clause IS NOT NULL THEN 'YES' ELSE 'NO' END AS has_section_3
FROM jurisdictions
ORDER BY region_code;

-- ============================================================
-- Part 6: bulk_upload_jobs — add progress tracking columns
-- ============================================================
ALTER TABLE bulk_upload_jobs ADD COLUMN IF NOT EXISTS total_rows INTEGER NOT NULL DEFAULT 0;
ALTER TABLE bulk_upload_jobs ADD COLUMN IF NOT EXISTS processed_rows INTEGER NOT NULL DEFAULT 0;
