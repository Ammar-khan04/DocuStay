#!/usr/bin/env python3
"""Remove all property manager related records for a user by email.
Deletes: property_manager_assignments, resident_modes, manager_invitations (to this email), and the user record.
Usage: python scripts/remove_property_manager_user.py dalocef361@pckage.com
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.user import User, UserRole
from app.models.property_manager_assignment import PropertyManagerAssignment
from app.models.resident_mode import ResidentMode
from app.models.manager_invitation import ManagerInvitation


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/remove_property_manager_user.py <email>")
        sys.exit(1)
    email = sys.argv[1].strip().lower()
    if not email or "@" not in email:
        print("Invalid email.")
        sys.exit(1)

    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email, User.role == UserRole.property_manager).first()
        if not user:
            # Try without role filter in case they were changed
            user = db.query(User).filter(User.email == email).first()
            if not user:
                print(f"No user found with email: {email}")
                sys.exit(0)
            if user.role != UserRole.property_manager:
                print(f"User {email} has role {user.role}, not property_manager. Aborting.")
                sys.exit(1)

        user_id = user.id
        print(f"Found property_manager user id={user_id} email={email}")

        # 1. Property manager assignments
        assignments = db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.user_id == user_id).all()
        for a in assignments:
            db.delete(a)
        print(f"  Deleted {len(assignments)} property_manager_assignment(s)")

        # 2. Resident modes (manager_personal)
        modes = db.query(ResidentMode).filter(ResidentMode.user_id == user_id).all()
        for m in modes:
            db.delete(m)
        print(f"  Deleted {len(modes)} resident_mode(s)")

        # 3. Manager invitations sent TO this email (pending or accepted)
        invs = db.query(ManagerInvitation).filter(ManagerInvitation.email == email).all()
        for inv in invs:
            db.delete(inv)
        print(f"  Deleted {len(invs)} manager_invitation(s) for this email")

        # 4. User record
        db.delete(user)
        print(f"  Deleted user id={user_id}")

        db.commit()
        print("Done. All property manager related records for this user have been removed.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
