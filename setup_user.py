"""Setup script: create first user (email + password only)."""

import sys
from getpass import getpass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from digest import db, auth


def main():
    email = input("Email: ").strip()
    if not email:
        print("Email required.")
        return 1
    
    password = getpass("Password: ")
    if not password:
        print("Password required.")
        return 1
    
    confirm = getpass("Confirm password: ")
    if password != confirm:
        print("Passwords don't match.")
        return 1
    
    try:
        with db.connect() as conn:
            user_id = auth.create_user(conn, email, password)
            conn.commit()
        print(f"✓ User created: {email} (id: {user_id})")
        return 0
    except auth.AuthError as e:
        print(f"✗ {e}")
        return 1
    except db.DatabaseProblem as e:
        print(f"✗ Database error: {e}")
        return 1
    except Exception as e:
        import traceback
        print(f"✗ Error: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
