import React from 'react';
import { Modal, Button } from './UI';

export interface InviteRoleChoiceModalProps {
  open: boolean;
  onClose: () => void;
  onSelectTenant: () => void;
  onSelectGuest: () => void;
  /** Optional context label, e.g. "for Unit 101" */
  contextLabel?: string;
}

/** First step of invite flow: choose whether to invite a Tenant or a Guest. */
export const InviteRoleChoiceModal: React.FC<InviteRoleChoiceModalProps> = ({
  open,
  onClose,
  onSelectTenant,
  onSelectGuest,
  contextLabel,
}) => {
  return (
    <Modal open={open} onClose={onClose} title="Who are you inviting?" className="max-w-md">
      <div className="p-6 space-y-4">
        {contextLabel && <p className="text-sm text-slate-600">{contextLabel}</p>}
        <p className="text-slate-700">
          <strong>Tenant</strong> — occupies the unit; they will sign up, verify email, and get access to invite guests and set presence for that unit.
        </p>
        <p className="text-slate-700">
          <strong>Guest</strong> — temporary stay with check-in and check-out dates; they sign the agreement and get a stay record.
        </p>
        <div className="flex flex-col sm:flex-row gap-3 pt-2">
          <Button
            variant="primary"
            onClick={() => {
              onClose();
              onSelectTenant();
            }}
            className="flex-1"
          >
            Invite as tenant
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              onClose();
              onSelectGuest();
            }}
            className="flex-1"
          >
            Invite as guest
          </Button>
        </div>
      </div>
    </Modal>
  );
};
