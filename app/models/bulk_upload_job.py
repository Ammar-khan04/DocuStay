"""Async bulk upload job tracking."""
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from app.database import Base


class BulkUploadJob(Base):
    __tablename__ = "bulk_upload_jobs"

    id = Column(Integer, primary_key=True, index=True)
    job_key = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="processing")  # processing | completed | failed
    csv_content = Column(Text, nullable=False)
    total_rows = Column(Integer, nullable=False, default=0)
    processed_rows = Column(Integer, nullable=False, default=0)
    created = Column(Integer, nullable=False, default=0)
    updated = Column(Integer, nullable=False, default=0)
    failed_from_row = Column(Integer, nullable=True)
    failure_reason = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
