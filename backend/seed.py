import bcrypt
from datetime import datetime, timedelta
import json
from backend.database import engine, SessionLocal, Base
from backend.models import Permission, User, Org, Role, CarrierComplianceRecord, Load, LoadStatusEvent, RateConfirmation

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def seed_db():
    print("Resetting database...")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        print("Seeding permissions...")
        permission_keys = [
            "load.create",
            "load.assign_carrier",
            "load.override_compliance_flag",
            "rate.confirm",
            "load.update_status",
            "staff.manage",
            "pod.upload",
        ]

        db_permissions = {}
        for key in permission_keys:
            perm = Permission(key=key)
            db.add(perm)
            db_permissions[key] = perm
        db.commit()

        # Generate standard password hash
        password_hash = hash_password("Password123")

        print("Seeding Shippers...")
        shipper = User(
            email="shipper@shipper.com",
            password_hash=password_hash,
            account_type="SHIPPER"
        )
        db.add(shipper)
        db.commit()

        print("Seeding Broker Org & Roles...")
        broker_org = Org(name="Apex Logistics", type="BROKER")
        db.add(broker_org)
        db.commit()

        broker_admin_role = Role(org_id=broker_org.id, name="Admin")
        broker_admin_role.permissions.extend(list(db_permissions.values()))

        broker_dispatcher_role = Role(org_id=broker_org.id, name="Dispatcher")
        broker_dispatcher_role.permissions.extend([
            db_permissions["load.assign_carrier"],
            db_permissions["rate.confirm"]
        ])

        broker_ops_lead_role = Role(org_id=broker_org.id, name="Ops Lead")
        broker_ops_lead_role.permissions.extend([
            db_permissions["load.assign_carrier"],
            db_permissions["rate.confirm"],
            db_permissions["load.override_compliance_flag"],
            db_permissions["load.update_status"]
        ])

        db.add_all([broker_admin_role, broker_dispatcher_role, broker_ops_lead_role])
        db.commit()

        print("Seeding Broker Staff Users...")
        broker_admin = User(
            email="admin@broker.com",
            password_hash=password_hash,
            account_type="BROKER_STAFF",
            org_id=broker_org.id,
            role_id=broker_admin_role.id
        )
        broker_dispatcher = User(
            email="dispatcher@broker.com",
            password_hash=password_hash,
            account_type="BROKER_STAFF",
            org_id=broker_org.id,
            role_id=broker_dispatcher_role.id
        )
        broker_ops_lead = User(
            email="opslead@broker.com",
            password_hash=password_hash,
            account_type="BROKER_STAFF",
            org_id=broker_org.id,
            role_id=broker_ops_lead_role.id
        )
        db.add_all([broker_admin, broker_dispatcher, broker_ops_lead])
        db.commit()

        print("Seeding Carrier Orgs & Roles...")
        carrier_org1 = Org(name="Falcon Express", type="CARRIER")
        carrier_org2 = Org(name="Red Flag Trucking", type="CARRIER")
        db.add_all([carrier_org1, carrier_org2])
        db.commit()

        # Falcon Roles
        falcon_admin_role = Role(org_id=carrier_org1.id, name="Admin")
        falcon_admin_role.permissions.extend([
            db_permissions["load.update_status"],
            db_permissions["pod.upload"],
            db_permissions["staff.manage"]
        ])

        falcon_driver_role = Role(org_id=carrier_org1.id, name="Driver")
        falcon_driver_role.permissions.extend([
            db_permissions["load.update_status"],
            db_permissions["pod.upload"]
        ])

        falcon_dispatch_role = Role(org_id=carrier_org1.id, name="Carrier Dispatch")
        falcon_dispatch_role.permissions.extend([
            db_permissions["load.update_status"]
        ])

        # Red Flag Roles
        red_admin_role = Role(org_id=carrier_org2.id, name="Admin")
        red_admin_role.permissions.extend([
            db_permissions["load.update_status"],
            db_permissions["pod.upload"],
            db_permissions["staff.manage"]
        ])

        red_driver_role = Role(org_id=carrier_org2.id, name="Driver")
        red_driver_role.permissions.extend([
            db_permissions["load.update_status"],
            db_permissions["pod.upload"]
        ])

        db.add_all([falcon_admin_role, falcon_driver_role, falcon_dispatch_role, red_admin_role, red_driver_role])
        db.commit()

        print("Seeding Carrier Staff Users...")
        carrier_admin = User(
            email="admin@carrier.com",
            password_hash=password_hash,
            account_type="CARRIER_STAFF",
            org_id=carrier_org1.id,
            role_id=falcon_admin_role.id
        )
        carrier_driver = User(
            email="driver@carrier.com",
            password_hash=password_hash,
            account_type="CARRIER_STAFF",
            org_id=carrier_org1.id,
            role_id=falcon_driver_role.id
        )
        carrier_dispatch = User(
            email="dispatch@carrier.com",
            password_hash=password_hash,
            account_type="CARRIER_STAFF",
            org_id=carrier_org1.id,
            role_id=falcon_dispatch_role.id
        )
        red_admin = User(
            email="redadmin@carrier.com",
            password_hash=password_hash,
            account_type="CARRIER_STAFF",
            org_id=carrier_org2.id,
            role_id=red_admin_role.id
        )
        red_driver = User(
            email="reddriver@carrier.com",
            password_hash=password_hash,
            account_type="CARRIER_STAFF",
            org_id=carrier_org2.id,
            role_id=red_driver_role.id
        )
        db.add_all([carrier_admin, carrier_driver, carrier_dispatch, red_admin, red_driver])
        db.commit()

        print("Seeding Carrier Compliance Records...")
        one_year_future = datetime.utcnow() + timedelta(days=365)
        ten_days_past = datetime.utcnow() - timedelta(days=10)

        compliance1 = CarrierComplianceRecord(
            carrier_org_id=carrier_org1.id,
            insurance_expiry_date=one_year_future,
            mc_dot_authority_status="ACTIVE",
            approved_equipment_types=json.dumps(["Flatbed", "Dry Van", "Reefer"]),
            approved_commodity_types=json.dumps(["Produce", "Electronics", "General Freight"])
        )

        compliance2 = CarrierComplianceRecord(
            carrier_org_id=carrier_org2.id,
            insurance_expiry_date=ten_days_past,
            mc_dot_authority_status="INACTIVE",
            approved_equipment_types=json.dumps(["Dry Van"]),
            approved_commodity_types=json.dumps(["General Freight"])
        )

        db.add_all([compliance1, compliance2])
        db.commit()

        print("Seeding Loads...")
        # Load 1: Posted
        load1 = Load(
            shipper_id=shipper.id,
            broker_org_id=broker_org.id,
            state="POSTED",
            required_equipment_type="Flatbed",
            required_commodity_type="Produce"
        )
        db.add(load1)
        db.commit()

        evt1 = LoadStatusEvent(
            load_id=load1.id,
            from_state=None,
            to_state="POSTED",
            changed_by_user_id=broker_admin.id,
            note="Load created and posted."
        )
        db.add(evt1)

        # Load 2: Carrier Assigned (Compliant carrier)
        load2 = Load(
            shipper_id=shipper.id,
            broker_org_id=broker_org.id,
            assigned_carrier_org_id=carrier_org1.id,
            state="CARRIER_ASSIGNED",
            required_equipment_type="Flatbed",
            required_commodity_type="Produce",
            compliance_flag=False
        )
        db.add(load2)
        db.commit()

        evt2 = LoadStatusEvent(
            load_id=load2.id,
            from_state="POSTED",
            to_state="CARRIER_ASSIGNED",
            changed_by_user_id=broker_dispatcher.id,
            note="Assigned to compliant carrier Falcon Express."
        )
        db.add(evt2)

        # Load 3: Carrier Assigned (Non-compliant carrier) -> Auto-flagged!
        load3 = Load(
            shipper_id=shipper.id,
            broker_org_id=broker_org.id,
            assigned_carrier_org_id=carrier_org2.id,
            state="CARRIER_ASSIGNED",
            required_equipment_type="Flatbed",
            required_commodity_type="Produce",
            compliance_flag=True,
            compliance_reason="Expired carrier insurance. MC/DOT authority status is inactive (INACTIVE). Carrier not approved for equipment type: 'Flatbed'. Carrier not approved for commodity type: 'Produce'."
        )
        db.add(load3)
        db.commit()

        evt3 = LoadStatusEvent(
            load_id=load3.id,
            from_state="POSTED",
            to_state="CARRIER_ASSIGNED",
            changed_by_user_id=broker_dispatcher.id,
            note="Assigned to non-compliant carrier Red Flag Trucking. Auto-flagged for compliance issues."
        )
        db.add(evt3)

        # Load 4: Rate Confirmed
        load4 = Load(
            shipper_id=shipper.id,
            broker_org_id=broker_org.id,
            assigned_carrier_org_id=carrier_org1.id,
            state="RATE_CONFIRMED",
            required_equipment_type="Dry Van",
            required_commodity_type="Electronics"
        )
        db.add(load4)
        db.commit()

        rate_conf = RateConfirmation(
            load_id=load4.id,
            version=1,
            base_rate=1500.0,
            accessorials=json.dumps([{"type": "Fuel Surcharge", "amount": 150.0}]),
            confirmed_by_user_id=broker_dispatcher.id
        )
        db.add(rate_conf)
        db.commit()

        load4.current_rate_confirmation_id = rate_conf.id
        db.commit()

        evt4_1 = LoadStatusEvent(
            load_id=load4.id,
            from_state="POSTED",
            to_state="CARRIER_ASSIGNED",
            changed_by_user_id=broker_dispatcher.id,
            note="Assigned to Falcon Express."
        )
        evt4_2 = LoadStatusEvent(
            load_id=load4.id,
            from_state="CARRIER_ASSIGNED",
            to_state="RATE_CONFIRMED",
            changed_by_user_id=broker_dispatcher.id,
            note="Rate confirmed. Version: 1, Base Rate: $1500.0."
        )
        db.add_all([evt4_1, evt4_2])
        db.commit()

        print("Seeding complete successfully!")
    finally:
        db.close()

if __name__ == "__main__":
    seed_db()
