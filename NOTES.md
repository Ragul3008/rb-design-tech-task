# LoadFlow Developer & Architecture Notes

This document highlights the major modules, design architectures, and implementation details of the LoadFlow platform:

## Core Technical Architecture

1.  **Framework Bootstrap:**
    The application runs on a Python FastAPI backend served by Uvicorn. The SQLite database is managed using the SQLAlchemy ORM.
2.  **Database Design:**
    *   `backend/database.py`: Establishes the SQLAlchemy engine and thread-safe session local factory.
    *   `backend/models.py`: Defines schemas for Users, Organizations, Roles, Permissions, Carrier Compliance, Rate Confirmations, and Access Logs.
3.  **Authentication Layer:**
    *   `backend/auth.py`: Utilizes password hashing via `bcrypt` and session tokens signed via HS256 JWT cookies using `pyjwt`.
4.  **Role-Based Access Control (RBAC):**
    *   `backend/rbac.py`: Implements custom query boundaries so users only see loads they own or are assigned to, and intercepts unauthorized API transactions to write to the database-backed `AccessLog` table.
5.  **Compliance Engine:**
    *   `backend/compliance.py`: Automatically computes compliance flags on carrier assignments, checking for lapsed insurance policies, inactive MC/DOT authority, and compatible equipment/commodity arrays.
6.  **Interactive Walkthrough & Tests:**
    *   `scripts/verify_rbac.py` serves as the integration test suite, validating API gatekeepers and sequential status transitions.
