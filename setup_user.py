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
    
    is_admin_input = input("Make this user admin? (y/n, default: y): ").strip().lower()
    is_admin = is_admin_input != 'n'  # default true
    
    try:
        with db.connect() as conn:
            user_id = auth.create_user(conn, email, password, is_admin=is_admin)
            conn.commit()
        admin_label = " (admin)" if is_admin else ""
        print(f"✓ User created: {email} (id: {user_id}){admin_label}")
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
