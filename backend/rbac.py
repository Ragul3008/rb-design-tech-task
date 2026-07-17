from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from backend.models import User, AccessLog, Load
from datetime import datetime

# Defined permission keys catalog
PERMISSION_CATALOG = [
    "load.create",
    "load.assign_carrier",
    "load.override_compliance_flag",
    "rate.confirm",
    "load.update_status",
    "staff.manage",
    "pod.upload"
]

def has_permission(user: User | None, permission_key: str) -> bool:
    if not user:
        return False
    if user.account_type == "SHIPPER":
        return False  # Shippers have no permission catalog access

    if not user.role:
        return False
        
    return any(p.key == permission_key for p in user.role.permissions)

def enforce_permission(user: User | None, permission_key: str, endpoint: str, db: Session):
    if not user or not has_permission(user, permission_key):
        # Log access violation
        try:
            log = AccessLog(
                user_id=user.id if user else None,
                user_email=user.email if user else "anonymous",
                org_id=user.org_id if user else None,
                attempted_permission=permission_key,
                endpoint=endpoint,
                reason=user.account_type + " does not hold required permission." if user else "No session user."
            )
            db.add(log)
            db.commit()
            print(f"[SECURITY] Access Denied: User {user.email if user else 'anonymous'} attempted {permission_key} on {endpoint}")
        except Exception as e:
            print("Failed to write access log:", e)

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: Missing permission '{permission_key}'"
        )
    return True

def get_load_scope(user: User):
    if user.account_type == "SHIPPER":
        return Load.shipper_id == user.id
    elif user.account_type == "BROKER_STAFF":
        if not user.org_id:
            raise HTTPException(status_code=400, detail="Broker staff lacks associated organization")
        return Load.broker_org_id == user.org_id
    elif user.account_type == "CARRIER_STAFF":
        if not user.org_id:
            raise HTTPException(status_code=400, detail="Carrier staff lacks associated organization")
        return Load.assigned_carrier_org_id == user.org_id
    else:
        return Load.id == "none"
