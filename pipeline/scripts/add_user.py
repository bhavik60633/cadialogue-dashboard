#!/usr/bin/env python3
"""
Bootstrap: add users to pipeline/state/users.json.

Usage:
    python -m pipeline.scripts.add_user owner@cadialogue.in \\
        --password=StrongPass123 --name="Site Owner" --role=admin

    python -m pipeline.scripts.add_user editor@cadialogue.in \\
        --password=EditorPass --name="Team Editor"
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import bcrypt  # type: ignore
except ImportError:
    print("ERROR: bcrypt not installed.  Run:  pip install bcrypt")
    sys.exit(1)

USERS_FILE = Path(__file__).parent.parent / "state" / "users.json"


def _load() -> list:
    if not USERS_FILE.exists():
        return []
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save(users: list) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(
        json.dumps(users, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add a user to the CADialogue dashboard"
    )
    parser.add_argument("email", help="User email address")
    parser.add_argument("--password", required=True, help="Plain-text password (hashed before storage)")
    parser.add_argument("--name", default="", help="Display name (defaults to email prefix)")
    parser.add_argument(
        "--role",
        default="editor",
        choices=["editor", "admin"],
        help="User role (default: editor)",
    )
    args = parser.parse_args()

    users = _load()

    hashed = bcrypt.hashpw(
        args.password.encode("utf-8"), bcrypt.gensalt(rounds=10)
    ).decode("utf-8")

    existing_user = next((u for u in users if u.get("email") == args.email), None)

    if existing_user:
        existing_user["bcrypt_hash"] = hashed
        existing_user["name"] = args.name or args.email.split("@")[0]
        existing_user["role"] = args.role
        print(f"[OK] User '{args.email}' updated (role: {args.role})")
    else:
        user = {
            "email": args.email,
            "name": args.name or args.email.split("@")[0],
            "bcrypt_hash": hashed,
            "role": args.role,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        users.append(user)
        print(f"[OK] User '{args.email}' added (role: {args.role})")

    _save(users)
    final_user = existing_user if existing_user else user
    print(f"   Name : {final_user['name']}")
    print(f"   Hash : {hashed[:30]}...")
    print(f"\nLogin at: http://localhost:3000/login")


if __name__ == "__main__":
    main()
