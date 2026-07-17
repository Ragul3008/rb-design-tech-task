from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Table, UniqueConstraint, Text
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime
from backend.database import Base

# Association table for Role-Permission many-to-many relationship
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", String, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", String, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)

class Org(Base):
    __tablename__ = "orgs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # 'BROKER' or 'CARRIER'

    users = relationship("User", back_populates="org")
    roles = relationship("Role", back_populates="org", cascade="all, delete-orphan")
    compliance_record = relationship("CarrierComplianceRecord", uselist=False, back_populates="carrier_org")

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    account_type = Column(String, nullable=False)  # 'BROKER_STAFF', 'CARRIER_STAFF', 'SHIPPER'
    org_id = Column(String, ForeignKey("orgs.id", ondelete="SET NULL"), nullable=True)
    role_id = Column(String, ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)

    org = relationship("Org", back_populates="users")
    role = relationship("Role", back_populates="users")
    confirmed_rates = relationship("RateConfirmation", back_populates="confirmed_by_user")
    status_events = relationship("LoadStatusEvent", back_populates="changed_by_user")
    access_logs = relationship("AccessLog", back_populates="user")

class Role(Base):
    __tablename__ = "roles"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id = Column(String, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)

    org = relationship("Org", back_populates="roles")
    users = relationship("User", back_populates="role")
    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles")

    __table_args__ = (UniqueConstraint("org_id", "name", name="uix_org_role_name"),)

class Permission(Base):
    __tablename__ = "permissions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    key = Column(String, unique=True, index=True, nullable=False)  # e.g., 'load.create'

    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")

class CarrierComplianceRecord(Base):
    __tablename__ = "carrier_compliance_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    carrier_org_id = Column(String, ForeignKey("orgs.id", ondelete="CASCADE"), unique=True, nullable=False)
    insurance_expiry_date = Column(DateTime, nullable=False)
    mc_dot_authority_status = Column(String, nullable=False)  # 'ACTIVE', 'INACTIVE'
    approved_equipment_types = Column(Text, nullable=False)  # JSON string of string[]
    approved_commodity_types = Column(Text, nullable=False)  # JSON string of string[]
    last_updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    carrier_org = relationship("Org", back_populates="compliance_record")

class RateConfirmation(Base):
    __tablename__ = "rate_confirmations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    load_id = Column(String, ForeignKey("loads.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, default=1, nullable=False)
    base_rate = Column(Float, nullable=False)
    accessorials = Column(Text, nullable=False)  # JSON string of accessorials details
    confirmed_by_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    confirmed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    confirmed_by_user = relationship("User", back_populates="confirmed_rates")
    load = relationship("Load", foreign_keys=[load_id], back_populates="rate_confirmations")

class Load(Base):
    __tablename__ = "loads"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    shipper_id = Column(String, ForeignKey("users.id"), nullable=False)
    broker_org_id = Column(String, ForeignKey("orgs.id"), nullable=False)
    assigned_carrier_org_id = Column(String, ForeignKey("orgs.id"), nullable=True)
    state = Column(String, default="POSTED", nullable=False)  # 'POSTED', 'CARRIER_ASSIGNED', etc.
    compliance_flag = Column(Boolean, default=False, nullable=False)
    compliance_reason = Column(Text, nullable=True)
    current_rate_confirmation_id = Column(String, ForeignKey("rate_confirmations.id", ondelete="SET NULL"), nullable=True)
    required_equipment_type = Column(String, nullable=False)
    required_commodity_type = Column(String, nullable=False)
    pod_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    shipper = relationship("User", foreign_keys=[shipper_id])
    broker_org = relationship("Org", foreign_keys=[broker_org_id])
    assigned_carrier_org = relationship("Org", foreign_keys=[assigned_carrier_org_id])
    
    current_rate_confirmation = relationship("RateConfirmation", foreign_keys=[current_rate_confirmation_id], post_update=True)
    rate_confirmations = relationship("RateConfirmation", foreign_keys=[RateConfirmation.load_id], back_populates="load", cascade="all, delete-orphan")
    status_events = relationship("LoadStatusEvent", back_populates="load", cascade="all, delete-orphan")

class LoadStatusEvent(Base):
    __tablename__ = "load_status_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    load_id = Column(String, ForeignKey("loads.id", ondelete="CASCADE"), nullable=False)
    from_state = Column(String, nullable=True)
    to_state = Column(String, nullable=False)
    changed_by_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    note = Column(Text, nullable=False)

    load = relationship("Load", back_populates="status_events")
    changed_by_user = relationship("User", back_populates="status_events")

class AccessLog(Base):
    __tablename__ = "access_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_email = Column(String, nullable=True)
    org_id = Column(String, nullable=True)
    attempted_permission = Column(String, nullable=False)
    endpoint = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    reason = Column(Text, nullable=False)

    user = relationship("User", back_populates="access_logs")
