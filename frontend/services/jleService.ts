
export type JurisdictionState =
  | 'AL' | 'AK' | 'AZ' | 'AR' | 'CA' | 'CO' | 'CT' | 'DE' | 'FL' | 'GA'
  | 'HI' | 'ID' | 'IL' | 'IN' | 'IA' | 'KS' | 'KY' | 'LA' | 'ME' | 'MD'
  | 'MA' | 'MI' | 'MN' | 'MS' | 'MO' | 'MT' | 'NE' | 'NV' | 'NH' | 'NJ'
  | 'NM' | 'NY' | 'NC' | 'ND' | 'OH' | 'OK' | 'OR' | 'PA' | 'RI' | 'SC'
  | 'SD' | 'TN' | 'TX' | 'UT' | 'VT' | 'VA' | 'WA' | 'WV' | 'WI' | 'WY';

export interface StayDetails {
  durationDays: number;
  paymentInvolved: boolean;
  exclusivePossession: boolean;
  checkInDate: string;
  checkOutDate: string;
}

export interface RiskFactor {
  factor: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  message: string;
  recommendation?: string;
}

export interface JurisdictionRule {
  name: string;
  group: 'A' | 'B' | 'C' | 'D' | 'E';
  /** Actual statutory threshold (null for lease-defined / behavior-based states) */
  legalThresholdDays: number | null;
  /** Operational authorization period the platform enforces */
  platformRenewalCycleDays: number;
  /** Days before renewal cycle ends to start reminding */
  reminderDaysBefore: number;
  agreementType: string;
  allowExtendedIfOwnerOccupied: boolean;
  groupLabel: string;
}

// ---------------------------------------------------------------------------
// Grouped jurisdiction buckets
// ---------------------------------------------------------------------------

const GROUP_A_BASE: Pick<JurisdictionRule, 'group' | 'legalThresholdDays' | 'platformRenewalCycleDays' | 'reminderDaysBefore' | 'groupLabel'> = {
  group: 'A',
  legalThresholdDays: 14,
  platformRenewalCycleDays: 13,
  reminderDaysBefore: 3,
  groupLabel: '14-day common-law',
};

const GROUP_B_BASE: Pick<JurisdictionRule, 'group' | 'legalThresholdDays' | 'platformRenewalCycleDays' | 'reminderDaysBefore' | 'groupLabel'> = {
  group: 'B',
  legalThresholdDays: 30,
  platformRenewalCycleDays: 29,
  reminderDaysBefore: 5,
  groupLabel: '30-day',
};

const GROUP_C_BASE: Pick<JurisdictionRule, 'group' | 'legalThresholdDays' | 'platformRenewalCycleDays' | 'reminderDaysBefore' | 'groupLabel'> = {
  group: 'C',
  legalThresholdDays: null,
  platformRenewalCycleDays: 14,
  reminderDaysBefore: 3,
  groupLabel: 'Lease-defined (14-day default)',
};

const GROUP_D_BASE: Pick<JurisdictionRule, 'group' | 'legalThresholdDays' | 'platformRenewalCycleDays' | 'reminderDaysBefore' | 'groupLabel'> = {
  group: 'D',
  legalThresholdDays: null,
  platformRenewalCycleDays: 14,
  reminderDaysBefore: 3,
  groupLabel: 'Behavior-based',
};

function g(base: typeof GROUP_A_BASE, name: string, agreementType = 'REVOCABLE_LICENSE', allowExtended = false): JurisdictionRule {
  return { ...base, name, agreementType, allowExtendedIfOwnerOccupied: allowExtended };
}

export const JURISDICTION_RULES: Record<JurisdictionState, JurisdictionRule> = {
  // Group A — 14-day common-law
  CA: g(GROUP_A_BASE, 'California', 'TRANSIENT_LODGER', true),
  CO: g(GROUP_A_BASE, 'Colorado'),
  CT: g(GROUP_A_BASE, 'Connecticut'),
  FL: g(GROUP_A_BASE, 'Florida', 'HB621_DECLARATION'),
  ME: g(GROUP_A_BASE, 'Maine'),
  MO: g(GROUP_A_BASE, 'Missouri'),
  NC: g(GROUP_A_BASE, 'North Carolina'),

  // Group B — 30-day
  AL: g(GROUP_B_BASE, 'Alabama'),
  IN: g(GROUP_B_BASE, 'Indiana'),
  KS: g(GROUP_B_BASE, 'Kansas'),
  KY: g(GROUP_B_BASE, 'Kentucky'),
  NY: g(GROUP_B_BASE, 'New York'),
  OH: g(GROUP_B_BASE, 'Ohio'),
  PA: g(GROUP_B_BASE, 'Pennsylvania'),

  // Group C — Lease-defined, 14-day platform default
  AK: g(GROUP_C_BASE, 'Alaska'),
  AR: g(GROUP_C_BASE, 'Arkansas'),
  DE: g(GROUP_C_BASE, 'Delaware'),
  HI: g(GROUP_C_BASE, 'Hawaii'),
  ID: g(GROUP_C_BASE, 'Idaho'),
  IA: g(GROUP_C_BASE, 'Iowa'),
  LA: g(GROUP_C_BASE, 'Louisiana'),
  MA: g(GROUP_C_BASE, 'Massachusetts'),
  MI: g(GROUP_C_BASE, 'Michigan'),
  NE: g(GROUP_C_BASE, 'Nebraska'),
  NV: g(GROUP_C_BASE, 'Nevada'),
  NH: g(GROUP_C_BASE, 'New Hampshire'),
  NJ: g(GROUP_C_BASE, 'New Jersey'),
  NM: g(GROUP_C_BASE, 'New Mexico'),
  ND: g(GROUP_C_BASE, 'North Dakota'),
  OK: g(GROUP_C_BASE, 'Oklahoma'),
  OR: g(GROUP_C_BASE, 'Oregon'),
  RI: g(GROUP_C_BASE, 'Rhode Island'),
  SC: g(GROUP_C_BASE, 'South Carolina'),
  SD: g(GROUP_C_BASE, 'South Dakota'),
  UT: g(GROUP_C_BASE, 'Utah'),
  VT: g(GROUP_C_BASE, 'Vermont'),
  VA: g(GROUP_C_BASE, 'Virginia'),
  WA: g(GROUP_C_BASE, 'Washington', 'ANTI_SQUATTER_DECLARATION'),
  WV: g(GROUP_C_BASE, 'West Virginia'),
  WI: g(GROUP_C_BASE, 'Wisconsin'),
  WY: g(GROUP_C_BASE, 'Wyoming'),

  // Group D — Behavior-based
  GA: g(GROUP_D_BASE, 'Georgia'),
  IL: g(GROUP_D_BASE, 'Illinois'),
  MD: g(GROUP_D_BASE, 'Maryland'),
  MN: g(GROUP_D_BASE, 'Minnesota'),
  MS: g(GROUP_D_BASE, 'Mississippi'),
  TN: g(GROUP_D_BASE, 'Tennessee'),
  TX: g(GROUP_D_BASE, 'Texas', 'TRANSIENT_GUEST'),

  // Group E — Unique
  AZ: {
    name: 'Arizona',
    group: 'E',
    legalThresholdDays: 29,
    platformRenewalCycleDays: 28,
    reminderDaysBefore: 5,
    agreementType: 'REVOCABLE_LICENSE',
    allowExtendedIfOwnerOccupied: false,
    groupLabel: 'Unique (29-day threshold)',
  },
  MT: {
    name: 'Montana',
    group: 'E',
    legalThresholdDays: 7,
    platformRenewalCycleDays: 7,
    reminderDaysBefore: 2,
    agreementType: 'REVOCABLE_LICENSE',
    allowExtendedIfOwnerOccupied: false,
    groupLabel: 'Unique (7-day threshold)',
  },
};

/** State options for dropdowns. Value = 2-letter code, label = full name. */
export const STATE_OPTIONS: { value: string; label: string }[] = (
  Object.entries(JURISDICTION_RULES) as [JurisdictionState, JurisdictionRule][]
)
  .map(([code, rule]) => ({ value: code, label: rule.name }))
  .sort((a, b) => a.label.localeCompare(b.label));

/** Describe the legal threshold for display. */
export function legalThresholdLabel(state: JurisdictionState): string {
  const r = JURISDICTION_RULES[state];
  if (r.legalThresholdDays != null) return `${r.legalThresholdDays} days`;
  if (r.group === 'C') return 'Lease-defined';
  if (r.group === 'D') return 'Behavior-based';
  return 'Varies';
}

export const analyzeStay = (state: JurisdictionState, details: StayDetails) => {
  const rules = JURISDICTION_RULES[state];
  if (!rules) throw new Error("Unsupported jurisdiction");

  const renewalLimit = rules.platformRenewalCycleDays;
  let classification = "GUEST";
  let riskLevel: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' = "LOW";
  let riskFactors: RiskFactor[] = [];

  if (details.durationDays > renewalLimit) {
    classification = "TENANT_RISK";
    riskLevel = "CRITICAL";
    riskFactors.push({
      factor: "DURATION_EXCEEDS_LIMIT",
      severity: "CRITICAL",
      message: `Stay of ${details.durationDays} days exceeds platform renewal cycle of ${renewalLimit} days` +
        (rules.legalThresholdDays != null ? ` (legal threshold: ${rules.legalThresholdDays} days)` : ''),
      recommendation: "Shorten stay or renew authorization before cycle ends."
    });
  } else if (details.durationDays > renewalLimit - rules.reminderDaysBefore) {
    classification = "TEMPORARY_OCCUPANT";
    riskLevel = "MEDIUM";
    riskFactors.push({
      factor: "APPROACHING_LIMIT",
      severity: "MEDIUM",
      message: `Stay is within ${rules.reminderDaysBefore} days of renewal cycle end`,
      recommendation: "Ensure authorization is renewed or check-out is enforced."
    });
  }

  if (details.paymentInvolved) {
    const severity = state === "TX" ? "HIGH" : "MEDIUM";
    riskFactors.push({
      factor: "PAYMENT_INVOLVED",
      severity,
      message: state === "TX" ? "Any payment in Texas can create tenant status" : "Payment may resemble rent",
      recommendation: "Avoid any exchange of money or labor."
    });
    if (riskLevel !== "CRITICAL") riskLevel = severity as any;
  }

  const weights: Record<string, number> = {
    DURATION_EXCEEDS_LIMIT: 50,
    APPROACHING_LIMIT: 20,
    PAYMENT_INVOLVED: 25,
    EXCLUSIVE_POSSESSION: 20
  };
  let riskScore = 0;
  riskFactors.forEach(rf => riskScore += weights[rf.factor] || 10);
  riskScore = Math.min(100, riskScore);

  return {
    jurisdiction: {
      state,
      name: rules.name,
      group: rules.group,
      groupLabel: rules.groupLabel,
      legalThresholdDays: rules.legalThresholdDays,
    },
    classification: { stayType: classification, riskLevel, riskScore },
    limits: {
      platformRenewalCycleDays: renewalLimit,
      legalThresholdDays: rules.legalThresholdDays,
      withinLimit: details.durationDays <= renewalLimit,
      daysUntilRisk: Math.max(0, renewalLimit - details.durationDays),
      // Backward compat
      maxSafeStayDays: renewalLimit,
    },
    riskFactors,
    legal: {
      agreementType: rules.agreementType,
    },
    canProceed: riskLevel !== "CRITICAL"
  };
};
