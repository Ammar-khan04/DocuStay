"""Demo accounts marker.

Stored separately so normal auth/user schema is untouched (no migrations needed).
"""
from __future__ import annotations

from sqlalchemy import Column, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class DemoAccount(Base):
    __tablename__ = "demo_accounts"
    __table_args__ = (UniqueConstraint("user_id", name="uq_demo_accounts_user_id"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")


def is_demo_user_id(db, user_id: int | None) -> bool:
    """True when the user is marked as a demo account (invite links from them use the demo flow)."""
    if user_id is None:
        return False
    return db.query(DemoAccount).filter(DemoAccount.user_id == user_id).first() is not None
