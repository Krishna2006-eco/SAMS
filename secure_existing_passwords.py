"""
ONE-TIME SECURITY FIX SCRIPT
Run this ONCE on your laptop where your real study_tracker.db lives:

    python secure_existing_passwords.py

It converts every user's plain-text password into a secure hash.
Users keep the SAME password - they just can't be read by anyone anymore.
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from database import get_db_connection
from werkzeug.security import generate_password_hash


def main():
    conn = get_db_connection()
    users = conn.execute('SELECT id, username, password FROM users').fetchall()

    fixed = 0
    for user in users:
        stored = user['password']
        # Skip passwords that are already hashed
        if stored.startswith(('pbkdf2:', 'scrypt:')):
            continue
        conn.execute(
            'UPDATE users SET password = ? WHERE id = ?',
            (generate_password_hash(stored), user['id'])
        )
        fixed += 1
        print(f"Secured password for: {user['username']}")

    conn.commit()
    conn.close()
    print(f"\nDone! {fixed} password(s) secured. Everyone logs in with their same password as before.")


if __name__ == '__main__':
    main()
