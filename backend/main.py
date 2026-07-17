from fastapi import FastAPI, Depends, HTTPException, status, Response, Cookie, Body
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import json
import os

from backend.database import get_db, engine, Base
from backend.models import Org, User, Role, Permission, CarrierComplianceRecord, RateConfirmation, Load, LoadStatusEvent, AccessLog
from backend.auth import verify_password, create_access_token, get_current_user, hash_password
from backend.rbac import enforce_permission, get_load_scope, has_permission, PERMISSION_CATALOG
from backend.compliance import check_carrier_compliance, recheck_carrier_loads_compliance

app = FastAPI(title="LoadFlow Operations Suite")

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Schemas
class LoginRequest(BaseModel):
    email: str
    password: str

class CreateLoadRequest(BaseModel):
    requiredEquipmentType: str
    requiredCommodityType: str
    shipperId: Optional[str] = None
    brokerOrgId: Optional[str] = None

class AssignCarrierRequest(BaseModel):
    carrierOrgId: str

class RateConfirmRequest(BaseModel):
    baseRate: float
    accessorials: List[Dict[str, Any]] = []

class StatusUpdateRequest(BaseModel):
    toState: str
    note: Optional[str] = ""

class ComplianceOverrideRequest(BaseModel):
    reason: str

class PodUploadRequest(BaseModel):
    podUrl: str

class CreateRoleRequest(BaseModel):
    name: str
    permissionKeys: List[str]

class CreateStaffRequest(BaseModel):
    email: str
    password: str
    roleId: str

class UpdateComplianceRequest(BaseModel):
    insuranceExpiryDate: str
    mcDotAuthorityStatus: str
    approvedEquipmentTypes: List[str]
    approvedCommodityTypes: List[str]

# Authentication endpoints
@app.post("/api/auth/login")
async def login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token({
        "userId": user.id,
        "email": user.email,
        "accountType": user.account_type,
        "orgId": user.org_id
    })

    response.set_cookie(
        key="token",
        value=token,
        httponly=True,
        samesite="strict",
        max_age=3600 * 24,
        path="/"
    )

    # Return profile payload
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "accountType": user.account_type,
            "orgId": user.org_id,
            "role": {
                "id": user.role.id,
                "name": user.role.name,
                "permissions": [p.key for p in user.role.permissions]
            } if user.role else None
        }
    }

@app.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie(key="token", path="/")
    return {"success": True, "message": "Logged out successfully"}

@app.get("/api/auth/me")
async def get_me(user: User = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "accountType": user.account_type,
            "orgId": user.org_id,
            "org": {
                "id": user.org.id,
                "name": user.org.name,
                "type": user.org.type
            } if user.org else None,
            "role": {
                "id": user.role.id,
                "name": user.role.name,
                "permissions": [p.key for p in user.role.permissions]
            } if user.role else None
        }
    }

# Loads endpoints
@app.get("/api/loads")
async def get_loads(
    state: Optional[str] = None,
    search: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    scope = get_load_scope(user)
    query = db.query(Load).filter(scope)

    if state:
        query = query.filter(Load.state == state)

    if search:
        search_filter = f"%{search}%"
        # Join user & org for search checks
        query = query.join(User, Load.shipper_id == User.id)\
                     .outerjoin(Org, Load.assigned_carrier_org_id == Org.id)\
                     .filter(
                         (Load.required_equipment_type.like(search_filter)) |
                         (Load.required_commodity_type.like(search_filter)) |
                         (User.email.like(search_filter)) |
                         (Org.name.like(search_filter))
                     )

    loads = query.order_by(Load.created_at.desc()).all()

    # Format output payload
    output = []
    for load in loads:
        events = []
        for e in sorted(load.status_events, key=lambda ev: ev.timestamp, reverse=True):
            events.append({
                "id": e.id,
                "fromState": e.from_state,
                "toState": e.to_state,
                "changedByUserId": e.changed_by_user_id,
                "changedByUser": {"email": e.changed_by_user.email},
                "timestamp": e.timestamp.isoformat() + "Z",
                "note": e.note
            })

        output.append({
            "id": load.id,
            "shipperId": load.shipper_id,
            "shipper": {"id": load.shipper.id, "email": load.shipper.email},
            "brokerOrgId": load.broker_org_id,
            "brokerOrg": {"id": load.broker_org.id, "name": load.broker_org.name},
            "assignedCarrierOrgId": load.assigned_carrier_org_id,
            "assignedCarrierOrg": {"id": load.assigned_carrier_org.id, "name": load.assigned_carrier_org.name} if load.assigned_carrier_org else None,
            "state": load.state,
            "complianceFlag": load.compliance_flag,
            "complianceReason": load.compliance_reason,
            "currentRateConfirmationId": load.current_rate_confirmation_id,
            "currentRateConfirmation": {
                "id": load.current_rate_confirmation.id,
                "version": load.current_rate_confirmation.version,
                "baseRate": load.current_rate_confirmation.base_rate,
                "accessorials": load.current_rate_confirmation.accessorials,
                "confirmedAt": load.current_rate_confirmation.confirmed_at.isoformat() + "Z"
            } if load.current_rate_confirmation else None,
            "requiredEquipmentType": load.required_equipment_type,
            "requiredCommodityType": load.required_commodity_type,
            "podUrl": load.pod_url,
            "createdAt": load.created_at.isoformat() + "Z",
            "statusEvents": events
        })

    return {"loads": output}

@app.post("/api/loads", status_code=201)
async def create_load(
    req: CreateLoadRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    final_shipper_id = req.shipperId
    final_broker_org_id = req.brokerOrgId

    if user.account_type == "SHIPPER":
        final_shipper_id = user.id
        if not final_broker_org_id:
            default_broker = db.query(Org).filter(Org.type == "BROKER").first()
            if not default_broker:
                raise HTTPException(status_code=400, detail="No broker organization available")
            final_broker_org_id = default_broker.id
    elif user.account_type == "BROKER_STAFF":
        enforce_permission(user, "load.create", "/api/loads (POST)", db)
        if not final_shipper_id:
            raise HTTPException(status_code=400, detail="shipperId is required when created by broker staff")
        final_broker_org_id = user.org_id
    else:
        raise HTTPException(status_code=403, detail="Forbidden")

    load = Load(
        shipper_id=final_shipper_id,
        broker_org_id=final_broker_org_id,
        required_equipment_type=req.requiredEquipmentType,
        required_commodity_type=req.requiredCommodityType,
        state="POSTED",
        compliance_flag=False
    )
    db.add(load)
    db.commit()

    evt = LoadStatusEvent(
        load_id=load.id,
        from_state=None,
        to_state="POSTED",
        changed_by_user_id=user.id,
        note=f"Load created and posted by {user.email}."
    )
    db.add(evt)
    db.commit()

    return {"load": {"id": load.id, "state": load.state}}

@app.get("/api/loads/{load_id}")
async def get_load(
    load_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    scope = get_load_scope(user)
    load = db.query(Load).filter(Load.id == load_id, scope).first()
    if not load:
        raise HTTPException(status_code=404, detail="Load not found or access denied")

    events = []
    for e in sorted(load.status_events, key=lambda ev: ev.timestamp, reverse=True):
        events.append({
            "id": e.id,
            "fromState": e.from_state,
            "toState": e.to_state,
            "changedByUser": {"email": e.changed_by_user.email},
            "timestamp": e.timestamp.isoformat() + "Z",
            "note": e.note
        })

    rate_confirmations = []
    for rc in sorted(load.rate_confirmations, key=lambda r: r.version, reverse=True):
        rate_confirmations.append({
            "id": rc.id,
            "version": rc.version,
            "baseRate": rc.base_rate,
            "accessorials": rc.accessorials,
            "confirmedByUser": {"email": rc.confirmed_by_user.email},
            "confirmedAt": rc.confirmed_at.isoformat() + "Z"
        })

    return {
        "load": {
            "id": load.id,
            "shipper": {"id": load.shipper.id, "email": load.shipper.email},
            "brokerOrg": {"id": load.broker_org.id, "name": load.broker_org.name},
            "assignedCarrierOrg": {"id": load.assigned_carrier_org.id, "name": load.assigned_carrier_org.name} if load.assigned_carrier_org else None,
            "state": load.state,
            "complianceFlag": load.compliance_flag,
            "complianceReason": load.compliance_reason,
            "currentRateConfirmation": {
                "id": load.current_rate_confirmation.id,
                "version": load.current_rate_confirmation.version,
                "baseRate": load.current_rate_confirmation.base_rate,
                "accessorials": load.current_rate_confirmation.accessorials,
                "confirmedAt": load.current_rate_confirmation.confirmed_at.isoformat() + "Z"
            } if load.current_rate_confirmation else None,
            "rateConfirmations": rate_confirmations,
            "requiredEquipmentType": load.required_equipment_type,
            "requiredCommodityType": load.required_commodity_type,
            "podUrl": load.pod_url,
            "createdAt": load.created_at.isoformat() + "Z",
            "statusEvents": events
        }
    }

@app.post("/api/loads/{load_id}/assign")
async def assign_carrier(
    load_id: str,
    req: AssignCarrierRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    endpoint = f"/api/loads/{load_id}/assign"
    enforce_permission(user, "load.assign_carrier", endpoint, db)

    scope = get_load_scope(user)
    load = db.query(Load).filter(Load.id == load_id, scope).first()
    if not load:
        raise HTTPException(status_code=404, detail="Load not found")

    if load.state not in ["POSTED", "CARRIER_ASSIGNED"]:
        raise HTTPException(status_code=400, detail=f"Cannot assign carrier in load state {load.state}")

    # Check sandbox values or direct ID
    carrier_org_id = req.carrierOrgId
    if carrier_org_id == "FALCON_EXPRESS":
        carrier_org = db.query(Org).filter(Org.name.like("%Falcon%"), Org.type == "CARRIER").first()
    elif carrier_org_id == "RED_FLAG":
        carrier_org = db.query(Org).filter(Org.name.like("%Red Flag%"), Org.type == "CARRIER").first()
    else:
        carrier_org = db.query(Org).filter(Org.id == carrier_org_id, Org.type == "CARRIER").first()

    if not carrier_org:
        raise HTTPException(status_code=400, detail="Invalid carrier organization")

    # Run compliance check
    compliant, reason = check_carrier_compliance(
        carrier_org.id,
        load.required_equipment_type,
        load.required_commodity_type,
        db
    )

    load.assigned_carrier_org_id = carrier_org.id
    load.state = "CARRIER_ASSIGNED"
    load.compliance_flag = not compliant
    load.compliance_reason = reason
    db.commit()

    # Log in audit events
    note = f"Carrier Assigned: '{carrier_org.name}'. Compliance Auto-Check: {'PASSED' if compliant else f'FAILED - {reason}'}"
    evt = LoadStatusEvent(
        load_id=load.id,
        from_state="POSTED",
        to_state="CARRIER_ASSIGNED",
        changed_by_user_id=user.id,
        note=note
    )
    db.add(evt)
    db.commit()

    return {"load": {"id": load.id, "state": load.state, "complianceFlag": load.compliance_flag}}

@app.post("/api/loads/{load_id}/rate-confirm")
async def confirm_rate(
    load_id: str,
    req: RateConfirmRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    endpoint = f"/api/loads/{load_id}/rate-confirm"
    enforce_permission(user, "rate.confirm", endpoint, db)

    scope = get_load_scope(user)
    load = db.query(Load).filter(Load.id == load_id, scope).first()
    if not load:
        raise HTTPException(status_code=404, detail="Load not found")

    if load.state not in ["CARRIER_ASSIGNED", "RATE_CONFIRMED"]:
        raise HTTPException(status_code=400, detail="Cannot confirm rate in this state")

    # Compliance Block Check
    is_overridden = False
    if load.compliance_flag:
        can_override = has_permission(user, "load.override_compliance_flag")
        if not can_override:
            # Log access block
            log = AccessLog(
                user_id=user.id,
                user_email=user.email,
                org_id=user.org_id,
                attempted_permission="load.override_compliance_flag",
                endpoint=endpoint,
                reason=f"Attempted to confirm rate on flagged load {load.id} but lacks override permission."
            )
            db.add(log)
            db.commit()
            raise HTTPException(
                status_code=403,
                detail="Compliance Block: Carrier is flagged as non-compliant. Action blocked unless authorized."
            )
        is_overridden = True

    # Version check
    current_version = 0
    if load.current_rate_confirmation:
        current_version = load.current_rate_confirmation.version

    rate = RateConfirmation(
        load_id=load.id,
        version=current_version + 1,
        base_rate=req.baseRate,
        accessorials=json.dumps(req.accessorials),
        confirmed_by_user_id=user.id
    )
    db.add(rate)
    db.commit()

    load.current_rate_confirmation_id = rate.id
    load.state = "RATE_CONFIRMED"
    db.commit()

    note = f"Rate confirmed. Version: {rate.version}, Base Rate: ${rate.base_rate}."
    if is_overridden:
        note += f" [COMPLIANCE OVERRIDE BY USER: {user.email}]. Reason: Carrier flagged but overridden."

    evt = LoadStatusEvent(
        load_id=load.id,
        from_state="CARRIER_ASSIGNED",
        to_state="RATE_CONFIRMED",
        changed_by_user_id=user.id,
        note=note
    )
    db.add(evt)
    db.commit()

    return {"load": {"id": load.id, "state": load.state}, "rateConfirmation": {"id": rate.id}}

@app.post("/api/loads/{load_id}/status")
async def update_status(
    load_id: str,
    req: StatusUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    endpoint = f"/api/loads/{load_id}/status"
    enforce_permission(user, "load.update_status", endpoint, db)

    scope = get_load_scope(user)
    load = db.query(Load).filter(Load.id == load_id, scope).first()
    if not load:
        raise HTTPException(status_code=404, detail="Load not found")

    state_order = [
        "POSTED", "CARRIER_ASSIGNED", "RATE_CONFIRMED", "DISPATCHED",
        "IN_TRANSIT", "DELIVERED", "POD_VERIFIED", "INVOICED_CLOSED"
    ]

    from_state = load.state
    if from_state not in state_order or req.toState not in state_order:
        raise HTTPException(status_code=400, detail="Invalid states provided")

    from_idx = state_order.index(from_state)
    to_idx = state_order.index(req.toState)

    is_next_step = to_idx == from_idx + 1
    can_override = has_permission(user, "load.override_compliance_flag")

    if not is_next_step and not can_override:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid transition. Must move sequentially from {from_state} to {state_order[from_idx+1]}."
        )

    # Compliance Block check
    if load.compliance_flag and to_idx > 1:
        if not can_override:
            # Log access block
            log = AccessLog(
                user_id=user.id,
                user_email=user.email,
                org_id=user.org_id,
                attempted_permission="load.override_compliance_flag",
                endpoint=endpoint,
                reason=f"Attempted to transition flagged load {load.id} to {req.toState} without override permission."
            )
            db.add(log)
            db.commit()
            raise HTTPException(status_code=403, detail="Compliance Block: Carrier is flagged as non-compliant.")

    load.state = req.toState
    db.commit()

    note = req.note or f"State transitioned from {from_state} to {req.toState}."
    if not is_next_step and can_override:
        note += f" [MANUAL SEQUENCE OVERRIDE BY USER: {user.email}]."
    if load.compliance_flag and to_idx > 1 and can_override:
        note += f" [COMPLIANCE BYPASS OVERRIDE BY USER: {user.email}]. Reason: {load.compliance_reason}"

    evt = LoadStatusEvent(
        load_id=load.id,
        from_state=from_state,
        to_state=req.toState,
        changed_by_user_id=user.id,
        note=note
    )
    db.add(evt)
    db.commit()

    return {"load": {"id": load.id, "state": load.state}}

@app.post("/api/loads/{load_id}/override")
async def manual_override(
    load_id: str,
    req: ComplianceOverrideRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    endpoint = f"/api/loads/{load_id}/override"
    enforce_permission(user, "load.override_compliance_flag", endpoint, db)

    scope = get_load_scope(user)
    load = db.query(Load).filter(Load.id == load_id, scope).first()
    if not load:
        raise HTTPException(status_code=404, detail="Load not found")

    if not load.compliance_flag:
        raise HTTPException(status_code=400, detail="Load compliance is not flagged")

    load.compliance_flag = False
    load.compliance_reason = f"Overridden. Previous: {load.compliance_reason}"
    db.commit()

    evt = LoadStatusEvent(
        load_id=load.id,
        from_state=load.state,
        to_state=load.state,
        changed_by_user_id=user.id,
        note=f"Manual Compliance Override by {user.email}. Justification: {req.reason}"
    )
    db.add(evt)
    db.commit()

    return {"load": {"id": load.id, "complianceFlag": load.compliance_flag}}

@app.post("/api/loads/{load_id}/pod")
async def upload_pod(
    load_id: str,
    req: PodUploadRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    endpoint = f"/api/loads/{load_id}/pod"
    enforce_permission(user, "pod.upload", endpoint, db)

    scope = get_load_scope(user)
    load = db.query(Load).filter(Load.id == load_id, scope).first()
    if not load:
        raise HTTPException(status_code=404, detail="Load not found")

    if load.state not in ["DELIVERED", "POD_VERIFIED"]:
        raise HTTPException(status_code=400, detail="Load must be DELIVERED to upload POD")

    load.pod_url = req.podUrl
    load.state = "POD_VERIFIED"
    db.commit()

    evt = LoadStatusEvent(
        load_id=load.id,
        from_state="DELIVERED",
        to_state="POD_VERIFIED",
        changed_by_user_id=user.id,
        note=f"Proof of Delivery (POD) uploaded. URL: {req.podUrl}. State transitioned to POD_VERIFIED."
    )
    db.add(evt)
    db.commit()

    return {"load": {"id": load.id, "state": load.state, "podUrl": load.pod_url}}

# Roles & Staff
@app.get("/api/roles")
async def get_roles(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not user.org_id:
        raise HTTPException(status_code=400, detail="User has no organization")

    roles = db.query(Role).filter(Role.org_id == user.org_id).all()
    
    output = []
    for r in roles:
        output.append({
            "id": r.id,
            "name": r.name,
            "permissions": [{"key": p.key} for p in r.permissions],
            "_count": {"users": len(r.users)}
        })
    return {"roles": output}

@app.post("/api/roles", status_code=201)
async def create_role(
    req: CreateRoleRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not user.org_id:
        raise HTTPException(status_code=400, detail="User has no organization")

    enforce_permission(user, "staff.manage", "/api/roles (POST)", db)

    # Check if duplicate name
    existing = db.query(Role).filter(Role.org_id == user.org_id, Role.name == req.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="A role with this name already exists.")

    db_perms = db.query(Permission).filter(Permission.key.in_(req.permissionKeys)).all()
    if len(db_perms) != len(req.permissionKeys):
        raise HTTPException(status_code=400, detail="Some permission keys are invalid")

    role = Role(name=req.name, org_id=user.org_id)
    role.permissions.extend(db_perms)
    db.add(role)
    db.commit()

    return {"role": {"id": role.id, "name": role.name}}

@app.get("/api/staff")
async def get_staff(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not user.org_id:
        raise HTTPException(status_code=400, detail="User has no organization")

    staff = db.query(User).filter(User.org_id == user.org_id).all()
    output = []
    for s in staff:
        output.append({
            "id": s.id,
            "email": s.email,
            "accountType": s.account_type,
            "role": {
                "id": s.role.id,
                "name": s.role.name,
                "permissions": [{"key": p.key} for p in s.role.permissions]
            } if s.role else None
        })
    return {"staff": output}

@app.post("/api/staff", status_code=201)
async def create_staff(
    req: CreateStaffRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not user.org_id:
        raise HTTPException(status_code=400, detail="User has no organization")

    enforce_permission(user, "staff.manage", "/api/staff (POST)", db)

    # Check duplicate email
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="A user with this email already exists.")

    # Check role is valid for org
    role = db.query(Role).filter(Role.id == req.roleId, Role.org_id == user.org_id).first()
    if not role:
        raise HTTPException(status_code=400, detail="Invalid role ID selected")

    staff_type = "BROKER_STAFF" if user.org.type == "BROKER" else "CARRIER_STAFF"
    p_hash = hash_password(req.password)

    new_staff = User(
        email=req.email,
        password_hash=p_hash,
        account_type=staff_type,
        org_id=user.org_id,
        role_id=req.roleId
    )
    db.add(new_staff)
    db.commit()

    return {"staff": {"id": new_staff.id, "email": new_staff.email}}

# Compliance records
@app.get("/api/compliance")
async def get_compliance(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if user.account_type == "CARRIER_STAFF":
        if not user.org_id:
            raise HTTPException(status_code=400, detail="User lacks organization")
        record = db.query(CarrierComplianceRecord).filter(CarrierComplianceRecord.carrier_org_id == user.org_id).first()
        records = [record] if record else []
    elif user.account_type == "BROKER_STAFF":
        records = db.query(CarrierComplianceRecord).all()
    else:
        records = []

    output = []
    for r in records:
        output.append({
            "id": r.id,
            "carrierOrgId": r.carrier_org_id,
            "carrierOrg": {"name": r.carrier_org.name},
            "insuranceExpiryDate": r.insurance_expiry_date.isoformat() + "Z",
            "mcDotAuthorityStatus": r.mc_dot_authority_status,
            "approvedEquipmentTypes": r.approved_equipment_types,
            "approvedCommodityTypes": r.approved_commodity_types,
            "lastUpdatedAt": r.last_updated_at.isoformat() + "Z"
        })
    return {"records": output}

@app.post("/api/compliance")
async def update_compliance(
    req: UpdateComplianceRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if user.account_type != "CARRIER_STAFF" or not user.org_id:
        raise HTTPException(status_code=403, detail="Only carrier staff can update compliance record")

    enforce_permission(user, "staff.manage", "/api/compliance (POST)", db)

    # Parse date
    try:
        expiry_date = datetime.strptime(req.insuranceExpiryDate, "%Y-%m-%d")
    except ValueError:
        # Fallback to ISO format parsing if full timestamp sent
        expiry_date = datetime.fromisoformat(req.insuranceExpiryDate.replace("Z", ""))

    record = db.query(CarrierComplianceRecord).filter(CarrierComplianceRecord.carrier_org_id == user.org_id).first()
    if record:
        record.insurance_expiry_date = expiry_date
        record.mc_dot_authority_status = req.mcDotAuthorityStatus
        record.approved_equipment_types = json.dumps(req.approvedEquipmentTypes)
        record.approved_commodity_types = json.dumps(req.approvedCommodityTypes)
        record.last_updated_at = datetime.utcnow()
    else:
        record = CarrierComplianceRecord(
            carrier_org_id=user.org_id,
            insurance_expiry_date=expiry_date,
            mc_dot_authority_status=req.mcDotAuthorityStatus,
            approved_equipment_types=json.dumps(req.approvedEquipmentTypes),
            approved_commodity_types=json.dumps(req.approvedCommodityTypes)
        )
        db.add(record)

    db.commit()

    # Recheck active loads
    recheck_carrier_loads_compliance(user.org_id, db)

    return {"record": {"id": record.id}}

# Security log views
@app.get("/api/logs")
async def get_logs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    is_broker = user.account_type == "BROKER_STAFF"
    can_manage = has_permission(user, "staff.manage")
    can_override = has_permission(user, "load.override_compliance_flag")

    if not is_broker or (not can_manage and not can_override):
        raise HTTPException(status_code=403, detail="Forbidden: Insufficient log viewing permissions")

    access_logs = db.query(AccessLog).order_by(AccessLog.timestamp.desc()).limit(100).all()
    audit_logs = db.query(LoadStatusEvent).order_by(LoadStatusEvent.timestamp.desc()).limit(100).all()

    formatted_access = []
    for l in access_logs:
        formatted_access.append({
            "id": l.id,
            "userId": l.user_id,
            "userEmail": l.user_email,
            "orgId": l.org_id,
            "attemptedPermission": l.attempted_permission,
            "endpoint": l.endpoint,
            "timestamp": l.timestamp.isoformat() + "Z",
            "reason": l.reason
        })

    formatted_audit = []
    for a in audit_logs:
        formatted_audit.append({
            "id": a.id,
            "loadId": a.load_id,
            "load": {"requiredEquipmentType": a.load.required_equipment_type},
            "fromState": a.from_state,
            "toState": a.to_state,
            "changedByUser": {"email": a.changed_by_user.email},
            "timestamp": a.timestamp.isoformat() + "Z",
            "note": a.note
        })

    return {
        "accessLogs": formatted_access,
        "auditLogs": formatted_audit
    }

# SPA Mount Paths
@app.get("/")
@app.get("/dashboard")
async def serve_dashboard():
    return FileResponse("static/index.html")

# Serve visual artifacts locally
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
