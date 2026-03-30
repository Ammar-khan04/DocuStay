
export enum UserType {
  PROPERTY_OWNER = 'PROPERTY_OWNER',
  PROPERTY_MANAGER = 'PROPERTY_MANAGER',
  TENANT = 'TENANT',
  GUEST = 'GUEST',
  ADMIN = 'ADMIN'
}

export type ContextMode = 'business' | 'personal';

export enum AccountStatus {
  PENDING_VERIFICATION = 'PENDING_VERIFICATION',
  EMAIL_VERIFIED = 'EMAIL_VERIFIED',
  PHONE_VERIFIED = 'PHONE_VERIFIED',
  FULLY_VERIFIED = 'FULLY_VERIFIED',
  ACTIVE = 'ACTIVE'
}

export interface UserSession {
  user_id: string;
  user_type: UserType;
  user_name: string;
  email: string;
  account_status: AccountStatus;
  token: string;
}

export interface AppState {
  user: UserSession | null;
  pendingVerification?: {
    userId: string;
    type: 'email' | 'phone';
    expectedCode?: string;
    generatedAt: string;
  };
  invitationData?: any;
}
