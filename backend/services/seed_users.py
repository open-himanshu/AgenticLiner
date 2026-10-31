"""
User Seed Script for AgenticLiner.
Creates exactly ONE account per role (supervisor, organiser, data_manager, participant).
Contains NO business demo data.
"""

import sys
import os
import secrets

# Ensure root directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.core.database.connection import get_connection
from backend.services.auth_service import hash_password

SEEDED_ACCOUNTS = [
    {
        "id": "usr_supervisor_01",
        "username": "admin",
        "email": "admin@galgotias.edu",
        "password_env": "SUPERVISOR_PASSWORD",
        "role": "supervisor",
        "full_name": "University Supervisor (Dean Office)"
    },
    {
        "id": "usr_organiser_01",
        "username": "organiser",
        "email": "organiser@galgotias.edu",
        "password_env": "ORGANISER_PASSWORD",
        "role": "organiser",
        "full_name": "Student Club Organiser"
    },
    {
        "id": "usr_data_mgr_01",
        "username": "datamanager",
        "email": "datamanager@galgotias.edu",
        "password_env": "DATA_MANAGER_PASSWORD",
        "role": "data_manager",
        "full_name": "Campus Data Operations Manager"
    },
    {
        "id": "usr_participant_01",
        "username": "student",
        "email": "student@galgotias.edu",
        "password_env": "PARTICIPANT_PASSWORD",
        "role": "participant",
        "full_name": "Student Attendee"
    }
]

_CACHED_HASHES = {}
_GENERATED_PASSWORDS = {}
_PRINTED_CREDENTIALS = set()

def get_cached_hash(password: str) -> str:
    if password not in _CACHED_HASHES:
        _CACHED_HASHES[password] = hash_password(password)
    return _CACHED_HASHES[password]

def seed_users(force: bool = False):
    with get_connection() as conn:
        cur = conn.cursor()
        if force:
            cur.execute("DELETE FROM users")

        inserted = 0
        for acc in SEEDED_ACCOUNTS:
            password = os.getenv(acc["password_env"])
            generated_password = not password
            if generated_password:
                if acc["role"] not in _GENERATED_PASSWORDS:
                    _GENERATED_PASSWORDS[acc["role"]] = secrets.token_urlsafe(18)
                password = _GENERATED_PASSWORDS[acc["role"]]
            cur.execute("SELECT id FROM users WHERE LOWER(email) = LOWER(?)", (acc["email"],))
            existing = cur.fetchone()
            if not existing:
                p_hash = get_cached_hash(password)
                cur.execute(
                    "INSERT INTO users (id, username, email, password_hash, role, full_name) VALUES (?, ?, ?, ?, ?, ?)",
                    (acc["id"], acc["username"], acc["email"], p_hash, acc["role"], acc["full_name"])
                )
                inserted += 1
                if generated_password and acc["role"] not in _PRINTED_CREDENTIALS:
                    print(
                        f"Generated seed password for {acc['role']} "
                        f"({acc['email']}): {password}"
                    )
                    _PRINTED_CREDENTIALS.add(acc["role"])

        conn.commit()
        print(f"Seed complete. {inserted} user accounts created.")

if __name__ == "__main__":
    force_flag = "--force" in sys.argv
    seed_users(force=force_flag)
