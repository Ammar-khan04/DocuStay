
import { JurisdictionState } from './jleService';
import { formatDateTimeLocal } from '../utils/dateUtils';

export interface EnforcementDocument {
  title: string;
  statute: string;
  content: string;
  instructions: string;
}

export const generateEnforcementPacket = (state: JurisdictionState, data: any): EnforcementDocument[] => {
  const commonInstructions = "Print these documents immediately. Take them to your local Sheriff's office or Police station. Do not attempt a self-help eviction.";

  switch (state) {
    case 'FL':
      return [
        {
          title: "Verified Complaint for Removal of Unauthorized Person",
          statute: "F.S. § 82.036 (HB 621)",
          instructions: "Sign this in the presence of a notary before taking to the Sheriff.",
          content: `Pursuant to Section 82.036, Florida Statutes, I, ${data.ownerName}, declare that ${data.guestName} is an unauthorized person at ${data.propertyAddress}. This person is NOT a tenant. I request immediate removal by the County Sheriff.`
        },
        {
          title: "Notice of License Revocation",
          statute: "DocuStay Authorization Protocol",
          instructions: "Keep as proof of service.",
          content: `Stay authorization for Token ${data.tokenId} was officially revoked at ${formatDateTimeLocal(new Date())}.`
        }
      ];
    case 'NY':
      return [
        {
          title: "Notice to Vacate - License Termination",
          statute: "RPAPL § 711",
          instructions: "Deliver to guest immediately.",
          content: `In accordance with New York Real Property Actions and Proceedings Law § 711, your license to occupy ${data.propertyAddress} is hereby terminated. Continued occupancy constitutes Criminal Trespass.`
        }
      ];
    default:
      return [{ title: "General Trespass Warning", statute: "Common Law", instructions: commonInstructions, content: "Guest has overstayed their legal license." }];
  }
};
