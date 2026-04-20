
import { JurisdictionState } from './jleService';

export interface Clause {
  id: string;
  name: string;
  category: string;
  applicableStates: string[];
  text: string;
  statute?: string;
}

export const CLAUSE_LIBRARY: Record<string, Clause> = {
  "NO_TENANCY_UNIVERSAL": {
    id: "NO_TENANCY_UNIVERSAL",
    name: "No Tenancy Rights",
    category: "RELATIONSHIP",
    applicableStates: ["ALL"],
    text: `{{GUEST_NAME}} ("Guest") acknowledges and agrees that this Agreement does not create a landlord-tenant relationship. Guest is granted a revocable license only and has no tenancy rights, leasehold interest, or possessory rights in the Property.`
  },
  "NO_HOMESTEAD_UNIVERSAL": {
    id: "NO_HOMESTEAD_UNIVERSAL",
    name: "No Homestead Rights",
    category: "RELATIONSHIP",
    applicableStates: ["ALL"],
    text: `Guest expressly waives any and all homestead rights, claims, or protections that may arise under state or local law. Guest acknowledges that this temporary stay does not establish residency or domicile at the Property.`
  },
  "UTILITY_RESTRICTION_UNIVERSAL": {
    id: "UTILITY_RESTRICTION_UNIVERSAL",
    name: "Utility Account Restriction",
    category: "UTILITIES",
    applicableStates: ["ALL"],
    text: `Guest is expressly prohibited from establishing, activating, or modifying any utility accounts in Guest's name at the Property address. Any attempt to do so constitutes a material breach and may be reported as fraud.`
  },
  "REVOCABILITY_UNIVERSAL": {
    id: "REVOCABILITY_UNIVERSAL",
    name: "Revocability Clause",
    category: "REVOCATION",
    applicableStates: ["ALL"],
    text: `This license is revocable at will by the Owner. Upon notice of revocation delivered via DocuStay, email, or SMS, Guest must vacate the Property within {{REVOCATION_HOURS}} hours.`
  },
  "FL_HB621_DECLARATION": {
    id: "FL_HB621_DECLARATION",
    name: "HB 621 Sworn Declaration",
    category: "STATE_SPECIFIC",
    applicableStates: ["FL"],
    statute: "F.S. § 82.036",
    text: `Pursuant to Florida Statute § 82.036, Guest hereby declares under penalty of perjury they are a Transient Guest and NOT a tenant, and has not entered into a written or oral lease.`
  },
  "NY_LICENSE_NOT_LEASE": {
    id: "NY_LICENSE_NOT_LEASE",
    name: "License Not Lease (NY)",
    category: "RELATIONSHIP",
    applicableStates: ["NY"],
    statute: "RPAPL § 711",
    text: `This Agreement constitutes a License, not a Lease, under New York law. Pursuant to NY RPAPL § 711, Guest acknowledges that no landlord-tenant relationship is created.`
  }
};

export const STATE_TEMPLATES: Record<string, any> = {
  "FL": {
    title: "FLORIDA TRANSIENT OCCUPANCY LICENSE (F.S. § 82.036)",
    requiredClauses: ["NO_TENANCY_UNIVERSAL", "NO_HOMESTEAD_UNIVERSAL", "FL_HB621_DECLARATION", "REVOCABILITY_UNIVERSAL", "UTILITY_RESTRICTION_UNIVERSAL"],
    revocationHours: 12
  },
  "NY": {
    title: "NEW YORK REVOCABLE LICENSE FOR TEMPORARY OCCUPANCY",
    requiredClauses: ["NY_LICENSE_NOT_LEASE", "NO_HOMESTEAD_UNIVERSAL", "REVOCABILITY_UNIVERSAL", "UTILITY_RESTRICTION_UNIVERSAL"],
    revocationHours: 24
  }
};

export const generateAgreementContent = (state: JurisdictionState, data: any) => {
  const template = STATE_TEMPLATES[state] || STATE_TEMPLATES["FL"];
  const clauses = template.requiredClauses.map((id: string) => CLAUSE_LIBRARY[id]);
  
  const mergeFields: Record<string, string> = {
    GUEST_NAME: data.guestName,
    REVOCATION_HOURS: String(template.revocationHours),
    PROPERTY_ADDRESS: data.propertyAddress,
    CHECKOUT_DATE: data.checkoutDate
  };

  const processedClauses = clauses.map((c: Clause) => {
    let text = c.text;
    Object.entries(mergeFields).forEach(([k, v]) => {
      text = text.replace(new RegExp(`{{${k}}}`, 'g'), v);
    });
    return { ...c, text };
  });

  return {
    title: template.title,
    clauses: processedClauses,
    id: `AGR-${Date.now()}-${Math.floor(Math.random()*1000)}`
  };
};
