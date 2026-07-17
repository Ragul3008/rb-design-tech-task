from datetime import datetime
import json
from sqlalchemy.orm import Session
from backend.models import CarrierComplianceRecord, Load, LoadStatusEvent, User

def check_carrier_compliance(
    carrier_org_id: str,
    required_equipment: str,
    required_commodity: str,
    db: Session
) -> tuple[bool, str | None]:
    try:
        record = db.query(CarrierComplianceRecord).filter(
            CarrierComplianceRecord.carrier_org_id == carrier_org_id
        ).first()

        if not record:
            return False, "No compliance record found for the assigned carrier."

        reasons = []
        now = datetime.utcnow()

        # 1. Insurance check
        if record.insurance_expiry_date < now:
            reasons.push("Expired carrier insurance.") if hasattr(reasons, 'push') else reasons.append("Expired carrier insurance.")

        # 2. Authority status check
        if record.mc_dot_authority_status != "ACTIVE":
            reasons.append(f"MC/DOT authority status is inactive ({record.mc_dot_authority_status}).")

        # 3. Equipment check
        try:
            approved_equipments = json.loads(record.approved_equipment_types)
        except Exception:
            approved_equipments = []
        if required_equipment not in approved_equipments:
            reasons.append(f"Carrier not approved for equipment type: '{required_equipment}'.")

        # 4. Commodity check
        try:
            approved_commodities = json.loads(record.approved_commodity_types)
        except Exception:
            approved_commodities = []
        if required_commodity not in approved_commodities:
            reasons.append(f"Carrier not approved for commodity type: '{required_commodity}'.")

        if reasons:
            return False, " ".join(reasons)

        return True, None
    except Exception as e:
        return False, f"System compliance check error: {str(e)}"

def recheck_carrier_loads_compliance(carrier_org_id: str, db: Session):
    active_loads = db.query(Load).filter(
        Load.assigned_carrier_org_id == carrier_org_id,
        Load.state.in_(["CARRIER_ASSIGNED", "RATE_CONFIRMED"])
    ).all()

    # Get a broker admin user to attribute system logs
    system_user = db.query(User).filter(User.account_type == "BROKER_STAFF").first()
    system_user_id = system_user.id if system_user else None

    for load in active_loads:
        compliant, reason = check_carrier_compliance(
            carrier_org_id,
            load.required_equipment_type,
            load.required_commodity_type,
            db
        )

        old_flag = load.compliance_flag
        new_flag = not compliant

        load.compliance_flag = new_flag
        load.compliance_reason = reason

        db.commit()

        if old_flag != new_flag and system_user_id:
            evt = LoadStatusEvent(
                load_id=load.id,
                from_state=load.state,
                to_state=load.state,
                changed_by_user_id=system_user_id,
                note=f"Compliance auto-check updated. Flagged: {new_flag}. Reason: {reason or 'Compliant'}"
            )
            db.add(evt)
            db.commit()
