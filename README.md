# LoadFlow — Freight Brokerage Operations Suite (Python Edition)

LoadFlow is a robust, secure freight brokerage operations platform designed to connect Shippers, Brokers, and Carriers while strictly enforcing Role-Based Access Control (RBAC), multi-tenant organization boundaries, and cargo compliance requirements.

## Stack Choice & One-Line Reason
*   **Tech Stack:** Python FastAPI & SQLAlchemy ORM with a unified Single Page Application (Tailwind CSS + vanilla JS) served directly via Uvicorn.
*   **One-Line Reason:** Lightweight, robust Python-based API server with zero npm compilation dependencies, making it extremely easy to read, modify, and deploy for Python developers.

---

## Getting Started & Local Setup

To set up the database and run the server locally, follow these steps:

1.  **Install Dependencies:**
    Make sure you have Python 3.10+ installed, then run:
    ```bash
    pip install -r requirements.txt
    ```
2.  **Seed mock data:**
    Resets the SQLite database (`dev.db`) and seeds standard organizations, roles, permissions, compliance certificates, and initial loads:
    ```bash
    python -m backend.seed
    ```
3.  **Start Development Server:**
    Launches Uvicorn on port 3000 to host both the API endpoints and the dashboard frontend:
    ```bash
    python -m uvicorn backend.main:app --reload --port 3000
    ```
4.  **Access App:**
    Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## Seed Accounts (Quick Sandbox Logins)

The login screen features **Quick Login Profile Buttons** to pre-fill and submit login credentials instantly. You can also log in manually using:

*   **Broker Admin:** `admin@broker.com` / `Password123`
*   **Broker Dispatcher:** `dispatcher@broker.com` / `Password123`
*   **Broker Ops Lead:** `opslead@broker.com` / `Password123`
*   **Carrier Admin:** `admin@carrier.com` / `Password123`
*   **Carrier Driver:** `driver@carrier.com` / `Password123`
*   **Carrier Dispatcher:** `dispatch@carrier.com` / `Password123`
*   **Shipper:** `shipper@shipper.com` / `Password123`
*   **Non-Compliant Carrier Admin:** `redadmin@carrier.com` / `Password123`
*   **Non-Compliant Carrier Driver:** `reddriver@carrier.com` / `Password123`

---

## How to Verify RBAC & Multi-Tenant Containment

Our security architecture enforces two distinct boundaries on the server-side (re-checked on every API transaction):

### 1. Verification Script (Automated Test)
We have a comprehensive verification script that validates security blocks and lifecycle sequencing automatically:
```bash
python scripts/verify_rbac.py
```
**This script tests:**
1.  Driver login simulation.
2.  Direct posting to `POST /api/loads/[LOAD-UUID]/assign` using Driver credentials (expects `403 Forbidden`).
3.  Verification that the `AccessLog` table contains the logged security violation.
4.  Standard lifecycle transition sequencing from `POSTED` up to `INVOICED_CLOSED` using authorized roles.

### 2. Manual Verification Walkthrough
1.  Log in as **Carrier Driver** (`driver@carrier.com` / `Password123`).
2.  Attempt to assign a carrier or override compliance via raw HTTP tools or curl directly:
    ```bash
    curl -X POST http://localhost:3000/api/loads/[LOAD-UUID]/assign \
      -H "Content-Type: application/json" \
      -d '{"carrierOrgId":"RED_FLAG"}'
    ```
3.  Observe that the server returns a `403 Forbidden` response.
4.  Log in as **Broker Admin** (`admin@broker.com` / `Password123`) and click on the **Security Logs** tab. You will see the blocked attempt listed in the **Security Access Violation Log** table with a full audit log detailing who, when, and what permission was missing.

---

## Key Core Features Built

1.  **Custom Session Auth:** Secure session cookies signed with HS256 JWT using `pyjwt`.
2.  **Admin Role Builder & Staff Assign:** Administrators can dynamically compile checkbox permissions into custom roles and assign them to staff.
3.  **Automated Compliance Engine:** Triggers compliance auto-flagging upon carrier assignment checking:
    *   Lapsed insurance policies (`insurance_expiry_date < now`).
    *   Inactive/suspended regulatory authorities (`mc_dot_authority_status !== 'ACTIVE'`).
    *   Equipment / commodity compatibility checking.
4.  **Bypass Justification Audits:** Compliance flags block transitions past `CARRIER_ASSIGNED` unless manual override is executed by an authorized user (Ops Lead), writing justification notes to the database audit trail.
5.  **State Machine Sequence Gating:** Restricts status updates to sequential progression (`Posted` → `Assigned` → `Rate Confirmed` → `Dispatched` → `In Transit` → `Delivered` → `POD Verified` → `Closed`).
6.  **Interactive Dashboards:** Cohesive dark-mode UI with cards, status badges, log tables, forms, and alerts.
