-- ============================================================
-- DocuStay Supabase Migration v2 (Full UPSERT — All 50 States)
-- Purpose: Complete and verify the Legal Logic Layer
-- Prepared by: Manus AI for DOCUSTAY LLC
-- Date: 2026-03-21
--
-- This migration does three things:
--   1. UPSERTS all 50 states into jurisdiction_statutes —
--      existing rows are overwritten with verified data,
--      missing rows are inserted. Nothing is skipped.
--   2. Adds a group_classification column and populates
--      all 50 states with their Group A-E classification.
--   3. Creates and populates a guest_templates table with
--      the 5 universal master template sections.
--
-- HOW TO RUN:
--   Paste this entire file into the Supabase SQL Editor at:
--   supabase.com/dashboard/project/fdjefirdrajkynitmikx/editor
--   Then click "Run".
-- ============================================================


-- ============================================================
-- PART 1: UPSERT ALL 50 STATES INTO jurisdiction_statutes
-- ON CONFLICT DO UPDATE ensures existing rows are overwritten.
-- ============================================================

-- ---- GROUP B: 30-Day Rule States ----

INSERT INTO jurisdiction_statutes (state_code, statute_title, section_3_clause, legal_threshold_days, threshold_rule, platform_renewal_cycle, reminder_day_1, reminder_day_2)
VALUES
  ('AL', 'Code of Alabama Section 35-9A-141',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under the Code of Alabama Section 35-9A-141 and applicable common law, a continuous stay of 30 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   30, 'Common Law', 28, 26, 27),

  ('IN', 'IC 32-31-1-1',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Indiana Code IC 32-31-1-1 and applicable common law, a continuous stay of 30 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   30, 'Common Law', 28, 26, 27),

  ('KS', 'K.S.A. Section 58-2540',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under K.S.A. Section 58-2540 and applicable common law, a continuous stay of 30 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   30, 'Common Law', 28, 26, 27),

  ('KY', 'KRS Section 383.010',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under KRS Section 383.010 and applicable common law, a continuous stay of 30 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   30, 'Common Law', 28, 26, 27),

  ('NY', 'RPAPL Section 711',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under New York Real Property Actions and Proceedings Law (RPAPL) Section 711, a continuous stay of 30 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   30, 'Statutory', 28, 26, 27),

  ('OH', 'ORC Section 5321.01',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Ohio Revised Code Section 5321.01 and applicable common law, a continuous stay of 30 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   30, 'Common Law', 28, 26, 27),

  ('PA', '68 P.S. Section 250.1',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under 68 P.S. Section 250.1 and applicable common law, a continuous stay of 30 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   30, 'Common Law', 28, 26, 27)

ON CONFLICT (state_code) DO UPDATE SET
  statute_title = EXCLUDED.statute_title,
  section_3_clause = EXCLUDED.section_3_clause,
  legal_threshold_days = EXCLUDED.legal_threshold_days,
  threshold_rule = EXCLUDED.threshold_rule,
  platform_renewal_cycle = EXCLUDED.platform_renewal_cycle,
  reminder_day_1 = EXCLUDED.reminder_day_1,
  reminder_day_2 = EXCLUDED.reminder_day_2;


-- ---- GROUP A: 14-Day Common Law States ----

INSERT INTO jurisdiction_statutes (state_code, statute_title, section_3_clause, legal_threshold_days, threshold_rule, platform_renewal_cycle, reminder_day_1, reminder_day_2)
VALUES
  ('CA', 'CA Civil Code Section 1940.1 / Section 1946.5',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under California Civil Code Sections 1940.1 and 1946.5, a guest who stays more than 14 consecutive days or more than 14 days in any 6-month period may acquire tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   14, 'Common Law', 14, 12, 13),

  ('CO', 'C.R.S. Section 38-12-301',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Colorado Revised Statutes Section 38-12-301 and applicable common law, a continuous stay of 14 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   14, 'Common Law', 14, 12, 13),

  ('CT', 'C.G.S. Section 47a-1',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Connecticut General Statutes Section 47a-1 and applicable common law, a continuous stay of 14 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   14, 'Common Law', 14, 12, 13),

  ('FL', 'FL Statute Section 82.036 (HB 621)',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Florida Statute Section 82.036 (HB 621) and applicable common law, a guest who stays more than 14 consecutive days or more than 14 days in any 6-month period may acquire tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   14, 'Common Law', 14, 12, 13),

  ('ME', 'Maine Common Law (14-Day Threshold)',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Maine common law, a continuous stay of 14 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   14, 'Common Law', 14, 12, 13),

  ('MO', 'Missouri Common Law (14-Day Threshold)',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Missouri common law, a continuous stay of 14 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   14, 'Common Law', 14, 12, 13),

  ('NC', 'North Carolina Common Law (14-Day Threshold)',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under North Carolina common law, a continuous stay of 14 days or more may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   14, 'Common Law', 14, 12, 13)

ON CONFLICT (state_code) DO UPDATE SET
  statute_title = EXCLUDED.statute_title,
  section_3_clause = EXCLUDED.section_3_clause,
  legal_threshold_days = EXCLUDED.legal_threshold_days,
  threshold_rule = EXCLUDED.threshold_rule,
  platform_renewal_cycle = EXCLUDED.platform_renewal_cycle,
  reminder_day_1 = EXCLUDED.reminder_day_1,
  reminder_day_2 = EXCLUDED.reminder_day_2;


-- ---- GROUP D: Behavior-Based States ----

INSERT INTO jurisdiction_statutes (state_code, statute_title, section_3_clause, legal_threshold_days, threshold_rule, platform_renewal_cycle, reminder_day_1, reminder_day_2)
VALUES
  ('GA', 'O.C.G.A. Section 44-7-1',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Georgia law (O.C.G.A. Section 44-7-1), tenancy is determined by behavior rather than a fixed number of days. Actions such as contributing to rent or utilities, receiving mail at the Property, or possessing a key without the owner present may trigger tenant rights. This acknowledgment serves as a clear record of your temporary, non-tenant status. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Behavior-Based', 14, 12, 13),

  ('IL', '765 ILCS 705/1',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Illinois law (765 ILCS 705/1), tenancy is determined by behavior rather than a fixed number of days. Actions such as contributing to rent or utilities, receiving mail at the Property, or possessing a key without the owner present may trigger tenant rights. This acknowledgment serves as a clear record of your temporary, non-tenant status. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Behavior-Based', 14, 12, 13),

  ('MD', 'MD Real Prop Section 8-101',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Maryland Real Property Section 8-101, tenancy is determined by behavior rather than a fixed number of days. Actions such as contributing to rent or utilities, receiving mail at the Property, or possessing a key without the owner present may trigger tenant rights. This acknowledgment serves as a clear record of your temporary, non-tenant status. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Behavior-Based', 14, 12, 13),

  ('MN', 'Minn. Stat. Section 504B.001',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Minnesota Statutes Section 504B.001, tenancy is determined by behavior rather than a fixed number of days. Actions such as contributing to rent or utilities, receiving mail at the Property, or possessing a key without the owner present may trigger tenant rights. This acknowledgment serves as a clear record of your temporary, non-tenant status. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Behavior-Based', 14, 12, 13),

  ('MS', 'Miss. Code Section 89-7-1',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Mississippi Code Section 89-7-1, tenancy is determined by behavior rather than a fixed number of days. Actions such as contributing to rent or utilities, receiving mail at the Property, or possessing a key without the owner present may trigger tenant rights. This acknowledgment serves as a clear record of your temporary, non-tenant status. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Behavior-Based', 14, 12, 13),

  ('TN', 'Tenn. Code Section 66-28-102',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Tennessee Code Section 66-28-102, tenancy is determined by behavior rather than a fixed number of days. Actions such as contributing to rent or utilities, receiving mail at the Property, or possessing a key without the owner present may trigger tenant rights. This acknowledgment serves as a clear record of your temporary, non-tenant status. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Behavior-Based', 14, 12, 13),

  ('TX', 'Texas Property Code Section 92.001 / Penal Code 30.05',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Texas Property Code Section 92.001 and Penal Code Section 30.05, tenancy is determined by behavior rather than a fixed number of days. Actions such as contributing to rent or utilities, receiving mail at the Property, or possessing a key without the owner present may trigger tenant rights. This acknowledgment serves as a clear record of your temporary, non-tenant status. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Behavior-Based', 14, 12, 13)

ON CONFLICT (state_code) DO UPDATE SET
  statute_title = EXCLUDED.statute_title,
  section_3_clause = EXCLUDED.section_3_clause,
  legal_threshold_days = EXCLUDED.legal_threshold_days,
  threshold_rule = EXCLUDED.threshold_rule,
  platform_renewal_cycle = EXCLUDED.platform_renewal_cycle,
  reminder_day_1 = EXCLUDED.reminder_day_1,
  reminder_day_2 = EXCLUDED.reminder_day_2;


-- ---- GROUP E: Unique Statutory States ----

INSERT INTO jurisdiction_statutes (state_code, statute_title, section_3_clause, legal_threshold_days, threshold_rule, platform_renewal_cycle, reminder_day_1, reminder_day_2)
VALUES
  ('AZ', 'A.R.S. Section 33-14 / AZ DOR Short-Term Lodging',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Arizona Revised Statutes Section 33-14 and the Arizona Department of Revenue short-term lodging regulations, a stay of 29 days or more may trigger transient lodging tax obligations and tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   29, 'Statutory (AZ DOR)', 28, 26, 27),

  ('MT', 'Montana Code Section 70-24-103',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Montana Code Section 70-24-103, a continuous stay of 7 days or more without a written agreement may lead to the establishment of tenant rights. This acknowledgment serves as a clear record of your temporary status for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   7, 'Common Law', 7, 5, 6)

ON CONFLICT (state_code) DO UPDATE SET
  statute_title = EXCLUDED.statute_title,
  section_3_clause = EXCLUDED.section_3_clause,
  legal_threshold_days = EXCLUDED.legal_threshold_days,
  threshold_rule = EXCLUDED.threshold_rule,
  platform_renewal_cycle = EXCLUDED.platform_renewal_cycle,
  reminder_day_1 = EXCLUDED.reminder_day_1,
  reminder_day_2 = EXCLUDED.reminder_day_2;


-- ---- GROUP C: Lease-Defined States (14-Day Platform Default) ----

INSERT INTO jurisdiction_statutes (state_code, statute_title, section_3_clause, legal_threshold_days, threshold_rule, platform_renewal_cycle, reminder_day_1, reminder_day_2)
VALUES
  ('AK', 'Alaska Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Alaska, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('AR', 'Arkansas Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Arkansas, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('DE', 'Delaware Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Delaware, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('HI', 'Hawaii Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Hawaii, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('ID', 'Idaho Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Idaho, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('IA', 'Iowa Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Iowa, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('LA', 'Louisiana Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Louisiana, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('MA', 'Massachusetts Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Massachusetts, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('MI', 'Michigan Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Michigan, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('NE', 'Nebraska Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Nebraska, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('NV', 'Nevada Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Nevada, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('NH', 'New Hampshire Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in New Hampshire, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('NJ', 'New Jersey Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in New Jersey, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('NM', 'New Mexico Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in New Mexico, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('ND', 'North Dakota Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in North Dakota, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('OK', 'Oklahoma Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Oklahoma, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('OR', 'Oregon ORS 90.275 — Temporary Occupancy Agreement',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest under a Temporary Occupancy Agreement as defined by Oregon Revised Statutes Section 90.275. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager, which would constitute a new Temporary Occupancy Agreement under ORS 90.275.',
   -1, 'Statutory (ORS 90.275)', 14, 12, 13),

  ('RI', 'Rhode Island Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Rhode Island, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('SC', 'South Carolina Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in South Carolina, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('SD', 'South Dakota Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in South Dakota, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('UT', 'Utah Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Utah, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('VT', 'Vermont Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Vermont, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('VA', 'Virginia Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Virginia, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('WA', 'RCW 9A.52.105',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that under Washington Revised Code Section 9A.52.105, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('WV', 'West Virginia Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in West Virginia, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('WI', 'Wisconsin Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Wisconsin, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13),

  ('WY', 'Wyoming Lease-Defined Occupancy',
   'By signing this document, you explicitly acknowledge and agree that your occupancy at the Property is that of a temporary guest and does not constitute a tenancy. You understand that in Wyoming, the nature of occupancy is primarily defined by the agreement between the parties. This document serves as that agreement, establishing your status as a temporary guest for the duration specified herein. You agree that you have no right to occupy the Property beyond the authorized period without a new, written authorization from the Property Owner/Manager.',
   -1, 'Lease-Defined', 14, 12, 13)

ON CONFLICT (state_code) DO UPDATE SET
  statute_title = EXCLUDED.statute_title,
  section_3_clause = EXCLUDED.section_3_clause,
  legal_threshold_days = EXCLUDED.legal_threshold_days,
  threshold_rule = EXCLUDED.threshold_rule,
  platform_renewal_cycle = EXCLUDED.platform_renewal_cycle,
  reminder_day_1 = EXCLUDED.reminder_day_1,
  reminder_day_2 = EXCLUDED.reminder_day_2;


-- ============================================================
-- PART 2: ADD group_classification COLUMN AND POPULATE ALL 50 STATES
-- ============================================================

ALTER TABLE jurisdiction_statutes
  ADD COLUMN IF NOT EXISTS group_classification VARCHAR(1);

UPDATE jurisdiction_statutes SET group_classification = 'A'
WHERE state_code IN ('CA', 'CO', 'CT', 'FL', 'ME', 'MO', 'NC');

UPDATE jurisdiction_statutes SET group_classification = 'B'
WHERE state_code IN ('AL', 'IN', 'KS', 'KY', 'NY', 'OH', 'PA');

UPDATE jurisdiction_statutes SET group_classification = 'C'
WHERE state_code IN ('AK', 'AR', 'DE', 'HI', 'IA', 'ID', 'LA', 'MA', 'MI',
                     'NE', 'NV', 'NH', 'NJ', 'NM', 'ND', 'OK', 'OR', 'RI',
                     'SC', 'SD', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY');

UPDATE jurisdiction_statutes SET group_classification = 'D'
WHERE state_code IN ('GA', 'IL', 'MD', 'MN', 'MS', 'TN', 'TX');

UPDATE jurisdiction_statutes SET group_classification = 'E'
WHERE state_code IN ('AZ', 'MT');


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
-- VERIFICATION QUERIES (uncomment and run after migration)
-- ============================================================

-- Total state count (should be 50):
-- SELECT COUNT(*) AS total_states FROM jurisdiction_statutes;

-- Group distribution (should show A=7, B=7, C=27, D=7, E=2):
-- SELECT group_classification, COUNT(*) AS count FROM jurisdiction_statutes GROUP BY group_classification ORDER BY group_classification;

-- Any states missing group classification (should return 0 rows):
-- SELECT state_code FROM jurisdiction_statutes WHERE group_classification IS NULL;

-- Template sections (should return 5 rows):
-- SELECT section_key, section_title FROM guest_templates ORDER BY id;

-- Full state audit:
-- SELECT state_code, statute_title, group_classification, platform_renewal_cycle FROM jurisdiction_statutes ORDER BY state_code;
