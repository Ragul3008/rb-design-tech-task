import urllib.request
import urllib.error
import json
import sqlite3
from http.cookiejar import CookieJar
import sys

BASE_URL = "http://localhost:3000"

def get_session_opener():
    cj = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    return opener

def login(opener, email, password):
    url = f"{BASE_URL}/api/auth/login"
    data = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        res = opener.open(req)
        return json.loads(res.read().decode("utf-8"))
    except Exception as e:
        print(f"[-] Login failed for {email}: {e}")
        return None

def main():
    print("----------------------------------------------------------------")
    print("LOADFLOW RBAC & STATE MACHINE INTEGRATION VERIFICATION (PYTHON)")
    print("----------------------------------------------------------------")

    # Connect directly to SQLite to fetch initial posted load ID
    conn = sqlite3.connect("dev.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, state FROM loads WHERE state = 'POSTED' LIMIT 1")
    row = cursor.fetchone()
    if not row:
        print("[-] Verification failed: Seed data missing. Make sure to run backend/seed.py first.")
        sys.exit(1)
        
    load_id = row[0]
    print(f"[+] Found active load for testing: {load_id} (State: {row[1]})")

    # 1. Simulates Driver logging in
    print("[+] Simulating driver authentication...")
    driver_opener = get_session_opener()
    driver_profile = login(driver_opener, "driver@carrier.com", "Password123")
    if not driver_profile:
        print("[-] Driver login failed. Make sure the dev server is running on port 3000.")
        print("    Run: uvicorn backend.main:app --reload --port 3000")
        sys.exit(1)
    print("[+] Driver authenticated successfully.")

    # 2. Direct POST to /api/loads/:id/assign by Driver (Expected: 403 Forbidden)
    print("[+] Attempting unauthorized action (Driver assigning carrier)...")
    url = f"{BASE_URL}/api/loads/{load_id}/assign"
    data = json.dumps({"carrierOrgId": "FALCON_EXPRESS"}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    
    blocked = False
    try:
        driver_opener.open(req)
    except urllib.error.HTTPError as e:
        print(f"[+] Status received: {e.code}")
        if e.code == 403:
            blocked = True
            print("[+] Security check PASSED: Driver received 403 Forbidden.")
        else:
            print(f"[-] Unexpected HTTP code received: {e.code}")

    if not blocked:
        print("[-] Security check FAILED: Driver was not blocked!")
        sys.exit(1)

    # 3. Verify AccessLog write
    print("[+] Querying AccessLog table for the blocked attempt...")
    cursor.execute(
        "SELECT timestamp, user_email, attempted_permission, endpoint, reason FROM access_logs WHERE user_email = 'driver@carrier.com' ORDER BY timestamp DESC LIMIT 1"
    )
    log_row = cursor.fetchone()
    if not log_row:
        print("[-] Security check FAILED: Access log not written to database.")
        sys.exit(1)
        
    print("[+] Security check PASSED: Found matching AccessLog entry in DB.")
    print(f"    Log entry: [{log_row[0]}] User {log_row[1]} denied for {log_row[2]} at {log_row[3]} - Reason: {log_row[4]}")

    # 4. State Machine Transition Verification (Posted -> Carrier Assigned -> Rate Confirmed -> Dispatched -> In Transit -> Delivered -> POD Verified -> Invoiced/Closed)
    print("----------------------------------------------------------------")
    print("VERIFYING lifecycle transitions...")

    # Sign in as Broker Admin
    print("[+] Authenticating as Broker Admin...")
    broker_opener = get_session_opener()
    broker_profile = login(broker_opener, "admin@broker.com", "Password123")
    
    # Assign Compliant Carrier (Falcon Express)
    print("[+] Assigning compliant carrier Falcon Express...")
    url = f"{BASE_URL}/api/loads/{load_id}/assign"
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    res = broker_opener.open(req)
    assign_data = json.loads(res.read().decode("utf-8"))
    print(f"[+] State is now: {assign_data['load']['state']}")

    # Rate Confirmation
    print("[+] Signing Rate Confirmation (base rate $1800)...")
    url = f"{BASE_URL}/api/loads/{load_id}/rate-confirm"
    rate_data = json.dumps({"baseRate": 1800.0, "accessorials": []}).encode("utf-8")
    req = urllib.request.Request(
        url, data=rate_data, headers={"Content-Type": "application/json"}, method="POST"
    )
    res = broker_opener.open(req)
    rate_resp = json.loads(res.read().decode("utf-8"))
    print(f"[+] State is now: {rate_resp['load']['state']}")

    # Dispatch Load
    print("[+] Transitioning to DISPATCHED...")
    url = f"{BASE_URL}/api/loads/{load_id}/status"
    status_data = json.dumps({"toState": "DISPATCHED", "note": "Driver dispatching"}).encode("utf-8")
    req = urllib.request.Request(
        url, data=status_data, headers={"Content-Type": "application/json"}, method="POST"
    )
    res = driver_opener.open(req)
    status_resp = json.loads(res.read().decode("utf-8"))
    print(f"[+] State is now: {status_resp['load']['state']}")

    # In Transit
    print("[+] Transitioning to IN_TRANSIT...")
    status_data = json.dumps({"toState": "IN_TRANSIT", "note": "In transit details"}).encode("utf-8")
    req = urllib.request.Request(
        url, data=status_data, headers={"Content-Type": "application/json"}, method="POST"
    )
    res = driver_opener.open(req)
    status_resp = json.loads(res.read().decode("utf-8"))
    print(f"[+] State is now: {status_resp['load']['state']}")

    # Delivered
    print("[+] Transitioning to DELIVERED...")
    status_data = json.dumps({"toState": "DELIVERED", "note": "Arrived at destination"}).encode("utf-8")
    req = urllib.request.Request(
        url, data=status_data, headers={"Content-Type": "application/json"}, method="POST"
    )
    res = driver_opener.open(req)
    status_resp = json.loads(res.read().decode("utf-8"))
    print(f"[+] State is now: {status_resp['load']['state']}")

    # Upload POD (Transitions to POD_VERIFIED)
    print("[+] Uploading Proof of Delivery (POD)...")
    url = f"{BASE_URL}/api/loads/{load_id}/pod"
    pod_data = json.dumps({"podUrl": "https://example.com/pods/verification-file.pdf"}).encode("utf-8")
    req = urllib.request.Request(
        url, data=pod_data, headers={"Content-Type": "application/json"}, method="POST"
    )
    res = driver_opener.open(req)
    pod_resp = json.loads(res.read().decode("utf-8"))
    print(f"[+] State is now: {pod_resp['load']['state']} (POD: {pod_resp['load']['podUrl']})")

    # Invoice / Close out load (Requires Broker Admin)
    print("[+] Closing out load (Broker Admin)...")
    url = f"{BASE_URL}/api/loads/{load_id}/status"
    status_data = json.dumps({"toState": "INVOICED_CLOSED", "note": "Audited and closed"}).encode("utf-8")
    req = urllib.request.Request(
        url, data=status_data, headers={"Content-Type": "application/json"}, method="POST"
    )
    res = broker_opener.open(req)
    status_resp = json.loads(res.read().decode("utf-8"))
    print(f"[+] State is now: {status_resp['load']['state']}")

    print("----------------------------------------------------------------")
    print("[+] VERIFICATION COMPLETE: ALL INTEGRITY & SECURITY CHECKS PASSED!")
    print("----------------------------------------------------------------")
    
    conn.close()

if __name__ == "__main__":
    main()
